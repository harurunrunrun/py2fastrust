// Streaming built-in calls keep their suspended work in the initiating frame.
#[derive(Clone,Debug)]
enum ProtocolPrintPhase { Validate, Piece, WriteLookup(Value), Text(Value), Wrote, FlushLookup, Flushed }
#[derive(Clone,Debug)]
struct ProtocolPrintData { args:Vec<Value>,sep:Value,end:Value,file:Option<Value>,flush:bool,cursor:usize }
#[derive(Clone,Debug)]
enum ProtocolStream {
    Print{data:ProtocolPrintData,phase:ProtocolPrintPhase},
    NextBoundary{iterator:Value,default:Option<Value>,stop_to_sink:bool},
    NextStart{iterator:Value},
    Collect{owner:Value,iters:Vec<Value>,function:Option<Value>,args:Vec<Value>,position:usize,end:Value,strict:bool},
    StrictProbe{owner:Value,iters:Vec<Value>,function:Option<Value>,position:usize},
    Constructor{data:ProtocolConstructor,phase:u8},
    ReversedLength(Value),
    ToolConstructor{data:ProtocolToolConstructor,phase:u8},
    FilterInput{owner:Value,predicate:Value,inner:Value,end:Value},
    FilterPredicate{owner:Value,value:Value,predicate:Value,inner:Value,end:Value},
    FilterTruth{owner:Value,value:Value,predicate:Value,inner:Value,end:Value},
    CallableValue{owner:Value,sentinel:Value},
    CallableEqual{owner:Value,value:Value},
    CallableTruth{owner:Value,value:Value},
    Enumerate{owner:Value,end:Value},
    SequenceItem{owner:Value,object:Value,position:isize},
    Tool{owner:Value,phase:ProtocolToolPhase,fetch:bool},
}
impl ProtocolStream {
    fn roots(&self,out:&mut Vec<Value>) {
        match self {
            Self::Constructor{data,..}=>{out.extend(data.inputs.iter().cloned());out.extend(data.iters.iter().cloned());out.extend([data.function.clone(),data.start.clone()]);},
            Self::ReversedLength(value)=>out.push(value.clone()),
            Self::ToolConstructor{data,..}=>data.roots(out),
            Self::StrictProbe{owner,iters,function,..}=>{out.push(owner.clone());out.extend(iters.iter().cloned());out.extend(function.iter().cloned());},
            Self::Print{data,phase}=>{out.extend(data.args.iter().cloned());out.extend([data.sep.clone(),data.end.clone()]);out.extend(data.file.iter().cloned());if let ProtocolPrintPhase::WriteLookup(value)|ProtocolPrintPhase::Text(value)=phase{out.push(value.clone());}},
            Self::NextBoundary{iterator,default,..}=>{out.push(iterator.clone());out.extend(default.iter().cloned());},
            Self::NextStart{iterator}=>out.push(iterator.clone()),
            Self::Collect{owner,iters,function,args,end,..}=>{out.push(owner.clone());out.extend(iters.iter().cloned());out.extend(function.iter().cloned());out.extend(args.iter().cloned());out.push(end.clone());},
            Self::FilterInput{owner,predicate,inner,end}=>out.extend([owner.clone(),predicate.clone(),inner.clone(),end.clone()]),
            Self::FilterPredicate{owner,value,predicate,inner,end}|Self::FilterTruth{owner,value,predicate,inner,end}=>out.extend([owner.clone(),value.clone(),predicate.clone(),inner.clone(),end.clone()]),
            Self::CallableValue{owner,sentinel}=>out.extend([owner.clone(),sentinel.clone()]),
            Self::CallableEqual{owner,value}|Self::CallableTruth{owner,value}=>out.extend([owner.clone(),value.clone()]),
            Self::Enumerate{owner,end}=>out.extend([owner.clone(),end.clone()]),
            Self::SequenceItem{owner,object,..}=>out.extend([owner.clone(),object.clone()]),
            Self::Tool{owner,phase,..}=>{out.push(owner.clone());phase.roots(out);},
        }
    }
}
impl Runtime {
    fn protocol_stream_queue(&mut self,state:&mut ProtocolState,record:ProtocolStream,value:Value) {
        state.actions.push_front(ProtocolAction::Stream(Box::new(record)));state.value=Some(value);
    }
    fn protocol_stream_plan(&mut self,state:&mut ProtocolState,function:Value,args:Vec<Value>) {
        state.plan=Some(ProtocolPlan{function,args,kwargs:Vec::new()});
    }
    fn protocol_stream_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool>{
        let Value::Builtin(name)=&plan.function else{return Ok(false)};
        // Public itertools constructors are native class objects. Preserve that
        // identity while routing their work through the same queued constructor.
        let normalized=if let Some(member)=name.strip_prefix("itertools.") {
            Some((format!("module:itertools:{member}"),plan.args.clone()))
        }else if let Some((_,owner,"__next__"))=native_attribute_parts(&plan.function).filter(|(_,owner,_)|owner.starts_with("itertools.")) {
            let _=owner;Some(("method:__next__".into(),plan.args.clone()))
        }else if let Some((kind,owner,member))=native_attribute_parts(&plan.function).filter(|(_,owner,_)|owner.starts_with("itertools.")) {
            if plan.args.first().is_some_and(|class|matches!(class,Value::Builtin(name)if name==owner)) {
                if kind=="new" && member=="__new__" {Some((format!("module:itertools:{}",owner.strip_prefix("itertools.").unwrap()),plan.args[1..].to_vec()))}
                else if kind=="class" && owner=="itertools.chain" && member=="from_iterable" {Some(("module:itertools:chain.from_iterable".into(),plan.args[1..].to_vec()))}
                else{None}
            }else{None}
        }else{None};
        if let Some((function,args))=normalized {
            state.plan=Some(ProtocolPlan{function:Value::Builtin(function),args,kwargs:plan.kwargs.clone()});return Ok(true);
        }
        if name=="method:send"&&plan.args.len()==2&&matches!(plan.args[1],Value::None)&&plan.kwargs.is_empty() {
            let generator=plan.args[0].clone();if self.protocol_generator_next(state,generator.clone())?{return Ok(true);}
        }
        if self.protocol_stream_constructor(state,plan)? {return Ok(true);}
        if self.protocol_stream_tools_constructor(state,plan)? {return Ok(true);}
        if name=="method:__next__" {
            if plan.args.len()!=1||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","__next__() takes no arguments"));}
            let iterator=plan.args[0].clone();let payload=self.native_payload(&iterator).unwrap_or_else(||iterator.clone());
            state.actions.push_front(ProtocolAction::Stream(Box::new(ProtocolStream::NextBoundary{iterator,default:None,stop_to_sink:false})));
            self.protocol_stream_inner_next(state,payload);return Ok(true);
        }
        match name.as_str() {
            "print"=>{
                const PARAMETERS:[&str;4]=["sep","end","file","flush"];
                for (name,_) in &plan.kwargs {if !PARAMETERS.contains(&name.as_str()){self.execution_unknown_keyword("print",name,&PARAMETERS)?;}}
                let get=|name:&str|plan.kwargs.iter().find(|(key,_)|key==name).map(|(_,value)|value.clone());
                let sep=get("sep").filter(|value|!matches!(value,Value::None)).unwrap_or_else(||Value::Str(" ".into()));
                let end=get("end").filter(|value|!matches!(value,Value::None)).unwrap_or_else(||Value::Str("\n".into()));
                let file=get("file").filter(|value|!matches!(value,Value::None));
                let flush=get("flush").unwrap_or(Value::Bool(false));
                let data=ProtocolPrintData{args:plan.args.clone(),sep,end,file,flush:false,cursor:0};
                self.protocol_stream_queue(state,ProtocolStream::Print{data,phase:ProtocolPrintPhase::Validate},Value::None);
                if !self.protocol_python_truth(state,flush.clone())? {state.value=Some(Value::Bool(self.truth(&flush)?));}
                Ok(true)
            },
            "next"=>{
                if !(1..=2).contains(&plan.args.len())||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","next expected one or two positional arguments"));}
                self.protocol_next_into(state,plan.args[0].clone(),plan.args.get(1).cloned(),false)
            },
            _=>Ok(false),
        }
    }
    fn protocol_next_into(&mut self,state:&mut ProtocolState,iterator:Value,default:Option<Value>,stop_to_sink:bool)->PyResult<bool>{
        // The boundary belongs to this Python next()/for operation, while
        // native adapters queue inner starts without an extra catch boundary.
        state.actions.push_front(ProtocolAction::Stream(Box::new(ProtocolStream::NextBoundary{iterator:iterator.clone(),default,stop_to_sink})));
        self.protocol_stream_inner_next(state,iterator);
        Ok(true)
    }
    fn protocol_stream_inner_next(&mut self,state:&mut ProtocolState,iterator:Value) {
        self.protocol_stream_queue(state,ProtocolStream::NextStart{iterator},Value::None);
    }
    fn protocol_stream_default_stdout(&mut self)->PyResult<Value> {
        let sys=self.import_module("sys")?;
        let Value::Obj(index)=sys else{unreachable!()};
        let Object::Module{attrs,..}=self.object(index)? else{unreachable!()};
        self.global_name_get(attrs,"stdout")?.ok_or_else(||pyerr("RuntimeError","lost sys.stdout"))
    }
    fn protocol_print_result(&mut self,state:&mut ProtocolState,mut data:ProtocolPrintData,phase:ProtocolPrintPhase,value:Value)->PyResult<()> {
        match phase {
            ProtocolPrintPhase::Validate=>{
                let Value::Bool(flush)=value else{return Err(pyerr("RuntimeError","missing print flush truth"));};data.flush=flush;
                if data.file.is_none(){data.file=Some(self.protocol_stream_default_stdout()?);}
                if matches!(data.file,Some(Value::None)){state.value=Some(Value::None);return Ok(());}
                for (name,value) in [("sep",&data.sep),("end",&data.end)] {
                    if !matches!(self.native_payload(value).unwrap_or_else(||value.clone()),Value::Str(_)){return Err(pyerr("TypeError",format!("{name} must be None or a string, not {}",self.typename(value))));}
                }
                self.protocol_stream_queue(state,ProtocolStream::Print{data,phase:ProtocolPrintPhase::Piece},Value::None);
            },
            ProtocolPrintPhase::Piece=>{
                let count=data.args.len().checked_mul(2).ok_or_else(||pyerr("OverflowError","too many print arguments"))?.max(1);
                if data.cursor>=count {
                    if data.flush {
                        let file=data.file.as_ref().unwrap().clone();
                        self.protocol_stream_queue(state,ProtocolStream::Print{data,phase:ProtocolPrintPhase::FlushLookup},Value::None);
                        self.protocol_stream_plan(state,Value::Builtin("getattr".into()),vec![file,Value::Str("flush".into())]);
                    }else{state.value=Some(Value::None);}
                    return Ok(());
                }
                let piece=if data.cursor==count-1{data.end.clone()}else if data.cursor%2==0{data.args[data.cursor/2].clone()}else{data.sep.clone()};
                let file=data.file.as_ref().unwrap().clone();
                self.protocol_stream_queue(state,ProtocolStream::Print{data,phase:ProtocolPrintPhase::WriteLookup(piece)},Value::None);
                self.protocol_stream_plan(state,Value::Builtin("getattr".into()),vec![file,Value::Str("write".into())]);
            },
            ProtocolPrintPhase::WriteLookup(piece)=>{
                self.protocol_stream_queue(state,ProtocolStream::Print{data,phase:ProtocolPrintPhase::Text(value)},Value::None);
                self.protocol_stream_plan(state,Value::Builtin("str".into()),vec![piece]);
            },
            ProtocolPrintPhase::Text(write)=>{
                self.protocol_stream_queue(state,ProtocolStream::Print{data,phase:ProtocolPrintPhase::Wrote},Value::None);
                self.protocol_stream_plan(state,write,vec![value]);
            },
            ProtocolPrintPhase::Wrote=>{data.cursor+=1;self.protocol_stream_queue(state,ProtocolStream::Print{data,phase:ProtocolPrintPhase::Piece},Value::None);},
            ProtocolPrintPhase::FlushLookup=>{
                self.protocol_stream_queue(state,ProtocolStream::Print{data,phase:ProtocolPrintPhase::Flushed},Value::None);
                self.protocol_stream_plan(state,value,Vec::new());
            },
            ProtocolPrintPhase::Flushed=>state.value=Some(Value::None),
        }
        Ok(())
    }
    fn protocol_stream_next_start(&mut self,state:&mut ProtocolState,iterator:Value)->PyResult<()> {
        if let Some((method,class))=self.protocol_slot(&iterator,"__next__") {
            self.protocol_bind(state,method,iterator,class,Vec::new(),Vec::new(),ProtocolAction::Pass,false)?;return Ok(());
        }
        if self.protocol_generator_next(state,iterator.clone())? {return Ok(());}
        let payload=self.native_payload(&iterator).unwrap_or_else(||iterator.clone());
        if self.protocol_stream_tool_start(state,iterator.clone(),payload.clone())? {return Ok(());}
        let special=matches!(&payload,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Iterator(IteratorState::Map(..)|IteratorState::Zip(..)|IteratorState::MapStrict(..)|IteratorState::ZipStrict(..)|IteratorState::Filter(..)|IteratorState::Callable(..)|IteratorState::Enumerate(..)|IteratorState::Reversed(..)))));
        if special {
            let Value::Obj(index)=payload else{unreachable!()};
            match self.object(index)? {
                Object::Iterator(IteratorState::Map(function,iters))|Object::Iterator(IteratorState::MapStrict(function,iters))=>{
                    let strict=matches!(self.heap.get(index).and_then(Option::as_ref),Some(Object::Iterator(IteratorState::MapStrict(..))));
                    let record=ProtocolStream::Collect{owner:iterator,iters,function:Some(function),args:Vec::new(),position:0,end:Value::None,strict};
                    self.protocol_stream_queue(state,record,Value::None);
                },
                Object::Iterator(IteratorState::Zip(iters))|Object::Iterator(IteratorState::ZipStrict(iters))=>{
                    let strict=matches!(self.heap.get(index).and_then(Option::as_ref),Some(Object::Iterator(IteratorState::ZipStrict(..))));
                    let record=ProtocolStream::Collect{owner:iterator,iters,function:None,args:Vec::new(),position:0,end:Value::None,strict};
                    self.protocol_stream_queue(state,record,Value::None);
                },
                Object::Iterator(IteratorState::Filter(predicate,inner))=>{
                    self.protocol_stream_queue(state,ProtocolStream::FilterInput{owner:iterator,predicate,inner:inner.clone(),end:Value::None},Value::None);
                    self.protocol_stream_inner_next(state,inner);
                },
                Object::Iterator(IteratorState::Callable(function,sentinel))=>{
                    if matches!(function,Value::None){return Err(self.iterator_stop(&iterator)?);}
                    self.protocol_stream_queue(state,ProtocolStream::CallableValue{owner:iterator,sentinel},Value::None);
                    self.protocol_stream_plan(state,function,Vec::new());
                },
                Object::Iterator(IteratorState::Enumerate(inner,_))=>{
                    self.protocol_stream_queue(state,ProtocolStream::Enumerate{owner:iterator,end:Value::None},Value::None);
                    self.protocol_stream_inner_next(state,inner);
                },
                Object::Iterator(IteratorState::Reversed(object,position))=>{
                    if position == -1 {return Err(self.iterator_stop(&iterator)?);}
                    let key=if position<=-2 {position.checked_neg().and_then(|number|number.checked_sub(2))}else{Some(position)}.ok_or_else(||pyerr("OverflowError","sequence iterator index overflow"))?;
                    self.protocol_stream_queue(state,ProtocolStream::SequenceItem{owner:iterator,object:object.clone(),position},Value::None);
                    let key=Value::Int(Int::from_i128(key as i128).into());
                    if let Some((method,class))=self.protocol_slot(&object,"__getitem__") {self.protocol_bind(state,method,object,class,vec![key],Vec::new(),ProtocolAction::Pass,false)?;}
                    else if !self.protocol_dict_getitem(state,object.clone(),key.clone())? {state.value=Some(self.getitem(object,key)?);}
                },
                _=>unreachable!(),
            }
            return Ok(());
        }
        state.value=Some(self.iterator_next(payload)?);
        Ok(())
    }
    fn protocol_stream_close_callable(&mut self,owner:&Value) {
        let owner=self.native_payload(owner).unwrap_or_else(||owner.clone());
        if let Value::Obj(index)=owner {self.heap[index]=Some(Object::Iterator(IteratorState::Callable(Value::None,Value::None)));}
    }
    fn protocol_stream_collect(&mut self,state:&mut ProtocolState,owner:Value,iters:Vec<Value>,function:Option<Value>,mut args:Vec<Value>,position:usize,value:Value,strict:bool)->PyResult<()> {
        // position zero is the start marker; subsequent positions identify the
        // next source after the just-returned item has been appended.
        if position>0{args.push(value);}
        if position<iters.len() {
            let inner=iters[position].clone();
            self.protocol_stream_queue(state,ProtocolStream::Collect{owner,iters,function,args,position:position+1,end:Value::None,strict},Value::None);
            self.protocol_stream_inner_next(state,inner);
        }else if let Some(function)=function {self.protocol_stream_plan(state,function,args);}
        else if args.is_empty(){return Err(self.iterator_stop(&owner)?);}
        else{state.value=Some(self.obj_value(Object::Tuple(args)));}
        Ok(())
    }
    fn protocol_stream_filter_again(&mut self,state:&mut ProtocolState,owner:Value,predicate:Value,inner:Value,end:Value) {
        self.protocol_stream_queue(state,ProtocolStream::FilterInput{owner,predicate,inner:inner.clone(),end},Value::None);
        self.protocol_stream_inner_next(state,inner);
    }
    fn protocol_stream_result(&mut self,state:&mut ProtocolState,record:ProtocolStream,value:Value)->PyResult<()>{
        match record {
            ProtocolStream::Print{data,phase}=>self.protocol_print_result(state,data,phase,value)?,
            ProtocolStream::Tool{owner,phase,..}=>self.protocol_stream_tool_result(state,owner,phase,Some(value),None)?,
            ProtocolStream::NextBoundary{..}=>state.value=Some(value),
            ProtocolStream::NextStart{iterator}=>self.protocol_stream_next_start(state,iterator)?,
            ProtocolStream::Collect{owner,iters,function,args,position,strict,..}=>self.protocol_stream_collect(state,owner,iters,function,args,position,value,strict)?,
            ProtocolStream::StrictProbe{function,position,..}=>return Err(Self::protocol_strict_error(function.is_some(),position,"longer")),
            ProtocolStream::Constructor{data,phase}=>self.protocol_stream_constructor_result(state,data,phase,value)?,
            ProtocolStream::ToolConstructor{data,phase}=>self.protocol_stream_tools_constructor_result(state,data,phase,Some(value),None)?,
            ProtocolStream::ReversedLength(object)=>{let length=self.as_int(&value)?.to_usize().filter(|size|*size<=isize::MAX as usize).ok_or_else(||pyerr("OverflowError","sequence is too large to reverse"))?;state.value=Some(self.obj_value(Object::Iterator(IteratorState::Reversed(object,length as isize-1))));},
            ProtocolStream::FilterInput{owner,predicate,inner,end}=>{
                if matches!(predicate,Value::None) {
                    self.protocol_stream_queue(state,ProtocolStream::FilterTruth{owner,value:value.clone(),predicate,inner,end},Value::None);
                    if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}
                }else{
                    self.protocol_stream_queue(state,ProtocolStream::FilterPredicate{owner,value:value.clone(),predicate:predicate.clone(),inner,end},Value::None);
                    self.protocol_stream_plan(state,predicate,vec![value]);
                }
            },
            ProtocolStream::FilterPredicate{owner,value:original,predicate,inner,end}=>{
                self.protocol_stream_queue(state,ProtocolStream::FilterTruth{owner,value:original,predicate,inner,end},Value::None);
                if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}
            },
            ProtocolStream::FilterTruth{owner,value:original,predicate,inner,end}=>{
                let Value::Bool(keep)=value else{return Err(pyerr("RuntimeError","missing filter truth"));};
                if keep{state.value=Some(original);}else{self.protocol_stream_filter_again(state,owner,predicate,inner,end);}
            },
            ProtocolStream::CallableValue{owner,sentinel}=>{
                if value.same_identity(&sentinel){self.protocol_stream_close_callable(&owner);return Err(self.iterator_stop(&owner)?);}
                self.protocol_stream_queue(state,ProtocolStream::CallableEqual{owner,value:value.clone()},Value::None);
                self.protocol_compare_into(state,"==".into(),sentinel,value)?;
            },
            ProtocolStream::CallableEqual{owner,value:original}=>{
                self.protocol_stream_queue(state,ProtocolStream::CallableTruth{owner,value:original},Value::None);
                if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}
            },
            ProtocolStream::CallableTruth{owner,value:original}=>{
                let Value::Bool(done)=value else{return Err(pyerr("RuntimeError","missing sentinel equality truth"));};
                if done{self.protocol_stream_close_callable(&owner);return Err(self.iterator_stop(&owner)?);}else{state.value=Some(original);}
            },
            ProtocolStream::SequenceItem{owner,object,position}=>{
                let payload=self.native_payload(&owner).unwrap_or_else(||owner.clone());let Value::Obj(index)=payload else{unreachable!()};
                let Object::Iterator(IteratorState::Reversed(_,current))=self.object(index)? else{unreachable!()};
                // sequence_iterator increments its live cursor after the call;
                // reversed snapshots its original index before __getitem__.
                if current!=-1 {let cursor=if position<=-2 {current}else{position};let next=cursor.checked_sub(1).ok_or_else(||pyerr("OverflowError","sequence iterator index overflow"))?;self.heap[index]=Some(Object::Iterator(IteratorState::Reversed(object,next)));}
                state.value=Some(value);
            },
            ProtocolStream::Enumerate{owner,..}=>{
                let payload=self.native_payload(&owner).unwrap_or_else(||owner.clone());let Value::Obj(index)=payload else{unreachable!()};
                let Object::Iterator(IteratorState::Enumerate(inner,n))=self.object(index)? else{unreachable!()};
                self.heap[index]=Some(Object::Iterator(IteratorState::Enumerate(inner,n.add(&Int::from_i128(1)))));
                state.value=Some(self.obj_value(Object::Tuple(vec![Value::Int(n.into()),value])));
            },
        }
        Ok(())
    }
    fn protocol_stream_failure(&mut self,state:&mut ProtocolState,error:&PyException)->PyResult<bool>{
        let mut current=error.clone();let mut replacement=false;
        loop {
            // A no-default inner next can propagate into input's ignored
            // flush/fileno boundary before reaching an outer next consumer.
            if self.protocol_input_recover_before(state,&current)? {return Ok(true);}
            let stop=self.exception_has_native_class(&current,"StopIteration");let index_error=self.exception_has_native_class(&current,"IndexError");
            let numeric=state.actions.iter().position(|action|matches!(action,ProtocolAction::Stream(record)if matches!(record.as_ref(),ProtocolStream::ToolConstructor{data,phase:1}if data.name=="islice")));
            if let Some(position)=numeric {
                let earlier=state.actions.iter().take(position).any(|action|matches!(action,ProtocolAction::Stream(record)if matches!(record.as_ref(),ProtocolStream::NextBoundary{..}|ProtocolStream::CallableValue{..}|ProtocolStream::SequenceItem{..}|ProtocolStream::Tool{fetch:true,..}|ProtocolStream::StrictProbe{..}|ProtocolStream::ToolConstructor{phase:4,..})));
                if !earlier {let ProtocolAction::Stream(record)=self.protocol_discard_actions(state,position+1).pop().unwrap()else{unreachable!()};let ProtocolStream::ToolConstructor{data,phase}=*record else{unreachable!()};state.plan=None;state.value=None;self.protocol_stream_tools_constructor_result(state,data,phase,None,Some(current))?;return Ok(true);}
            }
            if !stop&&!index_error{return if replacement{Err(current)}else{Ok(false)};}
            let boundary=state.actions.iter().position(|action|matches!(action,ProtocolAction::Stream(record)if matches!(record.as_ref(),ProtocolStream::NextBoundary{..}|ProtocolStream::CallableValue{..}|ProtocolStream::SequenceItem{..}|ProtocolStream::Tool{fetch:true,..}|ProtocolStream::Collect{strict:true,position:1..,..}|ProtocolStream::StrictProbe{..}|ProtocolStream::ToolConstructor{phase:4,..})));
            let Some(boundary)=boundary else{return if replacement{Err(current)}else{Ok(false)};};
            // IndexError terminates only the immediate sequence adapter, not
            // arbitrary user __next__, mapping, or iterator callbacks.
            if !stop&&!matches!(state.actions.get(boundary),Some(ProtocolAction::Stream(record))if matches!(record.as_ref(),ProtocolStream::SequenceItem{..})){return if replacement{Err(current)}else{Ok(false)};}
            let ProtocolAction::Stream(record)=self.protocol_discard_actions(state,boundary+1).pop().unwrap() else{unreachable!()};state.plan=None;state.value=None;
            state.binding_recovery=None;state.attribute_recovery=None;
            match *record {
                ProtocolStream::NextBoundary{default:Some(value),..}=>{state.value=Some(value);return Ok(true);},
                ProtocolStream::NextBoundary{stop_to_sink:true,..}=>{
                    match &mut state.sink {ProtocolSink::ForIter{finished,..}=>*finished=true,ProtocolSink::YieldFrom{finished}=>*finished=Some(Runtime::stop_value(&current)),_=>{}}
                    state.value=Some(Value::None);return Ok(true);
                },
                ProtocolStream::CallableValue{owner,..}=>{self.protocol_stream_close_callable(&owner);current=self.iterator_stop(&owner)?;replacement=true;},
                ProtocolStream::SequenceItem{owner,..}=>{let payload=self.native_payload(&owner).unwrap_or_else(||owner.clone());if let Value::Obj(index)=payload{self.heap[index]=Some(Object::Iterator(IteratorState::Reversed(Value::None,-1)));}current=self.iterator_stop(&owner)?;replacement=true;},
                ProtocolStream::ToolConstructor{data,phase}=>{self.protocol_stream_tools_constructor_result(state,data,phase,None,Some(current))?;return Ok(true);},
                ProtocolStream::Collect{owner,iters,function,position,..}=>{
                    if position>1{return Err(Self::protocol_strict_error(function.is_some(),position-1,"shorter"));}
                    match self.protocol_stream_strict_probe(state,owner,iters,function,1){Ok(())=>return Ok(true),Err(error)=>{current=error;replacement=true;} }
                },
                ProtocolStream::StrictProbe{owner,iters,function,position}=>{match self.protocol_stream_strict_probe(state,owner,iters,function,position+1){Ok(())=>return Ok(true),Err(error)=>{current=error;replacement=true;} }},
                ProtocolStream::Tool{owner,phase,..}=>match self.protocol_stream_tool_result(state,owner,phase,None,Some(current.clone())){
                    Ok(())=>return Ok(true),Err(error)=>{current=error;replacement=true;}
                },
                // A no-default next propagates through surrounding native
                // adapters in this same caller, retaining the original error.
                _=>{},
            }
        }
    }
}

