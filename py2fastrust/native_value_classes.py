"""Closed-world immutable instance capabilities and fresh local field writes.

Every selection is tied to solved source types, canonical call sites and official
binding owners. Rejected proofs retain the existing native reference layout.
"""
import ast
from dataclasses import dataclass


class Unproved(Exception):
    pass


@dataclass
class Edges:
    normal: object
    breaks: list
    continues: list


def join(states):
    states=[state for state in states if state is not None]
    if not states:return None
    names=set().union(*(state.keys()for state in states))
    # A fresh binding is established independently by each real constructor
    # execution. Never equate identities merely because allocation sites match.
    return {name:True for name in names if all(state.get(name,False)for state in states)}


class Registry:
    def __init__(self,model):
        self.model=model
        self.selected=set()
        self.reasons={}
        self.references={}
        self.initializers={}
        self.parents={id(child):node for node in model.iter_nodes()for child in ast.iter_child_nodes(node)}
        self.bindings={binding.node:binding for binding in model.iter_bindings()}
        self.plans={plan.index:plan for plan in model.plans if plan.reachable}
        self.nodes={id(node):node for node in model.iter_nodes()}
        for owner in model.classes.values():
            if not owner.used:continue
            refs={}
            try:
                self.prove(owner,refs)
            except Unproved as error:self.reasons[owner.index]=str(error)
            else:
                self.selected.add(owner.index)
                self.references.update(refs)
                initializer=owner.methods.get('__init__')
                if initializer is not None:self.initializers[initializer.index]=owner

    def kind(self,plan,node):
        from .native_classes import shape
        cell=self.model.records.get((plan.index,id(node)))
        return None if cell is None else shape(cell)

    def contains(self,kind,owner,seen=frozenset()):
        from .native_classes import InstanceType
        from .native_types import ListType,TupleType,TupleSequenceType,DequeType,MaybeType,NullableType,UnionType
        if isinstance(kind,InstanceType):return kind.name==self.model.class_key(owner)
        if id(kind)in seen:return False
        seen=seen|{id(kind)}
        if isinstance(kind,(ListType,TupleSequenceType,DequeType)):return self.contains(kind.element,owner,seen)
        if isinstance(kind,(MaybeType,NullableType)):return self.contains(kind.value,owner,seen)
        if isinstance(kind,TupleType):return any(self.contains(child,owner,seen)for child in kind.fields)
        if isinstance(kind,UnionType):return any(self.contains(child,owner,seen)for child in kind.alternatives)
        return any(self.contains(child,owner,seen)for child in getattr(kind,'_native_owned_kinds',()))

    def direct(self,plan,node,owner):
        from .native_classes import InstanceType
        kind=self.kind(plan,node)
        return isinstance(kind,InstanceType)and kind.name==self.model.class_key(owner)

    def observer_names(self,kind,seen=frozenset()):
        from .native_types import ListType,TupleType,TupleSequenceType,DequeType,MaybeType,NullableType,UnionType
        from .references import BuiltinIdentity
        if id(kind)in seen:return set()
        seen=seen|{id(kind)}
        names={value.name for value in getattr(kind,'builtins',())if isinstance(value,BuiltinIdentity)}
        children=getattr(kind,'_native_owned_kinds',())
        if isinstance(kind,(ListType,TupleSequenceType,DequeType)):children=(*children,kind.element)
        elif isinstance(kind,(MaybeType,NullableType)):children=(*children,kind.value)
        elif isinstance(kind,TupleType):children=(*children,*kind.fields)
        elif isinstance(kind,UnionType):children=(*children,*kind.alternatives)
        for child in children:names.update(self.observer_names(child,seen))
        return names&{'print','str','repr','format','id','hash','sorted','min','max',
                      'locals','globals','vars','eval','exec','compile','getattr','setattr','delattr'}

    def argument_kind(self,plan,node):
        return self.kind(plan,node.value if isinstance(node,ast.Starred)else node)

    def own_nodes(self,plan):
        if getattr(plan,'_native_retained_expression',False):
            clause=plan.node.generators[0]
            roots=[clause.target,*clause.ifs,plan.node.elt]
        else:
            roots=plan.node.body if isinstance(plan.node.body,list)else[plan.node.body]
        stack=list(reversed(roots))
        while stack:
            node=stack.pop();yield node
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                stack.extend(reversed([*node.decorator_list,*node.args.defaults,
                                       *[value for value in node.args.kw_defaults if value is not None]]))
                continue
            if isinstance(node,ast.ClassDef):
                stack.extend(reversed([*node.decorator_list,*node.bases,
                                       *[keyword.value for keyword in node.keywords]]))
                continue
            if isinstance(node,ast.Lambda)and node is not plan.node:
                # Its reached FunctionPlan owns its body; defaults are evaluated
                # here and are covered by capture and fresh-name uses below.
                stack.extend(reversed([*node.args.defaults,*[x for x in node.args.kw_defaults if x is not None]]))
                continue
            retained=getattr(self.model,'retained_generators',None)
            if isinstance(node,ast.GeneratorExp)and retained is not None and (plan.index,id(node))in retained.sites:
                stack.append(node.generators[0].iter)
                continue
            stack.extend(reversed(list(ast.iter_child_nodes(node))))

    def constructor(self,plan,node,owner):
        if not isinstance(node,ast.Call):return False
        from .native_classes import shape
        from .native_module_linking import ClassReferenceType
        key=(plan.index,id(node))
        linker=getattr(self.model,'module_linker',None)
        site=self.model.callable_cells.sites.get(key)
        if site is not None and(site.targets or site.errors or site.builtins or site.members or site.exception_constructors):
            return False
        callee=self.kind(plan,node.func)
        exact=isinstance(callee,ClassReferenceType)and callee.definition==owner.index
        if linker is not None and linker.class_calls.get(key)is owner:
            return exact
        if site is not None:
            actual=[record.owner for record in site.constructors.values()if record.error is None]
            captured=shape(site.callee)
            if(actual and all(item is owner for item in actual)
                    and isinstance(captured,ClassReferenceType)and captured.definition==owner.index):return True
        # The original nonlinked model's direct class-name path is sealed by
        # discovery and canonical binding resolution, not by a source spelling.
        binding=(self.bindings.get(self.model.unit.ordinal(node.func))
                 if self.model.unit is not None and isinstance(node.func,ast.Name)else None)
        return (linker is None and isinstance(node.func,ast.Name)
                and binding is not None and self.model.module_owner(binding.owner)
                and self.model.resolved_name(plan,node.func)not in plan.declared
                and self.model.resolved_name(plan,node.func)==self.model.class_key(owner)
                and self.direct(plan,node,owner))

    def local(self,plan,node,owner):
        from .native_classes import InstanceType
        if not isinstance(node,ast.Name)or self.model.is_module_plan(plan):return False
        if self.model.namespace.owns(plan,node)or self.model.lexical.field_for(node)is not None:return False
        name=self.model.resolved_name(plan,node)
        stored=self.model.namespace.local_kind(plan,name)
        return (self.direct(plan,node,owner)and name in plan.locals
                and(stored is None or stored==InstanceType(self.model.class_key(owner))))

    def builtin(self,plan,node):
        from .references import BuiltinIdentity
        from .native_classes import shape
        kind=self.kind(plan,node.func)
        values=getattr(kind,'builtins',())
        result={value.name for value in values if isinstance(value,BuiltinIdentity)}
        if isinstance(node.func,ast.Name):
            identity=self.model.builtin_identity(plan,node.func,{})
            if isinstance(identity,BuiltinIdentity):result.add(identity.name)
        return result

    def prove(self,owner,refs):
        from .native_copy_scalar_fields import selected
        from .native_class_calls import synchronous
        from .native_classes import InstanceType,shape
        from .native_module_linking import ClassReferenceType
        if not selected(self.model,owner):raise Unproved('fields are not closed Copy scalar slots or require collection')
        if owner.node.bases or owner.node.keywords or owner.node.decorator_list or owner.node.type_params:
            raise Unproved('inheritance, metaclasses or class replacement require reference identity')
        if any(name in owner.methods for name in('__new__','__del__','__setattr__','__getattribute__','__getattr__','__delattr__')):
            raise Unproved('custom allocation, attribute protocols or finalizers')
        initializer=owner.methods.get('__init__')
        self_name=None
        if initializer is not None:
            if not synchronous(self.model,initializer):raise Unproved('borrowed initializer would cross a suspended frame')
            if initializer.node.decorator_list:raise Unproved('initializer is not a plain bound source function')
            self_name=initializer.runtime_parameters[0]
            if shape(initializer.arguments[self_name])!=InstanceType(self.model.class_key(owner)):
                raise Unproved('initializer receiver does not have one concrete instance layout')
            for(scope,node_id),targets in self.model.call_edges_by_site.items():
                if initializer.index in targets:
                    call=self.nodes.get(node_id)
                    caller=self.plans.get(scope)
                    if caller is None or call is None or not self.constructor(caller,call,owner):
                        raise Unproved('initializer is invoked outside fresh canonical construction')
            scope=self.model.lexical.scope(initializer)
            for node in ast.walk(initializer.node):
                if not isinstance(node,ast.Name)or self.model.resolved_name(initializer,node)!=self_name:continue
                parent=self.parents.get(id(node))
                field=(isinstance(parent,ast.Attribute)and parent.value is node
                       and self.model.resolved_name(initializer,parent)in owner.fields)
                binding=self.bindings.get(self.model.unit.ordinal(node))if self.model.unit is not None else None
                if not isinstance(node.ctx,ast.Load)or not field or binding is not None and binding.scope!=scope:
                    raise Unproved('initializer receiver escapes, aliases or invokes a receiver method')
        namespace=getattr(self.model,'class_namespaces',None)
        for plan in self.plans.values():
            if getattr(plan.node,'decorator_list',())and any(self.contains(shape(value),owner)for value in[*plan.arguments.values(),plan.result]):
                member=(None if namespace is None or plan.owner is None else namespace.members.get((plan.owner.index,self.model.definition_name(plan.node))))
                if member is None or member.descriptor!='classmethod':
                    raise Unproved('decorated source frame has no closed ordinary callable capability')
            for node in self.own_nodes(plan):
                kind=self.kind(plan,node)
                if isinstance(node,ast.Call):
                    names=self.builtin(plan,node)
                    if names&{'locals','globals','vars','eval','exec','compile','getattr','setattr','delattr'}:
                        raise Unproved('reachable reflective namespace or attribute observer')
                    arguments=[*node.args,*(part.value for part in node.keywords)]
                    kinds=[self.argument_kind(plan,value)for value in arguments]
                    if isinstance(node.func,ast.Attribute):kinds.append(self.kind(plan,node.func.value))
                    observed=any(self.contains(value,owner)for value in kinds)
                    if observed and any(self.observer_names(value)for value in kinds):
                        raise Unproved('instance reaches an indirect builtin identity, representation or namespace observer')
                    if observed and names&{'print','str','repr','format','id','hash','sorted','min','max'}:
                        raise Unproved('instance or container identity/representation/comparison observer')
                    from .native_types import ListType,TupleType,TupleSequenceType
                    sealed=(isinstance(node.func,ast.Attribute)
                            and type(self.kind(plan,node.func.value))in {ListType,TupleType,TupleSequenceType}
                            and node.func.attr in {'append','extend','insert','pop','clear','reverse','copy','__len__'})
                    if observed and not names and not sealed and not self.model.call_edges_by_site.get((plan.index,id(node))):
                        raise Unproved('instance crosses a call without closed source effects')
                if isinstance(node,ast.Assert)and node.msg is not None and self.contains(self.kind(plan,node.msg),owner):
                    raise Unproved('assertion message exposes an instance representation')
                if isinstance(node,ast.FormattedValue)and self.contains(self.kind(plan,node.value),owner):
                    raise Unproved('formatting exposes an instance representation')
                if isinstance(node,ast.BinOp)and isinstance(node.op,ast.Mod)and self.kind(plan,node.left)in {'str','bytes'}and self.contains(self.kind(plan,node.right),owner):
                    raise Unproved('text formatting exposes an instance representation')
                if isinstance(node,ast.NamedExpr)and(self.contains(kind,owner)or self.contains(self.kind(plan,node.value),owner)):
                    raise Unproved('named expression rebinds an instance during evaluation')
                if isinstance(node,ast.Compare):
                    operands=[node.left,*node.comparators]
                    for left,operator,right in zip(operands,node.ops,operands[1:]):
                        if 'none'in(self.kind(plan,left),self.kind(plan,right)):continue
                        if self.contains(self.kind(plan,left),owner)or self.contains(self.kind(plan,right),owner):
                            raise Unproved('explicit or implicit instance identity comparison')
                if isinstance(node,ast.Attribute):
                    receiver=self.kind(plan,node.value)
                    if self.direct(plan,node.value,owner)and node.attr.startswith('__')and node.attr.endswith('__'):
                        raise Unproved('special instance protocol or namespace is explicitly exposed')
                    if isinstance(receiver,ClassReferenceType)and receiver.definition==owner.index and isinstance(node.ctx,(ast.Store,ast.Del)):
                        raise Unproved('class namespace is changed after definition')
                    if isinstance(receiver,ClassReferenceType)and receiver.definition==owner.index and node.attr in {'__dict__','__init__','__new__'}:
                        raise Unproved('constructor protocol or mutable class namespace is exposed as a value')
                    if self.direct(plan,node.value,owner)and self.model.resolved_name(plan,node)in owner.methods:
                        parent=self.parents.get(id(node))
                        if not isinstance(parent,ast.Call)or parent.func is not node:
                            raise Unproved('instance bound method escapes immediate invocation')
                if isinstance(node,ast.Name)and self.contains(kind,owner)and self.model.unit is not None:
                    binding=self.bindings.get(self.model.unit.ordinal(node))
                    if binding is not None and binding.role=='load'and binding.scope!=binding.owner:
                        raise Unproved('instance or instance container is captured by a different lexical scope')
            if getattr(plan,'_native_retained_expression',False):
                raise Unproved('suspended generator-expression frame has no fresh-instance transfer certificate')
            flow=Flow(self,owner,plan,refs,initializer,self_name)
            if isinstance(plan.node.body,list):flow.block(plan.node.body,{})
            else:flow.expression(plan.node.body,{})


