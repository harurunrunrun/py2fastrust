"""Native keyed bisection releases each visited list read before callbacks."""

def emit(emitter,node,identity,site,owner,item,key,bounds,wanted):
    from .native_classes import Expression,shape,domain,ClassUnsupported
    from .native_unions import project,union_kind
    from .native_aot_callables import emit_values
    from .native_class_builtins import _type_name,_error
    from .native_frame_bisect import _checked_advance
    from .native import _string
    mutating=identity.name.startswith('insort');right=not identity.name.endswith('_left')
    score_kind=shape(site.callback.result)if site.callback is not None else None
    if mutating and score_kind is None:
        raise ClassUnsupported(node,'the insort key callback result storage remains unresolved',proof='solved key result from the inserted item')
    handle,callback=emitter.fresh(),emitter.fresh()
    setup='let '+handle+'=('+owner.code+').clone();let '+callback+'=('+key.code+').clone();'
    key=Expression(callback,key.kind)
    probe=item
    def invoke(value):
        if site.callback is None:
            raise ClassUnsupported(node,'the bisect key callback has no solved visited-element demand site',proof='typed per-visited-element callback demand')
        return emit_values(emitter,node,site.callback,Expression(key.code+'.clone()',key.kind),[value],[],score_kind).code
    if mutating:
        new_score=emitter.fresh();setup+='let '+new_score+'='+invoke(Expression('('+item.code+').clone()',item.kind))+';';probe=Expression(new_score,score_kind)
    def leaf(kind,text):
        low,high,mid,value,score,advance=(emitter.fresh()for _ in range(6))
        before='let mut '+low+'='+bounds[0]+'.unwrap_or(0);let mut '+high+'='+bounds[1]+'.unwrap_or(-1);'
        before+='if '+low+'<0{'+_error(emitter,node,'none',_string('ValueError: lo must be non-negative')+'.to_owned()').code+';}'
        if domain(kind)!='list':
            source=Expression(text,kind);typename=_type_name(emitter,source,node)
            length_error='format!("TypeError: object of type \'{}\' has no len()",'+typename+')'
            index_error='format!("TypeError: \'{}\' object does not support indexing",'+typename+')'
            before+='if '+high+'== -1{'+_error(emitter,node,'none',length_error).code+';}'
            return '{'+before+_error(emitter,node,wanted,index_error).code+'}'
        if score_kind is None:
            raise ClassUnsupported(node,'the bisect key result storage remains unresolved for this list element family',proof='solved visited-element key result')
        length=emitter.fresh()
        before+='if '+high+'== -1{let '+length+'=('+text+').borrow().len();'+high+'='+emitter.at('isize::try_from('+length+').map_err(|_|"OverflowError: sequence is too large".to_owned())',node)+';}'
        fetched='{let values=('+text+').borrow();values.get('+mid+' as usize).cloned().ok_or_else(||"IndexError: list index out of range".to_owned())}'
        before+='while '+low+'<'+high+'{let '+mid+'='+low+'+('+high+'-'+low+')/2;let '+value+'='+emitter.at(fetched,node)+';'
        before+='let '+score+'='+invoke(Expression(value,kind.element))+';'
        comparison=_checked_advance(emitter,score_kind,probe.kind,node,right)
        before+='let '+advance+'='+emitter.at('('+comparison+')(&'+score+',&('+probe.code+'))',node)+';'
        before+='if '+advance+'{'+low+'='+mid+'+1;}else{'+high+'='+mid+';}}'
        if mutating:
            stored=emitter.coerce(item,kind.element,node);values,position=emitter.fresh(),emitter.fresh()
            before+='let mut '+values+'=('+text+').borrow_mut();let '+position+'=('+low+' as usize).min('+values+'.len());'
            before+=emitter.at(values+'.try_reserve(1).map_err(|_|"MemoryError: cannot allocate list".to_owned())',node)+';'
            return '{'+before+values+'.insert('+position+','+stored+');()}'
        return '{'+before+'class_from_usize('+low+' as usize)}'
    code=project(owner.kind,handle,lambda kind,text:leaf(kind,'('+text+').clone()'))if union_kind(owner.kind)else leaf(owner.kind,handle)
    return '{'+setup+code+'}'
