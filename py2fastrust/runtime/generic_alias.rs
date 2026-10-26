// Runtime parameterized built-in types (types.GenericAlias).  Type arguments
// remain ordinary Python values; creating an alias never erases them.
// Parameter collection/substitution control flow is adapted from CPython 3.14:
// Objects/genericaliasobject.c (_Py_make_parameters, _Py_subs_parameters,
// subs_tvars), Lib/typing.py (_paramspec_prepare_subst,
// _typevartuple_prepare_subst, _unpack_args), and Objects/typevarobject.c
// (typevar_typing_prepare_subst). These adaptations use the PSF license in
// stdlib/PYTHON_LICENSE.txt, also included in generated Rust submissions.
thread_local! {
    static GENERIC_REPR_ACTIVE: std::cell::RefCell<Vec<(Value, Vec<Value>)>> = std::cell::RefCell::new(Vec::new());
    static GENERIC_PARAMETERS_ACTIVE: std::cell::RefCell<Vec<Vec<Value>>> = std::cell::RefCell::new(Vec::new());
}
struct GenericParameterGuard;
impl GenericParameterGuard {
    fn enter(args: &[Value]) -> PyResult<Self> {
        GENERIC_PARAMETERS_ACTIVE.with(|active| {
            let mut active = active.borrow_mut();
            if active.iter().any(|old| {
                old.len() == args.len()
                    && old
                        .iter()
                        .zip(args)
                        .all(|(left, right)| left.same_identity(right))
            }) {
                return Err(pyerr(
                    "RecursionError",
                    "maximum recursion depth exceeded in __parameter__ calculation",
                ));
            }
            active.push(args.to_vec());
            Ok(Self)
        })
    }
}
impl Drop for GenericParameterGuard {
    fn drop(&mut self) {
        GENERIC_PARAMETERS_ACTIVE.with(|active| {
            active.borrow_mut().pop();
        });
    }
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
    fn generic_optional_attr(&mut self, value: Value, name: &str) -> PyResult<Option<Value>> {
        match self.getattr(value, name) {
            Ok(value) => Ok(Some(value)),
            Err(error) if error.kind == "AttributeError" => Ok(None),
            Err(error) => Err(error),
        }
    }

    // The boolean distinguishes a tuple from a list, including their subclasses.
    fn generic_sequence(&self, value: &Value) -> Option<(bool, Vec<Value>)> {
        let value = self.native_payload(value).unwrap_or_else(|| value.clone());
        if let Value::Obj(index) = value {
            match self.heap.get(index).and_then(Option::as_ref) {
                Some(Object::Tuple(items)) => return Some((true, items.clone())),
                Some(Object::List(items)) => return Some((false, items.clone())),
                _ => {}
            }
        }
        None
    }

