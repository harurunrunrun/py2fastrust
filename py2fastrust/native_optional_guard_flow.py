"""Refine optional local bindings after their actual identity/truth observer."""
import ast


def branches(model,plan,test,environment):
    from .native_classes import Cell,Environment,shape
    from .native_guard_flow import descendant_readonly,AnalysisPending
    from .native_union_sequences import branches as alternatives
    inverted=False;operand=test
    while isinstance(operand,ast.UnaryOp)and isinstance(operand.op,ast.Not):
        inverted=not inverted;operand=operand.operand
    subject=None;identity=False;is_none=False
    if isinstance(operand,ast.Compare)and len(operand.ops)==1:
        operator=operand.ops[0]
        if isinstance(operator,(ast.Is,ast.IsNot)):
            left,right=operand.left,operand.comparators[0]
            if isinstance(left,ast.Constant)and left.value is None:left,right=right,left
            if isinstance(left,ast.Name)and isinstance(right,ast.Constant)and right.value is None:
                subject=left;identity=True;is_none=isinstance(operator,ast.Is)
    elif isinstance(operand,ast.Name):subject=operand
    if subject is None:return None
    binding=model.namespace.owners.get(model.unit.ordinal(subject))if model.unit is not None else None
    scope=model.lexical.scope(plan)
    if binding is None or binding.owner!=scope or model.module_owner(scope):return None
    name=model.resolved_name(plan,subject)
    captured=model.lexical.environments.get(scope)
    if captured is not None and name in captured.fields and not descendant_readonly(model,scope,name):return None
    if name not in environment or name not in environment.definite:return None
    observed=model.records.get((plan.index,id(subject)))
    value=environment[name]
    # Identity tests never invoke a user method. Truth observers have already
    # executed their analyzed callbacks. A captured local is eligible only
    # without descendant writers; its ABI schema may differ from this point
    # value even though both denote the same official binding.
    if observed is None:return None
    members=list(alternatives(value))
    if any(member.tag is None for member in members):
        if not model.final:raise AnalysisPending()
        return None
    if not any(member.tag=='none'for member in members):return None
    selected=[[],[]]
    for member in members:
        for index,truth in enumerate((True,False)):
            actual=not truth if inverted else truth
            if identity:possible=(member.tag=='none')==(is_none if actual else not is_none)
            else:possible=not actual or member.tag!='none'
            if possible:selected[index].append(member)
    if not hasattr(model,'type_guard_cells'):model.type_guard_cells={}
    if not hasattr(model,'type_guard_branches'):model.type_guard_branches={}
    model.type_guard_branches[plan.index,id(test)]=tuple(bool(part)for part in selected)
    schema=model.namespace.local_schemas.setdefault((plan.index,name),Cell())
    model.namespace.contribute(schema,value,test,force=True)
    model.canonical_local(plan,name,schema)
    result=[]
    for index,parts in enumerate(selected):
        if not parts:result.append(None);continue
        inside=Environment(environment)
        cell=model.type_guard_cells.setdefault((plan.index,id(test),'optional',index,name),Cell())
        copies=tuple(model.flow_copy(part)for part in parts)
        replacement=copies[0]if len(copies)==1 else Cell('union',copies)
        cell.parent=None;cell.tag,cell.args=replacement.tag,replacement.args
        cell.list_origins=replacement.list_origins
        model.namespace.flow_cells.add(cell);inside[name]=cell
        result.append(inside)
    return tuple(result)
