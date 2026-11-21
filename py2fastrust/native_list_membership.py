"""Membership tests against typed owned and shared list storage."""
import ast

from .native_types import ListType,SharedListType


def membership(g,node,values):
    """Lower ``item in list`` after both operands were evaluated in source order."""
    from .native import _Expression,_Unsupported
    from .native_list_methods import _supported
    from .native_tuples import _equal
    key,container=values
    if container.kind=="list_int":element="int"
    elif isinstance(container.kind,ListType):element=container.kind.element
    else:return None
    if not _supported(element)or not _supported(key.kind):
        raise _Unsupported("list membership needs Python identity-then-equality for this item/element pair, including identity-dependent floats or special methods; that equality adapter is not implemented",node=node,operation="in",types=(("item",key.kind),("element",element)),proof="Python list.__contains__ identity and equality behavior")
    item,owner,value=g.temporary(),g.temporary(),g.temporary()
    contents=f"{owner}.borrow()"if isinstance(container.kind,SharedListType)else owner
    equal=_equal(g,_Expression(f"(*{value})",element,owned=False),_Expression(f"(*{item})",key.kind,owned=False))
    found=f"{contents}.iter().any(|{value}|{equal})"
    if isinstance(node.ops[0],ast.NotIn):found=f"!({found})"
    return _Expression(f"{{let {item}=&({key.code});let {owner}=&({container.code});{found}}}","bool")
