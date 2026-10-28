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


def capture(g,children,environment,*,unconditional=1,read=False,node=None,evaluate=None):
    """Lower descriptors once, joining facts for conditional later operands."""
    if evaluate is None:evaluate=getattr(g,"read_expression",g.expression) if read else g.expression
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


def branches(g,children,environment,*,node,evaluate):
    """Lower alternative branches from one state and join only effect metadata."""
    before=environment.copy();checkpoint=len(g.expression_mutations)
    environments=[];values=[]
    for child in children:
        inside=before.copy()
        values.append(evaluate(child,inside))
        _conditional_join(g,before,inside,node)
        environments.append(inside)
    merged=before.copy()
    for name in before:
        for inside in environments:
            if inside[name]!=before[name]:merged[name]=inside[name]
    environment.clear();environment.update(merged)
    _widen(g,environment,{binding.slot for binding in g.expression_mutations[checkpoint:]})
    return values


def lower(g,node,environment):
    from .native import _Expression
    from .native_types import rust_type
    if isinstance(node,ast.Compare):
        values=capture(g,(node.left,*node.comparators),environment,
                       unconditional=2,read=True,node=node)
        from .native_comparison_lowering import compare_values
        return compare_values(g,node,values)
    if isinstance(node,ast.BoolOp):
        values=capture(g,node.values,environment,node=node)
        from .native_expression_results import kind as result_kind
        kind=result_kind(g,values,node)
        code=g.coerce(values[-1],kind)
        for value in reversed(values[:-1]):
            name=g.temporary()
            check=g.truth(_Expression(name,kind))
            continued=f"{{drop({name});{code}}}"
            yes,no=(continued,name) if isinstance(node.op,ast.And)else(name,continued)
            code=f"{{let {name}:{rust_type(kind)}={g.coerce(value,kind)};if {check}{{{yes}}}else{{{no}}}}}"
        return _Expression(code,kind)
    assert isinstance(node,ast.IfExp)
    test=g.condition(node.test,environment)
    yes,no=branches(g,(node.body,node.orelse),environment,node=node,evaluate=g.expression)
    from .native_expression_results import kind as result_kind
    kind=result_kind(g,[yes,no],node)
    return _Expression(f"(if {g.truth(test)}{{{g.coerce(yes,kind)}}}else{{{g.coerce(no,kind)}}})",kind)
