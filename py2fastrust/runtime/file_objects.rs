// Native file objects retain stable heap identities for each I/O layer. Rust
// buffers contain no Python references; the explicit child/attribute edges are
// traced by the runtime GC, including cycles made through a file's __dict__.
#[derive(Clone, Debug)]
enum FilePayload {
    Raw(FileRawRef),
    Buffer(FileBufferRef),
    Text(std::rc::Rc<std::cell::RefCell<FileText>>),
}
#[derive(Clone, Debug)]
struct IoFile {
    payload:FilePayload, attrs:usize, child:Option<Value>, mode:String,
    type_name:String, closefd:bool,
}
#[derive(Clone,Debug)]
struct FileMode {read:bool,write:bool,append:bool,create:bool,truncate:bool,exclusive:bool,binary:bool,raw_mode:String}
impl FileMode {
    fn parse(mode:&str)->PyResult<Self> {
        let mut seen=std::collections::HashSet::new();
        if mode.is_empty()||mode.chars().any(|c|!"rwaxbt+".contains(c)||!seen.insert(c)) {
            return Err(pyerr("ValueError",format!("invalid mode: '{mode}'")));
        }
        let primary:Vec<_>=mode.chars().filter(|c|"rwax".contains(*c)).collect();
        if primary.len()!=1 || seen.contains(&'b')&&seen.contains(&'t') {
            return Err(pyerr("ValueError","must have exactly one of create/read/write/append mode"));
        }
        let first=primary[0];let plus=seen.contains(&'+');
        Ok(Self{read:first=='r'||plus,write:first!='r'||plus,append:first=='a',create:first!='r',
            truncate:first=='w',exclusive:first=='x',binary:seen.contains(&'b'),
            raw_mode:format!("{}b{}",if plus&&first!='a'{'r'}else{first},if plus{"+"}else{""})})
    }
    fn flags(&self)->i32 {
        let mut flags=if self.read&&self.write{2}else if self.write{1}else{0};
        if self.create{flags|=64;}if self.truncate{flags|=512;}
        if self.exclusive{flags|=128;}if self.append{flags|=1024;}
        #[cfg(target_os="linux")]{flags|=0x80000;}
        flags
    }
}
fn file_type_name(name:&str)->bool {
    matches!(name,"_io.FileIO"|"_io.BufferedReader"|"_io.BufferedWriter"|"_io.BufferedRandom"|"_io.TextIOWrapper"|"_io._IOBase"|"_io._RawIOBase"|"_io._BufferedIOBase"|"_io._TextIOBase")
}
fn file_type_parent(name:&str)->Option<&'static str> {
    match name {"_io.FileIO"=>Some("_io._RawIOBase"),"_io.BufferedReader"|"_io.BufferedWriter"|"_io.BufferedRandom"=>Some("_io._BufferedIOBase"),
        "_io.TextIOWrapper"=>Some("_io._TextIOBase"),"_io._RawIOBase"|"_io._BufferedIOBase"|"_io._TextIOBase"=>Some("_io._IOBase"),"_io._IOBase"=>Some("object"),_=>None}
}
fn file_method_name(name:&str,text:bool,raw:bool)->bool {
    matches!(name,"__enter__"|"__exit__"|"__iter__"|"__next__"|"__repr__"|"__del__"|"__getstate__"|"close"|"flush"|"readable"|"writable"|"seekable"|"isatty"|"fileno"|"read"|"readline"|"readlines"|"write"|"writelines"|"seek"|"tell"|"truncate")
    || !text&&name=="readinto" || !text&&!raw&&matches!(name,"readinto1"|"read1") || raw&&name=="readall" || !raw&&name=="detach"
    || !raw&&!text&&name=="peek" || text&&name=="reconfigure"
}
fn file_position(value:u64)->Value {Value::Int(Int::from_i128(value as i128).into())}
fn file_data_property(file:&IoFile,name:&str)->bool {
    let raw=matches!(file.payload,FilePayload::Raw(_));let text=matches!(file.payload,FilePayload::Text(_));
    matches!(name,"__dict__"|"__class__"|"closed")||name=="name"&&!raw||name=="mode"&&!text
        ||name=="closefd"&&raw||name=="raw"&&!raw&&!text||name=="buffer"&&text
        ||text&&matches!(name,"encoding"|"errors"|"line_buffering"|"write_through"|"newlines")
}

