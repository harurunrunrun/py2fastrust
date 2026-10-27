// The phase numbers mirror operand_slots.rs; lookups after a Python callback
// remain after that callback, so class mutation cannot observe eager dispatch.
#[derive(Clone, Debug)]
enum ProtocolOperandKind {
    Binary { phase:u8, same:bool, right_first:bool, reflected:Option<SlotDefinition>, sequence:bool },
    Comparison { phase:u8, reverse:bool },
}
#[derive(Clone, Debug)]
struct ProtocolOperand { op:String,left:Value,right:Value,kind:ProtocolOperandKind }
impl ProtocolOperand {
    fn roots(&self,out:&mut Vec<Value>) {
        out.extend([self.left.clone(),self.right.clone()]);
        if let ProtocolOperandKind::Binary{reflected:Some(slot),..}=&self.kind{out.push(slot.value().clone());}
    }
}
impl Runtime {
    fn start_protocol_binary(&mut self,frame:&mut Frame,op:String,left:Value,right:Value)->PyResult<bool> {
        let op=match op.strip_prefix('i'){Some(base) if operand_method(base).is_some()=>format!("{base}="),_=>op};
        if operand_method(op.strip_suffix('=').unwrap_or(&op)).is_none() || (self.object_class(&left).is_none()&&self.object_class(&right).is_none()) || self.is_template_value(&left)||self.is_template_value(&right) {return Ok(false);}
        if self.is_typing_value(&left)||self.is_typing_value(&right)||self.generic_parts(&left).is_some()||self.generic_parts(&right).is_some(){return Ok(false);}
        if [&left,&right].iter().any(|value|matches!(value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::DictView{..}|Object::MappingProxy{..})))){return Ok(false);}
        let operation=ProtocolOperand{op,left,right,kind:ProtocolOperandKind::Binary{phase:0,same:false,right_first:false,reflected:None,sequence:false}};
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        self.protocol_operand_next(&mut state,operation)?;
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn start_protocol_compare(&mut self,frame:&mut Frame,op:String,left:Value,right:Value)->PyResult<bool> {
        if !["==","!=","<","<=",">",">="].contains(&op.as_str()){return Ok(false);}
        if self.object_class(&left).is_none()&&self.object_class(&right).is_none() {
            let mut state=Self::protocol_empty(ProtocolSink::Stack);
            if !self.protocol_sequence_compare(&mut state,&op,left,right)? {return Ok(false);}
            frame.protocol=Some(state);self.resume_protocol(frame)?;return Ok(true);
        }
        if self.is_typing_value(&left)||self.is_typing_value(&right)||self.generic_parts(&left).is_some()||self.generic_parts(&right).is_some(){return Ok(false);}
        let lc=self.operand_class(&left);let rc=self.operand_class(&right);
        let reverse=!Self::same_type(&lc,&rc)&&self.is_subclass(&rc,&lc)?;
        let operation=ProtocolOperand{op,left,right,kind:ProtocolOperandKind::Comparison{phase:0,reverse}};
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        self.protocol_operand_next(&mut state,operation)?;
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn protocol_compare_into(&mut self,state:&mut ProtocolState,op:String,left:Value,right:Value)->PyResult<()> {
        if self.object_class(&left).is_none()&&self.object_class(&right).is_none() {
            if self.protocol_sequence_compare(state,&op,left.clone(),right.clone())? {return Ok(());}
            state.value=Some(self.compare_value(&op,&left,&right)?);return Ok(());
        }
        let lc=self.operand_class(&left);let rc=self.operand_class(&right);
        let reverse=!Self::same_type(&lc,&rc)&&self.is_subclass(&rc,&lc)?;
        self.protocol_operand_next(state,ProtocolOperand{op,left,right,kind:ProtocolOperandKind::Comparison{phase:0,reverse}})
    }
    fn start_protocol_unary(&mut self,frame:&mut Frame,op:&str,value:Value)->PyResult<bool> {
        let name=match op {"-"=>"__neg__","+"=>"__pos__","~"=>"__invert__",_=>return Ok(false)};
        let Some((method,class))=self.protocol_slot(&value,name)else{return Ok(false)};
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        self.protocol_bind(&mut state,method,value,class,Vec::new(),Vec::new(),ProtocolAction::Pass,false)?;
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn protocol_operand_result(&mut self,state:&mut ProtocolState,operation:ProtocolOperand,value:Value)->PyResult<()> {
        if matches!(&value,Value::Builtin(name)if name=="NotImplemented"){self.protocol_operand_next(state,operation)}else{state.value=Some(value);Ok(())}
    }
    fn protocol_operand_invoke(&mut self,state:&mut ProtocolState,slot:SlotDefinition,receiver:Value,argument:Value,operation:ProtocolOperand,inplace:bool)->PyResult<bool> {
        if operand_descriptor(slot.value()).is_none() {
            let class=self.operand_class(&receiver);
            self.protocol_bind_recover(state,slot.value().clone(),receiver,class,vec![argument],Vec::new(),ProtocolAction::Operand(Box::new(operation)),Some(ProtocolBindingRecovery::Decline))?;
            return Ok(true);
        }
        let comparison=matches!(operation.kind,ProtocolOperandKind::Comparison{..});
        if comparison && matches!(operand_descriptor(slot.value()),Some(("object","__ne__"))) {
            if let Some(eq)=self.operand_slot(&receiver,"__eq__") {
                state.actions.push_front(ProtocolAction::Operand(Box::new(operation.clone())));
                if operand_descriptor(eq.value()).is_none() {
                    let class=self.operand_class(&receiver);
                    self.protocol_bind_recover(state,eq.value().clone(),receiver,class,vec![argument],Vec::new(),ProtocolAction::NeFromEq,Some(ProtocolBindingRecovery::Decline))?;
                }else{
                    state.actions.push_front(ProtocolAction::NeFromEq);
                    state.value=Some(self.operand_compare_slot(&eq,&receiver,&argument)?.unwrap_or(Value::Builtin("NotImplemented".into())));
                }
                return Ok(true);
            }return Ok(false);
        }
        if comparison {
            if let Some((owner,name))=operand_descriptor(slot.value()) {
                if ["list","tuple"].contains(&owner) {
                    let op=match name {"__eq__"=>"==","__ne__"=>"!=","__lt__"=>"<","__le__"=>"<=","__gt__"=>">","__ge__"=>">=",_=>""};
                    let left=self.native_payload(&receiver).unwrap_or_else(||receiver.clone());let right=self.native_payload(&argument).unwrap_or_else(||argument.clone());
                    state.actions.push_front(ProtocolAction::Operand(Box::new(operation.clone())));
                    if self.protocol_sequence_compare(state,op,left,right)? {return Ok(true);}
                    state.actions.remove(0);
                }
            }
        }
        let result=if comparison {self.operand_compare_slot(&slot,&receiver,&argument)?}else if inplace{self.operand_inplace(&slot,&receiver,&argument)?}else{self.operand_binary_slot(&slot,&receiver,&argument)?};
        if let Some(value)=result {state.value=Some(value);return Ok(true);}Ok(false)
    }
    fn protocol_operand_next(&mut self,state:&mut ProtocolState,mut operation:ProtocolOperand)->PyResult<()> {
        loop {
            let mut candidate=None;
            match operation.kind.clone() {
                ProtocolOperandKind::Comparison{phase,reverse}=>{
                    if phase>=2 {
                        if ["==","!="].contains(&operation.op.as_str()){let same=operation.left.same_identity(&operation.right);state.value=Some(Value::Bool(if operation.op=="=="{same}else{!same}));return Ok(());}
                        return Err(pyerr("TypeError",format!("'{}' not supported between instances of '{}' and '{}'",operation.op,self.typename(&operation.left),self.typename(&operation.right))));
                    }
                    let (forward,reflected)=match operation.op.as_str(){"=="=>("__eq__","__eq__"),"!="=>("__ne__","__ne__"),"<"=>("__lt__","__gt__"),"<="=>("__le__","__ge__"),">"=>("__gt__","__lt__"),_ =>("__ge__","__le__")};
                    operation.kind=ProtocolOperandKind::Comparison{phase:phase+1,reverse};
                    let (receiver,argument,name)=if (phase==0)==reverse{(&operation.right,&operation.left,reflected)}else{(&operation.left,&operation.right,forward)};
                    if let Some(slot)=self.operand_slot(receiver,name){candidate=Some((slot,receiver.clone(),argument.clone(),false));}
                }
                ProtocolOperandKind::Binary{phase,mut same,mut right_first,mut reflected,mut sequence}=>{
                    let base=operation.op.strip_suffix('=').unwrap_or(&operation.op);let stem=operand_method(base).unwrap();
                    match phase {
                        0=>{if operation.op.ends_with('='){if let Some(slot)=self.operand_slot(&operation.left,&format!("__i{stem}__")){candidate=Some((slot,operation.left.clone(),operation.right.clone(),true));}}}
                        1=>{
                            reflected=self.operand_slot(&operation.right,&format!("__r{stem}__"));
                            same=Self::same_type(&self.operand_class(&operation.left),&self.operand_class(&operation.right));
                            right_first=!same&&self.is_subclass(&self.operand_class(&operation.right),&self.operand_class(&operation.left))?&&!Self::operand_same_slot(reflected.as_ref(),self.operand_slot(&operation.left,&format!("__r{stem}__")).as_ref());
                            if right_first {if let Some(slot)=&reflected{candidate=Some((slot.clone(),operation.right.clone(),operation.left.clone(),false));}}
                        }
                        2=>{
                            let forward=self.operand_slot(&operation.left,&format!("__{stem}__"));sequence=Self::operand_sequence_fallback(forward.as_ref());
                            if !sequence {if let Some(slot)=forward{candidate=Some((slot,operation.left.clone(),operation.right.clone(),false));}}
                        }
                        3=>{if !same&&!right_first&&reflected.is_some(){if let Some(slot)=self.operand_slot(&operation.right,&format!("__r{stem}__")){candidate=Some((slot,operation.right.clone(),operation.left.clone(),false));}}}
                        4=>{if sequence{if let Some(slot)=self.operand_slot(&operation.left,&format!("__{stem}__")){candidate=Some((slot,operation.left.clone(),operation.right.clone(),false));}}}
                        _=>{
                            let lp=self.native_payload(&operation.left).unwrap_or_else(||operation.left.clone());let rp=self.native_payload(&operation.right).unwrap_or_else(||operation.right.clone());
                            if base=="*" {
                                if ["str","bytes","bytearray","list","tuple"].contains(&self.operand_kind(&lp))&&Self::operand_sequence_fallback(self.operand_slot(&operation.left,"__mul__").as_ref()){let count=self.as_int(&operation.right)?;state.value=Some(self.binary_default(base,lp,Value::Int(count.into()))?);return Ok(());}
                                if ["str","bytes","bytearray","list","tuple"].contains(&self.operand_kind(&rp))&&Self::operand_sequence_fallback(self.operand_slot(&operation.right,"__rmul__").as_ref()){let count=self.as_int(&operation.left)?;state.value=Some(self.binary_default(base,rp,Value::Int(count.into()))?);return Ok(());}
                            }
                            return Err(pyerr("TypeError",format!("unsupported operand type(s) for {}: '{}' and '{}'",operation.op,self.typename(&operation.left),self.typename(&operation.right))));
                        }
                    }
                    operation.kind=ProtocolOperandKind::Binary{phase:phase+1,same,right_first,reflected,sequence};
                }
            }
            if let Some((slot,receiver,argument,inplace))=candidate {
                if self.protocol_operand_invoke(state,slot,receiver,argument,operation.clone(),inplace)?{return Ok(());}
            }
        }
    }
}
