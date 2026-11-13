"""Ordered builtin-list slice writes over captured original AST targets."""
import ast
from dataclasses import dataclass


@dataclass
class Site:
    owner:object
    bounds:tuple
    source:object=None
    iterator:object=None
    immediate:bool=False


def sites(model):
    if not hasattr(model,'list_slice_sites'):model.list_slice_sites={}
    return model.list_slice_sites


def parents(model):
    if not hasattr(model,'list_slice_parents'):
        model.list_slice_parents={id(child):node for node in model.iter_nodes()for child in ast.iter_child_nodes(node)}
    return model.list_slice_parents


def capture_read(model,plan,node,owner,bounds):
    parent=parents(model).get(id(node))
    if not isinstance(parent,ast.AugAssign)or parent.target is not node:return
    sites(model)[plan.index,id(node),'read']=Site(model.flow_copy(owner),tuple(None if value is None else model.flow_copy(value)for value in bounds))


def _supported(model,owner):
    from .native_classes import domain,shape
    from .native_types import alternatives
    kinds=alternatives(shape(owner))
    return all(domain(kind)in {'list','tuple','tuple_sequence','str','bytes','int','bool','int_bool','float','none'}for kind in kinds)


def analyze(model,plan,node,owner,value,environment,*,bounds=None,captured=False):
    from .native_classes import Cell,shape,domain,ClassUnsupported
    from .native_types import alternatives
    from .native_frame_slices import INTEGRAL,INVALID_BOUNDS
    if not isinstance(node.slice,ast.Slice):return False
    if shape(owner)is None and not model.final:
        from .native_guard_flow import AnalysisPending
        raise AnalysisPending()
    if not _supported(model,owner):return False
    if bounds is None:
        bounds=[]
        for expression in(node.slice.lower,node.slice.upper,node.slice.step):
            bounds.append(None if expression is None else model.expression(plan,expression,environment))
    lists=any(domain(kind)=='list'for kind in alternatives(shape(owner)))
    if lists:
        for bound in bounds:
            if bound is None:continue
            for kind in alternatives(shape(bound)):
                if kind is None and not model.final:continue
                if domain(kind)not in INTEGRAL|{'none'}|INVALID_BOUNDS:
                    raise ClassUnsupported(node.slice,'list slice assignment bound requires an unimplemented custom __index__ callback',types=(('bound',kind),),proof='builtin slice-index conversion')
    source=model.flow_copy(value)
    if not lists:
        sites(model)[plan.index,id(node),'write']=Site(model.flow_copy(owner),tuple(bounds),source)
        if not captured:model.remember(plan,node,model.cell(plan,node,'none',identity='slice_write'))
        return True
    from .native_immediate_generators import GeneratorType
    immediate=isinstance(shape(source),GeneratorType)
    iterator=None if immediate else model.iterators.source(plan,node,source,('slice_assignment',),environment=environment)
    item=model.generators.demand(plan,node,source,environment)if immediate else model.iterators.demand(plan,node,Cell(iterator),environment)
    from .native_union_sequences import branches
    from .native_list_positions import invalidate
    for choice in branches(owner):
        if choice.tag=='list':
            model.contribute(choice.args[0],item,node);invalidate(model,choice)
    sites(model)[plan.index,id(node),'write']=Site(model.flow_copy(owner),tuple(bounds),source,iterator,immediate)
    if not captured:model.remember(plan,node,model.cell(plan,node,'none',identity='slice_write'))
    return True



def check_augmented(model,plan,node,right):
    from .native_classes import ClassUnsupported,domain,shape
    site=sites(model).get((plan.index,id(node.target),'read'))
    if site is None:return
    from .native_types import alternatives
    if not any(domain(kind)=='list'for kind in alternatives(shape(site.owner))):return
    if shape(right)is None and not model.final:
        from .native_guard_flow import AnalysisPending
        raise AnalysisPending()
    if isinstance(node.op,ast.Add)and domain(shape(right))!='list':
        raise ClassUnsupported(node,'in-place addition to a list slice with this RHS needs the general list __iadd__ iterable and length-hint adapter; this path currently supports a proved builtin list RHS',types=(('RHS',shape(right)),),proof='list slice augmented iterable addition')


def captured_store(model,plan,node,value,environment):
    site=sites(model).get((plan.index,id(node),'read'))
    return False if site is None else analyze(model,plan,node,site.owner,value,environment,bounds=site.bounds,captured=True)


