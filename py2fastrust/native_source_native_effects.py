"""Source-heap writes of complete, canonical native operation phases.

These are compiler effects, not replacements for operand evaluation, binding,
iteration or errors. Input/output cursor changes are distinct from writes to
the tracked source lists. Unknown identities and value protocols stay opaque.
"""
import ast


def _plain_owner(model, owner):
    return (owner is not None and isinstance(owner.node, ast.ClassDef)
            and not owner.node.bases and not owner.node.keywords
            and not owner.node.decorator_list and not owner.node.type_params
            and not any(name in owner.methods for name in
                        ('__getattribute__', '__getattr__', '__instancecheck__')))


def _type_info(model, kind):
    from .native_types import TupleType, TupleSequenceType, alternatives
    from .native_module_linking import ClassReferenceType
    from .native_aot_callables import function_kind
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    from .native_type_checks import TYPE_NAMES
    for part in alternatives(kind):
        if isinstance(part, ClassReferenceType):
            if not _plain_owner(model, model.class_namespaces.owners.get(part.definition)):
                return False
        elif isinstance(part, TupleType):
            if not all(_type_info(model, field) for field in part.fields):
                return False
        elif isinstance(part, TupleSequenceType):
            if not _type_info(model, part.element):
                return False
        elif function_kind(part):
            if not part.targets or not all((isinstance(item, BuiltinIdentity)
                    or isinstance(item, BuiltinRef) and item.module == 'builtins')
                    and item.name in TYPE_NAMES for item in part.targets):
                return False
        else:
            return False
    return kind is not None


def _instance_value(model, kind):
    from .native_classes import InstanceType, domain
    from .native_types import alternatives
    from .native_list_positions import closed
    def plain_instance(part):
        owner = model.classes.get(part.name)
        if not _plain_owner(model, owner):
            return False
        members = getattr(getattr(model, 'class_namespaces', None), 'members', {})
        return ('__class__' not in owner.methods
                and '__class__' not in getattr(owner, 'fields', {})
                and (getattr(owner, 'index', None), '__class__') not in members)

    return kind is not None and all(
        plain_instance(part)
        if isinstance(part, InstanceType) else (closed(part) or domain(part) in {
            'list', 'tuple', 'tuple_sequence', 'dict', 'set', 'deque',
            'defaultdict', 'Counter', 'OrderedDict', 'function'})
        for part in alternatives(kind))


def builtin_iterable(kind):
    """Obtaining these builtin iterators does not invoke an element protocol."""
    from .native_types import ListType, TupleType, TupleSequenceType, alternatives
    from .native_classes import StreamType
    if isinstance(kind, StreamType):
        # The old immediate int-map carrier retains its actual word source;
        # a source-protocol iterator is never certified from its output type.
        return (kind.name == 'map_int' and len(kind.fields) == 1
                and builtin_iterable(kind.fields[0]))
    return kind is not None and all(
        isinstance(part, (ListType, TupleType, TupleSequenceType))
        or part in {'str', 'bytes', 'range'} for part in alternatives(kind))


def sealed_builtin(model, identity, argument_kinds):
    """No tracked source-heap writes, including all native internal phases."""
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    from .native_list_positions import closed
    if isinstance(identity, BuiltinRef) and identity.module == 'builtins':
        identity = BuiltinIdentity(identity.name)
    if not isinstance(identity, BuiltinIdentity):
        return False
    name = identity.name
    if name == 'isinstance':
        return (len(argument_kinds) == 2 and _instance_value(model, argument_kinds[0])
                and _type_info(model, argument_kinds[1]))
    if name in {'len', 'bool'}:
        # Length/truth of a builtin container does not inspect its elements.
        # In particular a list of source objects still has a native length.
        from .native_classes import domain
        return all(kind is not None and (closed(kind) or domain(kind) in {
            'list', 'tuple', 'tuple_sequence', 'dict', 'set', 'deque',
            'defaultdict', 'Counter', 'OrderedDict'}) for kind in argument_kinds)
    if name in {'map', 'filter'}:
        # Creation obtains the input iterators but does not call the predicate
        # or mapper. Pull-time callback demands are classified separately.
        return len(argument_kinds) >= 2 and all(builtin_iterable(kind) for kind in argument_kinds[1:])
    if name in {'iter', 'reversed', 'enumerate'}:
        return (bool(argument_kinds) and builtin_iterable(argument_kinds[0])
                and all(closed(kind) for kind in argument_kinds[1:]))
    if name == 'zip':
        return all(builtin_iterable(kind) for kind in argument_kinds)
    if name in {'list', 'tuple'}:
        return not argument_kinds or len(argument_kinds) == 1 and builtin_iterable(argument_kinds[0])
    if name in {'print', 'input', 'range', 'len', 'int', 'bool', 'float', 'str',
                'bytes', 'abs', 'ord', 'chr', 'round', 'pow', 'divmod',
                'sum', 'min', 'max', 'all', 'any'}:
        return all(kind is not None and closed(kind) for kind in argument_kinds)
    return False