class Flow:
    def __init__(self,registry,owner,plan,refs,initializer,self_name):
        self.registry,self.owner,self.plan,self.refs=registry,owner,plan,refs
        self.initializer,self.self_name=initializer,self_name

    def name(self,node):return self.registry.model.resolved_name(self.plan,node)

    def expression(self,node,state):
        if node is None:return
        if isinstance(node,ast.Name):
            if isinstance(node.ctx,ast.Load)and self.registry.contains(self.registry.kind(self.plan,node),self.owner):state.pop(self.name(node),None)
            return
        if isinstance(node,ast.Attribute):
            # A plain scalar-field read does not publish its receiver.
            if self.registry.direct(self.plan,node.value,self.owner)and self.name(node)in self.owner.fields:
                if not isinstance(node.value,ast.Name):self.expression(node.value,state)
                return
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            for value in getattr(node,'decorator_list',()):self.expression(value,state)
            for value in getattr(getattr(node,'args',None),'defaults',()):self.expression(value,state)
            for value in getattr(getattr(node,'args',None),'kw_defaults',()):self.expression(value,state)
            for value in getattr(node,'bases',()):self.expression(value,state)
            for keyword in getattr(node,'keywords',()):self.expression(keyword.value,state)
            return
        if isinstance(node,ast.Lambda):
            # Capture detection above prevents a fresh mutable receiver from
            # reaching a nested body without marking it published.
            for value in node.args.defaults:self.expression(value,state)
            for value in node.args.kw_defaults:self.expression(value,state)
            return
        for child in ast.iter_child_nodes(node):self.expression(child,state)

    def field(self,target,state):
        if not isinstance(target,ast.Attribute)or not self.registry.contains(self.registry.kind(self.plan,target.value),self.owner):
            self.expression(target,state);return
        receiver=target.value
        if not self.registry.direct(self.plan,receiver,self.owner)or not isinstance(receiver,ast.Name):
            raise Unproved('field write does not name one fresh concrete local instance')
        name=self.name(receiver)
        init=(self.plan is self.initializer and name==self.self_name)
        if not init and not(state.get(name,False)and self.registry.local(self.plan,receiver,self.owner)):
            raise Unproved('field write can reach a published, aliased or captured instance')
        self.refs[self.plan.index,id(target)]=(self.owner.index,name)

    def assign(self,target,value,state):
        if isinstance(target,ast.Name):
            name=self.name(target)
            if self.registry.constructor(self.plan,value,self.owner)and self.registry.local(self.plan,target,self.owner):state[name]=True
            else:state.pop(name,None)
        elif isinstance(target,(ast.Tuple,ast.List)):
            for child in target.elts:self.assign(child,None,state)
        else:self.field(target,state)

    def block(self,body,entry):
        state=dict(entry);breaks=[];continues=[]
        for node in body:
            if state is None:break
            reached=getattr(self.registry.model,'reached_statements',None)
            if reached is not None and(self.plan.index,id(node))not in reached:continue
            if isinstance(node,ast.Assign):
                self.expression(node.value,state)
                shared=(len(node.targets)>1 and self.registry.contains(self.registry.kind(self.plan,node.value),self.owner))
                for target in node.targets:self.assign(target,None if shared else node.value,state)
            elif isinstance(node,ast.AnnAssign):
                if node.value is not None:self.expression(node.value,state);self.assign(node.target,node.value,state)
            elif isinstance(node,ast.AugAssign):
                self.field(node.target,state)
                self.expression(node.value,state)
                self.field(node.target,state)
                if isinstance(node.target,ast.Name):state.pop(self.name(node.target),None)
            elif isinstance(node,ast.Delete):
                for target in node.targets:
                    if isinstance(target,ast.Name):state.pop(self.name(target),None)
                    else:self.field(target,state)
            elif isinstance(node,ast.If):
                self.expression(node.test,state)
                yes=self.block(node.body,state);no=self.block(node.orelse,state)
                state=join([yes.normal,no.normal]);breaks.extend(yes.breaks+no.breaks);continues.extend(yes.continues+no.continues)
            elif isinstance(node,(ast.For,ast.While)):
                if isinstance(node,ast.For):self.expression(node.iter,state)
                header=dict(state)
                while True:
                    start=dict(header)
                    if isinstance(node,ast.For):self.assign(node.target,None,start)
                    else:self.expression(node.test,start)
                    inside=self.block(node.body,start)
                    next_header=join([state,inside.normal,*inside.continues])
                    if next_header==header:break
                    header=next_header
                otherwise=self.block(node.orelse,header)
                state=join([otherwise.normal,*inside.breaks]);breaks.extend(otherwise.breaks);continues.extend(otherwise.continues)
            elif isinstance(node,ast.Break):breaks.append(dict(state));state=None
            elif isinstance(node,ast.Continue):continues.append(dict(state));state=None
            elif isinstance(node,(ast.Return,ast.Raise)):
                self.expression(getattr(node,'value',None)or getattr(node,'exc',None),state);state=None
            elif isinstance(node,(ast.With,ast.Try,ast.TryStar,ast.Match)):
                # Structured cleanup may re-enter source code. All local fresh
                # bindings become published before crossing that boundary.
                state={}
                for child in ast.walk(node):
                    if isinstance(child,ast.Attribute)and isinstance(child.ctx,(ast.Store,ast.Del)):
                        self.field(child,state)
                self.expression(node,state)
            else:self.expression(node,state)
        return Edges(state,breaks,continues)


