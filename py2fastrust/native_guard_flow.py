"""Refine local value alternatives after a proved canonical type predicate."""
import ast

from .references import BuiltinIdentity


class AnalysisPending(Exception):
    """A guard consumer waits for its producing argument/type constraints."""


def descendant_readonly(model,owner,name):
    if not hasattr(model,'guard_readonly_bindings'):model.guard_readonly_bindings={}
    key=owner,name
    if key not in model.guard_readonly_bindings:
        model.guard_readonly_bindings[key]=not any(binding.owner==owner and binding.name==name
            and binding.scope!=owner and binding.role not in {'load','parameter'}
            for binding in model.iter_bindings())
    return model.guard_readonly_bindings[key]


def lexical_point(model,plan,node,environment,owner,name):
    if not hasattr(model,'type_guard_cells'):return None
    if owner!=model.lexical.scope(plan)or not descendant_readonly(model,owner,name):return None
    if name not in environment:return None
    if not hasattr(model,'guarded_lexical_reads'):model.guarded_lexical_reads=set()
    model.guarded_lexical_reads.add((plan.index,id(node)))
    return environment[name]


def lexical_store(model,plan,node,value,owner,name):
    if not hasattr(model,'type_guard_cells'):return None
    if owner!=model.lexical.scope(plan)or not descendant_readonly(model,owner,name):return None
    from .native_classes import Cell
    key=plan.index,id(node),'lexical_store',name
    point=model.type_guard_cells.setdefault(key,Cell())
    incoming=model.flow_copy(value)
    point.parent=None;point.tag,point.args=incoming.tag,incoming.args
    model.namespace.flow_cells.add(point)
    return point


def _classinfo(model,plan,node,environment):
    from .native_classes import shape
    from .native_module_linking import ClassReferenceType
    from .native_type_checks import TYPE_NAMES
    if isinstance(node,ast.Tuple):
        values=[]
        for child in node.elts:
            part=_classinfo(model,plan,child,environment)
            if part is None:return None
            values.extend(part)
        return values
    if not isinstance(node,ast.Name):return None
    direct=model.builtin_identity(plan,node,environment)
    if isinstance(direct,BuiltinIdentity)and direct.name in TYPE_NAMES:return [('builtin',direct.name)]
    value=model.records.get((plan.index,id(node)))
    if value is None:return None
    kind=shape(value)
    if isinstance(kind,ClassReferenceType):
        owner=next(owner for owner in model.classes.values()if owner.index==kind.definition)
        if not isinstance(owner.node,ast.ClassDef)or owner.node.bases or owner.node.keywords:return None
        return [('source',kind.definition)]
    targets=getattr(kind,'targets',())
    if len(targets)==1 and isinstance(targets[0],BuiltinIdentity)and targets[0].name in TYPE_NAMES:
        return [('builtin',targets[0].name)]
    return None


def _matches(model,value,classes):
    from .native_classes import shape,domain
    tag=domain(shape(value))
    possible=False
    for category,name in classes:
        if category=='source':
            if tag=='object'and model.classes[shape(value).name].index==name:return True
        elif name=='int':
            if tag in {'int','bool','int_bool'}:return True
        elif name=='bool'and tag=='int_bool':possible=True
        elif name=='tuple':
            if tag in {'tuple','tuple_sequence'}:return True
        elif name in {'map','zip','filter','enumerate'}:
            if tag=='iterator'and getattr(shape(value).record,'operation',None)==name:return True
        elif name=='reversed':
            # Several reverse cursor carriers represent different Python
            # classes. Their existing runtime predicate keeps that distinction.
            if tag=='iterator':possible=True
        elif tag==name:return True
    return None if possible else False


def branches(model,plan,test,environment):
    from .native_classes import Cell,Environment,ClassUnsupported,shape
    from .native_union_sequences import branches as choices
    negative=isinstance(test,ast.UnaryOp)and isinstance(test.op,ast.Not)
    call=test.operand if negative else test
    if not isinstance(call,ast.Call)or len(call.args)!=2 or call.keywords:return None
    if not isinstance(call.args[0],ast.Name):return None
    identity=model.builtin_identity(plan,call.func,environment)if isinstance(call.func,ast.Name)else None
    if identity!=BuiltinIdentity('isinstance'):
        site=model.callable_cells.sites.get((plan.index,id(call)))
        if site is None or getattr(shape(site.callee),'targets',())!=(BuiltinIdentity('isinstance'),):return None
    classes=_classinfo(model,plan,call.args[1],environment)
    if classes is None:return None
    subject=call.args[0]
    binding=model.namespace.owners.get(model.unit.ordinal(subject))if model.unit is not None else None
    owner=model.lexical.scope(plan)
    if binding is None or binding.owner!=owner or model.module_owner(owner):return None
    captured=model.lexical.environments.get(owner)
    name=model.resolved_name(plan,subject)
    if captured is not None and name in captured.fields and not descendant_readonly(model,owner,name):return None
    if name not in environment or name not in environment.definite:return None
    value=environment[name]
    members=list(choices(value))
    if any(member.tag is None for member in members):
        if not model.final:raise AnalysisPending()
        raise ClassUnsupported(subject,'type-guard refinement is waiting on an unresolved local value produced by a source call or allocation',proof='resolved type-guard input alternatives')
    selected=[[],[]]
    for member in members:
        matched=_matches(model,member,classes)
        for index,truth in enumerate((True,False)):
            if matched is None or matched==(not truth if negative else truth):selected[index].append(member)
    if not hasattr(model,'type_guard_cells'):model.type_guard_cells={}
    if not hasattr(model,'type_guard_branches'):model.type_guard_branches={}
    model.type_guard_branches[(plan.index,id(test))]=tuple(bool(part)for part in selected)
    schema=model.namespace.local_schemas.setdefault((plan.index,name),Cell())
    model.namespace.contribute(schema,value,test,force=True)
    model.canonical_local(plan,name,schema)
    result=[]
    for index,members in enumerate(selected):
        if not members:result.append(None);continue
        branch=Environment(environment)
        cell=model.type_guard_cells.setdefault((plan.index,id(test),index,name),Cell())
        copies=tuple(model.flow_copy(member)for member in members)
        replacement=copies[0]if len(copies)==1 else Cell('union',copies)
        cell.parent=None;cell.tag,cell.args=replacement.tag,replacement.args
        model.namespace.flow_cells.add(cell)
        branch[name]=cell
        result.append(branch)
    return tuple(result)


def emit(emitter,node,setup,test):
    masks=getattr(emitter.model,'type_guard_branches',{}).get((emitter.plan.index,id(node.test)))
    if masks is None or all(masks):return None
    statements=node.body if masks[0]else node.orelse
    return setup+'let _='+test.code+';'+emitter.statements(statements)
