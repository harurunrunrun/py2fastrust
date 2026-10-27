// Python standard-stream calls. The byte reader itself is shared with native AOT.
impl Runtime {
    fn flush_stdout(&mut self)->PyResult<()> {
        let mut stdout=std::io::stdout().lock();
        stdout.write_all(self.output.as_bytes()).map_err(|error|pyerr("OSError",error.to_string()))?;
        self.output.clear();
        stdout.flush().map_err(|error|pyerr("OSError",error.to_string()))
    }
    fn print_piece(&mut self,file:Option<&Value>,value:Value)->PyResult<()> {
        if let Some(file)=file {
            let write=self.getattr(file.clone(),"write")?;
            self.view_rooted(vec![file.clone(),write.clone(),value.clone()],|runtime,_|{
                let text=runtime.str_value(&value)?;
                runtime.call(write,vec![Value::Str(text.into())],Vec::new(),None)?;
                Ok(())
            })
        } else {
            let text=self.str_value(&value)?;
            self.output.push_str(&text);
            Ok(())
        }
    }
    fn print_values(&mut self,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<Value> {
        const PARAMETERS:[&str;4]=["sep","end","file","flush"];
        for (name,_) in &kwargs {if !PARAMETERS.contains(&name.as_str()) {self.execution_unknown_keyword("print",name,&PARAMETERS)?;}}
        let get=|name:&str|kwargs.iter().find(|(key,_)|key==name).map(|(_,value)|value.clone());
        // The bool converter belongs to argument parsing, before sep/end checks.
        let flush=match get("flush"){Some(value)=>self.truth(&value)?,None=>false};
        let sep=get("sep").filter(|value|!matches!(value,Value::None)).unwrap_or_else(||Value::Str(" ".into()));
        let end=get("end").filter(|value|!matches!(value,Value::None)).unwrap_or_else(||Value::Str("\n".into()));
        for (name,value) in [("sep",&sep),("end",&end)] {
            if !matches!(self.native_payload(value).unwrap_or_else(||value.clone()),Value::Str(_)) {
                return Err(pyerr("TypeError",format!("{name} must be None or a string, not {}",self.typename(value))));
            }
        }
        let file=get("file").filter(|value|!matches!(value,Value::None));
        for (index,value) in args.into_iter().enumerate() {
            if index!=0{self.print_piece(file.as_ref(),sep.clone())?;}
            self.print_piece(file.as_ref(),value)?;
        }
        self.print_piece(file.as_ref(),end)?;
        if flush {
            if let Some(file)=file {let method=self.getattr(file,"flush")?;self.call(method,Vec::new(),Vec::new(),None)?;}
            else {self.flush_stdout()?;}
        }
        Ok(Value::None)
    }
    fn input_value(&mut self,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<Value> {
        // Calls from Python bytecode use the initiating frame's coordinator.
        // Internal native consumers have no such frame: keep the same state
        // machine and root each suspended operation while execute drives any
        // callback through its ordinary heap-frame trampoline.
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        self.protocol_input_builtin(&mut state,&ProtocolPlan{function:Value::Builtin("input".into()),args,kwargs})?;
        loop {
            state.actions.check_budget()?;
            let mut roots=Vec::new();state.roots(&mut roots);
            let turn=self.view_rooted(roots,|runtime,_|runtime.protocol_turn(None,&mut state));
            let outcome=match turn {
                Ok(ProtocolTurn::Continue)=>continue,
                Ok(ProtocolTurn::Done(value))=>{self.protocol_release_repr_guards(&mut state);return Ok(value);},
                Ok(ProtocolTurn::Schedule(child))=>{
                    let mut roots=Vec::new();state.roots(&mut roots);
                    self.view_rooted(roots,|runtime,_|runtime.execute(child)).map(|(value,_)|match value{FrameExit::Return(value)|FrameExit::Yield(value)=>value})
                },
                Err(error)=>Err(error),
            };
            match outcome {
                Ok(value)=>state.value=Some(value),
                Err(error)=>{
                    if self.exception_has_native_class(&error,"AttributeError") && self.protocol_attribute_failure(&mut state)? {continue;}
                    if !self.protocol_input_failure(&mut state,&error)? {self.protocol_release_repr_guards(&mut state);return Err(error);}
                },
            }
        }
    }
    fn stream_size(&mut self,value:&Value)->PyResult<Option<usize>> {
        let payload=self.native_payload(value).unwrap_or_else(||value.clone());
        let value=if matches!(payload,Value::Int(_)|Value::Bool(_)){payload}else{value.clone()};
        let number=self.as_int(&value)?.to_i128().ok_or_else(||pyerr("OverflowError","cannot fit 'int' into an index-sized integer"))?;
        let number=isize::try_from(number).map_err(|_|pyerr("OverflowError","cannot fit 'int' into an index-sized integer"))?;
        Ok(if number<0 {None}else{Some(number as usize)})
    }
}
