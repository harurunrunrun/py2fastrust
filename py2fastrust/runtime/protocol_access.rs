// Attribute and subscription adapters suspend in the initiating Python frame.
impl Runtime {
    fn protocol_empty(sink:ProtocolSink)->ProtocolState {
        ProtocolState{plan:None,value:None,actions:ProtocolActions::new(),sink,binding_recovery:None,attribute_recovery:None,repr_guards:Vec::new()}
    }
    fn protocol_bind_value(&mut self,state:&mut ProtocolState,value:Value,instance:Option<Value>,class:Value,after:ProtocolAction)->PyResult<()> {
        if let Value::Obj(index)=&value {match self.object(*index)? {
            Object::Property{get,..} if instance.is_some()=>{
                state.actions.push_front(after);
                state.plan=Some(ProtocolPlan{function:get,args:vec![instance.unwrap()],kwargs:Vec::new()});return Ok(());
            }
            Object::Function(_)|Object::Cached(_)|Object::Static(_)|Object::ClassMethod(_)=>{},
            _=>{
                if let Some((getter,owner))=self.protocol_slot(&value,"__get__") {
                    self.protocol_bind(state,getter,value,owner,vec![instance.unwrap_or(Value::None),class],Vec::new(),after,false)?;return Ok(());
                }
            }
        }}
        let value=self.bind_descriptor(value,instance,class)?;
        state.actions.push_front(after);state.value=Some(value);Ok(())
    }
    fn start_protocol_specialattr(&mut self,frame:&mut Frame,object:Value,name:&str)->PyResult<bool> {
        let Some((descriptor,class))=self.protocol_slot(&object,name) else{return Ok(false)};
        if !self.protocol_user_descriptor(&descriptor){return Ok(false);}
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        self.protocol_bind_value(&mut state,descriptor,Some(object),class,ProtocolAction::Pass)?;
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn start_protocol_getitem(&mut self,frame:&mut Frame,object:Value,key:Value)->PyResult<bool> {
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        if let Some((method,class))=self.protocol_slot(&object,"__getitem__") {
            self.protocol_bind(&mut state,method,object,class,vec![key],Vec::new(),ProtocolAction::Pass,false)?;
        }else if matches!(&object,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_)))) {
            if self.protocol_slot(&object,"__getattribute__").is_some() {
                state.actions.push_back(ProtocolAction::Invoke(vec![key],Vec::new()));
                self.protocol_attribute(&mut state,object,"__class_getitem__".into(),None,false)?;
                if let Some(recovery)=&mut state.attribute_recovery{recovery.subscription=true;}
            }else if let Some(method)=self.slot_override(&object,"__class_getitem__",0) {
                state.actions.push_back(ProtocolAction::Invoke(vec![key],Vec::new()));
                self.protocol_bind_value(&mut state,method,None,object,ProtocolAction::Pass)?;
            }else{return Ok(false);}
        }else if !self.protocol_dict_getitem(&mut state,object,key)? {return Ok(false);}
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn start_protocol_setitem(&mut self,frame:&mut Frame,object:Value,key:Value,value:Option<Value>)->PyResult<bool> {
        let name=if value.is_some(){"__setitem__"}else{"__delitem__"};
        let Some((method,class))=self.protocol_slot(&object,name) else{return self.start_protocol_collection_mutation(frame,object,key,value,false)};
        let mut state=Self::protocol_empty(ProtocolSink::Discard);
        let mut args=vec![key];args.extend(value);
        self.protocol_bind(&mut state,method,object,class,args,Vec::new(),ProtocolAction::Pass,false)?;
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn start_protocol_getattr(&mut self,frame:&mut Frame,value:Value,name:String)->PyResult<bool> {
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        if !self.protocol_attribute(&mut state,value,name,None,false)?{return Ok(false);}
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn start_protocol_setattr(&mut self,frame:&mut Frame,object:Value,name:String,value:Option<Value>)->PyResult<bool> {
        let mut state=Self::protocol_empty(ProtocolSink::Discard);
        if !self.protocol_attribute_mutation(&mut state,object,name,value,false)? {return Ok(false);}
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn protocol_attribute_mutation(&mut self,state:&mut ProtocolState,object:Value,name:String,value:Option<Value>,bypass:bool)->PyResult<bool> {
        self.protocol_attribute_mutation_key(state,object,name,value,bypass,None)
    }
    fn protocol_attribute_mutation_key(&mut self,state:&mut ProtocolState,object:Value,name:String,value:Option<Value>,bypass:bool,key:Option<Value>)->PyResult<bool> {
        let key=key.unwrap_or_else(||Value::Str(self.intern_keyword(&name)));
        let slot=if value.is_some(){"__setattr__"}else{"__delattr__"};
        if !bypass {if let Some((method,class))=self.protocol_slot(&object,slot) {
            let mut args=vec![key];args.extend(value);
            self.protocol_bind(state,method,object,class,args,Vec::new(),ProtocolAction::DiscardResult,false)?;return Ok(true);
        }}
        if let Some(class)=self.object_class(&object) {if let Some(descriptor)=self.class_attribute_lookup(&class,&name) {
            if let Value::Obj(index)=&descriptor {if let Object::Property{set,del,..}=self.object(*index)? {
                if let Some(function)=if value.is_some(){set}else{del} {
                    let mut args=vec![object];args.extend(value);
                    state.actions.push_front(ProtocolAction::DiscardResult);state.plan=Some(ProtocolPlan{function,args,kwargs:Vec::new()});return Ok(true);
                }return Ok(false);
            }}
            let method=if value.is_some(){"__set__"}else{"__delete__"};
            if let Some((method,class))=self.protocol_slot(&descriptor,method) {
                let mut args=vec![object];args.extend(value);
                self.protocol_bind(state,method,descriptor,class,args,Vec::new(),ProtocolAction::DiscardResult,false)?;return Ok(true);
            }
        }}Ok(false)
    }
    fn protocol_dict_getitem(&mut self,state:&mut ProtocolState,object:Value,key:Value)->PyResult<bool> {
        self.protocol_collection_lookup(state,object,key,ProtocolLookupOp::Get{default:None,missing:true},None)
    }
    fn protocol_native_access(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let parts=native_attribute_parts(&plan.function).map(|(_,owner,name)|(owner.to_owned(),name.to_owned()));
        let (owner,name)=match parts {
            Some(parts)=>parts,
            None=>match &plan.function {Value::Builtin(name) if name=="type_method:object:__getattribute__"=>("object".into(),"__getattribute__".into()),Value::Builtin(name) if name=="unbound:dict:__getitem__"=>("dict".into(),"__getitem__".into()),_=>return Ok(false)},
        };
        if !matches!((owner.as_str(),name.as_str()),("object","__getattribute__"|"__setattr__"|"__delattr__"|"__str__")|("dict","__getitem__")){return Ok(false);}
        let count=if name=="__str__"{1}else if name=="__setattr__"{3}else{2};
        if plan.args.len()!=count||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","invalid descriptor arguments"));}
        self.native_validate_receiver(&owner,&plan.args[0])?;
        if owner=="dict" {return self.protocol_dict_getitem(state,plan.args[0].clone(),plan.args[1].clone());}
        if name=="__str__" {return self.protocol_python_repr(state,plan.args[0].clone(),"__str__");}
        let key=match self.native_payload(&plan.args[1]).unwrap_or_else(||plan.args[1].clone()){Value::Str(key)=>key.to_string(),_=>return Err(pyerr("TypeError","attribute name must be string"))};
        if name=="__setattr__"||name=="__delattr__" {return self.protocol_attribute_mutation_key(state,plan.args[0].clone(),key,plan.args.get(2).cloned(),true,Some(plan.args[1].clone()));}
        self.protocol_attribute_key(state,plan.args[0].clone(),key,None,true,Some(plan.args[1].clone()))
    }
    fn protocol_setattr_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let deletion=matches!(&plan.function,Value::Builtin(name)if name=="delattr");
        if plan.args.len()!=if deletion{2}else{3} || !plan.kwargs.is_empty(){return Err(pyerr("TypeError","invalid attribute assignment arguments"));}
        let name=match self.native_payload(&plan.args[1]).unwrap_or_else(||plan.args[1].clone()){Value::Str(name)=>name.to_string(),_=>return Err(pyerr("TypeError","attribute name must be string"))};
        self.protocol_attribute_mutation_key(state,plan.args[0].clone(),name,if deletion{None}else{Some(plan.args[2].clone())},false,Some(plan.args[1].clone()))
    }
    fn protocol_getattr_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        if !(2..=3).contains(&plan.args.len())||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","getattr expected 2 or 3 positional arguments"));}
        let name=match self.native_payload(&plan.args[1]).unwrap_or_else(||plan.args[1].clone()){Value::Str(name)=>name.to_string(),_=>return Err(pyerr("TypeError","attribute name must be string"))};
        self.protocol_attribute_key(state,plan.args[0].clone(),name,plan.args.get(2).cloned(),false,Some(plan.args[1].clone()))
    }
    fn protocol_attribute(&mut self,state:&mut ProtocolState,object:Value,name:String,default:Option<Value>,bypass:bool)->PyResult<bool> {
        self.protocol_attribute_key(state,object,name,default,bypass,None)
    }
    fn protocol_attribute_key(&mut self,state:&mut ProtocolState,object:Value,name:String,default:Option<Value>,bypass:bool,key:Option<Value>)->PyResult<bool> {
        let key=key.unwrap_or_else(||Value::Str(self.intern_keyword(&name)));
        if !bypass {
            if let Some((method,class))=self.protocol_slot(&object,"__getattribute__") {
                state.attribute_recovery=Some(ProtocolAttributeRecovery{receiver:object.clone(),name:name.clone(),key:key.clone(),default,fallback:true,subscription:false});
                self.protocol_bind(state,method,object,class,vec![key],Vec::new(),ProtocolAction::AttributeDone,false)?;return Ok(true);
            }
        }
        // Follow native getattribute precedence without executing user __get__
        // or __getattr__ on the Rust stack. Native metadata stays on its fast path.
        if let Value::Obj(index)=&object {
            match self.object(*index)? {
                Object::Instance{class,attrs}|Object::BuiltinInstance{class,attrs,..}=>{
                    let descriptor=self.class_attribute_lookup(&class,&name);
                    let data=descriptor.as_ref().is_some_and(|value|self.attribute_is_data(value));
                    if data || self.ns_get(attrs,&name).is_none() {
                        if let Some(descriptor)=descriptor {
                            if self.protocol_user_descriptor(&descriptor) {
                                state.attribute_recovery=Some(ProtocolAttributeRecovery{receiver:object.clone(),name:name.clone(),key:key.clone(),default,fallback:!bypass,subscription:false});
                                self.protocol_bind_value(state,descriptor,Some(object),class,ProtocolAction::AttributeDone)?;return Ok(true);
                            }
                        }
                    }
                    if self.slot_override(&class,"__getattr__",0).is_some() {
                        // A present native/data attribute is resolved normally;
                        // only a genuine absence enters the Python fallback.
                        let mut present=data || self.ns_get(attrs,&name).is_some() || self.class_attribute_lookup(&class,&name).is_some();
                        if !present {if let Some(payload)=self.native_payload(&object){match self.getattr_default(payload,&name){Ok(_)=>present=true,Err(error) if self.exception_has_native_class(&error,"AttributeError")=>{},Err(error)=>return Err(error)}}}
                        if !present && !["__class__","__dict__","__weakref__","__init__"].contains(&name.as_str()) {
                            if bypass{return Err(pyerr("AttributeError",format!("'{}' object has no attribute '{}'",self.typename(&object),name)));}
                            state.attribute_recovery=Some(ProtocolAttributeRecovery{receiver:object,name,key:key.clone(),default,fallback:true,subscription:false});
                            return self.protocol_attribute_failure(state);
                        }
                    }
                }
                Object::Class(class)=>{
                    let meta=self.class_attribute_lookup(&class.metaclass,&name);
                    if let Some(descriptor)=meta.as_ref().filter(|value|self.attribute_is_data(value)) {
                        if self.protocol_user_descriptor(descriptor) {
                            state.attribute_recovery=Some(ProtocolAttributeRecovery{receiver:object.clone(),name:name.clone(),key:key.clone(),default,fallback:!bypass,subscription:false});
                            self.protocol_bind_value(state,descriptor.clone(),Some(object),class.metaclass,ProtocolAction::AttributeDone)?;return Ok(true);
                        }
                    }
                    if let Some(descriptor)=self.class_attribute_lookup(&object,&name) {
                        if self.protocol_user_descriptor(&descriptor) {
                            state.attribute_recovery=Some(ProtocolAttributeRecovery{receiver:object.clone(),name:name.clone(),key:key.clone(),default,fallback:!bypass,subscription:false});
                            self.protocol_bind_value(state,descriptor,None,object,ProtocolAction::AttributeDone)?;return Ok(true);
                        }
                    }else if let Some(descriptor)=meta {
                        if self.protocol_user_descriptor(&descriptor) {
                            state.attribute_recovery=Some(ProtocolAttributeRecovery{receiver:object.clone(),name:name.clone(),key:key.clone(),default,fallback:!bypass,subscription:false});
                            self.protocol_bind_value(state,descriptor,Some(object),class.metaclass,ProtocolAction::AttributeDone)?;return Ok(true);
                        }
                    }
                    if !bypass && self.class_attribute_lookup(&object,&name).is_none() && self.class_attribute_lookup(&class.metaclass,&name).is_none() && !["__class__","__dict__","__name__","__qualname__","__module__","__mro__","__bases__","__annotations__","__annotate__","__type_params__"].contains(&name.as_str()) && self.slot_override(&class.metaclass,"__getattr__",0).is_some() {
                        state.attribute_recovery=Some(ProtocolAttributeRecovery{receiver:object,name,key:key.clone(),default,fallback:true,subscription:false});
                        return self.protocol_attribute_failure(state);
                    }
                }
                _=>{},
            }
        }
        Ok(false)
    }
    fn protocol_user_descriptor(&self,descriptor:&Value)->bool {
        if let Value::Obj(index)=descriptor {match self.heap.get(*index).and_then(Option::as_ref){Some(Object::Property{..})=>return true,Some(Object::Function(_)|Object::Static(_)|Object::ClassMethod(_)|Object::Cached(_))=>return false,_=>{}}}
        self.protocol_slot(descriptor,"__get__").is_some()
    }
    fn protocol_attribute_failure(&mut self,state:&mut ProtocolState)->PyResult<bool> {
        let Some(mut recovery)=state.attribute_recovery.take() else{return Ok(false)};
        state.plan=None;state.value=None;state.binding_recovery=None;
        if let Some(end)=state.actions.iter().position(|action|matches!(action,ProtocolAction::AttributeDone)){self.protocol_discard_actions(state,end+1);}
        if recovery.fallback {
            recovery.fallback=false;
            if let Some((method,class))=self.protocol_slot(&recovery.receiver,"__getattr__") {
                let key=recovery.key.clone();
                self.protocol_bind(state,method,recovery.receiver.clone(),class,vec![key],Vec::new(),ProtocolAction::AttributeDone,false)?;
                state.attribute_recovery=Some(recovery);return Ok(true);
            }
        }
        if let Some(default)=recovery.default {state.value=Some(default);return Ok(true);}
        if recovery.subscription {return Err(pyerr("TypeError","type is not subscriptable"));}
        Ok(false)
    }
}
