"""Canonical source length and truth calls with checked structural lengths."""
from dataclasses import dataclass

from .call_semantics import Argument,CallArguments


@dataclass
class ProtocolSite:
    member:object
    callback:object
    slot:str


def member(model,kind,slots,node):
    """Distinguish a missing slot from an unsupported current slot binding."""
    from .native_classes import InstanceType,ClassUnsupported
    if not isinstance(kind,InstanceType):return None
    owner=model.classes[kind.name]
    namespace=getattr(model,'class_namespaces',None)
    for slot in slots:
        value=None if namespace is None else namespace.members.get((owner.index,slot))
        if value is None:
            if slot in owner.methods:
                raise ClassUnsupported(node,'source '+slot+' needs its canonical class namespace and current function binding',proof='source special-method lookup identity')
            continue
        if getattr(value,'source_binding_deleted',False):
            raise ClassUnsupported(node,'source '+slot+' was deleted during class publication; dynamic missing-slot fallback is not implemented',proof='current source special-method presence')
        if value.plan is None or value.descriptor!='function':
            raise ClassUnsupported(node,'source '+slot+' exists in the class namespace but is not a retained ordinary source method; nonfunction/lambda/descriptor slot dispatch is not implemented',proof='source special-method descriptor binding')
        from .native_source_display import guard_direct_method
        guard_direct_method(model,owner,slot,node)
        return value
    if owner.node.bases:
        raise ClassUnsupported(node,'inherited '+ '/'.join(slots)+' lookup needs a proved class MRO; absence from this class namespace does not establish a missing inherited slot',proof='source inherited special-method lookup')
    return None


def sites(model):
    if not hasattr(model,'source_length_sites'):
        model.source_length_sites={}
        from .native_callback_effects import register
        register(model,lambda plan,node:any(key[:2]==(plan.index,id(node))for key in model.source_length_sites))
    return model.source_length_sites


def analyze_slot(model,plan,node,value,environment,slot,identity=None):
    from .native_classes import shape,ClassUnsupported
    from .native_guard_flow import AnalysisPending
    from .native_aot_callables import analyze_values
    kind=shape(value)
    selected=member(model,kind,(slot,),node)
    if selected is None:return None
    if environment is None:
        site=sites(model).get((plan.index,id(node),kind,slot,identity))
        if site is None:
            raise ClassUnsupported(node,'source '+slot+' needs its original argument-evaluation environment; this consumer has not implemented that callback boundary',proof='source special-method callback effects')
        return site
    namespace=model.class_namespaces
    namespace.observe_method(selected,node)
    callback=analyze_values(model.callable_cells,plan,node,namespace.field(selected,node),
        CallArguments((Argument(node),),()),[value],[],environment,
        identity=('source_special_protocol',slot,kind,identity))
    site=ProtocolSite(selected,callback,slot)
    sites(model)[plan.index,id(node),kind,slot,identity]=site
    if shape(callback.result)is None:
        if not model.final:raise AnalysisPending()
        if not callback.errors:
            raise ClassUnsupported(node,'source '+slot+' result storage remains unresolved',proof='resolved source special-method result')
    return site


def emit_slot(emitter,node,value,site):
    from .native_classes import Expression,shape
    from .native_module_linking import ClassReferenceType
    from .native_class_binding_contexts import CapturedClassContext
    from .native_aot_callables import emit_values
    # Truth observation must retain the original value for `and`/`or` result
    # selection. Clone its existing shared handle, never replay its producer.
    setup,owner=emitter.capture(Expression('('+value.code+').clone()',value.kind));reference=emitter.fresh()
    setup+='let '+reference+'={'+owner.code+'.borrow().class_definition.clone()};'
    context=Expression(reference,ClassReferenceType(site.member.owner.index))
    function=emitter.model.class_namespaces.emit_get(emitter,node,context,site.member)
    before,function=emitter.capture(function);setup+=before
    wanted=shape(site.callback.result)or'int'
    result=emit_values(emitter,node,site.callback,function,[owner],[],wanted,
        captured_class_context=CapturedClassContext(site.member,context))
    before,result=emitter.capture(result)
    return setup+before,result


