"""Embed nonescaping builtin list fields in their identity-preserving owner.

Source ListType remains the element ABI. A separate original-AST capability
selects only fresh constructor fields whose entire reached use is an indexed
place or builtin len. Parent borrows never survive index/RHS source callbacks.
"""
import ast
from dataclasses import dataclass

from .native_types import ListType
from .references import BuiltinIdentity


class Unproved(Exception):pass


@dataclass
class Field:
    owner:object
    index:int
    name:object
    kind:object
    statement:object=None
    target:object=None
    reads:bool=False


class Registry:
    def __init__(self,model):
        from .native_classes import shape
        self.model=model;self.base=model.value_classes
        self.fields={};self.sites={};self.initializers={};self.reasons={}
        for owner in model.classes.values():
            if not owner.used:continue
            for index,(name,field)in enumerate(owner.fields.items()):
                kind=shape(field.cell)
                if not isinstance(kind,ListType):continue
                info=Field(owner,index,name,kind)
                try:sites=self.prove(info)
                except Unproved as error:self.reasons[owner.index,index]=str(error)
                else:
                    self.fields[owner.index,index]=info
                    self.sites.update({site:info for site in sites})
                    self.initializers[info.statement]=info

    def kind(self,plan,node):return self.base.kind(plan,node)

    def fresh(self,plan,node):
        if isinstance(node,(ast.List,ast.ListComp)):return True
        if isinstance(node,ast.BinOp)and isinstance(node.op,ast.Mult):
            scalars={'int','bool','int_bool'}
            return (self.fresh(plan,node.left)and self.kind(plan,node.right)in scalars
                    or self.fresh(plan,node.right)and self.kind(plan,node.left)in scalars)
        return False

    def builtin_len(self,plan,node):
        if not isinstance(node,ast.Call)or not isinstance(node.func,ast.Name)or len(node.args)!=1 or node.keywords:return False
        identity=self.model.builtin_identity(plan,node.func,{})
        if not isinstance(identity,BuiltinIdentity)or identity.name!='len':return False
        kind=self.kind(plan,node.func)
        targets=getattr(kind,'targets',())
        return not targets or all(isinstance(target,BuiltinIdentity)and target.name=='len'for target in targets)

    def prove(self,info):
        from .native_classes import InstanceType,shape
        from .native_class_calls import synchronous
        from .native_module_linking import ClassReferenceType
        model=self.model;owner=info.owner;base=self.base
        if model.unit is None:raise Unproved('official original-source bindings are unavailable')
        if getattr(model,'gc_classes',())or any('__del__'in item.methods for item in model.classes.values()if item.used):
            raise Unproved('source collection/finalizer lifetime observations are retained')
        if owner.node.bases or owner.node.keywords or owner.node.decorator_list or owner.node.type_params:
            raise Unproved('inheritance, metaclasses or class replacement are retained')
        if any(name in owner.methods for name in ('__new__','__del__','__getattribute__','__getattr__','__setattr__','__delattr__')):
            raise Unproved('custom allocation, attributes or destruction are retained')
        namespace=getattr(model,'class_namespaces',None)
        if namespace is not None and (owner.index,info.name)in namespace.members:
            raise Unproved('the field participates in class namespace or descriptor lookup')
        init=owner.methods.get('__init__')
        if init is None or not synchronous(model,init)or init.node.decorator_list:
            raise Unproved('a canonical synchronous initializer is unavailable')
        self_name=init.runtime_parameters[0]
        if shape(init.arguments[self_name])!=InstanceType(model.class_key(owner)):
            raise Unproved('initializer self has no exact owner type')
        scope=model.lexical.scope(init)
        parameters=[binding for binding in model.iter_bindings()if binding.owner==scope and binding.scope==scope
                    and binding.name==self_name and binding.role=='parameter']
        if len(parameters)!=1:raise Unproved('initializer self has no unique official parameter binding')
        if any(binding.owner==scope and binding.name==self_name and binding.role not in {'load','parameter'}
               for binding in model.iter_bindings()):
            raise Unproved('initializer self is rebound or deleted')
        for (caller,node_id),targets in model.call_edges_by_site.items():
            if init.index not in targets:continue
            plan=base.plans.get(caller);node=base.nodes.get(node_id)
            if plan is None or node is None or not base.constructor(plan,node,owner):
                raise Unproved('initializer is entered outside a fresh canonical constructor')
        sites=[];stores=[]
        reflective={'vars','globals','locals','getattr','setattr','delattr','dir','eval','exec','compile'}
        dunders={'__dict__','__weakref__','__getattribute__','__setattr__','__delattr__','__reduce__','__reduce_ex__','__getstate__','__setstate__'}
        # A place retains the parent, whereas an ordinary field load could
        # retain only the list. Do not expose changed lifetime/address reuse.
        safe={'type','isinstance','bool','len'}
        for plan in base.plans.values():
            for node in base.own_nodes(plan):
                if isinstance(node,ast.FormattedValue)and base.contains(self.kind(plan,node.value),owner):
                    raise Unproved('owner formatting can observe its retained lifetime/address')
                if isinstance(node,ast.Assert)and node.msg is not None and base.contains(self.kind(plan,node.msg),owner):
                    raise Unproved('assertion rendering can expose the retained owner')
                if (isinstance(node,ast.BinOp)and isinstance(node.op,ast.Mod)
                        and self.kind(plan,node.left)in {'str','bytes'} and base.contains(self.kind(plan,node.right),owner)):
                    raise Unproved('text formatting can expose the retained owner')
                if isinstance(node,ast.Call):
                    names=base.builtin(plan,node)
                    if names & reflective:raise Unproved('a reflective namespace/attribute operation is retained')
                    values=[*node.args,*(part.value for part in node.keywords)]
                    kinds=[base.argument_kind(plan,value)for value in values]
                    if isinstance(node.func,ast.Attribute):kinds.append(self.kind(plan,node.func.value))
                    observed=any(base.contains(kind,owner)for kind in kinds)
                    if observed:
                        callee=self.kind(plan,node.func)
                        if getattr(callee,'members',()):raise Unproved('the owner reaches an opaque module protocol')
                        if any(value.name not in safe for value in getattr(callee,'builtins',())):
                            raise Unproved('the owner reaches an unproved builtin protocol')
                        if not names<=safe or not names and not model.call_edges_by_site.get((plan.index,id(node))):
                            raise Unproved('the owner reaches a call without closed source effects')
                if not isinstance(node,ast.Attribute):continue
                receiver=self.kind(plan,node.value)
                if node.attr in dunders:raise Unproved('an implicit object dictionary/copy/attribute protocol is exposed')
                if isinstance(receiver,ClassReferenceType)and receiver.definition==owner.index:
                    if isinstance(node.ctx,(ast.Store,ast.Del))or node.attr in {'__init__','__new__'}:
                        raise Unproved('class namespace or initializer protocol can be changed/exposed')
                if base.direct(plan,node.value,owner)and node.attr in {'__class__','__init__','__new__'}:
                    raise Unproved('instance class/initializer protocol is exposed')
                if model.resolved_name(plan,node)!=info.name:continue
                if not base.direct(plan,node.value,owner):
                    if receiver is None or base.contains(receiver,owner):
                        raise Unproved('a field receiver has unknown or multiple owner layouts')
                    continue
                parent=base.parents.get(id(node))
                if isinstance(node.ctx,ast.Store):
                    statement=parent
                    value=(statement.value if isinstance(statement,ast.AnnAssign)else
                           statement.value if isinstance(statement,ast.Assign)and len(statement.targets)==1 else None)
                    if (plan is not init or value is None or not isinstance(node.value,ast.Name)
                            or model.resolved_name(init,node.value)!=self_name or not self.fresh(init,value)):
                        raise Unproved('the field is assigned outside one fresh self initializer')
                    binding=base.bindings.get(model.unit.ordinal(node.value))
                    if binding is None or binding.owner!=scope or binding.scope!=scope:
                        raise Unproved('initializer store does not target the original self binding')
                    ancestor=statement
                    while ancestor is not init.node:
                        ancestor=base.parents.get(id(ancestor))
                        if ancestor is None or isinstance(ancestor,(ast.For,ast.While,ast.AsyncFor,ast.comprehension)):
                            raise Unproved('initializer field store may execute repeatedly')
                    stores.append((statement,node));sites.append((plan.index,id(node)));continue
                if isinstance(node.ctx,ast.Del):raise Unproved('the field is deleted')
                if isinstance(parent,ast.Subscript)and parent.value is node and not isinstance(parent.slice,ast.Slice):
                    if isinstance(parent.ctx,ast.Del):raise Unproved('field length can change through deletion')
                    if self.kind(plan,parent.slice)not in {'int','bool','int_bool'}:
                        raise Unproved('index conversion has no closed native integer protocol')
                    if isinstance(parent.ctx,ast.Load)or isinstance(base.parents.get(id(parent)),ast.AugAssign):info.reads=True
                    sites.append((plan.index,id(node)));continue
                if isinstance(parent,ast.Call)and parent.args==[node]and self.builtin_len(plan,parent):
                    sites.append((plan.index,id(node)));continue
                raise Unproved('the whole field list escapes, aliases, iterates or invokes a list protocol')
        if len(stores)!=1:raise Unproved('the field has no unique at-most-once fresh initializer store')
        info.statement,info.target=stores[0]
        return sites


