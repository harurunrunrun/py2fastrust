"""Store captured unpacked values through the original targets in source order."""
import ast

from .native import _Binding, _Expression, _MaybeInfo, _Unsupported
from .native_types import (ListType, SharedListType, TupleType, TupleSequenceType,
                           TypedListInfo, reference_cloneable, tuple_code, unmaybe)


def _unsupported(target, message, **kwargs):
    raise _Unsupported(message, node=target, operation="indexed/attribute unpacking",
                       proof="ordered target-place storage", **kwargs)


def owned(g, value, node):
    if value.owned:
        return value.code
    if not reference_cloneable(value.kind):
        _unsupported(node, "this unpacked mutable value has no identity-preserving shared storage; copying its contents would change aliases",
                     types=(("value", value.kind),))
    return g.coerce(value, value.kind)


def placeholders(g, target, environment):
    if isinstance(target, ast.Name):
        return [f"{g.bind(target.id, 'int', environment)}={g.literal(0)};"]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [line for child in target.elts for line in placeholders(g, child, environment)]
    # These bindings are reached only after an unconditional unpack error.
    # A place does not introduce a Python name and must never be evaluated.
    return []


def _check(g, actual, expected, target):
    from .native_unpack import _check
    return _check(g, actual, expected, target)


def _number(g, value, target):
    if value.kind not in {'int', 'bool', 'int_bool'}:
        _unsupported(target, "this indexed unpacking target requires the builtin integer-index conversion; a custom __index__ target adapter is not implemented",
                     types=(("index", value.kind),))
    return g.number(value)


def assign(g, target, value, environment):
    if isinstance(target, ast.Name):
        if target.id in g.iterating_lists:
            _unsupported(target, "this unpacking target aliases a borrowed iterator owner; an owned iterator/target adapter is required")
        code=owned(g, value, target)
        return [f"{g.bind(target.id, value, environment)}={code};"]
    if isinstance(target, (ast.Tuple, ast.List)):
        count=len(target.elts)
        if any(isinstance(child, ast.Starred) for child in target.elts):
            _unsupported(target, "starred indexed/attribute unpacking requires a staged remainder-list target adapter; that adapter is not implemented")
        name=g.temporary()
        lines=[f"let {name}={owned(g, value, target)};"]
        if isinstance(value.kind, TupleType):
            lines.append(_check(g, str(len(value.kind.fields)), count, target))
            if len(value.kind.fields)!=count:
                return lines+placeholders(g, target, environment)
            fields=[_Expression(f"{name}.{index}", kind, owned=value.owned)
                    for index,kind in enumerate(value.kind.fields)]
        elif isinstance(value.kind, (TupleSequenceType, ListType)) or value.kind=='list_int':
            shared=isinstance(value.kind, SharedListType)
            owner=f"{name}.borrow()" if shared else name
            lines.append(_check(g, f"{owner}.len()", count, target))
            kind='int' if value.kind=='list_int' else value.kind.element
            fields=[_Expression(f"{owner}[{index}]", kind, owned=False) for index in range(count)]
        else:
            _unsupported(target, "nested indexed/attribute unpacking needs a proved builtin tuple/list element layout; an iterator/protocol unpack adapter is not implemented for this value",
                         types=(("value", value.kind),))
        # Snapshot every member at this level before its first target store.
        # Nested levels are deliberately unpacked only when their turn arrives.
        captured=[]
        for field in fields:
            temporary=g.temporary()
            lines.append(f"let {temporary}={owned(g, field, target)};")
            captured.append(_Expression(temporary, field.kind, owned=True))
        for child, field in zip(target.elts, captured):
            lines.extend(assign(g, child, field, environment))
        return lines
    if isinstance(target, ast.Attribute):
        _unsupported(target, "this ordinary native unpacking path has no attribute-store protocol adapter; class-field/descriptor assignment requires the class emitter")
    if not isinstance(target, ast.Subscript):
        _unsupported(target, "this unpacking target has no ordered native store adapter")
    if isinstance(target.slice, ast.Slice):
        _unsupported(target, "slice targets in unpacking require ordered slice replacement and alias-preserving resize handling; that slice-store adapter is not implemented")
    from .native_nested_lists import kind_for
    from .native_typed_lists import _index
    kind=kind_for(g, target.value, environment)
    receiver=None
    if kind is None and not isinstance(target.value, ast.Name):
        # A Store target's receiver is still an ordinary evaluated expression.
        # The solver need not have cached a separate read at this Store site.
        receiver=g.expression(target.value, environment)
        kind=receiver.kind
    if isinstance(kind, SharedListType):
        receiver=receiver or g.expression(target.value, environment)
        handle, offset, position=(g.temporary() for _ in range(3))
        lines=[f"let {handle}={receiver.code};"]
        index=g.expression(target.slice, environment)
        lines.append(f"let {offset}={_number(g,index,target)};")
        lines.append(f"let {position}={_index(g, offset, f'{handle}.borrow().len()', target, assignment=True)};")
        converted=g.coerce(value, kind.element)
        lines.append(f"{handle}.borrow_mut()[{position}]={converted};")
        return lines
    if (isinstance(target.value, ast.Subscript) and value.kind=='int'
            and kind_for(g, target.value.value, environment)=='matrix_int'):
        setup,row=g.row_target(target.value, environment)
        index=g.expression(target.slice, environment)
        offset=g.temporary()
        return [setup, f"let {offset}={_number(g,index,target)};",
                g.at(f"native_set(&mut {row},{offset},{value.code})", target)+';']
    binding=environment.get(target.value.id) if isinstance(target.value, ast.Name) else None
    if not isinstance(binding, _Binding) or target.value.id in g.iterating_lists:
        _unsupported(target, "this indexed unpacking target has no stable owned-list place or shared-list handle; a receiver storage/protocol adapter is not implemented",
                     types=(("receiver", kind),))
    kind=unmaybe(binding.kind)
    slot=binding.slot
    lines=[]
    if isinstance(binding.info,_MaybeInfo):
        # Evaluate the original name's unbound check before any index effects.
        # Do not retain a contents borrow across the index expression.
        receiver=g.expression(target.value,environment)
        lines.append(f"let _={receiver.code};")
        slot=f"({binding.slot}.as_mut().unwrap())"
    if kind=='list_int':
        element='int'
    elif type(kind) is ListType and isinstance(binding.info,(TypedListInfo,_MaybeInfo)):
        element=kind.element
    else:
        _unsupported(target, "indexed unpacking currently requires a builtin list with a proved element layout; mapping/deque/alternative receiver stores need a dedicated ordered-place adapter",
                     types=(("receiver", binding.kind),))
    index=g.expression(target.slice, environment)
    offset, position=(g.temporary() for _ in range(2))
    converted=g.coerce(value, element)
    return lines+[f"let {offset}={_number(g,index,target)};",
                  f"let {position}={_index(g, offset, f'{slot}.len()', target, assignment=True)};",
                  f"{slot}[{position}]={converted};"]


def fields(g, target, values, environment):
    kind=TupleType(tuple(value.kind for value in values))
    value=_Expression(tuple_code(owned(g, value, target) for value in values), kind, owned=True)
    return assign(g, target, value, environment)