def _identity(state, plan, function):
    from .native_aot_callables import function_kind
    from .native_types import alternatives
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    kind = state.kind(plan, function)
    if function_kind(kind):
        targets = tuple(kind.targets)
        return targets[0] if len(targets) == 1 and isinstance(targets[0], (BuiltinIdentity, BuiltinRef)) else None
    if kind is not None and len(alternatives(kind)) > 1:
        return None
    from .native_physical_list_builtins import static_builtin
    if isinstance(function, ast.Name) and static_builtin(state.model, plan, function, function.id):
        return BuiltinIdentity(function.id)
    return None


def operation(state, plan, node):
    """Return all tracked native writes, or None without a complete proof.

    This summary excludes separately registered source-child effects. A native
    callback may receive an incoming witness only when BOTH its source effects
    and every native phase preserve the required slot.
    """
    if not isinstance(node, ast.Call):
        return None
    from .native_types import ListType, alternatives
    from .native_list_positions import closed
    model = state.model
    arguments = [state.kind(plan, item) for item in node.args]
    arguments += [state.kind(plan, item.value) for item in node.keywords]
    identity = _identity(state, plan, node.func)
    if identity is not None and sealed_builtin(model, identity, arguments):
        return frozenset()
    # The immediate integer-map collector is a separate canonical operation;
    # its result is not an iterator kind, and its int parser cannot call source.
    if (identity is not None and getattr(identity, 'name', None) in {'list', 'tuple'}
            and len(node.args) == 1 and not node.keywords
            and getattr(state.kind(plan, node.args[0]), 'name', None) == 'map_int'
            and builtin_iterable(state.kind(plan, node.args[0]))):
        return frozenset()
    function_kind = state.kind(plan, node.func)
    if function_kind in {'reader_text', 'reader_bytes', 'read_text', 'read_bytes'}:
        return frozenset() if not arguments else None
    if not isinstance(node.func, ast.Attribute):
        return None
    receiver = state.kind(plan, node.func.value)
    members = alternatives(receiver) if receiver is not None else ()
    if members and all(part in {'stdin', 'stdin_buffer'} for part in members):
        return (frozenset() if node.func.attr in {'read', 'readline'} and not arguments else None)
    point = plan.index, id(node)
    if members and all(part in {'str', 'bytes'} for part in members):
        sites = (getattr(model, 'text_split_sites', {}),
                 getattr(model, 'text_operation_sites', {}))
        if (any(point in sites_by_kind for sites_by_kind in sites)
                and all(kind is not None and closed(kind) for kind in arguments)):
            return frozenset()
    if receiver in {'int', 'bool', 'int_bool'} and node.func.attr in {'bit_length', 'bit_count'}:
        return frozenset() if not arguments else None
    if isinstance(receiver, ListType):
        method = model.sequence_calls.get(point)
        if method is None or method.name != node.func.attr:
            return None
        if method.name in {'copy', 'count', 'index'}:
            return (frozenset() if closed(receiver.element)
                    and all(kind is not None and closed(kind) for kind in arguments) else None)
        if method.name in {'append', 'clear', 'extend', 'insert', 'pop', 'remove', 'reverse', 'sort'}:
            return frozenset(state.aliases(plan, node.func.value))
    return None
