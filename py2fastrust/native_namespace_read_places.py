"""Checked, borrowed scalar reads from actual typed namespace list slots.

The place does not assert that a binding is initialized, immutable, or unique.
It reads the current slot on the captured class/module generation. Only a
closed scalar index may run while its namespace/list loans are live.
"""
import ast
from dataclasses import dataclass

from .native_module_linking import ClassReferenceType, ModuleType
from .native_types import ListType


SCALARS = frozenset({'int', 'bool', 'int_bool', 'float'})
INDICES = frozenset({'int', 'bool', 'int_bool'})


@dataclass(frozen=True)
class ReadPlace:
    receiver: object
    receiver_kind: object
    attribute: object
    slot: int
    kind: object
    member: object = None


def lifetime_closed(model):
    """Do not extend capture lifetimes across source Drop/frame observers."""
    captures = getattr(model, 'callable_field_demand', None)
    if captures is None or captures.model is not model or captures.barrier is not None:
        return False
    cached = getattr(model, 'namespace_read_place_lifetime', None)
    if cached is not None:
        return cached
    model.namespace_read_place_lifetime = False
    from .native_finite_depth_calls import _model_proof, Unproved
    try:
        # This existing source certificate rejects collection/finalizers,
        # suspended frames, namespace reflection and unknown native callbacks.
        _model_proof(model)
    except Unproved:
        return False
    from .native_classes import shape
    from .native_single_execution_metadata import _identities
    from .native_module_calls import BuiltinRef
    from .references import BuiltinIdentity
    identities = set(model.callable_cells.builtin_used) | set(model.callable_cells.member_used)
    for cell in model.records.values():
        kind = shape(cell)
        if getattr(kind, '_native_namespace_view', False):
            return False
        identities.update(_identities(kind))
    for identity in identities:
        if isinstance(identity, BuiltinIdentity) and identity.name in {'id', 'hash'}:
            return False
        if isinstance(identity, BuiltinRef) and (
                identity.module in {'gc', 'weakref'}
                or identity.module == 'sys' and identity.name in {'getrefcount', '_getframe', '_current_frames'}
                or identity.module == 'builtins' and identity.name in {'id', 'hash'}):
            return False
    model.namespace_read_place_lifetime = True
    return True


def select(emitter, node):
    """Use only the existing exact attribute adapter and physical slot ABI."""
    if not (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Attribute)):
        return None
    attribute = node.value
    kind = emitter.kind(attribute)
    if not (isinstance(kind, ListType) and kind.element in SCALARS
            and emitter.kind(node) == kind.element
            and emitter.kind(node.slice) in INDICES):
        return None
    from .native_scalar_effects import scalar_rhs
    if not scalar_rhs(node.slice, emitter.kind):
        return None
    model = emitter.model
    owner_kind = emitter.kind(attribute.value)
    member = None
    if isinstance(owner_kind, ClassReferenceType):
        registry = getattr(model, 'class_namespaces', None)
        if registry is None:
            return None
        site = emitter.plan.index, id(attribute)
        records = registry.attribute_reads.get(site, ())
        if (site in registry.instance_reads or len(records) != 1
                or records[0].plan is not None):
            return None
        member = records[0]
        if (member.owner is not registry.owners.get(owner_kind.definition)
                or member.name != model.resolved_name(emitter.plan, attribute)):
            return None
        key = member.key
    elif isinstance(owner_kind, ModuleType):
        linker = getattr(model, 'module_linker', None)
        if linker is None or owner_kind.number not in linker.by_number:
            return None
        module = linker.by_number[owner_kind.number]
        # Native modules and missing-export fallbacks have separate adapters.
        if module.native_adapter:
            return None
        key = model.unit.global_name(module.name, attribute.attr)
        if model.unit.global_name(module.name, '__getattr__') in model.namespace.incoming:
            return None
    else:
        return None
    # A narrowed point kind must never relabel a different physical carrier.
    if dict(model.namespace.fields()).get(key) != kind:
        return None
    if not lifetime_closed(model):
        return None
    return ReadPlace(attribute.value, owner_kind, attribute,
                     model.namespace.index(key), kind, member)


def read(emitter, node):
    place = select(emitter, node)
    if place is None:
        return None
    from .native import _string
    from .native_classes import Expression
    from .native_list_end_indices import method, result
    before, owner = emitter.capture(emitter.expression(place.receiver))
    namespace, member, contents, raw, completed = [emitter.fresh() for _ in range(5)]
    if place.member is not None:
        receiver = owner.code + '.module'
        failure = _string("AttributeError: type object '" + place.member.owner.node.name
                          + "' has no attribute '" + place.member.name + "'") + '.to_owned()'
    else:
        receiver = owner.code
        failure = ('class_module_export_error(&' + owner.code + ','
                   + _string(place.attribute.attr) + ','
                   + _string(repr(place.attribute.attr)) + ',false)')
    current = (namespace + '.value_' + str(place.slot)
               + '.as_ref().ok_or_else(||' + failure + ')')
    # Presence is tested before evaluating the source index, as for an owned
    # attribute load. The index certificate excludes all callbacks/rebinding.
    setup = ('let ' + namespace + '=' + receiver + '.borrow();'
             + 'let ' + member + '=' + emitter.at(current, place.attribute) + ';')
    operation = method(node.slice)
    if operation is not None:
        indexed = result(contents, operation)
    else:
        index_setup, index = emitter.capture(emitter.expression(node.slice))
        setup += index_setup
        indexed = ('class_slice_get(&' + contents + ',&('
                   + emitter.number(index) + ')).cloned()')
    setup += ('let ' + raw + '={let ' + contents + '=' + member + '.borrow();'
              + indexed + '};')
    # The local Result boundary drops every loan on both success and failure
    # before an error can reach the source handler/cleanup in the enclosing body.
    code = ('{' + before + 'let ' + completed + '=(||->Result<'
            + emitter.rust_type(place.kind.element) + ',NativeError>{' + setup
            + 'Ok(' + emitter.at(raw, node) + ')})();' + completed + '?}')
    return Expression(code, place.kind.element)
