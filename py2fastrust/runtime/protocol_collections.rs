// Hash-table callbacks run in the initiating frame. Snapshots retain original
// keys and stored hashes; after equality callbacks a changed table is rescanned.
#[derive(Clone,Debug)]
enum ProtocolLookupOp {
    Get{default:Option<Value>,missing:bool}, Contains, Set(Value), SetDefault(Value),
    Pop(Option<Value>), Delete, Add, Toggle, Discard(bool),
}
#[derive(Clone,Debug)]
enum ProtocolLookupPhase { Hash, Scan, StoredHash, Equal, Truth }
#[derive(Clone,Debug)]
struct ProtocolLookup {
    object:Value,owner:usize,key:Value,hash:i64,set:bool,op:ProtocolLookupOp,
    phase:ProtocolLookupPhase,index:usize,entries:Vec<(Value,Value)>,
}
#[derive(Clone,Debug)]
enum ProtocolCollection {
    ProxyResult(Value),
    Compare{left:Value,right:Value,entries:Vec<(Value,Value)>,index:usize,phase:u8,set:bool,invert:bool},
    Lookup(ProtocolLookup),
    DictInput{owner:Value,source:Value,kwargs:KeywordArgs,phase:u8,iterator:Option<Value>,key:Option<Value>,pair:Vec<Value>,index:usize,mapping:bool,return_owner:bool},
    SetCopy{owner:Value,source:Value,entries:Vec<(Value,i64)>,index:usize},
    TruthResult(bool),
    ItemsContains { owner:Value, candidate:Value, wanted:Value },
    IterateContains{iterator:Value,key:Value,phase:u8,reverse:bool,current:Option<Value>},
    Copy{owner:Value,source:Value,entries:Vec<(Value,Value)>,index:usize,kwargs:KeywordArgs,return_owner:bool},
    Keywords{owner:Value,keywords:KeywordArgs,index:usize,return_owner:bool},
    SetInput{owner:Value,sources:Vec<Value>,source_index:usize,iterator:Option<Value>,phase:u8,frozen:bool,return_owner:bool},
    Build{owner:Value,entries:Vec<(Value,Value)>,index:usize,set:bool},
    TupleHash{owner:Value,items:Vec<Value>,index:usize,hash:u64},
    Search{owner:Value,key:Value,name:String,index:usize,count:usize,stop:usize,phase:u8,current:Option<Value>},
}
impl ProtocolCollection {
    fn roots(&self,out:&mut Vec<Value>){match self {
        Self::ProxyResult(owner)=>out.push(owner.clone()),
        Self::DictInput{owner,source,kwargs,iterator,key,pair,..}=>{out.extend([owner.clone(),source.clone()]);out.extend(kwargs.iter().flat_map(|(key,value)|[key.original.clone(),value.clone()]));out.extend(iterator.iter().cloned());out.extend(key.iter().cloned());out.extend(pair.iter().cloned());}
        Self::SetCopy{owner,source,entries,..}=>{out.extend([owner.clone(),source.clone()]);out.extend(entries.iter().map(|(key,_)|key.clone()));}
        Self::TruthResult(_)=>{},
        Self::ItemsContains{owner,candidate,wanted}=>out.extend([owner.clone(),candidate.clone(),wanted.clone()]),
        Self::IterateContains{iterator,key,current,..}=>{out.extend([iterator.clone(),key.clone()]);out.extend(current.iter().cloned());}
        Self::Copy{owner,source,entries,kwargs,..}=>{out.extend([owner.clone(),source.clone()]);out.extend(entries.iter().flat_map(|(key,value)|[key.clone(),value.clone()]));out.extend(kwargs.iter().flat_map(|(key,value)|[key.original.clone(),value.clone()]));}
        Self::Keywords{owner,keywords,..}=>{out.push(owner.clone());out.extend(keywords.iter().flat_map(|(key,value)|[key.original.clone(),value.clone()]));}
        Self::SetInput{owner,sources,iterator,..}=>{out.push(owner.clone());out.extend(sources.iter().cloned());out.extend(iterator.iter().cloned());}
        Self::Compare{left,right,entries,..}=>{out.extend([left.clone(),right.clone()]);out.extend(entries.iter().flat_map(|(key,value)|[key.clone(),value.clone()]));}
        Self::Lookup(record)=>{out.extend([record.object.clone(),record.key.clone()]);out.extend(record.entries.iter().flat_map(|(k,v)|[k.clone(),v.clone()]));match &record.op{ProtocolLookupOp::Get{default,..}|ProtocolLookupOp::Pop(default)=>out.extend(default.iter().cloned()),ProtocolLookupOp::Set(value)|ProtocolLookupOp::SetDefault(value)=>out.push(value.clone()),_=>{}}}
        Self::Build{owner,entries,..}=>{out.push(owner.clone());out.extend(entries.iter().flat_map(|(k,v)|[k.clone(),v.clone()]));}
        Self::TupleHash{owner,items,..}=>{out.push(owner.clone());out.extend(items.iter().cloned());}
        Self::Search{owner,key,current,..}=>{out.extend([owner.clone(),key.clone()]);out.extend(current.iter().cloned());}
    }}
}
impl Runtime {
    fn protocol_key_error(key:Value)->PyException {let mut error=pyerr("KeyError","");error.args=vec![key];error}
    fn protocol_collection_target(name:&str)->bool {
        ["dict","set","frozenset"].contains(&name)||name.starts_with("method:")||name.starts_with("unbound:")||name.starts_with("native_attr:")
    }
    fn protocol_collection_lookup(&mut self,state:&mut ProtocolState,object:Value,mut key:Value,op:ProtocolLookupOp,known:Option<i64>)->PyResult<bool> {
        let (owner,set)=if let Some(owner)=self.dictionary_owner(&object){(owner,false)}else if let Some((owner,_))=self.frozen_owner(&object){(owner,true)}else{return Ok(false)};
        if set&&matches!(op,ProtocolLookupOp::Contains|ProtocolLookupOp::Discard(_))&&self.frozen_owner(&key).is_some_and(|(_,frozen)|!frozen){let entries=self.frozen_entries(&key)?;key=self.frozen_make(entries,true);}
        let record=ProtocolLookup{object,owner,key:key.clone(),hash:known.unwrap_or(0),set,op,phase:if known.is_some(){ProtocolLookupPhase::Scan}else{ProtocolLookupPhase::Hash},index:0,entries:Vec::new()};
        if known.is_some(){self.protocol_lookup_scan(state,record)?;}else{state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Lookup(record))));state.plan=Some(ProtocolPlan{function:Value::Builtin("hash".into()),args:vec![key],kwargs:Vec::new()});}Ok(true)
    }
    fn protocol_lookup_hash(&mut self,record:&ProtocolLookup,index:usize,key:&Value)->Option<i64> {
        if record.set {match self.heap.get(record.owner).and_then(Option::as_ref){Some(Object::FrozenSet{hashes,..})=>hashes.get(index).copied(),_=>{let identity=self.identity_number(key);self.set_member_hashes.get(&record.owner).and_then(|map|map.get(&identity)).copied()}}}
        else{self.dictionary_hashes.get(&record.owner).and_then(|hashes|hashes.get(index)).and_then(|hash|*hash)}
    }
    fn protocol_lookup_unchanged(&self,record:&ProtocolLookup)->PyResult<bool> {
        let entries=self.assoc_entries(record.owner)?;
        Ok(entries.len()==record.entries.len()&&entries.iter().zip(&record.entries).all(|((left,_),(right,_))|left.same_identity(right)))
    }
    fn protocol_lookup_scan(&mut self,state:&mut ProtocolState,mut record:ProtocolLookup)->PyResult<()> {
        if record.entries.is_empty(){record.entries=self.assoc_entries(record.owner)?;record.index=0;}
        loop {
            if record.index>=record.entries.len(){return self.protocol_lookup_finish(state,record,None);}
            let key=record.entries[record.index].0.clone();
            let Some(hash)=self.protocol_lookup_hash(&record,record.index,&key)else{
                record.phase=ProtocolLookupPhase::StoredHash;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Lookup(record))));state.plan=Some(ProtocolPlan{function:Value::Builtin("hash".into()),args:vec![key],kwargs:Vec::new()});return Ok(());
            };
            if hash!=record.hash{record.index+=1;continue;}
            if key.same_identity(&record.key){let index=record.index;return self.protocol_lookup_finish(state,record,Some(index));}
            record.phase=ProtocolLookupPhase::Equal;let query=record.key.clone();state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Lookup(record))));self.protocol_compare_into(state,"==".into(),key,query)?;return Ok(());
        }
    }
    fn protocol_lookup_finish(&mut self,state:&mut ProtocolState,record:ProtocolLookup,found:Option<usize>)->PyResult<()> {
        let entries=self.assoc_entries(record.owner)?;
        let default_mode=matches!(&record.op,ProtocolLookupOp::SetDefault(_));
        match record.op {
            ProtocolLookupOp::Get{default,missing}=>{
                if let Some(index)=found {state.value=Some(entries[index].1.clone());}
                else if let Some(default)=default {state.value=Some(default);}
                else if missing {if let Some((method,class))=self.protocol_slot(&record.object,"__missing__"){self.protocol_bind(state,method,record.object,class,vec![record.key],Vec::new(),ProtocolAction::Pass,false)?;}else{return Err(Self::protocol_key_error(record.key));}}
                else{return Err(Self::protocol_key_error(record.key));}
            }
            ProtocolLookupOp::Contains=>state.value=Some(Value::Bool(found.is_some())),
            ProtocolLookupOp::Set(value)|ProtocolLookupOp::SetDefault(value)=>{
                let default=default_mode;
                if let Some(index)=found {
                    if default{state.value=Some(entries[index].1.clone());return Ok(());}
                    let Some(Object::Dict(items))=self.heap[record.owner].as_mut()else{return Err(pyerr("TypeError","dictionary is read-only"))};items[index].1=value.clone();
                }else{
                    let Some(Object::Dict(items))=self.heap[record.owner].as_mut()else{return Err(pyerr("TypeError","dictionary is read-only"))};let old=items.len();items.push((record.key.clone(),value.clone()));
                    let hashes=self.dictionary_hashes.entry(record.owner).or_default();hashes.resize(old,None);hashes.push(Some(record.hash));self.assoc_inserted(record.owner,record.key);
                }
                state.value=Some(if default{value}else{Value::None});
            }
            ProtocolLookupOp::Pop(default)=>{
                if let Some(index)=found {let Some(Object::Dict(items))=self.heap[record.owner].as_mut()else{return Err(pyerr("TypeError","dictionary is read-only"))};let (_,value)=items.remove(index);self.dictionary_remove_entry_hash(record.owner,index);self.assoc_dictionary_removed(record.owner,index);state.value=Some(value);}
                else if let Some(value)=default{state.value=Some(value);}else{return Err(Self::protocol_key_error(record.key));}
            }
            ProtocolLookupOp::Delete=>{
                let Some(index)=found else{return Err(Self::protocol_key_error(record.key));};let Some(Object::Dict(items))=self.heap[record.owner].as_mut()else{return Err(pyerr("TypeError","dictionary is read-only"))};items.remove(index);self.dictionary_remove_entry_hash(record.owner,index);self.assoc_dictionary_removed(record.owner,index);state.value=Some(Value::None);
            }
            ProtocolLookupOp::Add=>{
                if found.is_none(){let Some(Object::Set(items))=self.heap[record.owner].as_mut()else{return Err(pyerr("TypeError","cannot add to immutable set"))};items.push(record.key.clone());let identity=self.identity_number(&record.key);self.set_member_hashes.entry(record.owner).or_default().insert(identity,record.hash);self.assoc_inserted(record.owner,record.key);}
                state.value=Some(Value::None);
            }
            ProtocolLookupOp::Toggle=>{
                if let Some(index)=found {
                    let Some(Object::Set(items))=self.heap[record.owner].as_mut()else{return Err(pyerr("TypeError","cannot modify immutable set"))};
                    let key=items.remove(index);self.assoc_removed(record.owner,&key);
                }else {
                    let Some(Object::Set(items))=self.heap[record.owner].as_mut()else{return Err(pyerr("TypeError","cannot modify immutable set"))};
                    items.push(record.key.clone());let identity=self.identity_number(&record.key);
                    self.set_member_hashes.entry(record.owner).or_default().insert(identity,record.hash);self.assoc_inserted(record.owner,record.key);
                }
                state.value=Some(Value::None);
            }
            ProtocolLookupOp::Discard(required)=>{
                if let Some(index)=found{let Some(Object::Set(items))=self.heap[record.owner].as_mut()else{return Err(pyerr("TypeError","cannot remove from immutable set"))};let key=items.remove(index);self.assoc_removed(record.owner,&key);}
                else if required{return Err(Self::protocol_key_error(record.key));}state.value=Some(Value::None);
            }
        }Ok(())
    }
    fn start_protocol_build(&mut self,frame:&mut Frame,values:Vec<Value>,set:bool)->PyResult<()> {
        let owner=self.obj_value(if set{Object::Set(Vec::new())}else{Object::Dict(Vec::new())});
        let entries=if set{values.into_iter().map(|value|(value,Value::None)).collect()}else{values.chunks_exact(2).map(|values|(values[0].clone(),values[1].clone())).collect()};
        let mut state=Self::protocol_empty(ProtocolSink::Stack);state.value=Some(Value::None);state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Build{owner,entries,index:0,set})));frame.protocol=Some(state);self.resume_protocol(frame)
    }
    fn start_protocol_collection_mutation(&mut self,frame:&mut Frame,object:Value,key:Value,value:Option<Value>,set:bool)->PyResult<bool> {
        if matches!(&object,Value::Obj(owner)if matches!(self.heap.get(*owner).and_then(Option::as_ref),Some(Object::MappingProxy{..}))){return Ok(false);}
        let mut state=Self::protocol_empty(ProtocolSink::Discard);let op=if set{ProtocolLookupOp::Add}else if let Some(value)=value{ProtocolLookupOp::Set(value)}else{ProtocolLookupOp::Delete};
        if !self.protocol_collection_lookup(&mut state,object,key,op,None)?{return Ok(false);}frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn protocol_collection_compare(&mut self,state:&mut ProtocolState,op:&str,mut left:Value,mut right:Value)->PyResult<bool> {
        let dict=self.dictionary_owner(&left).is_some()&&self.dictionary_owner(&right).is_some();let set=self.frozen_owner(&left).is_some()&&self.frozen_owner(&right).is_some();
        if !dict&&!set{return Ok(false);}if dict&&!["==","!="].contains(&op){return Ok(false);}
        let lp=self.native_payload(&left).unwrap_or_else(||left.clone());let rp=self.native_payload(&right).unwrap_or_else(||right.clone());
        if set && self.protocol_set_native_input(&lp) && self.protocol_set_native_input(&rp) {
            state.value=Some(Value::Bool(self.frozen_compare(op,&left,&right).unwrap()?));return Ok(true);
        }
        let invert=op=="!=";let left_owner=if dict{self.dictionary_owner(&left).unwrap()}else{self.frozen_owner(&left).unwrap().0};let right_owner=if dict{self.dictionary_owner(&right).unwrap()}else{self.frozen_owner(&right).unwrap().0};
        let lsize=self.assoc_size(left_owner);let rsize=self.assoc_size(right_owner);
        let impossible=match op {"=="|"!="=>lsize!=rsize,"<"=>lsize>=rsize,"<="=>lsize>rsize,">"=>lsize<=rsize,">="=>lsize<rsize,_=>return Ok(false)};
        if impossible{state.value=Some(Value::Bool(invert));return Ok(true);}
        if left.same_identity(&right){state.value=Some(Value::Bool(!invert));return Ok(true);}
        if op==">"||op==">="{std::mem::swap(&mut left,&mut right);}
        let owner=if dict{self.dictionary_owner(&left).unwrap()}else{self.frozen_owner(&left).unwrap().0};let entries=self.assoc_entries(owner)?;
        state.value=Some(Value::Bool(true));state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Compare{left,right,entries,index:0,phase:0,set,invert})));Ok(true)
    }
    fn protocol_collection_compare_next(&mut self,state:&mut ProtocolState,left:Value,right:Value,entries:Vec<(Value,Value)>,index:usize,set:bool,invert:bool)->PyResult<()> {
        if index>=entries.len(){state.value=Some(Value::Bool(!invert));return Ok(());}
        let key=entries[index].0.clone();let owner=if set{self.frozen_owner(&left).unwrap().0}else{self.dictionary_owner(&left).unwrap()};
        let known=if set{let identity=self.identity_number(&key);match self.heap.get(owner).and_then(Option::as_ref){Some(Object::FrozenSet{hashes,..})=>hashes.get(index).copied(),_=>self.set_member_hashes.get(&owner).and_then(|hashes|hashes.get(&identity)).copied()}}else{self.dictionary_hashes.get(&owner).and_then(|hashes|hashes.get(index)).and_then(|hash|*hash)};
        state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Compare{left,right:right.clone(),entries,index,phase:1,set,invert})));
        self.protocol_collection_lookup(state,right,key,if set{ProtocolLookupOp::Contains}else{ProtocolLookupOp::Get{default:Some(Value::Builtin("$dict:missing_value".into())),missing:false}},known)?;Ok(())
    }
    fn start_protocol_contains(&mut self,frame:&mut Frame,key:Value,object:Value,reverse:bool)->PyResult<bool> {
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        state.actions.push_back(ProtocolAction::Collection(Box::new(ProtocolCollection::TruthResult(reverse))));
        if !self.protocol_contains_into(&mut state,key,object)? {return Ok(false);}
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
    fn protocol_contains_into(&mut self,state:&mut ProtocolState,key:Value,object:Value)->PyResult<bool> {
        let object=self.proxy_payload(&object).unwrap_or(object);
        if let Some((method,class))=self.protocol_slot(&object,"__contains__"){let recovery=ProtocolBindingRecovery::Contains(object.clone(),key.clone());self.protocol_bind_recover(state,method,object,class,vec![key],Vec::new(),ProtocolAction::ContainsResult,Some(recovery))?;}
        else if self.protocol_view_contains(state,object.clone(),key.clone())? {}
        else if !self.protocol_collection_lookup(state,object.clone(),key.clone(),ProtocolLookupOp::Contains,None)?{
            let payload=self.native_payload(&object).unwrap_or_else(||object.clone());
            // Closed numeric keys cannot run equality callbacks. Preserve the
            // exact arithmetic range path instead of walking its cardinality.
            // Subclasses/custom keys retain the queued comparison iterator.
            let range=if matches!(key,Value::Int(_)|Value::Bool(_)|Value::Float(_)) {
                match &payload {Value::Obj(index)=>match self.heap.get(*index).and_then(Option::as_ref){Some(Object::Range(start,stop,step))=>Some((start.inner().clone(),stop.inner().clone(),step.inner().clone())),_=>None},_=>None}
            }else{None};
            if let Some((start,stop,step))=range {
                state.value=Some(Value::Bool(self.range_contains(start,stop,step,key)?));return Ok(true);
            }
            if matches!(&payload,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::List(_)|Object::Tuple(_)))){self.protocol_search_next(state,ProtocolCollection::Search{owner:object,key,name:"__contains__".into(),index:0,count:0,stop:usize::MAX,phase:0,current:None})?;}
            else if matches!(payload,Value::Str(_)|Value::Bytes(_)){return Ok(false);}
            else {state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::IterateContains{iterator:Value::None,key,phase:0,reverse:false,current:None})));state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![object],kwargs:Vec::new()});}
        }
        Ok(true)
    }
    fn protocol_dict_keywords(&mut self,state:&mut ProtocolState,owner:Value,keywords:KeywordArgs,return_owner:bool)->PyResult<()> {
        state.value=Some(Value::None);state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Keywords{owner,keywords,index:0,return_owner})));Ok(())
    }
    fn protocol_view_contains(&mut self,state:&mut ProtocolState,object:Value,candidate:Value)->PyResult<bool> {
        let Value::Obj(at)=&object else{return Ok(false)};
        let Some(Object::DictView{owner,kind})=self.heap.get(*at).and_then(Option::as_ref)else{return Ok(false)};
        let (owner,kind)=(*owner,*kind);
        if kind==DictViewKind::Values {
            state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::IterateContains{iterator:Value::None,key:candidate,phase:0,reverse:false,current:None})));
            state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![object],kwargs:Vec::new()});return Ok(true);
        }
        let key=if kind==DictViewKind::Items {
            let payload=self.native_payload(&candidate).unwrap_or_else(||candidate.clone());
            let pair=match payload{Value::Obj(at)=>match self.object(at)?{Object::Tuple(pair)if pair.len()==2=>pair,_=>{state.value=Some(Value::Bool(false));return Ok(true);}},_=>{state.value=Some(Value::Bool(false));return Ok(true);}};
            state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::ItemsContains{owner:object,candidate,wanted:pair[1].clone()})));
            pair[0].clone()
        }else{candidate};
        self.protocol_collection_lookup(state,Value::Obj(owner),key,if kind==DictViewKind::Items{ProtocolLookupOp::Get{default:Some(Value::Builtin("$view:missing".into())),missing:false}}else{ProtocolLookupOp::Contains},None)?;
        Ok(true)
    }
    fn protocol_dict_input(&mut self,state:&mut ProtocolState,owner:Value,source:Value,kwargs:KeywordArgs,return_owner:bool)->PyResult<()> {
        self.protocol_dict_input_mode(state,owner,source,kwargs,return_owner,false)
    }
    fn protocol_dict_union(&mut self,state:&mut ProtocolState,left:Value,right:Value)->PyResult<()> {
        let out=self.obj_value(Object::Dict(Vec::new()));
        state.actions.push_front(ProtocolAction::Return(out.clone()));
        state.actions.push_front(ProtocolAction::Invoke(vec![out.clone(),right],Vec::new()));
        state.actions.push_front(ProtocolAction::Return(Value::Builtin("method:update".into())));
        self.protocol_dict_copy(state,out,left,Vec::new(),false)
    }
    fn protocol_dict_copy(&mut self,state:&mut ProtocolState,owner:Value,source:Value,kwargs:KeywordArgs,return_owner:bool)->PyResult<()> {
        // PyDict_Copy returns a new empty dictionary before consulting a
        // subclass's iteration or mapping slots, including hidden native MROs.
        let empty=self.native_capability_payload(&source,"dict").and_then(|payload|self.dictionary_owner(&payload)).is_some_and(|index|self.assoc_size(index)==0);
        if empty{return self.protocol_dict_keywords(state,owner,kwargs,return_owner);}
        self.protocol_dict_input_mode(state,owner,source,kwargs,return_owner,true)
    }
    fn protocol_dict_input_mode(&mut self,state:&mut ProtocolState,owner:Value,source:Value,kwargs:KeywordArgs,return_owner:bool,copy_method:bool)->PyResult<()> {
        if let Some(index)=self.dictionary_direct_source(&source){
            let target=self.dictionary_owner(&owner).ok_or_else(||pyerr("TypeError","expected dictionary destination"))?;
            if target==index{return self.protocol_dict_keywords(state,owner,kwargs,return_owner);}
            let entries=self.assoc_entries(index)?;
            // Cloning a clean table preserves stored hashes and comparisons.
            // Unknown hashes must stay queued because recovering one can call
            // Python; the native clone is used only when it is callback-free.
            let hashes_known=self.dictionary_hashes.get(&index).is_some_and(|hashes|hashes.len()>=entries.len()&&hashes[..entries.len()].iter().all(Option::is_some));
            if self.assoc_size(target)==0&&self.dictionary_can_clone(index,copy_method)&&(entries.is_empty()||hashes_known) {
                self.dictionary_clone_into(target,index)?;
                return self.protocol_dict_keywords(state,owner,kwargs,return_owner);
            }
            state.value=Some(Value::None);state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Copy{owner,source,entries,index:0,kwargs,return_owner})));
        }else{state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::DictInput{owner,source:source.clone(),kwargs,phase:0,iterator:None,key:None,pair:Vec::new(),index:0,mapping:false,return_owner})));state.plan=Some(ProtocolPlan{function:Value::Builtin("getattr".into()),args:vec![source,Value::Str("keys".into()),Value::Builtin("$dict:no_keys".into())],kwargs:Vec::new()});}Ok(())
    }
    fn protocol_set_input(&mut self,state:&mut ProtocolState,owner:Value,sources:Vec<Value>,frozen:bool,return_owner:bool)->PyResult<()> {
        state.value=Some(Value::None);state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::SetInput{owner,sources,source_index:0,iterator:None,phase:0,frozen,return_owner})));Ok(())
    }
    fn protocol_dict_advance(&mut self,state:&mut ProtocolState,mut record:ProtocolCollection)->PyResult<()> {
        let ProtocolCollection::DictInput{iterator,phase,..}=&mut record else{unreachable!()};let iterator=iterator.clone().unwrap();*phase=3;state.actions.push_front(ProtocolAction::Collection(Box::new(record)));state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![iterator,Value::Builtin("$dict:end".into())],kwargs:Vec::new()});Ok(())
    }
    fn protocol_dict_item(&mut self,state:&mut ProtocolState,object:Value,key:Value)->PyResult<()> {
        let object=self.proxy_payload(&object).unwrap_or(object);
        if let Some((method,class))=self.protocol_slot(&object,"__getitem__"){self.protocol_bind(state,method,object,class,vec![key],Vec::new(),ProtocolAction::Pass,false)?;}
        else if !self.protocol_dict_getitem(state,object.clone(),key.clone())?{state.value=Some(self.getitem(object,key)?);}Ok(())
    }
    fn protocol_collection_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let Value::Builtin(function)=&plan.function else{return Ok(false)};
        if function=="dict"{
            if plan.args.len()>1{return Err(pyerr("TypeError","dict expected at most 1 argument"));}let owner=self.obj_value(Object::Dict(Vec::new()));
            if let Some(source)=plan.args.first(){self.protocol_dict_input(state,owner,source.clone(),plan.kwargs.clone(),true)?;}else{self.protocol_dict_keywords(state,owner,plan.kwargs.clone(),true)?;}return Ok(true);
        }
        if function=="set"||function=="frozenset"{
            if plan.args.len()>1||!plan.kwargs.is_empty(){return Err(pyerr("TypeError",format!("{function} expected at most one positional argument")));}
            if plan.args.first().is_some_and(|source|self.protocol_set_native_input(source)) {
                state.value=Some(if function=="set"{self.set_constructor_value(plan.args.clone(),plan.kwargs.clone())?}else{self.frozen_constructor(plan.args.clone(),plan.kwargs.clone())?});return Ok(true);
            }
            if function=="frozenset"{if let Some(value)=plan.args.first(){if matches!(value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::FrozenSet{..}))){state.value=Some(value.clone());return Ok(true);}}}
            let owner=self.obj_value(Object::Set(Vec::new()));self.protocol_set_input(state,owner,plan.args.clone(),function=="frozenset",true)?;return Ok(true);
        }
        if function=="hash" && plan.args.len()==1 && plan.kwargs.is_empty() && self.protocol_slot(&plan.args[0],"__hash__").is_none(){
            let payload=self.native_payload(&plan.args[0]).unwrap_or_else(||plan.args[0].clone());if let Value::Obj(index)=payload {if let Object::Tuple(items)=self.object(index)? {
                if items.is_empty(){state.value=Some(Value::Int(Int::from_i128(0x345678).into()));}else{
                    state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::TupleHash{owner:plan.args[0].clone(),items:items.clone(),index:0,hash:0x345678})));state.plan=Some(ProtocolPlan{function:Value::Builtin("hash".into()),args:vec![items[0].clone()],kwargs:Vec::new()});
                }return Ok(true);
            }}
        }
        let name=if let Some(name)=function.strip_prefix("method:"){name.to_owned()}else if let Some((_,_,name))=native_attribute_parts(&plan.function){name.to_owned()}else if let Some(name)=function.strip_prefix("unbound:"){name.split_once(':').map(|(_,name)|name.to_owned()).unwrap_or_default()}else{return Ok(false)};
        let Some(object)=plan.args.first().cloned()else{return Ok(false)};
        if let Some(inner)=self.proxy_payload(&object) {
            if name=="__getitem__" {
                if plan.args.len()!=2||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","__getitem__ expected one argument"));}
                state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::ProxyResult(object))));
                self.protocol_dict_item(state,inner,plan.args[1].clone())?;return Ok(true);
            }
            if ["copy","get","keys","values","items"].contains(&name.as_str()) {
                state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::ProxyResult(object))));
                state.actions.push_front(ProtocolAction::Invoke(plan.args[1..].to_vec(),plan.kwargs.clone()));
                state.plan=Some(ProtocolPlan{function:Value::Builtin("getattr".into()),args:vec![inner,Value::Str(name.into())],kwargs:Vec::new()});return Ok(true);
            }
            if name=="__contains__" {
                if plan.args.len()!=2||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","__contains__ expected one argument"));}
                state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::ProxyResult(object))));
                state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::TruthResult(false))));
                return self.protocol_contains_into(state,plan.args[1].clone(),inner);
            }
        }
        if name=="__contains__" && self.view_kind(&object).is_some() {
            if plan.args.len()!=2||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","__contains__ expected one argument"));}
            return self.protocol_view_contains(state,object,plan.args[1].clone());
        }
        if self.dictionary_owner(&object).is_some(){
            if matches!(native_attribute_parts(&plan.function),Some((_,"dict","__or__"|"__ror__")))&&plan.args.len()==2&&plan.kwargs.is_empty(){
                let argument=plan.args[1].clone();
                if self.native_capability_payload(&argument,"dict").is_none(){state.value=Some(Value::Builtin("NotImplemented".into()));return Ok(true);}
                let (left,right)=if name=="__ror__"{(argument,object)}else{(object,argument)};
                self.protocol_dict_union(state,left,right)?;return Ok(true);
            }
            if name=="update"{if plan.args.len()>2{return Err(pyerr("TypeError","update expected at most one argument"));}if let Some(source)=plan.args.get(1){self.protocol_dict_input(state,object,source.clone(),plan.kwargs.clone(),false)?;}else{self.protocol_dict_keywords(state,object,plan.kwargs.clone(),false)?;}return Ok(true);}

            let count=plan.args.len()-1;let mutating=["__setitem__","__delitem__","pop","setdefault"].contains(&name.as_str());if mutating&&matches!(&object,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::MappingProxy{..}))){return Ok(false);}
            let valid=match name.as_str(){"get"|"pop"|"setdefault"=>(1..=2).contains(&count),"__getitem__"|"__contains__"|"__delitem__"=>count==1,"__setitem__"=>count==2,_=>return Ok(false)};
            if !valid||!plan.kwargs.is_empty(){return Err(pyerr("TypeError",format!("invalid arguments for {name}")));}
            let key=plan.args[1].clone();let op=match name.as_str(){"get"=>ProtocolLookupOp::Get{default:Some(plan.args.get(2).cloned().unwrap_or(Value::None)),missing:false},"pop"=>ProtocolLookupOp::Pop(plan.args.get(2).cloned()),"setdefault"=>ProtocolLookupOp::SetDefault(plan.args.get(2).cloned().unwrap_or(Value::None)),"__getitem__"=>ProtocolLookupOp::Get{default:None,missing:true},"__contains__"=>ProtocolLookupOp::Contains,"__setitem__"=>ProtocolLookupOp::Set(plan.args[2].clone()),_=>ProtocolLookupOp::Delete};return self.protocol_collection_lookup(state,object,key,op,None);
        }
        if self.frozen_owner(&object).is_some_and(|(_,frozen)|!frozen)&&name=="update"{if !plan.kwargs.is_empty(){return Err(pyerr("TypeError","update takes no keyword arguments"));}self.protocol_set_input(state,object,plan.args[1..].to_vec(),false,false)?;return Ok(true);}
        if self.frozen_owner(&object).is_some() && ["add","discard","remove","__contains__"].contains(&name.as_str()){
            if plan.args.len()!=2||!plan.kwargs.is_empty(){return Err(pyerr("TypeError",format!("{name} takes one argument")));}let op=match name.as_str(){"add"=>ProtocolLookupOp::Add,"discard"=>ProtocolLookupOp::Discard(false),"remove"=>ProtocolLookupOp::Discard(true),_=>ProtocolLookupOp::Contains};return self.protocol_collection_lookup(state,object,plan.args[1].clone(),op,None);
        }
        let payload=self.native_payload(&object).unwrap_or_else(||object.clone());
        if let Value::Obj(index)=payload {if matches!(self.object(index)?,Object::List(_)|Object::Tuple(_))&&["count","index","remove","__contains__"].contains(&name.as_str()){
            let count=plan.args.len()-1;if count<1||count>if name=="index"{3}else{1}||!plan.kwargs.is_empty(){return Err(pyerr("TypeError",format!("invalid arguments for {name}")));}
            let len=match self.object(index)?{Object::List(items)|Object::Tuple(items)=>items.len(),_=>unreachable!()};
            let bound=|runtime:&mut Self,value:Option<&Value>,default:usize|->PyResult<usize>{if let Some(value)=value{let n=runtime.index_identity(value)?.into_inner();let n=n.to_i128().unwrap_or(if n.is_negative(){i128::MIN}else{i128::MAX});Ok(if n<0{(len as i128).saturating_add(n).max(0) as usize}else{n.min(usize::MAX as i128) as usize})}else{Ok(default)}};
            let start=bound(self,plan.args.get(2),0)?;let stop=bound(self,plan.args.get(3),usize::MAX)?;
            self.protocol_search_next(state,ProtocolCollection::Search{owner:object,key:plan.args[1].clone(),name,index:start,count:0,stop,phase:0,current:None})?;return Ok(true);
        }}Ok(false)
    }
    fn protocol_search_next(&mut self,state:&mut ProtocolState,mut record:ProtocolCollection)->PyResult<()> {
        let ProtocolCollection::Search{owner,key,name,index,count,stop,phase,current}=&mut record else{unreachable!()};
        let payload=self.native_payload(owner).unwrap_or_else(||owner.clone());let Value::Obj(at)=payload else{unreachable!()};let items=match self.object(at)?{Object::List(items)|Object::Tuple(items)=>items,_=>unreachable!()};
        if *index>=items.len()||*index>=*stop{state.value=Some(match name.as_str(){"count"=>Value::Int(Int::from_i128(*count as i128).into()),"__contains__"=>Value::Bool(false),_=>return Err(pyerr("ValueError",if name=="remove"{"list.remove(x): x not in list"}else{"value is not in sequence"}))});return Ok(());}
        let stored=items[*index].clone();*current=Some(stored.clone());*phase=1;let query=key.clone();
        if stored.same_identity(&query){state.value=Some(Value::Bool(true));state.actions.push_front(ProtocolAction::Collection(Box::new(record)));}
        else{state.actions.push_front(ProtocolAction::Collection(Box::new(record)));self.protocol_compare_into(state,"==".into(),stored,query)?;}Ok(())
    }
    fn protocol_collection_result(&mut self,state:&mut ProtocolState,record:ProtocolCollection,value:Value)->PyResult<()> {
        match record {
            ProtocolCollection::ProxyResult(_)=>state.value=Some(value),
            ProtocolCollection::Compare{left,right,entries,index,phase,set,invert}=>{
                if phase==0{return self.protocol_collection_compare_next(state,left,right,entries,index,set,invert);}
                if phase==1{
                    if set{if !self.truth(&value)?{state.value=Some(Value::Bool(invert));return Ok(());}return self.protocol_collection_compare_next(state,left,right,entries,index+1,set,invert);}
                    if matches!(&value,Value::Builtin(name)if name=="$dict:missing_value"){state.value=Some(Value::Bool(invert));return Ok(());}
                    let expected=entries[index].1.clone();if expected.same_identity(&value){return self.protocol_collection_compare_next(state,left,right,entries,index+1,set,invert);}
                    state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Compare{left,right,entries,index,phase:2,set,invert})));self.protocol_compare_into(state,"==".into(),expected,value)?;
                }else if phase==2{state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Compare{left,right,entries,index,phase:3,set,invert})));if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}}
                else if self.truth(&value)?{self.protocol_collection_compare_next(state,left,right,entries,index+1,set,invert)?;}else{state.value=Some(Value::Bool(invert));}
            }
            ProtocolCollection::TruthResult(reverse)=>{
                if let Value::Bool(value)=value{state.value=Some(Value::Bool(value!=reverse));}
                else{state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::TruthResult(reverse))));if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}}
            }
            ProtocolCollection::ItemsContains{owner:_,candidate:_,wanted}=>{
                if matches!(&value,Value::Builtin(name)if name=="$view:missing"){state.value=Some(Value::Bool(false));}
                else if value.same_identity(&wanted){state.value=Some(Value::Bool(true));}
                else{state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::TruthResult(false))));self.protocol_compare_into(state,"==".into(),value,wanted)?;}
            }
            ProtocolCollection::IterateContains{mut iterator,key,mut phase,reverse,mut current}=>{
                if phase==0{iterator=value;phase=1;}
                else if phase==2{if matches!(&value,Value::Builtin(name)if name=="$contains:end"){state.value=Some(Value::Bool(reverse));return Ok(());}if value.same_identity(&key){state.value=Some(Value::Bool(!reverse));return Ok(());}current=Some(value.clone());phase=3;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::IterateContains{iterator,key:key.clone(),phase,reverse,current})));self.protocol_compare_into(state,"==".into(),value,key)?;return Ok(());}
                else if phase==3{phase=4;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::IterateContains{iterator,key,phase,reverse,current})));if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}return Ok(());}
                else if phase==4{if self.truth(&value)?{state.value=Some(Value::Bool(!reverse));return Ok(());}phase=1;current=None;}
                if phase==1{phase=2;state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![iterator.clone(),Value::Builtin("$contains:end".into())],kwargs:Vec::new()});}
                state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::IterateContains{iterator,key,phase,reverse,current})));
            }
            ProtocolCollection::SetCopy{owner,source,entries,index}=>{
                let target=self.frozen_owner(&owner).unwrap().0;
                if index==0 && self.frozen_owner(&source).is_some_and(|(source,_)|source==target) {
                    state.value=Some(Value::None);return Ok(());
                }
                if index==0 && self.assoc_size(target)==0 {
                    let mut hashes=HashMap::new();
                    for (key,hash) in &entries {hashes.insert(self.identity_number(key),*hash);}
                    self.heap[target]=Some(Object::Set(entries.iter().map(|(key,_)|key.clone()).collect()));
                    self.set_member_hashes.insert(target,hashes);self.assoc_sync(target)?;
                    state.value=Some(Value::None);return Ok(());
                }
                if index>=entries.len(){state.value=Some(Value::None);}else{let (key,hash)=entries[index].clone();state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::SetCopy{owner:owner.clone(),source,entries,index:index+1})));self.protocol_collection_lookup(state,owner,key,ProtocolLookupOp::Add,Some(hash))?;}
            }
            ProtocolCollection::Keywords{owner,keywords,index,return_owner}=>{
                if index==keywords.len(){state.value=Some(if return_owner{owner}else{Value::None});}
                else{let (key,value)=keywords[index].clone();let known=key.hash;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Keywords{owner:owner.clone(),keywords,index:index+1,return_owner})));self.protocol_collection_lookup(state,owner,key.original,ProtocolLookupOp::Set(value),known)?;}
            }
            ProtocolCollection::Copy{owner,source,entries,index,kwargs,return_owner}=>{
                if index==entries.len(){self.protocol_dict_keywords(state,owner,kwargs,return_owner)?;}
                else{let (key,value)=entries[index].clone();let source_owner=self.dictionary_owner(&source).unwrap();let known=self.dictionary_hashes.get(&source_owner).and_then(|hashes|hashes.get(index)).and_then(|hash|*hash);state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Copy{owner:owner.clone(),source,entries,index:index+1,kwargs,return_owner})));self.protocol_collection_lookup(state,owner,key,ProtocolLookupOp::Set(value),known)?;}
            }
            ProtocolCollection::DictInput{owner,source,kwargs,mut phase,mut iterator,mut key,mut pair,mut index,mut mapping,return_owner}=>{
                match phase {
                    0=>{if matches!(&value,Value::Builtin(name)if name=="$dict:no_keys"){phase=2;mapping=false;state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![source.clone()],kwargs:Vec::new()});}else{phase=1;mapping=true;state.plan=Some(ProtocolPlan{function:value,args:Vec::new(),kwargs:Vec::new()});}}
                    1=>{phase=2;state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![value],kwargs:Vec::new()});}
                    2=>{iterator=Some(value);return self.protocol_dict_advance(state,ProtocolCollection::DictInput{owner,source,kwargs,phase,iterator,key,pair,index,mapping,return_owner});}
                    3=>{
                        if matches!(&value,Value::Builtin(name)if name=="$dict:end"){return self.protocol_dict_keywords(state,owner,kwargs,return_owner);}
                        if mapping{key=Some(value.clone());phase=4;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::DictInput{owner,source:source.clone(),kwargs,phase,iterator,key,pair,index,mapping,return_owner})));return self.protocol_dict_item(state,source,value);}
                        key=Some(value.clone());phase=5;state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![value],kwargs:Vec::new()});
                    }
                    4=>{phase=8;let entry=key.clone().unwrap();state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::DictInput{owner:owner.clone(),source,kwargs,phase,iterator,key,pair,index,mapping,return_owner})));self.protocol_collection_lookup(state,owner,entry,ProtocolLookupOp::Set(value),None)?;return Ok(());}
                    5=>{phase=6;pair.clear();key=Some(value.clone());state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![value,Value::Builtin("$dict:pair_end".into())],kwargs:Vec::new()});}
                    6=>{
                        if matches!(&value,Value::Builtin(name)if name=="$dict:pair_end"){if pair.len()!=2{return Err(pyerr("ValueError",format!("dictionary update sequence element #{index} has length {}; 2 is required",pair.len())));}let entry_key=pair[0].clone();let entry_value=pair[1].clone();phase=8;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::DictInput{owner:owner.clone(),source,kwargs,phase,iterator,key,pair,index,mapping,return_owner})));self.protocol_collection_lookup(state,owner,entry_key,ProtocolLookupOp::Set(entry_value),None)?;return Ok(());}
                        pair.push(value);state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![key.clone().unwrap(),Value::Builtin("$dict:pair_end".into())],kwargs:Vec::new()});
                    }
                    8=>{index+=1;return self.protocol_dict_advance(state,ProtocolCollection::DictInput{owner,source,kwargs,phase,iterator,key,pair,index,mapping,return_owner});}
                    _=>unreachable!(),
                }
                state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::DictInput{owner,source,kwargs,phase,iterator,key,pair,index,mapping,return_owner})));
            }
            ProtocolCollection::SetInput{owner,sources,mut source_index,mut iterator,mut phase,frozen,return_owner}=>{
                if phase==1{iterator=Some(value);phase=2;}
                else if phase==3{if matches!(&value,Value::Builtin(name)if name=="$set:end"){source_index+=1;iterator=None;phase=0;}else{phase=2;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::SetInput{owner:owner.clone(),sources,source_index,iterator,phase,frozen,return_owner})));self.protocol_collection_lookup(state,owner,value,ProtocolLookupOp::Add,None)?;return Ok(());}}
                if phase==0{if source_index>=sources.len(){if frozen{let Value::Obj(index)=owner else{unreachable!()};let entries=self.frozen_entries(&Value::Obj(index))?;let result=self.frozen_make(entries,true);state.value=Some(if return_owner{result}else{Value::None});}else{state.value=Some(if return_owner{owner}else{Value::None});}return Ok(());}if self.frozen_owner(&sources[source_index]).is_some(){let source=sources[source_index].clone();let entries=self.frozen_entries(&source)?;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::SetInput{owner:owner.clone(),sources,source_index:source_index+1,iterator:None,phase:0,frozen,return_owner})));state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::SetCopy{owner,source,entries,index:0})));state.value=Some(Value::None);return Ok(());}phase=1;state.plan=Some(ProtocolPlan{function:Value::Builtin("iter".into()),args:vec![sources[source_index].clone()],kwargs:Vec::new()});}
                else if phase==2{phase=3;state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![iterator.clone().unwrap(),Value::Builtin("$set:end".into())],kwargs:Vec::new()});}
                state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::SetInput{owner,sources,source_index,iterator,phase,frozen,return_owner})));
            }
            ProtocolCollection::Lookup(mut record)=>match record.phase {
                ProtocolLookupPhase::Hash=>{record.hash=self.as_int(&value)?.to_i128().unwrap_or(0) as i64;record.phase=ProtocolLookupPhase::Scan;self.protocol_lookup_scan(state,record)?;}
                ProtocolLookupPhase::Scan=>unreachable!(),
                ProtocolLookupPhase::StoredHash=>{
                    if !self.protocol_lookup_unchanged(&record)?{record.entries.clear();record.index=0;record.phase=ProtocolLookupPhase::Scan;self.protocol_lookup_scan(state,record)?;return Ok(());}
                    let hash=self.as_int(&value)?.to_i128().unwrap_or(0) as i64;let stored=&record.entries[record.index].0;
                    if record.set{let identity=self.identity_number(stored);self.set_member_hashes.entry(record.owner).or_default().insert(identity,hash);}else{let hashes=self.dictionary_hashes.entry(record.owner).or_default();hashes.resize(record.entries.len(),None);hashes[record.index]=Some(hash);}
                    record.phase=ProtocolLookupPhase::Scan;self.protocol_lookup_scan(state,record)?;
                }
                ProtocolLookupPhase::Equal=>{
                    record.phase=ProtocolLookupPhase::Truth;state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Lookup(record))));if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}
                }
                ProtocolLookupPhase::Truth=>{
                    let matched=self.truth(&value)?;if !self.protocol_lookup_unchanged(&record)?{record.entries.clear();record.index=0;record.phase=ProtocolLookupPhase::Scan;self.protocol_lookup_scan(state,record)?;}else if matched{let index=record.index;self.protocol_lookup_finish(state,record,Some(index))?;}else{record.index+=1;record.phase=ProtocolLookupPhase::Scan;self.protocol_lookup_scan(state,record)?;}
                }
            },
            ProtocolCollection::Build{owner,entries,index,set}=>{
                if index>=entries.len(){state.value=Some(owner);}else{let (key,value)=entries[index].clone();state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Build{owner:owner.clone(),entries,index:index+1,set})));self.protocol_collection_lookup(state,owner,key,if set{ProtocolLookupOp::Add}else{ProtocolLookupOp::Set(value)},None)?;}
            }
            ProtocolCollection::TupleHash{owner,items,index,hash}=>{
                let part=self.as_int(&value)?.to_i128().unwrap_or(0) as u64;let hash=(hash^part).wrapping_mul(1_000_003);let index=index+1;
                if index==items.len(){let hash=(hash^items.len() as u64) as i64;state.value=Some(Value::Int(Int::from_i128(if hash == -1{-2}else{hash} as i128).into()));}
                else{let value=items[index].clone();state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::TupleHash{owner,items,index,hash})));state.plan=Some(ProtocolPlan{function:Value::Builtin("hash".into()),args:vec![value],kwargs:Vec::new()});}
            }
            ProtocolCollection::Search{owner,key,name,mut index,mut count,stop,phase,current}=>{
                if phase==1{state.actions.push_front(ProtocolAction::Collection(Box::new(ProtocolCollection::Search{owner,key,name,index,count,stop,phase:2,current})));if !self.protocol_python_truth(state,value.clone())?{state.value=Some(Value::Bool(self.truth(&value)?));}return Ok(());}
                if self.truth(&value)?{match name.as_str(){"__contains__"=>{state.value=Some(Value::Bool(true));return Ok(());},"index"=>{state.value=Some(Value::Int(Int::from_i128(index as i128).into()));return Ok(());},"remove"=>{let payload=self.native_payload(&owner).unwrap_or(owner);if let Value::Obj(at)=payload{if let Some(Object::List(items))=self.heap[at].as_mut(){if index<items.len(){items.remove(index);}}}state.value=Some(Value::None);return Ok(());},_=>count+=1}}
                index+=1;self.protocol_search_next(state,ProtocolCollection::Search{owner,key,name,index,count,stop,phase:0,current:None})?;
            }
        }Ok(())
    }
}