def prepare(model):model.owned_class_lists=Registry(model)


def selected(model,owner,index):
    registry=getattr(model,'owned_class_lists',None)
    return None if registry is None else registry.fields.get((owner.index,index))


def site(emitter,node):
    registry=getattr(emitter.model,'owned_class_lists',None)
    return None if registry is None else registry.sites.get((emitter.plan.index,id(node)))


def prefix(info):return f'class_owned_field_{info.owner.index}_{info.index}'


def reference(emitter,node):
    if not isinstance(node,ast.Subscript):return None
    info=site(emitter,node.value)
    if info is None:return None
    setup,owner=emitter.capture(emitter.expression(node.value.value))
    setup+=emitter.at(prefix(info)+'_ensure(&'+owner.code+')',node.value)+';'
    more,index=emitter.capture(emitter.expression(node.slice))
    return setup+more,('owned_class_index',info,owner,index)


def expression(emitter,node):
    from .native_classes import Expression
    result=reference(emitter,node)
    if result is None:return None
    setup,place=result
    value=load(emitter,place,node)
    return Expression('{'+setup+value.code+'}',value.kind)


def load(emitter,place,node,kind=None):
    _,info,owner,index=place
    code=emitter.at(prefix(info)+'_get(&'+owner.code+',&('+emitter.number(index)+'))',node)
    from .native_list_positions import project_element
    return project_element(emitter,code,info.kind.element,emitter.kind(node)if kind is None else kind,node)