#[derive(Clone,Debug)]
enum ProtocolGroupMode { Outer, Inner{generation:usize,key:Value} }
#[derive(Clone,Debug)]
enum ProtocolToolPhase {
    AccumulateInput,AccumulateValue,
    Batched(Vec<Value>),ChainOuter,ChainIter,ChainInner,
    CompressData,CompressSelect(Value),CompressTruth(Value),
    CountValue(Value),CycleInput,
    DropInput,DropPredicate(Value),DropTruth(Value),
    FalseInput,FalsePredicate(Value),FalseTruth(Value),
    GroupStep(ProtocolGroupMode),GroupInput(ProtocolGroupMode),GroupKey(ProtocolGroupMode,Value),
    GroupCompared(ProtocolGroupMode,Value),GroupTruth(ProtocolGroupMode,Value),
    ISliceInput(usize),PairFirst,PairNext(Value),
    StarInput,StarIter,StarCollect{iterator:Value,args:Vec<Value>},
    TakeInput,TakePredicate(Value),TakeTruth(Value),
    TeeInput(usize),ZipInput{position:usize,values:Vec<Value>},
}
impl ProtocolToolPhase {
    fn roots(&self,out:&mut Vec<Value>) {
        match self {
            Self::Batched(values)=>out.extend(values.iter().cloned()),
            Self::CompressSelect(value)|Self::CompressTruth(value)|Self::CountValue(value)|Self::DropPredicate(value)|Self::DropTruth(value)|Self::FalsePredicate(value)|Self::FalseTruth(value)|Self::PairNext(value)|Self::TakePredicate(value)|Self::TakeTruth(value)=>out.push(value.clone()),
            Self::GroupStep(mode)|Self::GroupInput(mode)|Self::GroupKey(mode,_)|Self::GroupCompared(mode,_)|Self::GroupTruth(mode,_)=>{
                if let ProtocolGroupMode::Inner{key,..}=mode{out.push(key.clone());}
                if let Self::GroupKey(_,value)|Self::GroupCompared(_,value)|Self::GroupTruth(_,value)=self{out.push(value.clone());}
            },
            Self::StarCollect{iterator,args}=>{out.push(iterator.clone());out.extend(args.iter().cloned());},
            Self::ZipInput{values,..}=>out.extend(values.iter().cloned()),
            _=>{},
        }
    }
}
impl Runtime {
    fn protocol_stream_abandon(&mut self,state:&ProtocolState) {
        for action in &state.actions {if let ProtocolAction::Stream(record)=action {if let ProtocolStream::Tool{owner,phase:ProtocolToolPhase::TeeInput(_),fetch:true}=record.as_ref() {
            if let Ok((_,tool))=self.protocol_stream_tool_state(owner) {if let ToolsState::Tee{shared,..}=*tool {shared.borrow_mut().running=false;}}
        }
        if let ProtocolStream::Tool{owner,phase,..}=record.as_ref() {if let Ok((index,mut tool))=self.protocol_stream_tool_state(owner) {
            match (phase,tool.as_mut()) {
                (ProtocolToolPhase::ChainOuter|ProtocolToolPhase::ChainIter,ToolsState::Chain{done,inner,..})=>{*done=true;*inner=None;},
                (ProtocolToolPhase::ZipInput{..},ToolsState::ZipLongest{active,..})=>*active=0,
                _=>continue,
            }self.protocol_stream_tool_store(index,tool);
        }}
        }}
    }
    fn protocol_stream_tool_state(&self,owner:&Value)->PyResult<(usize,Box<ToolsState>)> {
        let payload=self.native_payload(owner).unwrap_or_else(||owner.clone());
        let Value::Obj(index)=payload else{return Err(pyerr("RuntimeError","invalid tool iterator"))};
        let Object::Iterator(IteratorState::Tools(tool))=self.object(index)? else{return Err(pyerr("RuntimeError","invalid tool iterator"))};Ok((index,tool))
    }
    fn protocol_stream_tool_store(&mut self,index:usize,tool:Box<ToolsState>) {self.heap[index]=Some(Object::Iterator(IteratorState::Tools(tool)));}
    fn protocol_stream_tool_action(&mut self,state:&mut ProtocolState,owner:Value,phase:ProtocolToolPhase,value:Value) {
        self.protocol_stream_queue(state,ProtocolStream::Tool{owner,phase,fetch:false},value);
    }
    fn protocol_stream_tool_fetch(&mut self,state:&mut ProtocolState,owner:Value,phase:ProtocolToolPhase,iterator:Value) {
        self.protocol_stream_queue(state,ProtocolStream::Tool{owner,phase,fetch:true},Value::None);self.protocol_stream_inner_next(state,iterator);
    }
    fn protocol_stream_tool_truth(&mut self,state:&mut ProtocolState,owner:Value,phase:ProtocolToolPhase,value:Value)->PyResult<()> {
        self.protocol_stream_tool_action(state,owner,phase,Value::None);
        if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}Ok(())
    }
    fn protocol_stream_binary(&mut self,state:&mut ProtocolState,left:Value,right:Value)->PyResult<()> {
        if self.object_class(&left).is_none()&&self.object_class(&right).is_none(){state.value=Some(self.binary("+",left,right)?);return Ok(());}
        self.protocol_operand_next(state,ProtocolOperand{op:"+".into(),left,right,kind:ProtocolOperandKind::Binary{phase:0,same:false,right_first:false,reflected:None,sequence:false}})
    }
    fn protocol_stream_tool_stop(&mut self,owner:&Value,error:Option<PyException>,preserve:bool)->PyException {
        if preserve {if let Some(error)=error{return error;}}
        self.iterator_stop(owner).unwrap_or_else(|error|error)
    }
    fn protocol_stream_tool_start(&mut self,state:&mut ProtocolState,owner:Value,payload:Value)->PyResult<bool> {
        let Value::Obj(index)=payload else{return Ok(false)};
        let Some(Object::Iterator(IteratorState::Tools(_)))=self.heap.get(index).and_then(Option::as_ref) else{return Ok(false)};
        let (_,mut tool)=self.protocol_stream_tool_state(&owner)?;
        match tool.as_mut() {
            // These iterator states only move already-built values and integer
            // positions; they cannot invoke Python code.
            ToolsState::Combinations{..}|ToolsState::Permutations{..}|ToolsState::Product{..}|ToolsState::Repeat{..}=>{state.value=Some(self.iterator_next(Value::Obj(index))?);},
            ToolsState::Accumulate{iter,total,initial,started,..}=>{
                if !*started {*started=true;if let Some(value)=initial.take(){*total=Some(value.clone());self.protocol_stream_tool_store(index,tool);state.value=Some(value);return Ok(true);}}
                let iter=iter.clone();self.protocol_stream_tool_store(index,tool);self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::AccumulateInput,iter);
            },
            ToolsState::Batched{iter,..}=>self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::Batched(Vec::new()),iter.clone()),
            ToolsState::Chain{outer,inner,done}=>{
                if *done{return Err(self.iterator_stop(&owner)?);}
                if let Some(inner)=inner {self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::ChainInner,inner.clone());}
                else{self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::ChainOuter,outer.clone());}
            },
            ToolsState::Compress{data,..}=>self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::CompressData,data.clone()),
            ToolsState::Count{current,step,fast}=>{
                let (left,right)=(current.clone(),if *fast{Value::Int(Int::from_i128(1).into())}else{step.clone()});
                self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::CountValue(left.clone()),Value::None);
                self.protocol_stream_binary(state,left,right)?;
            },
            ToolsState::Cycle{iter,cache,index:position}=>{
                if let Some(iter)=iter{self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::CycleInput,iter.clone());}
                else if cache.is_empty(){return Err(self.iterator_stop(&owner)?);}
                else{let value=cache[*position].clone();*position=(*position+1)%cache.len();self.protocol_stream_tool_store(index,tool);state.value=Some(value);}
            },
            ToolsState::DropWhile{iter,..}=>self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::DropInput,iter.clone()),
            ToolsState::FilterFalse{iter,..}=>self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::FalseInput,iter.clone()),
            ToolsState::GroupBy(_)=>self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::GroupStep(ProtocolGroupMode::Outer),Value::None),
            ToolsState::Group{generation,key,..}=>self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::GroupStep(ProtocolGroupMode::Inner{generation:*generation,key:key.clone()}),Value::None),
            ToolsState::ISlice{iter,start,stop,index:position,done,..}=>{
                if *done||stop.is_some_and(|stop|*position>=stop.max(*start)){*done=true;self.protocol_stream_tool_store(index,tool);return Err(self.iterator_stop(&owner)?);}
                self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::ISliceInput(*position),iter.clone());
            },
            ToolsState::Pairwise{iter,previous}=>self.protocol_stream_tool_fetch(state,owner,previous.clone().map(ProtocolToolPhase::PairNext).unwrap_or(ProtocolToolPhase::PairFirst),iter.clone()),
            ToolsState::StarMap{iter,..}=>self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::StarInput,iter.clone()),
            ToolsState::TakeWhile{iter,done,..}=>{if *done{return Err(self.iterator_stop(&owner)?);}self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::TakeInput,iter.clone());},
            ToolsState::Tee{shared,cursor}=>{
                let position=cursor.get();let (value,source,exhausted)={let shared=shared.borrow();(shared.buffer.get(position-shared.base).cloned(),shared.iter.clone(),shared.exhausted)};
                if let Some(value)=value {self.protocol_stream_tee_deliver(state,&owner,value,position)?;}
                else if exhausted{return Err(self.iterator_stop(&owner)?);}
                else{if shared.borrow().running{return Err(pyerr("RuntimeError","cannot re-enter the tee iterator"));}shared.borrow_mut().running=true;self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::TeeInput(position),source);}
            },
            ToolsState::ZipLongest{active,..}=>{if *active==0{return Err(self.iterator_stop(&owner)?);}self.protocol_stream_zip_longest(state,owner,0,Vec::new())?;},
        }
        Ok(true)
    }
    fn protocol_stream_zip_longest(&mut self,state:&mut ProtocolState,owner:Value,mut position:usize,mut values:Vec<Value>)->PyResult<()> {
        let (_,tool)=self.protocol_stream_tool_state(&owner)?;let ToolsState::ZipLongest{iters,fill,active}=*tool else{unreachable!()};
        if active==0{return Err(self.iterator_stop(&owner)?);}
        while position<iters.len() {
            if let Some(iter)=&iters[position] {self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::ZipInput{position,values},iter.clone());return Ok(());}
            values.push(fill.clone());position+=1;
        }
        state.value=Some(self.obj_value(Object::Tuple(values)));Ok(())
    }
    fn protocol_stream_tee_deliver(&mut self,state:&mut ProtocolState,owner:&Value,value:Value,position:usize)->PyResult<()> {
        let (_,tool)=self.protocol_stream_tool_state(owner)?;let ToolsState::Tee{shared,cursor}=*tool else{unreachable!()};
        cursor.set(position.checked_add(1).ok_or_else(||pyerr("OverflowError","tee index overflow"))?);
        {let mut shared=shared.borrow_mut();shared.cursors.retain(|cursor|cursor.strong_count()!=0);let oldest=shared.cursors.iter().filter_map(std::rc::Weak::upgrade).map(|cursor|cursor.get()).min().unwrap_or(cursor.get());while shared.base<oldest{shared.buffer.pop_front();shared.base+=1;}}
        state.value=Some(value);Ok(())
    }
    fn protocol_stream_group_shared(&self,owner:&Value)->PyResult<std::rc::Rc<std::cell::RefCell<ToolsGroup>>> {
        let (_,tool)=self.protocol_stream_tool_state(owner)?;match *tool{ToolsState::GroupBy(shared)|ToolsState::Group{shared,..}=>Ok(shared),_=>unreachable!()}
    }
    fn protocol_stream_group_advance(&mut self,state:&mut ProtocolState,owner:Value,mode:ProtocolGroupMode)->PyResult<()> {
        let shared=self.protocol_stream_group_shared(&owner)?;let source=shared.borrow().iter.clone();
        self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::GroupInput(mode),source);Ok(())
    }
    fn protocol_stream_group_emit(&mut self,state:&mut ProtocolState,owner:&Value)->PyResult<()> {
        let shared=self.protocol_stream_group_shared(owner)?;
        let (key,generation)={let mut data=shared.borrow_mut();let key=data.current.as_ref().unwrap().0.clone();data.active_key=Some(key.clone());data.generation=data.generation.checked_add(1).ok_or_else(||pyerr("OverflowError","too many groups"))?;(key,data.generation)};
        let group=self.tools_iterator(ToolsState::Group{shared,generation,key:key.clone()});state.value=Some(self.obj_value(Object::Tuple(vec![key,group])));Ok(())
    }
    fn protocol_stream_tool_result(&mut self,state:&mut ProtocolState,owner:Value,phase:ProtocolToolPhase,value:Option<Value>,error:Option<PyException>)->PyResult<()> {
        let (index,mut tool)=self.protocol_stream_tool_state(&owner)?;
        match phase {
            ProtocolToolPhase::AccumulateInput=>{
                let Some(value)=value else{return Err(self.protocol_stream_tool_stop(&owner,error,true));};
                let ToolsState::Accumulate{function,total,..}=tool.as_mut() else{unreachable!()};
                if let Some(previous)=total.clone(){let function=function.clone();self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::AccumulateValue,Value::None);if matches!(function,Value::None){self.protocol_stream_binary(state,previous,value)?;}else{self.protocol_stream_plan(state,function,vec![previous,value]);}}
                else{*total=Some(value.clone());self.protocol_stream_tool_store(index,tool);state.value=Some(value);}
            },
            ProtocolToolPhase::AccumulateValue=>{let value=value.unwrap();let ToolsState::Accumulate{total,..}=tool.as_mut() else{unreachable!()};*total=Some(value.clone());self.protocol_stream_tool_store(index,tool);state.value=Some(value);},
            ProtocolToolPhase::Batched(mut values)=>{
                let ToolsState::Batched{iter,size,strict}=*tool else{unreachable!()};
                if let Some(value)=value{values.push(value);if values.len()<size{self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::Batched(values),iter);return Ok(());}}
                if values.is_empty(){return Err(self.protocol_stream_tool_stop(&owner,None,false));}
                if strict&&values.len()!=size{return Err(pyerr("ValueError","batched(): incomplete batch"));}state.value=Some(self.obj_value(Object::Tuple(values)));
            },
            ProtocolToolPhase::ChainOuter=>{
                if let Some(value)=value{self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::ChainIter,Value::None);self.protocol_stream_plan(state,Value::Builtin("iter".into()),vec![value]);}
                else{let ToolsState::Chain{done,..}=tool.as_mut()else{unreachable!()};*done=true;self.protocol_stream_tool_store(index,tool);return Err(self.protocol_stream_tool_stop(&owner,None,false));}
            },
            ProtocolToolPhase::ChainIter=>{let value=value.unwrap();let ToolsState::Chain{inner,..}=tool.as_mut()else{unreachable!()};*inner=Some(value.clone());self.protocol_stream_tool_store(index,tool);self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::ChainInner,value);},
            ProtocolToolPhase::ChainInner=>{if let Some(value)=value{state.value=Some(value);}else{let ToolsState::Chain{inner,outer,..}=tool.as_mut()else{unreachable!()};*inner=None;let outer=outer.clone();self.protocol_stream_tool_store(index,tool);self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::ChainOuter,outer);}},
            ProtocolToolPhase::CompressData=>{let Some(value)=value else{return Err(self.protocol_stream_tool_stop(&owner,error,true));};let ToolsState::Compress{selectors,..}=*tool else{unreachable!()};self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::CompressSelect(value),selectors);},
            ProtocolToolPhase::CompressSelect(original)=>{let Some(value)=value else{return Err(self.protocol_stream_tool_stop(&owner,error,true));};self.protocol_stream_tool_truth(state,owner,ProtocolToolPhase::CompressTruth(original),value)?;},
            ProtocolToolPhase::CompressTruth(original)=>{if matches!(value,Some(Value::Bool(true))){state.value=Some(original);}else{self.protocol_stream_tool_start(state,owner,Value::Obj(index))?;}},
            ProtocolToolPhase::CountValue(original)=>{let value=value.unwrap();let ToolsState::Count{current,..}=tool.as_mut()else{unreachable!()};*current=value;self.protocol_stream_tool_store(index,tool);state.value=Some(original);},
            ProtocolToolPhase::CycleInput=>{let ToolsState::Cycle{iter,cache,..}=tool.as_mut()else{unreachable!()};if let Some(value)=value{cache.push(value.clone());self.protocol_stream_tool_store(index,tool);state.value=Some(value);}else{*iter=None;self.protocol_stream_tool_store(index,tool);self.protocol_stream_tool_start(state,owner,Value::Obj(index))?;}},
            ProtocolToolPhase::DropInput|ProtocolToolPhase::FalseInput|ProtocolToolPhase::TakeInput=>{
                let Some(value)=value else{if let ToolsState::TakeWhile{done,..}=tool.as_mut(){*done=true;self.protocol_stream_tool_store(index,tool);}return Err(self.protocol_stream_tool_stop(&owner,error,true));};
                let (predicate,next)=match tool.as_ref(){ToolsState::DropWhile{predicate,dropping,..}=>{if !*dropping{state.value=Some(value);return Ok(());}(predicate.clone(),ProtocolToolPhase::DropPredicate(value.clone()))},ToolsState::FilterFalse{predicate,..}=>(predicate.clone(),ProtocolToolPhase::FalsePredicate(value.clone())),ToolsState::TakeWhile{predicate,..}=>(predicate.clone(),ProtocolToolPhase::TakePredicate(value.clone())),_=>unreachable!()};
                if matches!(predicate,Value::None)&&matches!(tool.as_ref(),ToolsState::FilterFalse{..}){self.protocol_stream_tool_action(state,owner,next,value);}
                else{self.protocol_stream_tool_action(state,owner,next,Value::None);self.protocol_stream_plan(state,predicate,vec![value]);}
            },
            ProtocolToolPhase::DropPredicate(original)=>self.protocol_stream_tool_truth(state,owner,ProtocolToolPhase::DropTruth(original),value.unwrap())?,
            ProtocolToolPhase::FalsePredicate(original)=>self.protocol_stream_tool_truth(state,owner,ProtocolToolPhase::FalseTruth(original),value.unwrap())?,
            ProtocolToolPhase::TakePredicate(original)=>self.protocol_stream_tool_truth(state,owner,ProtocolToolPhase::TakeTruth(original),value.unwrap())?,
            ProtocolToolPhase::DropTruth(original)=>{let yes=matches!(value,Some(Value::Bool(true)));if yes{self.protocol_stream_tool_start(state,owner,Value::Obj(index))?;}else{let ToolsState::DropWhile{dropping,..}=tool.as_mut()else{unreachable!()};*dropping=false;self.protocol_stream_tool_store(index,tool);state.value=Some(original);}},
            ProtocolToolPhase::FalseTruth(original)=>{if matches!(value,Some(Value::Bool(true))){self.protocol_stream_tool_start(state,owner,Value::Obj(index))?;}else{state.value=Some(original);}},
            ProtocolToolPhase::TakeTruth(original)=>{if matches!(value,Some(Value::Bool(true))){state.value=Some(original);}else{let ToolsState::TakeWhile{done,..}=tool.as_mut()else{unreachable!()};*done=true;self.protocol_stream_tool_store(index,tool);return Err(self.protocol_stream_tool_stop(&owner,None,false));}},
            ProtocolToolPhase::ISliceInput(position)=>{
                let ToolsState::ISlice{index:current,target,step,stop,done,..}=tool.as_mut()else{unreachable!()};
                let Some(value)=value else{*done=true;self.protocol_stream_tool_store(index,tool);return Err(self.protocol_stream_tool_stop(&owner,error,true));};
                *current=current.checked_add(1).ok_or_else(||pyerr("OverflowError","islice index overflow"))?;
                let emit=position==*target&&stop.is_none_or(|stop|position<stop);if emit{*target=target.saturating_add(*step);}self.protocol_stream_tool_store(index,tool);
                if emit{state.value=Some(value);}else{self.protocol_stream_tool_start(state,owner,Value::Obj(index))?;}
            },
            ProtocolToolPhase::PairFirst=>{let Some(value)=value else{return Err(self.protocol_stream_tool_stop(&owner,error,true));};let ToolsState::Pairwise{previous,iter}=tool.as_mut()else{unreachable!()};*previous=Some(value.clone());let iter=iter.clone();self.protocol_stream_tool_store(index,tool);self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::PairNext(value),iter);},
            ProtocolToolPhase::PairNext(previous)=>{let Some(value)=value else{return Err(self.protocol_stream_tool_stop(&owner,error,true));};let ToolsState::Pairwise{previous:stored,..}=tool.as_mut()else{unreachable!()};*stored=Some(value.clone());self.protocol_stream_tool_store(index,tool);state.value=Some(self.obj_value(Object::Tuple(vec![previous,value])));},
            ProtocolToolPhase::StarInput=>{let Some(value)=value else{return Err(self.protocol_stream_tool_stop(&owner,error,true));};self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::StarIter,Value::None);self.protocol_stream_plan(state,Value::Builtin("iter".into()),vec![value]);},
            ProtocolToolPhase::StarIter=>{let iterator=value.unwrap();self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::StarCollect{iterator:iterator.clone(),args:Vec::new()},iterator);},
            ProtocolToolPhase::StarCollect{iterator,mut args}=>{if let Some(value)=value{args.push(value);self.protocol_stream_tool_fetch(state,owner,ProtocolToolPhase::StarCollect{iterator:iterator.clone(),args},iterator);}else{let ToolsState::StarMap{function,..}=*tool else{unreachable!()};self.protocol_stream_plan(state,function,args);}},
            ProtocolToolPhase::TeeInput(position)=>{let ToolsState::Tee{shared,..}=*tool else{unreachable!()};shared.borrow_mut().running=false;if let Some(value)=value{shared.borrow_mut().buffer.push_back(value.clone());self.protocol_stream_tee_deliver(state,&owner,value,position)?;}else{shared.borrow_mut().exhausted=true;return Err(self.protocol_stream_tool_stop(&owner,None,false));}},
            ProtocolToolPhase::ZipInput{position,mut values}=>{
                let ToolsState::ZipLongest{iters,fill,active}=tool.as_mut()else{unreachable!()};
                let value=if let Some(value)=value{value}else{iters[position]=None;*active=active.saturating_sub(1);if *active==0{self.protocol_stream_tool_store(index,tool);return Err(self.protocol_stream_tool_stop(&owner,None,false));}fill.clone()};values.push(value);self.protocol_stream_tool_store(index,tool);self.protocol_stream_zip_longest(state,owner,position+1,values)?;
            },
            ProtocolToolPhase::GroupStep(mode)=>{
                let shared=self.protocol_stream_group_shared(&owner)?;let (current,consumed,active,exhausted,generation)={let data=shared.borrow();(data.current.clone(),data.consumed,data.active_key.clone(),data.exhausted,data.generation)};
                if exhausted||matches!(&mode,ProtocolGroupMode::Inner{generation:expected,..}if *expected!=generation){return Err(self.protocol_stream_tool_stop(&owner,None,false));}
                if current.is_none()||consumed{self.protocol_stream_group_advance(state,owner,mode)?;}
                else{let (key,original)=current.unwrap();let target=match &mode{ProtocolGroupMode::Outer=>active,ProtocolGroupMode::Inner{key,..}=>Some(key.clone())};if let Some(target)=target{
                    if target.same_identity(&key){self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::GroupTruth(mode,original),Value::Bool(true));}
                    else{self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::GroupCompared(mode,original),Value::None);self.protocol_compare_into(state,"==".into(),target,key)?;}
                }else{self.protocol_stream_group_emit(state,&owner)?;}}
            },
            ProtocolToolPhase::GroupInput(mode)=>{let shared=self.protocol_stream_group_shared(&owner)?;if let Some(value)=value{let function=shared.borrow().function.clone();if matches!(function,Value::None){self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::GroupKey(mode,value.clone()),value);}else{self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::GroupKey(mode,value.clone()),Value::None);self.protocol_stream_plan(state,function,vec![value]);}}else{let mut data=shared.borrow_mut();data.exhausted=true;data.current=None;return Err(self.protocol_stream_tool_stop(&owner,None,false));}},
            ProtocolToolPhase::GroupKey(mode,original)=>{let shared=self.protocol_stream_group_shared(&owner)?;{let mut data=shared.borrow_mut();data.current=Some((value.unwrap(),original));data.consumed=false;}self.protocol_stream_tool_action(state,owner,ProtocolToolPhase::GroupStep(mode),Value::None);},
            ProtocolToolPhase::GroupCompared(mode,original)=>self.protocol_stream_tool_truth(state,owner,ProtocolToolPhase::GroupTruth(mode,original),value.unwrap())?,
            ProtocolToolPhase::GroupTruth(mode,original)=>{
                let equal=matches!(value,Some(Value::Bool(true)));match mode{ProtocolGroupMode::Outer=>if equal{self.protocol_stream_group_advance(state,owner,ProtocolGroupMode::Outer)?;}else{self.protocol_stream_group_emit(state,&owner)?;},ProtocolGroupMode::Inner{..}=>if equal{self.protocol_stream_group_shared(&owner)?.borrow_mut().consumed=true;state.value=Some(original);}else{return Err(self.protocol_stream_tool_stop(&owner,None,false));}}
            },
        }
        Ok(())
    }
}

