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
        if !kwargs.is_empty(){return Err(pyerr("TypeError","input() takes no keyword arguments"));}
        if args.len()>1{return Err(pyerr("TypeError",format!("input expected at most 1 argument, got {}",args.len())));}
        if let Some(prompt)=args.first(){let text=self.str_value(prompt)?;self.output.push_str(&text);}
        self.flush_stdout()?;
        let line=self.stream_call("stdin:readline",Vec::new(),Vec::new(),false)?;
        match line {
            Value::Str(line) if line.is_empty()=>Err(pyerr("EOFError","EOF when reading a line")),
            Value::Str(line)=>Ok(Value::Str(line.strip_suffix('\n').unwrap_or(&line).into())),
            _=>unreachable!(),
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
