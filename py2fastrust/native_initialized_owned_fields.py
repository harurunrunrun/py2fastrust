"""Definite field initialization permits plain storage in private owned objects.

The existing owner certificate rules out escaping partial objects, reflective
field access, deletion and source finalizers. A separate ordered must analysis
checks reads during construction, including reads through canonical methods.
Only allocation-free private placeholders are used; none is a Python value
until the original source store completes.
"""
import ast
from dataclasses import dataclass


class Unproved(Exception):
    pass


@dataclass(frozen=True)
class Summary:
    requires: bool
    ensures: bool


class Registry:
    def __init__(self,model):
        from .native_classes import shape
        self.model=model
        self.fields={}
        self.reasons={}
        self.summaries={}
        self.active=set()
        self.owners=getattr(model,'owned_object_places',None)
        if self.owners is None:return
        from .native_namespace_read_places import lifetime_closed
        if not lifetime_closed(model):return
        for owner in model.classes.values():
            if owner.index not in self.owners.selected:continue
            initializer=owner.methods.get('__init__')
            if initializer is None or shape(initializer.result)!='none':continue
            for index,(name,field)in enumerate(owner.fields.items()):
                key=owner.index,index
                initial=self.initial(owner,index,shape(field.cell))
                if initial is None:continue
                try:
                    summary=self.summary(owner,name,initializer)
                    if summary.requires:raise Unproved('a constructor path reads this field before its source assignment')
                    if not summary.ensures:raise Unproved('a normal constructor exit can leave this field undefined')
                except Unproved as error:self.reasons[key]=str(error)
                else:self.fields[key]=initial

    def initial(self,owner,index,kind):
        if kind=='int':return 'Int::from_i128(0)'if self.model.integer=='bigint'else'0'
        if kind in {'bool','float','none'}:return {'bool':'false','float':'0.0_f64','none':'()'}[kind]
        from .native_owned_class_lists import selected
        from .native_class_record_fields import selected as record
        info=selected(self.model,owner,index)
        if info is not None and record(self.model,info)is None:return 'Vec::new()'
        return None

    def summary(self,owner,field,plan):
        key=owner.index,field,plan.index
        if key in self.summaries:return self.summaries[key]
        if key in self.active:raise Unproved('initialization method summary has a recursive edge')
        self.active.add(key)
        try:
            flow=Flow(self,owner,field,plan)
            normal=flow.block(plan.node.body,False)
            exits=flow.returns+([]if normal is None else[normal])
            summary=Summary(flow.requires,bool(exits)and all(exits))
            self.summaries[key]=summary
            return summary
        finally:self.active.remove(key)


