"""Tracked source writes of registered unpack/comprehension pull phases.

These compiler facts do not execute, shorten or replace an iterator. Native
cursor changes and parse errors stay in the existing ordered consumer. Every
unclosed source/native callback role invalidates the incoming witnesses.
"""
import ast
from dataclasses import dataclass, field


@dataclass
class PullEffect:
    closed: bool = True
    writes: set = field(default_factory=set)
    calls: list = field(default_factory=list)

    def add(self, other):
        self.closed &= other.closed
        self.writes.update(other.writes)
        self.calls.extend(other.calls)
        return self


def unknown(state):
    return PullEffect(False, set(state.slots))


def _source_children(state, plan, node, include_source):
    from .native_call_context_effects import source_plan
    indices = set(state.model.call_edges_by_site.get((plan.index, id(node)), ()))
    if any(index not in state.plans or source_plan(state.plans[index]) is None for index in indices):
        return None, unknown(state)
    writes = set()
    if include_source:
        for index in indices:
            writes.update(state.effects.get(index, state.slots))
    return indices, PullEffect(writes=writes)


def _callback(state, plan, node, site, arguments, include_source):
    from .native_aot_callables import function_kind
    from .native_classes import shape
    from .native_module_linking import ClassReferenceType
    from .native_call_context_effects import source_plan
    from .native_source_native_effects import sealed_builtin
    kind = shape(site.callee)
    if isinstance(kind, ClassReferenceType):
        if (site.errors or site.targets or site.builtins or site.members
                or site.exception_constructors or set(site.constructors) != {kind.definition}):
            return unknown(state)
        children, effect = _source_children(state, plan, node, include_source)
        record = site.constructors[kind.definition]
        if (children is None or record.error
                or not state.constructor_role_closed(record.owner,
                    {source_plan(state.plans[index]).index for index in children})):
            return unknown(state)
        if children:
            effect.calls.append((node, frozenset(children)))
        return effect
    if (not function_kind(kind) or site.errors or site.members
            or site.constructors or site.exception_constructors
            or set(kind.targets) != set(site.targets) | set(site.builtins)):
        return unknown(state)
    children, effect = _source_children(state, plan, node, include_source)
    if children is None:
        return effect
    callback_targets = set()
    for target in site.targets:
        definition = getattr(target, 'definition', target)
        original = state.model.callable_cells.plans.get(definition)
        if original is None:
            return unknown(state)
        original = source_plan(original)
        if original is None:
            return unknown(state)
        matched = {index for index in children
                   if source_plan(state.plans[index]) is original}
        if not matched:
            return unknown(state)
        callback_targets.update(matched)
    for identity, record in site.builtins.items():
        if record.error or not sealed_builtin(state.model, identity, arguments):
            return unknown(state)
    if callback_targets:
        effect.calls.append((node, frozenset(callback_targets)))
    return effect


def operator_effects_closed(state, plan, node):
    """The registered implicit source methods cover every operator phase."""
    from .native_classes import InstanceType, shape
    from .native_call_context_effects import source_plan
    previous = state.model.augmented.get((plan.index, id(node)))
    if previous is None or not isinstance(shape(previous), InstanceType):
        return False
    site = state.model.operators.sites.get((plan.index, id(node), None))
    if site is None or not site.branches:
        return False
    children = set(state.model.call_edges_by_site.get((plan.index, id(node)), ()))
    if not children or any(index not in state.plans for index in children):
        return False
    original_children = {source_plan(state.plans[index]).index for index in children}
    covered = set()
    for branch in site.branches.values():
        if not branch.complete or not branch.phases or branch.fallback not in (None, 'error'):
            return False
        for phase in branch.phases:
            callback = phase.site
            if (not callback.targets or callback.errors or callback.builtins
                    or callback.members or callback.constructors or callback.exception_constructors):
                return False
            for target in callback.targets:
                definition = getattr(target, 'definition', target)
                original = state.model.callable_cells.plans.get(definition)
                original = None if original is None else source_plan(original)
                if original is None or original.index not in original_children:
                    return False
                covered.add(original.index)
    return covered == original_children


