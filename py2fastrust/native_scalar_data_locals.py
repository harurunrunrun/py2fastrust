"""Concrete scalar snapshots within closed, straight-line loop iterations.

An official binding must be defined once in one iteration body and used only
there, through scalar fields or read-only source formals. Every reachable call
and operator phase in that body must preserve already published instances.
The backing list and any external aliases keep their ordinary shared handles.
"""
import ast


class Registry:
    def __init__(self,model):
        self.model=model
        self.values=model.value_classes
        self.locals={}
        self.assignments={}
        self.reasons={}
        self.safe={}
        self.active=set()
        self.data=model.scalar_data_results
        if model.unit is None:return
        rows=tuple(model.iter_bindings())
        nodes={model.unit.ordinal(node):node for node in model.iter_nodes()}
        from .native_class_identity_demand import Unproved
        for plan in model.plans:
            if not plan.reachable or model.is_module_plan(plan):continue
            scope=model.lexical.scope(plan)
            for loop in self.values.own_nodes(plan):
                if not isinstance(loop,(ast.For,ast.While)):continue
                body=loop.body
                if not body or any(not isinstance(node,(ast.Assign,ast.AnnAssign,ast.Expr,ast.Pass))for node in body):continue
                inside={id(child)for node in body for child in ast.walk(node)}
                positions={id(child):position for position,node in enumerate(body)for child in ast.walk(node)}
                candidates=[]
                for node in body:
                    targets=node.targets if isinstance(node,ast.Assign)else[node.target]if isinstance(node,ast.AnnAssign)else[]
                    if len(targets)!=1 or not isinstance(targets[0],ast.Name)or node.value is None:continue
                    target=targets[0];name=model.resolved_name(plan,target)
                    if name in plan.runtime_parameters:continue
                    owner=self.data.fresh.owner(self.kind(plan,target))
                    if owner is None or not self.values.local(plan,target,owner):continue
                    uses=[row for row in rows if row.owner==scope and row.name==name]
                    stores=[row for row in uses if row.role!='load']
                    if len(stores)!=1 or stores[0].node!=model.unit.ordinal(target):continue
                    loads=[nodes.get(row.node)for row in uses if row.role=='load']
                    if (not loads or any(row.scope!=scope for row in uses)
                            or any(value is None or id(value)not in inside for value in loads)):
                        continue
                    if any(positions[id(value)]<=positions[id(node)]for value in loads):continue
                    if not all(self.read_only_use(plan,value)for value in loads):continue
                    if not self.producer(plan,node.value,owner):continue
                    try:model.class_identity_demand.prove(owner)
                    except Unproved:continue
                    if not all(self.node_safe(plan,value,owner)for value in body):continue
                    candidates.append((node,name,owner))
                for node,name,owner in candidates:
                    self.locals[plan.index,name]=owner
                    self.assignments[plan.index,id(node)]=owner

    def kind(self,plan,node):return self.values.kind(plan,node)

    def targets(self,plan,node):
        site=self.model.callable_cells.sites.get((plan.index,id(node)))
        if site is not None and(site.errors or site.builtins or site.members or site.constructors or site.exception_constructors):return ()
        indexes=self.model.call_edges_by_site.get((plan.index,id(node)),())
        if any(index not in self.values.plans for index in indexes):return ()
        return tuple(self.values.plans[index]for index in indexes)

    def phases(self,plan,node):
        site=self.model.operators.sites.get((plan.index,id(node),None))
        if site is None or not site.branches:return ()
        plans=[]
        for branch in site.branches.values():
            if not branch.complete or branch.fallback is not None or len(branch.phases)!=1:return ()
            call=branch.phases[0].site
            if call.errors or call.builtins or call.members or call.constructors or call.exception_constructors:return ()
            if not call.targets:return ()
            for target in call.targets:
                definition=getattr(target,'definition',target)
                callee=self.model.callable_cells.plans.get(definition)
                if callee is None:return ()
                plans.append(callee)
        return tuple(plans)

    def view_formals(self,plans):
        from .native_scalar_data_parameters import parameter
        from .native_classes import InstanceType,shape
        return bool(plans)and all(parameter(self.model,plan,name)is not None
            for plan in plans for name in plan.runtime_parameters
            if isinstance(shape(plan.arguments[name]),InstanceType))

    def read_only_use(self,plan,node):
        parent=self.values.parents.get(id(node))
        if isinstance(parent,ast.Attribute)and parent.value is node:
            owner=self.data.fresh.owner(self.kind(plan,node))
            if isinstance(parent.ctx,ast.Load)and self.model.resolved_name(plan,parent)in owner.fields:return True
            call=self.values.parents.get(id(parent))
            return isinstance(call,ast.Call)and call.func is parent and self.view_formals(self.targets(plan,call))
        if isinstance(parent,ast.BinOp):return self.view_formals(self.phases(plan,parent))
        if isinstance(parent,ast.Call):
            from .native_source_native_effects import _identity,sealed_builtin
            identity=_identity(self,plan,parent.func)
            if (getattr(identity,'name',None)=='isinstance'and parent.args and parent.args[0]is node
                    and sealed_builtin(self.model,identity,[self.kind(plan,arg)for arg in parent.args])):return True
            return self.view_formals(self.targets(plan,parent))
        return False

    def producer(self,plan,node,owner):
        from .native_types import ListType
        if isinstance(node,ast.Subscript)and not isinstance(node.slice,ast.Slice):
            container=self.kind(plan,node.value)
            return isinstance(container,ListType)and self.kind(plan,node)==container.element and self.data.fresh.owner(container.element)is owner
        return self.data.expression(plan,node)is owner

    def plan_safe(self,plan,owner):
        key=plan.index,owner.index
        if key in self.safe:return self.safe[key]
        if key in self.active:return False
        self.active.add(key)
        try:
            from .native_class_calls import synchronous
            result=(synchronous(self.model,plan)and isinstance(plan.node,ast.FunctionDef)
                    and all(self.node_safe(plan,node,owner)for node in plan.node.body))
            self.safe[key]=result
            return result
        finally:self.active.remove(key)

    def node_safe(self,plan,node,owner):
        from .native_classes import InstanceType
        from .native_list_positions import closed
        from .native_source_native_effects import _identity,sealed_builtin,comparison_closed
        from .references import BuiltinIdentity
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda,
                            ast.GeneratorExp,ast.ListComp,ast.SetComp,ast.DictComp,
                            ast.NamedExpr,ast.Yield,ast.YieldFrom,ast.Await,ast.With,
                            ast.Try,ast.TryStar,ast.Delete,ast.For,ast.While,ast.AsyncFor)):return False
        if isinstance(node,(ast.If,ast.IfExp,ast.BoolOp)):
            conditions=node.values[:-1]if isinstance(node,ast.BoolOp)else[node.test]
            if not all(sealed_builtin(self.model,BuiltinIdentity('bool'),[self.kind(plan,value)])for value in conditions):return False
        if isinstance(node,ast.If):
            if not self.node_safe(plan,node.test,owner):return False
            mask=getattr(self.model,'type_guard_branches',{}).get((plan.index,id(node.test)))
            branches=(node.body if mask[0]else node.orelse,)if mask is not None and not all(mask)else(node.body,node.orelse)
            return all(self.node_safe(plan,child,owner)for body in branches for child in body)
        if isinstance(node,ast.Attribute):
            receiver=self.kind(plan,node.value)
            if isinstance(receiver,InstanceType):
                actual=self.model.classes[receiver.name]
                from .native_copy_scalar_fields import selected
                if not selected(self.model,actual):return False
                field=self.model.resolved_name(plan,node)
                if field not in actual.fields:
                    parent=self.values.parents.get(id(node))
                    if not isinstance(parent,ast.Call)or parent.func is not node or not self.targets(plan,parent):return False
                if isinstance(node.ctx,(ast.Store,ast.Del))and actual is owner:
                    fresh=self.data.fresh.results.get(plan.index)
                    initializer=owner.methods.get('__init__')
                    allowed=(initializer is plan and isinstance(node.value,ast.Name)
                             and self.model.resolved_name(plan,node.value)==plan.runtime_parameters[0])
                    if not allowed and(fresh is None or id(node)not in fresh.fields):return False
        if isinstance(node,ast.Subscript):
            from .native_types import ListType,TupleType,TupleSequenceType
            if (not isinstance(self.kind(plan,node.value),(ListType,TupleType,TupleSequenceType))
                    or self.kind(plan,node.slice)not in {'int','bool','int_bool'}):return False
        if isinstance(node,ast.Call):
            constructor=next((candidate for candidate in self.model.classes.values()
                              if candidate.index in self.model.scalar_constructor_data.owners
                              and self.values.constructor(plan,node,candidate)),None)
            plans=self.targets(plan,node)
            if constructor is not None:
                if not self.plan_safe(constructor.methods['__init__'],owner):return False
            elif plans:
                if not all(self.plan_safe(target,owner)for target in plans):return False
            else:
                identity=_identity(self,plan,node.func)
                if not sealed_builtin(self.model,identity,[self.kind(plan,arg)for arg in node.args]+[self.kind(plan,arg.value)for arg in node.keywords]):return False
        if isinstance(node,(ast.BinOp,ast.UnaryOp,ast.AugAssign)):
            operands=([node.left,node.right]if isinstance(node,ast.BinOp)else
                      [node.target,node.value]if isinstance(node,ast.AugAssign)else[node.operand])
            if not all(closed(self.kind(plan,value))for value in operands):
                phases=self.phases(plan,node)
                if not phases or not all(self.plan_safe(target,owner)for target in phases):return False
        if isinstance(node,ast.Compare):
            operands=[node.left,*node.comparators]
            if not all(comparison_closed(self.kind(plan,left),operator,self.kind(plan,right))
                       for left,operator,right in zip(operands,node.ops,operands[1:])):return False
        return all(self.node_safe(plan,child,owner)for child in ast.iter_child_nodes(node))


