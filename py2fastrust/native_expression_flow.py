"""Capture conditional expression operands once and preserve effect facts."""
import ast


def _widen(g,environment,slots):
    from .native import _Binding
    affected={name:binding for name,binding in environment.items()
              if isinstance(binding,_Binding) and binding.slot in slots}
    environment.update(g.after_loop(affected))


def _conditional_join(g,before,after,node):
    """Join metadata for an expression that may not execute.

    Ordinary expressions currently cannot replace caller bindings. Accepted
    mutations can invalidate cardinality/empty facts, so use the existing
    conservative container-fact join without changing physical Rust slots.
    """
    from .native import _Binding,_Unsupported
    if before.keys()!=after.keys():
        raise _Unsupported("conditional expression changes namespace bindings")
    affected=set()
    for name,previous in before.items():
        current=after[name]
        if previous==current:continue
        if not(isinstance(previous,_Binding) and isinstance(current,_Binding)
               and previous.slot==current.slot and previous.kind==current.kind):
            raise _Unsupported("conditional expression changes binding storage or type")
        affected.add(current.slot)
    _widen(g,after,affected)


def capture(g,children,environment,*,unconditional=1,read=False,node=None):
    """Lower descriptors once, joining facts for conditional later operands."""
    evaluate=getattr(g,"read_expression",g.expression) if read else g.expression
    checkpoint=len(g.expression_mutations)
    values=[]
    for index,child in enumerate(children):
        before=environment.copy()
        values.append(evaluate(child,environment))
        if index>=unconditional:
            _conditional_join(g,before,environment,node)
    # An enclosing BoolOp/IfExp can skip this entire expression, and nested
    # generators can report mutations from copied local environments. Never
    # retain a cardinality proof for any storage these operands may mutate.
    _widen(g,environment,{binding.slot for binding in g.expression_mutations[checkpoint:]})
    return values


def lower(g,node,environment):
    from .native import _Expression
    if isinstance(node,ast.Compare):
        values=capture(g,(node.left,*node.comparators),environment,
                       unconditional=2,read=True,node=node)
        from .native_comparison_lowering import compare_values
        return compare_values(g,node,values)
    if isinstance(node,ast.BoolOp):
        values=capture(g,node.values,environment,node=node)
        kind=g.scalar_kind(values)
        code=g.coerce(values[-1],kind)
        for value in reversed(values[:-1]):
            name=g.temporary()
            check=g.truth(_Expression(name,kind))
            yes,no=(code,name) if isinstance(node.op,ast.And)else(name,code)
            code=f"{{let {name}={g.coerce(value,kind)};if {check}{{{yes}}}else{{{no}}}}}"
        return _Expression(code,kind)
    assert isinstance(node,ast.IfExp)
    test=g.expression(node.test,environment)
    before=environment.copy()
    yes_environment=before.copy();no_environment=before.copy()
    checkpoint=len(g.expression_mutations)
    yes=g.expression(node.body,yes_environment)
    no=g.expression(node.orelse,no_environment)
    _conditional_join(g,before,yes_environment,node)
    _conditional_join(g,before,no_environment,node)
    merged=before.copy()
    for name in before:
        if yes_environment[name]!=before[name]:merged[name]=yes_environment[name]
        if no_environment[name]!=before[name]:merged[name]=no_environment[name]
    environment.clear();environment.update(merged)
    _widen(g,environment,{binding.slot for binding in g.expression_mutations[checkpoint:]})
    kind=g.scalar_kind([yes,no])
    return _Expression(f"(if {g.truth(test)}{{{g.coerce(yes,kind)}}}else{{{g.coerce(no,kind)}}})",kind)