impl IoFile {
    fn capabilities(&self)->PyResult<(bool,bool)> {
        self.check()?;
        Ok(match &self.payload {FilePayload::Raw(raw)=>{let raw=raw.borrow();(raw.readable,raw.writable)},FilePayload::Buffer(buffer)=>{let buffer=buffer.borrow();(buffer.can_read,buffer.can_write)},FilePayload::Text(text)=>{let buffer=text.borrow().buffer()?;let buffer=buffer.borrow();(buffer.can_read,buffer.can_write)}})
    }
    fn raw(&self)->PyResult<FileRawRef> {
        match &self.payload {
            FilePayload::Raw(raw)=>Ok(raw.clone()),FilePayload::Buffer(buffer)=>buffer.borrow().raw(),
            FilePayload::Text(text)=>text.borrow().buffer()?.borrow().raw(),
        }
    }
    fn check(&self)->PyResult<()> {self.raw()?.borrow().check()}
    fn closed(&self)->PyResult<bool> {Ok(self.raw()?.borrow().handle.is_none())}
    fn flush(&self)->PyResult<()> {match &self.payload {
        FilePayload::Raw(raw)=>raw.borrow().check(),FilePayload::Buffer(buffer)=>buffer.borrow_mut().flush(),
        FilePayload::Text(text)=>text.borrow_mut().flush(),
    }}
    fn close(&self)->PyResult<()> {match &self.payload {
        FilePayload::Raw(raw)=>raw.borrow_mut().close(),FilePayload::Buffer(buffer)=>buffer.borrow_mut().close(),
        FilePayload::Text(text)=>text.borrow_mut().close(),
    }}
}
impl Runtime {
    fn file_value(&self,value:&Value)->Option<IoFile> {
        match value {Value::Obj(index)=>match self.heap.get(*index).and_then(Option::as_ref){Some(Object::IoFile(file))=>Some(file.clone()),_=>None},_=>None}
    }
    fn file_allocate(&mut self,payload:FilePayload,child:Option<Value>,name:Value,mode:String,type_name:&str,closefd:bool)->Value {
        let attrs=self.alloc(Object::Dict(Vec::new()));
        if matches!(payload,FilePayload::Raw(_)){self.ns_set(attrs,"name".into(),name);}
        if matches!(payload,FilePayload::Text(_))&&!mode.is_empty(){self.ns_set(attrs,"mode".into(),Value::Str(mode.clone().into()));}
        self.obj_value(Object::IoFile(IoFile{payload,attrs,child,mode,type_name:type_name.into(),closefd}))
    }
    fn file_index(&mut self,value:&Value)->PyResult<i64> {
        self.as_int(value)?.to_i128().and_then(|value|i64::try_from(value).ok()).ok_or_else(||pyerr("OverflowError","Python int too large to convert to C ssize_t"))
    }
    fn file_path(&mut self,value:Value)->PyResult<(std::path::PathBuf,Value)> {
        let payload=self.native_payload(&value).unwrap_or_else(||value.clone());
        let path=match payload {
            Value::Str(_)|Value::Bytes(_)=>payload,
            _=>{
                let method=self.special_method(value.clone(),"__fspath__").map_err(|error|if self.missing_special_method(&value,"__fspath__",&error){pyerr("TypeError",format!("expected str, bytes or os.PathLike object, not {}",self.typename(&value)))}else{error})?;
                let result=self.call(method,Vec::new(),Vec::new(),None)?;
                self.native_payload(&result).unwrap_or(result)
            },
        };
        let native=match &path {
            Value::Str(text)=>{if text.contains('\0'){return Err(pyerr("ValueError","embedded null character"));}std::path::PathBuf::from(text.as_str())},
            Value::Bytes(bytes)=>{
                if bytes.contains(&0){return Err(pyerr("ValueError","embedded null byte"));}
                #[cfg(unix)]{use std::os::unix::ffi::OsStringExt;std::path::PathBuf::from(std::ffi::OsString::from_vec(bytes.to_vec()))}
                #[cfg(not(unix))]{std::path::PathBuf::from(String::from_utf8(bytes.to_vec()).map_err(|_|pyerr("ValueError","invalid filename encoding"))?)}
            },
            _=>return Err(pyerr("TypeError","__fspath__() must return str or bytes")),
        };
        Ok((native,path))
    }
    fn file_open_raw(&mut self,source:Value,mode:&FileMode,closefd:bool,opener:Option<Value>,preserve_name:bool)->PyResult<(FileRawRef,Value)> {
        let payload=self.native_payload(&source).unwrap_or_else(||source.clone());
        let descriptor=if matches!(payload,Value::Int(_)|Value::Bool(_)){Some(self.file_index(&payload)?)}else{
            match self.special_method(source.clone(),"__index__") {
                Ok(method)=>{let result=self.call(method,Vec::new(),Vec::new(),None)?;Some(self.file_index(&result)?)},
                Err(error) if self.missing_special_method(&source,"__index__",&error)=>None,Err(error)=>return Err(error),
            }
        };
        if let Some(fd)=descriptor {
            let fd=i32::try_from(fd).map_err(|_|pyerr("OverflowError","Python int too large to convert to C int"))?;
            return Ok((std::rc::Rc::new(std::cell::RefCell::new(FileRaw::descriptor(fd,closefd,mode.read,mode.write)?)),source));
        }
        let original_name=source.clone();
        let (path,name)=self.file_path(source)?;
        let file_name=if preserve_name{original_name}else{name.clone()};
        if !closefd{return Err(pyerr("ValueError","Cannot use closefd=False with file name"));}
        if let Some(opener)=opener {
            let result=self.call(opener,vec![name.clone(),Value::Int(Int::from_i128(mode.flags() as i128).into())],Vec::new(),None)?;
            let fd=self.file_index(&result)?;
            let fd=i32::try_from(fd).map_err(|_|pyerr("OverflowError","Python int too large to convert to C int"))?;
            return Ok((std::rc::Rc::new(std::cell::RefCell::new(FileRaw::descriptor(fd,true,mode.read,mode.write)?)),file_name));
        }
        let result=std::fs::OpenOptions::new().read(mode.read).write(mode.write).append(mode.append)
            .create(mode.create&&!mode.exclusive).create_new(mode.exclusive).truncate(mode.truncate).open(path);
        let file=result.map_err(|error|{let mut error=file_os_error(error);error.attributes.insert("filename".into(),name.clone());error})?;
        if file.metadata().map_err(file_os_error)?.is_dir(){let mut error=file_os_error(std::io::Error::from_raw_os_error(21));error.attributes.insert("filename".into(),name);return Err(error);}
        let mut raw=FileRaw::owned(file,mode.read,mode.write);
        if mode.append{raw.seek(0,2)?;}
        Ok((std::rc::Rc::new(std::cell::RefCell::new(raw)),file_name))
    }
    fn file_open(&mut self,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<Value> {
        let values=codec_bind("open",args,kwargs,&["file","mode","buffering","encoding","errors","newline","closefd","opener"])?;
        let source=values[0].clone().ok_or_else(||pyerr("TypeError","open() missing required argument 'file' (pos 1)"))?;
        let mode_text=codec_argument(self,values[1].as_ref(),"r","mode")?;
        let mode=FileMode::parse(&mode_text)?;
        let buffering=match &values[2]{Some(value)=>self.file_index(value)?,None=>-1};
        let encoding=codec_argument(self,values[3].as_ref().filter(|value|!matches!(value,Value::None)),"UTF-8","encoding")?;
        let errors=codec_argument(self,values[4].as_ref().filter(|value|!matches!(value,Value::None)),"strict","errors")?;
        let newline=match &values[5]{None|Some(Value::None)=>None,Some(value)=>Some(codec_argument(self,Some(value),"","newline")?)};
        if mode.binary {
            for (index,name) in [(3,"encoding"),(4,"errors"),(5,"newline")] {
                if values[index].as_ref().is_some_and(|value|!matches!(value,Value::None)){return Err(pyerr("ValueError",format!("binary mode doesn't take an {name} argument")));}
            }
        }
        let closefd=match &values[6]{Some(value)=>self.truth(value)?,None=>true};
        let opener=values[7].clone().filter(|value|!matches!(value,Value::None));
        let roots=self.roots.len();self.roots.push(values.into_iter().flatten().collect());
        let mut opened=None;
        let result=(||{
            let (raw,name)=self.file_open_raw(source,&mode,closefd,opener,false)?;
            opened=Some(raw.clone());
            let raw_value=self.file_allocate(FilePayload::Raw(raw.clone()),None,name.clone(),mode.raw_mode.clone(),"_io.FileIO",closefd);
            self.roots[roots].push(raw_value.clone());
            if !mode.binary {
                TextCodec::lookup(if encoding=="locale"{"utf-8"}else{&encoding})?;
                if buffering==0{return Err(pyerr("ValueError","can't have unbuffered text I/O"));}
                if newline.as_ref().is_some_and(|value|!matches!(value.as_str(),""|"\n"|"\r"|"\r\n")){return Err(pyerr("ValueError","illegal newline value"));}
            }
            if buffering==0{return Ok(raw_value);}
            let capacity=if buffering<=1{131072}else{usize::try_from(buffering).map_err(|_|pyerr("OverflowError","buffer size is too large"))?};
            let buffer=std::rc::Rc::new(std::cell::RefCell::new(FileBuffer::new(raw,capacity)));
            let type_name=if mode.read&&mode.write{"_io.BufferedRandom"}else if mode.read{"_io.BufferedReader"}else{"_io.BufferedWriter"};
            let buffer_value=self.file_allocate(FilePayload::Buffer(buffer.clone()),Some(raw_value),name.clone(),mode.raw_mode,type_name,closefd);
            self.roots[roots].push(buffer_value.clone());
            if mode.binary{return Ok(buffer_value);}
            let text=FileText::new(buffer,encoding,errors,newline,buffering==1,false)?;
            Ok(self.file_allocate(FilePayload::Text(std::rc::Rc::new(std::cell::RefCell::new(text))),Some(buffer_value),name,mode_text,"_io.TextIOWrapper",closefd))
        })();
        if result.is_err(){if let Some(raw)=opened{let _=raw.borrow_mut().close();}}
        self.roots.truncate(roots);result
    }
    fn file_constructor(&mut self,kind:&str,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<Value> {
        if kind=="_io.FileIO" {
            let values=codec_bind("FileIO",args,kwargs,&["file","mode","closefd","opener"])?;
            let source=values[0].clone().ok_or_else(||pyerr("TypeError","FileIO() missing required argument 'file'"))?;
            let mode=FileMode::parse(&codec_argument(self,values[1].as_ref(),"r","mode")?)?;
            let closefd=match &values[2]{Some(value)=>self.truth(value)?,None=>true};
            let root=self.roots.len();self.roots.push(values.iter().flatten().cloned().collect());
            let result=(||{let (raw,name)=self.file_open_raw(source,&mode,closefd,values[3].clone().filter(|value|!matches!(value,Value::None)),true)?;
                Ok(self.file_allocate(FilePayload::Raw(raw),None,name,mode.raw_mode,kind,closefd))})();
            self.roots.truncate(root);return result;
        }
        if matches!(kind,"_io.BufferedReader"|"_io.BufferedWriter"|"_io.BufferedRandom") {
            let values=codec_bind(kind,args,kwargs,&["raw","buffer_size"])?;
            let child=values[0].clone().ok_or_else(||pyerr("TypeError","missing required raw stream"))?;
            let file=self.file_value(&child).ok_or_else(||pyerr("NotImplementedError","buffering a Python-defined raw stream is not yet implemented"))?;
            let FilePayload::Raw(raw)=&file.payload else{return Err(pyerr("TypeError","expected a raw file stream"));};
            let capacity=match &values[1]{Some(value)=>self.file_index(value)?,None=>131072};
            if capacity<=0{return Err(pyerr("ValueError","buffer size must be strictly positive"));}
            raw.borrow().check()?;
            if matches!(kind,"_io.BufferedReader"|"_io.BufferedRandom")&&!raw.borrow().readable{return Err(file_unsupported("File or stream is not readable"));}
            if matches!(kind,"_io.BufferedWriter"|"_io.BufferedRandom")&&!raw.borrow().writable{return Err(file_unsupported("File or stream is not writable"));}
            if kind=="_io.BufferedRandom"{raw.borrow_mut().seek(0,1)?;}
            let buffer=std::rc::Rc::new(std::cell::RefCell::new(FileBuffer::new(raw.clone(),capacity as usize)));
            buffer.borrow_mut().can_read=kind!="_io.BufferedWriter";
            buffer.borrow_mut().can_write=kind!="_io.BufferedReader";
            return Ok(self.file_allocate(FilePayload::Buffer(buffer),Some(child),Value::None,file.mode,kind,file.closefd));
        }
        if kind=="_io.TextIOWrapper" {
            let values=codec_bind("TextIOWrapper",args,kwargs,&["buffer","encoding","errors","newline","line_buffering","write_through"])?;
            let child=values[0].clone().ok_or_else(||pyerr("TypeError","missing required buffer"))?;
            let file=self.file_value(&child).ok_or_else(||pyerr("NotImplementedError","wrapping a Python-defined binary stream is not yet implemented"))?;
            let buffer=match &file.payload {FilePayload::Buffer(buffer)=>buffer.clone(),FilePayload::Raw(raw)=>std::rc::Rc::new(std::cell::RefCell::new(FileBuffer::new(raw.clone(),8192))),_=>return Err(pyerr("TypeError","a binary buffer is required"))};
            let encoding=codec_argument(self,values[1].as_ref().filter(|value|!matches!(value,Value::None)),"UTF-8","encoding")?;
            let errors=codec_argument(self,values[2].as_ref().filter(|value|!matches!(value,Value::None)),"strict","errors")?;
            let newline=match &values[3]{None|Some(Value::None)=>None,Some(value)=>Some(codec_argument(self,Some(value),"","newline")?)};
            if newline.as_ref().is_some_and(|value|!matches!(value.as_str(),""|"\n"|"\r"|"\r\n")){return Err(pyerr("ValueError","illegal newline value"));}
            let line_buffering=match &values[4]{Some(value)=>self.truth(value)?,None=>false};
            let write_through=match &values[5]{Some(value)=>self.truth(value)?,None=>false};
            let text=FileText::new(buffer,encoding,errors,newline,line_buffering,write_through)?;
            return Ok(self.file_allocate(FilePayload::Text(std::rc::Rc::new(std::cell::RefCell::new(text))),Some(child),Value::None,String::new(),kind,file.closefd));
        }
        Err(pyerr("NotImplementedError",format!("{kind} constructor is not yet implemented")))
    }
    fn file_getattr(&mut self,value:Value,name:&str)->Option<PyResult<Value>> {
        if let Value::Builtin(kind)=&value {
            if file_type_name(kind) {
                let class_name=kind.rsplit('.').next().unwrap();
                let special=match name {
                    "__name__"|"__qualname__"=>Some(Value::Str(class_name.into())),"__module__"=>Some(Value::Str("_io".into())),
                    "__class__"=>Some(Value::Builtin("type".into())),_=>None,
                };
                if let Some(result)=special{return Some(Ok(result));}
                if file_method_name(name,kind=="_io.TextIOWrapper",kind=="_io.FileIO") {return Some(Ok(Value::Builtin(format!("file_method:{name}"))));}
            }
            return None;
        }
        let file=self.file_value(&value)?;
        let text=matches!(file.payload,FilePayload::Text(_));let raw=matches!(file.payload,FilePayload::Raw(_));
        Some((||{
            if !file_data_property(&file,name){if let Some(value)=self.ns_get(file.attrs,name){return Ok(value);}}
            match name {
                "__dict__"=>return Ok(Value::Obj(file.attrs)),"__class__"=>return Ok(Value::Builtin(file.type_name.clone())),
                "name"=>return self.file_name(&file),"mode" if !text=>return Ok(Value::Str(file.mode.clone().into())),
                "closed"=>return Ok(Value::Bool(file.closed()?)),"closefd" if raw=>return Ok(Value::Bool(file.closefd)),
                "raw" if !text&&!raw=>{if let FilePayload::Buffer(buffer)=&file.payload{buffer.borrow().raw()?;}return file.child.clone().ok_or_else(||pyerr("ValueError","raw stream has been detached"));},
                "buffer" if text=>{if let FilePayload::Text(state)=&file.payload{state.borrow().buffer()?;}return file.child.clone().ok_or_else(||pyerr("ValueError","underlying buffer has been detached"));},
                "encoding"|"errors"|"line_buffering"|"write_through"|"newlines" if text=>{
                    let FilePayload::Text(state)=&file.payload else{unreachable!()};
                    let state=state.borrow();
                    return Ok(match name {
                        "encoding"=>Value::Str(state.encoding.clone().into()),"errors"=>Value::Str(state.errors.clone().into()),
                        "line_buffering"=>Value::Bool(state.line_buffering),"write_through"=>Value::Bool(state.write_through),
                        _=>{let flags=state.newline_flags;drop(state);let mut values=Vec::new();for (flag,line) in [(1,"\r"),(2,"\n"),(4,"\r\n")] {if flags&flag!=0{values.push(Value::Str(line.into()));}}match values.len(){0=>Value::None,1=>values.remove(0),_=>self.obj_value(Object::Tuple(values))}},
                    });
                },
                _=>(),
            }
            if file_method_name(name,text,raw){return Ok(self.obj_value(Object::Bound(Value::Builtin(format!("file_method:{name}")),value)));}
            Err(pyerr("AttributeError",format!("'{}' object has no attribute '{name}'",self.typename(&value))))
        })())
    }
    fn file_setattr(&mut self,value:&Value,name:&str,new_value:Value)->Option<PyResult<()>> {
        let file=self.file_value(value)?;
        if file_data_property(&file,name) {
            return Some(Err(pyerr("AttributeError",format!("attribute '{name}' is not writable"))));
        }
        self.ns_set(file.attrs,name.into(),new_value);Some(Ok(()))
    }
    fn file_delattr(&mut self,value:&Value,name:&str)->Option<PyResult<()>> {
        let file=self.file_value(value)?;
        if file_data_property(&file,name){
            return Some(Err(pyerr("AttributeError",format!("attribute '{name}' is not writable"))));
        }
        Some(if self.ns_del(file.attrs,name){Ok(())}else{Err(pyerr("AttributeError",format!("file object has no attribute '{name}'")))})
    }
    fn file_special_method(&mut self,value:Value,name:&str)->Option<PyResult<Value>> {
        let file=self.file_value(&value)?;
        if file_method_name(name,matches!(file.payload,FilePayload::Text(_)),matches!(file.payload,FilePayload::Raw(_))){return Some(Ok(self.obj_value(Object::Bound(Value::Builtin(format!("file_method:{name}")),value))));}
        None
    }
    fn file_repr(&mut self,file:&IoFile)->PyResult<String> {
        if matches!(file.payload,FilePayload::Text(_)) {
            let FilePayload::Text(text)=&file.payload else{unreachable!()};
            let mut result="<_io.TextIOWrapper".to_string();
            match self.file_name(file){Ok(name)=>{result.push_str(" name=");result.push_str(&self.repr(&name)?);},Err(error)if error.kind=="ValueError"||error.kind=="AttributeError"=>(),Err(error)=>return Err(error)}
            if let Some(mode)=self.ns_get(file.attrs,"mode"){result.push_str(" mode=");result.push_str(&self.repr(&mode)?);}
            result.push_str(" encoding=");result.push_str(&text_repr_str(&text.borrow().encoding));result.push('>');return Ok(result);
        }
        let name_value=self.file_name(file)?;
        let name=self.repr(&name_value)?;
        if matches!(file.payload,FilePayload::Raw(_)) {
            return Ok(if file.closed()?{"<_io.FileIO [closed]>".into()}else{format!("<_io.FileIO name={name} mode='{}' closefd={}>",file.mode,if file.closefd{"True"}else{"False"})});
        }
        Ok(format!("<{} name={name}>",file.type_name))
    }
    fn file_name(&mut self,file:&IoFile)->PyResult<Value> {
        if let Some(child)=&file.child{return self.getattr(child.clone(),"name");}
        if matches!(file.payload,FilePayload::Raw(_)){return self.ns_get(file.attrs,"name").ok_or_else(||pyerr("AttributeError","'FileIO' object has no attribute 'name'"));}
        Err(pyerr("ValueError","underlying buffer has been detached"))
    }
    fn file_exception_message(&mut self,error:&PyException)->Option<PyResult<String>> {
        if !self.exception_has_native_class(error,"OSError"){return None;}
        let number=error.attributes.get("errno")?.clone();
        let reason=error.attributes.get("strerror")?.clone();
        if matches!(number,Value::None)&&matches!(reason,Value::None){return None;}
        Some((||{
            let mut message=format!("[Errno {}] {}",self.str_value(&number)?,self.str_value(&reason)?);
            if let Some(filename)=error.attributes.get("filename").filter(|value|!matches!(value,Value::None)){
                message.push_str(": ");message.push_str(&self.repr(filename)?);
                if let Some(filename2)=error.attributes.get("filename2").filter(|value|!matches!(value,Value::None)){message.push_str(" -> ");message.push_str(&self.repr(filename2)?);}
            }
            Ok(message)
        })())
    }
    fn file_read(&mut self,file:&IoFile,count:Option<usize>,line:bool,once:bool)->PyResult<Value> {
        file.check()?;
        match &file.payload {
            FilePayload::Text(text)=>Ok(Value::Str(text.borrow_mut().read(count,line)?.into())),
            FilePayload::Buffer(buffer)=>Ok(Value::Bytes(buffer.borrow_mut().read(count,line,once)?.into())),
            FilePayload::Raw(raw)=>{
                let mut output=Vec::new();
                if line {let mut byte=[0];while count!=Some(output.len()) {if raw.borrow_mut().read(&mut byte)?==0{break;}output.push(byte[0]);if byte[0]==b'\n'{break;}}}
                else if let Some(count)=count {output.try_reserve(count).map_err(|_|file_memory())?;output.resize(count,0);let size=raw.borrow_mut().read(&mut output)?;output.truncate(size);}
                else {let mut chunk=[0;8192];loop{let size=raw.borrow_mut().read(&mut chunk)?;if size==0{break;}output.try_reserve(size).map_err(|_|file_memory())?;output.extend_from_slice(&chunk[..size]);}}
                Ok(Value::Bytes(output.into()))
            },
        }
    }
    fn file_write(&mut self,file:&IoFile,value:Value)->PyResult<Value> {
        if let FilePayload::Text(text)=&file.payload {
            let payload=self.native_payload(&value).unwrap_or(value);
            let Value::Str(value)=payload else{return Err(pyerr("TypeError","write() argument must be str"));};
            return Ok(file_position(text.borrow_mut().write(&value)? as u64));
        }
        self.view_rooted(vec![value.clone()],|runtime,root|{
            // Keep the export live until after the OS/buffer operation. A
            // release callback can inspect the written file or reenter I/O.
            let view=runtime.buffer_memoryview(value,0)?;runtime.roots[root].push(view.clone());
            let result=(||{
                let metadata=runtime.buffer_view(&view)?;
                let bytes=runtime.buffer_view_bytes(&metadata,false)?;
                let count=match &file.payload{FilePayload::Raw(raw)=>raw.borrow_mut().write(&bytes)?,FilePayload::Buffer(buffer)=>buffer.borrow_mut().write(&bytes)?,FilePayload::Text(_)=>unreachable!()};
                Ok(file_position(count as u64))
            })();
            let released=runtime.buffer_release(view);match result{Ok(result)=>{released?;Ok(result)},Err(error)=>{let _=released;Err(error)}}
        })
    }
    fn file_readinto(&mut self,file:&IoFile,value:Value,once:bool)->PyResult<Value> {
        self.view_rooted(vec![value.clone()],|runtime,root|{
            let kind=runtime.typename(&value);
            let view=runtime.buffer_memoryview(value,1).map_err(|_|pyerr("TypeError",format!("readinto() argument must be read-write bytes-like object, not {kind}")))?;
            runtime.roots[root].push(view.clone());
            let result=(||{
                let metadata=runtime.buffer_view(&view)?;
                let count=metadata.shape.iter().try_fold(metadata.itemsize,|size,dimension|size.checked_mul(*dimension))
                    .filter(|size|*size<=isize::MAX as usize).ok_or_else(||pyerr("OverflowError","buffer size is too large"))?;
                let lease=runtime.buffer_lease(metadata.lease)?;
                let offset=usize::try_from(metadata.offset).map_err(|_|pyerr("BufferError","invalid contiguous buffer offset"))?;
                let bytes=match &file.payload{
                    FilePayload::Buffer(buffer)=>buffer.borrow_mut().readinto_bytes(count,once)?,
                    FilePayload::Raw(raw)=>{let mut bytes=Vec::new();bytes.try_reserve(count).map_err(|_|file_memory())?;bytes.resize(count,0);let size=raw.borrow_mut().read(&mut bytes)?;bytes.truncate(size);bytes},
                    FilePayload::Text(_)=>return Err(pyerr("TypeError","readinto requires a binary stream")),
                };
                let mut data=runtime.buffer_owner_data(&lease.owner)?;
                let end=offset.checked_add(bytes.len()).filter(|end|*end<=data.len()).ok_or_else(||pyerr("BufferError","buffer bounds changed during I/O"))?;
                data[offset..end].copy_from_slice(&bytes);
                runtime.buffer_replace(lease.owner,data)?;
                Ok(file_position(bytes.len() as u64))
            })();
            let released=runtime.buffer_release(view);match result{Ok(result)=>{released?;Ok(result)},Err(error)=>{let _=released;Err(error)}}
        })
    }
    fn file_method(&mut self,name:&str,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<Value> {
        let value=args.first().cloned().ok_or_else(||pyerr("TypeError","unbound file method requires an instance"))?;
        let file=self.file_value(&value).ok_or_else(||pyerr("TypeError","descriptor requires a file object"))?;
        let args=args[1..].to_vec();
        if name=="reconfigure"{return self.file_reconfigure(file,args,kwargs);}
        if !kwargs.is_empty(){return Err(pyerr("TypeError",format!("{name}() takes no keyword arguments")));}
        let root=self.roots.len();self.roots.push(std::iter::once(value.clone()).chain(args.iter().cloned()).collect());
        let result=(||{
            match name {
                "__enter__"=>{file.check()?;if !args.is_empty(){return Err(pyerr("TypeError","__enter__ takes no arguments"));}return Ok(value.clone());},
                "__exit__"=>{if args.len()!=3{return Err(pyerr("TypeError","__exit__ takes three arguments"));}file.close()?;return Ok(Value::None);},
                "__iter__"=>{file.check()?;if !args.is_empty(){return Err(pyerr("TypeError","__iter__ takes no arguments"));}return Ok(value.clone());},
                "__next__"=>{
                    if let FilePayload::Text(text)=&file.payload{text.borrow_mut().telling=false;}
                    let result=self.file_read(&file,None,true,false)?;
                    if matches!(&result,Value::Str(value)if value.is_empty())||matches!(&result,Value::Bytes(value)if value.is_empty()){
                        if let FilePayload::Text(text)=&file.payload{text.borrow_mut().telling=true;}
                        return Err(pyerr("StopIteration",""));
                    }
                    return Ok(result);
                },
                "__repr__"=>return Ok(Value::Str(self.file_repr(&file)?.into())),
                "__getstate__"=>return Err(pyerr("TypeError","cannot pickle file objects")),
                "close"|"__del__"=>{if !args.is_empty(){return Err(pyerr("TypeError","close() takes no arguments"));}file.close()?;return Ok(Value::None);},
                "flush"=>{if !args.is_empty(){return Err(pyerr("TypeError","flush() takes no arguments"));}file.flush()?;return Ok(Value::None);},
                "closed"=>return Ok(Value::Bool(file.closed()?)),
                "readable"|"writable"|"seekable"|"isatty"|"fileno"=>{
                    if !args.is_empty(){return Err(pyerr("TypeError",format!("{name}() takes no arguments")));}
                    let (readable,writable)=file.capabilities()?;
                    let raw=file.raw()?;let mut raw=raw.borrow_mut();raw.check()?;
                    return Ok(match name {"readable"=>Value::Bool(readable),"writable"=>Value::Bool(writable),"isatty"=>Value::Bool(raw.isatty()?),"fileno"=>file_position(raw.fileno()? as u64),_=>Value::Bool(raw.seek(0,1).is_ok())});
                },
                "read"|"read1"|"readline"|"readall"=>{
                    if args.len()>1 || name=="readall"&&!args.is_empty(){return Err(pyerr("TypeError",format!("{name}() takes at most one argument")));}
                    if args.first().is_some_and(|value|matches!(value,Value::None))&&(name=="read1"||name=="readline"&&matches!(file.payload,FilePayload::Text(_))){return Err(pyerr("TypeError","'NoneType' object cannot be interpreted as an integer"));}
                    let count=match args.first(){None|Some(Value::None)=>None,Some(value)=>self.stream_size(value)?};
                    return self.file_read(&file,count,name=="readline",name=="read1");
                },
                "readlines"=>{
                    if args.len()>1{return Err(pyerr("TypeError","readlines() takes at most one argument"));}
                    let hint=match args.first(){None|Some(Value::None)=>None,Some(value)=>self.stream_size(value)?};
                    let mut output=Vec::new();let mut size=0usize;
                    loop {if let FilePayload::Text(text)=&file.payload{text.borrow_mut().telling=false;}let line=self.file_read(&file,None,true,false)?;let length=match &line{Value::Str(value)=>value.chars().count(),Value::Bytes(value)=>value.len(),_=>unreachable!()};if length==0{if let FilePayload::Text(text)=&file.payload{text.borrow_mut().telling=true;}break;}size=size.saturating_add(length);output.push(line);if hint.is_some_and(|hint|hint>0&&size>hint){break;}}
                    return Ok(self.obj_value(Object::List(output)));
                },
                "write"=>{if args.len()!=1{return Err(pyerr("TypeError","write() takes exactly one argument"));}return self.file_write(&file,args[0].clone());},
                "readinto"|"readinto1"=>{if args.len()!=1{return Err(pyerr("TypeError","readinto() takes exactly one argument"));}return self.file_readinto(&file,args[0].clone(),name=="readinto1");},
                "writelines"=>{
                    if args.len()!=1{return Err(pyerr("TypeError","writelines() takes exactly one argument"));}
                    file.check()?;let iterator=self.iter(args[0].clone())?;self.roots[root].push(iterator.clone());
                    while let Some(line)=self.next(iterator.clone())?{self.file_write(&file,line)?;}
                    return Ok(Value::None);
                },
                "tell"=>{
                    if !args.is_empty(){return Err(pyerr("TypeError","tell() takes no arguments"));}
                    let position=match &file.payload{FilePayload::Raw(raw)=>raw.borrow_mut().seek(0,1)?,FilePayload::Buffer(buffer)=>buffer.borrow_mut().tell()?,FilePayload::Text(text)=>text.borrow_mut().tell()?};
                    return Ok(file_position(position));
                },
                "seek"=>{
                    if args.is_empty()||args.len()>2{return Err(pyerr("TypeError","seek() takes one or two arguments"));}
                    let offset=self.file_index(&args[0])?;let whence=if args.len()==2{self.file_index(&args[1])?}else{0};
                    let whence=i32::try_from(whence).map_err(|_|pyerr("OverflowError","whence is too large"))?;
                    let position=match &file.payload{FilePayload::Raw(raw)=>raw.borrow_mut().seek(offset,whence)?,FilePayload::Buffer(buffer)=>buffer.borrow_mut().seek(offset,whence)?,FilePayload::Text(text)=>text.borrow_mut().seek(offset,whence)?};
                    return Ok(file_position(position));
                },
                "truncate"=>{
                    if args.len()>1{return Err(pyerr("TypeError","truncate() takes at most one argument"));}
                    let raw=file.raw()?;
                    let size=match args.first().filter(|value|!matches!(value,Value::None)){
                        Some(value)=>{let size=self.file_index(value)?;if size<0{return Err(file_os_error(std::io::Error::from_raw_os_error(22)));}size as u64},
                        None=>match &file.payload{FilePayload::Raw(raw)=>raw.borrow_mut().seek(0,1)?,FilePayload::Buffer(buffer)=>buffer.borrow_mut().tell()?,FilePayload::Text(text)=>{let text=text.borrow();text.buffer()?.borrow_mut().flush()?;text.buffer()?.borrow_mut().tell()?}},
                    };
                    match &file.payload{FilePayload::Raw(raw)=>raw.borrow_mut().truncate(size)?,FilePayload::Buffer(buffer)=>buffer.borrow_mut().truncate(size)?,FilePayload::Text(text)=>text.borrow().buffer()?.borrow_mut().truncate(size)?};
                    return Ok(file_position(size));
                },
                "peek"=>{
                    if args.len()>1{return Err(pyerr("TypeError","peek() takes at most one argument"));}
                    if let Some(size)=args.first(){self.file_index(size)?;}
                    let FilePayload::Buffer(buffer)=&file.payload else{return Err(file_unsupported("peek"));};
                    let mut buffer=buffer.borrow_mut();buffer.fill()?;
                    return Ok(Value::Bytes(buffer.input[buffer.at..].to_vec().into()));
                },
                "detach"=>{
                    if !args.is_empty(){return Err(pyerr("TypeError","detach() takes no arguments"));}
                    file.flush()?;let child=file.child.clone().ok_or_else(||pyerr("ValueError","underlying buffer has been detached"))?;
                    match &file.payload {FilePayload::Buffer(buffer)=>{buffer.borrow_mut().raw.take();},FilePayload::Text(text)=>{text.borrow_mut().buffer.take();},FilePayload::Raw(_)=>return Err(file_unsupported("detach"))}
                    let Value::Obj(index)=value else{unreachable!()};let mut detached=file.clone();detached.child=None;self.heap[index]=Some(Object::IoFile(detached));return Ok(child);
                },
                _=>return Err(pyerr("NotImplementedError",format!("file method {name} is not yet implemented"))),
            }
        })();self.roots.truncate(root);result
    }
    fn file_reconfigure(&mut self,file:IoFile,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<Value> {
        if !args.is_empty(){return Err(pyerr("TypeError","reconfigure() takes no positional arguments"));}
        let values=codec_bind("reconfigure",args,kwargs,&["encoding","errors","newline","line_buffering","write_through"])?;
        let FilePayload::Text(text)=&file.payload else{return Err(file_unsupported("reconfigure"));};
        let old_encoding=text.borrow().encoding.clone();let old_errors=text.borrow().errors.clone();
        let encoding=values[0].as_ref().filter(|value|!matches!(value,Value::None));
        let errors=values[1].as_ref().filter(|value|!matches!(value,Value::None));
        let new_encoding=codec_argument(self,encoding,&old_encoding,"encoding")?;
        let new_errors=codec_argument(self,errors,if encoding.is_some(){"strict"}else{&old_errors},"errors")?;
        TextCodec::lookup(if new_encoding=="locale"{"utf-8"}else{&new_encoding})?;
        let newline=match &values[2]{None=>text.borrow().newline.clone(),Some(Value::None)=>None,Some(value)=>Some(codec_argument(self,Some(value),"","newline")?)};
        if newline.as_ref().is_some_and(|value|!matches!(value.as_str(),""|"\n"|"\r"|"\r\n")){return Err(pyerr("ValueError","illegal newline value"));}
        let line_buffering=match values[3].as_ref().filter(|value|!matches!(value,Value::None)){Some(value)=>self.truth(value)?,None=>text.borrow().line_buffering};
        let write_through=match values[4].as_ref().filter(|value|!matches!(value,Value::None)){Some(value)=>self.truth(value)?,None=>text.borrow().write_through};
        let mut text=text.borrow_mut();
        if text.read_started&&(encoding.is_some()||errors.is_some()||values[2].is_some()){return Err(file_unsupported("It is not possible to set the encoding or newline of stream after the first read"));}
        text.flush()?;
        text.encoding=if new_encoding=="locale"{"UTF-8".into()}else{new_encoding};text.errors=new_errors;text.newline=newline;
        text.line_buffering=line_buffering;text.write_through=write_through;
        Ok(Value::None)
    }
}
