"""Explicit C-iterator exception boundaries and deferred Python caller frames."""
from contextlib import contextmanager


def result(emitter,value):
    from .native_class_calls import entry_result
    code='Ok::<Option<'+emitter.rust_type(value.kind)+'>,NativeError>('+value.code+')'
    return ('(||{'+code+'})()'if entry_result(emitter.model,emitter.plan)else'(async{'+code+'}).await')


@contextmanager
def context(emitter):
    previous=getattr(emitter,'iterator_callback_context',None)
    old_visible=getattr(emitter,'exception_origin_visible',True)
    marker=previous or emitter.fresh()
    emitter.iterator_callback_context=marker
    emitter.exception_origin_visible=False
    try:yield marker,previous is None
    finally:
        emitter.iterator_callback_context=previous
        emitter.exception_origin_visible=old_visible


def boundary(emitter,node,value,marker,*,clear,owner):
    from .native_classes import Expression
    from .native_exception_values import is_stop
    from .native import _string
    item,error=emitter.fresh(),emitter.fresh()
    clear='true'if clear is True else'false'if clear is False else clear
    stop='if ('+clear+')&&('+is_stop(emitter,error)+'){'+marker+'=false;None}else'
    propagate=''
    if owner:
        condition=marker+('||!'+error+'.origin_visible'if emitter.model.exceptions.used else'')
        propagate='if '+condition+'{'+error+'.frames.push(('+str(node.lineno)+','+emitter.location_code()+'));'
        if emitter.model.exceptions.used:propagate+='class_exception_sync(&'+error+');'
        propagate+='}'
    code='match '+result(emitter,value)+'{Ok('+item+')=>'+item+',Err(mut '+error+')=>{'+stop+'{'+propagate+'return Err('+error+');}}}'
    return Expression('{'+('let mut '+marker+'=false;'if owner else'')+code+'}',value.kind)


def callback_call(emitter,invocation,callee,node):
    from .native_class_calls import entry_result
    marker=emitter.iterator_callback_context
    entered,value,error,called=(emitter.fresh()for _ in range(4))
    prefix=''
    if entry_result(emitter.model,callee):
        prefix='let mut '+entered+'=false;'
        call='class_sync_call(&class_scope,||{'+entered+'=true;'+invocation+'},'+str(node.lineno)+','+emitter.location_code()+')'
        entered_code=entered
    else:
        future,flag=emitter.fresh(),emitter.fresh()
        prefix='let '+entered+'=Rc::new(std::cell::Cell::new(false));let '+flag+'='+entered+'.clone();let '+future+'='+invocation+';'
        call='class_call(class_scope.clone(),Box::pin(async move{'+flag+'.set(true);'+future+'.await}),'+str(node.lineno)+','+emitter.location_code()+').await'
        entered_code=entered+'.get()'
    update=error+'.frames.pop();'
    if emitter.model.exceptions.used:update+='class_exception_sync(&'+error+');'
    update+=marker+'=true;'
    return '{'+prefix+'let '+called+'='+call+';match '+called+'{Ok('+value+')=>Ok('+value+'),Err(mut '+error+')=>{if '+entered_code+'{'+update+'}Err('+error+')}}}?'


def cleanup_pull(emitter,value,cleanup):
    """A C adapter can release its own state before forwarding any source error."""
    from .native_classes import Expression
    item,error=emitter.fresh(),emitter.fresh()
    return Expression('match '+result(emitter,value)+'{Ok('+item+')=>'+item+',Err('+error+')=>{'+cleanup+'return Err('+error+');}}',value.kind)
