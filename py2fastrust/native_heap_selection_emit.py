"""Native selection kernels retain at most the requested number of entries."""
import ast
from .native_types import EmptyType,alternatives


def _length(emitter,node,source):
    from .native_classes import Expression,domain
    from .native_unions import union_kind,project
    if union_kind(source.kind):return project(source.kind,source.code,lambda kind,text:_length(emitter,node,Expression('('+text+').clone()',kind)))
    tag=domain(source.kind);owner='('+source.code+')'
    if tag=='dict_view':length=emitter.model.mappings.views.length(emitter,source)
    elif tag in {'list','dict','set','deque'}:length=owner+'.borrow().len()'
    elif tag=='str':length=owner+('.len()'if emitter.model.string_mode=='ascii'else'.codepoint_len()')
    elif tag in {'bytes','tuple_sequence'}:length=owner+'.len()'
    elif tag=='tuple':length=str(len(source.kind.fields))+'_usize'
    elif tag=='range':
        variable=emitter.fresh();size=emitter.fresh()
        if emitter.model.integer=='bigint':
            body=('let one=Int::from_i128(1);let zero=Int::from_i128(0);'
                  'let count=if '+variable+'.step.is_negative(){if '+variable+'.start<='+variable+'.stop{zero}else{'+variable+'.start.sub(&'+variable+'.stop).sub(&one).divmod(&'+variable+'.step.abs()).unwrap().0.add(&one)}}'
                  'else{if '+variable+'.start>='+variable+'.stop{zero}else{'+variable+'.stop.sub(&'+variable+'.start).sub(&one).divmod(&'+variable+'.step).unwrap().0.add(&one)}};'
                  'let '+size+'=count.to_usize().filter(|value|*value<=isize::MAX as usize).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned());')
        else:
            body=('let count:u128=if '+variable+'.step>0{if '+variable+'.start>='+variable+'.stop{0}else{let distance=('+variable+'.stop as u128).wrapping_sub('+variable+'.start as u128);(distance-1)/('+variable+'.step as u128)+1}}'
                  'else{if '+variable+'.start<='+variable+'.stop{0}else{let distance=('+variable+'.start as u128).wrapping_sub('+variable+'.stop as u128);(distance-1)/('+variable+'.step.unsigned_abs()as u128)+1}};'
                  'let '+size+'=usize::try_from(count).ok().filter(|value|*value<=isize::MAX as usize).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned());')
        length='{let '+variable+'=&'+owner+';'+body+emitter.at(size,node)+'}'
    else:return 'None::<usize>'
    return 'Some('+length+')'


def _has_length(kind):
    from .native_classes import domain
    return any(domain(choice)in {'dict_view','list','dict','set','deque','str','bytes','tuple_sequence','tuple','range'}for choice in alternatives(kind))


