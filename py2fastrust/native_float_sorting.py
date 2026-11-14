"""Typed less-than floating sorts over the existing CPython index schedule."""
import ast

from .native_float_identity import floating


def requires_frames(unit,analysis):
    from .native_types import ListType,TupleType,TupleSequenceType,alternatives
    from .native_key_types import DictType,SetType
    from .references import BuiltinIdentity
    def floating_items(kind):
        for branch in alternatives(kind):
            if isinstance(branch,(ListType,TupleSequenceType))and floating(branch.element):return True
            if isinstance(branch,TupleType)and any(floating(part)for part in branch.fields):return True
            if isinstance(branch,(DictType,SetType))and floating(branch.key):return True
        return False
    def floating_key(facts,node):
        for keyword in node.keywords:
            if keyword.arg!='key':continue
            value=facts.values.get(unit.ordinal(keyword.value))
            if BuiltinIdentity('float')in getattr(value,'alternatives',()):return True
        return False
    for node in ast.walk(unit.tree):
        if not isinstance(node,ast.Call):continue
        site=unit.ordinal(node)
        for facts in analysis.scopes.values():
            call=facts.calls.get(site)
            if call is not None and BuiltinIdentity('sorted')in call.identity.alternatives:
                if floating_key(facts,node)or any(floating_items(facts.expressions.get(unit.ordinal(argument)))for argument in node.args):return True
            if isinstance(node.func,ast.Attribute)and node.func.attr=='sort':
                receiver=facts.expressions.get(unit.ordinal(node.func.value))
                if any(isinstance(kind,ListType)and(floating(kind.element)or floating_key(facts,node))for kind in alternatives(receiver)):return True
    return False


def analyze(model,plan,node,site,*,method):
    from .native_classes import shape
    from .native_float_identity import require
    from .native_types import alternatives
    if site.error:return
    for branch in alternatives(shape(site.key)):
        if getattr(branch,'_native_cmp_key',False):continue
        value=site.element if branch=='none'else(site.callback.result if site.callback is not None else None)
        if value is not None:require(model,plan,node,('sorting',method,branch),value)



def guard_source(emitter,node,source):
    from .native_class_mappings import mapping_kind
    from .native_numeric_keys import observe_set
    from .native_types import alternatives
    for kind in alternatives(source.kind):
        if mapping_kind(kind)and kind.record.category=='set':observe_set(emitter,kind,node)


def emit(emitter,node,values,key_kind,reverse,*,decorated):
    if not floating(key_kind):return None
    from .native_classes import Expression,ClassUnsupported
    from .native_float_identity import builtin_container
    from .native_class_calls import entry_result
    if not builtin_container(key_kind):
        raise ClassUnsupported(node,'floating sorting keys require the registered builtin numeric/list/tuple less-than and identity protocols; this nominal or custom key protocol has no native adapter',types=(('key',key_kind),),proof='typed floating sorting comparison')
    first,second,order,error=(emitter.fresh()for _ in range(4))
    suffix='.0'if decorated else''
    left=Expression(values+'['+first+']'+suffix,key_kind,owned=False)
    right=Expression(values+'['+second+']'+suffix,key_kind,owned=False)
    less=emitter.comparison(ast.Lt(),left,right,node)
    asynchronous=not entry_result(emitter.model,emitter.plan)
    modes=getattr(emitter.model,'cmp_sort_modes',None)
    if modes is None:modes=set();emitter.model.cmp_sort_modes=modes
    modes.add(asynchronous)
    closure=('async 'if asynchronous else'')+'|'+first+':usize,'+second+':usize|{Ok::<bool,NativeError>('+less+')}'
    memory='||native_at::<()>(Err("MemoryError: cannot allocate sorting indices".to_owned()),'+str(node.lineno)+','+emitter.location_code()+').unwrap_err()'
    invocation='native_cmp_sort_indices'+('_async'if asynchronous else'')+'('+values+'.len(),'+reverse+','+closure+','+memory+')'+('.await'if asynchronous else'')+'?'
    return ('let(mut '+order+','+error+')='+invocation+';native_cmp_sort_apply(&mut '+values+',&mut '+order+');'
            'if let Some(error)='+error+'{return Err(error);}')
