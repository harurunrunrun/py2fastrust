"""Indexed stores for closed builtin list/non-list receiver alternatives.

The captured receiver and index keep their original value identities. Each
mutable arm retains its actual uniform list element ABI; immutable arms report
Python's assignment error after target operand evaluation.
"""
from .native_types import alternatives

TARGETS = frozenset({'list', 'tuple', 'tuple_sequence', 'str', 'bytes',
                     'int', 'bool', 'int_bool', 'float', 'none'})
INDICES = TARGETS | frozenset({'function','range'})


def supported(owner, index):
    from .native_classes import domain
    from .native_unions import union_kind
    return ((union_kind(owner)or union_kind(index)or index not in {'int','bool','int_bool'})
            and any(domain(kind) == 'list' for kind in alternatives(owner))
            and all(domain(kind) in TARGETS for kind in alternatives(owner))
            and index is not None
            and all(domain(kind) in INDICES for kind in alternatives(index)))


def analyze(model, plan, node, owner, index, value):
    from .native_classes import shape
    from .native_union_sequences import branches, INTEGRAL
    index_kind = shape(index)
    if not supported(shape(owner), index_kind if index_kind is not None else 'int'):
        return False
    if index_kind is None and model.final:
        return False
    # Store constraints belong to every feasible mutable receiver allocation.
    # They do not certify that this particular execution chooses that arm.
    if index_kind is None or any(kind in INTEGRAL for kind in alternatives(index_kind)):
        from .native_list_positions import store
        for member in branches(owner):
            if member.tag == 'list':
                model.contribute(member.args[0], value, node)
                store(model, member, node.slice, value, node)
    # The read cell retained by an augmented assignment includes immutable
    # receiver read results too. Its destination is a different ABI: a mutable
    # list element. Never overwrite/unify that old read cell with this view.
    result = model.cell(plan, node, identity='finite_list_write_destination')
    for member in branches(owner):
        if member.tag == 'list':
            if not model.namespace.contribute(result, member.args[0], node, force=True):
                model.contribute(result, member.args[0], node)
    model.remember(plan, node, result)
    return True


def requires_frames(unit, analysis):
    """Select builtin alternative storage before emission, without a retry."""
    import ast
    from .native_constraints import Allocation, TupleValue
    from .native_positional_selection import Provenance
    from .native_classes import domain
    flow = Provenance(analysis.heap)
    targets = [node for node in ast.walk(unit.tree)
               if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
               and not isinstance(node.slice, ast.Slice)]
    for facts in analysis.scopes.values():
        for node in targets:
            if supported(facts.expressions.get(unit.ordinal(node.value)),
                         facts.expressions.get(unit.ordinal(node.slice))):
                return True
            # Mutation can leave the coarse element kind unresolved before
            # this capability is selected. Canonical solved allocation/atom
            # alternatives suffice to choose analysis, never to certify a
            # storage ABI or operation. The typed model still solves both.
            index = facts.expressions.get(unit.ordinal(node.slice))
            from .native_constraints import IteratorValue
            index_value=facts.values.get(unit.ordinal(node.slice))
            iterable_index=(index is None and index_value is not None
                and not index_value.unknown and not index_value.unbound
                and any(isinstance(value,IteratorValue)for value in index_value.alternatives))
            if not iterable_index and(index is None or any(domain(kind) not in INDICES for kind in alternatives(index))):
                continue
            members = flow.resolve(facts.values.get(unit.ordinal(node.value)))
            if not members:
                continue
            lists = [member for member in members if isinstance(member, Allocation) and member.category == 'list']
            other = [member for member in members if member not in lists]
            if lists and not other and(iterable_index or any(kind not in {'int','bool','int_bool'}for kind in alternatives(index))):
                return True
            if lists and other and all(
                    isinstance(member, str) and member in TARGETS - {'list', 'tuple', 'tuple_sequence'}
                    or isinstance(member, TupleValue)
                    or isinstance(member, Allocation) and member.category == 'tuple_sequence'
                    for member in other):
                return True
    return False


def emit(emitter, node, owner, index, value):
    from .native_classes import Expression, domain
    from .native_unions import project, union_kind
    from .native_class_builtins import _error, _type_name
    from .native_union_sequences import INTEGRAL
    if union_kind(owner.kind):
        return Expression(project(owner.kind, owner.code, lambda kind, code:
            emit(emitter, node, Expression('(' + code + ').clone()', kind), index, value).code), 'none')
    if domain(owner.kind) != 'list':
        return _error(emitter, node, 'none',
            'format!("TypeError: \'{}\' object does not support item assignment",'
            + _type_name(emitter, owner, node) + ')')
    if union_kind(index.kind):
        return Expression(project(index.kind, index.code, lambda kind, code:
            emit(emitter, node, owner, Expression('(' + code + ').clone()', kind), value).code), 'none')
    if domain(index.kind) not in INTEGRAL:
        return _error(emitter, node, 'none',
            'format!("TypeError: list indices must be integers or slices, not {}",'
            + _type_name(emitter, index, node) + ')')
    code = 'class_list_set(&' + owner.code + ',&(' + emitter.number(index) + '),'
    code += emitter.coerce(value, owner.kind.element, node) + ')'
    return Expression(emitter.at(code, node), 'none')