def reference(emitter,node):
    if not isinstance(node,ast.Subscript)or not isinstance(node.slice,ast.Slice):return None
    if(emitter.plan.index,id(node),'write')not in sites(emitter.model):return None
    setup,owner=emitter.capture(emitter.expression(node.value));bounds=[]
    for expression in(node.slice.lower,node.slice.upper,node.slice.step):
        if expression is None:bounds.append(None)
        else:
            before,value=emitter.capture(emitter.expression(expression));setup+=before;bounds.append(value)
    return setup,('list_slice',owner,tuple(bounds))


def load(emitter,reference,node,wanted):
    from .native_frame_slices import _owner
    emitter.model.native_frame_slices_required=True
    from .native_classes import Expression
    owner=reference[1]
    return _owner(emitter,node,Expression('('+owner.code+').clone()',owner.kind),reference[2],wanted)



def _reserve_cursor_hint(emitter,node,cursor,values):
    from .native_classes import domain,shape
    from .native_class_iterators import iterator_kind
    from .native_types import alternatives
    from .native_unions import union_kind
    if not iterator_kind(cursor.kind):return ''
    record=cursor.kind.record
    if hasattr(record,'adapter')or record.operation not in {'source','reverse'}:return ''
    kinds=alternatives(shape(record.source))
    if not any(domain(kind)=='range'for kind in kinds):return ''
    emitter.model.native_slice_range_hints=True
    emitter.model.source_hint_reserve=True
    guard=emitter.fresh();hint=emitter.fresh()
    def current(kind,code):
        if domain(kind)!='range':return 'Ok::<usize,String>(8_usize)'
        if record.operation=='reverse':return 'class_slice_reverse_range_hint(&'+code+'.cursor,&'+code+'.first,&'+code+'.step,'+code+'.active)'
        active='true'if emitter.model.integer=='bigint'else code+'.active'
        return 'class_slice_range_hint(&'+code+'.cursor,&'+code+'.stop,&'+code+'.step,'+active+')'
    if union_kind(shape(record.source)):
        arms=['ClassIteratorSource_'+str(record.index)+'::V'+str(index)+'(source)=>'+current(kind,'source')for index,kind in enumerate(kinds)]
        code='match &'+guard+'.source{'+','.join(arms)+'}'
    else:code=current(kinds[0],guard+'.source')
    checked=emitter.at('{let '+guard+'='+cursor.code+'.borrow();'+code+'}',node)
    return 'let '+hint+'='+checked+';'+emitter.at('class_source_hint_reserve(&mut '+values+','+hint+')',node)+';'


def _materialize(emitter,node,value,site,element):
    from .native_classes import Expression
    from .native_class_iterators import iterator_kind
    values=emitter.fresh()
    def append(e,item):
        reserve=e.at(values+'.try_reserve(1).map_err(|_|"MemoryError: cannot allocate slice assignment".to_owned())',node)
        return reserve+';'+values+'.push('+e.coerce(item,element,node)+');'
    code='let mut '+values+'=Vec::<'+emitter.rust_type(element)+'>::new();'
    if site.immediate:
        result=emitter.model.generators.consume(emitter,node,'list',value,[],{},'none',append_item=append)
        return code+result.code+';',values
    # Exact builtin lists are shallow snapshots, including a[:] = a. Do not
    # retain any lease while later target mutation or callbacks can execute.
    if getattr(value.kind,'element',None)is not None:
        from .native_classes import domain
        if domain(value.kind)=='list':
            item=emitter.fresh()
            before,retained=emitter.capture(value)
            code+='{'+before+'let source='+retained.code+'.borrow();'+emitter.at(values+'.try_reserve(source.len()).map_err(|_|"MemoryError: cannot allocate slice assignment".to_owned())',node)+';'
            code+='for '+item+' in source.iter(){'+values+'.push('+emitter.coerce(Expression(item+'.clone()',value.kind.element),element,node)+');}}'
            return code,values
    error=lambda source:'"TypeError: must assign iterable to extended slice".to_owned()'
    cursor=emitter.model.iterators.construct(emitter,node,value,kind=site.iterator,not_iterable=error)
    before,cursor=emitter.capture(cursor);code+=before
    code+=_reserve_cursor_hint(emitter,node,cursor,values)
    pulled=emitter.model.iterators.pull(emitter,node,cursor);item=emitter.fresh()
    code+='loop{let Some('+item+')=('+pulled.code+')else{break;};'+append(emitter,Expression(item,pulled.kind))+'}'
    return code,values


