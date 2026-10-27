// Caller-owned slot continuations. Python callbacks use the ordinary heap
// frame trampoline; conversions run after the callback's frame has returned.
#[derive(Clone, Debug)]
enum ProtocolSink { Stack, Discard, ForIter{target:usize,finished:bool}, YieldFrom{finished:Option<Value>}, Not, Jump { target:usize, when:bool } }
#[derive(Clone, Debug)]
enum ProtocolAction {
    Invoke(Vec<Value>,KeywordArgs),
    EndBinding(Option<ProtocolBindingRecovery>),
    DiscardResult,
    Pass,
    ContainsResult,
    Return(Value),
    Length(bool),
    IndexLength(bool),
    Integer(String),
    StrictBool,
    Cached(CacheReturn),
    HashResult,
    StringResult(String),
    IteratorResult,
    AttributeDone,
    Operand(Box<ProtocolOperand>),
    Sequence(Box<ProtocolSequence>),
    NeFromEq,
    InvertBoolean,
    Stream(Box<ProtocolStream>),
    Representation(Box<ProtocolRepresentation>),
    Collection(Box<ProtocolCollection>),
    Consumer(Box<ProtocolConsumer>),
    Cell(Box<ProtocolCellComparison>),
    Sort(Box<ProtocolSort>),
    Fold(Box<ProtocolFold>),
    SetWork(Box<ProtocolSetWork>),
}
#[derive(Clone, Debug)]
enum ProtocolBindingRecovery { BoolLength(Value), Hash(Value), Repr(Value), Iter(Value), Contains(Value,Value), Decline }
#[derive(Clone, Debug)]
struct ProtocolAttributeRecovery { receiver:Value, key:Value, name:String, default:Option<Value>, fallback:bool, subscription:bool }

