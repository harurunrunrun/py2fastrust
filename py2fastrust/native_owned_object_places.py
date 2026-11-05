"""Private source objects use owned data and deferred receiver places.

The Python instance type remains unchanged. The certificate proves that every
runtime instance has one local owner and that every transient receiver loan
ends before another source operation can borrow it.
"""
import ast
from dataclasses import dataclass


class Unproved(Exception):
    pass


class Registry:
    def __init__(self,model):
        self.model=model;self.selected=set();self.reasons={};self.locals={};self.receivers={}
        self.values=model.value_classes
        self.parents=self.values.parents
        if model.unit is None:
            self.reasons.update((owner.index,'no official source/binding graph')for owner in model.classes.values())
            return
        self.binding_rows=tuple(model.iter_bindings())
        self.bindings={binding.node:binding for binding in self.binding_rows}
        self.nodes={model.unit.node_ordinals[id(node)]:node for node in model.iter_nodes()if id(node)in model.unit.node_ordinals}
        self.plans={plan.index:plan for plan in model.plans if plan.reachable}
        try:
            from .native_finite_depth_calls import _model_proof,Unproved as GraphUnproved
            _model_proof(model)
        except GraphUnproved as error:
            self.reasons.update((owner.index,str(error))for owner in model.classes.values())
            return
        for owner in model.classes.values():
            if not owner.used:continue
            from .native_copy_scalar_fields import selected
            if selected(model,owner):continue
            try:local,receivers=self.prove(owner)
            except Unproved as error:self.reasons[owner.index]=str(error)
            else:
                self.selected.add(owner.index);self.locals.update(local);self.receivers.update(receivers)

    def source(self,plan):return getattr(plan,'specialization_source',plan)

    def kind(self,plan,node):return self.values.kind(plan,node)

    def contains(self,kind,owner):return self.values.contains(kind,owner)

    def canonical_method(self,plan,node,owner):
        from .native_classes import InstanceType
        if not isinstance(node,ast.Call)or not isinstance(node.func,ast.Attribute):return False
        kind=self.kind(plan,node.func.value)
        if not isinstance(kind,InstanceType)or kind.name!=self.model.class_key(owner):return False
        if (plan.index,id(node))in self.model.callable_cells.sites:return False
        method=owner.methods.get(self.model.resolved_name(plan,node.func))
        targets=self.model.call_edges_by_site.get((plan.index,id(node)),())
        return method is not None and bool(targets)and all(
            index in self.plans and self.source(self.plans[index])is self.source(method)for index in targets)

    def prove(self,owner):
        from .native_classes import InstanceType,shape
        from .native_module_linking import ClassReferenceType
        from .native_class_calls import synchronous
        model=self.model;kind=InstanceType(model.class_key(owner))
        if owner.node.bases or owner.node.keywords or owner.node.decorator_list or owner.node.type_params:
            raise Unproved('class construction/lookup is not plain')
        if any(name in owner.methods for name in ('__new__','__del__','__getattribute__','__getattr__','__setattr__','__delattr__')):
            raise Unproved('custom allocation, attribute or lifetime protocol')
        if not owner.fields:raise Unproved('no non-Copy instance data needs ownership')
        if any(shape(field.cell)is None for field in owner.fields.values()):raise Unproved('unresolved field layout')
        namespace=getattr(model,'class_namespaces',None)
        for name,method in owner.methods.items():
            if method.node not in owner.node.body or method.node.decorator_list or method.node.type_params:
                raise Unproved('method publication is not a canonical direct function')
            if method.signature.variadic_positional or method.signature.variadic_keyword:
                raise Unproved('variadic method binding retains its existing physical receiver')
            writes=[binding for binding in self.binding_rows if binding.owner==model.unit.scope_for(owner.node).ordinal
                    and binding.name==name and binding.role!='load']
            if len(writes)!=1:raise Unproved('class method has another binding producer')
        for field in owner.fields:
            if field in owner.methods or namespace is not None and(owner.index,field)in namespace.members:
                raise Unproved('instance field overlaps a class descriptor/member')
        from .native_class_record_fields import selected as record_selected
        for (number,_),info in getattr(model.owned_class_lists,'fields',{}).items():
            if number==owner.index and record_selected(model,info)is not None:
                raise Unproved('record-field mutable receiver projection is not selected yet')
        local={};receivers={};constructors=0
        for plan in self.plans.values():
            if self.contains(shape(plan.result),owner):raise Unproved('an object escapes through a source return')
            for name,cell in plan.arguments.items():
                if not self.contains(shape(cell),owner):continue
                if(plan.owner is not owner or not plan.runtime_parameters or name!=plan.runtime_parameters[0]
                        or shape(cell)!=kind or not synchronous(model,plan)):
                    raise Unproved('an object crosses a non-receiver parameter')
                receivers[plan.index,name]=owner.index
            for node in self.values.own_nodes(plan):
                if isinstance(node,ast.Attribute):
                    receiver=self.kind(plan,node.value)
                    if isinstance(receiver,ClassReferenceType)and receiver.definition==owner.index and isinstance(node.ctx,(ast.Store,ast.Del)):
                        raise Unproved('source class metadata changes after publication')
                if isinstance(node,ast.Call)and self.values.constructor(plan,node,owner):
                    parent=self.parents.get(id(node))
                    if not(isinstance(parent,ast.Assign)and parent.value is node and len(parent.targets)==1
                           and isinstance(parent.targets[0],ast.Name)and not model.is_module_plan(plan)):
                        raise Unproved('construction does not bind one fresh function-local owner')
                    target=parent.targets[0];binding=self.bindings.get(model.unit.ordinal(target));scope=model.lexical.scope(plan)
                    if(binding is None or binding.owner!=scope or binding.scope!=scope
                            or model.unit.scopes[scope].kind!='function'
                            or model.namespace.owns(plan,target)or model.lexical.field_for(target)is not None):
                        raise Unproved('constructor binding is shared/captured')
                    local[plan.index,model.resolved_name(plan,target)]=owner.index;constructors+=1
                if not isinstance(node,ast.Name)or not self.contains(self.kind(plan,node),owner):continue
                if self.kind(plan,node)!=kind:raise Unproved('an instance has a mixed physical value family')
                name=model.resolved_name(plan,node);scope=model.lexical.scope(plan)
                binding=self.bindings.get(model.unit.ordinal(node))
                if(binding is None or binding.scope!=binding.owner or binding.owner!=scope
                        or model.namespace.owns(plan,node)or model.lexical.field_for(node)is not None):
                    raise Unproved('a source reference escapes its local owner scope')
                if not isinstance(node.ctx,ast.Load):continue
                parent=self.parents.get(id(node))
                if not isinstance(parent,ast.Attribute)or parent.value is not node:
                    raise Unproved('whole-object alias, identity or escaping value use')
                attribute=model.resolved_name(plan,parent)
                if attribute in owner.methods:
                    call=self.parents.get(id(parent))
                    if not isinstance(call,ast.Call)or call.func is not parent or not self.canonical_method(plan,call,owner):
                        raise Unproved('a method reference escapes or needs dynamic binding')
                    if attribute=='__init__':raise Unproved('explicit initializer reentry')
                elif attribute in owner.fields:
                    if isinstance(parent.ctx,ast.Load)and self.kind(plan,parent)!=shape(owner.fields[attribute].cell):
                        raise Unproved('point field type requires another physical projection')
                else:raise Unproved('an instance protocol/unknown attribute is observed')
        if not constructors:raise Unproved('no fresh local construction')
        # Audit every producer of a selected binding, including walrus/import/
        # comprehension/with targets whose point type may differ from the owner.
        for plan in self.plans.values():
            scope=model.lexical.scope(plan)
            for node in self.values.own_nodes(plan):
                if isinstance(node,ast.Name)and isinstance(node.ctx,ast.Load)and self.contains(self.kind(plan,node),owner):
                    key=plan.index,model.resolved_name(plan,node)
                    if key not in local and key not in receivers:
                        raise Unproved('an instance value lacks a certified owning place')
                if isinstance(node,ast.Attribute)and isinstance(node.ctx,ast.Del)and self.kind(plan,node.value)==kind:
                    raise Unproved('attribute deletion needs an owned cleanup place')
            for binding in self.binding_rows:
                name=binding.name
                if binding.owner!=scope or binding.role=='load':continue
                if(plan.index,name)in receivers:
                    if binding.role!='parameter':raise Unproved('receiver binding is rebound/deleted')
                    continue
                if(plan.index,name)not in local:continue
                node=self.nodes.get(binding.node)
                if isinstance(node,ast.Name)and isinstance(node.ctx,ast.Del):continue
                parent=self.parents.get(id(node))
                if not(isinstance(node,ast.Name)and isinstance(parent,ast.Assign)
                       and len(parent.targets)==1 and parent.targets[0]is node
                       and self.values.constructor(plan,parent.value,owner)):
                    raise Unproved('an owner binding has a non-constructor producer')
        return local,receivers