def analyze_length(model,plan,node,value,environment,*,identity=None):
    from .native_classes import shape,Cell,Environment
    from .native_types import alternatives
    kind=shape(value)
    if kind is None:return None
    branches=alternatives(kind)
    if len(branches)>1:
        joined=None;handled=False
        for branch in branches:
            inside=Environment(environment)
            handled|=analyze_length(model,plan,node,model.cell_for_kind(branch),inside,identity=identity)is not None
            joined=inside if joined is None else model.join(joined,inside,node,'length_protocol_union')
        model.replace_environment(environment,joined)
        return model.cell(plan,node,'int',identity=('source_length_result',identity))if handled else None
    site=analyze_slot(model,plan,node,value,environment,'__len__',identity)
    return model.cell(plan,node,'int',identity=('source_length_result',identity))if site is not None else None


def analyze_truth(model,plan,node,value,environment,*,identity=None):
    from .native_classes import shape,InstanceType,Environment
    from .native_types import alternatives
    kind=shape(value)
    if kind is None:return None
    branches=alternatives(kind)
    if len(branches)>1:
        joined=None;handled=False
        for branch in branches:
            inside=Environment(environment)
            handled|=analyze_truth(model,plan,node,model.cell_for_kind(branch),inside,identity=identity)is not None
            joined=inside if joined is None else model.join(joined,inside,node,'truth_protocol_union')
        model.replace_environment(environment,joined)
        return model.cell(plan,node,'bool',identity=('source_truth_result',identity))if handled else None
    if not isinstance(kind,InstanceType):return None
    selected=member(model,kind,('__bool__','__len__'),node)
    if selected is not None:analyze_slot(model,plan,node,value,environment,selected.name,identity)
    return model.cell(plan,node,'bool',identity=('source_truth_result',identity))


def _checked_length(emitter,node,value):
    from .native_classes import Expression,InstanceType,ClassUnsupported
    from .native_unions import project
    from .native_types import EmptyType
    from .native_class_builtins import _type_name
    def leaf(kind,code):
        if isinstance(kind,EmptyType):return 'native_empty::<usize>('+code+')'
        current=Expression('('+code+').clone()',kind)
        if kind in {'int','bool','int_bool'}:
            emitter.model.source_length_runtime=True
            return emitter.at('class_source_length(&('+emitter.number(current)+'))',node)
        if isinstance(kind,InstanceType):
            owner=emitter.model.classes[kind.name]
            namespace=getattr(emitter.model,'class_namespaces',None)
            if owner.node.bases or '__index__'in owner.methods or namespace is not None and(owner.index,'__index__')in namespace.members:
                raise ClassUnsupported(node,'source __len__ returned an object requiring its __index__ method; that integer-index callback adapter is not implemented',types=(('__len__ result',kind),),proof='source length result integer-index conversion')
        actual=_type_name(emitter,current,node)
        return emitter.at('Err::<usize,String>(format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+actual+'))',node)
    return project(value.kind,value.code,leaf)


def emit_length_size(emitter,node,value,*,identity=None):
    from .native_classes import Expression,InstanceType,ClassUnsupported
    if not isinstance(value.kind,InstanceType):return None
    selected=member(emitter.model,value.kind,('__len__',),node)
    if selected is None:return None
    site=sites(emitter.model).get((emitter.plan.index,id(node),value.kind,'__len__',identity))
    if site is None:
        raise ClassUnsupported(node,'source __len__ has no analyzed callback boundary for this consumer',proof='source length callback effects and evaluation order')
    before,result=emit_slot(emitter,node,value,site)
    return '{'+before+_checked_length(emitter,node,result)+'}'



def emit_length(emitter,node,value,*,identity=None):
    from .native_classes import Expression
    result=emit_length_size(emitter,node,value,identity=identity)
    return Expression('class_from_usize('+result+')','int')if result is not None else None


def analyze_hint(model,plan,node,value,environment,consumer):
    """List construction consults the original owner's length after iter()."""
    return analyze_length(model,plan,node,value,environment,identity=('length_hint',consumer))