// Native protocols do not consume Python frame depth. Their pending inline
// and boxed action records have an independent, explicit storage bound.
const PROTOCOL_ACTION_STORAGE_LIMIT:usize=64*1024*1024;
#[derive(Clone, Debug, Default)]
struct ProtocolActions {
    queue:std::collections::VecDeque<ProtocolAction>,bytes:usize,
}
impl std::ops::Deref for ProtocolActions {
    type Target=std::collections::VecDeque<ProtocolAction>;
    fn deref(&self)->&Self::Target {&self.queue}
}
impl<'a> IntoIterator for &'a ProtocolActions {
    type Item=&'a ProtocolAction;
    type IntoIter=std::collections::vec_deque::Iter<'a,ProtocolAction>;
    fn into_iter(self)->Self::IntoIter {self.queue.iter()}
}
impl<'a> IntoIterator for &'a mut ProtocolActions {
    type Item=&'a mut ProtocolAction;
    type IntoIter=std::collections::vec_deque::IterMut<'a,ProtocolAction>;
    fn into_iter(self)->Self::IntoIter {self.queue.iter_mut()}
}
impl ProtocolAction {
    fn storage_bytes(&self)->usize {
        std::mem::size_of::<Self>().saturating_add(match self {
            Self::Sequence(_)=>std::mem::size_of::<ProtocolSequence>(),
            Self::Operand(_)=>std::mem::size_of::<ProtocolOperand>(),
            Self::Stream(_)=>std::mem::size_of::<ProtocolStream>(),
            Self::Representation(_)=>std::mem::size_of::<ProtocolRepresentation>(),
            Self::Collection(_)=>std::mem::size_of::<ProtocolCollection>(),
            Self::Consumer(_)=>std::mem::size_of::<ProtocolConsumer>(),
            Self::Cell(_)=>std::mem::size_of::<ProtocolCellComparison>(),
            Self::Sort(_)=>std::mem::size_of::<ProtocolSort>(),
            Self::Fold(_)=>std::mem::size_of::<ProtocolFold>(),
            Self::SetWork(_)=>std::mem::size_of::<ProtocolSetWork>(),
            _=>0,
        })
    }
}
impl ProtocolActions {
    fn new()->Self {Self::default()}
    fn push_front(&mut self,action:ProtocolAction) {self.bytes=self.bytes.saturating_add(action.storage_bytes());self.queue.push_front(action);}
    fn push_back(&mut self,action:ProtocolAction) {self.bytes=self.bytes.saturating_add(action.storage_bytes());self.queue.push_back(action);}
    fn insert(&mut self,index:usize,action:ProtocolAction) {self.bytes=self.bytes.saturating_add(action.storage_bytes());self.queue.insert(index,action);}
    fn pop_front(&mut self)->Option<ProtocolAction> {let action=self.queue.pop_front()?;self.bytes-=action.storage_bytes();Some(action)}
    fn remove(&mut self,index:usize)->Option<ProtocolAction> {let action=self.queue.remove(index)?;self.bytes-=action.storage_bytes();Some(action)}
    fn drain<R:std::ops::RangeBounds<usize>>(&mut self,range:R)->std::vec::IntoIter<ProtocolAction> {
        let removed=self.queue.drain(range).collect::<Vec<_>>();for action in &removed {self.bytes-=action.storage_bytes();}removed.into_iter()
    }
    fn clear(&mut self) {self.queue.clear();self.bytes=0;}
    fn iter_mut(&mut self)->std::collections::vec_deque::IterMut<'_,ProtocolAction> {self.queue.iter_mut()}
    fn check_budget(&self)->PyResult<()> {
        if self.bytes>PROTOCOL_ACTION_STORAGE_LIMIT {Err(pyerr("RecursionError","native protocol continuation storage limit exceeded"))}else{Ok(())}
    }
}
#[derive(Clone, Debug)]
struct ProtocolPlan { function:Value,args:Vec<Value>,kwargs:KeywordArgs }
#[derive(Clone, Debug)]
struct ProtocolState {
    plan:Option<ProtocolPlan>,value:Option<Value>,actions:ProtocolActions,
    sink:ProtocolSink,binding_recovery:Option<ProtocolBindingRecovery>,attribute_recovery:Option<ProtocolAttributeRecovery>,repr_guards:Vec<usize>,
}
impl ProtocolState {
    fn roots(&self,out:&mut Vec<Value>) {
        if let Some(plan)=&self.plan {out.push(plan.function.clone());out.extend(plan.args.iter().cloned());out.extend(plan.kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));}
        if let ProtocolSink::YieldFrom{finished:Some(value)}=&self.sink {out.push(value.clone());}
        out.extend(self.value.iter().cloned());out.extend(self.repr_guards.iter().copied().map(Value::Obj));
        if let Some(recovery)=&self.binding_recovery {match recovery {ProtocolBindingRecovery::BoolLength(value)|ProtocolBindingRecovery::Hash(value)|ProtocolBindingRecovery::Repr(value)|ProtocolBindingRecovery::Iter(value)=>out.push(value.clone()),ProtocolBindingRecovery::Contains(owner,key)=>out.extend([owner.clone(),key.clone()]),_=>{}}}
        if let Some(recovery)=&self.attribute_recovery {out.extend([recovery.receiver.clone(),recovery.key.clone()]);out.extend(recovery.default.iter().cloned());}
        for action in &self.actions {match action {
            ProtocolAction::Invoke(args,kwargs)=>{out.extend(args.iter().cloned());out.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));}
            ProtocolAction::Return(value)=>out.push(value.clone()),
            ProtocolAction::Operand(operation)=>operation.roots(out),
            ProtocolAction::Sequence(sequence)=>sequence.roots(out),
            ProtocolAction::Stream(record)=>record.roots(out),
            ProtocolAction::Representation(record)=>record.roots(out),
            ProtocolAction::Collection(record)=>record.roots(out),
            ProtocolAction::Consumer(record)=>record.roots(out),
            ProtocolAction::Cell(record)=>record.roots(out),
            ProtocolAction::Sort(record)=>record.roots(out),
            ProtocolAction::Fold(record)=>record.roots(out),
            ProtocolAction::SetWork(record)=>record.roots(out),
            ProtocolAction::EndBinding(Some(ProtocolBindingRecovery::BoolLength(value)|ProtocolBindingRecovery::Hash(value)|ProtocolBindingRecovery::Repr(value)|ProtocolBindingRecovery::Iter(value)))=>out.push(value.clone()),
            ProtocolAction::EndBinding(Some(ProtocolBindingRecovery::Contains(owner,key)))=>out.extend([owner.clone(),key.clone()]),
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
            Value::Builtin(name)=>return ["len","bool","int","hash","str","repr","iter","print","next","ascii","format","list","tuple","any","all","sorted","min","max","module:functools:reduce","map","filter","zip","enumerate","reversed","getattr","setattr","delattr"].contains(&name.as_str()) || matches!(native_attribute_parts(&Value::Builtin(name.clone())),Some((_,"cell",method))if cell_comparison_op(method).is_some()) || Self::protocol_collection_target(&name) || name.starts_with("module:itertools:") || name.starts_with("itertools.") || matches!(native_attribute_parts(&Value::Builtin(name.clone())),Some((_,"object","__getattribute__"|"__setattr__"|"__delattr__"|"__str__"))|Some((_,"dict","__getitem__"))) || name=="type_method:object:__getattribute__" || name=="unbound:dict:__getitem__",
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
        frame.protocol=Some(ProtocolState{plan:Some(ProtocolPlan{function,args,kwargs}),value:None,actions:ProtocolActions::new(),sink:ProtocolSink::Stack,binding_recovery:None,attribute_recovery:None,repr_guards:Vec::new()});
        self.resume_protocol(frame)?;Ok(true)
    }
    fn start_protocol_truth(&mut self,frame:&mut Frame,value:Value,sink:ProtocolSink)->PyResult<bool> {
        let mut state=ProtocolState{plan:None,value:None,actions:ProtocolActions::new(),sink,binding_recovery:None,attribute_recovery:None,repr_guards:Vec::new()};
        if !self.protocol_python_truth(&mut state,value)? {return Ok(false);}
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn protocol_slot(&self,value:&Value,name:&str)->Option<(Value,Value)> {
        let class=self.object_class(value)?;
        let definition=self.slot_override(&class,name,0)?;
        Some((definition,class))
    }
    fn protocol_bind(&mut self,state:&mut ProtocolState,descriptor:Value,receiver:Value,class:Value,args:Vec<Value>,kwargs:KeywordArgs,after:ProtocolAction,bool_fallback:bool)->PyResult<()> {
        let recovery=bool_fallback.then(||ProtocolBindingRecovery::BoolLength(receiver.clone()));
        self.protocol_bind_recover(state,descriptor,receiver,class,args,kwargs,after,recovery)
    }
    fn protocol_bind_recover(&mut self,state:&mut ProtocolState,mut descriptor:Value,mut receiver:Value,mut class:Value,mut args:Vec<Value>,kwargs:KeywordArgs,after:ProtocolAction,recovery:Option<ProtocolBindingRecovery>)->PyResult<()> {
        state.actions.push_front(after);
        let mut binding_started=false;
        for _ in 0..self.recursion_limit {
            if let Value::Obj(index)=descriptor.clone() {
                match self.object(index)? {
                    Object::Function(_)|Object::Cached(_)=>{args.insert(0,receiver);state.plan=Some(ProtocolPlan{function:descriptor,args,kwargs});return Ok(());}
                    Object::Static(function)=>{state.plan=Some(ProtocolPlan{function,args,kwargs});return Ok(());}
                    Object::ClassMethod(function)=>{args.insert(0,class);state.plan=Some(ProtocolPlan{function,args,kwargs});return Ok(());}
                    Object::Property{get,..}=>{
                        if !binding_started {state.actions.push_front(ProtocolAction::Invoke(args,kwargs.clone()));let previous=state.binding_recovery.clone();state.actions.push_front(ProtocolAction::EndBinding(previous.clone()));state.binding_recovery=recovery.clone().or(previous);}
                        else {state.actions.push_front(ProtocolAction::Invoke(args,kwargs.clone()));}
                        state.plan=Some(ProtocolPlan{function:get,args:vec![receiver],kwargs:Vec::new()});return Ok(());
                    }
                    _=>{},
                }
            }
            if let Some(descriptor_class)=self.object_class(&descriptor) {
                if let Some(getter)=self.slot_override(&descriptor_class,"__get__",0) {
                    if !binding_started {state.actions.push_front(ProtocolAction::Invoke(args,kwargs.clone()));let previous=state.binding_recovery.clone();state.actions.push_front(ProtocolAction::EndBinding(previous.clone()));state.binding_recovery=recovery.clone().or(previous);binding_started=true;}
                    else {state.actions.push_front(ProtocolAction::Invoke(args,kwargs.clone()));}
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
        if self.protocol_cell_descriptor(state,plan)? {return Ok(true);}
        if matches!(native_attribute_parts(&plan.function),Some((_,"cell",_))) {state.value=Some(self.native_attribute_call(plan.function.clone(),plan.args.clone(),plan.kwargs.clone())?);return Ok(true);}
        if let Some((kind,owner,name))=native_attribute_parts(&plan.function) {
            if kind=="method"||kind=="wrapper" {
                let receiver=plan.args.first().ok_or_else(||pyerr("TypeError",format!("descriptor {owner}.{name} requires an instance")))?;
                self.native_validate_receiver(owner,receiver)?;
            }
        }
        if self.protocol_stream_builtin(state,plan)? {return Ok(true);}
        if self.protocol_set_bulk_builtin(state,plan)? {return Ok(true);}
        if self.protocol_collection_builtin(state,plan)? {return Ok(true);}
        if self.protocol_consumer_builtin(state,plan)? {return Ok(true);}
        if self.protocol_sort_builtin(state,plan)? {return Ok(true);}
        if self.protocol_fold_builtin(state,plan)? {return Ok(true);}
        if self.protocol_native_access(state,plan)? {return Ok(true);}
        if self.protocol_extra_builtin(state,plan)? {return Ok(true);}
        if self.protocol_representation_builtin(state,plan)? {return Ok(true);}
        if name=="getattr" {return self.protocol_getattr_builtin(state,plan);}
        if name=="setattr"||name=="delattr" {return self.protocol_setattr_builtin(state,plan);}
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
    fn protocol_turn(&mut self,frame:Option<&Frame>,state:&mut ProtocolState)->PyResult<ProtocolTurn> {
        if let Some(mut plan)=state.plan.take() {
            if matches!(&plan.function,Value::Builtin(name)if name=="$protocol:generator_next") {return Ok(ProtocolTurn::Schedule(self.protocol_generator_frame(plan.args.remove(0))?));}
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
                    CachedLookup::Miss{function,entry}=>{state.plan=Some(ProtocolPlan{function,args:entry.args.clone(),kwargs:entry.kwargs.clone()});state.actions.push_front(ProtocolAction::Cached(CacheReturn{owner:Value::Obj(index),entry}));}
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
            state.value=Some(self.call(plan.function,plan.args,plan.kwargs,frame)?);
            return Ok(ProtocolTurn::Continue);
        }
        let value=state.value.take().ok_or_else(||pyerr("RuntimeError","missing protocol result"))?;
        if state.actions.is_empty(){return Ok(ProtocolTurn::Done(value));}
        let action=state.actions.pop_front().unwrap();
        match action {
            ProtocolAction::Pass=>state.value=Some(value),
            ProtocolAction::ContainsResult=>state.value=Some(value),
            ProtocolAction::Return(result)=>state.value=Some(result),
            ProtocolAction::EndBinding(previous)=>{state.binding_recovery=previous;state.value=Some(value);}
            ProtocolAction::DiscardResult=>state.value=Some(Value::None),
            ProtocolAction::HashResult=>state.value=Some(self.protocol_hash_result(value)?),
            ProtocolAction::StringResult(method)=>state.value=Some(self.protocol_string_result(value,&method)?),
            ProtocolAction::IteratorResult=>state.value=Some(self.protocol_iterator_result(value)?),
            ProtocolAction::AttributeDone=>{state.attribute_recovery=None;state.value=Some(value);}
            ProtocolAction::Operand(operation)=>self.protocol_operand_result(state,*operation,value)?,
            ProtocolAction::Sequence(sequence)=>self.protocol_sequence_result(state,*sequence,value)?,
            ProtocolAction::Stream(record)=>self.protocol_stream_result(state,*record,value)?,
            ProtocolAction::Representation(record)=>self.protocol_representation_result(state,*record,value)?,
            ProtocolAction::Collection(record)=>self.protocol_collection_result(state,*record,value)?,
            ProtocolAction::Consumer(record)=>self.protocol_consumer_result(state,*record,value)?,
            ProtocolAction::Cell(record)=>self.protocol_cell_result(state,*record,value)?,
            ProtocolAction::Sort(record)=>self.protocol_sort_result(state,*record,value)?,
            ProtocolAction::Fold(record)=>self.protocol_fold_result(state,*record,value)?,
            ProtocolAction::SetWork(record)=>self.protocol_set_work_result(state,*record,value)?,
            ProtocolAction::NeFromEq=>{if matches!(&value,Value::Builtin(name)if name=="NotImplemented"){state.value=Some(value);}else{state.actions.push_front(ProtocolAction::InvertBoolean);if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}}}
            ProtocolAction::InvertBoolean=>{let Value::Bool(value)=value else{unreachable!()};state.value=Some(Value::Bool(!value));}
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
            frame.protocol.as_ref().unwrap().actions.check_budget()?;
            let mut state=frame.protocol.take().unwrap();let mut roots=Vec::new();state.roots(&mut roots);
            let turn=self.view_rooted(roots,|runtime,_|runtime.protocol_turn(Some(frame),&mut state));
            match turn {
                Ok(ProtocolTurn::Continue)=>frame.protocol=Some(state),
                Ok(ProtocolTurn::Schedule(child))=>{frame.protocol=Some(state);frame.protocol.as_ref().unwrap().actions.check_budget()?;frame.next_call=Some(Box::new(child));return Ok(());}
                Ok(ProtocolTurn::Done(value))=>{self.protocol_release_repr_guards(&mut state);match state.sink {ProtocolSink::Stack=>frame.stack.push(value),ProtocolSink::Discard=>{},ProtocolSink::ForIter{target,finished}=>{if finished{Self::pop(frame)?;frame.pc=target;}else{frame.stack.push(value);}},ProtocolSink::YieldFrom{finished}=>{if let Some(finished)=finished{Self::pop(frame)?;frame.stack.push(finished);}else{frame.pc-=1;frame.protocol_exit=Some(FrameExit::Yield(value));}},ProtocolSink::Not=>{let Value::Bool(value)=value else{unreachable!()};frame.stack.push(Value::Bool(!value));},ProtocolSink::Jump{target,when}=>{let Value::Bool(value)=value else{unreachable!()};if value==when{frame.pc=target;}}}return Ok(());}
                Err(error)=>{frame.protocol=Some(state);return Err(error);}
            }
        }
    }
    fn protocol_binding_failure(&mut self,frame:&mut Frame,error:&PyException)->PyResult<bool> {
        let Some(mut state)=frame.protocol.take() else{return Ok(false)};
        let recovered=(||{
            if self.protocol_consumer_failure(&mut state,error)?{self.protocol_sync_repr_guards(&mut state);return Ok(true);}
            if self.protocol_stream_failure(&mut state,error)? {self.protocol_sync_repr_guards(&mut state);return Ok(true);}
            if !self.exception_has_native_class(error,"AttributeError"){return Ok(false);}
            if let Some(recovery)=state.binding_recovery.take() {
                state.plan=None;state.value=None;
                let end=state.actions.iter().position(|action|match (&recovery,action) {
                    (ProtocolBindingRecovery::BoolLength(_),ProtocolAction::StrictBool)|(ProtocolBindingRecovery::Hash(_),ProtocolAction::HashResult)|(ProtocolBindingRecovery::Repr(_),ProtocolAction::StringResult(_))|(ProtocolBindingRecovery::Iter(_),ProtocolAction::IteratorResult)=>true,
                    (ProtocolBindingRecovery::Decline,ProtocolAction::Operand(_))=>true,
                    (ProtocolBindingRecovery::Contains(..),ProtocolAction::ContainsResult)=>true,
                    _=>false,
                }).unwrap_or(state.actions.len());
                let keep=matches!(recovery,ProtocolBindingRecovery::Decline);
                let discard=if keep {end}else{(end+1).min(state.actions.len())};
                self.protocol_discard_actions(&mut state,discard);
                match recovery {
                    ProtocolBindingRecovery::BoolLength(value)=>{if !self.protocol_python_length(&mut state,value.clone(),true)?{state.value=Some(Value::Bool(match self.native_payload(&value){Some(payload)=>self.truth(&payload)?,None=>true}));}return Ok(true);}
                    ProtocolBindingRecovery::Decline=>{state.value=Some(Value::Builtin("NotImplemented".into()));return Ok(true);}
                    recovery=>return self.protocol_recover_builtin_binding(&mut state,recovery),
                }
            }
            self.protocol_attribute_failure(&mut state)
        })();
        frame.protocol=Some(state);
        recovered
    }
}