#[derive(Clone,Debug)]
struct ProtocolConstructor {name:String,inputs:Vec<Value>,function:Value,start:Value,iters:Vec<Value>,position:usize,strict:bool}
impl Runtime {
    fn protocol_strict_error(map:bool,position:usize,relation:&str)->PyException {
        let name=if map{"map"}else{"zip"};let previous=if position==1{"argument 1".into()}else{format!("arguments 1-{position}")};
        pyerr("ValueError",format!("{name}() argument {} is {relation} than {previous}",position+1))
    }
    fn protocol_stream_strict_probe(&mut self,state:&mut ProtocolState,owner:Value,iters:Vec<Value>,function:Option<Value>,position:usize)->PyResult<()> {
        if position>=iters.len(){return Err(self.iterator_stop(&owner)?);}
        let iterator=iters[position].clone();self.protocol_stream_queue(state,ProtocolStream::StrictProbe{owner,iters,function,position},Value::None);self.protocol_stream_inner_next(state,iterator);Ok(())
    }
    fn protocol_stream_native_strict_next(&mut self,iters:Vec<Value>,function:Option<Value>)->PyResult<Option<Value>> {
        let mut roots=iters.clone();roots.extend(function.iter().cloned());
        self.view_rooted(roots,|runtime,root|{
            if iters.is_empty(){return Ok(None);}
            let mut args=Vec::new();
            for (position,iterator) in iters.iter().enumerate() {
                if let Some(value)=runtime.next(iterator.clone())?{runtime.roots[root].push(value.clone());args.push(value);}
                else{
                    if position>0{return Err(Self::protocol_strict_error(function.is_some(),position,"shorter"));}
                    for (position,iterator) in iters.iter().enumerate().skip(1) {if runtime.next(iterator.clone())?.is_some(){return Err(Self::protocol_strict_error(function.is_some(),position,"longer"));}}
                    return Ok(None);
                }
            }
            if let Some(function)=function{Ok(Some(runtime.call(function,args,Vec::new(),None)?))}else{Ok(Some(runtime.obj_value(Object::Tuple(args))))}
        })
    }
    fn protocol_stream_constructor(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let Value::Builtin(name)=&plan.function else{return Ok(false)};
        match name.as_str() {
            "map"|"zip"=>{
                for (key,_) in &plan.kwargs{if key!="strict"{self.execution_unknown_keyword(name,key,&["strict"])?;}}
                let strict=plan.kwargs.iter().find(|(key,_)|key=="strict").map(|(_,value)|value.clone()).unwrap_or(Value::Bool(false));
                let data=ProtocolConstructor{name:name.clone(),inputs:plan.args.clone(),function:Value::None,start:Value::None,iters:Vec::new(),position:0,strict:false};
                self.protocol_stream_queue(state,ProtocolStream::Constructor{data,phase:0},Value::None);
                if !self.protocol_python_truth(state,strict.clone())?{state.value=Some(Value::Bool(self.truth(&strict)?));}
            },
            "filter"=>{
                if plan.args.len()!=2||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","filter expected 2 positional arguments"));}
                let data=ProtocolConstructor{name:name.clone(),inputs:vec![plan.args[1].clone()],function:plan.args[0].clone(),start:Value::None,iters:Vec::new(),position:0,strict:false};
                self.protocol_stream_constructor_next(state,data)?;
            },
            "enumerate"=>{
                let mut args=codec_bind("enumerate",plan.args.clone(),plan.kwargs.clone(),&["iterable","start"])?;
                let iterable=args[0].take().ok_or_else(||pyerr("TypeError","enumerate() missing required argument 'iterable'"))?;
                let start=args[1].take().unwrap_or_else(||Value::Int(Int::from_i128(0).into()));
                let data=ProtocolConstructor{name:name.clone(),inputs:vec![iterable],function:Value::None,start:start.clone(),iters:Vec::new(),position:0,strict:false};
                self.protocol_stream_queue(state,ProtocolStream::Constructor{data,phase:1},Value::None);
                if let Some(integer)=self.protocol_primitive_int(&start){state.value=Some(Value::Int(integer.into()));}
                else if let Some((method,class))=self.protocol_slot(&start,"__index__"){self.protocol_bind(state,method,start,class,Vec::new(),Vec::new(),ProtocolAction::Integer("__index__".into()),false)?;}
                else{return Err(pyerr("TypeError",format!("'{}' object cannot be interpreted as an integer",self.typename(&start))));}
            },
            "reversed"=>{
                if plan.args.len()!=1||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","reversed() takes exactly one argument"));}
                let object=plan.args[0].clone();
                if let Some((method,class))=self.protocol_slot(&object,"__reversed__") {self.protocol_bind(state,method,object,class,Vec::new(),Vec::new(),ProtocolAction::Pass,false)?;}
                else if let Some(class)=self.object_class(&object){
                    // A concrete native __reversed__ uses its own payload; it
                    // must precede a later Python __len__ implementation.
                    if self.slot_definition(&class,"__reversed__",0).is_some(){return Ok(false);}
                    if self.slot_definition(&class,"__getitem__",0).is_none(){return Err(pyerr("TypeError",format!("'{}' object is not reversible",self.typename(&object))));}
                    self.protocol_stream_queue(state,ProtocolStream::ReversedLength(object.clone()),Value::None);self.protocol_stream_plan(state,Value::Builtin("len".into()),vec![object]);
                }else{return Ok(false);}
            },
            _=>return Ok(false),
        }
        Ok(true)
    }
    fn protocol_stream_constructor_next(&mut self,state:&mut ProtocolState,mut data:ProtocolConstructor)->PyResult<()> {
        if data.position<data.inputs.len(){let iterable=data.inputs[data.position].clone();data.position+=1;self.protocol_stream_queue(state,ProtocolStream::Constructor{data,phase:2},Value::None);self.protocol_stream_plan(state,Value::Builtin("iter".into()),vec![iterable]);return Ok(());}
        let iterator=match data.name.as_str(){
            "map"=>if data.strict{IteratorState::MapStrict(data.function,data.iters)}else{IteratorState::Map(data.function,data.iters)},
            "zip"=>if data.strict{IteratorState::ZipStrict(data.iters)}else{IteratorState::Zip(data.iters)},
            "filter"=>IteratorState::Filter(data.function,data.iters.remove(0)),
            "enumerate"=>IteratorState::Enumerate(data.iters.remove(0),self.protocol_primitive_int(&data.start).ok_or_else(||pyerr("TypeError","invalid enumerate index"))?),
            _=>unreachable!(),
        };
        state.value=Some(self.obj_value(Object::Iterator(iterator)));Ok(())
    }
    fn protocol_stream_constructor_result(&mut self,state:&mut ProtocolState,mut data:ProtocolConstructor,phase:u8,value:Value)->PyResult<()> {
        match phase {
            0=>{let Value::Bool(strict)=value else{unreachable!()};data.strict=strict;if data.name=="map"{if data.inputs.len()<2{return Err(pyerr("TypeError","map() must have at least two arguments."));}data.function=data.inputs.remove(0);}},
            1=>{data.start=value;},
            2=>data.iters.push(value),
            _=>unreachable!(),
        }
        self.protocol_stream_constructor_next(state,data)
    }
}

