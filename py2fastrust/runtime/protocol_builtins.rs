// Built-in protocol callbacks share the caller's heap continuation. Validators
// run after callback return, preserving the caller's exception-handler scope.
// Implemented independently from Python 3.14 documentation and behavior probes.
impl Runtime {
    fn protocol_extra_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let Value::Builtin(name)=&plan.function else{return Ok(false)};
        if !["hash","repr","str","iter"].contains(&name.as_str()) {return Ok(false);}
        let value=if name=="str" {
            // Encoding/decoding remains with the codec path; its callbacks have
            // a different protocol from the one-argument string conversion.
            if plan.args.len()>1 || plan.kwargs.iter().any(|(name,_)|name=="encoding"||name=="errors") {return Ok(false);}
            let mut values=codec_bind("str",plan.args.clone(),plan.kwargs.clone(),&["object","encoding","errors"])?;
            match values[0].take() {Some(value)=>value,None=>return Ok(false)}
        }else{
            if name=="iter" && plan.args.len()==2 && plan.kwargs.is_empty() {return Ok(false);}
            if plan.args.len()!=1 || !plan.kwargs.is_empty() {return Err(pyerr("TypeError",format!("{name}() takes exactly one positional argument")));}
            plan.args[0].clone()
        };
        match name.as_str() {
            "hash"=>{
                if let Some((method,class))=self.protocol_slot(&value,"__hash__") {
                    if matches!(method,Value::None) {return Err(pyerr("TypeError",format!("unhashable type: '{}'",self.typename(&value))));}
                    self.protocol_bind_recover(state,method,value.clone(),class,Vec::new(),Vec::new(),ProtocolAction::HashResult,Some(ProtocolBindingRecovery::Hash(value)))?;
                    return Ok(true);
                }
            },
            "repr"=>return self.protocol_python_repr(state,value,"__repr__"),
            "str"=>{
                if let Some((method,class))=self.protocol_slot(&value,"__str__") {
                    self.protocol_bind_recover(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::StringResult("__str__".into()),None)?;
                    return Ok(true);
                }
                // object.__str__ invokes the selected __repr__ slot. Retain a
                // returned str subclass as a Value instead of copying its text.
                if let Some(class)=self.object_class(&value) {
                    let object_str=matches!(self.slot_definition(&class,"__str__",0),Some(SlotDefinition::Native(ref descriptor))if matches!(native_attribute_parts(descriptor),Some((_,"object","__str__"))));
                    if object_str {return self.protocol_python_repr(state,value,"__str__");}
                }
            },
            "iter"=>{
                if let Some((method,class))=self.protocol_slot(&value,"__iter__") {
                    if matches!(method,Value::None) {return Err(pyerr("TypeError",format!("'{}' object is not iterable",self.typename(&value))));}
                    self.protocol_bind_recover(state,method,value.clone(),class,Vec::new(),Vec::new(),ProtocolAction::IteratorResult,Some(ProtocolBindingRecovery::Iter(value)))?;
                    return Ok(true);
                }
            },
            _=>{},
        }
        Ok(false)
    }

    fn protocol_python_repr(&mut self,state:&mut ProtocolState,value:Value,validator:&str)->PyResult<bool> {
        if let Some((method,class))=self.protocol_slot(&value,"__repr__") {
            self.protocol_bind_recover(state,method,value.clone(),class,Vec::new(),Vec::new(),ProtocolAction::StringResult(validator.into()),Some(ProtocolBindingRecovery::Repr(value)))?;
            return Ok(true);
        }
        Ok(false)
    }

    fn protocol_hash_result(&mut self,value:Value)->PyResult<Value> {
        let number=self.protocol_primitive_int(&value).ok_or_else(||pyerr("TypeError","__hash__ method should return an integer"))?;
        let hash=number.to_i128().filter(|value|*value>=i64::MIN as i128&&*value<=i64::MAX as i128).map(|value|value as i64).unwrap_or_else(||numeric_int_hash(&number));
        Ok(Value::Int(Int::from_i128(if hash == -1 {-2}else{hash as i128}).into()))
    }

    fn protocol_string_result(&mut self,value:Value,method:&str)->PyResult<Value> {
        if matches!(value,Value::Str(_)) || matches!(self.native_payload(&value),Some(Value::Str(_))) {return Ok(value);}
        Err(pyerr("TypeError",format!("{method} returned non-string (type {})",self.typename(&value))))
    }

    fn protocol_iterator_result(&mut self,value:Value)->PyResult<Value> {
        if matches!(&value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Iterator(_)|Object::Generator(_)))) ||
            matches!(&value,Value::Builtin(name)if name.starts_with("stream:")||name.starts_with("streambuffer:")) ||
            self.object_class(&value).is_some_and(|class|self.slot_definition(&class,"__next__",0).is_some()) {
            return Ok(value);
        }
        Err(pyerr("TypeError",format!("iter() returned non-iterator of type '{}'",self.typename(&value))))
    }

    fn protocol_recover_builtin_binding(&mut self,state:&mut ProtocolState,recovery:ProtocolBindingRecovery)->PyResult<bool> {
        match recovery {
            ProtocolBindingRecovery::Hash(value)=>Err(pyerr("TypeError",format!("unhashable type: '{}'",self.typename(&value)))),
            ProtocolBindingRecovery::Repr(value)=>{
                // A failing __repr__ descriptor selects the plain object
                // representation, including for subclasses with native data.
                state.value=Some(Value::Str(format!("<{} object>",self.typename(&value)).into()));
                Ok(true)
            },
            ProtocolBindingRecovery::Iter(value)=>{
                if self.object_class(&value).is_some_and(|class|self.slot_definition(&class,"__getitem__",0).is_some()) {
                    state.value=Some(self.obj_value(Object::Iterator(IteratorState::Reversed(value,-2))));
                    return Ok(true);
                }
                Err(pyerr("TypeError",format!("'{}' object is not iterable",self.typename(&value))))
            },
            ProtocolBindingRecovery::Contains(owner,key)=>{
                state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::IterateContains{iterator:Value::None,key,phase:0,reverse:false,current:None})));
                state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![owner],kwargs:Vec::new()});Ok(true)
            },
            _=>Ok(false),
        }
    }
}
