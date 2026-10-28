"""Consume Python expressions only for truth, without constructing their value union.

Rust's boolean operators keep source-order short circuiting. Accepted leaves use
builtin truth protocols; user-defined truth/destruction protocols retain their
existing explicit unsupported boundary. Value-returning and/or are separate.
"""
import ast

from .call_semantics import CallBindingError,FunctionSignature,normalize_call


_BOOL_SIGNATURE=FunctionSignature.declaration(('obj',),positional_only=('obj',),default_names=('obj',))


def lower(g,node,environment=None):
    from .native import _Expression
    if isinstance(node,ast.BoolOp):
        if environment is None:
            values=[g.condition(child)for child in node.values]
        else:
            from .native_expression_flow import capture
            values=capture(g,node.values,environment,node=node,evaluate=g.condition)
        operator='&&'if isinstance(node.op,ast.And)else'||'
        code='('+operator.join('('+value.code+')'for value in values)+')'
        constants=[value.constant for value in values]
        constant=(all(constants)if isinstance(node.op,ast.And)else any(constants))if all(value is not None for value in constants)else None
        return _Expression(code,'bool',constant)
    if isinstance(node,ast.UnaryOp)and isinstance(node.op,ast.Not):
        value=g.condition(node.operand)if environment is None else g.condition(node.operand,environment)
        return _Expression('!('+value.code+')','bool',None if value.constant is None else not value.constant)
    if isinstance(node,ast.IfExp):
        test=g.condition(node.test)if environment is None else g.condition(node.test,environment)
        if environment is None:
            yes,no=g.condition(node.body),g.condition(node.orelse)
        else:
            from .native_expression_flow import branches
            yes,no=branches(g,(node.body,node.orelse),environment,node=node,evaluate=g.condition)
        constant=(yes.constant if test.constant else no.constant)if test.constant is not None else None
        return _Expression('(if '+test.code+'{'+yes.code+'}else{'+no.code+'})','bool',constant)
    if environment is None:
        return g.condition_leaf(node)
    value=g.expression(node,environment)
    constant=(False if value.kind=='none'else bool(value.constant)if value.constant is not None else None)
    return _Expression(g.truth(value),'bool',constant)


def try_expression(g,node,environment):
    from .native import _Expression,_Unsupported
    if isinstance(node,ast.UnaryOp)and isinstance(node.op,ast.Not):
        return g.condition(node,environment)
    if not isinstance(node,ast.Call):return None
    from .references import BuiltinIdentity,callable_reference
    if callable_reference(g,node.func,environment)!=BuiltinIdentity('bool'):return None
    try:
        plan=_BOOL_SIGNATURE.plan(normalize_call(node))
        bound=plan.capture(lambda expression,parameter:g.condition(expression,environment),
                           defaults={'obj':_Expression('false','bool',False)})
    except CallBindingError as error:
        raise _Unsupported('builtin bool requires zero or one positional argument; this call binding or its Python TypeError is not implemented ('+str(error)+')',node=node,operation='builtin bool argument binding')from error
    return bound['obj']