def prepare(model):model.scalar_data_locals=Registry(model)


def owner(emitter,name):
    return getattr(getattr(emitter.model,'scalar_data_locals',None),'locals',{}).get((emitter.plan.index,name))


def local_type(emitter,name):
    selected=owner(emitter,name)
    return None if selected is None else'ClassData_'+str(selected.index)


def data_value(emitter,node,selected):
    from .native_classes import Expression
    if isinstance(node,ast.Subscript):
        setup,place=emitter.reference(node)
        if place[0]=='list_region':
            _,region,index,_=place
            values='&'+region.storage()
        elif place[0]=='owned_local_list':
            from .native_owned_local_lists import checked
            _,local,index,_=place
            values=checked(emitter,local,node.value)
        elif place[0]=='index':
            _,container,index,_=place
            guard=emitter.fresh()
            setup+='let '+guard+'='+container.code+'.borrow();'
            values='&'+guard
        else:
            value=emitter.expression(node);result=emitter.fresh()
            return Expression('{let '+result+'='+value.code+';(*'+result+').clone()}',value.kind)
        result=emitter.fresh()
        value=emitter.at('class_slice_get('+values+',&('+emitter.number(index)+'))',node)
        return Expression('{'+setup+'let '+result+'='+value+';(**'+result+').clone()}',emitter.kind(node))
    from .native_scalar_data_results import data_value as fresh_value
    return fresh_value(emitter,node,selected)


def statement(emitter,node):
    selected=getattr(getattr(emitter.model,'scalar_data_locals',None),'assignments',{}).get((emitter.plan.index,id(node)))
    if selected is None:return None
    target=node.targets[0]if isinstance(node,ast.Assign)else node.target
    before,value=emitter.capture(data_value(emitter,node.value,selected))
    return before+emitter.assign(target,value)
