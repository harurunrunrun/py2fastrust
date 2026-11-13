"""Exact structural slicing of retained ranges, independent of address sizes."""


def has_range_value(value,heap,active=frozenset()):
    from .native_constraints import RangeValue,Variable
    if value is None:return False
    for part in value.alternatives:
        if isinstance(part,RangeValue):return True
        if isinstance(part,Variable)and part not in active:
            if has_range_value(heap.get(part),heap,active|{part}):return True
    return False


def _bound(emitter,node,value):
    from .native_classes import Expression,domain
    from .native_unions import project,union_kind
    from .native_frame_slices import INTEGRAL
    if value is None:return 'None'
    if union_kind(value.kind):
        return project(value.kind,value.code,lambda kind,code:_bound(emitter,node,Expression('('+code+').clone()',kind)))
    if value.kind=='none':return 'None'
    if domain(value.kind)in INTEGRAL:return 'Some('+emitter.number(value)+')'
    return emitter.at('Err::<Option<NativeInt>,String>("TypeError: slice indices must be integers or None or have an __index__ method".to_owned())',node)


def emit(emitter,node,owner,bounds,wanted):
    from .native_classes import Expression
    setup,owner=emitter.capture(owner)
    names=[emitter.fresh()for _ in bounds]
    setup+='let '+names[2]+':Option<NativeInt>='+_bound(emitter,node,bounds[2])+';'
    zero=names[2]+'.as_ref().is_some_and(|value|value.is_zero())'if emitter.model.integer=='bigint'else names[2]+'==Some(0)'
    setup+='if '+zero+'{'+emitter.at('Err::<(),String>("ValueError: slice step cannot be zero".to_owned())',node)+';}'
    setup+=''.join('let '+names[i]+':Option<NativeInt>='+_bound(emitter,node,bounds[i])+';'for i in(0,1))
    emitter.model.native_range_slices_required=True
    result=Expression(emitter.at('class_range_slice(&'+owner.code+','+','.join(names)+')',node),'range')
    return Expression('{'+setup+emitter.coerce(result,wanted,node)+'}',wanted)


def runtime(model):
    if not getattr(model,'native_range_slices_required',False):return ''
    return BIG if model.integer=='bigint'else FIXED


FIXED=r'''
fn class_range_slice_overflow()->String{"OverflowError: sliced range structural fields do not fit the selected integer mode".to_owned()}
fn class_range_structural_length(source:&ClassRange)->u128{
 if if source.step<0{source.start<=source.stop}else{source.start>=source.stop}{return 0;}
 let distance=if source.step<0{(source.start as u128).wrapping_sub(source.stop as u128)}else{(source.stop as u128).wrapping_sub(source.start as u128)};
 (distance-1)/(source.step.unsigned_abs()as u128)+1
}
fn class_range_slice_bound(value:NativeInt,length:u128,backward:bool)->Option<u128>{
 let upper=if backward{length.checked_sub(1)}else{Some(length)};
 if value<0{
  let distance=value.unsigned_abs()as u128;
  if distance>length{if backward{None}else{Some(0)}}else{Some(length-distance)}
 }else{upper.map(|upper|(value as u128).min(upper))}
}
fn class_range_slice_offset(start:NativeInt,distance:u128,subtract:bool)->Result<NativeInt,String>{
 let initial=start.unsigned_abs()as u128;
 let (negative,magnitude)=if (start<0)==subtract{
  (subtract,initial.checked_add(distance).ok_or_else(class_range_slice_overflow)?)
 }else if initial>=distance{(start<0,initial-distance)}else{(subtract,distance-initial)};
 let maximum=NativeInt::MAX as u128;
 if negative{
  if magnitude==maximum+1{return Ok(NativeInt::MIN);}
  if magnitude<=maximum{return Ok(-(magnitude as NativeInt));}
 }else if magnitude<=maximum{return Ok(magnitude as NativeInt);}
 Err(class_range_slice_overflow())
}
fn class_range_slice_element(source:&ClassRange,index:u128)->Result<NativeInt,String>{
 let distance=index.checked_mul(source.step.unsigned_abs()as u128).ok_or_else(class_range_slice_overflow)?;
 class_range_slice_offset(source.start,distance,source.step<0)
}
fn class_range_slice_endpoint(source:&ClassRange,length:u128,index:Option<u128>)->Result<NativeInt,String>{
 match index{
  None=>source.start.checked_sub(source.step).ok_or_else(class_range_slice_overflow),
  Some(0)=>Ok(source.start),
  Some(index)if index==length=>class_range_slice_element(source,index-1)?.checked_add(source.step).ok_or_else(class_range_slice_overflow),
  Some(index)=>class_range_slice_element(source,index),
 }
}
fn class_range_slice(source:&ClassRange,start:Option<NativeInt>,stop:Option<NativeInt>,step:Option<NativeInt>)->Result<ClassRange,String>{
 let step=step.unwrap_or(1);
 if step==0{return Err("ValueError: slice step cannot be zero".to_owned());}
 let length=class_range_structural_length(source);let backward=step<0;
 let first=start.map(|value|class_range_slice_bound(value,length,backward)).unwrap_or(if backward{length.checked_sub(1)}else{Some(0)});
 let last=stop.map(|value|class_range_slice_bound(value,length,backward)).unwrap_or(if backward{None}else{Some(length)});
 let composed_step=source.step.checked_mul(step).ok_or_else(class_range_slice_overflow)?;
 let first=class_range_slice_endpoint(source,length,first)?;
 let last=class_range_slice_endpoint(source,length,last)?;
 class_range(first,last,composed_step)
}
'''


BIG=r'''
fn class_range_structural_length(source:&ClassRange)->Int{
 if if source.step.is_negative(){source.start<=source.stop}else{source.start>=source.stop}{return Int::from_i128(0);}
 let distance=if source.step.is_negative(){source.start.sub(&source.stop)}else{source.stop.sub(&source.start)};
 let one=Int::from_i128(1);distance.sub(&one).divmod(&source.step.abs()).expect("nonzero range step").0.add(&one)
}
fn class_range_slice_bound(value:Int,length:&Int,backward:bool)->Int{
 let lower=Int::from_i128(if backward{-1}else{0});let upper=if backward{length.sub(&Int::from_i128(1))}else{length.clone()};
 let value=if value.is_negative(){value.add(length)}else{value};
 if value<lower{lower}else if value>upper{upper}else{value}
}
fn class_range_slice(source:&ClassRange,start:Option<Int>,stop:Option<Int>,step:Option<Int>)->Result<ClassRange,String>{
 let step=step.unwrap_or_else(||Int::from_i128(1));
 if step.is_zero(){return Err("ValueError: slice step cannot be zero".to_owned());}
 let length=class_range_structural_length(source);let backward=step.is_negative();
 let first=start.map(|value|class_range_slice_bound(value,&length,backward)).unwrap_or_else(||if backward{length.sub(&Int::from_i128(1))}else{Int::from_i128(0)});
 let last=stop.map(|value|class_range_slice_bound(value,&length,backward)).unwrap_or_else(||if backward{Int::from_i128(-1)}else{length.clone()});
 class_range(source.start.add(&first.mul(&source.step)),source.start.add(&last.mul(&source.step)),source.step.mul(&step))
}
'''