def prepare(model):model.owned_object_places=Registry(model)


def selected(model,owner):return owner.index in getattr(getattr(model,'owned_object_places',None),'selected',())


def receiver(model,plan,name):return(plan.index,name)in getattr(getattr(model,'owned_object_places',None),'receivers',{})


@dataclass(frozen=True)
class Place:
    emitter:object
    node:object
    owner:object
    name:object
    parameter:bool

    def slot(self):
        from .native_classes import InstanceType
        return self.emitter.slot(self.name,InstanceType(self.emitter.model.class_key(self.owner)))

    def argument(self):return 'class_argument_'+str(self.emitter.plan.runtime_parameters.index(self.name))

    def check(self):
        if self.parameter:return ''
        from .native import _string
        message="UnboundLocalError: cannot access local variable '"+self.emitter.model.display_name(self.name)+"' where it is not associated with a value"
        return self.emitter.at(self.slot()+'.as_ref().ok_or_else(||'+_string(message)+'.to_owned())',self.node)+';'

    def shared(self):return '(&*'+self.argument()+')'if self.parameter else self.slot()+'.as_ref().expect("checked stable object owner")'

    def mutable(self):return '(&mut *'+self.argument()+')'if self.parameter else self.slot()+'.as_mut().expect("checked stable object owner")'


