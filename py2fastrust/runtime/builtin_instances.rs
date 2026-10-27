// Native payload construction for Python subclasses of supported built-in types.
impl Runtime {
    fn builtin_instance_allows_dict(&self, class: &Value) -> bool {
        for base in self
            .class_mro(class, 0)
            .unwrap_or_else(|| vec![class.clone()])
        {
            if let Value::Obj(index) = base {
                if let Some(Object::Class(definition)) =
                    self.heap.get(index).and_then(Option::as_ref)
                {
                    if self.ns_get(definition.attrs, "__slots__").is_none() {
                        return true;
                    }
                }
            }
        }
        false
    }

    fn builtin_instance_new(
        &mut self,
        type_name: &str,
        class: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        let root = self.roots.len();
        let mut protected = vec![class.clone()];
        protected.extend(args.iter().cloned());
        protected.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        self.roots.push(protected);
        let result = self.builtin_instance_construct(type_name, class, args, kwargs, root);
        self.roots.truncate(root);
        result
    }

    fn builtin_instance_construct(
        &mut self,
        type_name: &str,
        class: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
        root: usize,
    ) -> PyResult<Value> {
        if !["tuple", "list", "dict", "set", "str", "int", "float", "bytes", "complex", "frozenset"].contains(&type_name) {
            return Err(pyerr(
                "NotImplementedError",
                format!("native payload for {} subclasses", type_name),
            ));
        }
        if !self.is_subclass(&class, &Value::Builtin(type_name.into()))? {
            return Err(pyerr(
                "TypeError",
                format!("{}.__new__ requires a {} subtype", type_name, type_name),
            ));
        }
        if type_name == "tuple" && (args.len() > 1 || !kwargs.is_empty()) {
            return Err(pyerr(
                "TypeError",
                "tuple.__new__ takes at most one iterable argument",
            ));
        }
        if type_name == "tuple" || type_name == "int" || type_name == "bytes" {
            for base in self
                .class_mro(&class, 0)
                .unwrap_or_else(|| vec![class.clone()])
            {
                if let Value::Obj(index) = base {
                    if let Some(Object::Class(definition)) =
                        self.heap.get(index).and_then(Option::as_ref)
                    {
                        if let Some(slots) = self.ns_get(definition.attrs, "__slots__") {
                            let empty = match slots {
                                Value::Obj(index) => {
                                    matches!(self.heap.get(index).and_then(Option::as_ref), Some(Object::Tuple(values) | Object::List(values)) if values.is_empty())
                                }
                                _ => false,
                            };
                            if !empty {
                                return Err(pyerr(
                                    "TypeError",
                                    format!(
                                        "nonempty __slots__ not supported for subtype of '{}'",
                                        type_name
                                    ),
                                ));
                            }
                        }
                    }
                }
            }
        };
        let payload = match type_name {
            "frozenset"=>{if Self::same_type(&class,&Value::Builtin("frozenset".into())){self.frozen_constructor(args,kwargs)?}else{if args.len()>1||(!kwargs.is_empty()&&self.slot_override(&class,"__init__",0).is_none()){return Err(pyerr("TypeError","frozenset expected one positional argument"));}let entries=if let Some(source)=args.first(){self.frozen_collect(source.clone())?}else{Vec::new()};self.frozen_make(entries,true)}},
            "complex"=>self.complex_constructor(args,kwargs)?,
            "float"=>{
                let custom_init=self.slot_override(&class,"__init__",0).is_some_and(|value|!matches!(native_attribute_parts(&value),Some((_,"object","__init__"))));
                self.builtin("float",args,if custom_init{Vec::new()}else{kwargs},None)?
            },
            "bytes"=>self.bytes_constructor(args,kwargs)?,
            "list" => self.obj_value(Object::List(Vec::new())),
            "dict" => self.obj_value(Object::Dict(Vec::new())),
            "set" => self.obj_value(Object::Set(Vec::new())),
            "tuple" => {
                if Self::same_type(&class, &Value::Builtin("tuple".into())) {
                    if let Some(Value::Obj(index)) = args.first() {
                        if matches!(self.object(*index)?, Object::Tuple(_)) {
                            return Ok(args[0].clone());
                        }
                    }
                }
                let values = if let Some(iterable) = args.first() {
                    self.builtin_collect(iterable.clone(), root)?
                } else {
                    Vec::new()
                };
                self.obj_value(Object::Tuple(values))
            }
            "int" => {
                if args.len() > 2 || kwargs.iter().any(|(name, _)| name != "base") {
                    return Err(pyerr("TypeError", "invalid arguments to int.__new__"));
                }
                let mut converted = args;
                if let Some((_, base)) = kwargs.first() {
                    if converted.is_empty() || converted.len() > 1 {
                        return Err(pyerr("TypeError", "invalid base argument to int.__new__"));
                    }
                    converted.push(base.clone());
                }
                if converted.len() == 2 {
                    if !matches!(converted[0], Value::Str(_) | Value::Bytes(_)) {
                        return Err(pyerr(
                            "TypeError",
                            "int() can't convert non-string with explicit base",
                        ));
                    }
                    let base = self.as_int(&converted[1])?.to_i128().unwrap_or(-1);
                    if base != 0 && !(2..=36).contains(&base) {
                        return Err(pyerr(
                            "ValueError",
                            "int() base must be >= 2 and <= 36, or 0",
                        ));
                    }
                    if let Value::Bytes(bytes) = &converted[0] {
                        converted[0] = Value::Str(
                            String::from_utf8(bytes.to_vec())
                                .map_err(|_| pyerr("ValueError", "invalid literal for int"))?.into(),
                        );
                    }
                }
                self.builtin("int", converted, Vec::new(), None)?
            }
            "str" => {
                if args.len() > 3
                    || kwargs
                        .iter()
                        .any(|(name, _)| !["object", "encoding", "errors"].contains(&name.as_str()))
                {
                    return Err(pyerr("TypeError", "invalid arguments to str.__new__"));
                }
                if args.len() > 1 || kwargs.iter().any(|(name, _)| name != "object") {
                    return Err(pyerr(
                        "NotImplementedError",
                        "str subclass construction with an encoding is not implemented",
                    ));
                }
                let mut converted = args;
                if let Some((_, object)) = kwargs.first() {
                    if !converted.is_empty() {
                        return Err(pyerr(
                            "TypeError",
                            "argument for str() given by name and position",
                        ));
                    }
                    converted.push(object.clone());
                }
                self.builtin("str", converted, Vec::new(), None)?
            }
            _ => unreachable!(),
        };
        self.roots[root].push(payload.clone());
        if Self::same_type(&class, &Value::Builtin(type_name.into())) {
            return Ok(payload);
        }
        let payload=self.native_payload(&payload).unwrap_or(payload);
        let attrs = self.alloc(Object::Dict(Vec::new()));
        self.roots[root].push(Value::Obj(attrs));
        Ok(self.obj_value(Object::BuiltinInstance {
            class,
            attrs,
            payload,
        }))
    }

