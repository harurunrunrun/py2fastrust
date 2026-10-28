// Typed compiled-future calls. A waiting call polls its result channel; the
// iterative executor polls each callee on a separate heap-stack entry.
use std::cell::RefCell;
use std::future::Future;
use std::pin::Pin;
use std::rc::Rc;
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};

type ClassResult<T> = Result<T, NativeError>;
type ClassFuture<T> = Pin<Box<dyn Future<Output = ClassResult<T>>>>;
type ClassTask = Pin<Box<dyn Future<Output = ()>>>;
type ClassList<T> = Rc<RefCell<Vec<T>>>;

struct ClassControl { child: Option<ClassTask>, depth: usize, limit: usize }
struct ClassIo { input: StandardInput, output: String }
#[derive(Clone)]
struct ClassScope { control: Rc<RefCell<ClassControl>>, io: Rc<RefCell<ClassIo>> }
impl ClassScope {
    fn new() -> Self {
        Self {control:Rc::new(RefCell::new(ClassControl{child:None,depth:0,limit:1000})),
              io:Rc::new(RefCell::new(ClassIo{input:StandardInput::new(),output:String::new()}))}
    }
}
struct ClassNoop;
impl Wake for ClassNoop { fn wake(self: Arc<Self>) {} }
struct ClassCall<T> {
    scope: ClassScope, future: Option<ClassFuture<T>>,
    result: Rc<RefCell<Option<ClassResult<T>>>>,
    line: usize, caller: &'static str,
}
fn class_call<T: 'static>(scope: ClassScope, future: ClassFuture<T>, line:usize, caller:&'static str) -> ClassCall<T> {
    ClassCall {scope,future:Some(future),result:Rc::new(RefCell::new(None)),line,caller}
}
impl<T: 'static> Future for ClassCall<T> {
    type Output = ClassResult<T>;
    fn poll(self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Self::Output> {
        let this=self.get_mut();
        if let Some(result)=this.result.borrow_mut().take() {
            return Poll::Ready(result.map_err(|mut error|{error.frames.push((this.line,this.caller));error}));
        }
        if let Some(future)=this.future.take() {
            let mut control=this.scope.control.borrow_mut();
            if control.depth>=control.limit {
                return Poll::Ready(Err(NativeError {message:"RecursionError: maximum recursion depth exceeded".into(),
                    line:this.line,function:this.caller,frames:Vec::new()}));
            }
            let result=this.result.clone();
            control.child=Some(Box::pin(async move {let value=future.await;*result.borrow_mut()=Some(value);}));
        }
        Poll::Pending
    }
}
fn class_execute<T: 'static>(scope:ClassScope, future:ClassFuture<T>) -> ClassResult<T> {
    let result=Rc::new(RefCell::new(None));
    let completed=result.clone();
    let root:ClassTask=Box::pin(async move {let value=future.await;*completed.borrow_mut()=Some(value);});
    let mut stack=vec![root];
    let waker=Waker::from(Arc::new(ClassNoop));
    let mut context=Context::from_waker(&waker);
    while let Some(mut task)=stack.pop() {
        scope.control.borrow_mut().depth=stack.len()+1;
        match task.as_mut().poll(&mut context) {
            Poll::Ready(())=>{},
            Poll::Pending=>{
                stack.push(task);
                let child=scope.control.borrow_mut().child.take().expect("compiled call must schedule its callee");
                stack.push(child);
            }
        }
    }
    let value=result.borrow_mut().take().expect("compiled entry must finish");
    value
}