def emit_hint(emitter,node,value,consumer):
    from .native_classes import InstanceType,Expression
    from .native_types import alternatives
    from .native_unions import project
    if not any(isinstance(kind,InstanceType)for kind in alternatives(value.kind)):return None
    model=emitter.model
    def leaf(kind,code):
        size=emit_length_size(emitter,node,Expression('('+code+').clone()',kind),identity=('length_hint',consumer))
        if size is None:return '8_usize'
        from .native_class_calls import entry_result
        body='Ok::<usize,NativeError>('+size+')'
        call=('(||->ClassResult<usize>{'+body+'})()'if entry_result(model,emitter.plan)else'(async{'+body+'}).await')
        typed=model.exceptions.used
        suppress='error.message=="TypeError"||error.message.starts_with("TypeError:")'
        if typed:suppress='error.exception_kind==Some(ClassExceptionKind::TypeError)||('+suppress+')'
        # A swallowed internal hint call never adds this outer Python frame to
        # a retained exception object. Keep actual callback frames intact.
        frame='('+str(node.lineno)+','+emitter.location_code()+')'
        clean='if error.frames.last()==Some(&'+frame+'){error.frames.pop();}'
        if typed:clean+='class_exception_sync(&error);'
        return 'match '+call+'{Ok(value)=>value,Err(mut error)if '+suppress+'=>{'+clean+'8_usize},Err(error)=>return Err(error)}'
    return project(value.kind,value.code,leaf)


def reserve_hint(emitter,node,values,hint):
    if hint is None:return ''
    emitter.model.source_hint_reserve=True
    return emitter.at('class_source_hint_reserve(&mut '+values+','+hint+')',node)+';'


def emit_truth(emitter,node,value,*,identity=None):
    from .native_classes import Expression,InstanceType,ClassUnsupported
    from .native_unions import union_kind,project
    from .native_types import alternatives,EmptyType
    if union_kind(value.kind):
        if not any(isinstance(part,InstanceType)for part in alternatives(value.kind)):return None
        return project(value.kind,value.code,lambda kind,code:emitter.truth(Expression('('+code+').clone()',kind),node,identity=identity))
    if not isinstance(value.kind,InstanceType):return None
    selected=member(emitter.model,value.kind,('__bool__','__len__'),node)
    if selected is None:return 'true'
    if node is None:
        raise ClassUnsupported(emitter.plan.node,'source truth conversion needs its original observer location; this implicit consumer has not implemented source truth callbacks',proof='source truth callback location')
    site=sites(emitter.model).get((emitter.plan.index,id(node),value.kind,selected.name,identity))
    if site is None:
        raise ClassUnsupported(node,'source '+selected.name+' truth conversion has no analyzed callback boundary for this consumer',proof='source truth callback effects and evaluation order')
    before,result=emit_slot(emitter,node,value,site)
    if site.slot=='__len__':checked='('+_checked_length(emitter,node,result)+')!=0'
    else:
        from .native_class_builtins import _type_name
        def leaf(kind,code):
            if isinstance(kind,EmptyType):return 'native_empty::<bool>('+code+')'
            if kind=='bool':return code
            if kind=='int_bool':
                error=emitter.at('Err::<bool,String>("TypeError: __bool__ should return bool, returned int".to_owned())',node)
                return 'match '+code+'{NativeScalar::Bool(value)=>value,NativeScalar::Int(_)=>'+error+'}'
            actual=_type_name(emitter,Expression(code,kind),node)
            return emitter.at('Err::<bool,String>(format!("TypeError: __bool__ should return bool, returned {}",'+actual+'))',node)
        checked=project(result.kind,result.code,leaf)
    return '{'+before+checked+'}'


def runtime(model):
    reserve=('fn class_source_hint_reserve<T>(values:&mut Vec<T>,hint:usize)->Result<(),String>{'
             'if hint>isize::MAX as usize/std::mem::size_of::<usize>(){return Err(\"MemoryError\".to_owned());}'
             'values.try_reserve_exact(hint).map_err(|_|\"MemoryError\".to_owned())}'
             if getattr(model,'source_hint_reserve',False)else'')
    if not getattr(model,'source_length_runtime',False):return reserve
    negative='value.is_negative()'if model.integer=='bigint'else'*value<0'
    wide='value.to_i128()'if model.integer=='bigint'else'Some(*value as i128)'
    return ('fn class_source_length(value:&NativeInt)->Result<usize,String>{'
            'if '+negative+'{return Err("ValueError: __len__() should return >= 0".to_owned());}'
            'let length=('+wide+').and_then(|value|isize::try_from(value).ok()).ok_or_else(||"OverflowError: cannot fit \'int\' into an index-sized integer".to_owned())?;'
            'Ok(length as usize)}')+reserve
