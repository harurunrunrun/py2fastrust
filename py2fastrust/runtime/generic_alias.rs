// Runtime parameterized built-in types (types.GenericAlias).  Type arguments
// remain ordinary Python values; creating an alias never erases them.
thread_local! {
    static GENERIC_REPR_ACTIVE: std::cell::RefCell<Vec<(Value, Vec<Value>)>> = std::cell::RefCell::new(Vec::new());
}
struct GenericReprGuard;
impl GenericReprGuard {
    fn enter(origin: &Value, args: &[Value]) -> PyResult<Self> {
        GENERIC_REPR_ACTIVE.with(|active| {
            let mut active = active.borrow_mut();
            if active.iter().any(|(base, parameters)| {
                base.same_identity(origin)
                    && parameters.len() == args.len()
                    && parameters
                        .iter()
                        .zip(args)
                        .all(|(left, right)| left.same_identity(right))
            }) {
                Err(pyerr(
                    "RecursionError",
                    "maximum recursion depth exceeded while getting the repr of an object",
                ))
            } else {
                active.push((origin.clone(), args.to_vec()));
                Ok(Self)
            }
        })
    }
}
impl Drop for GenericReprGuard {
    fn drop(&mut self) {
        GENERIC_REPR_ACTIVE.with(|active| {
            active.borrow_mut().pop();
        });
    }
}
impl Runtime {
    fn generic_alias(&mut self, origin: Value, key: Value) -> PyResult<Value> {
        let payload = self.native_payload(&key).unwrap_or_else(|| key.clone());
        let (args, supplied_tuple) = match &payload {
            Value::Obj(index) => match self.object(*index)? {
                Object::Tuple(values) => (
                    values,
                    if let Value::Obj(original) = &key {
                        Some(*original)
                    } else {
                        None
                    },
                ),
                _ => (vec![key.clone()], None),
            },
            _ => (vec![key.clone()], None),
        };
        let root = self.roots.len();
        let mut roots = vec![origin.clone(), key];
        roots.extend(args.iter().cloned());
        self.roots.push(roots);
        let args_tuple = supplied_tuple.unwrap_or_else(|| self.alloc(Object::Tuple(args.clone())));
        self.roots[root].push(Value::Obj(args_tuple));
        let parameters = self.alloc(Object::Tuple(Vec::new()));
        self.roots[root].push(Value::Obj(parameters));
        let result = self.obj_value(Object::GenericAlias {
            origin,
            args,
            args_tuple,
            parameters,
        });
        self.roots.truncate(root);
        Ok(result)
    }

    fn generic_parts(&self, value: &Value) -> Option<(Value, Vec<Value>, usize, usize)> {
        if let Value::Obj(index) = value {
            if let Some(Object::GenericAlias {
                origin,
                args,
                args_tuple,
                parameters,
            }) = self.heap.get(*index).and_then(Option::as_ref)
            {
                return Some((origin.clone(), args.clone(), *args_tuple, *parameters));
            }
        }
        None
    }

