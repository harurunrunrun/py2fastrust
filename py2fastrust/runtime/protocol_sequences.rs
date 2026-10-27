// Lexicographic native sequence comparisons suspend around element callbacks.
// The live-list boundaries follow Python 3.14 behavioral probes: equality and
// truth can mutate either list, so ordering refetches the current items.
#[derive(Clone,Debug)]
enum ProtocolSequencePhase { Start, Equality, Truth, Requested }
#[derive(Clone,Debug)]
struct ProtocolSequence {
    op:String,left:usize,right:usize,index:usize,phase:ProtocolSequencePhase,
    items:Option<(Value,Value)>,cycle_candidate:bool,
}
impl ProtocolSequence {
    fn roots(&self,out:&mut Vec<Value>) {
        out.extend([Value::Obj(self.left),Value::Obj(self.right)]);
        if let Some((left,right))=&self.items {out.extend([left.clone(),right.clone()]);}
    }
}
impl Runtime {
    fn protocol_sequence_compare(&mut self,state:&mut ProtocolState,op:&str,left:Value,right:Value)->PyResult<bool> {
        if !["==","!=","<","<=",">",">="].contains(&op) {return Ok(false);}
        let (Value::Obj(left),Value::Obj(right))=(left,right) else{return Ok(false)};
        let pair=match (self.heap.get(left).and_then(Option::as_ref),self.heap.get(right).and_then(Option::as_ref)) {
            (Some(Object::List(a)),Some(Object::List(b)))=>Some((true,a.len(),b.len())),
            (Some(Object::Tuple(a)),Some(Object::Tuple(b)))=>Some((false,a.len(),b.len())),
            _=>None,
        };
        let Some((list,a,b))=pair else{return Ok(false)};
        if list && ["==","!="].contains(&op) && a!=b {state.value=Some(Value::Bool(op=="!="));return Ok(true);}
        // Native container recursion is separate from Python frame depth in
        // CPython 3.14. Detect a repeated pair only within a callback-free run.
        let cycle=state.actions.iter().any(|action|matches!(action,ProtocolAction::Sequence(sequence)if sequence.cycle_candidate&&sequence.left==left&&sequence.right==right&&sequence.op==op));
        if cycle {return Err(pyerr("RecursionError","maximum recursion depth exceeded in comparison"));}
        let sequence=ProtocolSequence{op:op.into(),left,right,index:0,phase:ProtocolSequencePhase::Start,items:None,cycle_candidate:true};
        self.protocol_sequence_queue(state,sequence,Value::None);
        Ok(true)
    }
    fn protocol_sequence_callback_boundary(&self,state:&mut ProtocolState) {
        for action in &mut state.actions {if let ProtocolAction::Sequence(sequence)=action {sequence.cycle_candidate=false;}}
    }
    fn protocol_sequence_comparison_callback(&self,op:&str,left:&Value,right:&Value)->bool {
        let (forward,reverse)=match op {"=="=>("__eq__","__eq__"),"!="=>("__ne__","__ne__"),"<"=>("__lt__","__gt__"),"<="=>("__le__","__ge__"),">"=>("__gt__","__lt__"),_=>("__ge__","__le__")};
        for (value,name) in [(left,forward),(right,reverse)] {
            if self.operand_slot(value,name).is_some_and(|slot|operand_descriptor(slot.value()).is_none()) {return true;}
            let payload=self.native_payload(value).unwrap_or_else(||value.clone());
            if matches!(payload,Value::Obj(index)if matches!(self.heap.get(index).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..)|Object::Set(_)|Object::FrozenSet{..}|Object::GenericAlias{..}|Object::TypeUnion{..}))) {return true;}
        }
        false
    }
    fn protocol_sequence_truth_callback(&self,value:&Value)->bool {
        self.object_class(value).is_some_and(|class|["__bool__","__len__"].iter().any(|name|matches!(self.slot_definition(&class,name,0),Some(SlotDefinition::Python(_)))))
    }
    fn protocol_sequence_queue(&mut self,state:&mut ProtocolState,sequence:ProtocolSequence,value:Value) {
        state.actions.insert(0,ProtocolAction::Sequence(Box::new(sequence)));
        state.value=Some(value);
    }
    fn protocol_sequence_size(&self,index:usize)->usize {
        match self.heap.get(index).and_then(Option::as_ref) {Some(Object::List(values)|Object::Tuple(values))=>values.len(),_=>0}
    }
    fn protocol_sequence_item(&self,index:usize,position:usize)->Option<Value> {
        match self.heap.get(index).and_then(Option::as_ref) {Some(Object::List(values)|Object::Tuple(values))=>values.get(position).cloned(),_=>None}
    }
    fn protocol_sequence_lengths(&self,sequence:&ProtocolSequence)->Value {
        let left=self.protocol_sequence_size(sequence.left);let right=self.protocol_sequence_size(sequence.right);
        Value::Bool(match sequence.op.as_str() {"=="=>left==right,"!="=>left!=right,"<"=>left<right,"<="=>left<=right,">"=>left>right,_=>left>=right})
    }
    fn protocol_sequence_result(&mut self,state:&mut ProtocolState,mut sequence:ProtocolSequence,value:Value)->PyResult<()> {
        match sequence.phase {
            ProtocolSequencePhase::Start=>{
                loop {
                    let Some(left)=self.protocol_sequence_item(sequence.left,sequence.index) else{break;};
                    let Some(right)=self.protocol_sequence_item(sequence.right,sequence.index) else{break;};
                    if left.same_identity(&right) {sequence.index=sequence.index.checked_add(1).ok_or_else(||pyerr("OverflowError","sequence comparison index overflow"))?;continue;}
                    sequence.items=Some((left.clone(),right.clone()));sequence.phase=ProtocolSequencePhase::Equality;
                    self.protocol_sequence_queue(state,sequence,Value::None);
                    if self.protocol_sequence_comparison_callback("==",&left,&right) {self.protocol_sequence_callback_boundary(state);}
                    self.protocol_compare_into(state,"==".into(),left,right)?;
                    return Ok(());
                }
                state.value=Some(self.protocol_sequence_lengths(&sequence));
            },
            ProtocolSequencePhase::Equality=>{
                sequence.phase=ProtocolSequencePhase::Truth;
                self.protocol_sequence_queue(state,sequence,Value::None);
                if self.protocol_sequence_truth_callback(&value) {self.protocol_sequence_callback_boundary(state);}
                if !self.protocol_python_truth(state,value.clone())? {state.value=Some(Value::Bool(self.truth(&value)?));}
            },
            ProtocolSequencePhase::Truth=>{
                let Value::Bool(equal)=value else{return Err(pyerr("RuntimeError","missing sequence equality truth result"));};
                sequence.items=None;
                if equal {
                    sequence.index=sequence.index.checked_add(1).ok_or_else(||pyerr("OverflowError","sequence comparison index overflow"))?;
                    sequence.phase=ProtocolSequencePhase::Start;
                    self.protocol_sequence_queue(state,sequence,Value::None);
                }else if sequence.index>=self.protocol_sequence_size(sequence.left) || sequence.index>=self.protocol_sequence_size(sequence.right) {
                    state.value=Some(self.protocol_sequence_lengths(&sequence));
                }else if ["==","!="].contains(&sequence.op.as_str()) {
                    state.value=Some(Value::Bool(sequence.op=="!="));
                }else{
                    // A list callback can replace the first unequal items.
                    // Their old references expire before the requested compare.
                    let left=self.protocol_sequence_item(sequence.left,sequence.index).unwrap();
                    let right=self.protocol_sequence_item(sequence.right,sequence.index).unwrap();
                    let op=sequence.op.clone();sequence.items=Some((left.clone(),right.clone()));sequence.phase=ProtocolSequencePhase::Requested;
                    self.protocol_sequence_queue(state,sequence,Value::None);
                    if self.protocol_sequence_comparison_callback(&op,&left,&right) {self.protocol_sequence_callback_boundary(state);}
                    self.protocol_compare_into(state,op,left,right)?;
                }
            },
            // Ordering's first unequal comparison may return an arbitrary
            // Python value. Its truth belongs to the eventual consumer.
            ProtocolSequencePhase::Requested=>state.value=Some(value),
        }
        Ok(())
    }
}
