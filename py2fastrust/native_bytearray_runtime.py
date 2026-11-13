"""Checked mutable u8 storage and Python bytearray structural operations."""


def runtime(model):
 if not getattr(model,'native_bytearray_required',False):return ''
 integer=lambda name:name+'.to_i128()'if model.integer=='bigint'else'Some(*'+name+' as i128)'
 return (RUNTIME.replace('BYTEARRAY_NUMBER',integer('value'))
         .replace('BYTEARRAY_INDEX',integer('index'))
         .replace('BYTEARRAY_COUNT',integer('count')))


RUNTIME=r'''
#[derive(Clone)]
struct ClassByteArray(Rc<RefCell<Vec<u8>>>);
impl ClassDisplay for ClassByteArray{
 fn class_str(&self)->String{class_bytearray_repr(&self.0.borrow())}
}
fn class_bytearray_repr(data:&[u8])->String{
 use std::fmt::Write as _;
 let quote=if data.contains(&b'\'')&&!data.contains(&b'"'){b'"'}else{b'\''};
 let mut result=String::from("bytearray(b");result.push(quote as char);
 for &byte in data{match byte{
  b'\\'=>result.push_str("\\\\"),b'\''=>result.push_str("\\'"),
  b'\n'=>result.push_str("\\n"),b'\r'=>result.push_str("\\r"),b'\t'=>result.push_str("\\t"),
  byte if byte==quote=>{result.push('\\');result.push(byte as char);},
  32..=126=>result.push(byte as char),byte=>write!(&mut result,"\\x{byte:02x}").unwrap(),
 }}result.push(quote as char);result.push(')');result
}
fn class_bytearray_pack(value:&NativeInt)->Result<u8,String>{
 let value=BYTEARRAY_NUMBER.ok_or_else(||"ValueError: byte must be in range(0, 256)".to_owned())?;
 u8::try_from(value).map_err(|_|"ValueError: byte must be in range(0, 256)".to_owned())
}
fn class_bytearray_key(index:&NativeInt)->Result<isize,String>{
 BYTEARRAY_INDEX.and_then(|index|isize::try_from(index).ok()).ok_or_else(||"IndexError: cannot fit 'int' into an index-sized integer".to_owned())
}
fn class_bytearray_position(length:usize,index:isize)->Result<usize,String>{
 let position=if index<0{length as i128+index as i128}else{index as i128};
 if position<0||position>=length as i128{Err("IndexError: bytearray index out of range".to_owned())}else{Ok(position as usize)}
}
fn class_bytearray_get(owner:&ClassByteArray,index:isize)->Result<u8,String>{
 let data=owner.0.borrow();let position=class_bytearray_position(data.len(),index)?;Ok(data[position])
}
fn class_bytearray_set(owner:&ClassByteArray,index:isize,value:u8)->Result<(),String>{
 let mut data=owner.0.borrow_mut();let position=class_bytearray_position(data.len(),index)?;data[position]=value;Ok(())
}
fn class_bytearray_append(owner:&ClassByteArray,value:u8)->Result<(),String>{
 let mut data=owner.0.borrow_mut();data.try_reserve(1).map_err(|_|"MemoryError".to_owned())?;data.push(value);Ok(())
}
fn class_bytearray_repeat(owner:&ClassByteArray,count:&NativeInt,inplace:bool)->Result<ClassByteArray,String>{
 let count=BYTEARRAY_COUNT.and_then(|count|isize::try_from(count).ok()).ok_or_else(||"OverflowError: cannot fit 'int' into an index-sized integer".to_owned())?.max(0)as usize;
 let base=owner.0.borrow().len();let size=base.checked_mul(count).filter(|size|*size<=isize::MAX as usize).ok_or_else(||"MemoryError".to_owned())?;
 if inplace{
  let mut data=owner.0.borrow_mut();if count==0{data.clear();}else if base>0{data.try_reserve(size-base).map_err(|_|"MemoryError".to_owned())?;for _ in 1..count{data.extend_from_within(0..base);}}
  Ok(owner.clone())
 }else{
  let mut data=Vec::new();data.try_reserve(size).map_err(|_|"MemoryError".to_owned())?;if base>0{let input=owner.0.borrow();for _ in 0..count{data.extend_from_slice(&input);}}
  Ok(ClassByteArray(Rc::new(RefCell::new(data))))
 }
}
fn class_bytearray_concat(owner:&ClassByteArray,input:&[u8],inplace:bool)->Result<ClassByteArray,String>{
 let result=if inplace{owner.clone()}else{ClassByteArray(Rc::new(RefCell::new(owner.0.borrow().clone())))};
 {let mut data=result.0.borrow_mut();data.try_reserve(input.len()).map_err(|_|"MemoryError".to_owned())?;data.extend_from_slice(input);}Ok(result)
}
fn class_bytearray_slice_assign(owner:&ClassByteArray,start:Option<i128>,stop:Option<i128>,step:Option<i128>,values:Vec<u8>)->Result<(),String>{
 let mut data=owner.0.borrow_mut();let indices=native_slice_indices(data.len(),start,stop,step)?;
 if step.unwrap_or(1)==1{
  let begin=usize::try_from(indices.cursor).expect("bounded forward slice");let end=begin.checked_add(indices.len()).expect("bounded slice endpoint");
  let length=data.len().checked_sub(indices.len()).and_then(|length|length.checked_add(values.len())).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"MemoryError".to_owned())?;
  if length>data.len(){let extra=length-data.len();data.try_reserve(extra).map_err(|_|"MemoryError".to_owned())?;}
  data.splice(begin..end,values);
 }else{
  if indices.len()!=values.len(){return Err(format!("ValueError: attempt to assign bytes of size {} to extended slice of size {}",values.len(),indices.len()));}
  for(index,value)in indices.zip(values){data[index]=value;}
 }
 Ok(())
}
'''