def emit_selected(emitter,node,identity,site,count,source,key,wanted):
    from .native_classes import Expression,shape,ClassUnsupported
    from .native_aot_callables import emit_values
    from .native_class_sorting import _sort,_ordering
    from .native_class_builtins import _error
    from .native import _string
    element=shape(site.element)
    if element is None:raise ClassUnsupported(node,'the heap selection element storage remains unresolved',proof='solved selection payload')
    largest=identity.name=='nlargest'
    zero=Expression(emitter.literal(0),'int');one=Expression(emitter.literal(1),'int')
    is_one=emitter.comparison(ast.Eq(),count,one,node)
    positive=emitter.comparison(ast.Gt(),count,zero,node)
    number=emitter.number(count)
    capacity=(number+'.to_usize().unwrap_or(usize::MAX)'if emitter.model.integer=='bigint'else'usize::try_from('+number+').unwrap_or(usize::MAX)')
    size=emitter.fresh();capacity_name=emitter.fresh();snapshot=emitter.fresh()
    setup='let '+capacity_name+'=if '+positive+'{'+capacity+'}else{0};'
    has_length=_has_length(source.kind)
    if has_length:setup+='let '+size+'=if '+is_one+'{None::<usize>}else{'+_length(emitter,node,source)+'};'
    score_kind=element if key.kind=='none'else shape(site.callback.result)if site.callback is not None else None
    if score_kind is None and not isinstance(element,EmptyType):raise ClassUnsupported(node,'the heap selection key result storage remains unresolved',proof='solved selection score')
    if score_kind is not None and any(kind=='float'for kind in _nested(score_kind)):
        raise ClassUnsupported(node,'heap selection decorates retained keys with stable ordinals; binary64 NaN/object identity in decorated tuple comparisons and stable final sorting are not implemented',types=(('score',score_kind),),proof='identity-aware floating decorated selection')

    def consume(action):
        if getattr(source.kind,'_native_class_generator',False):
            return emitter.model.generators.consume(emitter,node,'eager_member',source,[source],{},'none',append_item=action).code+';'
        cursor=emitter.model.iterators.construct(emitter,node,source,kind=site.source)
        before,cursor=emitter.capture(cursor);pulled=emitter.model.iterators.pull(emitter,node,cursor);item=emitter.fresh()
        return before+'loop{let Some('+item+')=('+pulled.code+')else{break;};'+action(emitter,Expression(item,pulled.kind))+'}'
    def snapshot_append(current,item):
        if isinstance(item.kind,EmptyType):return 'match '+item.code+'{};'
        return current.at(snapshot+'.try_reserve(1).map_err(|_|"MemoryError: cannot allocate selection input".to_owned())',node)+';'+snapshot+'.push('+current.coerce(item,element,node)+');'
    if not has_length:
        return '{'+setup+_bounded(emitter,node,site,source,key,element,score_kind,capacity_name,largest,consume,_ordering)+'}'
    sorted_body='let mut '+snapshot+'=Vec::<'+emitter.rust_type(element)+'>::new();'+consume(snapshot_append)
    if not isinstance(element,EmptyType):sorted_body+=_sort(emitter,node,snapshot,element,str(largest).lower(),key,site)
    sorted_body+='class_list('+snapshot+')'
    bounded=_bounded(emitter,node,site,source,key,element,score_kind,capacity_name,largest,consume,_ordering)
    # A real known length controls the snapshot route, rather than a source spelling.
    full=size+'.is_some_and(|length|'+capacity_name+'>=length)'
    return '{'+setup+'if '+full+'{'+sorted_body+'}else{'+bounded+'}}'


def _nested(kind):
    from .native_types import TupleType,TupleSequenceType,ListType
    for choice in alternatives(kind):
        yield choice
        if isinstance(choice,TupleType):
            for child in choice.fields:yield from _nested(child)
        elif isinstance(choice,(ListType,TupleSequenceType)):yield from _nested(choice.element)


