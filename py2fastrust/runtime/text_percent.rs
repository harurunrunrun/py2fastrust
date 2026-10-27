// Unicode %-formatting keeps parsing and Python conversions in caller-owned
// heap records. Structural float-to-integer conversion is deliberately exact:
// displaying a float as decimal is not the user-visible int() conversion.
#[derive(Clone,Debug,Default)]
struct TextPercentSpec { kind:char,left:bool,zero:bool,alternate:bool,plus:bool,space:bool,width:usize,precision:Option<usize> }
#[derive(Clone,Debug)]
enum TextPercentPhase { Parse, Mapped, Text, Integer(String), Character, Float(String) }
#[derive(Clone,Debug)]
struct ProtocolTextPercent {
    format:Value, values:Value, source:Vec<char>,position:usize,output:String,
    mapping:bool,arguments:Vec<Value>,cursor:usize,spec:TextPercentSpec,
    phase:TextPercentPhase,original:Option<Value>,identity:Option<Value>,
}
impl ProtocolTextPercent {
    fn roots(&self,out:&mut Vec<Value>) {
        out.extend([self.format.clone(),self.values.clone()]);
        // Positional elements remain owned by the immutable original tuple.
        // A mapped result may be transient and needs its separate strong root.
        if self.mapping{out.extend(self.arguments.iter().cloned());}
        out.extend(self.original.iter().cloned());out.extend(self.identity.iter().cloned());
    }
    fn next_argument(&mut self)->PyResult<Value> {bytes_percent_argument(&self.arguments,&mut self.cursor)}
}
fn text_percent_append(output:&mut String,text:&str)->PyResult<()> {
    output.len().checked_add(text.len()).filter(|n|*n<=isize::MAX as usize).ok_or_else(||pyerr("OverflowError","formatted string is too long"))?;
    output.try_reserve(text.len()).map_err(|_|pyerr("MemoryError","cannot allocate formatted string"))?;output.push_str(text);Ok(())
}
fn text_percent_pad(output:&mut String,character:char,count:usize)->PyResult<()> {
    let bytes=count.checked_mul(character.len_utf8()).ok_or_else(||pyerr("OverflowError","formatted string is too long"))?;
    output.len().checked_add(bytes).filter(|n|*n<=isize::MAX as usize).ok_or_else(||pyerr("OverflowError","formatted string is too long"))?;
    output.try_reserve(bytes).map_err(|_|pyerr("MemoryError","cannot allocate formatted string"))?;
    output.extend(std::iter::repeat(character).take(count));Ok(())
}
impl Runtime {
    fn text_percent_mapping(&self,value:&Value)->bool {
        let payload=self.native_payload(value).unwrap_or_else(||value.clone());
        if matches!(payload,Value::Str(_)){return false;}
        if let Value::Obj(index)=&payload {if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_))){return false;}}
        matches!(payload,Value::Bytes(_)) || self.buffer_kind(&payload)==Some("bytearray") || self.bytes_percent_mapping(value)
    }
    fn protocol_text_percent_start(&mut self,state:&mut ProtocolState,format:Value,values:Value)->PyResult<()> {
        let Value::Str(source)=self.native_payload(&format).unwrap_or_else(||format.clone())else{return Err(pyerr("TypeError","format must be a string"))};
        let payload=self.native_payload(&values).unwrap_or_else(||values.clone());
        let arguments=if let Value::Obj(index)=payload {match self.object(index)?{Object::Tuple(items)=>items,_=>vec![values.clone()]}}else{vec![values.clone()]};
        let mapping=self.text_percent_mapping(&values);
        if !source.contains('%') {
            if !mapping&&!arguments.is_empty(){return Err(pyerr("TypeError","not all arguments converted during string formatting"));}
            state.value=Some(Value::Str(source));return Ok(());
        }
        let data=ProtocolTextPercent{format,values:values.clone(),source:source.chars().collect(),position:0,output:String::new(),mapping,arguments,cursor:0,spec:TextPercentSpec::default(),phase:TextPercentPhase::Parse,original:None,identity:None};
        self.protocol_text_percent_scan(state,data)
    }
    fn protocol_text_percent_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let Some((_,"str",method@("__mod__"|"__rmod__")))=native_attribute_parts(&plan.function)else{return Ok(false)};
        let receiver=plan.args.first().ok_or_else(||pyerr("TypeError",format!("descriptor '{method}' of 'str' object needs an argument")))?;
        self.native_validate_receiver("str",receiver)?;
        if !plan.kwargs.is_empty(){return Err(pyerr("TypeError",format!("wrapper {method}() takes no keyword arguments")));}
        if plan.args.len()!=2{return Err(pyerr("TypeError",format!("expected 1 argument, got {}",plan.args.len()-1)));}
        let (format,values)=if method=="__rmod__"{(plan.args[1].clone(),receiver.clone())}else{(receiver.clone(),plan.args[1].clone())};
        if !matches!(self.native_payload(&format).unwrap_or_else(||format.clone()),Value::Str(_)){state.value=Some(Value::Builtin("NotImplemented".into()));return Ok(true);}
        self.protocol_text_percent_start(state,format,values)?;Ok(true)
    }
    fn protocol_text_percent_queue(&mut self,state:&mut ProtocolState,mut data:ProtocolTextPercent,phase:TextPercentPhase,function:Value,args:Vec<Value>) {
        data.phase=phase;state.actions.push_front(ProtocolAction::TextPercent(Box::new(data)));
        state.plan=Some(ProtocolPlan{function,args,kwargs:Vec::new()});
    }
    fn protocol_text_percent_scan(&mut self,state:&mut ProtocolState,mut data:ProtocolTextPercent)->PyResult<()> {
        while data.position<data.source.len() {
            let start=data.position;
            while data.position<data.source.len() && data.source[data.position]!='%' {data.position+=1;}
            if data.position>start {
                data.identity=None;text_percent_append(&mut data.output,&data.source[start..data.position].iter().collect::<String>())?;
            }
            if data.position==data.source.len(){break;}
            data.position+=1;
            let Some(character)=data.source.get(data.position).copied()else{return Err(pyerr("ValueError","incomplete format"))};
            if character=='%' {data.position+=1;data.identity=None;text_percent_append(&mut data.output,"%")?;continue;}
            data.spec=TextPercentSpec::default();data.original=None;
            if character=='(' {
                if !data.mapping{return Err(pyerr("TypeError","format requires a mapping"));}
                let start=data.position+1;data.position+=1;let mut nesting=1usize;
                while data.position<data.source.len() && nesting!=0 {
                    match data.source[data.position]{'('=>nesting+=1,')'=>nesting-=1,_=>{}};data.position+=1;
                }
                if nesting!=0{return Err(pyerr("ValueError","incomplete format key"));}
                let key=Value::Str(data.source[start..data.position-1].iter().collect());let owner=data.values.clone();
                data.phase=TextPercentPhase::Mapped;state.actions.push_front(ProtocolAction::TextPercent(Box::new(data)));
                if let Some((method,class))=self.protocol_slot(&owner,"__getitem__") {self.protocol_bind(state,method,owner,class,vec![key],Vec::new(),ProtocolAction::Pass,false)?;}
                else if !self.protocol_dict_getitem(state,owner.clone(),key.clone())?{state.value=Some(self.text_percent_mapping_getitem(owner,key)?);}
                return Ok(());
            }
            return self.protocol_text_percent_spec(state,data);
        }
        if !data.mapping && data.cursor<data.arguments.len(){return Err(pyerr("TypeError","not all arguments converted during string formatting"));}
        state.value=Some(data.identity.unwrap_or_else(||Value::Str(data.output.into())));Ok(())
    }
    fn text_percent_mapping_getitem(&mut self,owner:Value,key:Value)->PyResult<Value> {
        let payload=self.native_payload(&owner).unwrap_or_else(||owner.clone());
        let kind=if let Value::Obj(index)=&payload {match self.heap.get(*index).and_then(Option::as_ref){Some(Object::List(_))=>Some("list"),Some(Object::Range(..))=>Some("range"),Some(Object::MemoryView(_))=>Some("memoryview"),_=>None}}else if matches!(payload,Value::Bytes(_)){Some("byte")}else{None};
        let kind=kind.or_else(||if self.buffer_kind(&payload)==Some("bytearray"){Some("bytearray")}else{None});
        if let Some(kind)=kind{return Err(pyerr("TypeError",if kind=="memoryview"{"memoryview: invalid slice key".into()}else{format!("{kind} indices must be integers or slices, not str")}));}
        self.getitem(owner,key)
    }
    fn protocol_text_percent_spec(&mut self,state:&mut ProtocolState,mut data:ProtocolTextPercent)->PyResult<()> {
        while let Some(character)=data.source.get(data.position) {
            match character{'-'=>data.spec.left=true,'0'=>data.spec.zero=true,'#'=>data.spec.alternate=true,'+'=>data.spec.plus=true,' '=>data.spec.space=true,_=>break};data.position+=1;
        }
        if data.source.get(data.position)==Some(&'*') {
            data.position+=1;let value=data.next_argument()?;
            let number=self.protocol_primitive_int(&value).ok_or_else(||pyerr("TypeError","* wants int"))?;
            let number=number.to_i128().filter(|n|isize::try_from(*n).is_ok()).ok_or_else(||pyerr("OverflowError","Python int too large to convert to C ssize_t"))?;
            data.spec.left|=number<0;data.spec.width=if number==isize::MIN as i128{0}else{number.abs()as usize};
        }else{
            while let Some(character@'0'..='9')=data.source.get(data.position) {
                data.spec.width=data.spec.width.checked_mul(10).and_then(|n|n.checked_add((*character as u8-b'0')as usize)).filter(|n|*n<=isize::MAX as usize).ok_or_else(||pyerr("ValueError","width too big"))?;data.position+=1;
            }
        }
        if data.source.get(data.position)==Some(&'.') {
            data.position+=1;let mut precision=0usize;
            if data.source.get(data.position)==Some(&'*') {
                data.position+=1;let value=data.next_argument()?;
                let number=self.protocol_primitive_int(&value).ok_or_else(||pyerr("TypeError","* wants int"))?;
                precision=number.to_i128().filter(|n|i32::try_from(*n).is_ok()).ok_or_else(||pyerr("OverflowError","Python int too large to convert to C int"))?.max(0)as usize;
            }else{
                while let Some(character@'0'..='9')=data.source.get(data.position) {
                    precision=precision.checked_mul(10).and_then(|n|n.checked_add((*character as u8-b'0')as usize)).filter(|n|*n<=i32::MAX as usize).ok_or_else(||pyerr("ValueError","precision too big"))?;data.position+=1;
                }
            }
            data.spec.precision=Some(precision);
        }
        if data.source.get(data.position).is_some_and(|character|matches!(character,'h'|'l'|'L')){data.position+=1;}
        data.spec.kind=*data.source.get(data.position).ok_or_else(||pyerr("ValueError","incomplete format"))?;data.position+=1;
        let value=data.next_argument()?;data.original=Some(value.clone());
        let kind=data.spec.kind;
        match kind {
            's'|'r'|'a'=>self.protocol_text_percent_queue(state,data,TextPercentPhase::Text,Value::Builtin(match kind{'s'=>"str",'r'=>"repr",_=>"ascii"}.into()),vec![value]),
            'd'|'i'|'u'|'o'|'x'|'X'=>return self.protocol_text_percent_integer(state,data,value),
            'e'|'E'|'f'|'F'|'g'|'G'=>return self.protocol_text_percent_float(state,data,value),
            'c'=>return self.protocol_text_percent_character(state,data,value),
            _=>return Err(pyerr("ValueError",format!("unsupported format character '{}' (0x{:x}) at index {}",if ('\u{1f}'..='~').contains(&kind){kind}else{'?'},kind as u32,data.position-1))),
        }
        Ok(())
    }
    fn text_percent_wrong_number(&self,data:&ProtocolTextPercent)->PyException {
        let kind=data.spec.kind;let name=self.typename(data.original.as_ref().unwrap());
        if kind=='c'{return pyerr("TypeError",format!("%c requires an int or a unicode character, not {name}"));}
        pyerr("TypeError",format!("%{kind} format: {} is required, not {name}",if "oxX".contains(kind){"an integer"}else{"a real number"}))
    }
    fn protocol_text_percent_integer(&mut self,state:&mut ProtocolState,data:ProtocolTextPercent,value:Value)->PyResult<()> {
        let payload=self.native_payload(&value).unwrap_or_else(||value.clone());
        if let Some(number)=self.protocol_primitive_int(&value){return self.protocol_text_percent_number(state,data,number);}
        let decimal="diu".contains(data.spec.kind);
        if decimal {
            if let Some((method,class))=self.protocol_slot(&value,"__int__") {
                let mut data=data;data.phase=TextPercentPhase::Integer("__int__".into());state.actions.push_front(ProtocolAction::TextPercent(Box::new(data)));
                return self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Pass,false);
            }
            if let Value::Float(number)=payload {return self.protocol_text_percent_number(state,data,Int::exact_from_f64(*number).map_err(int_error)?);}
        }
        if let Some((method,class))=self.protocol_slot(&value,"__index__") {
            let mut data=data;data.phase=TextPercentPhase::Integer("__index__".into());state.actions.push_front(ProtocolAction::TextPercent(Box::new(data)));
            return self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Pass,false);
        }
        Err(self.text_percent_wrong_number(&data))
    }
    fn protocol_text_percent_number(&mut self,state:&mut ProtocolState,data:ProtocolTextPercent,number:Int)->PyResult<()> {
        let spec=&data.spec;let kind=spec.kind;
        let magnitude=Int::exact_parts(false,number.magnitude().into_owned());
        let digits=magnitude.format_integer(match kind{'o'=>"o",'x'=>"x",'X'=>"X",_=>"d"}).map_err(int_error)?.unwrap();
        let mut field=String::new();if number.is_negative(){field.push('-');}else if spec.plus{field.push('+');}else if spec.space{field.push(' ');}
        if spec.alternate{match kind{'o'=>field.push_str("0o"),'x'=>field.push_str("0x"),'X'=>field.push_str("0X"),_=>{}}}
        text_percent_pad(&mut field,'0',spec.precision.unwrap_or(0).saturating_sub(digits.len()))?;text_percent_append(&mut field,&digits)?;
        self.protocol_text_percent_field(state,data,field,None)
    }
    fn protocol_text_percent_float(&mut self,state:&mut ProtocolState,mut data:ProtocolTextPercent,value:Value)->PyResult<()> {
        let payload=self.native_payload(&value).unwrap_or_else(||value.clone());
        if matches!(payload,Value::Float(_)) || matches!(value,Value::Int(_)|Value::Bool(_)){let number=self.as_float(&payload)?;return self.protocol_text_percent_real(state,data,number);}
        if let Some((method,class))=self.protocol_slot(&value,"__float__") {
            data.phase=TextPercentPhase::Float("__float__".into());state.actions.push_front(ProtocolAction::TextPercent(Box::new(data)));
            return self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Pass,false);
        }
        if matches!(payload,Value::Int(_)|Value::Bool(_)){let number=self.as_float(&payload)?;return self.protocol_text_percent_real(state,data,number);}
        if let Some((method,class))=self.protocol_slot(&value,"__index__") {
            data.phase=TextPercentPhase::Float("__index__".into());state.actions.push_front(ProtocolAction::TextPercent(Box::new(data)));
            return self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Pass,false);
        }
        Err(pyerr("TypeError",format!("must be real number, not {}",self.typename(&value))))
    }
    fn protocol_text_percent_real(&mut self,state:&mut ProtocolState,data:ProtocolTextPercent,number:f64)->PyResult<()> {
        let spec=&data.spec;let mut format=String::new();
        if spec.plus{format.push('+');}else if spec.space{format.push(' ');}
        if spec.alternate{format.push('#');}format.push('.');format.push_str(&spec.precision.unwrap_or(6).to_string());format.push(spec.kind);
        let field=text_format_float(number,&TextFormatSpec::parse(&format,true)?)?;
        self.protocol_text_percent_field(state,data,field,None)
    }
    fn protocol_text_percent_character(&mut self,state:&mut ProtocolState,mut data:ProtocolTextPercent,value:Value)->PyResult<()> {
        let payload=self.native_payload(&value).unwrap_or_else(||value.clone());
        if let Value::Str(text)=payload {
            let length=text.chars().count();if length!=1{return Err(pyerr("TypeError",format!("%c requires an int or a unicode character, not a string of length {length}")));}
            return self.protocol_text_percent_field(state,data,text.to_string(),None);
        }
        if let Some(number)=self.protocol_primitive_int(&value){return self.protocol_text_percent_codepoint(state,data,number);}
        if let Some((method,class))=self.protocol_slot(&value,"__index__") {
            data.phase=TextPercentPhase::Character;state.actions.push_front(ProtocolAction::TextPercent(Box::new(data)));
            return self.protocol_bind(state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Pass,false);
        }
        Err(self.text_percent_wrong_number(&data))
    }
    fn protocol_text_percent_codepoint(&mut self,state:&mut ProtocolState,data:ProtocolTextPercent,number:Int)->PyResult<()> {
        let number=number.to_usize().filter(|n|*n<0x110000).ok_or_else(||pyerr("OverflowError","%c arg not in range(0x110000)"))?;
        if (0xd800..=0xdfff).contains(&number){return Err(pyerr("NotImplementedError","unpaired Unicode surrogates are not supported"));}
        self.protocol_text_percent_field(state,data,char::from_u32(number as u32).unwrap().to_string(),None)
    }
    fn protocol_text_percent_field(&mut self,state:&mut ProtocolState,mut data:ProtocolTextPercent,mut field:String,identity:Option<Value>)->PyResult<()> {
        let spec=&data.spec;let numeric="diuoxXeEfFgG".contains(spec.kind);
        if "sra".contains(spec.kind){if let Some(precision)=spec.precision {if let Some((byte,_))=field.char_indices().nth(precision){field.truncate(byte);}}}
        let padding=spec.width.saturating_sub(field.chars().count());
        data.identity=if data.output.is_empty() && data.position==data.source.len() && padding==0 && identity.as_ref().is_some_and(|value|matches!(value,Value::Str(text)if text.as_str()==field)){identity}else{None};
        if spec.left {text_percent_append(&mut data.output,&field)?;text_percent_pad(&mut data.output,' ',padding)?;}
        else if spec.zero&&numeric {
            let sign=usize::from(field.as_bytes().first().is_some_and(|b|matches!(b,b'-'|b'+'|b' ')));
            let prefix=if field.as_bytes().get(sign)==Some(&b'0')&&field.as_bytes().get(sign+1).is_some_and(|b|matches!(b,b'x'|b'X'|b'o')){2}else{0};
            text_percent_append(&mut data.output,&field[..sign+prefix])?;text_percent_pad(&mut data.output,'0',padding)?;text_percent_append(&mut data.output,&field[sign+prefix..])?;
        }else{text_percent_pad(&mut data.output,' ',padding)?;text_percent_append(&mut data.output,&field)?;}
        data.original=None;data.phase=TextPercentPhase::Parse;
        state.actions.push_front(ProtocolAction::TextPercent(Box::new(data)));state.value=Some(Value::None);Ok(())
    }
    fn protocol_text_percent_result(&mut self,state:&mut ProtocolState,mut data:ProtocolTextPercent,value:Value)->PyResult<()> {
        match data.phase.clone() {
            TextPercentPhase::Parse=>self.protocol_text_percent_scan(state,data),
            TextPercentPhase::Mapped=>{data.arguments=vec![value];data.cursor=0;self.protocol_text_percent_spec(state,data)},
            TextPercentPhase::Text=>{
                let payload=self.native_payload(&value).unwrap_or_else(||value.clone());
                let Value::Str(text)=payload else{return Err(pyerr("TypeError","string conversion returned non-string"))};
                self.protocol_text_percent_field(state,data,text.to_string(),Some(value))
            },
            TextPercentPhase::Integer(_)=>{let number=self.protocol_primitive_int(&value).ok_or_else(||self.text_percent_wrong_number(&data))?;self.protocol_text_percent_number(state,data,number)},
            TextPercentPhase::Character=>{let number=self.protocol_primitive_int(&value).ok_or_else(||self.text_percent_wrong_number(&data))?;self.protocol_text_percent_codepoint(state,data,number)},
            TextPercentPhase::Float(method)=>{
                let payload=self.native_payload(&value).unwrap_or_else(||value.clone());
                let number=if method=="__float__" {match payload{Value::Float(number)=>*number,_=>return Err(pyerr("TypeError",format!("{}.__float__ returned non-float (type {})",self.typename(data.original.as_ref().unwrap()),self.typename(&value))))}}
                    else{let number=self.protocol_primitive_int(&value).ok_or_else(||pyerr("TypeError",format!("__index__ returned non-int (type {})",self.typename(&value))))?;self.as_float(&Value::Int(number.into()))?};
                self.protocol_text_percent_real(state,data,number)
            },
        }
    }
    fn protocol_text_percent_mask_failure(&mut self,state:&mut ProtocolState,error:&PyException)->PyResult<Option<PyException>> {
        if !self.exception_has_native_class(error,"TypeError"){return Ok(None);}
        let Some(boundary)=state.actions.iter().position(|action|matches!(action,ProtocolAction::TextPercent(data)if matches!(data.phase,TextPercentPhase::Integer(_)|TextPercentPhase::Character)))else{return Ok(None)};
        // Inner catches belong to the operation that raised, before this
        // numeric conversion masks a TypeError with printf's required text.
        for action in state.actions.iter().take(boundary) {
            if let ProtocolAction::Class(record)=action {if self.protocol_class_catches(record,error,None)?{return Ok(None);}}
        }
        if state.actions.iter().take(boundary).any(|action|match action {
            ProtocolAction::Input(data)=>data.ignores_failure(),
            ProtocolAction::Consumer(data)=>data.phase==2,
            ProtocolAction::Stream(data)=>matches!(data.as_ref(),ProtocolStream::ToolConstructor{data,phase:1}if data.name=="islice"),
            _=>false,
        }){return Ok(None);}
        let ProtocolAction::TextPercent(data)=self.protocol_discard_actions(state,boundary+1).pop().unwrap()else{unreachable!()};
        state.plan=None;state.value=None;state.binding_recovery=None;state.attribute_recovery=None;self.protocol_sync_repr_guards(state);
        Ok(Some(self.text_percent_wrong_number(&data)))
    }
    fn text_percent_sync(&mut self,format:Value,values:Value)->PyResult<Value> {
        let mut state=Self::protocol_empty(ProtocolSink::Stack);self.protocol_text_percent_start(&mut state,format,values)?;
        loop {
            state.actions.check_budget()?;let mut roots=Vec::new();state.roots(&mut roots);
            let turn=self.view_rooted(roots,|runtime,_|runtime.protocol_turn(None,&mut state));
            let outcome=match turn {
                Ok(ProtocolTurn::Continue)=>continue,
                Ok(ProtocolTurn::Done(value))=>{self.protocol_release_repr_guards(&mut state);return Ok(value);},
                Ok(ProtocolTurn::Schedule(child))=>{let mut roots=Vec::new();state.roots(&mut roots);self.view_rooted(roots,|runtime,_|runtime.execute(child)).map(|(value,_)|match value{FrameExit::Return(value)|FrameExit::Yield(value)=>value})},
                Err(error)=>Err(error),
            };
            match outcome{Ok(value)=>state.value=Some(value),Err(error)=>match self.protocol_state_failure(&mut state,&error,None){
                Ok(true)=>{},Ok(false)=>{self.protocol_release_repr_guards(&mut state);return Err(error);},
                Err(error)=>{self.protocol_release_repr_guards(&mut state);return Err(error);},
            }}
        }
    }
}
