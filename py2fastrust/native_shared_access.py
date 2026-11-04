"""Borrow stable shared-list paths during non-reentrant scalar indexing.

Each owner and index retains its source evaluation order. Intermediate row
handles stay behind immutable parent guards instead of incrementing Rc counts.
No guard spans a call, named expression, or other possible storage change.
"""
import ast
from dataclasses import dataclass

from .native_types import SharedListType, unmaybe


@dataclass(frozen=True)
class Access:
    root: ast.Name
    binding: object
    steps: tuple


def pure_scalar(g,node,environment):
    from .native_nested_lists import kind_for
    from .native_scalar_effects import scalar_rhs
    return scalar_rhs(node,lambda child:unmaybe(kind_for(g,child,environment)))


def access(g,node,environment):
    """Prove an existing local storage path; do not allocate emitter temporaries."""
    from .native import _Binding
    from .native_nested_lists import kind_for
    from .native_sequence_storage import binding_name
    steps=[]
    current=node
    while isinstance(current,ast.Subscript) and not isinstance(current.slice,ast.Slice):
        if not isinstance(kind_for(g,current.value,environment),SharedListType):return None
        if not pure_scalar(g,current.slice,environment):return None
        steps.append(current)
        current=current.value
    if not isinstance(current,ast.Name):return None
    binding=environment.get(binding_name(g,current))
    if not isinstance(binding,_Binding)or not isinstance(unmaybe(binding.kind),SharedListType):return None
    return Access(current,binding,tuple(reversed(steps)))


def owner(g,proved,environment):
    from .native import _MaybeInfo,_string
    from .native_nested_lists import _index
    reference=g.temporary()
    binding=proved.binding
    if isinstance(binding.info,_MaybeInfo):
        if binding.info.owner is None:message=f"NameError: name '{proved.root.id}' is not defined"
        elif g.scope_name()!=binding.info.owner:message=f"NameError: cannot access free variable '{proved.root.id}' where it is not associated with a value in enclosing scope"
        else:message=f"UnboundLocalError: cannot access local variable '{proved.root.id}' where it is not associated with a value"
        code=g.at(f"{binding.slot}.as_ref().ok_or_else(||String::from({_string(message)}))",proved.root)
    else:code=f"&({binding.slot})"
    lines=[f"let {reference}={code};"]
    kind=unmaybe(binding.kind)
    for step in proved.steps:
        from .native_list_end_indices import method,result as end_result
        operation=method(step.slice)
        if operation is not None:
            guard,next_reference=(g.temporary()for _ in range(2))
            lines.append(f"let {guard}={reference}.borrow();let {next_reference}="
                         +g.at(end_result(guard,operation,clone=False),step)+";")
            reference=next_reference;kind=kind.element
            continue
        number,guard,position,next_reference=(g.temporary()for _ in range(4))
        value=g.expression(step.slice,environment)
        lines.append(f"let {number}={g.number(value)};let {guard}={reference}.borrow();")
        checked=_index(g,number,f"{guard}.len()",step)
        lines.append(f"let {position}={checked};let {next_reference}=&{guard}[{position}];")
        reference=next_reference
        kind=kind.element
    return lines,reference,kind


def read(g,node,environment):
    if not pure_scalar(g,node.slice,environment):return None
    proved=access(g,node.value,environment)
    if proved is None:return None
    from .native import _Expression
    from .native_nested_lists import _index
    lines,reference,kind=owner(g,proved,environment)
    from .native_list_end_indices import method,result as end_result
    operation=method(node.slice)
    if operation is not None:
        guard,value=(g.temporary()for _ in range(2))
        lines.append(f"let {guard}={reference}.borrow();let {value}="
                     +g.at(end_result(guard,operation),node)+f";{value}")
        return _Expression("{"+"".join(lines)+"}",kind.element)
    number,guard,position,result=(g.temporary()for _ in range(4))
    value=g.expression(node.slice,environment)
    lines.append(f"let {number}={g.number(value)};let {guard}={reference}.borrow();")
    checked=_index(g,number,f"{guard}.len()",node)
    lines.append(f"let {position}={checked};let {result}={guard}[{position}].clone();{result}")
    return _Expression("{"+"".join(lines)+"}",kind.element)


def statement(g,node,target,environment):
    """A scalar store keeps no owned handle and borrows after all index effects."""
    if not pure_scalar(g,target.slice,environment):return None
    proved=access(g,target.value,environment)
    if proved is None:return None
    from .native import _Expression
    from .native_nested_lists import _index,kind_for
    from .native_scalar_effects import SCALARS
    kind=kind_for(g,target.value,environment)
    if kind.element not in SCALARS:return None
    if isinstance(node,ast.AugAssign)and not pure_scalar(g,node.value,environment):return None
    lines=[]
    item=g.temporary()
    if isinstance(node,ast.Assign):
        value=g.expression(node.value,environment)
        lines.append(f"let {item}={value.code};")
    before,reference,kind=owner(g,proved,environment)
    lines.extend(before)
    number,guard,position=(g.temporary()for _ in range(3))
    value_index=g.expression(target.slice,environment)
    lines.append(f"let {number}={g.number(value_index)};let mut {guard}={reference}.borrow_mut();")
    checked=_index(g,number,f"{guard}.len()",target,assignment=not isinstance(node,ast.AugAssign))
    lines.append(f"let {position}={checked};")
    if isinstance(node,ast.Delete):lines.append(f"{guard}.remove({position});")
    else:
        if isinstance(node,ast.AugAssign):
            previous=g.temporary()
            lines.append(f"let {previous}={guard}[{position}].clone();")
            right=g.expression(node.value,environment)
            value=g.binary(node.op,_Expression(previous,kind.element),right,node)
            lines.append(f"let {item}={value.code};")
        converted=g.coerce(_Expression(item,value.kind),kind.element)
        lines.append(f"{guard}[{position}]={converted};")
    return "{"+"".join(lines)+"}",environment
