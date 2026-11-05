"""Captured canonical comparison-key factories for native ordering consumers."""
import ast
from dataclasses import dataclass

from .call_semantics import Argument,CallArguments
from .native_types import alternatives,EmptyType


@dataclass(frozen=True)
class CmpKeyType:
    record:object
    _native_stored_reference=True
    _native_reference_cloneable=True
    _native_cmp_key=True
    _native_python_name='functools.KeyWrapper'

    @property
    def _native_kind_tag(self):return 'cmp_key_'+str(self.record.index)

    @property
    def _native_owned_kinds(self):
        from .native_classes import shape
        return (shape(self.record.callback),)


@dataclass(eq=False)
class CmpKey:
    index:int
    callback:object
    result:object=None
    error:str|None=None
    emitted:bool=False


def bind(positional,keywords):
    count=len(positional)+len(keywords)
    if count>1:return None,f'TypeError: cmp_to_key() takes at most 1 argument ({count} given)'
    if positional:return positional[0],None
    value=dict(keywords).get('mycmp')
    if value is None:return None,"TypeError: cmp_to_key() missing required argument 'mycmp' (pos 1)"
    return value,None


def analyze(model,plan,node,identity,metadata,positional,keywords,environment,*,factory):
    from .native_classes import Cell
    callback,error=bind(positional,keywords)
    records=getattr(model,'cmp_key_records',None)
    if records is None:
        records={};model.cmp_key_records=records
        from .native_owned_kinds import register
        register(model,lambda:(CmpKeyType(record)for record in model.cmp_key_records.values()if record.error is None))
    key=plan.index,id(node)
    if key not in records:records[key]=CmpKey(len(records),model.cell(plan,node,identity=('cmp_key_callback',identity)))
    record=records[key];record.error=error
    if error:record.result=factory('none')
    else:
        model.contribute(record.callback,callback,node)
        record.result=factory(CmpKeyType(record))
    return record


def emit(emitter,node,identity,record,positional,keywords):
    from .native import _string
    from .native_classes import Expression,shape
    if record.error:
        return Expression(emitter.at('Err::<(),String>('+_string(record.error)+'.to_owned())',node),'none')
    callback,error=bind(positional,keywords);assert error is None
    record.emitted=True
    return Expression('Rc::new(NativeCmpKey_'+str(record.index)+'{callback:'+emitter.coerce(callback,shape(record.callback),node)+'})',CmpKeyType(record))


def analyze_comparison(model,plan,node,kind,element,environment):
    from .native_aot_callables import analyze_values
    return analyze_values(model.callable_cells,plan,node,kind.record.callback,
        CallArguments((Argument(node),Argument(node)),()),[element,element],[],environment,
        identity=('sorting_cmp',kind.record.index))


def _negative(emitter,node,value):
    from .native import _string
    from .native_classes import Expression,domain
    from .native_unions import union_kind,project
    if union_kind(value.kind):
        return project(value.kind,value.code,lambda kind,code:_negative(emitter,node,Expression(code,kind)))
    if isinstance(value.kind,EmptyType):return 'native_empty::<bool>('+value.code+')'
    if domain(value.kind)=='float':return '('+value.code+')<0.0'
    if domain(value.kind)in {'int','bool','int_bool'}:
        return '('+emitter.number(value)+')<'+emitter.numeric.literal(0)
    if domain(value.kind)=='object'and '__lt__'in emitter.model.classes[value.kind.name].methods:
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'the comparison callback returned an object with __lt__; invoking that rich comparison against zero is not implemented by the native comparison-key consumer',types=(('callback result',value.kind),),proof='comparison-result rich ordering protocol')
    from .native_class_builtins import _type_name
    message=_string("TypeError: '<' not supported between instances of '{}' and 'int'")
    return emitter.at('Err::<bool,String>(format!('+message+','+_type_name(emitter,value,node)+'))',node)


def sort(emitter,node,values,element,reverse,key,site):
    from .native import _string
    from .native_classes import Expression,shape
    from .native_aot_callables import emit_values
    from .native_class_calls import entry_result
    record=site.comparators[key.kind]
    first,second,result,order,error=(emitter.fresh()for _ in range(5))
    callback=Expression('('+key.code+').callback.clone()',shape(key.kind.record.callback))
    value=emit_values(emitter,node,record,callback,
        [Expression(values+'['+first+'].clone()',element),Expression(values+'['+second+'].clone()',element)],[],shape(record.result))
    comparison='let '+result+'='+value.code+';Ok::<bool,NativeError>('+_negative(emitter,node,Expression(result,value.kind))+')'
    asynchronous=not entry_result(emitter.model,emitter.plan)
    modes=getattr(emitter.model,'cmp_sort_modes',None)
    if modes is None:modes=set();emitter.model.cmp_sort_modes=modes
    modes.add(asynchronous)
    closure=('async 'if asynchronous else'')+'|'+first+':usize,'+second+':usize|{'+comparison+'}'
    memory='||native_at::<()>(Err("MemoryError: cannot allocate sorting indices".to_owned()),'+str(node.lineno)+','+emitter.location_code()+').unwrap_err()'
    invocation='native_cmp_sort_indices'+('_async'if asynchronous else'')+'('+values+'.len(),'+reverse+','+closure+','+memory+')'+('.await'if asynchronous else'')+'?'
    return ('let(mut '+order+','+error+')='+invocation+';native_cmp_sort_apply(&mut '+values+',&mut '+order+');'
            'if let Some(error)='+error+'{return Err(error);}')


def runtime(model,emitter):
    records=getattr(model,'cmp_key_records',{})
    lines=[]
    for record in records.values():
        if record.error is not None or not record.emitted:continue
        from .native_classes import shape
        lines.append('struct NativeCmpKey_'+str(record.index)+'{callback:'+emitter.rust_type(shape(record.callback))+'}')
    modes=getattr(model,'cmp_sort_modes',set())
    if modes:
        from .native_cmp_sorting import kernel
        from importlib.resources import files
        lines.append(files('py2fastrust').joinpath('runtime','native_cmp_sort.rs').read_text(encoding='utf-8'))
        for mode in sorted(modes):
            full=kernel(asynchronous=mode)
            lines.append(full[full.index('async fn native_cmp_gallop_left'if mode else'fn native_cmp_gallop_left'):])
    return '\n'.join(lines)
