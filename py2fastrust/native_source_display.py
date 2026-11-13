"""Typed display calls and canonical plain source special-method aliases."""
from dataclasses import dataclass

from .call_semantics import Argument,CallArguments


SLOTS=frozenset({'__str__','__repr__'})
ALIAS_SLOTS=SLOTS|{'__getitem__','__setitem__','__len__','__reversed__','__contains__'}


def alias_slot(name):
    from .native_class_operators import SUPPORTED_SLOTS
    return name in ALIAS_SLOTS and name in SUPPORTED_SLOTS


def guard_direct_method(model,owner,name,node):
    namespace=getattr(model,'class_namespaces',None)
    member=None if namespace is None else namespace.members.get((owner.index,name))
    if member is None or member.plan is None:return
    if getattr(member,'source_binding_deleted',False):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'source instance method '+repr(name)+' is deleted during class publication; dynamic instance descriptor lookup for that missing binding is not implemented',proof='deleted instance method binding')
    if getattr(member,'source_function_alias',False):return
    writes=model.namespace.incoming.get(member.key,{})
    if any(role!='method_definition'for role,ordinal in writes):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'source instance method '+repr(name)+' is reassigned during class publication; dynamic instance descriptor binding for that replacement is not implemented',proof='current instance method binding identity')


def plan_aliases(model,owner):
    """Record an original binding's identity without publishing its value."""
    import ast
    namespace=getattr(model,'class_namespaces',None)
    if namespace is None:return
    available={}
    for statement in owner.node.body:
        if isinstance(statement,ast.FunctionDef):
            name=model.unit.name_for(statement);member=namespace.member(owner,name)
            if member.plan is not None and member.descriptor=='function':available[name]=member
            else:available.pop(name,None)
        elif isinstance(statement,ast.Assign):
            alias=None
            if (len(statement.targets)==1 and isinstance(statement.targets[0],ast.Name)
                    and isinstance(statement.value,ast.Name)):
                target=model.unit.name_for(statement.targets[0]);source=model.unit.name_for(statement.value)
                member=namespace.member(owner,target)
                if alias_slot(target) and member.plan is None and source in available:
                    origin=available[source]
                    member.plan=origin.plan;member.function_cell=origin.function_cell
                    member.descriptor='function';member.source_function_alias=True
                    owner.methods[target]=origin.plan;alias=target;available[target]=member
            for target in statement.targets:
                if isinstance(target,ast.Name):
                    name=model.unit.name_for(target)
                    if name!=alias:available.pop(name,None)
        elif isinstance(statement,(ast.AnnAssign,ast.AugAssign)):
            if isinstance(statement.target,ast.Name):available.pop(model.unit.name_for(statement.target),None)
        elif isinstance(statement,ast.Delete):
            for target in statement.targets:
                if isinstance(target,ast.Name):available.pop(model.unit.name_for(target),None)


def method_read(registry,plan,node,environment):
    member=registry.local_member(plan,node)
    return (member is not None and member.plan is not None and member.descriptor=='function'
            and member.name in getattr(environment,'definite',environment))


def bind_alias(registry,plan,node,value):
    from .native_classes import shape,ClassUnsupported
    member=registry.local_member(plan,node)
    if member is None or not alias_slot(member.name):return False
    kind=shape(value);definitions=getattr(kind,'definitions',())
    if(len(definitions)!=1 or getattr(kind,'builtins',())or getattr(kind,'members',())or getattr(kind,'methods',())):
        raise ClassUnsupported(node,'source '+member.name+' slot assignment requires one retained plain source function; arbitrary descriptor/nonfunction slot values are not implemented',proof='source '+member.name+' slot function alias identity')
    target=registry.model.callable_cells.plans[definitions[0]]
    import ast
    if isinstance(target.node,ast.Lambda):
        raise ClassUnsupported(node,'source '+member.name+' slot alias refers to a lambda; retaining that lambda as a class descriptor is not implemented, and it cannot be substituted with an earlier function binding',proof='actual '+member.name+' alias RHS callable identity')
    originals=[candidate for candidate in registry.members.values()if candidate.owner is member.owner and candidate.plan is target and candidate.descriptor=='function']
    if target.owner is not member.owner or not originals:
        raise ClassUnsupported(node,'source '+member.name+' function aliases must retain an existing ordinary function from this class namespace; cross-class/descriptor aliases are not implemented',proof='same-class '+member.name+' function alias')
    if member.plan is not None and not getattr(member,'source_function_alias',False):
        raise ClassUnsupported(node,'replacing an earlier '+member.name+' function definition during class publication requires a versioned slot publication plan; this slice admits new plain function aliases',proof='source '+member.name+' alias publication order')
    member.plan=target;member.function_cell=value;member.descriptor='function';member.source_function_alias=True
    member.owner.methods[member.name]=target
    return True


@dataclass
class DisplaySite:
    member:object
    callback:object
    slot:str


def selected(model,kind,representation):
    from .native_classes import InstanceType
    if not isinstance(kind,InstanceType):return None
    owner=model.classes[kind.name]
    for slot in (('__repr__',)if representation else('__str__','__repr__')):
        if slot in owner.methods:return owner,slot
    return None