class Flow:
    def __init__(self,registry,owner,field,plan):
        from .native_classes import InstanceType,shape
        self.registry,self.model,self.owner,self.field,self.plan=registry,registry.model,owner,field,plan
        if not isinstance(plan.node,ast.FunctionDef)or not plan.runtime_parameters:
            raise Unproved('initialization entry has no canonical ordinary method body')
        self.parameter=plan.runtime_parameters[0]
        if ((plan.index,self.parameter)not in registry.owners.receivers
                or shape(plan.arguments[self.parameter])!=InstanceType(self.model.class_key(owner))):
            raise Unproved('initialization method receiver is not the certified owned receiver')
        from .native_frame_specialization import source_plan
        self.scope=self.model.lexical.scope(source_plan(plan))
        self.requires=False
        self.returns=[]

    def receiver(self,node):
        if not isinstance(node,ast.Name):return False
        binding=self.model.lexical.binding(node)
        return (binding is not None and binding.owner==self.scope
                and self.model.resolved_name(self.plan,node)==self.parameter
                and self.model.lexical.execution_scope(binding.scope)==self.scope)

    def is_field(self,node):
        return (isinstance(node,ast.Attribute)and self.receiver(node.value)
                and self.model.resolved_name(self.plan,node)==self.field)

    def read(self,state):
        if not state:self.requires=True
        return True

    def expression(self,node,state):
        if node is None:return state
        if isinstance(node,ast.Attribute):
            state=self.expression(node.value,state)
            return self.read(state)if self.is_field(node)and isinstance(node.ctx,ast.Load)else state
        if isinstance(node,ast.Call):
            state=self.expression(node.func,state)
            for argument in node.args:state=self.expression(argument,state)
            for keyword in node.keywords:state=self.expression(keyword.value,state)
            if isinstance(node.func,ast.Attribute)and self.receiver(node.func.value):
                name=self.model.resolved_name(self.plan,node.func)
                # A stored callback cannot reach this private receiver: the
                # owner certificate excludes passing/capturing/publishing it.
                # Reading the callback field itself was evaluated above.
                if name in self.owner.fields:return state
                if not self.registry.owners.canonical_method(self.plan,node,self.owner):
                    raise Unproved('receiver call has no complete canonical method targets')
                targets=self.model.call_edges_by_site.get((self.plan.index,id(node)),())
                if not targets:raise Unproved('receiver call has no reached source target')
                summaries=[self.registry.summary(self.owner,self.field,self.registry.owners.plans[index])for index in targets]
                if any(summary.requires for summary in summaries):state=self.read(state)
                state=state or all(summary.ensures for summary in summaries)
            return state
        if isinstance(node,ast.BoolOp):
            state=self.expression(node.values[0],state)
            branch=state
            for child in node.values[1:]:branch=self.expression(child,branch)
            return state
        if isinstance(node,ast.IfExp):
            state=self.expression(node.test,state)
            yes=self.expression(node.body,state)
            no=self.expression(node.orelse,state)
            return yes and no
        if isinstance(node,ast.Dict):
            for key,value in zip(node.keys,node.values):
                state=self.expression(key,state)
                state=self.expression(value,state)
            return state
        if isinstance(node,ast.Compare):
            state=self.expression(node.left,state)
            if not node.comparators:return state
            state=self.expression(node.comparators[0],state)
            branch=state
            for child in node.comparators[1:]:branch=self.expression(child,branch)
            return state
        if isinstance(node,(ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp)):
            if not node.generators:raise Unproved('comprehension has no original generator')
            state=self.expression(node.generators[0].iter,state)
            branch=state
            for index,generator in enumerate(node.generators):
                if index:branch=self.expression(generator.iter,branch)
                for condition in generator.ifs:branch=self.expression(condition,branch)
            for child in ([node.key,node.value]if isinstance(node,ast.DictComp)else[node.elt]):
                branch=self.expression(child,branch)
            return state
        if isinstance(node,ast.Lambda):
            for child in [*node.args.defaults,*[value for value in node.args.kw_defaults if value is not None]]:
                state=self.expression(child,state)
            return state
        if isinstance(node,ast.NamedExpr):return self.target(node.target,self.expression(node.value,state))
        if isinstance(node,(ast.Yield,ast.YieldFrom,ast.Await)):
            raise Unproved('field initialization crosses suspended source evaluation')
        for child in ast.iter_child_nodes(node):state=self.expression(child,state)
        return state

    def target(self,node,state,*,read=False):
        if isinstance(node,(ast.Tuple,ast.List)):
            for child in node.elts:state=self.target(child,state,read=read)
            return state
        if isinstance(node,ast.Starred):return self.target(node.value,state,read=read)
        if isinstance(node,ast.Attribute):
            state=self.expression(node.value,state)
            if self.is_field(node):
                if read:state=self.read(state)
                return True
            return state
        if isinstance(node,ast.Subscript):
            return self.expression(node.slice,self.expression(node.value,state))
        if isinstance(node,ast.Name):return state
        raise Unproved('assignment target has no ordered field-state transfer')

    def block(self,statements,state):
        for node in statements:
            if state is None:return None
            if isinstance(node,ast.Assign):
                state=self.expression(node.value,state)
                for target in node.targets:state=self.target(target,state)
            elif isinstance(node,ast.AnnAssign):
                if node.value is None:raise Unproved('annotation-only target evaluation retains optional field storage')
                state=self.target(node.target,self.expression(node.value,state))
            elif isinstance(node,ast.AugAssign):
                state=self.target(node.target,state,read=True)
                state=self.expression(node.value,state)
            elif isinstance(node,ast.Expr):state=self.expression(node.value,state)
            elif isinstance(node,ast.If):
                state=self.expression(node.test,state)
                branches=[self.block(node.body,state),self.block(node.orelse,state)]
                normal=[value for value in branches if value is not None]
                state=all(normal)if normal else None
            elif isinstance(node,(ast.For,ast.While)):
                state=self.expression(node.iter if isinstance(node,ast.For)else node.test,state)
                branch=self.target(node.target,state)if isinstance(node,ast.For)else state
                self.block(node.body,branch)
                otherwise=self.block(node.orelse,state)
                # A loop may take zero iterations; a break can skip its else.
                breaking=any(isinstance(child,ast.Break)for statement in node.body for child in ast.walk(statement))
                state=state if breaking else otherwise
            elif isinstance(node,ast.Return):
                self.returns.append(self.expression(node.value,state));state=None
            elif isinstance(node,ast.Raise):
                self.expression(node.cause,self.expression(node.exc,state));state=None
            elif isinstance(node,ast.Assert):
                state=self.expression(node.test,state)
                self.expression(node.msg,state)
            elif isinstance(node,(ast.Break,ast.Continue)):state=None
            elif isinstance(node,(ast.Pass,ast.Global,ast.Nonlocal)):pass
            else:raise Unproved('source control needs an explicit initialized-field transfer: '+type(node).__name__)
        return state


def prepare(model):model.initialized_owned_fields=Registry(model)


def selected(model,owner,index):
    return(owner.index,index)in getattr(getattr(model,'initialized_owned_fields',None),'fields',{})


def initial(model,owner,index):return model.initialized_owned_fields.fields[owner.index,index]


def wrap(model,owner,index,value):return value if selected(model,owner,index)else'Some('+value+')'
