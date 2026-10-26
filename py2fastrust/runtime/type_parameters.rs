// Python type parameters, lazy type aliases and PEP 604 unions.  The two
// compilers share these objects and the ordinary Function calling convention.
#[derive(Clone, Debug)]
struct TypeLazy {
    value: Option<Value>,
    thunk: Option<Value>,
}
impl TypeLazy {
    fn constant(value: Value) -> Self {
        Self {
            value: Some(value),
            thunk: None,
        }
    }
    fn lazy(thunk: Value) -> Self {
        Self {
            value: None,
            thunk: Some(thunk),
        }
    }
}
#[derive(Clone, Debug)]
struct TypeParameter {
    name: String,
    kind: String,
    module: Value,
    attrs: usize,
    covariant: bool,
    contravariant: bool,
    infer_variance: bool,
    bound: TypeLazy,
    constraints: TypeLazy,
    default: TypeLazy,
}
#[derive(Clone, Debug)]
struct TypingAliasCacheEntry {
    owner: Value,
    key: Value,
    value: Value,
    hash: u64,
    category: u8,
}
fn is_no_default(value: &Value) -> bool {
    matches!(value, Value::Builtin(name) if name == "typing.NoDefault")
}
fn typing_type_name(name: &str) -> bool {
    matches!(
        name,
        "typing.TypeVar"
            | "typing.ParamSpec"
            | "typing.TypeVarTuple"
            | "typing.TypeAliasType"
            | "typing.Generic"
            | "typing.ParamSpecArgs"
            | "typing.ParamSpecKwargs"
            | "typing.ForwardRef"
            | "typing.Union"
            | "typing._UnpackGenericAlias"
            | "typing._GenericAlias"
            | "NoDefaultType"
    )
}
fn typing_constructor_name(name: &str) -> bool {
    matches!(
        name,
        "typing.TypeVar"
            | "typing.ParamSpec"
            | "typing.TypeVarTuple"
            | "typing.TypeAliasType"
            | "typing.ParamSpecArgs"
            | "typing.ParamSpecKwargs"
            | "typing.ForwardRef"
            | "NoDefaultType"
    )
}
impl Runtime {
    fn initialize_generic_class(&mut self, class: &Value) -> PyResult<()> {
        let root = self.roots.len();
        self.roots.push(vec![class.clone()]);
        let result = (|| {
            let Value::Obj(index) = class else {
                return Ok(());
            };
            let Object::Class(class) = self.object(*index)? else {
                return Ok(());
            };
            if !class.bases.iter().any(|base| {
                self.class_mro(base, 0)
                    .unwrap_or_default()
                    .iter()
                    .any(|base| matches!(base,Value::Builtin(name)if name=="typing.Generic"))
            }) {
                return Ok(());
            }
            let original = self.ns_get(class.attrs, "__orig_bases__");
            if original.is_none()
                && class
                    .bases
                    .iter()
                    .any(|base| matches!(base,Value::Builtin(name)if name=="typing.Generic"))
            {
                return Err(pyerr("TypeError", "Cannot inherit from plain Generic"));
            }
            let params = if let Some(original) = original {
                let bases = self.to_vec(original)?;
                let collected = self.generic_collect_parameters(&bases)?;
                self.roots[root].push(collected.clone());
                let mut declared = None;
                for base in &bases {
                    if let Some((origin, args, _, _)) = self.generic_parts(base) {
                        if matches!(origin,Value::Builtin(name)if name=="typing.Generic") {
                            if declared.is_some() {
                                return Err(pyerr(
                                    "TypeError",
                                    "Cannot inherit from Generic[...] multiple times.",
                                ));
                            }
                            let parameters = self.generic_collect_parameters(&args)?;
                            self.roots[root].push(parameters.clone());
                            declared = Some(parameters);
                        }
                    }
                }
                if let Some(declared) = declared {
                    let declared_values = self.to_vec(declared.clone())?;
                    for parameter in self.to_vec(collected)? {
                        if !declared_values
                            .iter()
                            .any(|declared| declared.same_identity(&parameter))
                        {
                            return Err(pyerr(
                                "TypeError",
                                "Some type variables are not listed in Generic[...]",
                            ));
                        }
                    }
                    declared
                } else {
                    collected
                }
            } else {
                self.obj_value(Object::Tuple(Vec::new()))
            };
            self.ns_set(class.attrs, "__parameters__".into(), params);
            Ok(())
        })();
        self.roots.truncate(root);
        result
    }
    fn typing_class_uses_typing(&self, class: &Value) -> bool {
        for base in self.class_mro(class, 0).unwrap_or_default() {
            if let Value::Builtin(name) = base {
                if [
                    "list",
                    "dict",
                    "set",
                    "tuple",
                    "frozenset",
                    "type",
                    "typing.Generic",
                ]
                .contains(&name.as_str())
                {
                    return name == "typing.Generic";
                }
            }
        }
        false
    }
    fn typing_alias_cached_call<F>(&mut self, owner: Value, key: Value, build: F) -> PyResult<Value>
    where
        F: FnOnce(&mut Runtime) -> PyResult<Value>,
    {
        let root = self.roots.len();
        self.roots.push(vec![owner.clone(), key.clone()]);
        let result = (|| {
            let category = if self.generic_is_typing_alias(&owner) {
                1
            } else {
                0
            };
            let hash: PyResult<u64> = (|| {
                Ok(self.generic_component_hash(&owner)?.rotate_left(17)
                    ^ self.generic_component_hash(&key)?)
            })();
            let hash = match hash {
                Ok(hash) => Some(hash),
                Err(error) if error.kind == "TypeError" => None,
                Err(error) => return Err(error),
            };
            if let Some(hash) = hash {
                let cached = self.typing_alias_cache.clone();
                for entry in &cached {
                    self.roots[root].extend([
                        entry.owner.clone(),
                        entry.key.clone(),
                        entry.value.clone(),
                    ]);
                }
                for previous in cached {
                    if previous.category == category
                        && previous.hash == hash
                        && self.identical_or_equal(&previous.owner, &owner)?
                        && self.identical_or_equal(&previous.key, &key)?
                    {
                        if let Some(index) = self
                            .typing_alias_cache
                            .iter()
                            .position(|entry| entry.value.same_identity(&previous.value))
                        {
                            self.typing_alias_cache.remove(index);
                        }
                        self.typing_alias_cache.push(previous.clone());
                        return Ok(previous.value);
                    }
                }
            }
            let value = build(self)?;
            if let Some(hash) = hash {
                if self
                    .typing_alias_cache
                    .iter()
                    .filter(|entry| entry.category == category)
                    .count()
                    >= 128
                {
                    let index = self
                        .typing_alias_cache
                        .iter()
                        .position(|entry| entry.category == category)
                        .unwrap();
                    self.typing_alias_cache.remove(index);
                }
                self.typing_alias_cache.push(TypingAliasCacheEntry {
                    owner,
                    key,
                    value: value.clone(),
                    hash,
                    category,
                });
            }
            Ok(value)
        })();
        self.roots.truncate(root);
        result
    }
    fn typing_generic_alias_uncached(&mut self, origin: Value, key: Value) -> PyResult<Value> {
        let alias = self.generic_alias(origin, key)?;
        if let Value::Obj(index) = &alias {
            if let Some(Object::GenericAlias { typing, .. }) = self.heap[*index].as_mut() {
                *typing = true;
            }
        }
        Ok(alias)
    }
    fn typing_generic_alias(&mut self, origin: Value, key: Value) -> PyResult<Value> {
        self.typing_alias_cached_call(origin.clone(), key.clone(), |runtime| {
            runtime.typing_generic_alias_uncached(origin, key)
        })
    }
    fn typing_class_subscript(&mut self, class: Value, key: Value) -> PyResult<Value> {
        self.typing_alias_cached_call(class.clone(), key.clone(), |runtime| {
            runtime.typing_class_subscript_uncached(class, key)
        })
    }
    fn typing_class_subscript_uncached(&mut self, class: Value, key: Value) -> PyResult<Value> {
        let root = self.roots.len();
        self.roots.push(vec![class.clone(), key.clone()]);
        let result = (|| {
            let params = self.getattr(class.clone(), "__parameters__")?;
            self.roots[root].push(params.clone());
            let params = self.to_vec(params)?;
            let replacements = self.generic_prepare_substitution(&class, &params, key)?;
            self.roots[root].extend(replacements.iter().cloned());
            let mut symbolic = Vec::new();
            for parameter in &params {
                symbolic.push(
                    if self.type_parameter_kind(parameter) == Some("typevartuple") {
                        self.obj_value(Object::TypeUnpack(parameter.clone()))
                    } else {
                        parameter.clone()
                    },
                );
            }
            self.roots[root].extend(symbolic.iter().cloned());
            let args = self.generic_substitute_args(&symbolic, &params, &replacements)?;
            let key = self.obj_value(Object::Tuple(args));
            self.typing_generic_alias_uncached(class, key)
        })();
        self.roots.truncate(root);
        result
    }
    fn is_typing_value(&self, value: &Value) -> bool {
        matches!(value,Value::Builtin(name)if name.starts_with("typing.") || name=="NoDefaultType")
            || matches!(value,Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::TypeParameter(_)|Object::TypeAlias{..}|Object::TypeUnpack(_)|Object::UnpackedAlias(_)|Object::ParamSpecMarker{..}|Object::TypeEvaluator(_)|Object::ForwardRef{..}|Object::TypeUnion{..})))
    }
    fn unpack_alias(&mut self, inner: Value) -> PyResult<Value> {
        if self.generic_parts(&inner).is_none() {
            return Err(pyerr("TypeError", "cannot unpack a non-generic alias"));
        }
        Ok(self.obj_value(Object::UnpackedAlias(inner)))
    }
    fn type_parameter_kind<'a>(&'a self, value: &Value) -> Option<&'a str> {
        if let Value::Obj(index) = value {
            if let Some(Object::TypeParameter(parameter)) =
                self.heap.get(*index).and_then(Option::as_ref)
            {
                return Some(&parameter.kind);
            }
        }
        None
    }
    fn make_type_parameter(
        &mut self,
        name: String,
        kind: String,
        bound: Value,
        constraints: Value,
        default: Value,
    ) -> PyResult<Value> {
        let empty = self.obj_value(Object::Tuple(Vec::new()));
        let attrs = self.alloc(Object::Dict(Vec::new()));
        let parameter = TypeParameter {
            name,
            kind,
            module: Value::Str("typing".into()),
            attrs,
            covariant: false,
            contravariant: false,
            infer_variance: true,
            bound: if matches!(bound, Value::None) {
                TypeLazy::constant(Value::None)
            } else {
                TypeLazy::lazy(bound)
            },
            constraints: if matches!(constraints, Value::None) {
                TypeLazy::constant(empty)
            } else {
                TypeLazy::lazy(constraints)
            },
            default: if matches!(default, Value::None) {
                TypeLazy::constant(Value::Builtin("typing.NoDefault".into()))
            } else {
                TypeLazy::lazy(default)
            },
        };
        Ok(self.obj_value(Object::TypeParameter(parameter)))
    }
    fn type_lazy_value(&mut self, owner: &Value, field: &str) -> PyResult<Value> {
        let Value::Obj(index) = owner else {
            return Err(pyerr(
                "TypeError",
                "expected a type parameter or type alias",
            ));
        };
        let lazy = match self.object(*index)? {
            Object::TypeParameter(parameter) => match field {
                "bound" => parameter.bound,
                "constraints" => parameter.constraints,
                "default" => parameter.default,
                _ => return Err(pyerr("AttributeError", field)),
            },
            Object::TypeAlias { value, .. } if field == "value" => value,
            _ => return Err(pyerr("AttributeError", field)),
        };
        if let Some(value) = lazy.value {
            return Ok(value);
        }
        let thunk = lazy
            .thunk
            .ok_or_else(|| pyerr("RuntimeError", "missing type evaluator"))?;
        let root = self.roots.len();
        self.roots.push(vec![owner.clone(), thunk.clone()]);
        let result = self.call(thunk, Vec::new(), Vec::new(), None);
        if let Ok(value) = &result {
            let lazy = match self.heap[*index].as_mut() {
                Some(Object::TypeParameter(parameter)) => match field {
                    "bound" => &mut parameter.bound,
                    "constraints" => &mut parameter.constraints,
                    "default" => &mut parameter.default,
                    _ => unreachable!(),
                },
                Some(Object::TypeAlias { value, .. }) => value,
                _ => unreachable!(),
            };
            lazy.value = Some(value.clone());
        }
        self.roots.truncate(root);
        result
    }
    fn type_parameter_default(&mut self, value: &Value) -> PyResult<Value> {
        self.type_lazy_value(value, "default")
    }
    fn type_lazy_evaluator(&mut self, lazy: TypeLazy, optional_none: bool) -> Value {
        if let Some(thunk) = lazy.thunk {
            return thunk;
        }
        let value = lazy.value.unwrap_or(Value::None);
        if optional_none && matches!(value, Value::None) {
            return Value::None;
        }
        if optional_none
            && matches!(&value,Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(values)) if values.is_empty()))
        {
            return Value::None;
        }
        self.obj_value(Object::TypeEvaluator(value))
    }
    fn type_parameter_subst(&mut self, parameter: &Value, replacement: Value) -> PyResult<Value> {
        match self.type_parameter_kind(parameter) {
            Some("typevartuple") => Err(pyerr(
                "TypeError",
                "Substitution of bare TypeVarTuple is not supported",
            )),
            Some("paramspec") => {
                if self.type_parameter_kind(&replacement) == Some("paramspec")
                    || matches!(&replacement,Value::Builtin(name) if name=="Ellipsis")
                {
                    return Ok(replacement);
                }
                let payload = self
                    .native_payload(&replacement)
                    .unwrap_or_else(|| replacement.clone());
                if let Value::Obj(index) = payload {
                    if let Object::List(values) | Object::Tuple(values) = self.object(index)? {
                        let mut result = Vec::new();
                        for value in values {
                            result.push(self.type_argument(value)?);
                        }
                        return Ok(self.obj_value(Object::Tuple(result)));
                    }
                }
                Err(pyerr(
                    "TypeError",
                    format!(
                        "Expected a list of types, an ellipsis, ParamSpec, or Concatenate. Got {}",
                        self.str_value(&replacement)?
                    ),
                ))
            }
            Some(_) => self.type_argument(replacement),
            None => Err(pyerr("TypeError", "expected a type parameter")),
        }
    }
    fn type_argument(&mut self, replacement: Value) -> PyResult<Value> {
        if matches!(replacement, Value::None) {
            return Ok(Value::Builtin("NoneType".into()));
        }
        if let Value::Str(arg) = replacement {
            return Ok(self.obj_value(Object::ForwardRef {
                arg: arg.to_string(),
                module: Value::None,
            }));
        }
        if matches!(&replacement,Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_)|Object::TypeUnpack(_))))
        {
            return Err(pyerr(
                "TypeError",
                format!(
                    "Parameters to generic types must be types. Got {}.",
                    self.repr(&replacement)?
                ),
            ));
        }
        Ok(replacement)
    }
    fn typing_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        if !self.is_typing_value(&value) {
            return None;
        }
        if let Value::Builtin(typ) = &value {
            if typing_type_name(typ) {
                match name {
                    "__module__" => {
                        return Some(Ok(Value::Str(
                            if typ == "NoDefaultType" {
                                "builtins"
                            } else {
                                "typing"
                            }
                            .into(),
                        )))
                    }
                    "__name__" | "__qualname__" => {
                        return Some(Ok(Value::Str(typ.rsplit('.').next().unwrap().into())))
                    }
                    "__bases__" => {
                        return Some(Ok(
                            self.obj_value(Object::Tuple(vec![Value::Builtin("object".into())]))
                        ))
                    }
                    "__class__" => return Some(Ok(Value::Builtin("type".into()))),
                    "__class_getitem__" if typ == "typing.Generic" => {
                        return Some(Ok(self.obj_value(Object::Bound(
                            Value::Builtin("method:__class_getitem__".into()),
                            value,
                        ))))
                    }
                    _ => {}
                }
            }
            if typ == "typing.NoDefault" && name == "__class__" {
                return Some(Ok(Value::Builtin("NoDefaultType".into())));
            }
            if typ == "typing.Unpack" && name == "__module__" {
                return Some(Ok(Value::Str("typing".into())));
            }
            return None;
        }
        let Value::Obj(index) = &value else {
            return None;
        };
        let object = self.heap.get(*index)?.as_ref()?.clone();
        Some((|| match object {
            Object::TypeParameter(parameter) => {
                if let Some(attr) = self.ns_get(parameter.attrs, name) {
                    return Ok(attr);
                }
                match name {
                    "__name__" => Ok(Value::Str(parameter.name.into())),
                    "__module__" => Ok(parameter.module),
                    "__class__" => Ok(Value::Builtin(format!(
                        "typing.{}",
                        match parameter.kind.as_str() {
                            "paramspec" => "ParamSpec",
                            "typevartuple" => "TypeVarTuple",
                            _ => "TypeVar",
                        }
                    ))),
                    "__bound__" if parameter.kind != "typevartuple" => {
                        self.type_lazy_value(&value, "bound")
                    }
                    "__constraints__" if parameter.kind == "typevar" => {
                        self.type_lazy_value(&value, "constraints")
                    }
                    "__default__" => self.type_lazy_value(&value, "default"),
                    "__infer_variance__" if parameter.kind != "typevartuple" => {
                        Ok(Value::Bool(parameter.infer_variance))
                    }
                    "__covariant__" if parameter.kind != "typevartuple" => {
                        Ok(Value::Bool(parameter.covariant))
                    }
                    "__contravariant__" if parameter.kind != "typevartuple" => {
                        Ok(Value::Bool(parameter.contravariant))
                    }
                    "evaluate_bound" if parameter.kind == "typevar" => {
                        Ok(self.type_lazy_evaluator(parameter.bound, true))
                    }
                    "evaluate_constraints" if parameter.kind == "typevar" => {
                        Ok(self.type_lazy_evaluator(parameter.constraints, true))
                    }
                    "evaluate_default" => Ok(self.type_lazy_evaluator(parameter.default, false)),
                    "args" | "kwargs" if parameter.kind == "paramspec" => {
                        Ok(self.obj_value(Object::ParamSpecMarker {
                            parameter: value,
                            kind: name.into(),
                        }))
                    }
                    "has_default" | "__typing_subst__" | "__typing_prepare_subst__" => Ok(self
                        .obj_value(Object::Bound(
                            Value::Builtin(format!("method:{}", name)),
                            value,
                        ))),
                    "__iter__" if parameter.kind == "typevartuple" => Ok(self.obj_value(
                        Object::Bound(Value::Builtin("method:__iter__".into()), value),
                    )),
                    _ => Err(pyerr(
                        "AttributeError",
                        format!(
                            "'{}' object has no attribute '{}'",
                            self.typename(&value),
                            name
                        ),
                    )),
                }
            }
            Object::TypeAlias {
                name: alias_name,
                module,
                params,
                value: lazy,
            } => match name {
                "__name__" => Ok(Value::Str(alias_name.into())),
                "__module__" => Ok(module),
                "__type_params__" | "__parameters__" => Ok(params),
                "__value__" => self.type_lazy_value(&value, "value"),
                "evaluate_value" => Ok(self.type_lazy_evaluator(lazy, false)),
                "__class__" => Ok(Value::Builtin("typing.TypeAliasType".into())),
                "__getitem__" => Ok(self.obj_value(Object::Bound(
                    Value::Builtin("method:__getitem__".into()),
                    value,
                ))),
                _ => Err(pyerr(
                    "AttributeError",
                    format!("'typing.TypeAliasType' object has no attribute '{}'", name),
                )),
            },
            Object::TypeUnpack(inner) => match name {
                "__origin__" => Ok(Value::Builtin("typing.Unpack".into())),
                "__args__" => Ok(self.obj_value(Object::Tuple(vec![inner.clone()]))),
                "__parameters__" => {
                    if self.type_parameter_kind(&inner).is_some() {
                        Ok(self.obj_value(Object::Tuple(vec![inner])))
                    } else {
                        self.getattr(inner, "__parameters__")
                    }
                }
                "__module__" => Ok(Value::Str("typing".into())),
                "__class__" => Ok(Value::Builtin("typing._UnpackGenericAlias".into())),
                "__typing_unpacked_tuple_args__" => {
                    if let Some((origin, _, args, _)) = self.generic_parts(&inner) {
                        if matches!(origin,Value::Builtin(name)if name=="tuple") {
                            return Ok(Value::Obj(args));
                        }
                    }
                    Ok(Value::None)
                }
                _ => Err(pyerr("AttributeError", name)),
            },
            Object::UnpackedAlias(inner) => match name {
                "__unpacked__" => Ok(Value::Bool(true)),
                "__class__" => Ok(Value::Builtin("GenericAlias".into())),
                "__typing_unpacked_tuple_args__" => {
                    let (origin, _, args, _) = self.generic_parts(&inner).unwrap();
                    if matches!(origin,Value::Builtin(name)if name=="tuple") {
                        Ok(Value::Obj(args))
                    } else {
                        Ok(Value::None)
                    }
                }
                _ => self.getattr(inner, name),
            },
            Object::ParamSpecMarker { parameter, kind } => match name {
                "__origin__" => Ok(parameter),
                "__class__" => Ok(Value::Builtin(format!(
                    "typing.ParamSpec{}",
                    if kind == "args" { "Args" } else { "Kwargs" }
                ))),
                _ => Err(pyerr("AttributeError", name)),
            },
            Object::ForwardRef { arg, module } => match name {
                "__forward_arg__" => Ok(Value::Str(arg.into())),
                "__forward_module__" => Ok(module),
                "__class__" => Ok(Value::Builtin("typing.ForwardRef".into())),
                _ => Err(pyerr("AttributeError", name)),
            },
            Object::TypeEvaluator(_) => match name {
                "__call__" => Ok(value),
                _ => Err(pyerr("AttributeError", name)),
            },
            Object::TypeUnion { args, parameters } => match name {
                "__args__" => Ok(self.obj_value(Object::Tuple(args.clone()))),
                "__origin__" => Ok(Value::Builtin("typing.Union".into())),
                "__class__" => Ok(Value::Builtin("typing.Union".into())),
                "__parameters__" => self.union_parameters(&value, &args, parameters),
                "__getitem__" => Ok(self.obj_value(Object::Bound(
                    Value::Builtin("method:__getitem__".into()),
                    value,
                ))),
                _ => Err(pyerr("AttributeError", name)),
            },
            _ => return Err(pyerr("__typing_not_handled__", "")),
        })())
        .filter(|result| !matches!(result,Err(error)if error.kind=="__typing_not_handled__"))
    }
    fn typing_method(
        &mut self,
        value: Value,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> Option<PyResult<Value>> {
        let kind = self.type_parameter_kind(&value).map(str::to_string);
        let special = kind.is_some()
            || matches!(&value,Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::TypeAlias{..}|Object::TypeUnion{..})))
            || matches!(&value,Value::Builtin(name) if name=="typing.Generic");
        if !special {
            return None;
        }
        Some((|| {
            if !kwargs.is_empty() {
                return Err(pyerr(
                    "TypeError",
                    format!("{}() takes no keyword arguments", name),
                ));
            }
            match name {
                "has_default" if kind.is_some() => {
                    if !args.is_empty() {
                        return Err(pyerr("TypeError", "has_default() takes no arguments"));
                    }
                    let Value::Obj(index) = value else {
                        unreachable!()
                    };
                    let Object::TypeParameter(parameter) = self.object(index)? else {
                        unreachable!()
                    };
                    Ok(Value::Bool(
                        parameter.default.thunk.is_some()
                            || parameter
                                .default
                                .value
                                .as_ref()
                                .map(|value| !is_no_default(value))
                                .unwrap_or(false),
                    ))
                }
                "__typing_subst__" if kind.is_some() => {
                    if args.len() != 1 {
                        return Err(pyerr("TypeError", "__typing_subst__() takes one argument"));
                    }
                    self.type_parameter_subst(&value, args[0].clone())
                }
                "__typing_prepare_subst__" if kind.is_some() => {
                    if args.len() != 2 {
                        return Err(pyerr(
                            "TypeError",
                            "__typing_prepare_subst__() takes two arguments",
                        ));
                    }
                    let params = self.getattr(args[0].clone(), "__parameters__")?;
                    let params = self.to_vec(params)?;
                    let index = params
                        .iter()
                        .position(|parameter| parameter.same_identity(&value))
                        .ok_or_else(|| pyerr("ValueError", "type parameter is not in alias"))?;
                    let values = self.to_vec(args[1].clone())?;
                    let values =
                        self.generic_prepare_parameter(&args[0], &params, index, values)?;
                    Ok(self.obj_value(Object::Tuple(values)))
                }
                "__iter__" if kind.as_deref() == Some("typevartuple") => self.iter(value),
                "__getitem__" | "__class_getitem__" => {
                    if args.len() != 1 {
                        return Err(pyerr("TypeError", "expected one type argument"));
                    }
                    self.typing_getitem(value, args[0].clone()).unwrap()
                }
                _ => Err(pyerr("AttributeError", name)),
            }
        })())
    }
    fn typing_getitem(&mut self, value: Value, key: Value) -> Option<PyResult<Value>> {
        if matches!(&value,Value::Builtin(name)if name=="typing.Unpack") {
            return Some(Ok(self.obj_value(Object::TypeUnpack(key))));
        }
        if matches!(&value,Value::Builtin(name)if name=="typing.Union") {
            return Some((|| {
                let args = if matches!(&key,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_))))
                {
                    self.to_vec(key)?
                } else {
                    vec![key]
                };
                let mut converted = Vec::new();
                for value in args {
                    converted.push(self.type_argument(value)?);
                }
                self.make_union(converted)
            })());
        }
        if matches!(&value,Value::Builtin(name)if name=="typing.Generic") {
            return Some((|| {
                let args = if matches!(&key,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_))))
                {
                    self.to_vec(key.clone())?
                } else {
                    vec![key.clone()]
                };
                if args.is_empty() {
                    return Err(pyerr(
                        "TypeError",
                        "Parameter list to Generic[...] cannot be empty",
                    ));
                }
                let mut parameters = Vec::new();
                for arg in &args {
                    let parameter = match arg {
                        Value::Obj(index) => match self.object(*index)? {
                            Object::TypeUnpack(inner) => inner,
                            _ => arg.clone(),
                        },
                        _ => arg.clone(),
                    };
                    if self.type_parameter_kind(&parameter).is_none() {
                        return Err(pyerr("TypeError","Parameters to Generic[...] must all be type variables or parameter specification variables."));
                    }
                    if parameters
                        .iter()
                        .any(|old: &Value| old.same_identity(&parameter))
                    {
                        return Err(pyerr(
                            "TypeError",
                            "Parameters to Generic[...] must all be unique",
                        ));
                    }
                    parameters.push(parameter);
                }
                self.typing_generic_alias(value, key)
            })());
        }
        if let Value::Obj(index) = &value {
            match self.heap.get(*index).and_then(Option::as_ref).cloned() {
                Some(Object::UnpackedAlias(inner)) => {
                    return Some((|| {
                        let alias = self.getitem(inner, key)?;
                        self.unpack_alias(alias)
                    })())
                }
                Some(Object::TypeAlias { .. }) => return Some(self.generic_alias(value, key)),
                Some(Object::TypeUnion { args, parameters }) => {
                    return Some((|| {
                        let params = self.union_parameters(&value, &args, parameters)?;
                        let params = self.to_vec(params)?;
                        let replacements =
                            self.generic_prepare_substitution(&value, &params, key)?;
                        let args = self.generic_substitute_args(&args, &params, &replacements)?;
                        self.make_union(args)
                    })())
                }
                _ => {}
            }
        }
        None
    }
    fn typing_module_call(
        &mut self,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        if args.len() != 1 || !kwargs.is_empty() {
            return Err(pyerr("TypeError", format!("{}() takes one argument", name)));
        }
        let value = args[0].clone();
        match name {
            "get_origin" => {
                if let Some((origin, _, _, _)) = self.generic_parts(&value) {
                    return Ok(origin);
                }
                if matches!(&value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::TypeUnion{..}|Object::TypeUnpack(_)|Object::ParamSpecMarker{..})))
                {
                    return self.getattr(value, "__origin__");
                }
                Ok(Value::None)
            }
            "get_args" => {
                if let Some((_, _, args, _)) = self.generic_parts(&value) {
                    return Ok(Value::Obj(args));
                }
                if matches!(&value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::TypeUnion{..}|Object::TypeUnpack(_))))
                {
                    return self.getattr(value, "__args__");
                }
                Ok(self.obj_value(Object::Tuple(Vec::new())))
            }
            _ => Err(pyerr("NotImplementedError", format!("typing.{}", name))),
        }
    }
    fn typing_hash(&mut self, value: &Value) -> Option<PyResult<Value>> {
        let Value::Obj(index) = value else {
            return None;
        };
        let object = self.heap.get(*index)?.as_ref()?.clone();
        Some((|| {
            let hash = match object {
                Object::TypeUnpack(inner) => self
                    .generic_component_hash(&inner)?
                    .wrapping_add(0x17443a21),
                Object::UnpackedAlias(inner) => self
                    .generic_component_hash(&inner)?
                    .wrapping_add(0x46317abc),
                Object::ParamSpecMarker { .. } => {
                    return Err(pyerr(
                        "TypeError",
                        format!("unhashable type: '{}'", self.typename(value)),
                    ))
                }
                Object::ForwardRef { arg, module } => {
                    let arg = Value::Str(arg.into());
                    self.generic_component_hash(&arg)? ^ self.generic_component_hash(&module)?
                }
                Object::TypeUnion { args, .. } => {
                    let mut hash = 0x43434u64;
                    for arg in &args {
                        hash ^= self.generic_component_hash(arg)?;
                    }
                    hash
                }
                _ => return Err(pyerr("__typing_not_handled__", "")),
            } as i64;
            Ok(Value::Int(
                Int::from_i128(if hash == -1 { -2 } else { hash as i128 }).into(),
            ))
        })())
        .filter(|result| !matches!(result,Err(error)if error.kind=="__typing_not_handled__"))
    }
    fn union_parameters(
        &mut self,
        value: &Value,
        args: &[Value],
        parameters: Option<usize>,
    ) -> PyResult<Value> {
        if let Some(index) = parameters {
            return Ok(Value::Obj(index));
        }
        let result = self.generic_collect_parameters(args)?;
        if let (Value::Obj(index), Value::Obj(params)) = (value, &result) {
            if let Some(Object::TypeUnion { parameters, .. }) = self.heap[*index].as_mut() {
                *parameters = Some(*params);
            }
        }
        Ok(result)
    }
    fn make_union(&mut self, args: Vec<Value>) -> PyResult<Value> {
        let mut flattened = Vec::new();
        for value in args {
            let value = if matches!(value, Value::None) {
                Value::Builtin("NoneType".into())
            } else {
                value
            };
            let nested = if let Value::Obj(index) = &value {
                match self.object(*index)? {
                    Object::TypeUnion { args, .. } => Some(args),
                    _ => None,
                }
            } else {
                None
            };
            for value in nested.unwrap_or(vec![value]) {
                if !self.contains_vec(&flattened, &value)? {
                    flattened.push(value);
                }
            }
        }
        if flattened.is_empty() {
            return Err(pyerr("TypeError", "Cannot take a Union of no types."));
        }
        if flattened.len() == 1 {
            return Ok(flattened.remove(0));
        }
        Ok(self.obj_value(Object::TypeUnion {
            args: flattened,
            parameters: None,
        }))
    }
    fn union_operand(&self, value: &Value) -> bool {
        if self.type_parameter_kind(value) == Some("typevartuple") {
            return false;
        }
        matches!(value, Value::None)
            || matches!(value,Value::Builtin(name)if self.typename(value)=="type" || name=="NoneType")
            || matches!(value, Value::Type(_))
            || matches!(value,Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_)|Object::GenericAlias{..}|Object::TypeParameter(_)|Object::TypeAlias{..}|Object::TypeUnion{..}|Object::ForwardRef{..})))
    }
    fn typing_binary(&mut self, op: &str, left: &Value, right: &Value) -> Option<PyResult<Value>> {
        if op == "|" && self.union_operand(left) && self.union_operand(right) {
            return Some(self.make_union(vec![left.clone(), right.clone()]));
        }
        None
    }
    fn typing_equal(&mut self, left: &Value, right: &Value) -> Option<PyResult<bool>> {
        let (Value::Obj(li), Value::Obj(ri)) = (left, right) else {
            return None;
        };
        let l = self.heap.get(*li)?.as_ref()?.clone();
        let r = self.heap.get(*ri)?.as_ref()?.clone();
        match (l, r) {
            (Object::TypeUnpack(a), Object::TypeUnpack(b)) => Some(self.equal(&a, &b)),
            (Object::UnpackedAlias(a), Object::UnpackedAlias(b)) => Some(self.equal(&a, &b)),
            (
                Object::ParamSpecMarker {
                    parameter: a,
                    kind: ak,
                },
                Object::ParamSpecMarker {
                    parameter: b,
                    kind: bk,
                },
            ) => Some(Ok(ak == bk && a.same_identity(&b))),
            (
                Object::ForwardRef { arg: a, module: am },
                Object::ForwardRef { arg: b, module: bm },
            ) => Some(if a != b {
                Ok(false)
            } else {
                self.equal(&am, &bm)
            }),
            (Object::TypeUnion { args: a, .. }, Object::TypeUnion { args: b, .. }) => {
                Some((|| {
                    if a.len() != b.len() {
                        return Ok(false);
                    }
                    for value in &a {
                        if !self.contains_vec(&b, value)? {
                            return Ok(false);
                        }
                    }
                    Ok(true)
                })())
            }
            _ => None,
        }
    }
    fn typing_repr(&mut self, value: &Value) -> Option<PyResult<String>> {
        let Value::Obj(index) = value else {
            return None;
        };
        let object = self.heap.get(*index)?.as_ref()?.clone();
        Some(match object {
            Object::TypeParameter(parameter) => Ok(format!(
                "{}{}",
                if parameter.kind == "typevartuple" || parameter.infer_variance {
                    ""
                } else if parameter.covariant {
                    "+"
                } else if parameter.contravariant {
                    "-"
                } else {
                    "~"
                },
                parameter.name
            )),
            Object::TypeAlias { name, .. } => Ok(name),
            Object::TypeUnpack(inner) => self
                .generic_repr_item(&inner)
                .map(|value| format!("typing.Unpack[{}]", value)),
            Object::UnpackedAlias(inner) => self.repr(&inner).map(|value| format!("*{}", value)),
            Object::ParamSpecMarker { parameter, kind } => self
                .getattr(parameter, "__name__")
                .and_then(|name| self.str_value(&name))
                .map(|name| format!("{}.{}", name, kind)),
            Object::TypeEvaluator(value) => self
                .repr(&value)
                .map(|value| format!("<constevaluator {}>", value)),
            Object::ForwardRef { arg, module } => {
                let arg = text_repr_str(&arg);
                if matches!(module, Value::None) {
                    Ok(format!("ForwardRef({})", arg))
                } else {
                    self.repr(&module)
                        .map(|module| format!("ForwardRef({}, module={})", arg, module))
                }
            }
            Object::TypeUnion { args, .. } => (|| {
                let mut parts = Vec::new();
                for value in args {
                    parts.push(self.generic_repr_item(&value)?);
                }
                Ok(parts.join(" | "))
            })(),
            _ => Err(pyerr("__typing_not_handled__", "")),
        })
        .filter(|result| !matches!(result,Err(error)if error.kind=="__typing_not_handled__"))
    }
    fn typing_constructor(
        &mut self,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
        caller: Option<&Frame>,
    ) -> Option<PyResult<Value>> {
        if !matches!(
            name,
            "typing.TypeVar"
                | "typing.ParamSpec"
                | "typing.TypeVarTuple"
                | "typing.TypeAliasType"
                | "typing.ParamSpecArgs"
                | "typing.ParamSpecKwargs"
                | "typing.ForwardRef"
                | "NoDefaultType"
        ) {
            return None;
        }
        Some((|| {
            if name == "NoDefaultType" {
                if !args.is_empty() || !kwargs.is_empty() {
                    return Err(pyerr("TypeError", "NoDefaultType takes no arguments"));
                }
                return Ok(Value::Builtin("typing.NoDefault".into()));
            }
            if matches!(name, "typing.ParamSpecArgs" | "typing.ParamSpecKwargs") {
                if args.len() != 1 || !kwargs.is_empty() {
                    return Err(pyerr("TypeError", "expected one argument"));
                }
                return Ok(self.obj_value(Object::ParamSpecMarker {
                    parameter: args[0].clone(),
                    kind: if name.ends_with("Args") {
                        "args"
                    } else {
                        "kwargs"
                    }
                    .into(),
                }));
            }
            if name == "typing.ForwardRef" {
                let values = codec_bind(
                    "ForwardRef",
                    args,
                    kwargs,
                    &["arg", "is_argument", "module", "is_class", "owner"],
                )?;
                let arg = match values[0].clone() {
                    Some(Value::Str(arg)) => arg.to_string(),
                    _ => return Err(pyerr("TypeError", "Forward reference must be a string")),
                };
                return Ok(self.obj_value(Object::ForwardRef {
                    arg,
                    module: values[2].clone().unwrap_or(Value::None),
                }));
            }
            if name == "typing.TypeAliasType" {
                if args.len() != 2 {
                    return Err(pyerr(
                        "TypeError",
                        "TypeAliasType() takes exactly 2 positional arguments",
                    ));
                }
                let alias_name = match &args[0] {
                    Value::Str(name) => name.to_string(),
                    _ => {
                        return Err(pyerr(
                            "TypeError",
                            "TypeAliasType() argument 'name' must be str",
                        ))
                    }
                };
                let mut params = None;
                for (key, value) in kwargs {
                    if key != "type_params" {
                        return Err(pyerr(
                            "TypeError",
                            format!(
                                "TypeAliasType() got an unexpected keyword argument '{}'",
                                key
                            ),
                        ));
                    }
                    params = Some(value);
                }
                let params = params.unwrap_or_else(|| self.obj_value(Object::Tuple(Vec::new())));
                if !matches!(&params,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_))))
                {
                    return Err(pyerr("TypeError", "type_params must be a tuple"));
                }
                for value in self.to_vec(params.clone())? {
                    if self.type_parameter_kind(&value).is_none() {
                        return Err(pyerr(
                            "TypeError",
                            "type_params must contain only type parameters",
                        ));
                    }
                }
                let module = caller
                    .and_then(|frame| self.ns_get(frame.globals, "__name__"))
                    .unwrap_or_else(|| Value::Str("__main__".into()));
                return Ok(self.obj_value(Object::TypeAlias {
                    name: alias_name,
                    module,
                    params,
                    value: TypeLazy::constant(args[1].clone()),
                }));
            }
            let mut supplied_name = args.first().cloned();
            let mut bound = None;
            let mut default = Value::Builtin("typing.NoDefault".into());
            let mut covariance = false;
            let mut contravariance = false;
            let mut infer = false;
            for (key, value) in kwargs {
                match key.as_str() {
                    "name" => {
                        if supplied_name.is_some() {
                            return Err(pyerr(
                                "TypeError",
                                "got multiple values for argument 'name'",
                            ));
                        }
                        supplied_name = Some(value);
                    }
                    "bound" if name != "typing.TypeVarTuple" => bound = Some(value),
                    "default" => default = value,
                    "covariant" if name != "typing.TypeVarTuple" => {
                        covariance = self.truth(&value)?
                    }
                    "contravariant" if name != "typing.TypeVarTuple" => {
                        contravariance = self.truth(&value)?
                    }
                    "infer_variance" if name != "typing.TypeVarTuple" => {
                        infer = self.truth(&value)?
                    }
                    _ => {
                        return Err(pyerr(
                            "TypeError",
                            format!("{}() got an unexpected keyword argument '{}'", name, key),
                        ))
                    }
                }
            }
            let parameter_name = match supplied_name {
                Some(Value::Str(name)) => name.to_string(),
                Some(_) => return Err(pyerr("TypeError", "name must be a str")),
                None => return Err(pyerr("TypeError", "missing required argument 'name'")),
            };
            let kind = match name {
                "typing.ParamSpec" => "paramspec",
                "typing.TypeVarTuple" => "typevartuple",
                _ => "typevar",
            };
            if kind != "typevar" && args.len() > 1 {
                return Err(pyerr(
                    "TypeError",
                    "only one positional argument is accepted",
                ));
            }
            if covariance && contravariance {
                return Err(pyerr("ValueError", "Bivariant types are not supported."));
            }
            if infer && (covariance || contravariance) {
                return Err(pyerr(
                    "ValueError",
                    "Variance cannot be specified with infer_variance.",
                ));
            }
            let constraints = if args.len() > 1 {
                args[1..].to_vec()
            } else {
                Vec::new()
            };
            if constraints.len() == 1 {
                return Err(pyerr("TypeError", "A single constraint is not allowed"));
            }
            if !constraints.is_empty()
                && bound
                    .as_ref()
                    .is_some_and(|value| !matches!(value, Value::None))
            {
                return Err(pyerr(
                    "TypeError",
                    "Constraints cannot be combined with bound=...",
                ));
            }
            let bound = if let Some(bound) = bound {
                if matches!(bound, Value::None) {
                    Value::None
                } else {
                    self.type_argument(bound)?
                }
            } else if kind == "paramspec" {
                Value::Builtin("NoneType".into())
            } else {
                Value::None
            };
            let constraints = self.obj_value(Object::Tuple(constraints));
            let attrs = self.alloc(Object::Dict(Vec::new()));
            let module = caller
                .and_then(|frame| self.ns_get(frame.globals, "__name__"))
                .unwrap_or_else(|| Value::Str("__main__".into()));
            Ok(self.obj_value(Object::TypeParameter(TypeParameter {
                name: parameter_name,
                kind: kind.into(),
                module,
                attrs,
                covariant: covariance,
                contravariant: contravariance,
                infer_variance: infer,
                bound: TypeLazy::constant(bound),
                constraints: TypeLazy::constant(constraints),
                default: TypeLazy::constant(default),
            })))
        })())
    }
}