def _bounded(emitter,node,site,source,key,element,score_kind,capacity,largest,consume,ordering):
    from .native_classes import Expression
    from .native_aot_callables import emit_values
    heap,ordinal,initialized=(emitter.fresh()for _ in range(3))
    if isinstance(element,EmptyType):
        def impossible(current,item):return 'match '+item.code+'{};'
        if getattr(source.kind,'_native_class_generator',False):
            body='if '+capacity+'>0{'+consume(impossible)+'}'
        else:
            cursor=emitter.model.iterators.construct(emitter,node,source,kind=site.source)
            before,cursor=emitter.capture(cursor);pulled=emitter.model.iterators.pull(emitter,node,cursor);item=emitter.fresh()
            body=before+'if '+capacity+'>0{loop{let Some('+item+')=('+pulled.code+')else{break;};match '+item+'{}}}'
        return body+'class_list(Vec::<NativeEmpty>::new())'
    entry='('+emitter.rust_type(score_kind)+',usize,'+emitter.rust_type(element)+')'
    code='let mut '+heap+'=Vec::<'+entry+'>::new();let mut '+ordinal+':usize=0;let mut '+initialized+'=false;'
    emitter.model.native_frame_heaps=getattr(emitter.model,'native_frame_heaps',set())|{'native_heapify','native_heapreplace'}
    def compare_entries(a,b,*,finish=False):
        left,right=Expression(a+'.0.clone()',score_kind),Expression(b+'.0.clone()',score_kind)
        equal=emitter.comparison(ast.Eq(),left,right,node)
        primary=ordering(emitter,left,right,node)if finish or largest else ordering(emitter,right,left,node)
        tie=a+'.1.cmp(&'+b+'.1)'
        if finish:
            primary='('+primary+').map(|order:std::cmp::Ordering|order.reverse())'if largest else primary
            return 'if '+equal+'{Ok('+tie+')}else{'+primary+'}'
        # The root is the worst retained candidate; later equal candidates are worse.
        test='is_lt()'
        return 'if '+equal+'{Ok('+a+'.1>'+b+'.1)}else{('+primary+').map(|order:std::cmp::Ordering|order.'+test+')} '
    def operation(name,new_item=None):
        error=emitter.fresh();a,b=(emitter.fresh()for _ in range(2));result=emitter.fresh()
        comparison=compare_entries(a,b)
        closure='|'+a+':&'+entry+','+b+':&'+entry+'|{if '+error+'.is_some(){return false;}let '+result+':Result<bool,String>='+comparison+';match '+result+'{Ok(value)=>value,Err(value)=>{'+error+'=Some(value);false}}}'
        args='&mut '+heap+(','+new_item if new_item is not None else'')+','+closure
        call='native_'+name+'('+args+')'
        if name=='heapreplace':call=emitter.at(call,node)
        return '{let mut '+error+':Option<String>=None;'+call+';if let Some(error)='+error+'{'+emitter.at('Err::<(),String>(error)',node)+';}}'
    def append(current,item):
        if isinstance(item.kind,EmptyType):return 'match '+item.code+'{};'
        before,value=current.capture(Expression(current.coerce(item,element,node),element))
        score=Expression(value.code+'.clone()',element)if key.kind=='none'else emit_values(current,node,site.callback,Expression('('+key.code+').clone()',key.kind),[Expression(value.code+'.clone()',element)],[],score_kind)
        more,score=current.capture(score)
        entry_value='('+score.code+'.clone(),'+ordinal+','+value.code+')'
        top=Expression(heap+'[0].0.clone()',score_kind)
        first,second=(top,score)if largest else(score,top)
        primary=ordering(current,first,second,node)
        improved=current.at('('+primary+').map(|order:std::cmp::Ordering|order.is_lt())',node)
        body=before+more+'if '+heap+'.len()<'+capacity+'{'+current.at(heap+'.try_reserve(1).map_err(|_|"MemoryError: cannot allocate selection heap".to_owned())',node)+';'+heap+'.push('+entry_value+');if '+heap+'.len()=='+capacity+'{'+operation('heapify')+initialized+'=true;}}else if '+improved+'{'+operation('heapreplace',entry_value)+'}'
        body+=ordinal+'='+current.at(ordinal+'.checked_add(1).ok_or_else(||"OverflowError: selection ordinal is too large".to_owned())',node)+';'
        return body
    # Constructing the source remains required when the count is zero; pulling does not.
    if getattr(source.kind,'_native_class_generator',False):loop='if '+capacity+'>0{'+consume(append)+'}'
    else:
        cursor=emitter.model.iterators.construct(emitter,node,source,kind=site.source);before,cursor=emitter.capture(cursor);pulled=emitter.model.iterators.pull(emitter,node,cursor);item=emitter.fresh()
        loop=before+'if '+capacity+'>0{loop{let Some('+item+')=('+pulled.code+')else{break;};'+append(emitter,Expression(item,pulled.kind))+'}}'
    code+=loop+'if !'+heap+'.is_empty()&&!'+initialized+'{'+operation('heapify')+'}'
    a,b,error,result=(emitter.fresh()for _ in range(4));comparison=compare_entries(a,b,finish=True)
    code+='let mut '+error+':Option<String>=None;'+heap+'.sort_by(|'+a+','+b+'|{if '+error+'.is_some(){return std::cmp::Ordering::Equal;}let '+result+':Result<std::cmp::Ordering,String>='+comparison+';match '+result+'{Ok(value)=>value,Err(value)=>{'+error+'=Some(value);std::cmp::Ordering::Equal}}});if let Some(error)='+error+'{'+emitter.at('Err::<(),String>(error)',node)+';}class_list('+heap+'.into_iter().map(|(_,_,value)|value).collect())'
    return code
