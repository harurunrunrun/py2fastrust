// Generic class metadata can observe Python attributes while collecting bases.
// Each lookup and nested alias scan belongs to the same heap continuation.
#[derive(Clone,Debug)]
enum ClassParameterWork { Value(Value), Leave(usize) }
#[derive(Clone,Debug)]
struct ClassParameterFrame { pending:Vec<ClassParameterWork>, output:Vec<Value>, active:Vec<usize>, alias:Option<usize> }
impl ClassParameterFrame {
    fn new(values:Vec<Value>,alias:Option<usize>)->Self {
        Self{pending:values.into_iter().rev().map(ClassParameterWork::Value).collect(),output:Vec::new(),active:Vec::new(),alias}
    }
}
#[derive(Clone,Debug)]
enum ClassParameterPhase { Bases, Next, Subst(Value), Parameters(Value) }
#[derive(Clone,Debug)]
struct ProtocolClassParameters {
    class:Value,phase:ClassParameterPhase,frames:Vec<ClassParameterFrame>,collected:Vec<Value>,
    declared:Option<Vec<Value>>,declared_scan:bool,
}
impl ProtocolClassParameters {
    fn roots(&self,out:&mut Vec<Value>) {
        out.push(self.class.clone());out.extend(self.collected.iter().cloned());
        if let Some(values)=&self.declared{out.extend(values.iter().cloned());}
        match &self.phase{ClassParameterPhase::Subst(value)|ClassParameterPhase::Parameters(value)=>out.push(value.clone()),_=>{}}
        for frame in &self.frames {
            out.extend(frame.output.iter().cloned());out.extend(frame.alias.iter().map(|owner|Value::Obj(*owner)));
            for item in &frame.pending{match item{ClassParameterWork::Value(value)=>out.push(value.clone()),ClassParameterWork::Leave(owner)=>out.push(Value::Obj(*owner))}}
            out.extend(frame.active.iter().map(|owner|Value::Obj(*owner)));
        }
    }
}
impl Runtime {
    fn protocol_class_parameters_start(&mut self,state:&mut ProtocolState,class:Value)->PyResult<()> {
        let Value::Obj(owner)=&class else{state.value=Some(Value::None);return Ok(())};
        let definition=self.mro_class(*owner)?;
        if !definition.bases.iter().any(|base|self.class_mro(base,0).unwrap_or_default().iter().any(|base|matches!(base,Value::Builtin(name)if name=="typing.Generic"))) {
            state.value=Some(Value::None);return Ok(());
        }
        let original=self.ns_get(definition.attrs,"__orig_bases__");
        if original.is_none()&&definition.bases.iter().any(|base|matches!(base,Value::Builtin(name)if name=="typing.Generic")){return Err(pyerr("TypeError","Cannot inherit from plain Generic"));}
        if let Some(original)=original {
            state.actions.push_front(ProtocolAction::ClassParameters(Box::new(ProtocolClassParameters{class,phase:ClassParameterPhase::Bases,frames:Vec::new(),collected:Vec::new(),declared:None,declared_scan:false})));
            state.plan=Some(ProtocolPlan{function:Value::Builtin("tuple".into()),args:vec![original],kwargs:Vec::new()});
        }else{
            let parameters=self.obj_value(Object::Tuple(Vec::new()));self.ns_set(definition.attrs,"__parameters__".into(),parameters);state.value=Some(Value::None);
        }
        Ok(())
    }
    fn protocol_parameters_add(frame:&mut ClassParameterFrame,values:Vec<Value>) {
        for value in values{if !frame.output.iter().any(|old|old.same_identity(&value)){frame.output.push(value);}}
    }
    fn protocol_parameters_next(&mut self,state:&mut ProtocolState,mut data:ProtocolClassParameters)->PyResult<()> {
        loop {
            let work=data.frames.last_mut().and_then(|frame|frame.pending.pop());
            match work {
                Some(ClassParameterWork::Leave(owner))=>{let frame=data.frames.last_mut().unwrap();if frame.active.last()==Some(&owner){frame.active.pop();}continue;}
                Some(ClassParameterWork::Value(value))=>{
                    if self.generic_is_class(&value){continue;}
                    if self.type_parameter_kind(&value).is_some(){Self::protocol_parameters_add(data.frames.last_mut().unwrap(),vec![value]);continue;}
                    let target=if let Some((origin,_,_,_))=self.generic_parts(&value) {
                        if self.generic_is_typing_alias(&value){
                            data.phase=ClassParameterPhase::Subst(value);state.actions.push_front(ProtocolAction::ClassParameters(Box::new(data)));state.value=Some(Value::Builtin("$class:no_parameters".into()));return Ok(());
                        }
                        origin
                    }else{value.clone()};
                    data.phase=ClassParameterPhase::Subst(value);state.actions.push_front(ProtocolAction::ClassParameters(Box::new(data)));
                    state.plan=Some(ProtocolPlan{function:Value::Builtin("getattr".into()),args:vec![target,Value::Str("__typing_subst__".into()),Value::Builtin("$class:no_parameters".into())],kwargs:Vec::new()});return Ok(());
                }
                None=>{
                    let frame=data.frames.pop().ok_or_else(||pyerr("RuntimeError","missing generic parameter scan"))?;
                    if let Some(owner)=frame.alias {
                        let parameters=self.obj_value(Object::Tuple(frame.output.clone()));let Value::Obj(tuple)=parameters else{unreachable!()};
                        if let Some(Object::GenericAlias{parameters:cached,..})=self.heap[owner].as_mut(){*cached=Some(tuple);}
                    }
                    if let Some(parent)=data.frames.last_mut(){Self::protocol_parameters_add(parent,frame.output);continue;}
                    if !data.declared_scan {
                        data.collected=frame.output;
                        if let Some(declared)=data.declared.take(){data.declared_scan=true;data.frames.push(ClassParameterFrame::new(declared,None));continue;}
                    }else{
                        if data.collected.iter().any(|parameter|!frame.output.iter().any(|declared|declared.same_identity(parameter))){return Err(pyerr("TypeError","Some type variables are not listed in Generic[...]"));}
                        data.collected=frame.output;
                    }
                    let Value::Obj(owner)=data.class else{unreachable!()};let attrs=self.mro_class(owner)?.attrs;
                    let parameters=self.obj_value(Object::Tuple(data.collected));self.ns_set(attrs,"__parameters__".into(),parameters);state.value=Some(Value::None);return Ok(());
                }
            }
        }
    }
    fn protocol_class_parameters_result(&mut self,state:&mut ProtocolState,mut data:ProtocolClassParameters,value:Value)->PyResult<()> {
        match data.phase.clone() {
            ClassParameterPhase::Bases=>{
                let bases=self.to_vec(value)?;
                for base in &bases {if let Some((origin,args,_,_))=self.generic_parts(base){if matches!(origin,Value::Builtin(name)if name=="typing.Generic"){
                    if data.declared.is_some(){return Err(pyerr("TypeError","Cannot inherit from Generic[...] multiple times."));}data.declared=Some(args);
                }}}
                data.frames.push(ClassParameterFrame::new(bases,None));
            }
            ClassParameterPhase::Subst(original)=>{
                if !matches!(&value,Value::Builtin(name)if name=="$class:no_parameters") {
                    Self::protocol_parameters_add(data.frames.last_mut().unwrap(),vec![original]);
                }else if let Some((_,args,_,cached))=self.generic_parts(&original) {
                    let Value::Obj(owner)=original else{return Err(pyerr("RuntimeError","invalid generic alias"))};
                    if let Some(tuple)=cached {
                        if let Object::Tuple(parameters)=self.object(tuple)?{Self::protocol_parameters_add(data.frames.last_mut().unwrap(),parameters);}
                    }else{
                        if data.frames.iter().any(|frame|frame.alias==Some(owner)){return Err(pyerr("RecursionError","maximum recursion depth exceeded in __parameter__ calculation"));}
                        data.frames.push(ClassParameterFrame::new(args,Some(owner)));
                    }
                }else{
                    data.phase=ClassParameterPhase::Parameters(original.clone());state.actions.push_front(ProtocolAction::ClassParameters(Box::new(data)));
                    state.plan=Some(ProtocolPlan{function:Value::Builtin("getattr".into()),args:vec![original,Value::Str("__parameters__".into()),Value::Builtin("$class:no_parameters".into())],kwargs:Vec::new()});return Ok(());
                }
            }
            ClassParameterPhase::Parameters(original)=>{
                if !matches!(&value,Value::Builtin(name)if name=="$class:no_parameters") {
                    if let Some((true,parameters))=self.generic_sequence(&value){Self::protocol_parameters_add(data.frames.last_mut().unwrap(),parameters);}
                }else if let Some((_,values))=self.generic_sequence(&original) {
                    let Value::Obj(owner)=original else{unreachable!()};let frame=data.frames.last_mut().unwrap();
                    if frame.active.contains(&owner){return Err(pyerr("RecursionError","maximum recursion depth exceeded in __parameter__ calculation"));}
                    frame.active.push(owner);frame.pending.push(ClassParameterWork::Leave(owner));frame.pending.extend(values.into_iter().rev().map(ClassParameterWork::Value));
                }
            }
            ClassParameterPhase::Next=>{},
        }
        data.phase=ClassParameterPhase::Next;self.protocol_parameters_next(state,data)
    }
}
