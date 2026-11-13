"""Canonical typed dictionary pop with ordered captures and moved values."""
from dataclasses import dataclass,replace
from .native_types import EMPTY,EmptyType,TupleType,alternatives


@dataclass
class Pop:
    receiver:object
    result:object
    error:str|None=None


def binding_error(count,keywords):
    if keywords:return 'TypeError: dict.pop() takes no keyword arguments'
    if count<1:return f'TypeError: pop expected at least 1 argument, got {count}'
    if count>2:return f'TypeError: pop expected at most 2 arguments, got {count}'
    return None


def supported(kind):
    from .native_class_mappings import mapping_kind
    return(mapping_kind(kind)and kind.record.category=='dict'
           and kind.record.flavor in {'dict','Counter','defaultdict'})


def require_origin(model,node,kinds):
    if not model.final:return
    from .native_dictionary_positions import proved
    from .native_classes import ClassUnsupported
    if not all(proved(kind,model)for kind in kinds):
        raise ClassUnsupported(node,'dict.pop requires a proved actual constructor/update origin; this custom mapping contents protocol is not implemented',proof='canonical dictionary pop receiver origin')


def _query(model,node,kind):
    from .native_class_mappings import key_supported,key_pending,unhashable_leaf
    from .native_classes import ClassUnsupported
    if kind is None:
        if model.final:raise ClassUnsupported(node,'dict.pop query-key representation remains unresolved',proof='resolved dictionary pop query')
        return
    choices=alternatives(kind)
    if len(choices)>1:
        for choice in choices:_query(model,node,choice)
        return
    if isinstance(kind,TupleType):
        for child in kind.fields:_query(model,node,child)
        return
    if key_pending(kind)and not model.final:return
    if key_supported(kind)or unhashable_leaf(kind)is not None:return
    raise ClassUnsupported(node,'dict.pop query requires an unimplemented floating/custom hash and equality protocol; it cannot be treated as a missing key',types=(('key',kind),),proof='dictionary pop query hash/equality')


def sites(model):
    values=getattr(model,'mapping_pop_calls',None)
    if values is None:
        values=model.mapping_pop_calls={}
        from .native_callback_effects import register
        register(model,lambda plan,node:any(key[:2]==(plan.index,id(node))for key in model.mapping_pop_calls))
    return values


def analyze_values(model,plan,node,receiver,arguments,keywords,*,identity=None):
    from .native_classes import shape
    kinds=alternatives(shape(receiver))
    if not kinds or not all(supported(kind)for kind in kinds):return None
    require_origin(model,node,kinds)
    values=sites(model);key=plan.index,id(node),identity;values.pop(key,None)
    error=binding_error(len(arguments),keywords)
    result=model.cell(plan,node,EMPTY if error else None,identity=('mapping_pop',identity))
    site=Pop(receiver,result,error);values[key]=site
    if error:return site
    _query(model,node,shape(arguments[0]))
    for kind in kinds:
        value=kind.record.value
        if not model.namespace.contribute(result,value,node,force=True):model.contribute(result,value,node)
    if len(arguments)==2:
        if not model.namespace.contribute(result,arguments[1],node,force=True):model.contribute(result,arguments[1],node)
    return site


def analyze(model,plan,node,receiver,arguments,keywords):
    if node.func.attr!='pop':return None
    site=analyze_values(model,plan,node,receiver,arguments,keywords)
    return None if site is None else model.remember(plan,node,site.result)


def _remove(emitter,node,owner,key,default,wanted):
    from .native_classes import Expression,shape
    from .native_class_mappings import query_canonical,key_supported,unhashable_leaf,query_type_name
    from .native_class_builtins import _error
    from .native_types import tuple_code
    from .native_unions import project,union_kind
    from .native import _string
    original=key
    def missing():
        if default is None:
            from .native_integer_digit_limits import guard_error_repr
            guard_error_repr(emitter,original,node)
            return _error(emitter,node,wanted,'format!("KeyError: {}",'+emitter.show(original,node,True)+')').code
        return emitter.coerce(default,wanted,node)
    def lookup(query):
        canonical=query_canonical(emitter,query,shape(owner.kind.record.key))
        hashed,read,slot,value=(emitter.fresh()for _ in range(4))
        removed=('match '+canonical+'{Some('+hashed+')=>{let mut '+read+'='+owner.code+'.borrow_mut();let '+read+'=&mut *'+read+';'
                 +'match '+read+'.index.remove(&'+hashed+'){Some('+slot+')=>Some(native_dict_remove(&mut '+read+'.entries,&mut '+read+'.index,'+slot+').1),None=>None}},None=>None}')
        present=emitter.coerce(Expression(value,shape(owner.kind.record.value)),wanted,node)
        absent=missing()
        found=emitter.fresh()
        return '{let '+found+'='+removed+';match '+found+'{Some('+value+')=>'+present+',None=>{'+absent+'}}}'
    def inspect(value,finish,outer=None):
        kind,code=value.kind,value.code
        if union_kind(kind):return project(kind,code,lambda child,text:inspect(Expression('('+text+').clone()',child),finish,outer))
        if outer is None:outer=value
        if isinstance(kind,EmptyType):return 'native_empty::<'+emitter.rust_type(wanted)+'>('+code+')'
        if isinstance(kind,TupleType):
            def field(index,values):
                if index==len(kind.fields):return finish(Expression(tuple_code(item.code for item in values),replace(kind,fields=tuple(item.kind for item in values))))
                return inspect(Expression('('+code+').'+str(index)+'.clone()',kind.fields[index]),lambda item:field(index+1,values+[item]),outer)
            return field(0,[])
        leaf=unhashable_leaf(kind)
        if leaf is not None:
            return _error(emitter,node,wanted,'format!("TypeError: cannot use \'{}\' as a dict key (unhashable type: \'{}\')",'+query_type_name(emitter,outer,node)+','+_string(leaf)+')').code
        return finish(value)
    empty=emitter.fresh()
    return '{let '+empty+'={'+owner.code+'.borrow().is_empty()};if '+empty+'{'+missing()+'}else{'+inspect(key,lookup)+'}}'


def emit_values(emitter,node,site,owner,arguments,keywords,wanted):
    from .native_classes import Expression
    from .native_unions import project
    if site.error:
        from .native_class_builtins import _error
        from .native import _string
        return _error(emitter,node,wanted,_string(site.error)+'.to_owned()')
    setup,owner=emitter.capture(owner)
    def branch(kind,code):
        name=emitter.fresh();target=Expression(name,kind)
        return '{let '+name+'=('+code+').clone();'+_remove(emitter,node,target,arguments[0],arguments[1]if len(arguments)==2 else None,wanted)+'}'
    return Expression('{'+setup+project(owner.kind,owner.code,branch)+'}',wanted)


def emit(emitter,node):
    from .native_classes import Expression
    from .call_semantics import normalize_call
    site=getattr(emitter.model,'mapping_pop_calls',{}).get((emitter.plan.index,id(node),None))
    if site is None:return None
    if not all(supported(kind)for kind in alternatives(emitter.kind(node.func.value))):return None
    setup,owner=emitter.capture(emitter.expression(node.func.value));arguments=[];keywords=[]
    for argument in normalize_call(node).evaluation_order:
        before,value=emitter.capture(emitter.expression(argument.expression));setup+=before
        if argument.name is None:arguments.append(value)
        else:keywords.append((argument.name,value))
    result=emit_values(emitter,node,site,owner,arguments,keywords,emitter.kind(node))
    return Expression('{'+setup+result.code+'}',result.kind)