def sites(model):
    if not hasattr(model,'source_display_sites'):
        model.source_display_sites={}
        from .native_callback_effects import register
        register(model,lambda plan,node:any(key[:2]==(plan.index,id(node))for key in model.source_display_sites))
    return model.source_display_sites


def children(model,value):
    from .native_classes import Cell,shape
    from .native_types import ListType,TupleSequenceType,TupleType
    kind=shape(value);root=value.root()
    if isinstance(kind,(ListType,TupleSequenceType)):
        return (root.args[0],)if root.args else(model.cell_for_kind(kind.element),)
    if isinstance(kind,TupleType):return root.args or tuple(model.cell_for_kind(child)for child in kind.fields)
    if getattr(kind,'_native_class_mapping',False):return (kind.record.key,kind.record.value)
    if getattr(kind,'_native_mapping_view',False):return (kind.record.element,)
    if getattr(kind,'_native_class_deque',False):return (kind.record.element,)
    return ()


def analyze(model,plan,node,value,environment,representation=False,seen=frozenset()):
    from .native_classes import shape,ClassUnsupported
    from .native_types import alternatives
    from .native_aot_callables import analyze_values
    kind=shape(value)
    if kind is None or kind in seen:return
    seen=seen|{kind}
    if len(alternatives(kind))>1:
        for branch in alternatives(kind):analyze(model,plan,node,model.cell_for_kind(branch),environment,representation,seen)
        return
    choice=selected(model,kind,representation)
    if choice is not None:
        owner,slot=choice;namespace=model.class_namespaces;member=namespace.member(owner,slot)
        if member.descriptor!='function':
            raise ClassUnsupported(node,'source '+slot+' uses a nonfunction descriptor; implicit display through that descriptor is not implemented',proof='source display descriptor binding')
        namespace.observe_method(member,node)
        callback=analyze_values(model.callable_cells,plan,node,namespace.field(member,node),
            CallArguments((Argument(node),),()),[value],[],environment,
            identity=('source_display',kind,representation,slot))
        sites(model)[plan.index,id(node),kind,representation]=DisplaySite(member,callback,slot)
    for child in children(model,value):analyze(model,plan,node,child,environment,True,seen)


def contains(model,kind,representation=False,seen=frozenset()):
    from .native_classes import shape
    from .native_types import alternatives
    if kind is None or kind in seen:return False
    seen=seen|{kind}
    if len(alternatives(kind))>1:return any(contains(model,branch,representation,seen)for branch in alternatives(kind))
    if any(selected(model,branch,representation)is not None for branch in alternatives(kind)):return True
    return any(contains(model,shape(child),True,seen)
               for child in children(model,model.cell_for_kind(kind)))


def recursive_callbacks(emitter,node,kind,seen=frozenset()):
    from .native_classes import shape
    from .native_types import alternatives
    model=emitter.model
    if kind in seen:return False
    seen=seen|{kind}
    if len(alternatives(kind))>1:return any(recursive_callbacks(emitter,node,branch,seen)for branch in alternatives(kind))
    if selected(model,kind,True)is not None:
        site=sites(model).get((emitter.plan.index,id(node),kind,True))
        if site is not None:
            for definition in site.callback.targets:
                if not isinstance(definition,int):continue
                index=model.callable_cells.plans[definition].index
                pending=list(model.call_edges.get(index,()));visited=set()
                while pending:
                    current=pending.pop()
                    if current==index:return True
                    if current not in visited:visited.add(current);pending.extend(model.call_edges.get(current,()))
    return any(recursive_callbacks(emitter,node,shape(value),seen)for value in children(model,model.cell_for_kind(kind)))