fn class_list<T>(values:Vec<T>) -> ClassList<T> {Rc::new(RefCell::new(values))}
fn class_list_get<T:Clone>(values:&ClassList<T>,index:&NativeInt)->Result<T,String> {
    let values=values.borrow();let index=class_index(index,values.len())?;
    Ok(values[index].clone())
}
fn class_list_set<T>(values:&ClassList<T>,index:&NativeInt,value:T)->Result<(),String> {
    let mut values=values.borrow_mut();
    let index=class_index(index,values.len()).map_err(|_|"IndexError: list assignment index out of range".to_string())?;
    values[index]=value;Ok(())
}
fn class_list_pop<T>(values:&ClassList<T>,index:&NativeInt)->Result<T,String> {
    let mut values=values.borrow_mut();
    if values.is_empty(){return Err("IndexError: pop from empty list".into());}
    let index=class_index(index,values.len()).map_err(|_|"IndexError: pop index out of range".to_string())?;
    Ok(values.remove(index))
}
fn class_list_repeat<T:Clone>(values:&ClassList<T>,count:&NativeInt)->Result<ClassList<T>,String> {
    let count=class_repetition_count(count)?;let values=values.borrow();
    if count==0||values.is_empty(){return Ok(class_list(Vec::new()));}
    let length=values.len().checked_mul(count).ok_or_else(||"MemoryError: list is too large".to_string())?;
    let mut result=Vec::new();result.try_reserve(length).map_err(|_|"MemoryError: cannot allocate list".to_string())?;
    for _ in 0..count {result.extend(values.iter().cloned());}
    Ok(class_list(result))
}
fn class_list_repeat_in_place<T:Clone>(values:&ClassList<T>,count:&NativeInt)->Result<(),String> {
    let count=class_repetition_count(count)?;let mut values=values.borrow_mut();
    if count==0 {values.clear();return Ok(());}
    if count==1||values.is_empty(){return Ok(());}
    let original=values.len();
    let length=original.checked_mul(count).ok_or_else(||"MemoryError: list is too large".to_string())?;
    values.try_reserve(length-original).map_err(|_|"MemoryError: cannot allocate list".to_string())?;
    for _ in 1..count {for index in 0..original {let item=values[index].clone();values.push(item);}}
    Ok(())
}
fn class_list_extend<T:Clone>(values:&ClassList<T>,other:&ClassList<T>) {
    let incoming=other.borrow().clone();values.borrow_mut().extend(incoming);
}
fn class_list_concat<T:Clone>(values:&ClassList<T>,other:&ClassList<T>)->ClassList<T> {
    let mut result=values.borrow().clone();result.extend(other.borrow().iter().cloned());class_list(result)
}
fn class_unpack<T:Clone>(values:&ClassList<T>,count:usize)->Result<Vec<T>,String> {
    let values=values.borrow();
    if values.len()<count{return Err(format!("ValueError: not enough values to unpack (expected {count}, got {})",values.len()));}
    if values.len()>count{return Err(format!("ValueError: too many values to unpack (expected {count})"));}
    Ok(values.clone())
}

#[derive(Clone)]
struct ClassRange {start:NativeInt,stop:NativeInt,step:NativeInt}
fn class_range(start:NativeInt,stop:NativeInt,step:NativeInt)->Result<ClassRange,String> {
    NativeRange::new(start.clone(),stop.clone(),step.clone())?;
    Ok(ClassRange{start,stop,step})
}
impl ClassRange {
    fn iter(&self)->NativeRange {NativeRange::new(self.start.clone(),self.stop.clone(),self.step.clone()).unwrap()}
}

