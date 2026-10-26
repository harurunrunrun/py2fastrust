// Native immutable payload construction for Python subclasses of tuple.
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
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        let root = self.roots.len();
        let mut protected = vec![class.clone()];
        protected.extend(args.iter().cloned());
        protected.extend(kwargs.iter().map(|(_, value)| value.clone()));
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
        kwargs: Vec<(String, Value)>,
        root: usize,
    ) -> PyResult<Value> {
        if type_name != "tuple" {
            return Err(pyerr(
                "NotImplementedError",
                format!("native payload for {} subclasses", type_name),
            ));
        }
        if !self.is_subclass(&class, &Value::Builtin("tuple".into()))? {
            return Err(pyerr("TypeError", "tuple.__new__ requires a tuple subtype"));
        }
        if args.len() > 1 || !kwargs.is_empty() {
            return Err(pyerr(
                "TypeError",
                "tuple.__new__ takes at most one iterable argument",
            ));
        }
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
                                "nonempty __slots__ not supported for subtype of 'tuple'",
                            ));
                        }
                    }
                }
            }
        }
        let values = if let Some(iterable) = args.first() {
            self.to_vec(iterable.clone())?
        } else {
            Vec::new()
        };
        let payload = self.obj_value(Object::Tuple(values));
        self.roots[root].push(payload.clone());
        let attrs = self.alloc(Object::Dict(Vec::new()));
        self.roots[root].push(Value::Obj(attrs));
        Ok(self.obj_value(Object::BuiltinInstance {
            class,
            attrs,
            payload,
        }))
    }
}
