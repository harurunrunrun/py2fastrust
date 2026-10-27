// Generator next resumes through the same heap-frame scheduler as Python calls.
impl Runtime {
    fn protocol_generator_next(&mut self,state:&mut ProtocolState,iterator:Value)->PyResult<bool> {
        if !matches!(&iterator,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Generator(_)))){return Ok(false);}
        state.plan=Some(ProtocolPlan{function:Value::Builtin("$protocol:generator_next".into()),args:vec![iterator],kwargs:Vec::new()});Ok(true)
    }
    fn protocol_generator_frame(&mut self,iterator:Value)->PyResult<Frame> {
        let Value::Obj(index)=iterator else{return Err(pyerr("TypeError","expected generator"))};
        let Object::Generator(mut frame)=self.object(index)?else{return Err(pyerr("TypeError","expected generator"))};
        if frame.pc==usize::MAX{return Err(self.iterator_stop(&Value::Obj(index))?);}
        if self.running_generators.contains(&index){return Err(pyerr("ValueError","generator already executing"));}
        if self.recursion>=self.recursion_limit{return Err(pyerr("RecursionError","maximum recursion depth exceeded"));}
        if frame.pc>0&&matches!(self.codes[frame.code].ops.get(frame.pc-1).map(|instruction|&instruction.op),Some(Op::Yield)) {
            frame.stack.push(frame.resume_value.take().unwrap_or(Value::None));
        }
        frame.protocol_generator=Some(index);Ok(*frame)
    }
    fn protocol_generator_finished(&mut self,frame:&mut Frame)->Option<usize> {
        let owner=frame.protocol_generator.take()?;
        if let Some(position)=self.running_generators.iter().rposition(|index|*index==owner){self.running_generators.remove(position);}
        Some(owner)
    }
    fn start_protocol_yield_from(&mut self,frame:&mut Frame,iterator:Value)->PyResult<bool> {
        if frame.injected_exception.is_some()||frame.resume_value.as_ref().is_some_and(|value|!matches!(value,Value::None)){return Ok(false);}
        let mut state=Self::protocol_empty(ProtocolSink::YieldFrom{finished:None});
        if !self.protocol_next_into(&mut state,iterator,None,true)? {return Ok(false);}
        frame.resume_value=None;frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
}