def place(emitter,node):
    if not isinstance(node,ast.Name):return None
    registry=getattr(emitter.model,'owned_object_places',None)
    if registry is None:return None
    name=emitter.model.resolved_name(emitter.plan,node);key=emitter.plan.index,name
    number=registry.receivers.get(key,registry.locals.get(key))
    if number is None:return None
    owner=next(owner for owner in emitter.model.classes.values()if owner.index==number)
    return Place(emitter,node,owner,name,key in registry.receivers)


def expression(emitter,node):
    from .native_classes import Expression
    root=place(emitter,node)
    if root is not None:return Expression('{'+root.check()+root.shared()+'}',emitter.kind(node))
    if isinstance(node,ast.Attribute)and isinstance(node.ctx,ast.Load):
        root=place(emitter,node.value)
        if root is not None:
            name=emitter.model.resolved_name(emitter.plan,node)
            if name not in root.owner.fields:return None
            index=list(root.owner.fields).index(name)
            from .native_owned_class_lists import selected as owned_field
            if owned_field(emitter.model,root.owner,index):return None
            loaded=emitter.at(f'class_get_{root.owner.index}_{index}('+root.shared()+')',node)
            from .native_class_loop_fields import read
            return Expression('{'+root.check()+read(emitter,node,loaded,emitter.kind(node))+'}',emitter.kind(node))
    if isinstance(node,ast.Subscript):
        result=reference(emitter,node)
        if result is not None:
            setup,ref=result;value=load(emitter,ref,node)
            return Expression('{'+setup+value.code+'}',value.kind)
    return None


