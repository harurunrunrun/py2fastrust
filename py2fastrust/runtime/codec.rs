// UTF-8, ASCII, and Latin-1 codecs implemented without external libraries.
#[derive(Clone, Copy)]
enum TextCodec { Utf8, Ascii, Latin1 }
impl TextCodec {
    fn lookup(name: &str) -> PyResult<Self> {
        let mut normalized = String::new();
        let mut separator = false;
        for character in name.chars() {
            if character.is_ascii_alphanumeric() || character == '.' {
                if separator && !normalized.is_empty() { normalized.push('_'); }
                separator = false; normalized.push(character.to_ascii_lowercase());
            } else { separator = true; }
        }
        match normalized.as_str() {
            "utf8" | "utf_8" | "utf" | "u8" | "cp65001" => Ok(Self::Utf8),
            "ascii" | "646" | "us_ascii" | "us" | "ansi_x3.4_1968" | "ansi_x3_4_1968" | "ansi_x3.4_1986" | "iso646_us" | "iso_646.irv_1991" | "csascii" => Ok(Self::Ascii),
            "latin1" | "latin_1" | "latin" | "l1" | "iso8859_1" | "iso_8859_1" | "iso_8859_1_1987" | "iso_ir_100" | "cp819" | "ibm819" | "csisolatin1" => Ok(Self::Latin1),
            _ => Err(pyerr("LookupError", format!("unknown encoding: {name}"))),
        }
    }
    fn name(self) -> &'static str { match self { Self::Utf8 => "utf-8", Self::Ascii => "ascii", Self::Latin1 => "latin-1" } }
}
fn codec_bind(name: &str, args: Vec<Value>, kwargs: KeywordArgs, names: &[&str]) -> PyResult<Vec<Option<Value>>> {
    if args.len() > names.len() { return Err(pyerr("TypeError",format!("{name}() takes at most {} arguments",names.len()))); }
    let mut values = vec![None;names.len()];
    for (index,value) in args.into_iter().enumerate() { values[index] = Some(value); }
    for (key,value) in kwargs {
        let index = names.iter().position(|name|*name==key).ok_or_else(||pyerr("TypeError",format!("'{key}' is an invalid keyword argument for {name}()")))?;
        if values[index].is_some() { return Err(pyerr("TypeError",format!("argument '{key}' given by name and position"))); }
        values[index] = Some(value);
    }
    Ok(values)
}
fn codec_argument(runtime: &Runtime, value: Option<&Value>, default: &str, name: &str) -> PyResult<String> {
    let value = match value { None => default.to_owned(),Some(Value::Str(value)) => value.to_string(),Some(value) => match runtime.native_payload(value) { Some(Value::Str(value))=>value.into_inner(),_=>return Err(pyerr("TypeError",format!("{name} must be str"))) } };
    if value.contains('\0') { return Err(pyerr("ValueError","embedded null character")); }
    Ok(value)
}
fn codec_unknown_handler(errors: &str, decoding: bool) -> PyException {
    match errors {
        "surrogateescape" | "surrogatepass" | "namereplace" if !(decoding && errors=="namereplace") => pyerr("NotImplementedError",format!("codec error handler '{errors}' is not implemented")),
        "xmlcharrefreplace" | "namereplace" if decoding => pyerr("TypeError",format!("don't know how to handle UnicodeDecodeError in error callback '{errors}'")),
        _ => pyerr("LookupError",format!("unknown error handler name '{errors}'")),
    }
}
fn codec_unicode_message(encoding: &str, object: &Value, start: i128, end: i128, reason: &str, decoding: bool) -> String {
    let length=match object{Value::Str(value)=>value.chars().count(),Value::Bytes(value)=>value.len(),_=>0};
    let single=start>=0 && (start as u128)<length as u128 && start.checked_add(1)==Some(end);
    let location = if single { format!("position {start}") } else { format!("position {start}-{}",Int::exact_small(end).exact_add(&Int::exact_small(-1))) };
    if decoding {
        if single {
            let byte = match object { Value::Bytes(bytes)=>bytes[start as usize],_=>0 };
            format!("'{encoding}' codec can't decode byte 0x{byte:02x} in {location}: {reason}")
        } else { format!("'{encoding}' codec can't decode bytes in {location}: {reason}") }
    } else if single {
        let character=match object { Value::Str(value)=>value.chars().nth(start as usize).unwrap_or('\0').to_string(),_=>String::new() };
        format!("'{encoding}' codec can't encode character {} in {location}: {reason}",text_ascii_escape(&text_repr_str(&character)))
    } else { format!("'{encoding}' codec can't encode characters in {location}: {reason}") }
}
fn codec_exception_message(kind: &str, args: &[Value]) -> Option<String> {
    if !["UnicodeEncodeError","UnicodeDecodeError"].contains(&kind) { return None; }
    match args {
        [Value::Str(encoding),object,Value::Int(start),Value::Int(end),Value::Str(reason)] => Some(codec_unicode_message(encoding,object,start.to_i128()?,end.to_i128()?,reason,kind=="UnicodeDecodeError")),
        _ => None,
    }
}
fn codec_error(codec: TextCodec, object: Value, start: usize, end: usize, reason: &str, decoding: bool) -> PyException {
    let kind = if decoding { "UnicodeDecodeError" } else { "UnicodeEncodeError" };
    let mut error=pyerr(kind,codec_unicode_message(codec.name(),&object,start as i128,end as i128,reason,decoding));
    error.args=vec![Value::Str(codec.name().into()),object.clone(),Value::Int(Int::from_i128(start as i128).into()),Value::Int(Int::from_i128(end as i128).into()),Value::Str(reason.into())];
    for (name,value) in ["encoding","object","start","end","reason"].iter().zip(error.0.args.iter()) { error.0.attributes.insert((*name).into(),value.clone()); }
    error
}

