"""Builtin list in-place concatenation after original numeric slot dispatch."""
import ast


def applies(node, operator, left):
    from .native_types import list_type
    return isinstance(node, ast.AugAssign) and isinstance(operator, ast.Add) and list_type(left)


def requires_frames(unit, analysis):
    from .native_types import alternatives, list_type, SharedListType
    from .native_key_types import DictType
    for node in ast.walk(unit.tree):
        if not isinstance(node, ast.AugAssign) or not isinstance(node.op, ast.Add):
            continue
        for facts in analysis.scopes.values():
            receiver = facts.expressions.get(unit.ordinal(node.target))
            if not any(list_type(kind) for kind in alternatives(receiver)):
                continue
            source = facts.expressions.get(unit.ordinal(node.value))
            # Existing ordinary shared-list storage already consumes these
            # concrete callback-free builtin values. Keep that proved route.
            storage = facts.storage.get(unit.ordinal(node.target))
            if isinstance(storage, SharedListType) and all(
                    kind in {'str', 'bytes'} or type(kind) is DictType
                    for kind in alternatives(source)):
                continue
            if not all(list_type(kind) for kind in alternatives(source)):
                return True
    return False


def analyze(model, plan, node, operator, left, right, environment, identity):
    from .native_classes import shape
    from .native_types import list_type
    # The original statement owns its exact list/list fast path. A source-slot
    # fallback arm still needs in-place mutation rather than concatenation.
    if not applies(node, operator, shape(left)) or (identity is None and list_type(shape(right))):
        return None
    from .native_list_extend import analyze as extension
    from .native_union_sequences import branches
    from .native_classes import Environment
    environments = []
    for source in branches(right):
        inside = Environment(environment)
        branch_identity = ('inplace_list', identity, shape(source))
        if list_type(shape(source)):
            from .native_list_element_flows import concatenate
            concatenate(model, plan, node, left.root().args[0], source.root().args[0],
                        identity=branch_identity)
        else:
            extension(model, plan, node, left, source, inside,
                      identity=branch_identity, consumer='list +=')
        environments.append(inside)
    if environments:
        joined = environments[0]
        for inside in environments[1:]:
            joined = model.join(joined, inside, node, ('inplace_list', identity))
        model.replace_environment(environment, joined)
    return left


def emit(emitter, operator, left, right, node, wanted, identity):
    from .native_classes import Expression
    from .native_types import list_type
    if not applies(node, operator, left.kind) or (identity is None and list_type(right.kind)):
        return None
    from .native_sequence_storage import SequenceStorage
    from .native_list_extend import emit as extension
    storage = SequenceStorage((), '&(' + left.code + '.borrow())[..]',
        '&mut *' + left.code + '.borrow_mut()', left.kind, shared=True)
    from .native_unions import union_kind, project

    def branch(kind, code):
        if list_type(kind):
            return 'class_list_extend(&' + left.code + ',&' + code + ')'
        operation = extension(emitter, node, storage,
            Expression(code, kind, owned=not union_kind(right.kind)),
            identity=('inplace_list', identity, kind), consumer='list +=')
        return operation.code

    if union_kind(right.kind):
        operation = project(right.kind, right.code,
                            lambda kind, code: '{' + branch(kind, code) + '}')
    else:
        operation = branch(right.kind, right.code)
    # The statement layer performs its original target store only after the
    # extension completes. Never replace that store with a fresh list value.
    result = emitter.coerce(Expression(left.code + '.clone()', left.kind), wanted, node)
    return Expression('{' + operation + ';' + result + '}', wanted)