def _word_parser_closed(model, record):
    """The registered owned text snapshot pulls only the native int parser.

    Recheck the actual adapter/producer relationship, not its output ABI or
    may_call flag. Snapshot creation operands are still transferred at their
    original expression point; this certificate covers later pulls only.
    """
    from .native_integer_word_maps import IntegerWordMap
    from .native_classes import shape
    from .references import BuiltinIdentity
    adapter = record.adapter
    node, plan = record.node, record.plan
    if (type(adapter) is not IntegerWordMap or record.operation != 'map'
            or len(record.input_types) != 1 or not isinstance(node, ast.Call)
            or len(node.args) != 2 or isinstance(node.args[1], ast.Starred)
            or adapter.source is not node.args[1]
            or type(adapter.source_kind) is not str or adapter.source_kind not in {'str', 'bytes'}
            or getattr(shape(record.callback), 'targets', ()) != (BuiltinIdentity('int'),)
            or shape(record.element) != 'int'):
        return False
    source = adapter.source
    if not isinstance(source, ast.Call) or not isinstance(source.func, ast.Attribute):
        return False
    result = model.records.get((plan.index, id(node)))
    receiver = model.records.get((plan.index, id(source.func.value)))
    return (result is not None and shape(result) == record.kind
            and (plan.index, id(source)) in getattr(model, 'text_split_sites', {})
            and receiver is not None and shape(receiver) == adapter.source_kind)


def _pull(state, plan, node, value, include_source=True, seen=frozenset()):
    from .native_classes import shape, StreamType
    from .native_types import ListType, TupleType, TupleSequenceType
    from .native_class_iterators import iterator_kind
    from .native_source_native_effects import builtin_iterable, sealed_builtin
    from .references import BuiltinIdentity
    if value is None:
        return unknown(state)
    value = value.root()
    cell_key = ('cell', id(value))
    if cell_key in seen:
        return unknown(state)
    seen = seen | {cell_key}
    kind = shape(value)
    if value.tag == 'union':
        effect = PullEffect()
        for child in value.args:
            effect.add(_pull(state, plan, node, child, include_source, seen))
        return effect
    if iterator_kind(kind):
        iterators = state.model.iterators
        if not iterators.owns(kind) or kind.index in seen:
            return unknown(state)
        record = kind.record
        seen = seen | {kind.index}
        if hasattr(record, 'adapter'):
            return PullEffect() if _word_parser_closed(state.model, record) else unknown(state)
        if record.operation in {'source', 'reverse'}:
            # The core reverse cursor pulls a builtin sequence in the other
            # direction. Its actual source still has to close here; user
            # __reversed__/__getitem__ adapters are not inferred from a name.
            return _pull(state, plan, node, record.source, include_source, seen)
        if record.operation == 'enumerate':
            return _pull_kind(state, plan, node, record.input_type, include_source, seen)
        if record.operation not in {'map', 'zip', 'filter'}:
            return unknown(state)
        sources = record.input_types if record.operation in {'map', 'zip'} else (record.input_type,)
        effect = PullEffect()
        for source in sources:
            effect.add(_pull_kind(state, plan, node, source, include_source, seen))
        if not effect.closed:
            return effect
        if record.operation == 'zip':
            return effect
        arguments = tuple(shape(source.record.element) for source in sources)
        if record.operation == 'filter' and shape(record.callback) == 'none':
            if not sealed_builtin(state.model, BuiltinIdentity('bool'), arguments):
                return unknown(state)
            return effect
        site = record.demands.get((plan.index, id(node)))
        if site is None:
            return unknown(state)
        effect.add(_callback(state, plan, node, site, arguments, include_source))
        if (record.operation == 'filter'
                and not sealed_builtin(state.model, BuiltinIdentity('bool'), (shape(site.result),))):
            return unknown(state)
        return effect
    if value.tag == 'map_int':
        # This is the analyzed eager parser carrier, not an int output-kind
        # guess. Its retained source must itself have a closed pull protocol.
        if len(value.args) != 1:
            return unknown(state)
        words = value.args[0]
        effect = _pull(state, plan, node, words, include_source, seen)
        element = _item(words)
        if element is None or not sealed_builtin(state.model, BuiltinIdentity('int'), (shape(element),)):
            return unknown(state)
        return effect
    if value.tag == 'enumerate' and len(value.args) == 2:
        return _pull(state, plan, node, value.args[0], include_source, seen)
    if isinstance(kind, StreamType):
        return unknown(state)
    if isinstance(kind, (ListType, TupleType, TupleSequenceType)) or kind in {'str', 'bytes', 'range'}:
        return PullEffect() if builtin_iterable(kind) else unknown(state)
    return unknown(state)


def _pull_kind(state, plan, node, kind, include_source, seen):
    from .native_class_iterators import iterator_kind
    from .native_classes import Cell
    if not iterator_kind(kind) or not state.model.iterators.owns(kind):
        return unknown(state)
    return _pull(state, plan, node, Cell(kind), include_source, seen)


def _item(value):
    """Read existing element Cells only; do not mutate the solved Model."""
    from .native_class_iterators import iterator_kind
    from .native_classes import shape
    if value is None:
        return None
    value = value.root()
    kind = shape(value)
    if iterator_kind(kind):
        return getattr(kind.record, 'element', None)
    if value.tag in {'list', 'tuple_sequence'} and len(value.args) == 1:
        return value.args[0]
    return None