    fn generic_is_class(&self, value: &Value) -> bool {
        matches!(value, Value::Type(_))
            || matches!(value, Value::Builtin(_) if self.typename(value) == "type")
            || matches!(value, Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Class(_))))
    }

    fn generic_parameters(&mut self, value: &Value) -> PyResult<Value> {
        let (_, args, _, cached) = self
            .generic_parts(value)
            .ok_or_else(|| pyerr("TypeError", "expected a GenericAlias"))?;
        if let Some(index) = cached {
            return Ok(Value::Obj(index));
        }
        let root = self.roots.len();
        self.roots.push(vec![value.clone()]);
        let result = self.generic_collect_parameters(&args);
        if let (Ok(Value::Obj(parameters)), Value::Obj(index)) = (&result, value) {
            if let Some(Object::GenericAlias {
                parameters: cached, ..
            }) = self.heap[*index].as_mut()
            {
                *cached = Some(*parameters);
            }
        }
        self.roots.truncate(root);
        result
    }

    fn generic_collect_parameters(&mut self, args: &[Value]) -> PyResult<Value> {
        let _guard = GenericParameterGuard::enter(args)?;
        let root = self.roots.len();
        self.roots.push(args.to_vec());
        let result = (|| {
            let mut out = Vec::new();
            let mut active = Vec::new();
            for arg in args {
                self.generic_collect_parameter(arg, &mut out, &mut active, root)?;
            }
            Ok(self.obj_value(Object::Tuple(out)))
        })();
        self.roots.truncate(root);
        result
    }

    fn generic_collect_parameter(
        &mut self,
        value: &Value,
        out: &mut Vec<Value>,
        active: &mut Vec<usize>,
        root: usize,
    ) -> PyResult<()> {
        if self.generic_is_class(value) {
            return Ok(());
        }
        let direct = self.type_parameter_kind(value).is_some()
            || self
                .generic_optional_attr(value.clone(), "__typing_subst__")?
                .is_some();
        let parameters = if direct {
            vec![value.clone()]
        } else if let Some(parameters) =
            self.generic_optional_attr(value.clone(), "__parameters__")?
        {
            match self.generic_sequence(&parameters) {
                Some((true, values)) => values,
                _ => Vec::new(),
            }
        } else if let Some((_, values)) = self.generic_sequence(value) {
            let index = if let Value::Obj(index) = value {
                *index
            } else {
                unreachable!()
            };
            if active.contains(&index) {
                return Err(pyerr(
                    "RecursionError",
                    "maximum recursion depth exceeded in __parameter__ calculation",
                ));
            }
            active.push(index);
            for value in values {
                self.generic_collect_parameter(&value, out, active, root)?;
            }
            active.pop();
            return Ok(());
        } else {
            Vec::new()
        };
        for parameter in parameters {
            if !out.iter().any(|old| old.same_identity(&parameter)) {
                self.roots[root].push(parameter.clone());
                out.push(parameter);
            }
        }
        Ok(())
    }

    fn generic_unpacked_tuple_args(&mut self, value: &Value) -> PyResult<Option<Vec<Value>>> {
        if self.generic_is_class(value) {
            return Ok(None);
        }
        if let Some(Value::Obj(index)) =
            self.generic_optional_attr(value.clone(), "__typing_unpacked_tuple_args__")?
        {
            if let Object::Tuple(values) = self.object(index)? {
                return Ok(Some(values));
            }
        }
        Ok(None)
    }

    fn generic_unpack_arguments(&mut self, values: Vec<Value>) -> PyResult<Vec<Value>> {
        let root = self.roots.len();
        self.roots.push(values.clone());
        let result = (|| {
            let mut out = Vec::new();
            for value in values {
                if let Some(items) = self.generic_unpacked_tuple_args(&value)? {
                    if !matches!(items.last(), Some(Value::Builtin(name)) if name == "Ellipsis") {
                        self.roots[root].extend(items.iter().cloned());
                        out.extend(items);
                        continue;
                    }
                }
                out.push(value);
            }
            Ok(out)
        })();
        self.roots.truncate(root);
        result
    }

    fn generic_prepare_substitution(
        &mut self,
        alias: &Value,
        params: &[Value],
        key: Value,
    ) -> PyResult<Vec<Value>> {
        if params.is_empty() {
            return Err(pyerr(
                "TypeError",
                format!("{} is not a generic class", self.repr(alias)?),
            ));
        }
        let values = match self.generic_sequence(&key) {
            Some((true, values)) => values,
            _ => vec![key.clone()],
        };
        let root = self.roots.len();
        let mut roots = vec![alias.clone(), key];
        roots.extend(params.iter().cloned());
        roots.extend(values.iter().cloned());
        self.roots.push(roots);
        let result = (|| {
            let mut values = self.generic_unpack_arguments(values)?;
            self.roots[root].extend(values.iter().cloned());
            for index in 0..params.len() {
                values = self.generic_prepare_parameter(alias, params, index, values)?;
                self.roots[root].extend(values.iter().cloned());
            }
            if values.len() != params.len() {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "Too {} arguments for {}; actual {}, expected {}",
                        if values.len() > params.len() {
                            "many"
                        } else {
                            "few"
                        },
                        self.repr(alias)?,
                        values.len(),
                        params.len()
                    ),
                ));
            }
            Ok(values)
        })();
        self.roots.truncate(root);
        result
    }

    fn generic_prepare_parameter(
        &mut self,
        alias: &Value,
        params: &[Value],
        index: usize,
        args: Vec<Value>,
    ) -> PyResult<Vec<Value>> {
        let root = self.roots.len();
        let mut roots = vec![alias.clone()];
        roots.extend(params.iter().cloned());
        roots.extend(args.iter().cloned());
        self.roots.push(roots);
        let result = self.generic_prepare_parameter_inner(alias, params, index, args, root);
        self.roots.truncate(root);
        result
    }

    fn generic_prepare_parameter_inner(
        &mut self,
        alias: &Value,
        params: &[Value],
        index: usize,
        mut args: Vec<Value>,
        root: usize,
    ) -> PyResult<Vec<Value>> {
        let parameter = &params[index];
        let kind = self.type_parameter_kind(parameter).map(str::to_string);
        match kind.as_deref() {
            Some("typevar") => {
                if index < args.len() {
                    return Ok(args);
                }
                if index == args.len() {
                    let default = self.type_parameter_default(parameter)?;
                    if !is_no_default(&default) {
                        args.push(default);
                        return Ok(args);
                    }
                }
                Err(pyerr(
                    "TypeError",
                    format!(
                        "Too few arguments for {}; actual {}, expected at least {}",
                        self.repr(alias)?,
                        args.len(),
                        index + 1
                    ),
                ))
            }
            Some("paramspec") => {
                if index == args.len() {
                    let default = self.type_parameter_default(parameter)?;
                    if !is_no_default(&default) {
                        args.push(default);
                    }
                }
                if index >= args.len() {
                    return Err(pyerr(
                        "TypeError",
                        format!("Too few arguments for {}", self.repr(alias)?),
                    ));
                }
                let expression = self.generic_sequence(&args[0]).is_some()
                    || self.type_parameter_kind(&args[0]) == Some("paramspec")
                    || matches!(&args[0], Value::Builtin(name) if name == "Ellipsis");
                if params.len() == 1 && !expression {
                    let packed = self.obj_value(Object::Tuple(args));
                    Ok(vec![packed])
                } else {
                    if let Some((false, values)) = self.generic_sequence(&args[index]) {
                        args[index] = self.obj_value(Object::Tuple(values));
                    }
                    Ok(args)
                }
            }
            Some("typevartuple") => {
                if params[index + 1..]
                    .iter()
                    .any(|param| self.type_parameter_kind(param) == Some("typevartuple"))
                {
                    return Err(pyerr(
                        "TypeError",
                        format!(
                            "More than one TypeVarTuple parameter in {}",
                            self.repr(alias)?
                        ),
                    ));
                }
                let len = args.len();
                let mut left = index;
                let mut right = params.len() - index - 1;
                let mut arbitrary = None;
                for (position, arg) in args.iter().enumerate() {
                    if let Some(items) = self.generic_unpacked_tuple_args(arg)? {
                        self.roots[root].extend(items.iter().cloned());
                        if items.len() == 2
                            && matches!(&items[1], Value::Builtin(name) if name == "Ellipsis")
                        {
                            if arbitrary.is_some() {
                                return Err(pyerr(
                                    "TypeError",
                                    "More than one unpacked arbitrary-length tuple argument",
                                ));
                            }
                            arbitrary = Some((position, items[0].clone()));
                        }
                    }
                }
                if let Some((position, _)) = &arbitrary {
                    left = left.min(*position);
                    right = right.min(len - position - 1);
                } else if left + right > len {
                    return Err(pyerr(
                        "TypeError",
                        format!(
                            "Too few arguments for {}; actual {}, expected at least {}",
                            self.repr(alias)?,
                            len,
                            params.len() - 1
                        ),
                    ));
                }
                let replacement = if left == len - right {
                    let default = self.type_parameter_default(parameter)?;
                    if !is_no_default(&default) {
                        let values = self.generic_unpack_arguments(vec![default])?;
                        // CPython keeps the list returned by typing._unpack_args
                        // for a default, whereas explicit packs use a tuple.
                        self.obj_value(Object::List(values))
                    } else {
                        self.obj_value(Object::Tuple(Vec::new()))
                    }
                } else {
                    self.obj_value(Object::Tuple(args[left..len - right].to_vec()))
                };
                let mut out = args[..left].to_vec();
                if let Some((_, fill)) = &arbitrary {
                    out.extend(std::iter::repeat(fill.clone()).take(index - left));
                }
                out.push(replacement);
                if let Some((_, fill)) = &arbitrary {
                    out.extend(
                        std::iter::repeat(fill.clone())
                            .take(params.len().saturating_sub(right + left + index + 1)),
                    );
                }
                out.extend(args[len - right..].iter().cloned());
                Ok(out)
            }
            _ => {
                if let Some(prepare) =
                    self.generic_optional_attr(parameter.clone(), "__typing_prepare_subst__")?
                {
                    if !matches!(prepare, Value::None) {
                        let args = self.obj_value(Object::Tuple(args));
                        let result =
                            self.call(prepare, vec![alias.clone(), args], Vec::new(), None)?;
                        return self
                            .generic_sequence(&result)
                            .filter(|(tuple, _)| *tuple)
                            .map(|(_, values)| values)
                            .ok_or_else(|| {
                                pyerr("TypeError", "__typing_prepare_subst__ must return a tuple")
                            });
                    }
                }
                Ok(args)
            }
        }
    }

    fn generic_substitute_args(
        &mut self,
        args: &[Value],
        params: &[Value],
        replacements: &[Value],
    ) -> PyResult<Vec<Value>> {
        let root = self.roots.len();
        let mut roots = args.to_vec();
        roots.extend(params.iter().cloned());
        roots.extend(replacements.iter().cloned());
        self.roots.push(roots);
        let result = (|| {
            let mut out = Vec::new();
            for arg in args {
                let values = self.generic_substitute_argument(arg, params, replacements)?;
                self.roots[root].extend(values.iter().cloned());
                out.extend(values);
            }
            Ok(out)
        })();
        self.roots.truncate(root);
        result
    }

    fn generic_substitute_argument(
        &mut self,
        arg: &Value,
        params: &[Value],
        replacements: &[Value],
    ) -> PyResult<Vec<Value>> {
        if self.generic_is_class(arg) {
            return Ok(vec![arg.clone()]);
        }
        if let Value::Obj(index) = arg {
            if let Object::TypeUnpack(inner) = self.object(*index)? {
                if self.type_parameter_kind(&inner) == Some("typevartuple") {
                    let position = params
                        .iter()
                        .position(|param| param.same_identity(&inner))
                        .ok_or_else(|| {
                            pyerr(
                                "TypeError",
                                "unpacked TypeVarTuple was not found in __parameters__",
                            )
                        })?;
                    return Ok(match self.generic_sequence(&replacements[position]) {
                        Some((true, values)) => values,
                        _ => vec![replacements[position].clone()],
                    });
                }
                let values = self.generic_substitute_argument(&inner, params, replacements)?;
                let replacement = if values.len() == 1 {
                    values[0].clone()
                } else {
                    self.obj_value(Object::Tuple(values))
                };
                return Ok(vec![self.obj_value(Object::TypeUnpack(replacement))]);
            }
        }
        if let Some((tuple, values)) = self.generic_sequence(arg) {
            let values = self.generic_substitute_args(&values, params, replacements)?;
            return Ok(vec![self.obj_value(if tuple {
                Object::Tuple(values)
            } else {
                Object::List(values)
            })]);
        }
        if self.type_parameter_kind(arg).is_some() {
            let position = params
                .iter()
                .position(|param| param.same_identity(arg))
                .ok_or_else(|| {
                    pyerr(
                        "TypeError",
                        "type parameter was not found in __parameters__",
                    )
                })?;
            return Ok(vec![
                self.type_parameter_subst(arg, replacements[position].clone())?
            ]);
        }
        if let Some(substitute) = self.generic_optional_attr(arg.clone(), "__typing_subst__")? {
            let position = params
                .iter()
                .position(|param| param.same_identity(arg))
                .ok_or_else(|| {
                    pyerr(
                        "TypeError",
                        "argument with __typing_subst__ was not found in __parameters__",
                    )
                })?;
            let result = self.call(
                substitute,
                vec![replacements[position].clone()],
                Vec::new(),
                None,
            )?;
            let unpacked = self
                .generic_optional_attr(arg.clone(), "__typing_is_unpacked_typevartuple__")?
                .map(|value| self.truth(&value))
                .transpose()?
                .unwrap_or(false);
            if unpacked {
                return self
                    .generic_sequence(&result)
                    .filter(|(tuple, _)| *tuple)
                    .map(|(_, values)| values)
                    .ok_or_else(|| {
                        pyerr("TypeError", "expected __typing_subst__ to return a tuple")
                    });
            }
            return Ok(vec![result]);
        }
        let Some(parameters) = self.generic_optional_attr(arg.clone(), "__parameters__")? else {
            return Ok(vec![arg.clone()]);
        };
        let Some((true, parameters)) = self.generic_sequence(&parameters) else {
            return Ok(vec![arg.clone()]);
        };
        if parameters.is_empty() {
            return Ok(vec![arg.clone()]);
        }
        let mut items = Vec::new();
        for parameter in parameters {
            let replacement = params
                .iter()
                .position(|param| param.same_identity(&parameter))
                .map(|index| replacements[index].clone())
                .unwrap_or_else(|| parameter.clone());
            if self.type_parameter_kind(&parameter) == Some("typevartuple") {
                if let Some((true, values)) = self.generic_sequence(&replacement) {
                    items.extend(values);
                    continue;
                }
            }
            items.push(replacement);
        }
        let key = self.obj_value(Object::Tuple(items));
        Ok(vec![self.getitem(arg.clone(), key)?])
    }

    fn generic_subscript(&mut self, alias: &Value, key: Value) -> PyResult<Value> {
        if self.generic_is_typing_alias(alias) {
            return self.typing_alias_cached_call(alias.clone(), key.clone(), |runtime| {
                runtime.generic_subscript_uncached(alias, key)
            });
        }
        self.generic_subscript_uncached(alias, key)
    }

    fn generic_subscript_uncached(&mut self, alias: &Value, key: Value) -> PyResult<Value> {
        let (origin, args, _, _) = self
            .generic_parts(alias)
            .ok_or_else(|| pyerr("TypeError", "expected a GenericAlias"))?;
        let root = self.roots.len();
        self.roots.push(vec![alias.clone(), key.clone()]);
        let result = (|| {
            let parameters = self.generic_parameters(alias)?;
            self.roots[root].push(parameters.clone());
            let (_, params) = self.generic_sequence(&parameters).unwrap();
            let replacements = self.generic_prepare_substitution(alias, &params, key)?;
            self.roots[root].extend(replacements.iter().cloned());
            let args = self.generic_substitute_args(&args, &params, &replacements)?;
            let key = self.obj_value(Object::Tuple(args));
            if self.generic_is_typing_alias(alias) {
                self.typing_generic_alias_uncached(origin, key)
            } else {
                self.generic_alias(origin, key)
            }
        })();
        self.roots.truncate(root);
        result
    }

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
        let result = self.obj_value(Object::GenericAlias {
            origin,
            args,
            args_tuple,
            parameters: None,
            typing: false,
        });
        self.roots.truncate(root);
        Ok(result)
    }

    fn generic_parts(&self, value: &Value) -> Option<(Value, Vec<Value>, usize, Option<usize>)> {
        if let Value::Obj(index) = value {
            if let Some(Object::GenericAlias {
                origin,
                args,
                args_tuple,
                parameters,
                ..
            }) = self.heap.get(*index).and_then(Option::as_ref)
            {
                return Some((origin.clone(), args.clone(), *args_tuple, *parameters));
            }
        }
        None
    }

    fn generic_is_typing_alias(&self, value: &Value) -> bool {
        matches!(value, Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::GenericAlias { typing: true, .. })))
    }

    fn generic_finish_call(&mut self, result: Value, alias: &Value) -> PyResult<Value> {
        let root = self.roots.len();
        self.roots.push(vec![result.clone(), alias.clone()]);
        let outcome = (|| {
            if let Err(mut error) = self.setattr(result.clone(), "__orig_class__", alias.clone()) {
                let suppress = if self.generic_is_typing_alias(alias) {
                    let value = self.exception_value(&mut error);
                    if let Some(class) = self.object_class(&value) {
                        self.is_subclass(&class, &Value::Type("Exception".into()))?
                    } else {
                        self.exception_match(&value, &Value::Type("Exception".into()))?
                    }
                } else {
                    error.kind == "AttributeError" || error.kind == "TypeError"
                };
                if !suppress {
                    return Err(error);
                }
            }
            Ok(result)
        })();
        self.roots.truncate(root);
        outcome
    }

    fn generic_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        let (origin, _, args_tuple, _) = self.generic_parts(&value)?;
        let typing = self.generic_is_typing_alias(&value);
        if typing
            && [
                "__repr__",
                "__str__",
                "__hash__",
                "__eq__",
                "__ne__",
                "__call__",
                "__getitem__",
            ]
            .contains(&name)
        {
            return Some(Ok(self.obj_value(Object::Bound(
                Value::Builtin(format!("method:{}", name)),
                value,
            ))));
        }
        if typing
            && name.starts_with("__")
            && name.ends_with("__")
            && ![
                "__class__",
                "__origin__",
                "__args__",
                "__parameters__",
                "__mro_entries__",
                "__name__",
                "__qualname__",
                "__module__",
                "__dict__",
            ]
            .contains(&name)
        {
            return Some(Err(pyerr("AttributeError", name)));
        }
        match name {
            // The VM provides the type object, rather than the origin's type.
            "__class__" => None,
            "__origin__" => Some(Ok(origin)),
            "__args__" => Some(Ok(Value::Obj(args_tuple))),
            "__parameters__" => Some(self.generic_parameters(&value)),
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
                return self.generic_finish_call(result, &value);
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
                "__hash__" => self.generic_value_hash(&value),
                "__eq__" | "__ne__" => {
                    if self.generic_parts(&args[0]).is_none()
                        || self.generic_is_typing_alias(&value)
                            != self.generic_is_typing_alias(&args[0])
                    {
                        return Ok(Value::Builtin("NotImplemented".into()));
                    }
                    self.generic_compare_value(
                        if name == "__eq__" { "==" } else { "!=" },
                        &value,
                        &args[0],
                    )
                    .unwrap()
                }
                "__getitem__" => self.generic_subscript(&value, args[0].clone()),
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
        if self.generic_is_typing_alias(a) != self.generic_is_typing_alias(b) {
            return Some(Ok(Value::Bool(op == "!=")));
        }
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
            let hash = if self.generic_is_typing_alias(value) {
                ((0x345678u64 ^ origin_hash).wrapping_mul(1_000_003) ^ args_hash)
                    .wrapping_mul(1_000_003)
                    ^ 2
            } else {
                origin_hash ^ args_hash
            } as i64;
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
