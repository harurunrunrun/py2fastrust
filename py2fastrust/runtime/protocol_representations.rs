// Native container formatting queues each Python repr callback in its caller.
#[derive(Clone,Debug)]
enum ProtocolReprPhase { Next, Item, Key, Value }
#[derive(Clone,Debug)]
enum ProtocolReprSource { Iterator(Value), Dictionary{owner:usize,cursor:usize}, Snapshot{items:Vec<Value>,index:usize} }
impl ProtocolReprSource {fn roots(&self,out:&mut Vec<Value>){match self{Self::Iterator(value)=>out.push(value.clone()),Self::Dictionary{owner,..}=>out.push(Value::Obj(*owner)),Self::Snapshot{items,..}=>out.extend(items.iter().cloned())}}}
#[derive(Clone,Debug)]
enum ProtocolRepresentation {
    Container{owner:Value,guard:usize,source:ProtocolReprSource,open:String,close:String,separator:String,text:String,count:usize,tuple:bool,mapping:bool,phase:ProtocolReprPhase,pending:Vec<Value>},
    Ascii,
    Format(Option<Value>),
    Wrapped{owner:Value,open:String,close:String},
}
impl ProtocolRepresentation {
    fn roots(&self,out:&mut Vec<Value>) {match self {
        Self::Container{owner,source,pending,..}=>{out.push(owner.clone());source.roots(out);out.extend(pending.iter().cloned());},
        Self::Format(value)=>out.extend(value.iter().cloned()),Self::Wrapped{owner,..}=>out.push(owner.clone()),_=>{},
    }}
    fn guard(&self)->Option<usize> {match self{Self::Container{guard,..}=>Some(*guard),_=>None}}
}
impl Runtime {
    fn protocol_abandon(&mut self,frame:&mut Frame) {if let Some(mut state)=frame.protocol.take(){self.protocol_stream_abandon(&state);self.protocol_sort_abandon(&mut state);self.protocol_release_repr_guards(&mut state);}}
    fn protocol_release_repr_guards(&mut self,state:&mut ProtocolState) {for guard in state.repr_guards.drain(..){self.protocol_repr_active.remove(&guard);}}
    fn protocol_sync_repr_guards(&mut self,state:&mut ProtocolState) {
        let active=state.actions.iter().filter_map(|action|match action{ProtocolAction::Representation(record)=>record.guard(),_=>None}).collect::<std::collections::HashSet<_>>();
        state.repr_guards.retain(|guard|if active.contains(guard){true}else{self.protocol_repr_active.remove(guard);false});
    }
    fn protocol_repr_recursive(&self,value:&Value)->Option<String> {
        let Value::Obj(index)=value else{return None};if !self.protocol_repr_active.contains(index){return None;}
        let payload=self.native_payload(value).unwrap_or_else(||value.clone());
        let Value::Obj(owner)=payload else{return Some("...".into())};
        Some(match self.heap.get(owner).and_then(Option::as_ref){Some(Object::List(_))=>"[...]".into(),Some(Object::Tuple(_))=>"(...)".into(),Some(Object::Dict(_)|Object::Namespace(..))=>"{...}".into(),Some(Object::Set(_)|Object::FrozenSet{..})=>format!("{}(...)",self.typename(value)),_=>"...".into()})
    }
    fn protocol_representation_builtin(&mut self,state:&mut ProtocolState,plan:&ProtocolPlan)->PyResult<bool> {
        let normalized;
        let Value::Builtin(function)=&plan.function else{return Ok(false)};
        let method=function.strip_prefix("method:").or_else(||native_attribute_parts(&plan.function).map(|(_,_,name)|name)).or_else(||function.strip_prefix("unbound:").and_then(|name|name.split_once(':').map(|(_,name)|name)));
        let plan=if let Some(method)=method{let name=match method{"__repr__"=>"repr","__str__"=>"str",_=>return Ok(false)};normalized=ProtocolPlan{function:Value::Builtin(name.into()),args:plan.args.clone(),kwargs:plan.kwargs.clone()};&normalized}else{plan};
        let Value::Builtin(name)=&plan.function else{unreachable!()};
        if name=="format" {if !(1..=2).contains(&plan.args.len())||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","format expected 1 or 2 positional arguments"));}self.protocol_format_into(state,plan.args[0].clone(),-1,plan.args.get(1).cloned())?;return Ok(true);}
        if !["repr","str","ascii"].contains(&name.as_str()){return Ok(false);}
        if name=="ascii" {
            if plan.args.len()!=1||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","ascii() takes one positional argument"));}
            state.actions.push_front(ProtocolAction::Representation(Box::new(ProtocolRepresentation::Ascii)));
            state.plan=Some(ProtocolPlan{function:Value::Builtin("repr".into()),args:plan.args.clone(),kwargs:Vec::new()});return Ok(true);
        }
        let value=if name=="str" {if plan.args.len()>1{return Ok(false);}let mut args=codec_bind("str",plan.args.clone(),plan.kwargs.clone(),&["object","encoding","errors"])?;if args[1].is_some()||args[2].is_some(){return Ok(false);}let Some(value)=args[0].take()else{return Ok(false)};value}else{
            if plan.args.len()!=1||!plan.kwargs.is_empty(){return Err(pyerr("TypeError","repr() takes one positional argument"));}plan.args[0].clone()
        };
        if name=="str"{if let Value::Obj(index)=&value {if let Object::Exception(error)=self.object(*index)? {
            if error.group.is_some(){state.value=Some(Value::Str(self.exception_cached_message(&error)?.into()));return Ok(true);}
            match error.args.as_slice(){[]=>state.value=Some(Value::Str(String::new().into())),[argument]=>state.plan=Some(ProtocolPlan{function:Value::Builtin(if self.exception_has_native_class(&error,"KeyError"){"repr"}else{"str"}.into()),args:vec![argument.clone()],kwargs:Vec::new()}),_=>{let tuple=self.obj_value(Object::Tuple(error.args.clone()));state.plan=Some(ProtocolPlan{function:Value::Builtin("repr".into()),args:vec![tuple],kwargs:Vec::new()});}}return Ok(true);
        }}}
        if name=="str" {if let Value::Obj(owner)=&value {if let Some(Object::MappingProxy{owner:dictionary})=self.heap.get(*owner).and_then(Option::as_ref) {
            let inner=self.collection_keepers.get(owner).cloned().unwrap_or(Value::Obj(*dictionary));
            state.actions.push_front(ProtocolAction::Representation(Box::new(ProtocolRepresentation::Wrapped{owner:value,open:String::new(),close:String::new()})));
            state.plan=Some(ProtocolPlan{function:Value::Builtin("str".into()),args:vec![inner],kwargs:Vec::new()});return Ok(true);
        }}}
        self.protocol_container_repr(state,value)
    }
    fn protocol_container_repr(&mut self,state:&mut ProtocolState,value:Value)->PyResult<bool> {
        if let Some(text)=self.protocol_repr_recursive(&value){state.value=Some(Value::Str(text.into()));return Ok(true);}
        let payload=self.native_payload(&value).unwrap_or_else(||value.clone());
        let Value::Obj(owner)=payload.clone()else{return Ok(false)};
        let (open,close,tuple,mapping,source)=match self.object(owner)? {
            Object::List(_)=>("[".into(),"]".into(),false,false,ProtocolReprSource::Iterator(self.iter(payload)?)),
            Object::Tuple(_)=>("(".into(),")".into(),true,false,ProtocolReprSource::Iterator(self.iter(payload)?)),
            Object::Dict(_)|Object::Namespace(..)=>("{".into(),"}".into(),false,true,ProtocolReprSource::Dictionary{owner,cursor:0}),
            Object::Set(ref items) if items.is_empty()=>{let name=if self.object_class(&value).is_some(){self.typename(&value)}else{"set".into()};state.value=Some(Value::Str(format!("{name}()").into()));return Ok(true);}
            Object::Set(items)=>{let (open,close)=if self.object_class(&value).is_some(){(format!("{}({{",self.typename(&value)),"})".into())}else{("{".into(),"}".into())};(open,close,false,false,ProtocolReprSource::Snapshot{items,index:0})},
            Object::FrozenSet{ref items,..}=>{
                let name=if self.object_class(&value).is_some(){self.typename(&value)}else{"frozenset".into()};
                if items.is_empty(){state.value=Some(Value::Str(format!("{name}()").into()));return Ok(true);}
                (format!("{name}({{"),"})".into(),false,false,ProtocolReprSource::Snapshot{items:items.clone(),index:0})
            }
            Object::DictView{owner:dictionary,kind}=>(format!("{}([",kind.name()),"])".into(),false,false,ProtocolReprSource::Iterator(self.assoc_iterator(dictionary,kind,false)?)),
            Object::MappingProxy{owner:dictionary}=>{
                let inner=self.collection_keepers.get(&owner).cloned().unwrap_or(Value::Obj(dictionary));state.actions.push_front(ProtocolAction::Representation(Box::new(ProtocolRepresentation::Wrapped{owner:value,open:"mappingproxy(".into(),close:")".into()})));state.plan=Some(ProtocolPlan{function:Value::Builtin("repr".into()),args:vec![inner],kwargs:Vec::new()});return Ok(true);
            }
            Object::Exception(error) if error.group.is_none()=>(format!("{}(",self.exception_type_name(&error)),")".into(),false,false,ProtocolReprSource::Snapshot{items:error.args.clone(),index:0}),
            Object::Partial{function,args,..}=>{let mut items=vec![function];items.extend(args);("functools.partial(".into(),")".into(),false,false,ProtocolReprSource::Snapshot{items,index:0})}
            _=>return Ok(false),
        };
        let guard=match value{Value::Obj(index)=>index,_=>owner};
        let guarded=matches!(self.heap.get(owner).and_then(Option::as_ref),Some(Object::List(_)|Object::Tuple(_)|Object::Dict(_)|Object::Namespace(..)|Object::Set(_)|Object::FrozenSet{..}|Object::DictView{..}));
        if guarded{self.protocol_repr_active.insert(guard);state.repr_guards.push(guard);}
        let record=ProtocolRepresentation::Container{owner:value,guard,source,open,close,separator:", ".into(),text:String::new(),count:0,tuple,mapping,phase:ProtocolReprPhase::Next,pending:Vec::new()};
        self.protocol_repr_next(state,record);Ok(true)
    }
    fn protocol_repr_next(&mut self,state:&mut ProtocolState,mut record:ProtocolRepresentation) {
        let ProtocolRepresentation::Container{source,..}=&mut record else{unreachable!()};
        let next=match source {
            ProtocolReprSource::Iterator(iterator)=>{let iterator=iterator.clone();state.actions.push_front(ProtocolAction::Representation(Box::new(record)));state.plan=Some(ProtocolPlan{function:Value::Builtin("next".into()),args:vec![iterator,Value::Builtin("$repr:end".into())],kwargs:Vec::new()});return;}
            ProtocolReprSource::Snapshot{items,index}=>{let value=items.get(*index).cloned();*index+=1;value}
            ProtocolReprSource::Dictionary{owner,cursor}=>{
                // PyDict_Next-style cursor: values may change, deletions leave
                // holes, and later insertions are visible without invalidation.
                let entries=self.assoc_entries(*owner).unwrap_or_default();let _=self.assoc_sync(*owner);let mut found=None;
                if let Some(layout)=self.assoc_layouts.get(owner){while *cursor<layout.slots.len(){let key=layout.slots[*cursor].clone();*cursor+=1;if let Some(key)=key{if let Some((key,value))=entries.iter().find(|(stored,_)|stored.same_identity(&key)){found=Some((key.clone(),value.clone()));break;}}}}
                found.map(|(key,value)|self.obj_value(Object::Tuple(vec![key,value])))
            }
        };
        state.actions.push_front(ProtocolAction::Representation(Box::new(record)));state.value=Some(next.unwrap_or_else(||Value::Builtin("$repr:end".into())));
    }
    fn protocol_representation_result(&mut self,state:&mut ProtocolState,record:ProtocolRepresentation,value:Value)->PyResult<()> {
        let mut record=match record {
            ProtocolRepresentation::Wrapped{open,close,..}=>{let Value::Str(rendered)=self.native_payload(&value).unwrap_or(value)else{return Err(pyerr("TypeError","repr returned non-string"))};state.value=Some(Value::Str(format!("{open}{rendered}{close}").into()));return Ok(());}
            ProtocolRepresentation::Ascii=>{let value=self.native_payload(&value).unwrap_or(value);let Value::Str(value)=value else{return Err(pyerr("TypeError","repr returned non-string"))};state.value=Some(Value::Str(text_ascii_escape(&value).into()));return Ok(());}
            ProtocolRepresentation::Format(spec)=>{let specification=spec.map(|value|self.str_value(&value)).transpose()?.unwrap_or_default();state.value=Some(Value::Str(self.format_value(value,&specification)?.into()));return Ok(());}
            record=>record,
        };
        let ProtocolRepresentation::Container{guard,open,close,separator,text,count,tuple,mapping,phase,pending,..}=&mut record else{unreachable!()};
        match phase {
            ProtocolReprPhase::Next=>{
                if matches!(&value,Value::Builtin(name)if name=="$repr:end") {
                    if *tuple&&*count==1{text.push(',');}
                    let rendered=format!("{open}{text}{close}");
                    self.protocol_repr_active.remove(guard);state.repr_guards.retain(|owner|owner!=guard);
                    state.value=Some(Value::Str(rendered.into()));return Ok(());
                }
                if *count>0{text.push_str(separator);}*count+=1;
                let argument=if *mapping {
                    let Value::Obj(index)=value else{return Err(pyerr("RuntimeError","missing dictionary repr entry"))};let Object::Tuple(values)=self.object(index)? else{return Err(pyerr("RuntimeError","invalid dictionary repr entry"))};
                    *pending=values;*phase=ProtocolReprPhase::Key;pending[0].clone()
                }else{pending.push(value.clone());*phase=ProtocolReprPhase::Item;value};
                state.actions.push_front(ProtocolAction::Representation(Box::new(record)));
                state.plan=Some(ProtocolPlan{function:Value::Builtin("repr".into()),args:vec![argument],kwargs:Vec::new()});
            }
            ProtocolReprPhase::Item|ProtocolReprPhase::Value=>{
                let Value::Str(rendered)=self.native_payload(&value).unwrap_or(value)else{return Err(pyerr("TypeError","repr returned non-string"))};text.push_str(&rendered);pending.clear();*phase=ProtocolReprPhase::Next;
                self.protocol_repr_next(state,record);
            }
            ProtocolReprPhase::Key=>{
                let Value::Str(rendered)=self.native_payload(&value).unwrap_or(value)else{return Err(pyerr("TypeError","repr returned non-string"))};text.push_str(&rendered);text.push_str(": ");*phase=ProtocolReprPhase::Value;let argument=pending[1].clone();
                state.actions.push_front(ProtocolAction::Representation(Box::new(record)));
                state.plan=Some(ProtocolPlan{function:Value::Builtin("repr".into()),args:vec![argument],kwargs:Vec::new()});
            }
        }Ok(())
    }
    fn protocol_format_into(&mut self,state:&mut ProtocolState,value:Value,conversion:i32,spec:Option<Value>)->PyResult<()> {
        if let Some(name)=match conversion {114=>Some("repr"),97=>Some("ascii"),115=>Some("str"),_=>None}{state.actions.push_front(ProtocolAction::Representation(Box::new(ProtocolRepresentation::Format(spec))));state.plan=Some(ProtocolPlan{function:Value::Builtin(name.into()),args:vec![value],kwargs:Vec::new()});}
        else {
            let specification=match spec {Some(value)=>match self.native_payload(&value).unwrap_or(value){Value::Str(text)=>text.to_string(),_=>return Err(pyerr("TypeError","format specifier must be a string"))},None=>String::new()};
            if let Some((method,class))=self.protocol_slot(&value,"__format__"){self.protocol_bind(state,method,value,class,vec![Value::Str(specification.into())],Vec::new(),ProtocolAction::StringResult("__format__".into()),false)?;}
            else if specification.is_empty()&&matches!(self.operand_slot(&value,"__format__"),Some(SlotDefinition::Native(ref definition))if matches!(native_attribute_parts(definition),Some((_,"object","__format__")))) {state.plan=Some(ProtocolPlan{function:Value::Builtin("str".into()),args:vec![value],kwargs:Vec::new()});}
            else{state.value=Some(Value::Str(self.format_value(value,&specification)?.into()));}
        }
        Ok(())
    }
    fn start_protocol_format(&mut self,frame:&mut Frame,value:Value,conversion:i32,spec:Option<Value>)->PyResult<()> {
        let mut state=Self::protocol_empty(ProtocolSink::Stack);self.protocol_format_into(&mut state,value,conversion,spec)?;frame.protocol=Some(state);self.resume_protocol(frame)
    }
    fn start_protocol_for_iter(&mut self,frame:&mut Frame,iterator:Value,target:usize)->PyResult<bool> {
        let mut state=Self::protocol_empty(ProtocolSink::ForIter{target,finished:false});
        if !self.protocol_next_into(&mut state,iterator,None,true)?{return Ok(false);}
        frame.protocol=Some(state);self.resume_protocol(frame)?;Ok(true)
    }
}
