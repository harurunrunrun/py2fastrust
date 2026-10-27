// Class creation and type calls retain callback state in their Python caller.
#[derive(Clone,Debug)]
struct ClassConstruction { out:Value, ns:usize, slot_names:Vec<String>, kw:KeywordArgs }
impl ClassConstruction {
    fn roots(&self,out:&mut Vec<Value>) {out.extend([self.out.clone(),Value::Obj(self.ns)]);out.extend(self.kw.iter().flat_map(|(key,value)|[key.original.clone(),value.clone()]));}
}
#[derive(Clone,Debug)]
enum ProtocolClass {
    New{class:Value,args:Vec<Value>,kw:KeywordArgs},
    Init(Value),
    Payload{class:Value,base:Value},
    Alias(Value),
    AliasDone{alias:Value,result:Value},
    Slots{meta:Value,args:Vec<Value>,kw:KeywordArgs},
    Namespace{meta:Value,args:Vec<Value>,kw:KeywordArgs},
    Mro(ClassConstruction),
    GenericReady(ClassConstruction),
    Names{record:ClassConstruction,items:Vec<(Value,Value)>,index:usize},
    Ready(Value),
    Keep(Value),
    Load(String),
    Delete(String),
    Annotations,
    Build{data:ClassStatement,phase:ClassStatementPhase},
}
#[derive(Clone,Debug)]
enum ClassStatementPhase { BaseLookup, BaseEntries, KeywordHash, KeywordEqual, KeywordTruth, PrepareLookup, Prepared, Body, Write, Done }
#[derive(Clone,Debug)]
struct ClassStatement {
    function:Value,name:Value,bases:Vec<Value>,original:Value,resolved:Vec<Value>,index:usize,
    changed:bool,kw:KeywordArgs,meta:Value,bases_value:Value,namespace:Option<usize>,
    environment:Option<usize>,code:Option<usize>,cell:Option<usize>,writes:Vec<(String,Value)>,write_index:usize,
}
impl ProtocolClass {
    fn roots(&self,out:&mut Vec<Value>) {match self {
        Self::New{class,args,kw}|Self::Slots{meta:class,args,kw}|Self::Namespace{meta:class,args,kw}=>{out.push(class.clone());out.extend(args.iter().cloned());out.extend(kw.iter().flat_map(|(key,value)|[key.original.clone(),value.clone()]));},
        Self::Init(value)|Self::Ready(value)|Self::Keep(value)|Self::Alias(value)=>out.push(value.clone()),
        Self::AliasDone{alias,result}=>out.extend([alias.clone(),result.clone()]),
        Self::Payload{class,base}=>out.extend([class.clone(),base.clone()]),
        Self::Mro(record)|Self::GenericReady(record)=>record.roots(out),
        Self::Names{record,items,..}=>{record.roots(out);out.extend(items.iter().flat_map(|(key,value)|[key.clone(),value.clone()]));},
        Self::Build{data,..}=>{out.extend([data.function.clone(),data.name.clone(),data.original.clone(),data.meta.clone(),data.bases_value.clone()]);out.extend(data.bases.iter().chain(&data.resolved).cloned());out.extend(data.kw.iter().flat_map(|(key,value)|[key.original.clone(),value.clone()]));out.extend(data.namespace.iter().chain(&data.environment).chain(&data.cell).map(|owner|Value::Obj(*owner)));out.extend(data.writes.iter().map(|(_,value)|value.clone()));},
        Self::Load(_)|Self::Delete(_)|Self::Annotations=>{},
    }}
}
impl Runtime {
    fn start_protocol_class_name(&mut self,frame:&mut Frame,name:&str,operation:&str,value:Option<Value>)->PyResult<bool> {
        if self.codes[frame.code].kind!=ScopeKind::Class || !frame.comprehensions.is_empty() || name.starts_with('$') || name.starts_with('\0') || self.codes[frame.code].globals.iter().chain(&self.codes[frame.code].nonlocals).any(|key|key==name) {return Ok(false);}
        let mapping=self.execution_locals_value(frame.locals);
        let method=match operation {"store"=>"__setitem__","delete"=>"__delitem__",_=>"__getitem__"};
        let Some((descriptor,class))=self.protocol_slot(&mapping,method) else{return Ok(false)};
        let mut state=Self::protocol_empty(if operation=="load"{ProtocolSink::Stack}else{ProtocolSink::Discard});
        let after=match operation {"load"=>ProtocolAction::Class(Box::new(ProtocolClass::Load(name.into()))),"delete"=>ProtocolAction::Class(Box::new(ProtocolClass::Delete(name.into()))),"annotations"=>ProtocolAction::Class(Box::new(ProtocolClass::Annotations)),_=>ProtocolAction::DiscardResult};
        let mut args=vec![Value::Str(name.into())];args.extend(value);
        self.protocol_bind(&mut state,descriptor,mapping,class,args,Vec::new(),after,false)?;
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn protocol_class_catches(&mut self,record:&ProtocolClass,error:&PyException,frame:Option<&Frame>)->PyResult<bool> {
        Ok(match record {
            ProtocolClass::AliasDone{alias,..}=>if self.generic_is_typing_alias(alias){let mut error=error.clone();let value=self.exception_value(&mut error);self.exception_match(&value,&Value::Type("Exception".into()))?}
                else{self.exception_has_native_class(error,"AttributeError")||self.exception_has_native_class(error,"TypeError")},
            ProtocolClass::Delete(_)=>true,
            ProtocolClass::Load(_)|ProtocolClass::Annotations=>frame.is_some()&&self.exception_has_native_class(error,"KeyError"),
            _=>false,
        })
    }
    fn protocol_class_failure(&mut self,frame:Option<&Frame>,state:&mut ProtocolState,error:&PyException)->PyResult<bool> {
        let attribute=self.exception_has_native_class(error,"AttributeError");
        let type_error=self.exception_has_native_class(error,"TypeError");
        let stop=self.exception_has_native_class(error,"StopIteration");
        let index_error=self.exception_has_native_class(error,"IndexError");
        let mut boundary=None;
        // Queue order follows native call nesting. An outer class callback
        // must not swallow an exception owned by an inner native operation.
        for (index,action) in state.actions.iter().enumerate() {
            let inner=match action {
                ProtocolAction::Input(data)=>data.ignores_failure(),
                ProtocolAction::TextPercent(data)=>type_error&&matches!(data.phase,TextPercentPhase::Integer(_)|TextPercentPhase::Character),
                ProtocolAction::Consumer(data)=>type_error&&data.phase==2,
                ProtocolAction::Stream(data)=>match data.as_ref() {
                    ProtocolStream::ToolConstructor{data,phase:1} if data.name=="islice"=>true,
                    ProtocolStream::SequenceItem{..}=>stop||index_error,
                    ProtocolStream::NextBoundary{..}|ProtocolStream::CallableValue{..}|ProtocolStream::Tool{fetch:true,..}|ProtocolStream::Collect{strict:true,position:1..,..}|ProtocolStream::StrictProbe{..}|ProtocolStream::ToolConstructor{phase:4,..}=>stop,
                    _=>false,
                },
                ProtocolAction::AttributeDone=>attribute&&state.attribute_recovery.is_some(),
                ProtocolAction::EndBinding(_)|ProtocolAction::StringResult(_)|ProtocolAction::StrictBool|ProtocolAction::HashResult|ProtocolAction::IteratorResult|ProtocolAction::Operand(_)|ProtocolAction::ContainsResult=>attribute&&state.binding_recovery.is_some(),
                _=>false,
            };
            if inner{return Ok(false);}
            if let ProtocolAction::Class(record)=action {if self.protocol_class_catches(record,error,frame)?{boundary=Some(index);break;}}
        }
        let Some(boundary)=boundary else{return Ok(false)};
        let ProtocolAction::Class(record)=self.protocol_discard_actions(state,boundary+1).pop().unwrap() else{unreachable!()};
        state.plan=None;state.value=None;state.binding_recovery=None;state.attribute_recovery=None;
        match *record {
            ProtocolClass::AliasDone{result,..}=>state.value=Some(result),
            ProtocolClass::Load(name)=>state.value=Some(self.load_after_locals(frame.unwrap(),&name,false)?),
            ProtocolClass::Delete(name)=>return Err(pyerr("NameError",format!("name '{}' is not defined",name))),
            ProtocolClass::Annotations=>{let value=self.obj_value(Object::Dict(Vec::new()));self.protocol_class_mapping_set(state,frame.unwrap().locals,"__annotations__".into(),value)?;}
            _=>unreachable!(),
        }
        Ok(true)
    }
    fn protocol_class_base(&mut self,state:&mut ProtocolState,mut data:ClassStatement)->PyResult<()> {
        while data.index<data.bases.len() {
            let base=data.bases[data.index].clone();
            if self.native_is_class(&base) {data.resolved.push(base);data.index+=1;continue;}
            self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::BaseLookup},Value::None);
            self.protocol_class_plan(state,Value::Builtin("getattr".into()),vec![base,Value::Str("__mro_entries__".into()),Value::Builtin("$class:missing".into())],Vec::new());return Ok(());
        }
        data.index=0;self.protocol_class_keyword(state,data,None)
    }
    fn protocol_class_keyword(&mut self,state:&mut ProtocolState,mut data:ClassStatement,mut computed:Option<i64>)->PyResult<()> {
        let lookup=Value::Str("metaclass".into());let lookup_hash=self.frozen_member_hash(&lookup)?;
        while data.index<data.kw.len() {
            let keyword=data.kw[data.index].0.clone();
            let hash=if let Some(hash)=computed.take().or(keyword.hash){hash}else{
                self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::KeywordHash},Value::None);
                self.protocol_class_plan(state,Value::Builtin("hash".into()),vec![keyword.original],Vec::new());return Ok(());
            };
            if hash==lookup_hash {
                self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::KeywordEqual},Value::None);
                self.protocol_compare_into(state,"==".into(),keyword.original,lookup)?;return Ok(());
            }
            data.index+=1;
        }
        self.protocol_class_select_meta(state,data,None)
    }
    fn protocol_class_select_meta(&mut self,state:&mut ProtocolState,mut data:ClassStatement,index:Option<usize>)->PyResult<()> {
        let mut meta=index.map(|index|data.kw.remove(index).1).unwrap_or(Value::Builtin("type".into()));
        if self.native_is_class(&meta) {
            for base in &data.resolved {
                let other=self.object_class(base).filter(|_|matches!(base,Value::Obj(owner)if matches!(self.heap.get(*owner).and_then(Option::as_ref),Some(Object::Class(_))))).unwrap_or(Value::Builtin("type".into()));
                if self.is_subclass(&meta,&other)?{continue;}
                if self.is_subclass(&other,&meta)?{meta=other;continue;}
                return Err(pyerr("TypeError","metaclass conflict: the metaclass of a derived class must be a subclass of the metaclasses of all its bases"));
            }
        }
        data.meta=meta.clone();data.bases_value=self.obj_value(Object::Tuple(data.resolved.clone()));
        self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::PrepareLookup},Value::None);
        self.protocol_class_plan(state,Value::Builtin("getattr".into()),vec![meta,Value::Str("__prepare__".into()),Value::Builtin("$class:missing".into())],Vec::new());Ok(())
    }
    fn protocol_class_mapping_set(&mut self,state:&mut ProtocolState,owner:usize,name:String,value:Value)->PyResult<()> {
        let mapping=self.execution_locals_value(owner);
        if let Some((method,class))=self.protocol_slot(&mapping,"__setitem__") {
            self.protocol_bind(state,method,mapping,class,vec![Value::Str(name.into()),value],Vec::new(),ProtocolAction::Pass,false)
        }else{self.mapping_set(owner,name,value)?;state.value=Some(Value::None);Ok(())}
    }
    fn protocol_class_statement_result(&mut self,state:&mut ProtocolState,mut data:ClassStatement,phase:ClassStatementPhase,value:Value)->PyResult<()> {
        match phase {
            ClassStatementPhase::BaseLookup=>{
                if matches!(&value,Value::Builtin(name)if name=="$class:missing") {data.resolved.push(data.bases[data.index].clone());data.index+=1;self.protocol_class_base(state,data)?;}
                else{let original=data.original.clone();self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::BaseEntries},Value::None);self.protocol_class_plan(state,value,vec![original],Vec::new());}
            }
            ClassStatementPhase::BaseEntries=>{
                let payload=self.native_payload(&value).unwrap_or(value);
                let values=match payload{Value::Obj(owner)=>match self.object(owner)?{Object::Tuple(values)=>values,_=>return Err(pyerr("TypeError","__mro_entries__ must return a tuple"))},_=>return Err(pyerr("TypeError","__mro_entries__ must return a tuple"))};
                data.resolved.extend(values);data.index+=1;data.changed=true;self.protocol_class_base(state,data)?;
            }
            ClassStatementPhase::KeywordHash=>{let hash=self.as_int(&value)?.to_i128().ok_or_else(||pyerr("TypeError","invalid keyword hash"))? as i64;self.protocol_class_keyword(state,data,Some(hash))?;}
            ClassStatementPhase::KeywordEqual=>{
                self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::KeywordTruth},Value::None);
                if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}
            }
            ClassStatementPhase::KeywordTruth=>{
                if self.truth(&value)?{let index=data.index;self.protocol_class_select_meta(state,data,Some(index))?;}
                else{data.index+=1;self.protocol_class_keyword(state,data,None)?;}
            }
            ClassStatementPhase::PrepareLookup=>{
                if matches!(&value,Value::Builtin(name)if name=="$class:missing") {
                    let namespace=self.obj_value(Object::Dict(Vec::new()));self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::Prepared},namespace);
                }else{
                    let args=vec![data.name.clone(),data.bases_value.clone()];let kw=data.kw.clone();self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::Prepared},Value::None);self.protocol_class_plan(state,value,args,kw);
                }
            }
            ClassStatementPhase::Prepared=>{
                let Value::Obj(namespace)=value else{return Err(pyerr("TypeError","__prepare__ must return a mapping"))};
                let function=match &data.function{Value::Obj(owner)=>match self.object(*owner)?{Object::Function(function)=>function,_=>unreachable!()},_=>unreachable!()};
                let code=function.code;let env=self.alloc(Object::Namespace(OrderedNamespace::new(),function.closure));
                self.scope_parents.insert(namespace,env);self.scope_bindings.insert(namespace,self.codes[code].locals.clone());
                data.namespace=Some(namespace);data.environment=Some(env);data.code=Some(code);
                let class_body=self.codes[code].kind==ScopeKind::Class;let owner=data.function.clone();
                self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::Body},Value::None);
                if class_body{self.protocol_class_plan(state,Value::Builtin("$protocol:class_body".into()),vec![owner,Value::Obj(namespace),Value::Obj(env),Value::Int(Int::from_i128(code as i128).into())],Vec::new());}
                else{self.protocol_class_plan(state,owner,Vec::new(),Vec::new());}
            }
            ClassStatementPhase::Body=>{
                let code=data.code.unwrap();let namespace=data.namespace.unwrap();let env=data.environment.unwrap();
                let methods=self.codes[code].function_codes();
                let has_method=methods.iter().any(|index|self.codes[*index].kind==ScopeKind::Function&&!self.codes[*index].name.starts_with('<'));
                if self.codes[code].kind==ScopeKind::Class && (self.code_needs_class_dict(code,0)||(has_method&&self.codes[code].future_flags&0x1000000==0)) {
                    let cell=Value::Obj(self.closure_cell(Some(namespace),"__classdict__")?);data.writes.push(("__classdictcell__".into(),cell));
                }
                if self.codes[code].kind==ScopeKind::Class && methods.iter().any(|index|self.code_needs_class_cell(*index,0)) {
                    let cell=self.closure_cell(Some(env),"__class__")?;data.cell=Some(cell);data.writes.push(("__classcell__".into(),Value::Obj(cell)));
                }
                if data.changed{data.writes.push(("__orig_bases__".into(),data.original.clone()));}
                self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::Write},Value::None);
            }
            ClassStatementPhase::Write=>{
                if let Some((name,value))=data.writes.get(data.write_index).cloned() {
                    data.write_index+=1;let owner=data.namespace.unwrap();self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::Write},Value::None);self.protocol_class_mapping_set(state,owner,name,value)?;
                }else{
                    let meta=data.meta.clone();let args=vec![data.name.clone(),data.bases_value.clone(),Value::Obj(data.namespace.unwrap())];let kw=data.kw.clone();
                    self.protocol_class_queue(state,ProtocolClass::Build{data,phase:ClassStatementPhase::Done},Value::None);self.protocol_class_plan(state,meta,args,kw);
                }
            }
            ClassStatementPhase::Done=>{
                if self.native_is_class(&value) {
                    if let Some(cell)=data.cell {match self.object(cell)? {
                        Object::Cell(Some(contents))if contents.same_identity(&value)=>{},
                        Object::Cell(Some(_))=>return Err(pyerr("TypeError","__class__ set to a different object when defining class")),
                        _=>return Err(pyerr("RuntimeError","__class__ not set; was __classcell__ propagated to type.__new__?")),
                    }}
                }
                let binding=if let Some(cell)=data.cell{match self.object(cell)?{Object::Cell(contents)=>contents,_=>None}}else{Some(value.clone())};
                if let Some(binding)=binding{self.ns_set(data.environment.unwrap(),"__class__".into(),binding);}
                if let Value::Obj(owner)=&value {if let Object::Class(class)=self.object(*owner)?{self.annotation_namespaces.insert(data.namespace.unwrap(),class.attrs);}}
                state.value=Some(value);
            }
        }Ok(())
    }
    fn protocol_class_queue(&mut self,state:&mut ProtocolState,record:ProtocolClass,value:Value) {
        state.actions.push_front(ProtocolAction::Class(Box::new(record)));state.value=Some(value);
    }
    fn protocol_class_plan(&mut self,state:&mut ProtocolState,function:Value,args:Vec<Value>,kwargs:KeywordArgs) {
        state.plan=Some(ProtocolPlan{function,args,kwargs});
    }
    fn start_protocol_class_call(&mut self,frame:&mut Frame,function:Value,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<()> {
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        self.protocol_class_plan(&mut state,function,args,kwargs);frame.protocol=Some(state);self.resume_protocol(frame)
    }
    fn protocol_type_instance(&mut self,state:&mut ProtocolState,class:Value,args:Vec<Value>,kw:KeywordArgs,custom_call:bool)->PyResult<bool> {
        if !custom_call && matches!(&class,Value::Builtin(_)|Value::Type(_)) && self.native_is_class(&class) {
            self.protocol_class_plan(state,class,args,kw);return Ok(true);
        }
        let Value::Obj(owner)=class.clone() else{return Ok(false)};
        let Object::Class(definition)=self.object(owner)? else{return Ok(false)};
        if definition.mro_value.is_none(){return Err(pyerr("TypeError","cannot instantiate an incomplete class"));}
        if custom_call {
            if let Some(method)=self.slot_override(&definition.metaclass,"__call__",0) {
                self.protocol_bind(state,method,class,definition.metaclass,args,kw,ProtocolAction::Pass,false)?;return Ok(true);
            }
        }
        if self.is_subclass(&class,&Value::Type("BaseException".into()))? && self.slot_override(&class,"__new__",0).is_none() {
            let object=if self.is_subclass(&class,&Value::Type("BaseExceptionGroup".into()))? {
                self.exception_group_construct(class.clone(),args.clone(),kw.clone())?
            }else{
                if !kw.is_empty() && self.slot_override(&class,"__init__",0).is_none(){return Err(pyerr("TypeError",format!("{}() takes no keyword arguments",self.class_name(&class))));}
                let mut error=self.exception_new_for_class(class.clone(),args.clone())?;self.exception_value(&mut error)
            };
            self.protocol_class_queue(state,ProtocolClass::New{class,args,kw},object);return Ok(true);
        }
        match definition.allocator {
            ClassAllocator::Native(base)=>{
                state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::New{class:class.clone(),args:args.clone(),kw:kw.clone()})));
                self.protocol_class_native_allocate(state,base,class,args,kw)?;return Ok(true);
            }
            ClassAllocator::Missing=>return Err(pyerr("TypeError","cannot create class instances")),
            ClassAllocator::Dynamic=>{},
        }
        if let Some(new)=self.class_attribute_lookup(&class,"__new__") {
            let mut incoming=vec![class.clone()];incoming.extend(args.iter().cloned());
            state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::New{class:class.clone(),args,kw:kw.clone()})));
            self.protocol_bind_value(state,new,None,class,ProtocolAction::Invoke(incoming,kw))?;
        }else{
            if !self.is_subclass(&class,&Value::Builtin("object".into()))?{return Err(pyerr("TypeError","cannot create class instances"));}
            let attrs=self.alloc(Object::Dict(Vec::new()));let value=self.obj_value(Object::Instance{class:class.clone(),attrs});
            self.protocol_class_queue(state,ProtocolClass::New{class,args,kw},value);
        }
        Ok(true)
    }
    fn protocol_class_native_allocate(&mut self,state:&mut ProtocolState,base:Value,class:Value,mut args:Vec<Value>,mut kw:KeywordArgs)->PyResult<()> {
        let Value::Builtin(name)=&base else{state.value=Some(self.class_native_allocate(base,class,args,kw)?);return Ok(())};
        if name=="type" {return self.protocol_class_construct(state,class,args,kw);}
        if ["object","list","dict","set","bytearray"].contains(&name.as_str()) {
            state.value=Some(self.class_native_allocate(base,class,args,kw)?);return Ok(());
        }
        if name=="tuple" && (args.len()>1||!kw.is_empty()){return Err(pyerr("TypeError","tuple.__new__ takes at most one iterable argument"));}
        if name=="frozenset" {
            if args.len()>1||(!kw.is_empty()&&self.slot_override(&class,"__init__",0).is_none()){return Err(pyerr("TypeError","frozenset expected one positional argument"));}kw.clear();
        }
        if name=="float" && self.slot_override(&class,"__init__",0).is_some_and(|value|!matches!(native_attribute_parts(&value),Some((_,"object","__init__")))) {kw.clear();}
        if name=="int" {
            if args.len()>2||kw.iter().any(|(name,_)|name!="base"){return Err(pyerr("TypeError","invalid arguments to int.__new__"));}
            if let Some((_,base))=kw.first() {
                if args.len()!=1{return Err(pyerr("TypeError","invalid base argument to int.__new__"));}args.push(base.clone());
            }kw.clear();
            if args.len()==2 && !matches!(args[0],Value::Str(_)|Value::Bytes(_)){return Err(pyerr("TypeError","int() can't convert non-string with explicit base"));}
        }
        if stdlib_type_name(name) && !self.mro_cached_subtype(&class,&base)
            && (name=="functools.partial"||["itertools.accumulate","itertools.chain","itertools.cycle","itertools.dropwhile","itertools.filterfalse","itertools.groupby","itertools.islice","itertools.pairwise","itertools.starmap","itertools.takewhile"].contains(&name.as_str())) {
            return Err(pyerr("TypeError","native allocator requires its defining base in the MRO"));
        }
        let function=base.clone();state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::Payload{class,base})));
        self.protocol_class_plan(state,function,args,kw);Ok(())
    }
    fn protocol_class_construct(&mut self,state:&mut ProtocolState,meta:Value,args:Vec<Value>,kw:KeywordArgs)->PyResult<()> {
        if args.len()!=3{return Err(pyerr("TypeError","type() takes 1 or 3 arguments"));}
        if !matches!(self.native_payload(&args[0]).unwrap_or_else(||args[0].clone()),Value::Str(_)){return Err(pyerr("TypeError","type() argument 1 must be str"));}
        let base_values=match self.native_payload(&args[1]).unwrap_or_else(||args[1].clone()) {
            Value::Obj(owner)=>match self.object(owner)?{Object::Tuple(values)=>values,_=>return Err(pyerr("TypeError","type() argument 2 must be tuple"))},
            _=>return Err(pyerr("TypeError","type() argument 2 must be tuple")),
        };
        if !base_values.is_empty(){self.mro_best_base(&base_values)?;}
        let source=args[2].clone();self.dictionary_owner(&source).ok_or_else(||pyerr("TypeError","type namespace must be a dictionary"))?;
        let copied=self.obj_value(Object::Dict(Vec::new()));
        state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::Keep(source.clone()))));
        state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::Namespace{meta,args,kw})));
        // PyDict_Copy's empty-dictionary path does not inspect a subclass's
        // iteration or mapping methods. Nonempty copies share dict's queue.
        self.protocol_dict_copy(state,copied,source,Vec::new(),true)?;
        Ok(())
    }
    fn protocol_class_slots(&mut self,state:&mut ProtocolState,meta:Value,args:Vec<Value>,kw:KeywordArgs)->PyResult<()> {
        if args.len()>=3 {
            let namespace=self.native_payload(&args[2]).unwrap_or_else(||args[2].clone());
            if let Value::Obj(owner)=namespace {
                if let Some(Object::Dict(items))=self.heap.get(owner).and_then(Option::as_ref) {
                    if let Some(slots)=items.iter().find_map(|(key,value)|matches!(key,Value::Str(name)if name=="__slots__").then(||value.clone())) {
                        if !matches!(slots,Value::Str(_)) {
                            state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::Slots{meta,args,kw})));
                            self.protocol_class_plan(state,Value::Builtin("tuple".into()),vec![slots],Vec::new());return Ok(());
                        }
                    }
                }
            }
        }
        self.protocol_class_construct_ready(state,meta,args,kw,None)
    }
    fn protocol_class_construct_ready(&mut self,state:&mut ProtocolState,meta:Value,args:Vec<Value>,kw:KeywordArgs,slots:Option<Vec<Value>>)->PyResult<()> {
        let record=self.construct_class_prepare(meta,args,kw,slots)?;let Value::Obj(owner)=record.out else{unreachable!()};
        state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::Mro(record))));
        self.protocol_class_mro(state,owner)
    }
    fn protocol_class_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let Value::Builtin(name)=&plan.function else{return Ok(false)};
        if name=="__build_class__" {
            if plan.args.len()<2{return Err(pyerr("TypeError","__build_class__: not enough arguments"));}
            let function=plan.args[0].clone();let name=plan.args[1].clone();
            if !matches!(&function,Value::Obj(owner)if matches!(self.heap.get(*owner).and_then(Option::as_ref),Some(Object::Function(_)))){return Err(pyerr("TypeError","__build_class__: func must be a function"));}
            if !matches!(self.native_payload(&name).unwrap_or_else(||name.clone()),Value::Str(_)){return Err(pyerr("TypeError","__build_class__: name is not a string"));}
            let bases=plan.args[2..].to_vec();let original=self.obj_value(Object::Tuple(bases.clone()));
            let data=ClassStatement{function,name,bases,original,resolved:Vec::new(),index:0,changed:false,kw:plan.kwargs.clone(),meta:Value::None,bases_value:Value::None,namespace:None,environment:None,code:None,cell:None,writes:Vec::new(),write_index:0};
            self.protocol_class_base(state,data)?;return Ok(true);
        }
        if name=="type" && plan.args.len()!=1 {self.protocol_class_construct(state,Value::Builtin("type".into()),plan.args.clone(),plan.kwargs.clone())?;return Ok(true);}
        let member=native_attribute_parts(&plan.function).map(|(_,owner,method)|(owner,method)).or_else(||name.strip_prefix("type_method:").or_else(||name.strip_prefix("unbound:")).and_then(|member|member.split_once(':')));
        if let Some((owner,"__new__"))=member {
            if ["tuple","list","dict","set","str","int","float","bytes","bytearray","complex","frozenset"].contains(&owner) || stdlib_type_name(owner) {
                let class=plan.args.first().cloned().ok_or_else(||pyerr("TypeError","__new__ requires a type argument"))?;
                if !self.native_is_class(&class){return Err(pyerr("TypeError","__new__ requires a type argument"));}
                if owner=="int"&&matches!(&class,Value::Builtin(name)if name=="bool"){return Err(pyerr("TypeError","int.__new__ is not safe for bool"));}
                let args=plan.args[1..].to_vec();let kw=plan.kwargs.clone();
                if stdlib_type_name(owner) {
                    if !self.is_subclass(&class,&Value::Builtin(owner.into()))?{return Err(pyerr("TypeError","native allocator requires a subtype"));}
                }else{self.builtin_instance_validate(owner,&class,&args,&kw,false)?;}
                self.protocol_class_native_allocate(state,Value::Builtin(owner.into()),class,args,kw)?;return Ok(true);
            }
        }
        if let Some((owner,"__init__"))=member {
            if ["list","dict","set"].contains(&owner) && !plan.args.is_empty() {
                let receiver=plan.args[0].clone();self.native_validate_receiver(owner,&receiver)?;
                if plan.args.len()>2 || (owner!="dict"&&!plan.kwargs.is_empty()){return Err(pyerr("TypeError",format!("invalid arguments to {owner}.__init__")));}
                let payload=self.native_payload(&receiver).unwrap_or_else(||receiver.clone());
                let Value::Obj(index)=payload else{return Err(pyerr("TypeError","invalid built-in initialization receiver"))};
                if owner!="dict" {
                    if owner=="list"{self.protocol_sort_nonempty(index);}
                    self.heap[index]=Some(if owner=="list"{Object::List(Vec::new())}else{Object::Set(Vec::new())});
                    if owner=="set"{self.assoc_cleared(index);}
                }
                if owner=="dict" {
                    if let Some(source)=plan.args.get(1){self.protocol_dict_input(state,receiver,source.clone(),plan.kwargs.clone(),false)?;}
                    else{self.protocol_dict_keywords(state,receiver,plan.kwargs.clone(),false)?;}
                }else if let Some(source)=plan.args.get(1) {
                    if owner=="set"{self.protocol_set_input(state,receiver,vec![source.clone()],false,false)?;}
                    else{self.protocol_class_plan(state,Value::Builtin("method:extend".into()),vec![receiver,source.clone()],Vec::new());}
                }else{state.value=Some(Value::None);}
                return Ok(true);
            }
        }
        if let Some(("type",method))=member {
            if method=="__new__" {
                if plan.args.len()<4{return Err(pyerr("TypeError","type.__new__ needs arguments"));}
                self.protocol_class_construct(state,plan.args[0].clone(),plan.args[1..].to_vec(),plan.kwargs.clone())?;return Ok(true);
            }
            if method=="__call__" && !plan.args.is_empty() {return self.protocol_type_instance(state,plan.args[0].clone(),plan.args[1..].to_vec(),plan.kwargs.clone(),false);}
        }
        Ok(false)
    }
    fn protocol_class_result(&mut self,state:&mut ProtocolState,record:ProtocolClass,value:Value)->PyResult<()> {
        match record {
            ProtocolClass::New{class,args,kw}=>{
                let actual=self.native_receiver_class(&value);
                if self.is_subclass(&actual,&class)? {
                    if let Some(init)=self.class_attribute_lookup(&actual,"__init__") {
                        state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::Init(value.clone()))));
                        self.protocol_bind_value(state,init,Some(value),actual,ProtocolAction::Invoke(args,kw))?;return Ok(());
                    }
                }
                state.value=Some(value);
            }
            ProtocolClass::Init(object)=>{if !matches!(value,Value::None){return Err(pyerr("TypeError","__init__() should return None"));}state.value=Some(object);}
            ProtocolClass::Payload{class,base}=>{
                if Self::same_type(&class,&base){state.value=Some(value);return Ok(());}
                let payload=self.native_payload(&value).unwrap_or(value);
                let result=if matches!(&base,Value::Builtin(name)if stdlib_type_name(name)){self.stdlib_wrap_instance(class,payload)?}
                    else{let attrs=self.alloc(Object::Dict(Vec::new()));self.obj_value(Object::BuiltinInstance{class,attrs,payload})};
                state.value=Some(self.class_hide_allocation(result,base)?);
            }
            ProtocolClass::Alias(alias)=>{
                state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::AliasDone{alias:alias.clone(),result:value.clone()})));
                if !self.protocol_attribute_mutation(state,value.clone(),"__orig_class__".into(),Some(alias.clone()),false)? {
                    self.setattr(value,"__orig_class__",alias)?;state.value=Some(Value::None);
                }
            }
            ProtocolClass::AliasDone{result,..}=>state.value=Some(result),
            ProtocolClass::Slots{meta,args,kw}=>{let slots=self.to_vec(value)?;self.protocol_class_construct_ready(state,meta,args,kw,Some(slots))?;}
            ProtocolClass::Namespace{meta,mut args,kw}=>{args[2]=value;self.protocol_class_slots(state,meta,args,kw)?;}
            ProtocolClass::Mro(record)=>{
                let class=record.out.clone();
                if let Value::Obj(owner)=&class{self.class_init_native_capability(*owner);}
                state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::GenericReady(record))));self.protocol_class_parameters_start(state,class)?;
            }
            ProtocolClass::GenericReady(record)=>{
                self.class_construct_materialize(&record)?;
                let items=self.dict_items(Value::Obj(record.ns))?;
                self.protocol_class_queue(state,ProtocolClass::Names{record,items,index:0},Value::None);
            }
            ProtocolClass::Names{record,items,mut index}=>{
                while index<items.len() {
                    let (name,value)=items[index].clone();index+=1;
                    if let Some(class)=self.object_class(&value) {
                        if let Some(method)=self.class_lookup(&class,"__set_name__",0) {
                            let out=record.out.clone();state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::Names{record,items,index})));
                            self.protocol_bind(state,method,value,class,vec![out,name],Vec::new(),ProtocolAction::Pass,false)?;return Ok(());
                        }
                    }
                }
                let out=record.out;let mro=self.class_mro(&out,0).ok_or_else(||pyerr("TypeError","invalid class MRO"))?;
                let position=mro.iter().position(|base|Self::same_type(base,&out)).ok_or_else(||pyerr("TypeError","type is not a subtype of itself"))?;
                for base in mro.into_iter().skip(position+1) {
                    if let Value::Obj(owner)=base {if let Object::Class(class)=self.object(owner)? {
                        if let Some(method)=self.ns_get(class.attrs,"__init_subclass__") {
                            state.actions.push_front(ProtocolAction::Class(Box::new(ProtocolClass::Ready(out.clone()))));
                            self.protocol_bind_value(state,method,None,out,ProtocolAction::Invoke(Vec::new(),record.kw))?;return Ok(());
                        }
                    }}
                }
                if !record.kw.is_empty(){return Err(pyerr("TypeError","__init_subclass__() takes no keyword arguments"));}state.value=Some(out);
            }
            ProtocolClass::Ready(out)=>state.value=Some(out),
            ProtocolClass::Keep(_)=>state.value=Some(value),
            ProtocolClass::Load(_)=>state.value=Some(value),
            ProtocolClass::Delete(_)|ProtocolClass::Annotations=>state.value=Some(Value::None),
            ProtocolClass::Build{data,phase}=>self.protocol_class_statement_result(state,data,phase,value)?,
        }Ok(())
    }
}
