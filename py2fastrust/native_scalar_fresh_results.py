"""Original-source certificates for fresh scalar-instance results and locals.

The certificates describe allocation and publication, separately from Python's
instance type. They do not change calls, source effects or shared parameters.
"""
import ast
from dataclasses import dataclass,field


class Unproved(Exception):
    pass


@dataclass
class Result:
    plan:object
    owner:object
    locals:set=field(default_factory=set)
    assignments:dict=field(default_factory=dict)
    returns:dict=field(default_factory=dict)
    fields:set=field(default_factory=set)


class Registry:
    def __init__(self,model):
        self.model=model
        self.values=model.value_classes
        self.plans={plan.index:plan for plan in model.plans if plan.reachable}
        self.results={}
        self.reasons={}
        self.active=set()
        for plan in self.plans.values():
            try:self.prove(plan)
            except Unproved:pass

    def owner(self,kind):
        from .native_classes import InstanceType
        if not isinstance(kind,InstanceType):return None
        owner=self.model.classes[kind.name]
        from .native_scalar_constructor_data import selected
        return owner if selected(self.model,owner)else None

    def reached(self,plan,node):
        points=getattr(self.model,'reached_statements',None)
        return points is None or(plan.index,id(node))in points

    def fresh_call(self,plan,node,owner):
        if not isinstance(node,ast.Call):return False
        if self.values.constructor(plan,node,owner):return True
        targets=self.model.call_edges_by_site.get((plan.index,id(node)),())
        if not targets:return False
        for index in targets:
            callee=self.plans.get(index)
            if callee is None:return False
            try:result=self.prove(callee)
            except Unproved:return False
            if result.owner is not owner:return False
        return True

    def prove(self,plan):
        if plan.index in self.results:return self.results[plan.index]
        if plan.index in self.reasons:raise Unproved(self.reasons[plan.index])
        if plan.index in self.active:raise Unproved('fresh result graph contains a source cycle')
        self.active.add(plan.index)
        try:
            from .native_classes import shape
            owner=self.owner(shape(plan.result))
            if owner is None or not isinstance(plan.node,ast.FunctionDef):
                raise Unproved('result is not one sealed scalar instance layout')
            if (self.model.is_module_plan(plan)or plan.node.type_params
                    or plan.signature.variadic_positional or plan.signature.variadic_keyword):
                raise Unproved('source definition has a different frame/binding contract')
            result=Result(plan,owner)
            flow=Flow(self,result)
            normal=flow.block(plan.node.body,set())
            if normal is not None or not result.returns:
                raise Unproved('not every normal source return produces a fresh instance')
            self.results[plan.index]=result
            return result
        except Unproved as error:
            self.reasons[plan.index]=str(error)
            raise
        finally:self.active.remove(plan.index)


class Flow:
    def __init__(self,registry,result):
        self.registry=registry
        self.result=result
        self.plan=result.plan
        self.owner=result.owner

    def name(self,node):return self.registry.model.resolved_name(self.plan,node)

    def private(self,node):
        return (isinstance(node,ast.Name)and self.name(node)not in self.plan.runtime_parameters
                and self.registry.values.local(self.plan,node,self.owner))

    def expression(self,node,state):
        if node is None:return
        if isinstance(node,ast.Attribute):
            if (isinstance(node.ctx,ast.Load)and self.registry.values.direct(self.plan,node.value,self.owner)
                    and self.name(node)in self.owner.fields):
                if isinstance(node.value,ast.Name)and self.private(node.value):
                    if self.name(node.value)not in state:
                        raise Unproved('a private scalar receiver is not fresh on every incoming path')
                    return
        if isinstance(node,ast.Name)and isinstance(node.ctx,ast.Load)and self.private(node):
            raise Unproved('a local instance is passed, aliased, captured or observed before return')
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda,
                            ast.GeneratorExp,ast.ListComp,ast.SetComp,ast.DictComp,ast.NamedExpr)):
            raise Unproved('nested binding or deferred publication needs a separate lifetime proof')
        for child in ast.iter_child_nodes(node):self.expression(child,state)

    def target(self,node,state):
        if isinstance(node,ast.Name):
            if self.private(node):raise Unproved('a private instance local has a nonfresh producer')
            return
        if isinstance(node,(ast.Tuple,ast.List)):
            for child in node.elts:self.target(child,state)
            return
        if (isinstance(node,ast.Attribute)and isinstance(node.value,ast.Name)
                and self.private(node.value)):
            if self.name(node.value)not in state or self.name(node)not in self.owner.fields:
                raise Unproved('a private field store lacks a fresh concrete receiver')
            self.result.fields.add(id(node))
            return
        self.expression(node,state)

    def block(self,body,incoming):
        state=set(incoming)
        for node in body:
            if not self.registry.reached(self.plan,node):continue
            if isinstance(node,(ast.Assign,ast.AnnAssign)):
                value=node.value
                targets=node.targets if isinstance(node,ast.Assign)else[node.target]
                if value is None:continue
                if (len(targets)==1 and self.private(targets[0])
                        and self.registry.fresh_call(self.plan,value,self.owner)):
                    self.expression(value,state)
                    name=self.name(targets[0]);state.add(name)
                    self.result.locals.add(name)
                    self.result.assignments[id(node)]=value
                else:
                    self.expression(value,state)
                    for target in targets:self.target(target,state)
            elif isinstance(node,ast.AugAssign):
                if (isinstance(node.target,ast.Attribute)and isinstance(node.target.value,ast.Name)
                        and self.private(node.target.value)):
                    self.target(node.target,state)
                else:self.expression(node.target,state)
                self.expression(node.value,state)
                self.target(node.target,state)
            elif isinstance(node,ast.If):
                self.expression(node.test,state)
                masks=getattr(self.registry.model,'type_guard_branches',{}).get((self.plan.index,id(node.test)))
                if masks is not None and not all(masks):
                    # Reuse the exact original guard certificate consumed by
                    # Emitter, rather than inventing a successful fallthrough
                    # through a branch which that emitter never executes.
                    state=self.block(node.body if masks[0]else node.orelse,state)
                    if state is None:return None
                    continue
                yes=self.block(node.body,state);no=self.block(node.orelse,state)
                normal=[branch for branch in(yes,no)if branch is not None]
                if not normal:return None
                state=set.intersection(*normal)
            elif isinstance(node,ast.Return):
                value=node.value
                if isinstance(value,ast.Name)and self.private(value)and self.name(value)in state:
                    self.result.returns[id(node)]=value
                elif self.registry.fresh_call(self.plan,value,self.owner):
                    self.expression(value,state)
                    self.result.returns[id(node)]=value
                else:raise Unproved('a returned instance may already be shared or uninitialized')
                return None
            elif isinstance(node,ast.Raise):
                self.expression(node.exc,state);self.expression(node.cause,state)
                return None
            elif isinstance(node,ast.Expr):self.expression(node.value,state)
            elif isinstance(node,ast.Assert):
                self.expression(node.test,state);self.expression(node.msg,state)
            elif not isinstance(node,ast.Pass):
                raise Unproved('source control flow needs another fresh-result transfer')
        return state
