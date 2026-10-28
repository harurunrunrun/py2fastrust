"""Fuse typed list AugAssign only across a proved non-reentrant scalar RHS.

The target's owner and index still execute once before the original get check.
The mutable borrow and checked offset are shared by get and set only when the
RHS cannot access container storage or invoke Python code. Errors return before
the element is committed, and the borrow ends at this statement's Rust block.
"""
import ast


_SCALARS=frozenset({"int","bool","int_bool","float"})


def scalar_rhs(emitter,node):
    """A closed proof; unknown expressions retain the ordinary get/RHS/set path."""
    from .native_classes import domain
    if domain(emitter.kind(node))not in _SCALARS:return False
    if isinstance(node,ast.Constant):
        return type(node.value)in {int,bool,float}
    if isinstance(node,ast.Name):
        return isinstance(node.ctx,ast.Load)
    if isinstance(node,ast.Attribute):
        return (isinstance(node.ctx,ast.Load)and isinstance(node.value,ast.Name)
                and domain(emitter.kind(node.value))=="object")
    if isinstance(node,ast.UnaryOp):
        return isinstance(node.op,(ast.UAdd,ast.USub,ast.Invert,ast.Not))and scalar_rhs(emitter,node.operand)
    if isinstance(node,ast.BinOp):
        return scalar_rhs(emitter,node.left)and scalar_rhs(emitter,node.right)
    if isinstance(node,ast.BoolOp):
        return all(scalar_rhs(emitter,value)for value in node.values)
    if isinstance(node,ast.Compare):
        return scalar_rhs(emitter,node.left)and all(scalar_rhs(emitter,value)for value in node.comparators)
    if isinstance(node,ast.IfExp):
        return all(scalar_rhs(emitter,value)for value in (node.test,node.body,node.orelse))
    return False


def emit(emitter,node,setup,reference,old_kind):
    """Return a statement only after storage, payload, and RHS proofs succeed."""
    from .native import _Expression
    from .native_classes import domain
    if reference[0]!="index":return None
    _,owner,index,stored=reference
    wanted=emitter.kind(node.target)
    if (domain(stored)not in _SCALARS or old_kind!=stored or wanted!=stored
            or not scalar_rhs(emitter,node.value)):
        return None
    guard,offset,previous=(emitter.fresh()for _ in range(3))
    checked=emitter.at(f"class_index(&({emitter.number(index)}),{guard}.len())",node.target)
    before=(f"let mut {guard}={owner.code}.borrow_mut();let {offset}={checked};"
            f"let {previous}={guard}[{offset}].clone();")
    rhs_setup,right=emitter.capture(emitter.expression(node.value))
    result=emitter.binary(node.op,_Expression(previous,stored),right,node,wanted)
    result_setup,result=emitter.capture(result)
    commit=f"{guard}[{offset}]={emitter.coerce(result,stored,node.target)};"
    return "{"+setup+before+rhs_setup+result_setup+commit+"}"