def _assignment_value(state, plan, target):
    parent = state.model.value_classes.parents.get(id(target))
    if isinstance(parent, (ast.Assign, ast.AnnAssign)) and parent.value is not None:
        return state.model.records.get((plan.index, id(parent.value)))
    return None


def unpack_phase(state, plan, target, value=None, include_source=True):
    if not isinstance(target, (ast.Tuple, ast.List)):
        return PullEffect()
    record = getattr(state.model, 'unpack_sites', {}).get((plan.index, id(target)))
    value = value if value is not None else _assignment_value(state, plan, target)
    if record is not None and getattr(record, 'source_kind', None) is not None:
        effect = _pull_kind(state, plan, target, record.source_kind, include_source, frozenset())
    else:
        effect = _pull(state, plan, target, value, include_source)
    # Even fixed outer tuples can contain inner callback iterators. Invalidate
    # all such pull phases before visiting any target receiver/index.
    fields = getattr(record, 'fields', None) if record is not None else None
    if fields is None and value is not None:
        root = value.root()
        if root.tag == 'tuple' and len(root.args) == len(target.elts):
            fields = root.args
    for index, child in enumerate(target.elts):
        starred = isinstance(child, ast.Starred)
        child = child.value if starred else child
        if isinstance(child, (ast.Tuple, ast.List)):
            star = next((i for i, part in enumerate(target.elts) if isinstance(part, ast.Starred)), None)
            field_index = index if star is None or index < star else (
                len(fields) - len(target.elts) + index if fields is not None else -1)
            if starred:
                member = getattr(record, 'rest', None)
            else:
                member = (fields[field_index] if fields is not None and 0 <= field_index < len(fields)
                          else _item(value))
            effect.add(unpack_phase(state, plan, child, member, include_source))
    return effect


def unpack_effects(state, plan, target, value=None):
    return frozenset(unpack_phase(state, plan, target, value).writes)


def comprehension_phase(state, plan, node, include_source=True):
    if isinstance(node, ast.GeneratorExp):
        return unknown(state)
    record = state.model.comprehensions.get((plan.index, id(node)))
    if record is None or len(record.sources) != len(node.generators):
        return unknown(state)
    effect = PullEffect()
    for generator, source in zip(node.generators, record.sources):
        value = state.model.records.get((plan.index, id(source.node)))
        effect.add(_pull(state, plan, source.node, value, include_source))
        effect.add(unpack_phase(state, plan, generator.target, _item(value), include_source))
    if isinstance(node, ast.DictComp) and not state.hash_closed(plan, node.key):
        return unknown(state)
    if isinstance(node, ast.SetComp) and not state.hash_closed(plan, node.elt):
        return unknown(state)
    return effect


def comprehension_effects(state, plan, node, include_source=True):
    return frozenset(comprehension_phase(state, plan, node, include_source).writes)


def comprehension_item(state, plan, node, index):
    record = state.model.comprehensions.get((plan.index, id(node)))
    if record is None or not 0 <= index < len(record.sources):
        return None
    value = state.model.records.get((plan.index, id(record.sources[index].node)))
    return _item(value)


def _for_members(value):
    """Existing possible yielded Cells, for nested target pull protocols."""
    if value is None:
        return None
    value = value.root()
    if value.tag == 'union':
        result = []
        for child in value.args:
            members = _for_members(child)
            if members is None:
                return None
            result.extend(members)
        return result
    if value.tag == 'tuple' or getattr(value.tag, '_native_tuple_record', False):
        return value.args
    item = _item(value)
    return None if item is None else (item,)


def for_phase(state, plan, node, include_source=True):
    """The actual For demand is a pull operation, never an iterable truth test."""
    if not isinstance(node, ast.For):
        return unknown(state)
    value = state.model.records.get((plan.index, id(node.iter)))
    effect = _pull(state, plan, node, value, include_source)
    # Keep all registered source roles, including implicit provider demands;
    # an input's scalar ABI alone is not proof that its pull has no callback.
    _, children = _source_children(state, plan, node, include_source)
    effect.add(children)
    if isinstance(node.target, (ast.Tuple, ast.List)):
        members = _for_members(value)
        if members is None:
            effect.add(unknown(state))
        else:
            for member in members:
                effect.add(unpack_phase(state, plan, node.target, member, include_source))
    return effect


def for_effects(state, plan, node, include_source=True):
    return frozenset(for_phase(state, plan, node, include_source).writes)


def annotate_pulls(state, effect, available, mode):
    """Native phases and all source MAY writes precede callback permission."""
    if not effect.closed:
        return
    for node, targets in effect.calls:
        if not targets or not all(index in state.abis for index in targets):
            continue
        required = set().union(*(state.requirements[index] for index in targets))
        if required <= available and not required & effect.writes:
            mode.calls[id(node)] = frozenset(mode.calls.get(id(node), ())) | targets