impl Runtime {
    fn bytes_constructor(&mut self, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        let mut values=codec_bind("bytes",args,kwargs,&["source","encoding","errors"])?;
        let encoding=codec_argument(self,values[1].as_ref(),"utf-8","encoding")?;
        let errors=codec_argument(self,values[2].as_ref(),"strict","errors")?;
        let encoded=values[1].is_some();let error_argument=values[2].is_some();
        let source=values[0].take();
        if let Some(source)=source {
            let payload=self.native_capability_payload(&source,"str").or_else(||self.native_payload(&source)).unwrap_or_else(||source.clone());
            if let Value::Str(_) = &payload {
                if !encoded { return Err(pyerr("TypeError","string argument without an encoding")); }
                return self.codec_encode(payload,vec![Value::Str(encoding.into()),Value::Str(errors.into())],Vec::new());
            }
            if encoded || error_argument { return Err(pyerr("TypeError",if encoded{"encoding without a string argument"}else{"errors without a string argument"})); }
            if let Value::Bytes(_) = &source { return Ok(source); }
            let root=self.roots.len();self.roots.push(vec![source.clone()]);
            let result=(|| {
                match self.special_method(source.clone(),"__bytes__") {
                    Ok(method)=>{
                        let result=self.call(method,Vec::new(),Vec::new(),None)?;
                        if matches!(result,Value::Bytes(_)) { return Ok(result); }
                        if let Some(Value::Bytes(_))=self.native_payload(&result) { return Ok(result); }
                        return Err(pyerr("TypeError","__bytes__ returned non-bytes"));
                    },
                    Err(error) if self.missing_special_method(&source,"__bytes__",&error) => (),
                    Err(error)=>return Err(error),
                }
                if matches!(payload,Value::Bytes(_)){return Ok(payload);}
                let count=if matches!(payload,Value::Int(_) | Value::Bool(_)) { Some(self.as_int(&payload)?) }
                else { match self.special_method(source.clone(),"__index__") {
                    Ok(method)=>{let value=self.call(method,Vec::new(),Vec::new(),None)?;match value{Value::Int(value)=>Some(value.into_inner()),Value::Bool(value)=>Some(Int::from_i128(if value{1}else{0})),_=>return Err(pyerr("TypeError","__index__ returned non-int"))}},
                    Err(error) if self.missing_special_method(&source,"__index__",&error)=>None,Err(error)=>return Err(error),
                }};
                if let Some(count)=count {
                    if count.is_negative(){return Err(pyerr("ValueError","negative count"));}
                    let count=count.to_usize().filter(|count|*count<=isize::MAX as usize).ok_or_else(||pyerr("OverflowError","cannot fit 'int' into an index-sized integer"))?;
                    let mut result=Vec::new();result.try_reserve_exact(count).map_err(|_|pyerr("MemoryError","cannot allocate bytes"))?;result.resize(count,0);
                    return Ok(Value::Bytes(result.into()));
                }
                if let Some(data)=self.buffer_read(&source,false)?{return Ok(Value::Bytes(data.into()));}
                let iterator=self.iter(source)?;self.roots[root].push(iterator.clone());let mut result=Vec::new();
                while let Some(value)=self.next(iterator.clone())? {
                    self.roots[root].truncate(2);self.roots[root].push(value.clone());
                    let number=self.as_int(&value)?.to_usize().filter(|value|*value<256).ok_or_else(||pyerr("ValueError","bytes must be in range(0, 256)"))?;
                    result.push(number as u8);
                }
                Ok(Value::Bytes(result.into()))
            })();self.roots.truncate(root);result
        } else {
            if encoded || error_argument { return Err(pyerr("TypeError",if encoded{"encoding without a string argument"}else{"errors without a string argument"})); }
            Ok(Value::Bytes(Vec::new().into()))
        }
    }
    fn str_constructor(&mut self, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        let mut values=codec_bind("str",args,kwargs,&["object","encoding","errors"])?;
        let encoding=codec_argument(self,values[1].as_ref(),"utf-8","encoding")?;
        let errors=codec_argument(self,values[2].as_ref(),"strict","errors")?;
        let decoding=values[1].is_some() || values[2].is_some();
        let source=match values[0].take(){Some(value)=>value,None=>return Ok(Value::Str(String::new().into()))};
        if decoding {
            // str(object, encoding) reports failed buffer acquisition as TypeError,
            // including exporter exceptions and non-contiguous memoryviews. Keep
            // acquisition separate from decode errors, and preserve __buffer__
            // overrides on native subclasses.
            let source=self.class_hidden_text_payload(&source).unwrap_or(source);
            let source=if matches!(source,Value::Bytes(_)|Value::Str(_)){source}else{
                let data=self.buffer_read(&source,true).map_err(|_|pyerr("TypeError","decoding to str requires a bytes-like object"))?.ok_or_else(||pyerr("TypeError","decoding to str requires a bytes-like object"))?;
                Value::Bytes(data.into())
            };
            return self.codec_decode(source,vec![Value::Str(encoding.into()),Value::Str(errors.into())],Vec::new());
        }
        if matches!(source,Value::Str(_)){return Ok(source);}
        // An alias delegates explicit attributes to its origin. Its implicit
        // string slot still uses the alias's own representation.
        if matches!(&source,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::GenericAlias{..}|Object::UnpackedAlias(_)))) {
            return self.repr(&source).map(|text|Value::Str(text.into()));
        }
        match self.special_method(source.clone(),"__str__") {
            Ok(method)=>{
                let result=self.call(method,Vec::new(),Vec::new(),None)?;
                if matches!(result,Value::Str(_)) || matches!(self.native_payload(&result),Some(Value::Str(_))) {return Ok(result);}
                return Err(pyerr("TypeError","__str__ returned non-string"));
            },
            Err(error) if self.missing_special_method(&source,"__str__",&error)=>(),Err(error)=>return Err(error),
        }
        Ok(Value::Str(self.str_value(&source)?.into()))
    }
    fn codec_encode(&mut self, source: Value, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        let values=codec_bind("encode",args,kwargs,&["encoding","errors"])?;
        let encoding=codec_argument(self,values[0].as_ref(),"utf-8","encoding")?;
        let errors=codec_argument(self,values[1].as_ref(),"strict","errors")?;
        let codec=TextCodec::lookup(&encoding)?;
        let text=match &source{Value::Str(text)=>text,_=>return Err(pyerr("TypeError","encoding requires a string"))};
        if matches!(codec,TextCodec::Utf8){return Ok(Value::Bytes(text.as_bytes().to_vec().into()));}
        let maximum=if matches!(codec,TextCodec::Ascii){127}else{255};
        let characters:Vec<char>=text.chars().collect();let mut at=0;let mut output=Vec::with_capacity(text.len());
        while at<characters.len() {
            let character=characters[at];
            if character as u32<=maximum{output.push(character as u8);at+=1;continue;}
            let start=at;while at<characters.len() && characters[at] as u32>maximum{at+=1;}
            match errors.as_str() {
                "strict"=>return Err(codec_error(codec,source.clone(),start,at,if maximum==127{"ordinal not in range(128)"}else{"ordinal not in range(256)"},false)),
                "ignore"=>(),
                "replace"=>output.extend(std::iter::repeat(b'?').take(at-start)),
                "backslashreplace"=>{let text:String=characters[start..at].iter().collect();output.extend_from_slice(text_ascii_escape(&text).as_bytes());},
                "xmlcharrefreplace"=>for character in &characters[start..at]{output.extend_from_slice(format!("&#{};",*character as u32).as_bytes());},
                _=>return Err(codec_unknown_handler(&errors,false)),
            }
        }
        Ok(Value::Bytes(output.into()))
    }
    fn codec_decode(&mut self, source: Value, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        let values=codec_bind("decode",args,kwargs,&["encoding","errors"])?;
        let encoding=codec_argument(self,values[0].as_ref(),"utf-8","encoding")?;
        let errors=codec_argument(self,values[1].as_ref(),"strict","errors")?;
        let source=if matches!(source,Value::Bytes(_)|Value::Str(_)){source}else{Value::Bytes(self.buffer_read(&source,true)?.ok_or_else(||pyerr("TypeError","decoding requires a bytes-like object"))?.into())};
        let bytes=match &source{Value::Bytes(bytes)=>bytes,Value::Str(_)=>return Err(pyerr("TypeError","decoding str is not supported")),_=>return Err(pyerr("TypeError","decoding requires a bytes-like object"))};
        let codec=TextCodec::lookup(&encoding)?;
        if matches!(codec,TextCodec::Latin1){return Ok(Value::Str(bytes.iter().map(|byte|*byte as char).collect()));}
        let mut at=0;let mut output=String::with_capacity(bytes.len());
        while at<bytes.len() {
            let (start,end,reason)=if matches!(codec,TextCodec::Ascii) {
                if bytes[at]<128{output.push(bytes[at] as char);at+=1;continue;}
                (at,at+1,"ordinal not in range(128)")
            } else {
                match std::str::from_utf8(&bytes[at..]) {
                    Ok(text)=>{output.push_str(text);break;},
                    Err(error)=>{
                        let start=at+error.valid_up_to();output.push_str(std::str::from_utf8(&bytes[at..start]).unwrap());
                        let end=start+error.error_len().unwrap_or(bytes.len()-start);
                        let reason=if !(0xc2..=0xf4).contains(&bytes[start]){"invalid start byte"}else if error.error_len().is_none(){"unexpected end of data"}else{"invalid continuation byte"};
                        (start,end,reason)
                    },
                }
            };
            match errors.as_str() {
                "strict"=>return Err(codec_error(codec,source.clone(),start,end,reason,true)),
                "ignore"=>(),
                "replace"=>output.push('\u{fffd}'),
                "backslashreplace"=>for byte in &bytes[start..end]{output.push_str(&format!("\\x{byte:02x}"));},
                _=>return Err(codec_unknown_handler(&errors,true)),
            }
            at=end;
        }
        Ok(Value::Str(output.into()))
    }
}