fn class_read(scope:&ClassScope,binary:bool,line:bool,builtin_input:bool)->Result<ClassRead,String> {
    let mut io=scope.io.borrow_mut();
    if builtin_input&&!io.output.is_empty(){native_flush_output(&mut io.output)?;}
    if binary {return io.input.read_binary(None,line).map(ClassRead::Bytes).map_err(StandardInputError::native_message);}
    let mut value=String::new();io.input.read_text_into(&mut value,None,line).map_err(StandardInputError::native_message)?;
    if builtin_input {
        if value.is_empty(){return Err("EOFError: EOF when reading a line".into());}
        if value.ends_with('\n'){value.pop();}
    }
    Ok(ClassRead::Text(value))
}
enum ClassRead {Text(String),Bytes(Vec<u8>)}
fn class_read_text(scope:&ClassScope,line:bool,builtin_input:bool)->Result<String,String> {
    match class_read(scope,false,line,builtin_input)?{ClassRead::Text(value)=>Ok(value),_=>unreachable!()}
}
fn class_read_bytes(scope:&ClassScope,line:bool)->Result<Vec<u8>,String> {
    match class_read(scope,true,line,false)?{ClassRead::Bytes(value)=>Ok(value),_=>unreachable!()}
}
fn class_parse_bytes(value:&[u8])->Result<NativeInt,String> {
    let parsed=if value.iter().all(|byte|byte.is_ascii()&&!matches!(*byte,0..=8|14..=31|127)){native_parse_integer(std::str::from_utf8(value).unwrap())}
        else{Err("ValueError: invalid literal".into())};
    parsed.map_err(|_|format!("ValueError: invalid literal for int() with base 10: {}",text_repr_bytes(value)))
}
fn class_split_text(value:&str)->ClassList<String> {
    class_list(value.split(native_space).filter(|word|!word.is_empty()).map(str::to_owned).collect())
}
fn class_split_bytes(value:&[u8])->ClassList<Vec<u8>> {
    class_list(value.split(|byte|matches!(*byte,9..=13|32)).filter(|word|!word.is_empty()).map(<[u8]>::to_vec).collect())
}
fn class_string_add(mut left:String,right:&str)->Result<String,String> {
    left.try_reserve(right.len()).map_err(|_|"MemoryError: cannot allocate string".to_string())?;
    left.push_str(right);Ok(left)
}
fn class_string_repeat(value:&str,count:&NativeInt)->Result<String,String> {
    let count=class_repetition_count(count)?;
    let length=value.len().checked_mul(count).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"OverflowError: repeated string is too long".to_string())?;
    let mut result=String::new();result.try_reserve(length).map_err(|_|"MemoryError: cannot allocate string".to_string())?;
    for _ in 0..count {result.push_str(value);}Ok(result)
}
fn class_string_get(value:&str,index:&NativeInt)->Result<String,String> {
    let index=class_index(index,value.chars().count()).map_err(|_|"IndexError: string index out of range".to_string())?;
    Ok(value.chars().nth(index).unwrap().to_string())
}
fn class_tuple_text(values:&[String])->String {
    let mut result="(".to_owned();result.push_str(&values.join(", "));
    if values.len()==1{result.push(',');}result.push(')');result
}

fn class_parse_words<T,F:Fn(&T)->Result<NativeInt,String>>(values:&ClassList<T>,count:Option<usize>,parse:F)->Result<Vec<NativeInt>,String> {
    let values=values.borrow();let limit=count.unwrap_or(values.len());let mut result=Vec::new();
    for index in 0..limit {
        let value=values.get(index).ok_or_else(||format!("ValueError: not enough values to unpack (expected {limit}, got {index})"))?;
        result.push(parse(value)?);
    }
    if count.is_some()&&values.len()>limit {parse(&values[limit])?;return Err(format!("ValueError: too many values to unpack (expected {limit})"));}
    Ok(result)
}
fn class_strip_bytes(value:&[u8])->Vec<u8> {
    let start=value.iter().position(|byte|!matches!(*byte,9..=13|32)).unwrap_or(value.len());
    let end=value.iter().rposition(|byte|!matches!(*byte,9..=13|32)).map(|index|index+1).unwrap_or(start);
    value[start..end].to_vec()
}
trait ClassDisplay {
    fn class_str(&self)->String;
    fn class_repr(&self)->String {self.class_str()}
}
impl ClassDisplay for NativeInt {fn class_str(&self)->String{self.to_string()}}
impl ClassDisplay for NativeScalar {fn class_str(&self)->String{self.to_string()}}
impl PartialEq for NativeScalar {fn eq(&self,other:&Self)->bool{self.clone().integer()==other.clone().integer()}}
impl ClassDisplay for bool {fn class_str(&self)->String{if *self{"True"}else{"False"}.to_owned()}}
impl ClassDisplay for () {fn class_str(&self)->String{"None".to_owned()}}
impl ClassDisplay for String {
    fn class_str(&self)->String{self.clone()}
    fn class_repr(&self)->String{text_repr_str(self)}
}
impl ClassDisplay for Vec<u8> {fn class_str(&self)->String{text_repr_bytes(self)}}
impl<T:ClassDisplay> ClassDisplay for ClassList<T> {
    fn class_str(&self)->String {
        let values=self.borrow();let mut result="[".to_owned();
        for(index,value)in values.iter().enumerate(){if index!=0{result.push_str(", ");}result.push_str(&value.class_repr());}
        result.push(']');result
    }
}