def prepare(model):
    model.value_classes=Registry(model)


def selected(model,owner):
    return owner.index in getattr(getattr(model,'value_classes',None),'selected',())


def borrowed_self(model,plan,name,kind):
    registry=getattr(model,'value_classes',None)
    owner=None if registry is None else registry.initializers.get(plan.index)
    return owner is not None and name==plan.runtime_parameters[0]


def reference(emitter,target):
    from .native_classes import Expression,shape
    from .native import _string
    registry=getattr(emitter.model,'value_classes',None)
    record=None if registry is None else registry.references.get((emitter.plan.index,id(target)))
    if record is None:return None
    owner_index,name=record
    owner=next(owner for owner in emitter.model.classes.values()if owner.index==owner_index)
    if not selected(emitter.model,owner):return None
    kind=emitter.kind(target.value)
    stored=emitter.model.namespace.local_kind(emitter.plan,name)or kind
    slot=emitter.slot(name,stored)
    message=_string("UnboundLocalError: cannot access local variable '"+emitter.model.display_name(name)+"' where it is not associated with a value")
    receiver=emitter.fresh()
    loaded=emitter.at(f'{slot}.as_ref().ok_or_else(||{message}.to_owned())',target.value)
    field_name=emitter.model.resolved_name(emitter.plan,target)
    index=list(owner.fields).index(field_name)
    return f'let {receiver}={loaded};',('field',Expression(receiver,kind),owner,index,shape(owner.fields[field_name].cell))


def identity_equal(model,kind,left,right):
    from .native_classes import InstanceType
    if isinstance(kind,InstanceType)and selected(model,model.classes[kind.name]):
        return f'({left}).class_value_identity==({right}).class_value_identity'
    return f'Rc::ptr_eq(&({left}),&({right}))'


def identity(model,kind,value):
    from .native_classes import InstanceType
    if isinstance(kind,InstanceType)and selected(model,model.classes[kind.name]):
        return f'({value}).class_value_identity'
    return f'Rc::as_ptr(&({value})) as usize'


RUNTIME=r'''
thread_local! {
 static CLASS_VALUE_NEXT_ID:std::cell::Cell<usize>=std::cell::Cell::new(1);
}
#[inline(always)]
fn class_value_next_id()->Result<usize,String> {
 CLASS_VALUE_NEXT_ID.with(|next|{
  let id=next.get();
  let following=id.checked_add(2).ok_or_else(||"MemoryError: object identity space exhausted".to_owned())?;
  next.set(following);Ok(id)
 })
}
'''
