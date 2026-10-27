// Iterator consumers retain their partial result in caller-owned heap actions.
#[derive(Clone,Debug)]
struct ProtocolConsumer {mode:String,source:Value,owner:Value,iterator:Option<Value>,values:Vec<Value>,phase:u8}
impl ProtocolConsumer {fn roots(&self,out:&mut Vec<Value>){out.extend([self.source.clone(),self.owner.clone()]);out.extend(self.iterator.iter().cloned());out.extend(self.values.iter().cloned());}}
impl Runtime {
    fn protocol_iterator_length_hint(&self,value:&Value)->Option<Int> {
        let Value::Obj(owner)=value else{return None};
        match self.heap.get(*owner).and_then(Option::as_ref) {
            Some(Object::Iterator(IteratorState::List(owner,position)))=>match self.heap.get(*owner).and_then(Option::as_ref){Some(Object::List(values)|Object::Tuple(values))=>Some(Int::exact_small(values.len().saturating_sub(*position) as i128)),_=>Some(Int::exact_small(0))},
            Some(Object::Iterator(IteratorState::Values(values,position)))=>Some(Int::exact_small(values.len().saturating_sub(*position) as i128)),
            Some(Object::Iterator(IteratorState::Range(start,stop,step)))=>Some(range_length_exact(start,stop,step)),
            _=>None,
        }
    }
    fn protocol_consumer_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let Value::Builtin(function)=&plan.function else{return Ok(false)};
        let method=function.strip_prefix("method:").or_else(||native_attribute_parts(&plan.function).map(|(_,_,name)|name)).or_else(||function.strip_prefix("unbound:").and_then(|name|name.split_once(':').map(|(_,name)|name)));
        let (mode,source,owner)=if let Some(method)=method {
            if !["extend","__iadd__"].contains(&method)||plan.args.len()!=2||!plan.kwargs.is_empty(){return Ok(false);}
            let payload=self.native_payload(&plan.args[0]).unwrap_or_else(||plan.args[0].clone());
            if !matches!(&payload,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::List(_)))){return Ok(false);}
            if method=="__iadd__"{state.actions.push_front(ProtocolAction::Return(plan.args[0].clone()));}
            ("extend".to_owned(),plan.args[1].clone(),plan.args[0].clone())
        }else{
            if !["list","tuple","any","all"].contains(&function.as_str()){return Ok(false);}
            if !plan.kwargs.is_empty()||plan.args.len()>1||(["any","all"].contains(&function.as_str())&&plan.args.is_empty()){return Err(pyerr("TypeError",format!("invalid arguments to {function}")));}
            let source=plan.args.first().cloned().unwrap_or_else(||self.obj_value(Object::Tuple(Vec::new())));
            if function=="tuple"&&matches!(&source,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_)))){state.value=Some(source);return Ok(true);}
            let owner=if function=="list"{self.obj_value(Object::List(Vec::new()))}else{Value::None};(function.to_owned(),source,owner)
        };
        // The exact self-extension fast path cannot observe an overridden iter.
        if mode=="extend"{if let Value::Obj(index)=&source{if let Some(Object::List(items))=self.heap.get(*index).and_then(Option::as_ref){let items=items.clone();let payload=self.native_payload(&owner).unwrap_or_else(||owner.clone());if source.same_identity(&payload){let Value::Obj(index)=payload else{unreachable!()};let Some(Object::List(target))=self.heap[index].as_mut()else{unreachable!()};target.extend(items);self.protocol_sort_nonempty(index);state.value=Some(Value::None);return Ok(true);}}}}
        state.actions.push_front(ProtocolAction::Consumer(Box::new(ProtocolConsumer{mode,source:source.clone(),owner,iterator:None,values:Vec::new(),phase:0})));state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![source],kwargs:Vec::new()});Ok(true)
    }
    fn protocol_consumer_next(&mut self,state:&mut ProtocolState,mut record:ProtocolConsumer) {
        record.phase=5;let iterator=record.iterator.clone().unwrap();state.actions.push_front(ProtocolAction::Consumer(Box::new(record)));state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![iterator,Value::Builtin("$consumer:end".into())],kwargs:Vec::new()});
    }
    fn protocol_consumer_reserve(&mut self,record:&ProtocolConsumer,hint:Option<usize>) {
        if record.mode=="extend" && hint.unwrap_or(8)>0 {
            let payload=self.native_payload(&record.owner).unwrap_or_else(||record.owner.clone());
            if let Value::Obj(owner)=payload{self.protocol_sort_note(owner);}
        }
    }
    fn protocol_consumer_failure(&mut self,state:&mut ProtocolState,error:&PyException)->PyResult<bool>{
        if !self.exception_has_native_class(error,"TypeError"){return Ok(false);}
        let Some(index)=state.actions.iter().position(|action|matches!(action,ProtocolAction::Consumer(record)if record.phase==2))else{return Ok(false)};
        let ProtocolAction::Consumer(mut record)=state.actions.remove(index).unwrap()else{unreachable!()};self.protocol_discard_actions(state,index);state.plan=None;state.value=None;record.phase=3;let source=if record.mode=="tuple"{record.iterator.clone().unwrap()}else{record.source.clone()};state.actions.push_front(ProtocolAction::Consumer(record));state.plan=Some(ProtocolPlan{function:Value::Builtin("getattr".into()),args:vec![source,Value::Str("__length_hint__".into()),Value::Builtin("$consumer:no_hint".into())],kwargs:Vec::new()});Ok(true)
    }
    fn protocol_consumer_result(&mut self,state:&mut ProtocolState,mut record:ProtocolConsumer,value:Value)->PyResult<()> {
        match record.phase {
            0=>{record.iterator=Some(value);if record.mode=="any"||record.mode=="all"{self.protocol_consumer_next(state,record);}else{record.phase=2;let source=if record.mode=="tuple"{record.iterator.clone().unwrap()}else{record.source.clone()};state.actions.push_front(ProtocolAction::Consumer(Box::new(record)));state.plan=Some(ProtocolPlan{function:Value::Builtin("len".into()),args:vec![source],kwargs:Vec::new()});}}
            2=>{let hint=self.as_int(&value)?.to_usize();self.protocol_consumer_reserve(&record,hint);self.protocol_consumer_next(state,record);}
            3=>{if matches!(&value,Value::Builtin(name)if name=="$consumer:no_hint"){self.protocol_consumer_reserve(&record,None);self.protocol_consumer_next(state,record);}else{record.phase=4;state.actions.push_front(ProtocolAction::Consumer(Box::new(record)));state.plan=Some(ProtocolPlan{function:value,args:Vec::new(),kwargs:Vec::new()});}}
            4=>{let hint=if !matches!(&value,Value::Builtin(name)if name=="NotImplemented"){let length=self.protocol_primitive_int(&value).ok_or_else(||pyerr("TypeError","__length_hint__ must be an integer"))?;if length.is_negative(){return Err(pyerr("ValueError","__length_hint__() should return >= 0"));}if length.to_i128().is_none_or(|value|value>isize::MAX as i128){return Err(pyerr("OverflowError","Python int too large to convert to C ssize_t"));}length.to_usize()}else{None};self.protocol_consumer_reserve(&record,hint);self.protocol_consumer_next(state,record);}
            5=>{
                if matches!(&value,Value::Builtin(name)if name=="$consumer:end"){
                    state.value=Some(match record.mode.as_str(){"tuple"=>self.obj_value(Object::Tuple(record.values)),"any"=>Value::Bool(false),"all"=>Value::Bool(true),"extend"=>Value::None,_=>record.owner});return Ok(());
                }
                if record.mode=="any"||record.mode=="all"{record.phase=6;state.actions.push_front(ProtocolAction::Consumer(Box::new(record)));if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}}
                else{if record.mode=="tuple"{record.values.push(value);}else{let payload=self.native_payload(&record.owner).unwrap_or_else(||record.owner.clone());let Value::Obj(index)=payload else{unreachable!()};let Some(Object::List(items))=self.heap[index].as_mut()else{unreachable!()};items.push(value);self.protocol_sort_nonempty(index);}self.protocol_consumer_next(state,record);}
            }
            6=>{let truth=self.truth(&value)?;if truth==(record.mode=="any"){state.value=Some(Value::Bool(truth));}else{self.protocol_consumer_next(state,record);}}
            _=>unreachable!(),
        }Ok(())
    }
}
