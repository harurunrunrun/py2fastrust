// Caller-owned slot continuations. Python callbacks use the ordinary heap
// frame trampoline; conversions run after the callback's frame has returned.
#[derive(Clone, Debug)]
enum ProtocolSink { Stack, Not, Jump { target:usize, when:bool } }
#[derive(Clone, Debug)]
enum ProtocolAction {
    Invoke(Vec<Value>,KeywordArgs),
    EndBinding,
    Pass,
    Length(bool),
    IndexLength(bool),
    Integer(String),
    StrictBool,
    Cached(CacheReturn),
}
#[derive(Clone, Debug)]
struct ProtocolPlan { function:Value,args:Vec<Value>,kwargs:KeywordArgs }
#[derive(Clone, Debug)]
struct ProtocolState {
    plan:Option<ProtocolPlan>,value:Option<Value>,actions:Vec<ProtocolAction>,
    sink:ProtocolSink,bool_binding_fallback:Option<Value>,
}
impl ProtocolState {
    fn roots(&self,out:&mut Vec<Value>) {
        if let Some(plan)=&self.plan {out.push(plan.function.clone());out.extend(plan.args.iter().cloned());out.extend(plan.kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));}
        out.extend(self.value.iter().cloned());out.extend(self.bool_binding_fallback.iter().cloned());
        for action in &self.actions {match action {
            ProtocolAction::Invoke(args,kwargs)=>{out.extend(args.iter().cloned());out.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));}
            ProtocolAction::Cached(pending)=>{out.push(pending.owner.clone());out.extend(pending.entry.args.iter().cloned());out.extend(pending.entry.kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));}
            _=>{},
        }}
    }
}
enum ProtocolTurn { Continue, Schedule(Frame), Done(Value) }
impl Runtime {
    fn protocol_builtin_target(&self,mut value:Value)->bool {
        let mut visited=std::collections::HashSet::new();
        loop {match value {
            Value::Builtin(name)=>return ["len","bool","int"].contains(&name.as_str()),
            Value::Obj(index)=>{if !visited.insert(index){return false;}match self.heap.get(index).and_then(Option::as_ref) {
                Some(Object::Bound(function,_)|Object::Partial{function,..})=>value=function.clone(),
                Some(Object::Cached(cache))=>value=cache.function.clone(),
                _=>return false,
            }},
            _=>return false,
        }}
    }
    fn start_protocol_call(&mut self,frame:&mut Frame,function:Value,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<bool> {
        if !self.protocol_builtin_target(function.clone()) {return Ok(false);}
        frame.protocol=Some(ProtocolState{plan:Some(ProtocolPlan{function,args,kwargs}),value:None,actions:Vec::new(),sink:ProtocolSink::Stack,bool_binding_fallback:None});
        self.resume_protocol(frame)?;Ok(true)
    }
    fn start_protocol_truth(&mut self,frame:&mut Frame,value:Value,sink:ProtocolSink)->PyResult<bool> {
        let mut state=ProtocolState{plan:None,value:None,actions:Vec::new(),sink,bool_binding_fallback:None};
        if !self.protocol_python_truth(&mut state,value)? {return Ok(false);}
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn protocol_slot(&self,value:&Value,name:&str)->Option<(Value,Value)> {
        let class=self.object_class(value)?;
        let definition=self.slot_override(&class,name,0)?;
        Some((definition,class))
    }
    fn protocol_bind(&mut self,state:&mut ProtocolState,mut descriptor:Value,mut receiver:Value,mut class:Value,mut args:Vec<Value>,kwargs:KeywordArgs,after:ProtocolAction,bool_fallback:bool)->PyResult<()> {
        state.actions.insert(0,after);
        let mut binding_started=false;
        for _ in 0..self.recursion_limit {
            if let Value::Obj(index)=descriptor.clone() {
                match self.object(index)? {
                    Object::Function(_)|Object::Cached(_)=>{args.insert(0,receiver);state.plan=Some(ProtocolPlan{function:descriptor,args,kwargs});return Ok(());}
                    Object::Static(function)=>{state.plan=Some(ProtocolPlan{function,args,kwargs});return Ok(());}
                    Object::ClassMethod(function)=>{args.insert(0,class);state.plan=Some(ProtocolPlan{function,args,kwargs});return Ok(());}
                    Object::Property{get,..}=>{
                        if !binding_started {state.actions.insert(0,ProtocolAction::Invoke(args,kwargs.clone()));state.actions.insert(0,ProtocolAction::EndBinding);if bool_fallback {state.bool_binding_fallback=Some(receiver.clone());}}
                        else {state.actions.insert(0,ProtocolAction::Invoke(args,kwargs.clone()));}
                        state.plan=Some(ProtocolPlan{function:get,args:vec![receiver],kwargs:Vec::new()});return Ok(());
                    }
                    _=>{},
                }
            }
            if let Some(descriptor_class)=self.object_class(&descriptor) {
                if let Some(getter)=self.slot_override(&descriptor_class,"__get__",0) {
                    if !binding_started {state.actions.insert(0,ProtocolAction::Invoke(args,kwargs.clone()));state.actions.insert(0,ProtocolAction::EndBinding);if bool_fallback {state.bool_binding_fallback=Some(receiver.clone());}binding_started=true;}
                    else {state.actions.insert(0,ProtocolAction::Invoke(args,kwargs.clone()));}
                    args=vec![receiver,class];receiver=descriptor;class=descriptor_class;descriptor=getter;continue;
                }
            }
            let bound=self.bind_descriptor(descriptor,Some(receiver),class)?;
            state.plan=Some(ProtocolPlan{function:bound,args,kwargs});return Ok(());
        }
        Err(pyerr("RecursionError","maximum recursion depth exceeded while binding a special method"))
    }
    fn protocol_python_truth(&mut self,state:&mut ProtocolState,value:Value)->PyResult<bool> {
        if let Some((method,class))=self.protocol_slot(&value,"__bool__") {
            self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::StrictBool,true)?;return Ok(true);
        }
        // An earlier native bool slot takes precedence over a later Python
        // length implementation in the MRO.
        if let Some(class)=self.object_class(&value) {if matches!(self.slot_definition(&class,"__bool__",0),Some(SlotDefinition::Native(_))) {return Ok(false);}}
        self.protocol_python_length(state,value,true)
    }
    fn protocol_python_length(&mut self,state:&mut ProtocolState,value:Value,truth:bool)->PyResult<bool> {
        if let Some((method,class))=self.protocol_slot(&value,"__len__") {
            self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Length(truth),false)?;return Ok(true);
        }Ok(false)
    }
    fn protocol_primitive_int(&self,value:&Value)->Option<Int> {
        match value {
            Value::Int(number)=>Some(number.inner().clone()),Value::Bool(value)=>Some(Int::from_i128(if *value{1}else{0})),
            _=>match self.native_payload(value){Some(Value::Int(number))=>Some(number.into_inner()),_=>None},
        }
    }
    fn protocol_length_result(&mut self,value:Value,truth:bool)->PyResult<Value> {
        let length=self.protocol_length(&value)?;
        Ok(if truth {Value::Bool(length!=0)}else{Value::Int(Int::from_i128(length as i128).into())})
    }
    fn protocol_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let Value::Builtin(name)=&plan.function else{return Ok(false)};
        match name.as_str() {
            "len"=>{
                if plan.args.len()!=1||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","len() takes exactly one positional argument"));}
                self.protocol_python_length(state,plan.args[0].clone(),false)
            }
            "bool"=>{
                if plan.args.len()>1||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","bool() takes at most one positional argument"));}
                if let Some(value)=plan.args.first(){self.protocol_python_truth(state,value.clone())}else{Ok(false)}
            }
            "int" if plan.args.len()==1&&plan.kwargs.is_empty()=>{
                let value=plan.args[0].clone();
                if matches!(&value,Value::Int(_)|Value::Bool(_)|Value::Str(_)|Value::Bytes(_)|Value::Float(_)){return Ok(false);}
                for name in ["__int__","__index__"] {
                    if let Some((method,class))=self.protocol_slot(&value,name){self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Integer(name.into()),false)?;return Ok(true);}
                    if let Some(class)=self.object_class(&value){if matches!(self.slot_definition(&class,name,0),Some(SlotDefinition::Native(_))){return Ok(false);}}
                }
                Ok(false)
            }
            _=>Ok(false),
        }
    }
    fn protocol_turn(&mut self,frame:&Frame,state:&mut ProtocolState)->PyResult<ProtocolTurn> {
        if let Some(mut plan)=state.plan.take() {
            if self.protocol_builtin(state,&plan)? {return Ok(ProtocolTurn::Continue);}
            match self.prepare_direct_call(plan.function.clone(),plan.args.clone(),plan.kwargs.clone())? {
                PreparedCall::Frame(child)=>return Ok(ProtocolTurn::Schedule(child)),
                PreparedCall::Value(value)=>{state.value=Some(value);return Ok(ProtocolTurn::Continue);}
                PreparedCall::Fallback=>{},
            }
            if let Value::Obj(index)=plan.function.clone(){match self.object(index)? {
                Object::Bound(function,receiver)=>{plan.args.insert(0,receiver);state.plan=Some(ProtocolPlan{function,args:plan.args,kwargs:plan.kwargs});return Ok(ProtocolTurn::Continue);}
                Object::Partial{function,args:mut stored,keywords,..}=>{
                    let mut incoming=plan.args.into_iter();for value in &mut stored {if matches!(value,Value::Builtin(name)if name=="functools.Placeholder"){*value=incoming.next().ok_or_else(||pyerr("TypeError","missing positional arguments in partial call"))?;}}stored.extend(incoming);
                    let previous=self.keyword_items(Value::Obj(keywords))?;let kwargs=self.keyword_merge(previous,plan.kwargs)?;
                    state.plan=Some(ProtocolPlan{function,args:stored,kwargs});return Ok(ProtocolTurn::Continue);
                }
                Object::Cached(cache)=>{match self.cached_lookup(index,cache,plan.args,plan.kwargs)? {
                    CachedLookup::Hit(value)=>state.value=Some(value),
                    CachedLookup::Miss{function,entry}=>{state.plan=Some(ProtocolPlan{function,args:entry.args.clone(),kwargs:entry.kwargs.clone()});state.actions.insert(0,ProtocolAction::Cached(CacheReturn{owner:Value::Obj(index),entry}));}
                }return Ok(ProtocolTurn::Continue);}
                Object::Instance{..}|Object::BuiltinInstance{..}=>{
                    if let Some((method,class))=self.protocol_slot(&plan.function,"__call__") {
                        // Bind __call__ without host-stack reentry, preserving
                        // arguments until any user descriptor has resolved.
                        let args=std::mem::take(&mut plan.args);let kwargs=std::mem::take(&mut plan.kwargs);
                        self.protocol_bind(state,method,plan.function,class,args,kwargs,ProtocolAction::Pass,false)?;
                        return Ok(ProtocolTurn::Continue);
                    }
                }
                _=>{},
            }}
            state.value=Some(self.call(plan.function,plan.args,plan.kwargs,Some(frame))?);
            return Ok(ProtocolTurn::Continue);
        }
        let value=state.value.take().ok_or_else(||pyerr("RuntimeError","missing protocol result"))?;
        if state.actions.is_empty(){return Ok(ProtocolTurn::Done(value));}
        let action=state.actions.remove(0);
        match action {
            ProtocolAction::Pass=>state.value=Some(value),
            ProtocolAction::EndBinding=>{state.bool_binding_fallback=None;state.value=Some(value);}
            ProtocolAction::Invoke(args,kwargs)=>state.plan=Some(ProtocolPlan{function:value,args,kwargs}),
            ProtocolAction::StrictBool=>{if !matches!(value,Value::Bool(_)){return Err(pyerr("TypeError","__bool__ should return bool"));}state.value=Some(value);}
            ProtocolAction::Length(truth)=>{
                if self.protocol_primitive_int(&value).is_some(){state.value=Some(self.protocol_length_result(value,truth)?);}
                else if let Some((method,class))=self.protocol_slot(&value,"__index__"){self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::IndexLength(truth),false)?;}
                else{return Err(pyerr("TypeError",format!("'{}' object cannot be interpreted as an integer",self.typename(&value))));}
            }
            ProtocolAction::IndexLength(truth)=>{
                if self.protocol_primitive_int(&value).is_none(){return Err(pyerr("TypeError",format!("__index__ returned non-int (type {})",self.typename(&value))));}
                state.value=Some(self.protocol_length_result(value,truth)?);
            }
            ProtocolAction::Integer(method)=>{
                state.value=Some(match value {Value::Int(value)=>Value::Int(value),Value::Bool(value)=>Value::Int(Int::from_i128(if value{1}else{0}).into()),value=>match self.native_payload(&value){Some(Value::Int(number))=>Value::Int(number.into_inner().into()),_=>return Err(pyerr("TypeError",format!("{method} returned non-int (type {})",self.typename(&value))))}});
            }
            ProtocolAction::Cached(pending)=>{let Value::Obj(owner)=pending.owner else{unreachable!()};state.value=Some(self.cached_finish(owner,pending.entry,value)?);}
        }
        Ok(ProtocolTurn::Continue)
    }
    fn resume_protocol(&mut self,frame:&mut Frame)->PyResult<()> {
        loop {
            let mut state=frame.protocol.take().unwrap();let mut roots=Vec::new();state.roots(&mut roots);
            let turn=self.view_rooted(roots,|runtime,_|runtime.protocol_turn(frame,&mut state));
            match turn {
                Ok(ProtocolTurn::Continue)=>frame.protocol=Some(state),
                Ok(ProtocolTurn::Schedule(child))=>{frame.protocol=Some(state);frame.next_call=Some(Box::new(child));return Ok(());}
                Ok(ProtocolTurn::Done(value))=>{match state.sink {ProtocolSink::Stack=>frame.stack.push(value),ProtocolSink::Not=>{let Value::Bool(value)=value else{unreachable!()};frame.stack.push(Value::Bool(!value));},ProtocolSink::Jump{target,when}=>{let Value::Bool(value)=value else{unreachable!()};if value==when{frame.pc=target;}}}return Ok(());}
                Err(error)=>{frame.protocol=Some(state);return Err(error);}
            }
        }
    }
    fn protocol_binding_failure(&mut self,frame:&mut Frame,error:&PyException)->PyResult<bool> {
        if !self.exception_has_native_class(error,"AttributeError"){return Ok(false);}
        let Some(value)=frame.protocol.as_ref().and_then(|state|state.bool_binding_fallback.clone()) else{return Ok(false)};
        let mut old=frame.protocol.take().unwrap();old.bool_binding_fallback=None;old.plan=None;old.value=None;
        if let Some(end)=old.actions.iter().position(|action|matches!(action,ProtocolAction::StrictBool)){old.actions.drain(..=end);}else{old.actions.clear();}
        if !self.protocol_python_length(&mut old,value.clone(),true)? {old.value=Some(Value::Bool(match self.native_payload(&value){Some(payload)=>self.truth(&payload)?,None=>true}));}
        frame.protocol=Some(old);self.resume_protocol(frame)?;Ok(true)
    }
}
