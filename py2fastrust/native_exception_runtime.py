"""Feature-selected exception payload identity, traceback state, and rendering."""


def error_record_site(tokens,index):
    """Distinguish a record declaration/literal from a bare return/impl type."""
    if index and tokens[index-1].text=='struct':return True
    if index+3>=len(tokens):return False
    # Error data records are nonempty named-field records. Function bodies
    # following owned, reference or mutable-reference return types are not.
    return tokens[index+2].kind=='identifier'and tokens[index+3].text in {':',','}


def runtime(source,model):
    if not model.exceptions.used:return source
    from .rust_pruning import _lex
    tokens,_,pairs=_lex(source);edits=[];declarations=0;constructors=0
    has_context=model.context_managers.used
    for index,token in enumerate(tokens[:-1]):
        if token.text!='NativeErrorData'or tokens[index+1].text!='{':continue
        if not error_record_site(tokens,index):continue
        close=tokens[pairs[index+1]];prefix=''if source[:close.start].rstrip().endswith(',')else','
        declaration=index and tokens[index-1].text=='struct'
        if declaration:
            fields='exception_kind:Option<ClassExceptionKind>,payload:Option<Rc<dyn ClassExceptionPayload>>,origin:Option<Rc<RefCell<Option<NativeError>>>>,cause:Option<Box<NativeError>>,origin_visible:bool'
            if not has_context:fields+=',context:Option<Box<NativeError>>'
            declarations+=1
        else:
            fields='exception_kind:None,payload:None,origin:None,cause:None,origin_visible:true'
            if not has_context:fields+=',context:None'
            constructors+=1
        edits.append((close.start,close.start,prefix+fields))
    assert declarations==1 and constructors>0,(declarations,constructors)
    anchor='if let Err(error)=result {';start=source.rfind(anchor);assert start>=0
    opening=start+len(anchor)-1
    index=next(index for index,token in enumerate(tokens)if token.start==opening)
    edits.append((opening+1,tokens[pairs[index]].start,'class_exception_render_error(&error);std::process::exit(1);'))
    if has_context:
        index=next(index for index,token in enumerate(tokens)if token.text=='class_with_attach_context'and index and tokens[index-1].text=='fn')
        body=next(j for j in range(index+1,len(tokens))if tokens[j].text=='{')
        edits.append((tokens[body].end,tokens[pairs[body]].start,'class_exception_attach_context(error,previous);'))
    for begin,end,text in sorted(edits,reverse=True):source=source[:begin]+text+source[end:]
    # Native direct calls append logical Python frames during unwinding. Keep
    # the actual exception instance's retained traceback synchronized as well.
    source=source.replace('.frames.push(','.class_exception_push_frame(')
    location="(&'static str,&'static str)"if hasattr(model,'module_linker')else"&'static str"
    frame=( 'function.0,line,function.1'if hasattr(model,'module_linker')else'"'+model.filename.replace('\\','\\\\').replace('"','\\"')+'",line,function')
    origin=( 'error.function.0,error.line,error.function.1'if hasattr(model,'module_linker')else'"'+model.filename.replace('\\','\\\\').replace('"','\\"')+'",error.line,error.function')
    helpers=r'''
#[derive(Debug,Clone,Copy,PartialEq,Eq)]
enum ClassExceptionKind{ValueError,TypeError,RuntimeError,StopIteration}
trait ClassExceptionPayload:std::fmt::Debug{
 fn class_kind(&self)->ClassExceptionKind;
 fn class_name(&self)->&'static str;
 fn class_str(&self)->String;
 fn class_repr(&self)->String{unreachable!("exception repr demand was not registered")}
 fn class_message(&self)->String{let text=self.class_str();if text.is_empty(){self.class_name().to_owned()}else{format!("{}: {}",self.class_name(),text)}}
}
fn class_exception_message(error:&NativeError)->String{
 __EXIT_MESSAGE_HOOK__
 match &error.payload{Some(payload)=>payload.class_message(),None=>error.message.clone()}
}
fn class_exception_is_stop(error:&NativeError)->bool{error.exception_kind==Some(ClassExceptionKind::StopIteration)}
fn class_exception_stop_iteration<T>(line:usize,function:__LOCATION__,origin_visible:bool)->ClassResult<T>{
 let mut error=native_error("StopIteration".to_owned(),line,function);
 error.exception_kind=Some(ClassExceptionKind::StopIteration);error.origin_visible=origin_visible;Err(error)
}
fn class_exception_sync(error:&NativeError){
 if let Some(state)=&error.origin{let mut snapshot=error.clone();snapshot.origin=None;*state.borrow_mut()=Some(snapshot);}
}
fn class_exception_current(error:&NativeError)->NativeError{
 if let Some(origin)=&error.origin{
  let snapshot=origin.borrow().clone();
  if let Some(mut snapshot)=snapshot{snapshot.origin=Some(origin.clone());return snapshot;}
 }
 error.clone()
}
impl NativeError{
 fn class_exception_push_frame(&mut self,frame:(usize,__LOCATION__)){self.frames.push(frame);class_exception_sync(self);}
}
fn class_exception_raise(payload:Rc<dyn ClassExceptionPayload>,origin:Rc<RefCell<Option<NativeError>>>,line:usize,function:__LOCATION__)->NativeError{
 let previous={origin.borrow().clone()};
 let mut error=match previous{Some(mut error)=>{error.frames.push((line,function));error},None=>native_error(String::new(),line,function)};
 error.exception_kind=Some(payload.class_kind());error.message=payload.class_message();error.payload=Some(payload);error.origin=Some(origin);class_exception_sync(&error);error
}
fn class_exception_same_origin(left:&NativeError,right:&NativeError)->bool{
 match(&left.origin,&right.origin){(Some(left),Some(right))=>Rc::ptr_eq(left,right),_=>false}
}
fn class_exception_attach_context(error:&mut NativeError,previous:NativeError){
 if class_exception_same_origin(error,&previous){return;}
 let mut current=class_exception_current(&previous);let mut path=Vec::<NativeError>::new();
 loop{
  let next=match &current.context{Some(context)=>class_exception_current(context),None=>break};
  if class_exception_same_origin(error,&next){current.context=None;class_exception_sync(&current);break;}
  path.push(current);current=next;
 }
 while let Some(mut parent)=path.pop(){parent.context=Some(Box::new(current));class_exception_sync(&parent);current=parent;}
 error.context=Some(Box::new(current));class_exception_sync(error);
}
fn class_exception_generator_stop(previous:NativeError,line:usize,function:__LOCATION__)->NativeError{
 let mut error=native_error("RuntimeError: generator raised StopIteration".to_owned(),line,function);
 error.context=Some(Box::new(previous.clone()));error.exception_kind=Some(ClassExceptionKind::RuntimeError);
 error.cause=Some(Box::new(previous));error
}
fn class_exception_render_error(error:&NativeError){
 class_exception_render_inner(error,&mut std::collections::HashSet::new());
}
fn class_exception_render_inner(error:&NativeError,seen:&mut std::collections::HashSet<usize>)->bool{
 let current=class_exception_current(error);let error=&current;
 if let Some(origin)=&error.origin{if !seen.insert(Rc::as_ptr(origin)as usize){return false;}}
 if let Some(cause)=&error.cause{
  if class_exception_render_inner(cause,seen){eprintln!("\nThe above exception was the direct cause of the following exception:\n");}
 }else if let Some(context)=&error.context{
  if class_exception_render_inner(context,seen){eprintln!("\nDuring handling of the above exception, another exception occurred:\n");}
 }
 if error.origin_visible||!error.frames.is_empty(){
  eprintln!("Traceback (most recent call last):");
  for &(line,function)in error.frames.iter().rev(){eprintln!("  File {:?}, line {}, in {}",__FRAME__);}
 }
 if error.origin_visible{eprintln!("  File {:?}, line {}, in {}\n{}",__ORIGIN__,class_exception_message(error));}
 else{eprintln!("{}",class_exception_message(error));}
 true
}
'''
    if model.exceptions.records:
        helpers+=GC_RUNTIME
    exit_hook='if let Some(message)=exit_context_message(error){return message;}'if getattr(model,'native_exit_used',False)else''
    return source+helpers.replace('__LOCATION__',location).replace('__FRAME__',frame).replace('__ORIGIN__',origin).replace('__EXIT_MESSAGE_HOOK__',exit_hook)


GC_RUNTIME=r'''
fn class_exception_trace_edges(error:&NativeError,visit:&mut dyn FnMut(usize)){
 if let Some(origin)=&error.origin{visit(Rc::as_ptr(origin)as usize);}
 if let Some(context)=&error.context{class_exception_trace_edges(context,visit);}
 if let Some(cause)=&error.cause{class_exception_trace_edges(cause,visit);}
}
impl NativeClassGcNode for RefCell<Option<NativeError>>{
 fn trace(&self,visit:&mut dyn FnMut(usize))->bool{
  let Ok(data)=self.try_borrow()else{return false;};
  if let Some(error)=&*data{class_exception_trace_edges(error,visit);}true
 }
 fn available(&self)->bool{self.try_borrow_mut().is_ok()}
 fn clear(&self)->bool{let Ok(mut data)=self.try_borrow_mut()else{return false;};data.take();true}
}
fn class_exception_state_new(scope:&ClassScope)->Rc<RefCell<Option<NativeError>>>{
 let state=Rc::new(RefCell::new(None));
 let tracked:Rc<dyn NativeClassGcNode>=state.clone();
 scope.control.borrow_mut().gc.register(Rc::downgrade(&tracked));state
}
'''
