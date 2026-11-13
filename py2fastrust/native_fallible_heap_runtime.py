"""Native heaps adapted from CPython 3.14.4 Modules/_heapqmodule.c (PSF license).

Source: https://github.com/python/cpython/blob/v3.14.4/Modules/_heapqmodule.c

Changes use owned typed Rust operands, short RefCell leases, a source-positioned
error factory, and synchronous/asynchronous compiled comparison callbacks.
The accelerator's observable compare/update and cache traversal order is kept.
"""


def kernel(*,asynchronous=False):
 text=RUNTIME
 for before,after in {'@A@':'async 'if asynchronous else'',
                      '@S@':'_async'if asynchronous else'',
                      '@W@':'.await'if asynchronous else'',
                      '@F@':('std::ops::AsyncFnMut'if asynchronous else'FnMut')+'(T,T)->ClassResult<bool>'}.items():text=text.replace(before,after)
 return text


RUNTIME=r'''
@A@fn native_fallible_heap_bubble@S@<T:Clone,F:@F@>(heap:&ClassList<T>,floor:usize,mut cursor:usize,less:&mut F,make_error:&impl Fn(&str)->NativeError)->ClassResult<()>{
 let length=heap.borrow().len();
 let mut selected=heap.borrow().get(cursor).cloned().ok_or_else(||make_error("IndexError: index out of range"))?;
 while cursor>floor{
  let above=(cursor-1)/2;
  let parent={heap.borrow()[above].clone()};
  let moves=less(selected.clone(),parent)@W@?;
  if heap.borrow().len()!=length{return Err(make_error("RuntimeError: list changed size during iteration"));}
  if !moves{break;}
  {let mut data=heap.borrow_mut();selected=data[cursor].clone();data.swap(cursor,above);}
  cursor=above;
 }
 Ok(())
}
@A@fn native_fallible_heap_sink@S@<T:Clone,F:@F@>(heap:&ClassList<T>,mut cursor:usize,less:&mut F,make_error:&impl Fn(&str)->NativeError)->ClassResult<()>{
 let length=heap.borrow().len();let floor=cursor;
 if cursor>=length{return Err(make_error("IndexError: index out of range"));}
 while cursor<length/2{
  let mut child=cursor*2+1;
  if child+1<length{
   let (left,right)={let data=heap.borrow();(data[child].clone(),data[child+1].clone())};
   let left_first=less(left,right)@W@?;
   if !left_first{child+=1;}
   if heap.borrow().len()!=length{return Err(make_error("RuntimeError: list changed size during iteration"));}
  }
  heap.borrow_mut().swap(cursor,child);cursor=child;
 }
 native_fallible_heap_bubble@S@(heap,floor,cursor,less,make_error)@W@
}
@A@fn native_fallible_heappush@S@<T:Clone,F:@F@>(heap:&ClassList<T>,item:T,mut less:F,make_error:&impl Fn(&str)->NativeError)->ClassResult<()>{
 let cursor={let mut data=heap.borrow_mut();data.try_reserve(1).map_err(|_|make_error("MemoryError"))?;data.push(item);data.len()-1};
 native_fallible_heap_bubble@S@(heap,0,cursor,&mut less,make_error)@W@
}
@A@fn native_fallible_heappop@S@<T:Clone,F:@F@>(heap:&ClassList<T>,mut less:F,make_error:&impl Fn(&str)->NativeError)->ClassResult<T>{
 let answer={let mut data=heap.borrow_mut();let last=data.pop().ok_or_else(||make_error("IndexError: index out of range"))?;if data.is_empty(){return Ok(last);}std::mem::replace(&mut data[0],last)};
 native_fallible_heap_sink@S@(heap,0,&mut less,make_error)@W@?;Ok(answer)
}
@A@fn native_fallible_heapreplace@S@<T:Clone,F:@F@>(heap:&ClassList<T>,item:T,mut less:F,make_error:&impl Fn(&str)->NativeError)->ClassResult<T>{
 let answer={let mut data=heap.borrow_mut();let root=data.first_mut().ok_or_else(||make_error("IndexError: index out of range"))?;std::mem::replace(root,item)};
 native_fallible_heap_sink@S@(heap,0,&mut less,make_error)@W@?;Ok(answer)
}
@A@fn native_fallible_heappushpop@S@<T:Clone,F:@F@>(heap:&ClassList<T>,item:T,mut less:F,make_error:&impl Fn(&str)->NativeError)->ClassResult<T>{
 let top={heap.borrow().first().cloned()};let Some(top)=top else{return Ok(item);};
 if !less(top,item.clone())@W@?{return Ok(item);}
 let answer={let mut data=heap.borrow_mut();let root=data.first_mut().ok_or_else(||make_error("IndexError: index out of range"))?;std::mem::replace(root,item)};
 native_fallible_heap_sink@S@(heap,0,&mut less,make_error)@W@?;Ok(answer)
}
@A@fn native_fallible_heapify@S@<T:Clone,F:@F@>(heap:&ClassList<T>,mut less:F,make_error:&impl Fn(&str)->NativeError)->ClassResult<()>{
 let length=heap.borrow().len();let parents=length/2;
 if length<=2500{for root in(0..parents).rev(){native_fallible_heap_sink@S@(heap,root,&mut less,make_error)@W@?;}}
 else{
  let row_start=(1_usize<<(usize::BITS-1-(parents+1).leading_zeros()))-1;
  for root in(parents/2..row_start).rev().chain((row_start..parents).rev()){
   let mut parent=root;
   loop{native_fallible_heap_sink@S@(heap,parent,&mut less,make_error)@W@?;if parent%2==0{break;}parent/=2;}
  }
 }
 Ok(())
}
'''