def store(emitter,reference,value,node):
    from .native_classes import Expression,domain
    from .native_unions import project
    from .native_frame_slices import convert_bounds
    from .native_class_builtins import _type_name
    site=sites(emitter.model)[emitter.plan.index,id(node),'write']
    emitter.model.native_frame_slices_required=True
    emitter.model.native_list_slice_assignment_required=True
    def branch(kind,code):
        owner=Expression('('+code+').clone()',kind)
        if domain(kind)!='list':
            error='format!("TypeError: \'{}\' object does not support item assignment",'+_type_name(emitter,owner,node)+')'
            return '{'+emitter.at('Err::<(),String>('+error+')',node)+';}'
        setup,names=convert_bounds(emitter,node,reference[2])
        before,values=_materialize(emitter,node,value,site,kind.element);setup+=before
        setup+=emitter.at('class_list_slice_assign(&'+owner.code+','+','.join(names)+','+values+')',node)+';'
        return '{'+setup+'}'
    return project(reference[1].kind,reference[1].code,branch)+';'


def runtime(model):
    if not getattr(model,'native_list_slice_assignment_required',False):return ''
    return RUNTIME+(_range_hint_runtime(model)if getattr(model,'native_slice_range_hints',False)else'')


def _range_hint_runtime(model):
    if model.integer=='bigint':
        return r'''
fn class_slice_hint_size(value:&Int)->Result<usize,String>{value.to_i128().and_then(|value|usize::try_from(value).ok()).filter(|value|*value<=isize::MAX as usize).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())}
fn class_slice_range_hint(start:&Int,stop:&Int,step:&Int,active:bool)->Result<usize,String>{
 if !active||if step.is_negative(){start<=stop}else{start>=stop}{return Ok(0);}
 let distance=if step.is_negative(){start.sub(stop)}else{stop.sub(start)};
 let one=Int::from_i128(1);let count=distance.sub(&one).divmod(&step.abs())?.0.add(&one);class_slice_hint_size(&count)
}
fn class_slice_reverse_range_hint(cursor:&Int,first:&Int,step:&Int,active:bool)->Result<usize,String>{
 if !active{return Ok(0);}
 let distance=cursor.sub(first).abs();let count=distance.divmod(&step.abs())?.0.add(&Int::from_i128(1));class_slice_hint_size(&count)
}
'''
    return r'''
fn class_slice_hint_size(value:u128)->Result<usize,String>{usize::try_from(value).ok().filter(|value|*value<=isize::MAX as usize).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())}
fn class_slice_range_hint(start:&NativeInt,stop:&NativeInt,step:&NativeInt,active:bool)->Result<usize,String>{
 if !active||if *step<0{start<=stop}else{start>=stop}{return Ok(0);}
 let distance=if *step<0{(*start as u128).wrapping_sub(*stop as u128)}else{(*stop as u128).wrapping_sub(*start as u128)};
 class_slice_hint_size((distance-1)/(step.unsigned_abs()as u128)+1)
}
fn class_slice_reverse_range_hint(cursor:&NativeInt,first:&NativeInt,step:&NativeInt,active:bool)->Result<usize,String>{
 if !active{return Ok(0);}
 let distance=if cursor>=first{(*cursor as u128).wrapping_sub(*first as u128)}else{(*first as u128).wrapping_sub(*cursor as u128)};
 let count=(distance/(step.unsigned_abs()as u128)).checked_add(1).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())?;class_slice_hint_size(count)
}
'''


RUNTIME=r'''
fn class_list_slice_assign<T>(owner:&Rc<RefCell<Vec<T>>>,start:Option<i128>,stop:Option<i128>,step:Option<i128>,values:Vec<T>)->Result<(),String>{
 let mut target=owner.borrow_mut();
 let indices=native_slice_indices(target.len(),start,stop,step)?;
 if step.unwrap_or(1)==1{
  let begin=usize::try_from(indices.cursor).expect("bounded forward slice");
  let end=begin.checked_add(indices.len()).expect("bounded slice endpoint");
  let length=target.len().checked_sub(indices.len()).and_then(|length|length.checked_add(values.len())).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"MemoryError: list is too large".to_owned())?;
  if length>target.len(){let extra=length-target.len();target.try_reserve(extra).map_err(|_|"MemoryError: cannot resize list".to_owned())?;}
  target.splice(begin..end,values);
 }else{
  if indices.len()!=values.len(){return Err(format!("ValueError: attempt to assign sequence of size {} to extended slice of size {}",values.len(),indices.len()));}
  for(index,value)in indices.zip(values){target[index]=value;}
 }
 Ok(())
}
'''
