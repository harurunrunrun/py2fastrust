// input() captures the three current sys streams before any Python callback.
// Every lookup/conversion/call resumes in the initiating Python frame, so a
// recursive readline, prompt, descriptor or flush does not grow the Rust stack.
#[derive(Clone, Copy, Debug)]
enum ProtocolInputPhase {
    ErrorFlushLookup, ErrorFlushed, InputFdLookup, InputFd, InputFdNumber,
    OutputFdLookup, OutputFd, OutputFdNumber,
    InputEncoding, InputErrors, TerminalFlushLookup, TerminalFlushed,
    OutputEncoding, OutputErrors, TerminalPrompt,
    WriteLookup, PromptText, Wrote, FlushLookup, Flushed, ReadLookup, Read,
}
#[derive(Clone, Debug)]
struct ProtocolInput {
    input:Value, output:Value, error:Value, prompt:Option<Value>,
    phase:ProtocolInputPhase, write:Option<Value>,
    input_encoding:Option<Value>, input_errors:Option<Value>,
    output_encoding:Option<Value>, output_errors:Option<Value>,
}
impl ProtocolInput {
    fn roots(&self,out:&mut Vec<Value>) {
        out.extend([self.input.clone(),self.output.clone(),self.error.clone()]);
        for value in [&self.prompt,&self.write,&self.input_encoding,&self.input_errors,&self.output_encoding,&self.output_errors] {out.extend(value.iter().cloned());}
    }
    fn ignores_failure(&self)->bool {
        use ProtocolInputPhase::*;
        matches!(self.phase,ErrorFlushLookup|ErrorFlushed|InputFdLookup|InputFd|OutputFdLookup|OutputFd|InputEncoding|InputErrors|OutputEncoding|OutputErrors|TerminalFlushLookup|TerminalFlushed|FlushLookup|Flushed)
    }
}
impl Runtime {
    fn protocol_input_stream(&mut self,name:&str)->PyResult<Value> {
        let Value::Obj(module)=self.import_module("sys")? else{unreachable!()};
        let Object::Module{attrs,..}=self.object(module)? else{unreachable!()};
        self.global_name_get(attrs,name)?.filter(|value|!matches!(value,Value::None)).ok_or_else(||pyerr("RuntimeError",format!("lost sys.{name}")))
    }
    fn protocol_input_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        if !matches!(&plan.function,Value::Builtin(name)if name=="input") {return Ok(false);}
        if !plan.kwargs.is_empty(){return Err(pyerr("TypeError","input() takes no keyword arguments"));}
        if plan.args.len()>1{return Err(pyerr("TypeError",format!("input expected at most 1 argument, got {}",plan.args.len())));}
        let input=self.protocol_input_stream("stdin")?;
        let output=self.protocol_input_stream("stdout")?;
        let error=self.protocol_input_stream("stderr")?;
        let data=ProtocolInput{input,output,error:error.clone(),prompt:plan.args.first().cloned(),phase:ProtocolInputPhase::ErrorFlushLookup,write:None,input_encoding:None,input_errors:None,output_encoding:None,output_errors:None};
        self.protocol_input_lookup(state,data,ProtocolInputPhase::ErrorFlushLookup,error,"flush");
        Ok(true)
    }
    fn protocol_input_lookup(&mut self,state:&mut ProtocolState,mut data:ProtocolInput,phase:ProtocolInputPhase,object:Value,name:&str) {
        data.phase=phase;state.actions.push_front(ProtocolAction::Input(Box::new(data)));
        state.plan=Some(ProtocolPlan{function:Value::Builtin("getattr".into()),args:vec![object,Value::Str(name.into())],kwargs:Vec::new()});
    }
    fn protocol_input_call(&mut self,state:&mut ProtocolState,mut data:ProtocolInput,phase:ProtocolInputPhase,function:Value,args:Vec<Value>) {
        data.phase=phase;state.actions.push_front(ProtocolAction::Input(Box::new(data)));
        state.plan=Some(ProtocolPlan{function,args,kwargs:Vec::new()});
    }
    fn protocol_input_fallback(&mut self,state:&mut ProtocolState,mut data:ProtocolInput) {
        // Temporary terminal metadata is released before fallback callbacks.
        data.input_encoding=None;data.input_errors=None;data.output_encoding=None;data.output_errors=None;
        let output=data.output.clone();
        if data.prompt.is_some(){self.protocol_input_lookup(state,data,ProtocolInputPhase::WriteLookup,output,"write");}
        else{self.protocol_input_lookup(state,data,ProtocolInputPhase::FlushLookup,output,"flush");}
    }
    fn protocol_input_fd(&mut self,state:&mut ProtocolState,mut data:ProtocolInput,value:Value,output:bool)->PyResult<()> {
        let phase=if output{ProtocolInputPhase::OutputFdNumber}else{ProtocolInputPhase::InputFdNumber};
        if self.protocol_primitive_int(&value).is_some(){return self.protocol_input_result(state,{data.phase=phase;data},value);}
        if let Some((method,class))=self.protocol_slot(&value,"__index__") {
            data.phase=phase;state.actions.push_front(ProtocolAction::Input(Box::new(data)));
            self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Integer("__index__".into()),false)?;
            return Ok(());
        }
        Err(pyerr("TypeError",format!("'{}' object cannot be interpreted as an integer",self.typename(&value))))
    }
    fn protocol_input_text(&self,value:&Value)->Option<Value> {
        match self.native_payload(value).unwrap_or_else(||value.clone()) {value@Value::Str(_)=>Some(value),_=>None}
    }
    fn protocol_input_terminal_read(&mut self,state:&mut ProtocolState,data:ProtocolInput,prompt:Option<Value>)->PyResult<()> {
        if let Some(prompt)=prompt {
            let prompt=self.protocol_input_text(&prompt).ok_or_else(||pyerr("TypeError","input prompt conversion returned non-string"))?;
            let Value::Bytes(bytes)=self.codec_encode(prompt,vec![data.output_encoding.clone().unwrap(),data.output_errors.clone().unwrap()],Vec::new())? else{unreachable!()};
            if bytes.contains(&0){return Err(pyerr("ValueError","input: prompt string cannot contain null characters"));}
            // CPython's portable terminal reader displays the prompt on the
            // real stderr; replacement stdout.write is never called here.
            let _=self.flush_stdout();
            std::io::stderr().write_all(&bytes).map_err(|error|pyerr("OSError",error.to_string()))?;
            std::io::stderr().flush().map_err(|error|pyerr("OSError",error.to_string()))?;
        } else {let _=self.flush_stdout();}
        let mut bytes=self.input.read_binary(None,true).map_err(standard_input_exception)?;
        if bytes.is_empty(){return Err(pyerr("EOFError",""));}
        // The portable terminal reader keeps the same trailing LF/CR rule as
        // the interactive builtin. Nonterminal readline only removes one LF.
        if bytes.last()==Some(&b'\n'){bytes.pop();if bytes.last()==Some(&b'\r'){bytes.pop();}}
        state.value=Some(self.codec_decode(Value::Bytes(bytes.into()),vec![data.input_encoding.unwrap(),data.input_errors.unwrap()],Vec::new())?);
        Ok(())
    }
    fn protocol_input_result(&mut self,state:&mut ProtocolState,mut data:ProtocolInput,value:Value)->PyResult<()> {
        use ProtocolInputPhase::*;
        match data.phase {
            ErrorFlushLookup=>self.protocol_input_call(state,data,ErrorFlushed,value,Vec::new()),
            ErrorFlushed=>{let input=data.input.clone();self.protocol_input_lookup(state,data,InputFdLookup,input,"fileno");},
            InputFdLookup=>self.protocol_input_call(state,data,InputFd,value,Vec::new()),
            InputFd=>self.protocol_input_fd(state,data,value,false)?,
            OutputFdLookup=>self.protocol_input_call(state,data,OutputFd,value,Vec::new()),
            OutputFd=>self.protocol_input_fd(state,data,value,true)?,
            InputFdNumber|OutputFdNumber=>{
                use std::io::IsTerminal;
                let number=self.protocol_primitive_int(&value).ok_or_else(||pyerr("TypeError","fileno result is not an integer"))?;
                let number=number.to_i128().and_then(|number|std::os::raw::c_long::try_from(number).ok()).ok_or_else(||pyerr("OverflowError","Python int too large to convert to C long"))?;
                if matches!(data.phase,InputFdNumber) && number==0 && std::io::stdin().is_terminal(){let output=data.output.clone();self.protocol_input_lookup(state,data,OutputFdLookup,output,"fileno");}
                else if matches!(data.phase,OutputFdNumber) && number==1 && std::io::stdout().is_terminal(){let input=data.input.clone();self.protocol_input_lookup(state,data,InputEncoding,input,"encoding");}
                else{self.protocol_input_fallback(state,data);}
            },
            InputEncoding|InputErrors|OutputEncoding|OutputErrors=>{
                // CPython fetches both metadata attributes before validating
                // either type; descriptors on errors retain that side effect.
                if matches!(data.phase,InputErrors|OutputErrors) {
                    let encoding=if matches!(data.phase,InputErrors){data.input_encoding.as_ref().unwrap()}else{data.output_encoding.as_ref().unwrap()};
                    if self.protocol_input_text(encoding).is_none() || self.protocol_input_text(&value).is_none(){self.protocol_input_fallback(state,data);return Ok(());}
                }
                match data.phase {
                    InputEncoding=>{data.input_encoding=Some(value);let input=data.input.clone();self.protocol_input_lookup(state,data,InputErrors,input,"errors");},
                    InputErrors=>{data.input_errors=Some(value);let output=data.output.clone();self.protocol_input_lookup(state,data,TerminalFlushLookup,output,"flush");},
                    OutputEncoding=>{data.output_encoding=Some(value);let output=data.output.clone();self.protocol_input_lookup(state,data,OutputErrors,output,"errors");},
                    OutputErrors=>{data.output_errors=Some(value);let prompt=data.prompt.clone().unwrap();self.protocol_input_call(state,data,TerminalPrompt,Value::Builtin("str".into()),vec![prompt]);},
                    _=>unreachable!(),
                }
            },
            TerminalFlushLookup=>self.protocol_input_call(state,data,TerminalFlushed,value,Vec::new()),
            TerminalFlushed=>{
                if data.prompt.is_some(){let output=data.output.clone();self.protocol_input_lookup(state,data,OutputEncoding,output,"encoding");}
                else{self.protocol_input_terminal_read(state,data,None)?;}
            },
            TerminalPrompt=>self.protocol_input_terminal_read(state,data,Some(value))?,
            WriteLookup=>{data.write=Some(value);let prompt=data.prompt.clone().unwrap();self.protocol_input_call(state,data,PromptText,Value::Builtin("str".into()),vec![prompt]);},
            PromptText=>{let write=data.write.take().unwrap();self.protocol_input_call(state,data,Wrote,write,vec![value]);},
            Wrote=>{let output=data.output.clone();self.protocol_input_lookup(state,data,FlushLookup,output,"flush");},
            FlushLookup=>self.protocol_input_call(state,data,Flushed,value,Vec::new()),
            Flushed=>{let input=data.input.clone();self.protocol_input_lookup(state,data,ReadLookup,input,"readline");},
            ReadLookup=>self.protocol_input_call(state,data,Read,value,Vec::new()),
            Read=>{
                let payload=self.native_payload(&value).unwrap_or_else(||value.clone());
                state.value=Some(match payload {
                    Value::Str(line)=>{
                        if line.is_empty(){return Err(pyerr("EOFError","EOF when reading a line"));}
                        if let Some(text)=line.strip_suffix('\n'){Value::Str(text.into())}else{value}
                    },
                    Value::Bytes(line)=>{
                        if line.is_empty(){return Err(pyerr("EOFError","EOF when reading a line"));}
                        if line.last()==Some(&b'\n'){Value::Bytes(line[..line.len()-1].to_vec().into())}else{value}
                    },
                    _=>return Err(pyerr("TypeError","object.readline() returned non-string")),
                });
            },
        }
        Ok(())
    }
    fn protocol_input_recover_before(&mut self,state:&mut ProtocolState,error:&PyException)->PyResult<bool> {
        let Some(mut boundary)=state.actions.iter().position(|action|matches!(action,ProtocolAction::Input(data)if data.ignores_failure()))else{return Ok(false)};
        let attribute=self.exception_has_native_class(error,"AttributeError");
        // A failing getattr inside a flush/fileno may still have __getattr__
        // or an explicit default. Resolve that inner operation first, before
        // either suppressing input's error or consulting an outer consumer.
        if attribute && state.attribute_recovery.is_some() && state.actions.iter().take(boundary).any(|action|matches!(action,ProtocolAction::AttributeDone)) {
            if self.protocol_attribute_failure(state)? {return Ok(true);}
            boundary=state.actions.iter().position(|action|matches!(action,ProtocolAction::Input(data)if data.ignores_failure())).unwrap();
        }
        let stop=self.exception_has_native_class(error,"StopIteration");
        let index=self.exception_has_native_class(error,"IndexError");
        let type_error=self.exception_has_native_class(error,"TypeError");
        let inner=state.actions.iter().take(boundary).any(|action|match action {
            ProtocolAction::Consumer(record)=>type_error && record.phase==2,
            ProtocolAction::Stream(record)=>match record.as_ref() {
                ProtocolStream::ToolConstructor{data,phase:1} if data.name=="islice"=>true,
                ProtocolStream::SequenceItem{..}=>stop||index,
                ProtocolStream::NextBoundary{..}|ProtocolStream::CallableValue{..}|ProtocolStream::Tool{fetch:true,..}|ProtocolStream::Collect{strict:true,position:1..,..}|ProtocolStream::StrictProbe{..}|ProtocolStream::ToolConstructor{phase:4,..}=>stop,
                _=>false,
            },
            ProtocolAction::EndBinding(_)|ProtocolAction::StringResult(_)|ProtocolAction::StrictBool|ProtocolAction::HashResult|ProtocolAction::IteratorResult|ProtocolAction::Operand(_)|ProtocolAction::ContainsResult=>attribute && state.binding_recovery.is_some(),
            _=>false,
        });
        if inner{return Ok(false);}
        self.protocol_input_failure(state,error)
    }
    fn protocol_input_failure(&mut self,state:&mut ProtocolState,_error:&PyException)->PyResult<bool> {
        // Lookups may have queued descriptor-binding actions ahead of this
        // boundary. Clear those only after their own recovery has declined.
        let Some(position)=state.actions.iter().position(|action|matches!(action,ProtocolAction::Input(data)if data.ignores_failure()))else{return Ok(false)};
        let ProtocolAction::Input(data)=self.protocol_discard_actions(state,position+1).pop().unwrap()else{unreachable!()};
        state.plan=None;state.value=None;state.binding_recovery=None;state.attribute_recovery=None;
        self.protocol_sync_repr_guards(state);
        use ProtocolInputPhase::*;
        match data.phase {
            ErrorFlushLookup|ErrorFlushed=>{let input=data.input.clone();self.protocol_input_lookup(state,*data,InputFdLookup,input,"fileno");},
            TerminalFlushLookup|TerminalFlushed=>self.protocol_input_result(state,{let mut data=*data;data.phase=TerminalFlushed;data},Value::None)?,
            FlushLookup|Flushed=>{let input=data.input.clone();self.protocol_input_lookup(state,*data,ReadLookup,input,"readline");},
            _=>self.protocol_input_fallback(state,*data),
        }
        Ok(true)
    }
}
