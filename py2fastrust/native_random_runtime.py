"""Native MT19937 recurrence and exact structural random-range operations."""


def runtime(model):
    if not getattr(model,'native_random_required',False):return ''
    from_native='value.clone()'if model.integer=='bigint'else'Int::exact_small(*value as i128)'
    to_native='value'if model.integer=='bigint'else'value.normalized().to_i128().expect("normalized random integer")as NativeInt'
    return r'''
struct ClassRandomMt{words:[u32;624],position:usize}
impl ClassRandomMt{
 fn from_keys(keys:&[u32])->Self{
  let mut result=Self{words:[0;624],position:624};result.words[0]=19650218;
  for index in 1..624{let previous=result.words[index-1];result.words[index]=(previous^(previous>>30)).wrapping_mul(1812433253).wrapping_add(index as u32);}
  let mut position=1_usize;let mut key=0_usize;
  for _ in 0..624.max(keys.len()){
   let previous=result.words[position-1];let mixed=(previous^(previous>>30)).wrapping_mul(1664525);
   result.words[position]=(result.words[position]^mixed).wrapping_add(keys[key]).wrapping_add(key as u32);
   position+=1;key+=1;if position==624{result.words[0]=result.words[623];position=1;}if key==keys.len(){key=0;}
  }
  for _ in 0..623{
   let previous=result.words[position-1];let mixed=(previous^(previous>>30)).wrapping_mul(1566083941);
   result.words[position]=(result.words[position]^mixed).wrapping_sub(position as u32);
   position+=1;if position==624{result.words[0]=result.words[623];position=1;}
  }
  result.words[0]=0x80000000;result
 }
 fn integer(value:&Int)->Self{
  let magnitude=value.magnitude();if magnitude.is_empty(){Self::from_keys(&[0])}else{Self::from_keys(&magnitude)}
 }
 fn entropy()->Self{
  use std::io::Read as _;
  let mut bytes=[0_u8;2496];
  if std::fs::File::open("/dev/urandom").and_then(|mut input|input.read_exact(&mut bytes)).is_ok(){
   let mut keys=[0_u32;624];for(index,chunk)in bytes.chunks_exact(4).enumerate(){keys[index]=u32::from_ne_bytes([chunk[0],chunk[1],chunk[2],chunk[3]]);}return Self::from_keys(&keys);
  }
  let now=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_else(|error|error.duration()).as_nanos();
  let tick=std::time::Instant::now();std::hint::spin_loop();let monotonic=tick.elapsed().as_nanos();
  Self::from_keys(&[now as u32,(now>>32)as u32,std::process::id(),monotonic as u32,(monotonic>>32)as u32])
 }
 fn word(&mut self)->u32{
  if self.position==624{
   for index in 0..624{let combined=(self.words[index]&0x80000000)|(self.words[(index+1)%624]&0x7fffffff);self.words[index]=self.words[(index+397)%624]^(combined>>1)^if combined&1==0{0}else{0x9908b0df};}
   self.position=0;
  }
  let mut value=self.words[self.position];self.position+=1;value^=value>>11;value^=(value<<7)&0x9d2c5680;value^=(value<<15)&0xefc60000;value^=value>>18;value
 }
 fn bits(&mut self,count:u64)->Result<Int,String>{
  if count==0{return Ok(Int::exact_small(0));}
  if count<=32{return Ok(Int::exact_small((self.word()>>(32-count)as u32)as i128));}
  if count<(i128::BITS as u64){
   let words=(count-1)/32+1;let mut value=0_u128;
   for index in 0..words{let mut word=self.word();if index+1==words&&count%32!=0{word>>=32-(count%32)as u32;}value|=(word as u128)<<(index*32)as u32;}
   return Ok(Int::exact_small(value as i128));
  }
  let length=(count-1)/32+1;
  if length>(isize::MAX as u64)/4{return Err("MemoryError".to_owned());}
  let length=usize::try_from(length).map_err(|_|"MemoryError".to_owned())?;let mut digits=Vec::<u32>::new();digits.try_reserve_exact(length).map_err(|_|"MemoryError".to_owned())?;
  for index in 0..length{let mut word=self.word();if index+1==length&&count%32!=0{word>>=32-(count%32)as u32;}digits.push(word);}
  Ok(Int::exact_parts(false,digits))
 }
 fn below(&mut self,upper:&Int)->Result<Int,String>{
  let bits=u64::try_from(upper.bit_length()).map_err(|_|"OverflowError: Python int too large for C uint64_t".to_owned())?;
  loop{let value=self.bits(bits)?;if value.cmp(upper)==std::cmp::Ordering::Less{return Ok(value);}}
 }
 fn random(&mut self)->f64{let high=self.word()>>5;let low=self.word()>>6;((high as f64)*67108864.0+(low as f64))*(1.0/9007199254740992.0)}
}
thread_local!{static CLASS_RANDOM_STREAM:RefCell<Option<ClassRandomMt>>=RefCell::new(None);}
fn class_random_with<T,F>(operation:F)->Result<T,String>where F:FnOnce(&mut ClassRandomMt)->Result<T,String>{
 CLASS_RANDOM_STREAM.with(|stream|{let mut state=stream.borrow_mut();if state.is_none(){*state=Some(ClassRandomMt::entropy());}operation(state.as_mut().expect("initialized MT stream"))})
}
fn class_random_from_native(value:&NativeInt)->Int{__FROM_NATIVE__}
fn class_random_to_native(value:Int)->NativeInt{__TO_NATIVE__}
fn class_random_seed_integer(value:&NativeInt)->Result<(),String>{let state=ClassRandomMt::integer(&class_random_from_native(value));CLASS_RANDOM_STREAM.with(|stream|*stream.borrow_mut()=Some(state));Ok(())}
fn class_random_seed_none()->Result<(),String>{let state=ClassRandomMt::entropy();CLASS_RANDOM_STREAM.with(|stream|*stream.borrow_mut()=Some(state));Ok(())}
fn class_random_bits(count:&NativeInt)->Result<NativeInt,String>{
 let count=class_random_from_native(count);if count.is_negative(){return Err("ValueError: Cannot convert negative int".to_owned());}
 let count=count.to_i128().and_then(|value|u64::try_from(value).ok()).ok_or_else(||"OverflowError: Python int too large for C uint64_t".to_owned())?;
 class_random_with(|state|state.bits(count).map(class_random_to_native))
}
fn class_random_float()->Result<f64,String>{class_random_with(|state|Ok(state.random()))}
fn class_random_range_one(stop:&Int)->Result<NativeInt,String>{
 if stop.is_negative()||stop.is_zero(){return Err("ValueError: empty range for randrange()".to_owned());}
 class_random_with(|state|state.below(stop).map(class_random_to_native))
}
fn class_random_range_step<F>(start:&Int,stop:&Int,step:&Int,message:F)->Result<NativeInt,String>where F:FnOnce(bool)->String{
 let width=stop.exact_add(&start.exact_neg());
 if step.to_i128()==Some(1){
  if width.is_negative()||width.is_zero(){return Err(message(false));}
  return class_random_with(|state|state.below(&width).map(|offset|class_random_to_native(start.exact_add(&offset))));
 }
 if step.is_zero(){return Err("ValueError: zero step for randrange()".to_owned());}
 let adjustment=if step.is_negative(){Int::exact_small(1)}else{Int::exact_small(-1)};
 let number=width.exact_add(step).exact_add(&adjustment).exact_divmod(step)?.0;
 if number.is_zero()||number.is_negative(){return Err(message(true));}
 class_random_with(|state|state.below(&number).map(|offset|class_random_to_native(start.exact_add(&step.exact_mul(&offset)))))
}
fn class_random_randint(lower:&Int,upper:&Int)->Result<NativeInt,String>{
 if upper.cmp(lower)==std::cmp::Ordering::Less{return Err(format!("ValueError: empty range in randint({}, {})",lower,upper));}
 let width=upper.exact_add(&lower.exact_neg()).exact_add(&Int::exact_small(1));
 class_random_with(|state|state.below(&width).map(|offset|class_random_to_native(lower.exact_add(&offset))))
}
fn class_random_shuffle<T>(values:&mut[T])->Result<(),String>{
 class_random_with(|state|{for index in(1..values.len()).rev(){let limit=Int::exact_small((index+1)as i128);let selected=state.below(&limit)?.to_usize().ok_or_else(||"RuntimeError: random index escaped its exact range".to_owned())?;values.swap(index,selected);}Ok(())})
}
'''.replace('__FROM_NATIVE__',from_native).replace('__TO_NATIVE__',to_native)