def reference(emitter,node):
    from .native_classes import shape
    if isinstance(node,ast.Attribute):
        root=place(emitter,node.value)
        if root is None:return None
        name=emitter.model.resolved_name(emitter.plan,node)
        if name not in root.owner.fields:return None
        index=list(root.owner.fields).index(name)
        return root.check(),('owned_object_field',root,index,shape(root.owner.fields[name].cell))
    if not isinstance(node,ast.Subscript)or not isinstance(node.value,ast.Attribute):return None
    root=place(emitter,node.value.value)
    if root is None:return None
    from .native_owned_class_lists import site,prefix
    info=site(emitter,node.value)
    if info is None:return None
    from .native_initialized_owned_fields import selected as initialized
    setup=root.check()
    if not initialized(emitter.model,info.owner,info.index):
        setup+=emitter.at(prefix(info)+'_ensure('+root.shared()+')',node.value)+';'
    more,index=emitter.capture(emitter.expression(node.slice))
    return setup+more,('owned_object_index',root,info,index)


def load(emitter,ref,node,kind=None):
    from .native_classes import Expression
    if ref[0]=='owned_object_field':
        _,root,index,stored=ref
        return Expression(emitter.at(f'class_get_{root.owner.index}_{index}('+root.shared()+')',node),stored)
    _,root,info,index=ref
    from .native_owned_class_lists import prefix
    raw=emitter.at(prefix(info)+'_get('+root.shared()+',&('+emitter.number(index)+'))',node)
    from .native_list_positions import project_element
    return project_element(emitter,raw,info.kind.element,emitter.kind(node)if kind is None else kind,node)


def store(emitter,ref,value,node):
    if ref[0]=='owned_object_field':
        _,root,index,kind=ref
        previous=emitter.fresh()
        from .native_initialized_owned_fields import wrap
        stored=wrap(emitter.model,root.owner,index,emitter.coerce(value,kind,node))
        return '{let '+previous+'={let owner='+root.mutable()+';std::mem::replace(&mut owner.field_'+str(index)+','+stored+')};drop('+previous+');}'
    _,root,info,index=ref
    from .native_owned_class_lists import prefix
    return emitter.at(prefix(info)+'_set('+root.mutable()+',&('+emitter.number(index)+'),'+emitter.coerce(value,info.kind.element,node)+')',node)+';'


def initialize(emitter,node):
    if isinstance(node,ast.Assign)and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
        root=place(emitter,node.targets[0])
        if root is not None and not root.parameter:
            before,value=emitter.capture(emitter.expression(node.value))
            return before+emitter.assign_name(node.targets[0],value)
    registry=getattr(emitter.model,'owned_class_lists',None)
    info=None if registry is None else registry.initializers.get(node)
    if info is None:return None
    root=place(emitter,info.target.value)
    if root is None:return None
    from .native_owned_local_lists import allocation
    value=allocation(emitter,node.value,info.kind)
    captured=emitter.fresh()
    from .native_initialized_owned_fields import wrap
    return '{let '+captured+'='+value.code+';'+root.check()+root.mutable()+'.field_'+str(info.index)+'='+wrap(emitter.model,info.owner,info.index,captured)+';}'


def call_receiver(emitter,node,callee):
    if not isinstance(node.func,ast.Attribute):return None
    root=place(emitter,node.func.value)
    if root is None:return None
    registry=emitter.model.owned_object_places
    if not registry.canonical_method(emitter.plan,node,root.owner):return None
    from .native_classes import Expression,InstanceType
    setup=root.check();module=None
    if getattr(emitter.model,'module_linker',None)is not None:
        module=emitter.fresh()
        setup+='let '+module+'={'+root.shared()+'.borrow().class_definition.module.clone()};'
    return setup,Expression(root.mutable(),InstanceType(emitter.model.class_key(root.owner))),module