#[derive(Clone,Debug)]
struct ProtocolToolConstructor {
    name:String,bound:Vec<Option<Value>>,inputs:Vec<Value>,iters:Vec<Value>,pools:Vec<Vec<Value>>,
    position:usize,numeric:Vec<Option<Value>>,numbers:Vec<Option<Int>>,numeric_position:usize,numeric_error:Option<PyException>,numeric_error_position:usize,strict:bool,
}
impl ProtocolToolConstructor {
    fn roots(&self,out:&mut Vec<Value>){
        out.extend(self.bound.iter().flatten().cloned());out.extend(self.inputs.iter().cloned());out.extend(self.iters.iter().cloned());out.extend(self.pools.iter().flatten().cloned());out.extend(self.numeric.iter().flatten().cloned());
        if let Some(error)=&self.numeric_error {Runtime::exception_roots(error,out);}
    }
    fn pool(&self)->bool {matches!(self.name.as_str(),"combinations"|"combinations_with_replacement"|"permutations"|"product")}
}
impl Runtime {
    fn protocol_stream_tools_constructor(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool>{
        let Value::Builtin(fullname)=&plan.function else{return Ok(false)};
        let Some(name)=fullname.strip_prefix("module:itertools:")else{return Ok(false)};
        if name=="count"||name=="chain"{return Ok(false);}
        let mut bound;let mut inputs=Vec::new();let mut numeric=Vec::new();
        match name {
            "accumulate"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["iterable","func","initial"],2,0,1)?;inputs.push(bound[0].clone().unwrap());},
            "batched"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["iterable","n","strict"],2,0,2)?;inputs.push(bound[0].clone().unwrap());numeric.push(bound[1].clone());},
            "chain.from_iterable"|"cycle"|"pairwise"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["iterable"],1,1,1)?;inputs.push(bound[0].clone().unwrap());},
            "combinations"|"combinations_with_replacement"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["iterable","r"],2,0,2)?;inputs.push(bound[0].clone().unwrap());numeric.push(bound[1].clone());},
            "compress"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["data","selectors"],2,0,2)?;inputs.extend(bound.iter().flatten().cloned());},
            "dropwhile"|"filterfalse"|"takewhile"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["predicate","iterable"],2,2,2)?;inputs.push(bound[1].clone().unwrap());},
            "groupby"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["iterable","key"],2,0,1)?;inputs.push(bound[0].clone().unwrap());},
            "islice"=>{
                if !plan.kwargs.is_empty()||!(2..=4).contains(&plan.args.len()){return Err(pyerr("TypeError","islice() requires 2 to 4 positional arguments"));}
                bound=plan.args.iter().cloned().map(Some).collect();inputs.push(plan.args[0].clone());
                if plan.args.len()==2{numeric.extend([None,Some(plan.args[1].clone()),None]);}else{numeric.extend([Some(plan.args[1].clone()),Some(plan.args[2].clone()),plan.args.get(3).cloned()]);}
            },
            "permutations"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["iterable","r"],2,0,1)?;inputs.push(bound[0].clone().unwrap());},
            "product"=>{
                for (key,_)in &plan.kwargs{if key!="repeat"{self.execution_unknown_keyword("product",key,&["repeat"])?;}}
                let repeat=plan.kwargs.iter().find(|(key,_)|key=="repeat").map(|(_,value)|value.clone()).unwrap_or_else(||Value::Int(Int::from_i128(1).into()));
                bound=vec![Some(repeat.clone())];numeric.push(Some(repeat));inputs=plan.args.clone();
            },
            "repeat"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["object","times"],2,0,1)?;if let Some(times)=&bound[1]{numeric.push(Some(times.clone()));}},
            "starmap"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["function","iterable"],2,2,2)?;inputs.push(bound[1].clone().unwrap());},
            "tee"=>{bound=self.tools_arguments(name,plan.args.clone(),plan.kwargs.clone(),&["iterable","n"],2,2,1)?;inputs.push(bound[0].clone().unwrap());numeric.push(Some(bound[1].clone().unwrap_or_else(||Value::Int(Int::from_i128(2).into()))));},
            "zip_longest"=>{for (key,_)in &plan.kwargs{if key!="fillvalue"{self.execution_unknown_keyword("zip_longest",key,&["fillvalue"])?;}}bound=vec![Some(plan.kwargs.iter().find(|(key,_)|key=="fillvalue").map(|(_,value)|value.clone()).unwrap_or(Value::None))];inputs=plan.args.clone();},
            _=>return Ok(false),
        }
        // Keep the original arguments in bound while conversions suspend;
        // prepared iterator handles and pool elements have independent roots.
        let data=ProtocolToolConstructor{name:name.into(),bound,inputs,iters:Vec::new(),pools:Vec::new(),position:0,numeric,numbers:Vec::new(),numeric_position:0,numeric_error:None,numeric_error_position:usize::MAX,strict:false};
        self.protocol_stream_tools_numeric(state,data)?;Ok(true)
    }
    fn protocol_stream_tools_index_error(name:&str)->PyException {pyerr("ValueError",if name=="stop"{"Stop argument for islice() must be None or an integer: 0 <= x <= sys.maxsize."}else if name=="step"{"Step for islice() must be a positive integer or None."}else{"Indices for islice() must be None or an integer: 0 <= x <= sys.maxsize."})}
    fn protocol_stream_tools_numeric(&mut self,state:&mut ProtocolState,mut data:ProtocolToolConstructor)->PyResult<()> {
        if data.name=="islice"&&data.numeric_position==2 {
            let valid=|number:&Option<Int>|number.as_ref().is_none_or(|number|number.to_i128().is_some_and(|number|number>=0&&number<=isize::MAX as i128));
            if data.numeric_error_position==0||!valid(&data.numbers[0]){return Err(Self::protocol_stream_tools_index_error("start"));}
            if data.numeric_error_position==1{return Err(Self::protocol_stream_tools_index_error("stop"));}
            if !valid(&data.numbers[1]){return Err(Self::protocol_stream_tools_index_error("stop"));}
        }
        if data.numeric_position<data.numeric.len() {
            let value=data.numeric[data.numeric_position].clone().filter(|value|!matches!(value,Value::None));data.numeric_position+=1;
            if value.is_none()&&data.name=="islice"{data.numbers.push(None);return self.protocol_stream_tools_numeric(state,data);}
            let value=value.ok_or_else(||pyerr("TypeError","integer argument expected"))?;
            self.protocol_stream_queue(state,ProtocolStream::ToolConstructor{data,phase:1},Value::None);
            if let Some(integer)=self.protocol_primitive_int(&value){state.value=Some(Value::Int(integer.into()));}
            else if let Some((method,class))=self.protocol_slot(&value,"__index__"){self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Integer("__index__".into()),false)?;}
            else{return Err(pyerr("TypeError",format!("'{}' object cannot be interpreted as an integer",self.typename(&value))));}
            return Ok(());
        }
        if data.name=="batched" {
            let strict=data.bound[2].clone().unwrap_or(Value::Bool(false));self.protocol_stream_queue(state,ProtocolStream::ToolConstructor{data,phase:2},Value::None);
            if !self.protocol_python_truth(state,strict.clone())?{state.value=Some(Value::Bool(self.truth(&strict)?));}return Ok(());
        }
        self.protocol_stream_tools_numeric_done(state,data)
    }
    fn protocol_stream_tools_number(data:&ProtocolToolConstructor,index:usize,negative_zero:bool)->PyResult<usize> {
        let number=data.numbers[index].as_ref().unwrap();let number=number.to_i128().ok_or_else(||pyerr("OverflowError","Python int too large to convert to index"))?;
        if number<0 {if negative_zero{return Ok(0);}let message=match data.name.as_str(){"tee"=>"n must be >= 0","product"=>"repeat argument cannot be negative","combinations"|"combinations_with_replacement"=>"r must be non-negative",_=>"argument must be non-negative"};return Err(pyerr("ValueError",message));}
        usize::try_from(number).ok().filter(|number|*number<=isize::MAX as usize).ok_or_else(||pyerr("OverflowError","Python int too large to convert to index"))
    }
    fn protocol_stream_tools_numeric_done(&mut self,state:&mut ProtocolState,mut data:ProtocolToolConstructor)->PyResult<()> {
        match data.name.as_str(){
            "tee"=>{let count=Self::protocol_stream_tools_number(&data,0,false)?;if count==0{state.value=Some(self.obj_value(Object::Tuple(Vec::new())));return Ok(());}},
            "product"=>{if Self::protocol_stream_tools_number(&data,0,false)?==0{data.inputs.clear();}},
            "batched"=>{if data.numbers[0].as_ref().unwrap().to_i128().is_some_and(|number|number<=0){return Err(pyerr("ValueError","n must be at least one"));}},
            "islice"=>{if data.numeric_error.is_some()||data.numbers[2].as_ref().is_some_and(|number|number.to_i128().is_none_or(|number|number<=0||number>isize::MAX as i128)){return Err(Self::protocol_stream_tools_index_error("step"));}},
            _=>{},
        }
        self.protocol_stream_tools_input(state,data)
    }
    fn protocol_stream_tools_input(&mut self,state:&mut ProtocolState,mut data:ProtocolToolConstructor)->PyResult<()> {
        if data.position<data.inputs.len(){let value=data.inputs[data.position].clone();data.position+=1;self.protocol_stream_queue(state,ProtocolStream::ToolConstructor{data,phase:3},Value::None);self.protocol_stream_plan(state,Value::Builtin("iter".into()),vec![value]);return Ok(());}
        self.protocol_stream_tools_finish(state,data)
    }
    fn protocol_stream_tools_constructor_result(&mut self,state:&mut ProtocolState,mut data:ProtocolToolConstructor,phase:u8,value:Option<Value>,error:Option<PyException>)->PyResult<()> {
        match phase {
            1=>{if let Some(value)=value{
                let number=self.protocol_primitive_int(&value).ok_or_else(||pyerr("TypeError","integer argument expected"))?;
                if data.name!="islice"&&number.to_i128().is_none_or(|number|number<isize::MIN as i128||number>isize::MAX as i128){return Err(pyerr("OverflowError","Python int too large to convert to C ssize_t"));}
                data.numbers.push(Some(number));
            }else{data.numbers.push(None);if data.numeric_error.is_none(){data.numeric_error=error;data.numeric_error_position=data.numeric_position-1;}}self.protocol_stream_tools_numeric(state,data)?;},
            2=>{data.strict=matches!(value,Some(Value::Bool(true)));self.protocol_stream_tools_numeric_done(state,data)?;},
            3=>{
                let iterator=value.unwrap();data.iters.push(iterator.clone());
                if data.pool(){data.pools.push(Vec::new());self.protocol_stream_queue(state,ProtocolStream::ToolConstructor{data,phase:4},Value::None);self.protocol_stream_inner_next(state,iterator);}
                else{self.protocol_stream_tools_input(state,data)?;}
            },
            4=>{if let Some(value)=value{data.pools.last_mut().unwrap().push(value);let iterator=data.iters.last().unwrap().clone();self.protocol_stream_queue(state,ProtocolStream::ToolConstructor{data,phase:4},Value::None);self.protocol_stream_inner_next(state,iterator);}else{self.protocol_stream_tools_input(state,data)?;}},
            _=>unreachable!(),
        }
        Ok(())
    }
    fn protocol_stream_tools_finish(&mut self,state:&mut ProtocolState,mut data:ProtocolToolConstructor)->PyResult<()> {
        let arg=|index:usize|data.bound[index].clone().unwrap_or(Value::None);
        let tool=match data.name.as_str(){
            "accumulate"=>ToolsState::Accumulate{iter:data.iters.remove(0),function:arg(1),total:None,initial:data.bound[2].clone().filter(|value|!matches!(value,Value::None)),started:false},
            "batched"=>ToolsState::Batched{iter:data.iters.remove(0),size:Self::protocol_stream_tools_number(&data,0,false)?,strict:data.strict},
            "chain.from_iterable"=>ToolsState::Chain{outer:data.iters.remove(0),inner:None,done:false},
            "compress"=>ToolsState::Compress{data:data.iters.remove(0),selectors:data.iters.remove(0)},
            "cycle"=>ToolsState::Cycle{iter:Some(data.iters.remove(0)),cache:Vec::new(),index:0},
            "dropwhile"=>ToolsState::DropWhile{predicate:arg(0),iter:data.iters.remove(0),dropping:true},
            "filterfalse"=>ToolsState::FilterFalse{predicate:arg(0),iter:data.iters.remove(0)},
            "takewhile"=>ToolsState::TakeWhile{predicate:arg(0),iter:data.iters.remove(0),done:false},
            "groupby"=>ToolsState::GroupBy(std::rc::Rc::new(std::cell::RefCell::new(ToolsGroup{iter:data.iters.remove(0),function:arg(1),current:None,consumed:false,active_key:None,generation:0,exhausted:false}))),
            "islice"=>{let start=data.numbers[0].as_ref().map(|number|number.to_usize().unwrap()).unwrap_or(0);let stop=data.numbers[1].as_ref().map(|number|number.to_usize().unwrap());let step=data.numbers[2].as_ref().map(|number|number.to_usize().unwrap()).unwrap_or(1);ToolsState::ISlice{iter:data.iters.remove(0),start,stop,step,index:0,target:start,done:false}},
            "pairwise"=>ToolsState::Pairwise{iter:data.iters.remove(0),previous:None},
            "starmap"=>ToolsState::StarMap{function:arg(0),iter:data.iters.remove(0)},
            "zip_longest"=>{let active=data.iters.len();ToolsState::ZipLongest{iters:data.iters.into_iter().map(Some).collect(),fill:arg(0),active}},
            "combinations"|"combinations_with_replacement"=>{let size=Self::protocol_stream_tools_number(&data,0,false)?;let replacement=data.name=="combinations_with_replacement";let pool=data.pools.remove(0);let done=if replacement{pool.is_empty()&&size!=0}else{size>pool.len()};let indices=if done{Vec::new()}else if replacement{vec![0;size]}else{(0..size).collect()};ToolsState::Combinations{pool,indices,size,replacement,started:false,done}},
            "permutations"=>{let pool=data.pools.remove(0);let size=if let Some(value)=data.bound[1].as_ref().filter(|value|!matches!(value,Value::None)){let number=self.protocol_primitive_int(value).ok_or_else(||pyerr("TypeError","Expected int as r"))?;let number=number.to_i128().ok_or_else(||pyerr("OverflowError","Python int too large to convert to index"))?;if number<0{return Err(pyerr("ValueError","r must be non-negative"));}usize::try_from(number).map_err(|_|pyerr("OverflowError","Python int too large to convert to index"))?}else{pool.len()};let done=size>pool.len();let indices=(0..pool.len()).collect();let cycles=if done{Vec::new()}else{(0..size).map(|index|pool.len()-index).collect()};ToolsState::Permutations{pool,indices,cycles,size,started:false,done}},
            "product"=>{let repeat=Self::protocol_stream_tools_number(&data,0,false)?;let count=data.pools.len().checked_mul(repeat).ok_or_else(||pyerr("OverflowError","repeat argument is too large"))?;let mut pools=Vec::new();pools.try_reserve(count).map_err(|_|pyerr("MemoryError","cannot allocate product pools"))?;for _ in 0..repeat{pools.extend(data.pools.iter().cloned());}let done=pools.iter().any(Vec::is_empty);let indices=vec![0;pools.len()];ToolsState::Product{pools,indices,started:false,done}},
            "repeat"=>ToolsState::Repeat{value:arg(0),remaining:if data.numbers.is_empty(){None}else{Some(Self::protocol_stream_tools_number(&data,0,true)?)}},
            "tee"=>{
                let count=Self::protocol_stream_tools_number(&data,0,false)?;let source=data.iters.remove(0);
                let existing=if let Value::Obj(index)=&source{match self.object(*index)?{Object::Iterator(IteratorState::Tools(tool))=>if let ToolsState::Tee{shared,cursor}=*tool{Some((shared,cursor.get()))}else{None},_=>None}}else{None};
                let (shared,position)=existing.unwrap_or_else(||(std::rc::Rc::new(std::cell::RefCell::new(ToolsTee{iter:source,buffer:std::collections::VecDeque::new(),base:0,cursors:Vec::new(),exhausted:false,running:false})),0));
                let mut tees=Vec::new();tees.try_reserve(count).map_err(|_|pyerr("MemoryError","cannot allocate tee iterators"))?;
                for _ in 0..count{let cursor=std::rc::Rc::new(std::cell::Cell::new(position));shared.borrow_mut().cursors.push(std::rc::Rc::downgrade(&cursor));tees.push(self.tools_iterator(ToolsState::Tee{shared:shared.clone(),cursor}));}state.value=Some(self.obj_value(Object::Tuple(tees)));return Ok(());
            },
            _=>unreachable!(),
        };
        state.value=Some(self.tools_iterator(tool));Ok(())
    }
}
