// MRO callbacks and tentative hierarchy updates live in the caller's queue.
// A persistent transaction action survives every binding/conversion suspension.
type ProtocolMroTransaction = std::rc::Rc<std::cell::RefCell<ProtocolBasesTransaction>>;
#[derive(Clone,Debug)]
struct ProtocolBasesTransaction {
    owner:usize, requested:Value, previous:Class, changes:Vec<MroChange>,
    pending:Vec<(usize,Vec<usize>)>, active:bool,
}
impl ProtocolBasesTransaction {
    fn roots(&self,out:&mut Vec<Value>) {
        out.extend([Value::Obj(self.owner),self.requested.clone(),self.previous.bases_value.clone(),self.previous.layout_base.clone()]);
        out.extend(self.previous.bases.iter().cloned());
        out.extend(self.previous.mro_value.iter().map(|owner|Value::Obj(*owner)));
        for change in &self.changes {
            out.extend([Value::Obj(change.owner),Value::Obj(change.installed)]);
            out.extend(change.previous.iter().map(|owner|Value::Obj(*owner)));
        }
        for (owner,ancestors) in &self.pending {
            out.push(Value::Obj(*owner));out.extend(ancestors.iter().map(|owner|Value::Obj(*owner)));
        }
    }
}
#[derive(Clone,Debug)]
enum ProtocolMroPurpose { Single, Bases{transaction:ProtocolMroTransaction,ancestors:Vec<usize>} }
impl ProtocolMroPurpose {
    fn roots(&self,out:&mut Vec<Value>) {
        if let Self::Bases{transaction,ancestors}=self {
            transaction.borrow().roots(out);out.extend(ancestors.iter().map(|owner|Value::Obj(*owner)));
        }
    }
}
#[derive(Clone,Debug)]
enum ProtocolMro {
    Bound{plan:MroPlan,purpose:ProtocolMroPurpose},
    Returned{plan:MroPlan,purpose:ProtocolMroPurpose},
    Iterated{plan:MroPlan,purpose:ProtocolMroPurpose},
    Collect{plan:MroPlan,purpose:ProtocolMroPurpose,iterator:Value,values:Vec<Value>},
    Transaction(ProtocolMroTransaction),
    Next(ProtocolMroTransaction),
}
impl ProtocolMro {
    fn roots(&self,out:&mut Vec<Value>) {
        match self {
            Self::Bound{plan,purpose}|Self::Returned{plan,purpose}|Self::Iterated{plan,purpose}=>{plan.roots(out);purpose.roots(out);}
            Self::Collect{plan,purpose,iterator,values}=>{plan.roots(out);purpose.roots(out);out.push(iterator.clone());out.extend(values.iter().cloned());}
            Self::Transaction(transaction)|Self::Next(transaction)=>transaction.borrow().roots(out),
        }
    }
}
impl Runtime {
    fn protocol_class_mro(&mut self,state:&mut ProtocolState,owner:usize)->PyResult<()> {
        self.protocol_mro_start(state,owner,ProtocolMroPurpose::Single)
    }
    fn protocol_mro_start(&mut self,state:&mut ProtocolState,owner:usize,purpose:ProtocolMroPurpose)->PyResult<()> {
        let plan=self.mro_prepare(owner)?;
        if let Some(descriptor)=plan.descriptor.clone() {
            let metaclass=plan.metaclass.clone();
            self.protocol_bind_value(state,descriptor,Some(Value::Obj(owner)),metaclass,
                ProtocolAction::Mro(Box::new(ProtocolMro::Bound{plan,purpose})))?;
        }else {
            let values=self.calculate_class_mro(&Value::Obj(owner),0).ok_or_else(||pyerr("TypeError","Cannot create a consistent method resolution order (MRO)"))?;
            let result=self.obj_value(Object::Tuple(values));
            let change=self.mro_finish(plan,result)?;
            self.protocol_mro_completed(state,purpose,change)?;
        }
        Ok(())
    }
    fn protocol_class_set_bases(&mut self,state:&mut ProtocolState,owner:usize,value:Value)->PyResult<()> {
        let (bases,best,previous)=self.mro_bases_prepare(owner,&value)?;
        let transaction=std::rc::Rc::new(std::cell::RefCell::new(ProtocolBasesTransaction {
            owner,requested:value.clone(),previous,changes:Vec::new(),pending:vec![(owner,Vec::new())],active:true,
        }));
        state.actions.push_front(ProtocolAction::Mro(Box::new(ProtocolMro::Transaction(transaction.clone()))));
        if let Some(Object::Class(class))=self.heap[owner].as_mut() {
            class.bases=bases;class.bases_value=value;class.layout_base=best;
        }
        self.protocol_mro_next(state,transaction)
    }
    fn protocol_mro_next(&mut self,state:&mut ProtocolState,transaction:ProtocolMroTransaction)->PyResult<()> {
        state.actions.push_front(ProtocolAction::Mro(Box::new(ProtocolMro::Next(transaction))));
        state.value=Some(Value::None);Ok(())
    }
    fn protocol_mro_completed(&mut self,state:&mut ProtocolState,purpose:ProtocolMroPurpose,change:Option<MroChange>)->PyResult<()> {
        match purpose {
            ProtocolMroPurpose::Single=>state.value=Some(Value::Bool(change.is_some())),
            ProtocolMroPurpose::Bases{transaction,ancestors}=>{
                if let Some(change)=change {
                    let mut children=self.mro_children(&Value::Obj(change.owner));children.reverse();
                    let mut record=transaction.borrow_mut();record.changes.push(change);
                    record.pending.extend(children.into_iter().map(|owner|(owner,ancestors.clone())));
                }
                self.protocol_mro_next(state,transaction)?;
            }
        }
        Ok(())
    }
    fn protocol_mro_rollback_transaction(&mut self,transaction:&ProtocolMroTransaction) {
        let mut record=transaction.borrow_mut();if !record.active{return;}
        self.mro_rollback(&record.changes);
        if let Ok(current)=self.mro_class(record.owner) {
            if current.bases_value.same_identity(&record.requested) {
                if let Some(Object::Class(class))=self.heap[record.owner].as_mut() {
                    class.bases=record.previous.bases.clone();class.bases_value=record.previous.bases_value.clone();
                    class.layout_base=record.previous.layout_base.clone();
                }
            }
        }
        record.active=false;
    }
    fn protocol_mro_discard(&mut self,record:&ProtocolMro) {
        if let ProtocolMro::Transaction(transaction)=record {self.protocol_mro_rollback_transaction(transaction);}
    }
    fn protocol_mro_abandon(&mut self,state:&ProtocolState) {
        for action in &state.actions {if let ProtocolAction::Mro(record)=action {self.protocol_mro_discard(record);}}
    }
    fn protocol_mro_result(&mut self,state:&mut ProtocolState,record:ProtocolMro,value:Value)->PyResult<()> {
        match record {
            ProtocolMro::Bound{plan,purpose}=>{
                state.actions.push_front(ProtocolAction::Mro(Box::new(ProtocolMro::Returned{plan,purpose})));
                state.plan=Some(ProtocolPlan{function:value,args:Vec::new(),kwargs:Vec::new()});
            }
            ProtocolMro::Returned{plan,purpose}=>{
                if matches!(&value,Value::Obj(owner)if matches!(self.heap.get(*owner).and_then(Option::as_ref),Some(Object::Tuple(_)))) {
                    let change=self.mro_finish(plan,value)?;self.protocol_mro_completed(state,purpose,change)?;
                }else {
                    state.actions.push_front(ProtocolAction::Mro(Box::new(ProtocolMro::Iterated{plan,purpose})));
                    state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![value],kwargs:Vec::new()});
                }
            }
            ProtocolMro::Iterated{plan,purpose}=>{
                let iterator=value;
                state.actions.push_front(ProtocolAction::Mro(Box::new(ProtocolMro::Collect{plan,purpose,iterator:iterator.clone(),values:Vec::new()})));
                state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![iterator,Value::Builtin("$mro:end".into())],kwargs:Vec::new()});
            }
            ProtocolMro::Collect{plan,purpose,iterator,mut values}=>{
                if matches!(&value,Value::Builtin(name)if name=="$mro:end") {
                    let result=self.obj_value(Object::Tuple(values));
                    let change=self.mro_finish(plan,result)?;self.protocol_mro_completed(state,purpose,change)?;
                }else {
                    values.push(value);
                    state.actions.push_front(ProtocolAction::Mro(Box::new(ProtocolMro::Collect{plan,purpose,iterator:iterator.clone(),values})));
                    state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![iterator,Value::Builtin("$mro:end".into())],kwargs:Vec::new()});
                }
            }
            ProtocolMro::Next(transaction)=>{
                let next=transaction.borrow_mut().pending.pop();
                if let Some((owner,mut ancestors))=next {
                    if ancestors.contains(&owner){return Err(pyerr("RecursionError","cyclic pending subclass update"));}
                    ancestors.push(owner);
                    self.protocol_mro_start(state,owner,ProtocolMroPurpose::Bases{transaction,ancestors})?;
                }else{state.value=Some(Value::None);}
            }
            ProtocolMro::Transaction(transaction)=>{
                let result=(||{
                    let record=transaction.borrow();
                    if self.mro_class(record.owner)?.bases_value.same_identity(&record.requested){self.mro_register_bases(record.owner)?;}
                    Ok(())
                })();
                if let Err(error)=result {self.protocol_mro_rollback_transaction(&transaction);return Err(error);}
                transaction.borrow_mut().active=false;state.value=Some(Value::None);
            }
        }
        Ok(())
    }
    fn protocol_mro_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let Value::Builtin(function)=&plan.function else{return Ok(false)};
        if function=="native_attr_readonly" {
            if !matches!(plan.args.first().and_then(native_attribute_parts),Some((_,"type","__bases__"))){return Ok(false);}
            if plan.args.len()!=3||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","invalid __bases__ descriptor arguments"));}
            self.native_validate_receiver("type",&plan.args[1])?;
            let Value::Obj(owner)=plan.args[1]else{return Err(pyerr("TypeError","cannot set __bases__ on immutable type"))};
            self.protocol_class_set_bases(state,owner,plan.args[2].clone())?;return Ok(true);
        }
        if matches!(native_attribute_parts(&plan.function),Some((_,"type","__setattr__"))) {
            if plan.args.len()!=3||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","invalid descriptor arguments"));}
            let key=match self.native_payload(&plan.args[1]).unwrap_or_else(||plan.args[1].clone()){Value::Str(key)=>key.to_string(),_=>return Err(pyerr("TypeError","attribute name must be string"))};
            return self.protocol_attribute_mutation_key(state,plan.args[0].clone(),key,Some(plan.args[2].clone()),true,Some(plan.args[1].clone()));
        }
        Ok(false)
    }
}
