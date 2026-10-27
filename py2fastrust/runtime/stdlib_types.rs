// Public constructor classes retain the existing lazy iterator/callable payloads.
// These contracts are implemented from Python 3.14 documentation and behavioral
// probes; no CPython source algorithms are translated here.
fn stdlib_type_name(name: &str) -> bool {
    if name == "functools.partial" { return true; }
    name.strip_prefix("itertools.").is_some_and(|name| matches!(name,
        "accumulate" | "batched" | "chain" | "combinations" |
        "combinations_with_replacement" | "compress" | "count" | "cycle" |
        "dropwhile" | "filterfalse" | "groupby" | "islice" | "pairwise" |
        "permutations" | "product" | "repeat" | "starmap" | "takewhile" |
        "zip_longest" | "_tee" | "_grouper"))
}
fn stdlib_attribute_kind(owner: &str, name: &str) -> Option<&'static str> {
    if !stdlib_type_name(owner) { return None; }
    match name {
        "__new__" => Some("new"),
        "__class_getitem__" if matches!(owner,"itertools.chain" | "functools.partial") => Some("class"),
        "from_iterable" if owner == "itertools.chain" => Some("class"),
        "__call__" | "__get__" if owner == "functools.partial" => Some("wrapper"),
        "func" | "args" | "keywords" if owner == "functools.partial" => Some("member"),
        "__iter__" | "__next__" if owner.starts_with("itertools.") => Some("wrapper"),
        _ => None,
    }
}
impl Runtime {
    fn stdlib_instance_class(&self, value: &Value) -> Option<Value> {
        let Value::Obj(index) = value else { return None; };
        match self.heap.get(*index).and_then(Option::as_ref)? {
            Object::Partial { .. } => Some(Value::Builtin("functools.partial".into())),
            Object::Iterator(IteratorState::Tools(state)) => Some(Value::Builtin(format!("itertools.{}",state.type_name()))),
            _ => None,
        }
    }
    fn stdlib_type_attribute(&mut self, value: &Value, name: &str) -> Option<PyResult<Value>> {
        let Value::Builtin(owner) = value else { return None; };
        if !stdlib_type_name(owner) { return None; }
        Some((|| match name {
            "__class__" => Ok(Value::Builtin("type".into())),
            "__name__" | "__qualname__" => Ok(Value::Str(owner.rsplit('.').next().unwrap().into())),
            "__module__" => Ok(Value::Str(owner.split('.').next().unwrap().into())),
            "__base__" => Ok(Value::Builtin("object".into())),
            "__bases__" => Ok(self.obj_value(Object::Tuple(vec![Value::Builtin("object".into())]))),
            "__mro__" => Ok(self.obj_value(Object::Tuple(vec![value.clone(),Value::Builtin("object".into())]))),
            "__dict__" => {
                let mut entries=Vec::new();
                for name in ["__new__","__iter__","__next__","__call__","__get__","__class_getitem__","from_iterable","func","args","keywords"] {
                    if let Some(member)=self.native_own_attribute(value,name) {entries.push((Value::Str(name.into()),member));}
                }
                let owner=self.alloc(Object::Dict(entries));
                Ok(self.obj_value(Object::MappingProxy { owner }))
            },
            _ => match self.class_attribute_lookup(value,name) {
                Some(member) => self.bind_descriptor(member,None,value.clone()),
                None => Err(pyerr("AttributeError",format!("type '{}' has no attribute '{}'",owner,name))),
            },
        })())
    }
    fn stdlib_wrap_instance(&mut self, class: Value, payload: Value) -> PyResult<Value> {
        if self.stdlib_instance_class(&payload).is_some_and(|base| Self::same_type(&class,&base)) {return Ok(payload);}
        let attrs=match &payload {Value::Obj(index)=>match self.heap.get(*index).and_then(Option::as_ref) {Some(Object::Partial{attrs,..})=>*attrs,_=>self.alloc(Object::Dict(Vec::new()))},_=>unreachable!()};
        Ok(self.obj_value(Object::BuiltinInstance {class,attrs,payload}))
    }
    fn stdlib_instance_new(&mut self, owner: &str, class: Value, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        self.view_rooted(vec![class.clone()],|runtime,_| {
            let (module,name)=owner.split_once('.').unwrap();
            let payload=runtime.module_call(&format!("module:{module}:{name}"),args,kwargs)?;
            runtime.stdlib_wrap_instance(class,payload)
        })
    }
    fn stdlib_member(&self, owner: &str, receiver: &Value, name: &str) -> Option<PyResult<Value>> {
        if owner != "functools.partial" {return None;}
        let payload=self.native_payload(receiver).unwrap_or_else(||receiver.clone());
        let Value::Obj(index)=payload else{return None;};
        let Some(Object::Partial{function,args_tuple,keywords,..})=self.heap.get(index).and_then(Option::as_ref) else{return None;};
        Some(match name {"func"=>Ok(function.clone()),"args"=>Ok(Value::Obj(*args_tuple)),"keywords"=>Ok(Value::Obj(*keywords)),_=>return None})
    }
    fn stdlib_method(&mut self, owner: &str, name: &str, receiver: Value, rest: Vec<Value>, kwargs: KeywordArgs) -> Option<PyResult<Value>> {
        if !stdlib_type_name(owner) {return None;}
        Some((|| {
            let payload=self.native_payload(&receiver).unwrap_or_else(||receiver.clone());
            match name {
                "__iter__" | "__next__" => {
                    if !rest.is_empty() || !kwargs.is_empty() {return Err(pyerr("TypeError","iterator descriptor takes no arguments"));}
                    if name=="__iter__" {Ok(receiver)}else{self.iterator_next(payload)}
                },
                "__call__" if owner=="functools.partial" => self.call(payload,rest,kwargs,None),
                "__get__" if owner=="functools.partial" => {
                    if !(1..=2).contains(&rest.len()) || !kwargs.is_empty() {return Err(pyerr("TypeError","__get__ takes one or two arguments"));}
                    Ok(if matches!(rest[0],Value::None) {receiver}else{self.obj_value(Object::Bound(receiver,rest[0].clone()))})
                },
                _=>Err(pyerr("NotImplementedError",format!("native descriptor {owner}.{name}"))),
            }
        })())
    }
    fn stdlib_partial_payload(&self,value:&Value)->Option<Value> {
        let payload=self.native_payload(value).unwrap_or_else(||value.clone());
        if matches!(&payload,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Partial{..}))) {Some(payload)}else{None}
    }
    fn stdlib_callable(&self,value:&Value)->bool {
        match value {
            Value::Builtin(name)=>!["Ellipsis","NotImplemented","functools.Placeholder","typing.NoDefault"].contains(&name.as_str()),
            Value::Type(_)=>true,
            Value::Obj(index)=>matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Function(_)|Object::Bound(..)|Object::Class(_)|Object::Cached(_)|Object::Partial{..}|Object::GenericAlias{..}|Object::TypeEvaluator(_))) || self.object_class(value).is_some_and(|class|self.slot_definition(&class,"__call__",0).is_some()),
            _=>false,
        }
    }
    fn tools_is_number(&self,value:&Value)->bool {
        let payload=self.native_payload(value).unwrap_or_else(||value.clone());
        matches!(payload,Value::Int(_)|Value::Float(_)|Value::Complex(_)|Value::Bool(_)) ||
            self.object_class(value).is_some_and(|class| ["__int__","__index__","__float__"].iter().any(|name|self.slot_definition(&class,name,0).is_some()))
    }
}