    fn builtin_collect(&mut self, iterable: Value, root: usize) -> PyResult<Vec<Value>> {
        let iterator = self.iter(iterable)?;
        self.roots[root].push(iterator.clone());
        let mut values = Vec::new();
        while let Some(value) = self.next(iterator.clone())? {
            self.roots[root].push(value.clone());
            values.push(value);
        }
        Ok(values)
    }

    fn builtin_instance_init(
        &mut self,
        type_name: &str,
        receiver: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        let root = self.roots.len();
        let mut protected = vec![receiver.clone()];
        protected.extend(args.iter().cloned());
        protected.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        self.roots.push(protected);
        let result = self.builtin_instance_initialize(type_name, receiver, args, kwargs, root);
        self.roots.truncate(root);
        result
    }

    fn builtin_instance_initialize(
        &mut self,
        type_name: &str,
        receiver: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
        root: usize,
    ) -> PyResult<Value> {
        let payload = self.native_payload(&receiver).unwrap_or(receiver);
        let index = match &payload {
            Value::Obj(index) => *index,
            _ => {
                return Err(pyerr(
                    "TypeError",
                    "invalid built-in initialization receiver",
                ))
            }
        };
        let valid = match (type_name, self.object(index)?) {
            ("list", Object::List(_)) | ("dict", Object::Dict(_)) | ("set", Object::Set(_)) => true,
            _ => false,
        };
        if !valid {
            return Err(pyerr(
                "TypeError",
                format!("descriptor requires a '{}' object", type_name),
            ));
        }
        if args.len() > 1 || (type_name != "dict" && !kwargs.is_empty()) {
            return Err(pyerr(
                "TypeError",
                format!("invalid arguments to {}.__init__", type_name),
            ));
        }
        if type_name != "dict" {
            self.heap[index] = Some(if type_name == "list" {
                Object::List(Vec::new())
            } else {
                Object::Set(Vec::new())
            });
            if type_name=="set"{self.assoc_cleared(index);}
        }
        if let Some(source) = args.first() {
            if type_name == "dict" {
                self.dictionary_update_value(index,source.clone())?;
            } else if type_name=="set"{
                self.live_set_update(index,"update",vec![source.clone()],Vec::new())?;
            } else {
                let iterator = self.iter(source.clone())?;
                self.roots[root].push(iterator.clone());
                while let Some(value) = self.next(iterator.clone())? {
                    self.container_add(payload.clone(), value, false)?;
                }
            }
        }
        for (key, value) in kwargs {
            let hash=if let Some(hash)=key.hash{hash}else{self.frozen_member_hash(&key.original)?};
            self.dictionary_set_known(index,key.original,value,hash)?;
        }
        Ok(Value::None)
    }
}
