"""Live deque pull state keeps the owner and Python structural version stamp."""
from .native_types import alternatives

def needs_cursor(model,kind):
    return any(model.deques.element(part)is not None or model.mappings.views.element(part)is not None for part in alternatives(kind))

def cursor_payload(emitter,kind,*,reverse=False):
    if not getattr(kind,'_native_class_deque',False):return None
    return ('ClassDequeReverseCursor<'if reverse else'ClassDequeCursor<')+emitter.rust_type(kind.element)+'>'

def construct(kind,code,*,reverse=False):return ('ClassDequeReverseCursor::new('if reverse else'ClassDequeCursor::new(')+code+')'

def pull(emitter,node,kind,code,wanted):
    from .native_classes import Expression
    value=emitter.fresh()
    converted=emitter.coerce(Expression(value,kind.element),wanted,node)
    return '('+emitter.at(code+'.next()',node)+').map(|'+value+'|'+converted+')'

RUNTIME=r'''
struct ClassDeque<T>{inner:NativeDeque<T>,state:usize}
impl<T> std::ops::Deref for ClassDeque<T>{type Target=NativeDeque<T>;fn deref(&self)->&Self::Target{&self.inner}}
impl<T> std::ops::DerefMut for ClassDeque<T>{fn deref_mut(&mut self)->&mut Self::Target{&mut self.inner}}
impl<T> ClassDeque<T>{
    fn new(maxlen:Option<usize>)->Self{Self::from_deque(NativeDeque::new(maxlen))}
    fn from_deque(inner:NativeDeque<T>)->Self{Self{inner,state:0}}
    fn push_back(&mut self,value:T)->Result<(),String>{self.inner.push_back(value)?;self.state=self.state.wrapping_add(1);Ok(())}
    fn push_front(&mut self,value:T)->Result<(),String>{self.inner.push_front(value)?;self.state=self.state.wrapping_add(1);Ok(())}
    fn pop_back(&mut self)->Option<T>{let item=self.inner.values.pop_back();if item.is_some(){self.state=self.state.wrapping_add(1);}item}
    fn pop_front(&mut self)->Option<T>{let item=self.inner.values.pop_front();if item.is_some(){self.state=self.state.wrapping_add(1);}item}
    fn reverse(&mut self){self.inner.values.make_contiguous().reverse();}
    fn rotate(&mut self,amount:isize){if self.inner.len()>1{self.state=self.state.wrapping_add(1);}self.inner.rotate(amount);}
    fn clear(&mut self){if !self.inner.is_empty(){self.state=self.state.wrapping_add(1);}self.inner.clear();}
}

struct ClassDequeCursor<T>{owner:Rc<RefCell<ClassDeque<T>>>,state:usize,index:usize,remaining:usize}
impl<T:Clone> ClassDequeCursor<T>{
    fn new(owner:Rc<RefCell<ClassDeque<T>>>)->Self{
        let(state,remaining)={let queue=owner.borrow();(queue.state,queue.len())};
        Self{owner,state,index:0,remaining}
    }
    fn next(&mut self)->Result<Option<T>,String>{
        let queue=self.owner.borrow();
        if queue.state!=self.state{self.remaining=0;return Err("RuntimeError: deque mutated during iteration".to_owned());}
        if self.remaining==0{return Ok(None);}
        let value=queue.values[self.index].clone();
        self.index=self.index.checked_add(1).ok_or_else(||"OverflowError: deque iterator index overflow".to_owned())?;
        self.remaining-=1;Ok(Some(value))
    }
}
struct ClassDequeReverseCursor<T>{owner:Option<Rc<RefCell<ClassDeque<T>>>>,state:usize,remaining:usize}
impl<T:Clone> ClassDequeReverseCursor<T>{
    fn new(owner:Rc<RefCell<ClassDeque<T>>>)->Self{
        let(state,remaining)={let queue=owner.borrow();(queue.state,queue.len())};
        Self{owner:Some(owner),state,remaining}
    }
    fn next(&mut self)->Result<Option<T>,String>{
        if self.remaining==0{self.owner=None;return Ok(None);}
        let queue=self.owner.as_ref().unwrap().borrow();
        if queue.state!=self.state{self.remaining=0;return Err("RuntimeError: deque mutated during iteration".to_owned());}
        self.remaining-=1;Ok(Some(queue.values[self.remaining].clone()))
    }
}
'''
