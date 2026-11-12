"""Prove scalar expressions cannot reenter or observe borrowed containers."""
import ast


SCALARS=frozenset({'int','bool','int_bool','float'})


def scalar_rhs(node,kind,field=None,read=None):
    if kind(node)not in SCALARS:return False
    if isinstance(node,ast.Constant):return type(node.value)in {int,bool,float}
    if isinstance(node,ast.Name):return isinstance(node.ctx,ast.Load)
    if isinstance(node,ast.Attribute):return field is not None and field(node)
    if isinstance(node,ast.Subscript):return read is not None and read(node)
    if isinstance(node,ast.UnaryOp):
        return isinstance(node.op,(ast.UAdd,ast.USub,ast.Invert,ast.Not))and scalar_rhs(node.operand,kind,field,read)
    if isinstance(node,ast.BinOp):
        return scalar_rhs(node.left,kind,field,read)and scalar_rhs(node.right,kind,field,read)
    if isinstance(node,ast.BoolOp):return all(scalar_rhs(value,kind,field,read)for value in node.values)
    if isinstance(node,ast.Compare):
        return scalar_rhs(node.left,kind,field,read)and all(scalar_rhs(value,kind,field,read)for value in node.comparators)
    if isinstance(node,ast.IfExp):
        return all(scalar_rhs(value,kind,field,read)for value in(node.test,node.body,node.orelse))
    return False