def store(emitter,place,value,node):
    _,info,owner,index=place
    code=prefix(info)+'_set(&'+owner.code+',&('+emitter.number(index)+'),'+emitter.coerce(value,info.kind.element,node)+')'
    return emitter.at(code,node)+';'


def length(emitter,node):
    from .native_classes import Expression
    registry=getattr(emitter.model,'owned_class_lists',None)
    if registry is None or not registry.builtin_len(emitter.plan,node):return None
    info=site(emitter,node.args[0])
    if info is None:return None
    before,owner=emitter.capture(emitter.expression(node.args[0].value))
    code=emitter.at(prefix(info)+'_len(&'+owner.code+')',node.args[0])
    return Expression('{'+before+'class_from_usize('+code+')}',emitter.kind(node))


def initialize(emitter,node):
    registry=getattr(emitter.model,'owned_class_lists',None)
    if registry is None:return None
    info=registry.initializers.get(node)
    if info is None:return None
    # Intercept the original AST before generic Assign captures/clones its RHS.
    value=emitter.coerce(emitter.expression(node.value),info.kind,node.value)
    vector=emitter.fresh()
    code=f'let {vector}=match Rc::try_unwrap({value}){{Ok(value)=>value.into_inner(),Err(_)=>unreachable!("fresh builtin field list escaped")}};'
    more,owner=emitter.capture(emitter.expression(info.target.value))
    return '{'+code+more+f'{owner.code}.borrow_mut().field_{info.index}=Some({vector});'+'}'


def runtime(model,owner,emitter):
    from .native import _string
    registry=getattr(model,'owned_class_lists',None)
    if registry is None:return ''
    result=[]
    for (number,index),info in registry.fields.items():
        if number!=owner.index:continue
        name=prefix(info);handle=f'&ClassHandle_{number}';element=emitter.rust_type(info.kind.element)
        error=_string(f"AttributeError: '{owner.node.name}' object has no attribute '{owner.fields[info.name].name}'")
        field=f'field_{index}'
        result.append(f'fn {name}_ensure(owner:{handle})->Result<(),String>{{if owner.borrow().{field}.is_some(){{Ok(())}}else{{Err({error}.to_owned())}}}}')
        result.append(f'fn {name}_len(owner:{handle})->Result<usize,String>{{let owner=owner.borrow();let values=owner.{field}.as_ref().ok_or_else(||{error}.to_owned())?;Ok(values.len())}}')
        if info.reads:
            result.append(f'fn {name}_get(owner:{handle},index:&NativeInt)->Result<{element},String>{{let result={{let owner=owner.borrow();let values=owner.{field}.as_ref().expect("checked stable field");let offset=class_index(index,values.len())?;values[offset].clone()}};Ok(result)}}')
        result.append(f'fn {name}_set(owner:{handle},index:&NativeInt,value:{element})->Result<(),String>{{let previous={{let mut owner=owner.borrow_mut();let values=owner.{field}.as_mut().expect("checked stable field");let offset=class_index(index,values.len()).map_err(|_|"IndexError: list assignment index out of range".to_owned())?;std::mem::replace(&mut values[offset],value)}};drop(previous);Ok(())}}')
    return '\n'.join(result)