def show(emitter,value,node,representation=False):
    from .native_classes import Expression,shape,ClassUnsupported
    from .native_module_linking import ClassReferenceType
    from .native_class_binding_contexts import CapturedClassContext
    from .native_aot_callables import emit_values
    from .native_unions import project,union_kind
    from .native_class_builtins import _type_name
    from .native_types import ListType,TupleType,TupleSequenceType
    model=emitter.model;kind=value.kind
    choice=selected(model,kind,representation)
    if choice is not None:
        site=sites(model).get((emitter.plan.index,id(node),kind,representation))
        if site is None:
            raise ClassUnsupported(node,'source display '+choice[1]+' has no matching analyzed observer boundary; this consumer has not implemented native source display callback effects',proof='source display callback/effect site')
        setup,owner=emitter.capture(value);reference=emitter.fresh()
        setup+='let '+reference+'={'+owner.code+'.borrow().class_definition.clone()};'
        context=Expression(reference,ClassReferenceType(site.member.owner.index))
        function=model.class_namespaces.emit_get(emitter,node,context,site.member)
        before,function=emitter.capture(function);setup+=before
        result=emit_values(emitter,node,site.callback,function,[owner],[],shape(site.callback.result),captured_class_context=CapturedClassContext(site.member,context))
        before,result=emitter.capture(result);setup+=before
        def checked(child,code):
            if child=='str':return 'ClassDisplay::class_str(&('+code+'))'
            if getattr(child,'_native_class_iterator',False)and child.record.operation=='source':
                from .native_classes import domain
                source=domain(shape(child.record.source))
                if source not in {'list','tuple','tuple_sequence','bytes'}:
                    raise ClassUnsupported(node,'source display returns a '+str(source)+' cursor; preserving its Python-specific iterator type name in the non-string return TypeError is not implemented',proof='display return error iterator type name')
            if getattr(child,'_native_class_iterator',False)and child.record.operation=='reverse':
                from .native_classes import domain
                source=domain(shape(child.record.source))
                if source not in {'list','tuple','tuple_sequence','str','bytes'}:
                    raise ClassUnsupported(node,'source display returns a reversed '+str(source)+' cursor; preserving its Python-specific iterator type name in the non-string return TypeError is not implemented',proof='display return error reverse iterator type name')
            actual=_type_name(emitter,Expression(code,child),node)
            return emitter.at('Err::<String,String>(format!("TypeError: '+site.slot+' returned non-string (type {})",'+actual+'))',node)
        rendered=project(result.kind,result.code,checked)if union_kind(result.kind)else checked(result.kind,result.code)
        return '{'+setup+rendered+'}'
    if getattr(kind,'_native_named_tuple',False):
        if recursive_callbacks(emitter,node,kind):
            raise ClassUnsupported(node,'NamedTuple display reaches recursive source repr callbacks; retaining its tuple identity for recursive_repr is not implemented on this tuple ABI',proof='NamedTuple source repr recursion identity')
        return None
    if union_kind(kind):return None
    if not contains(model,kind,representation):return None
    if isinstance(kind,ListType):
        model.source_repr_guard_required=True
        owner,index,item,parts=(emitter.fresh()for _ in range(4))
        rendered=emitter.show(Expression(item,kind.element),node,True)
        advance=emitter.at(index+'.checked_add(1).ok_or_else(||"OverflowError: list repr index overflow".to_owned())',node)
        return ('{let '+owner+'=('+value.code+').clone();match class_source_repr_enter(0,Rc::as_ptr(&'+owner+')as usize){None=>"[...]".to_owned(),Some(_repr_guard)=>{let mut '+index+'=0_usize;let mut '+parts+'=Vec::<String>::new();'
                'loop{let Some('+item+')=({let source='+owner+'.borrow();source.get('+index+').cloned()})else{break;};'
                +index+'='+advance+';'+parts+'.push('+rendered+');}format!("[{}]",'+parts+'.join(", "))}}}')
    if isinstance(kind,TupleSequenceType):
        model.source_repr_guard_required=True
        owner,item,parts=(emitter.fresh()for _ in range(3));rendered=emitter.show(Expression(item,kind.element),node,True)
        return '{let '+owner+'=('+value.code+').clone();let identity='+owner+'.0.as_ref().map(|value|Rc::as_ptr(value)as usize).unwrap_or(0);match class_source_repr_enter(1,identity){None=>"(...)".to_owned(),Some(_repr_guard)=>{let mut '+parts+'=Vec::<String>::new();for '+item+' in '+owner+'.iter().cloned(){'+parts+'.push('+rendered+');}class_tuple_text(&'+parts+')}}}'
    if isinstance(kind,TupleType):
        if recursive_callbacks(emitter,node,kind):
            raise ClassUnsupported(node,'fixed-tuple display reaches recursive source repr callbacks; retaining stable tuple identity for the Python repr recursion guard is not implemented on this tuple ABI',proof='fixed tuple repr recursion identity')
        setup,owner=emitter.capture(value);parts=emitter.fresh();code='let mut '+parts+'=Vec::<String>::new();'
        for index,child in enumerate(kind.fields):code+=parts+'.push('+emitter.show(Expression(owner.code+'.'+str(index)+'.clone()',child),node,True)+');'
        return '{'+setup+code+'class_tuple_text(&'+parts+')}'
    raise ClassUnsupported(node,'displaying this container invokes source __repr__ callbacks while retaining mutable container iteration state; native callback-safe display for this container is not implemented',types=(('container',kind),),proof='source container repr callbacks and mutation order')


def runtime(model):
    if not getattr(model,'source_repr_guard_required',False):return ''
    return '''
thread_local!{static CLASS_SOURCE_REPR_ACTIVE:std::cell::RefCell<std::collections::HashSet<(u8,usize)>>=std::cell::RefCell::new(std::collections::HashSet::new());}
struct ClassSourceReprGuard{key:(u8,usize)}
fn class_source_repr_enter(kind:u8,identity:usize)->Option<ClassSourceReprGuard>{let key=(kind,identity);CLASS_SOURCE_REPR_ACTIVE.with(|active|if active.borrow_mut().insert(key){Some(ClassSourceReprGuard{key})}else{None})}
impl Drop for ClassSourceReprGuard{fn drop(&mut self){CLASS_SOURCE_REPR_ACTIVE.with(|active|{active.borrow_mut().remove(&self.key);});}}
'''