    fn generic_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        let (origin, _, args_tuple, parameters) = self.generic_parts(&value)?;
        match name {
            // The VM provides the type object, rather than the origin's type.
            "__class__" => None,
            "__origin__" => Some(Ok(origin)),
            "__args__" => Some(Ok(Value::Obj(args_tuple))),
            "__parameters__" => Some(Ok(Value::Obj(parameters))),
            "__unpacked__" => Some(Ok(Value::Bool(false))),
            "__bases__" | "__copy__" | "__deepcopy__" => Some(Err(pyerr(
                "AttributeError",
                format!("'types.GenericAlias' object has no attribute '{}'", name),
            ))),
            "__typing_unpacked_tuple_args__" => Some(Ok(Value::None)),
            "__mro_entries__" => Some(Ok(self.obj_value(Object::Bound(
                Value::Builtin(format!("method:{}", name)),
                value,
            )))),
            _ => Some(self.getattr(origin, name)),
        }
    }

    fn generic_method(
        &mut self,
        value: Value,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> Option<PyResult<Value>> {
        let (origin, parameters, _, _) = self.generic_parts(&value)?;
        if ![
            "__mro_entries__",
            "__repr__",
            "__str__",
            "__hash__",
            "__eq__",
            "__ne__",
            "__getitem__",
            "__call__",
        ]
        .contains(&name)
        {
            return None;
        }
        Some((|| {
            if name == "__call__" {
                let result = self.call(origin, args, kwargs, None)?;
                match self.setattr(result.clone(), "__orig_class__", value) {
                    Ok(()) => {}
                    Err(error) if error.kind == "AttributeError" || error.kind == "TypeError" => {}
                    Err(error) => return Err(error),
                }
                return Ok(result);
            }
            if !kwargs.is_empty() {
                return Err(pyerr(
                    "TypeError",
                    format!("GenericAlias.{}() takes no keyword arguments", name),
                ));
            }
            let expected = if ["__mro_entries__", "__eq__", "__ne__", "__getitem__"].contains(&name)
            {
                1
            } else {
                0
            };
            if args.len() != expected {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "GenericAlias.{}() takes exactly {} argument{} ({} given)",
                        name,
                        expected,
                        if expected == 1 { "" } else { "s" },
                        args.len()
                    ),
                ));
            }
            match name {
                "__mro_entries__" => Ok(self.obj_value(Object::Tuple(vec![origin]))),
                "__repr__" | "__str__" => {
                    Ok(Value::Str(self.generic_repr(&origin, &parameters)?.into()))
                }
                "__hash__" => self.generic_hash(&origin, &parameters),
                "__eq__" | "__ne__" => {
                    if self.generic_parts(&args[0]).is_none() {
                        return Ok(Value::Builtin("NotImplemented".into()));
                    }
                    self.generic_compare_value(
                        if name == "__eq__" { "==" } else { "!=" },
                        &value,
                        &args[0],
                    )
                    .unwrap()
                }
                "__getitem__" => Err(pyerr(
                    "TypeError",
                    format!(
                        "{} is not a generic class",
                        self.generic_repr(&origin, &parameters)?
                    ),
                )),
                _ => unreachable!(),
            }
        })())
    }

    fn generic_repr_item(&mut self, value: &Value) -> PyResult<String> {
        if matches!(value, Value::None)
            || matches!(value, Value::Builtin(name) | Value::Type(name) if name == "NoneType")
        {
            return Ok("None".into());
        }
        if matches!(value, Value::Builtin(name) if name == "Ellipsis") {
            return Ok("...".into());
        }
        if let Some((origin, args, _, _)) = self.generic_parts(value) {
            return self.generic_repr(&origin, &args);
        }
        if let Value::Builtin(name) | Value::Type(name) = value {
            // Type names already carry their public module where necessary.
            if self.typename(value) == "type"
                || (matches!(value, Value::Builtin(_)) && !name.contains(':'))
            {
                return Ok(name.clone());
            }
        }
        // Python uses a qualified name for class/function arguments, including
        // __main__; arbitrary values still use their ordinary repr.
        let is_named = matches!(value, Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Class(_) | Object::Function(_))));
        if is_named {
            let name = self.getattr(value.clone(), "__qualname__")?;
            let module = self.getattr(value.clone(), "__module__")?;
            if let (Value::Str(name), Value::Str(module)) = (name, module) {
                return Ok(if module == "builtins" {
                    name.to_string()
                } else {
                    format!("{}.{}", module, name)
                });
            }
        }
        self.repr(value)
    }

    fn generic_repr(&mut self, origin: &Value, args: &[Value]) -> PyResult<String> {
        let _guard = GenericReprGuard::enter(origin, args)?;
        let root = self.roots.len();
        let mut roots = vec![origin.clone()];
        roots.extend(args.iter().cloned());
        self.roots.push(roots);
        let result = (|| {
            let base = self.generic_repr_item(origin)?;
            let mut parts = Vec::new();
            for arg in args {
                if let Value::Obj(index) = arg {
                    if let Object::List(items) = self.object(*index)? {
                        let mut list_parts = Vec::new();
                        for item in &items {
                            list_parts.push(self.generic_repr_item(item)?);
                        }
                        parts.push(format!("[{}]", list_parts.join(", ")));
                        continue;
                    }
                }
                parts.push(self.generic_repr_item(arg)?);
            }
            Ok(format!(
                "{}[{}]",
                base,
                if parts.is_empty() {
                    "()".into()
                } else {
                    parts.join(", ")
                }
            ))
        })();
        self.roots.truncate(root);
        result
    }

    fn generic_equal(&mut self, a: &Value, b: &Value) -> Option<PyResult<bool>> {
        if let Some(result) = self.generic_compare_value("==", a, b) {
            return Some(result.and_then(|value| self.truth(&value)));
        }
        if self.generic_parts(a).is_some() || self.generic_parts(b).is_some() {
            return Some(Ok(false));
        }
        None
    }

    fn generic_compare_value(&mut self, op: &str, a: &Value, b: &Value) -> Option<PyResult<Value>> {
        if op != "==" && op != "!=" {
            return None;
        }
        let left = self.generic_parts(a);
        let right = self.generic_parts(b);
        // Leave unrelated objects to reflected rich comparison / NotImplemented.
        let (Some((left, _, left_args, _)), Some((right, _, right_args, _))) = (left, right) else {
            return None;
        };
        let root = self.roots.len();
        self.roots.push(vec![a.clone(), b.clone()]);
        let result = (|| {
            if !self.identical_or_equal(&left, &right)? {
                return Ok(Value::Bool(op == "!="));
            }
            let equal =
                self.compare_value("==", &Value::Obj(left_args), &Value::Obj(right_args))?;
            if op == "==" {
                Ok(equal)
            } else {
                // CPython's GenericAlias != checks the equality result
                // against the True singleton rather than calling bool().
                Ok(Value::Bool(!matches!(equal, Value::Bool(true))))
            }
        })();
        self.roots.truncate(root);
        Some(result)
    }

    fn generic_value_hash(&mut self, value: &Value) -> PyResult<Value> {
        let (origin, _, args_tuple, _) = self
            .generic_parts(value)
            .ok_or_else(|| pyerr("TypeError", "expected a GenericAlias"))?;
        let root = self.roots.len();
        self.roots.push(vec![value.clone()]);
        let result = (|| {
            let origin_hash = self.generic_component_hash(&origin)?;
            let args_hash = self.generic_component_hash(&Value::Obj(args_tuple))?;
            let hash = (origin_hash ^ args_hash) as i64;
            Ok(Value::Int(
                Int::from_i128(if hash == -1 { -2 } else { hash as i128 }).into(),
            ))
        })();
        self.roots.truncate(root);
        result
    }

    fn generic_hash(&mut self, origin: &Value, args: &[Value]) -> PyResult<Value> {
        // Use the same recursive component hashes for all aliases.  In
        // particular, unhashable arguments must still raise TypeError even
        // though alias creation and equality accept them.
        let origin_hash = self.generic_component_hash(origin)?;
        let mut hash = 0x345678u64;
        for arg in args {
            let bits = self.generic_component_hash(arg)?;
            hash = (hash ^ bits).wrapping_mul(1_000_003);
        }
        hash ^= args.len() as u64;
        hash ^= origin_hash;
        let hash = hash as i64;
        Ok(Value::Int(
            Int::from_i128(if hash == -1 { -2 } else { hash as i128 }).into(),
        ))
    }

    fn generic_component_hash(&mut self, value: &Value) -> PyResult<u64> {
        // GenericAlias accepts arbitrary objects as arguments.  Tuple members
        // must be recursively hashable, and equal integral floats/ints must
        // produce equal hashes just as they do in ordinary Python containers.
        if let Value::Obj(index) = value {
            if let Object::Tuple(items) = self.object(*index)? {
                let mut hash = 0x345678u64;
                for item in &items {
                    hash = (hash ^ self.generic_component_hash(item)?).wrapping_mul(1_000_003);
                }
                return Ok(hash ^ items.len() as u64);
            }
        }
        let normalized = match value {
            Value::Float(number) if number.is_finite() && number.fract() == 0.0 => {
                Int::from_f64(**number)
                    .ok()
                    .map(|number| Value::Int(number.into()))
            }
            _ => None,
        };
        let item = self.builtin(
            "hash",
            vec![normalized.unwrap_or_else(|| value.clone())],
            Vec::new(),
            None,
        )?;
        Ok(self.as_int(&item)?.to_i128().unwrap_or(0) as u64)
    }
}
