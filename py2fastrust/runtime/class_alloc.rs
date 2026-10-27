// Allocation slots are distinct from the visible __new__ attribute. A raw
// built-in tp_new wrapper preserves the previously inherited allocation slot.
#[derive(Clone,Debug)]
enum ClassAllocator { Native(Value), Dynamic, Missing }
// The slot namespace is private. Physical member descriptors use increasing
// IDs below this reserved sentinel; the owner already traces and clears it.
const HIDDEN_ALLOCATOR_SLOT:usize=usize::MAX;

impl Runtime {
    fn class_hidden_payload(&self,value:&Value)->Option<(Value,Value)> {
        let Value::Obj(owner)=value else{return None};
        if let Some(Object::BuiltinInstance{payload,..})=self.heap.get(*owner).and_then(Option::as_ref){return Some((self.native_receiver_class(payload),payload.clone()));}
        let Value::Obj(record)=self.instance_slots.get(owner)?.get(&HIDDEN_ALLOCATOR_SLOT)?else{return None};
        let Some(Object::Tuple(values))=self.heap.get(*record).and_then(Option::as_ref)else{return None};
        if values.len()==2{Some((values[0].clone(),values[1].clone()))}else{None}
    }
    fn class_hidden_text_payload(&self,value:&Value)->Option<Value> {
        if self.native_payload(value).is_some(){return None;}
        let (_,payload)=self.class_hidden_payload(value)?;
        let kind=if matches!(payload,Value::Str(_)){"str"}else if matches!(payload,Value::Bytes(_)){"bytes"}else{return None};
        self.native_capability_payload(value,kind).map(|_|payload)
    }
    fn class_static_base(&self,class:&Value)->Value {
        let mut value=class.clone();
        while let Value::Obj(owner)=&value {
            let Ok(class)=self.mro_class(*owner)else{break};value=class.layout_base;
        }
        if matches!(&value,Value::Builtin(name)if native_attribute_kind(name,"__new__").is_none()&&!stdlib_type_name(name)) {
            Value::Builtin("object".into())
        }else{value}
    }
    fn class_inherit_allocator(&self,base:&Value)->ClassAllocator {
        if let Value::Obj(owner)=base {if let Ok(class)=self.mro_class(*owner){return class.allocator;}}
        ClassAllocator::Native(self.class_static_base(base))
    }
    fn class_uses_object_allocator(&self,class:&Value)->bool {
        matches!(self.class_inherit_allocator(class),ClassAllocator::Native(base)if Self::same_type(&base,&Value::Builtin("object".into())))
    }
    fn class_refresh_allocator(&mut self,owner:usize) {
        let found=self.class_attribute_lookup(&Value::Obj(owner),"__new__");
        let preserve=found.as_ref().is_some_and(|value|{
            matches!(native_attribute_parts(value),Some(("new",_,"__new__")))||matches!(value,Value::Builtin(name)if name.starts_with("exception_type:")&&name.ends_with(":__new__"))
        });
        if !preserve {
            if let Some(Object::Class(class))=self.heap[owner].as_mut(){class.allocator=if found.is_some(){ClassAllocator::Dynamic}else{ClassAllocator::Missing};}
        }
    }
    fn class_update_allocators(&mut self,owner:usize)->PyResult<()> {
        let mut pending=vec![owner];let mut seen=std::collections::HashSet::new();
        while let Some(current)=pending.pop(){
            if !seen.insert(current){continue;}
            let next=self.mro_class(current)?.allocator_epoch.checked_add(1).ok_or_else(||pyerr("OverflowError","allocation slot revision exhausted"))?;
            if let Some(Object::Class(class))=self.heap[current].as_mut(){class.allocator_epoch=next;}
            self.class_refresh_allocator(current);pending.extend(self.mro_children(&Value::Obj(current)));
        }Ok(())
    }
    fn class_hide_allocation(&mut self,value:Value,base:Value)->PyResult<Value> {
        let Value::Obj(owner)=value.clone()else{return Ok(value)};
        let Some(Object::BuiltinInstance{class,attrs,payload})=self.heap.get(owner).and_then(Option::as_ref).cloned()else{return Ok(value)};
        if self.mro_cached_subtype(&class,&base){return Ok(value);}
        self.view_rooted(vec![value.clone(),base.clone(),payload.clone()],|runtime,_|{
            let keeper=runtime.obj_value(Object::Tuple(vec![base,payload]));
            runtime.instance_slots.entry(owner).or_default().insert(HIDDEN_ALLOCATOR_SLOT,keeper);
            runtime.heap[owner]=Some(Object::Instance{class,attrs});Ok(value)
        })
    }
    fn class_native_allocate(&mut self,base:Value,class:Value,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<Value> {
        let mut roots=vec![base.clone(),class.clone()];roots.extend(args.iter().cloned());roots.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        self.view_rooted(roots,|runtime,root|{
            match &base {
                Value::Builtin(name) if name=="object"=>runtime.native_attribute_call(Value::Builtin("native_attr:new:object:__new__".into()),std::iter::once(class).chain(args).collect(),kwargs),
                Value::Builtin(name) if name=="type"=>runtime.construct_class(class,args,kwargs),
                Value::Builtin(name) if stdlib_type_name(name)=>{
                    if !runtime.mro_cached_subtype(&class,&base) {
                        // Module-state allocators require their defining base
                        // in the MRO. Older CPython itertools allocators can
                        // dereference a missing module state; reject safely.
                        if name=="functools.partial"||["itertools.accumulate","itertools.chain","itertools.cycle","itertools.dropwhile","itertools.filterfalse","itertools.groupby","itertools.islice","itertools.pairwise","itertools.starmap","itertools.takewhile"].contains(&name.as_str()) {
                            return Err(pyerr("TypeError","native allocator requires its defining base in the MRO"));
                        }
                    }
                    let result=runtime.stdlib_instance_new(name,class,args,kwargs)?;runtime.class_hide_allocation(result,base)
                },
                Value::Builtin(name)=>{
                    let result=runtime.builtin_instance_construct(name,class,args,kwargs,root,true)?;
                    runtime.class_hide_allocation(result,base)
                },
                Value::Type(name)=>{
                    let mut error=runtime.new_exception(name,args)?;let payload=runtime.exception_value(&mut error);runtime.roots[root].push(payload.clone());
                    let attrs=runtime.alloc(Object::Dict(Vec::new()));runtime.roots[root].push(Value::Obj(attrs));
                    let result=runtime.obj_value(Object::BuiltinInstance{class,attrs,payload});runtime.class_hide_allocation(result,base)
                },
                _=>Err(pyerr("TypeError","invalid native allocation slot")),
            }
        })
    }
}
