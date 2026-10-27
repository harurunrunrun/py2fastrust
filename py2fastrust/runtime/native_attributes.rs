// Original native attribute resolution for explicit class/instance/super
// access. Owned-member names and descriptor categories follow Python 3.14;
// the override-only class_lookup remains separate for payload proof checks.
fn native_attribute_kind(owner: &str, name: &str) -> Option<&'static str> {
    match (owner, name) {
        ("dict", "__new__") => Some("new"),
        (
            "dict",
            "__repr__" | "__lt__" | "__le__" | "__eq__" | "__ne__" | "__gt__" | "__ge__"
            | "__iter__" | "__init__" | "__or__" | "__ror__" | "__ior__" | "__len__"
            | "__setitem__" | "__delitem__",
        ) => Some("wrapper"),
        ("dict", "__hash__") => Some("none"),
        (
            "dict",
            "__getitem__" | "__contains__" | "__sizeof__" | "get" | "setdefault" | "pop"
            | "popitem" | "keys" | "items" | "values" | "update" | "clear" | "copy"
            | "__reversed__",
        ) => Some("method"),
        ("dict", "fromkeys" | "__class_getitem__") => Some("class"),
        ("list", "__new__") => Some("new"),
        (
            "list",
            "__repr__" | "__lt__" | "__le__" | "__eq__" | "__ne__" | "__gt__" | "__ge__"
            | "__iter__" | "__init__" | "__len__" | "__setitem__" | "__delitem__" | "__add__"
            | "__mul__" | "__rmul__" | "__contains__" | "__iadd__" | "__imul__",
        ) => Some("wrapper"),
        ("list", "__hash__") => Some("none"),
        (
            "list",
            "__getitem__" | "__reversed__" | "__sizeof__" | "clear" | "copy" | "append" | "insert"
            | "extend" | "pop" | "remove" | "index" | "count" | "reverse" | "sort",
        ) => Some("method"),
        ("list", "__class_getitem__") => Some("class"),
        ("tuple", "__new__") => Some("new"),
        (
            "tuple",
            "__repr__" | "__hash__" | "__lt__" | "__le__" | "__eq__" | "__ne__" | "__gt__"
            | "__ge__" | "__iter__" | "__len__" | "__getitem__" | "__add__" | "__mul__"
            | "__rmul__" | "__contains__",
        ) => Some("wrapper"),
        ("tuple", "__getnewargs__" | "index" | "count") => Some("method"),
        ("tuple", "__class_getitem__") => Some("class"),
        ("set", "__new__") => Some("new"),
        (
            "set",
            "__repr__" | "__lt__" | "__le__" | "__eq__" | "__ne__" | "__gt__" | "__ge__"
            | "__iter__" | "__init__" | "__sub__" | "__rsub__" | "__and__" | "__rand__" | "__xor__"
            | "__rxor__" | "__or__" | "__ror__" | "__isub__" | "__iand__" | "__ixor__" | "__ior__"
            | "__len__",
        ) => Some("wrapper"),
        ("set", "__hash__") => Some("none"),
        (
            "set",
            "__contains__"
            | "add"
            | "clear"
            | "copy"
            | "discard"
            | "difference"
            | "difference_update"
            | "intersection"
            | "intersection_update"
            | "isdisjoint"
            | "issubset"
            | "issuperset"
            | "pop"
            | "__reduce__"
            | "remove"
            | "__sizeof__"
            | "symmetric_difference"
            | "symmetric_difference_update"
            | "union"
            | "update",
        ) => Some("method"),
        ("set", "__class_getitem__") => Some("class"),
        ("frozenset", "__new__") => Some("new"),
        (
            "frozenset",
            "__repr__" | "__hash__" | "__lt__" | "__le__" | "__eq__" | "__ne__" | "__gt__"
            | "__ge__" | "__iter__" | "__sub__" | "__rsub__" | "__and__" | "__rand__" | "__xor__"
            | "__rxor__" | "__or__" | "__ror__" | "__len__",
        ) => Some("wrapper"),
        (
            "frozenset",
            "__contains__"
            | "copy"
            | "difference"
            | "intersection"
            | "isdisjoint"
            | "issubset"
            | "issuperset"
            | "__reduce__"
            | "__sizeof__"
            | "symmetric_difference"
            | "union",
        ) => Some("method"),
        ("frozenset", "__class_getitem__") => Some("class"),
        ("str", "__new__") => Some("new"),
        (
            "str",
            "__repr__" | "__hash__" | "__str__" | "__lt__" | "__le__" | "__eq__" | "__ne__"
            | "__gt__" | "__ge__" | "__iter__" | "__mod__" | "__rmod__" | "__len__" | "__getitem__"
            | "__add__" | "__mul__" | "__rmul__" | "__contains__",
        ) => Some("wrapper"),
        (
            "str",
            "encode" | "replace" | "split" | "rsplit" | "join" | "capitalize" | "casefold"
            | "title" | "center" | "count" | "expandtabs" | "find" | "partition" | "index"
            | "ljust" | "lower" | "lstrip" | "rfind" | "rindex" | "rjust" | "rstrip" | "rpartition"
            | "splitlines" | "strip" | "swapcase" | "translate" | "upper" | "startswith"
            | "endswith" | "removeprefix" | "removesuffix" | "isascii" | "islower" | "isupper"
            | "istitle" | "isspace" | "isdecimal" | "isdigit" | "isnumeric" | "isalpha" | "isalnum"
            | "isidentifier" | "isprintable" | "zfill" | "format" | "format_map" | "__format__"
            | "__sizeof__" | "__getnewargs__",
        ) => Some("method"),
        ("str", "maketrans") => Some("static"),
        ("int", "__new__") => Some("new"),
        (
            "int",
            "__repr__" | "__hash__" | "__lt__" | "__le__" | "__eq__" | "__ne__" | "__gt__"
            | "__ge__" | "__add__" | "__radd__" | "__sub__" | "__rsub__" | "__mul__" | "__rmul__"
            | "__mod__" | "__rmod__" | "__divmod__" | "__rdivmod__" | "__pow__" | "__rpow__"
            | "__neg__" | "__pos__" | "__abs__" | "__bool__" | "__invert__" | "__lshift__"
            | "__rlshift__" | "__rshift__" | "__rrshift__" | "__and__" | "__rand__" | "__xor__"
            | "__rxor__" | "__or__" | "__ror__" | "__int__" | "__float__" | "__floordiv__"
            | "__rfloordiv__" | "__truediv__" | "__rtruediv__" | "__index__",
        ) => Some("wrapper"),
        (
            "int",
            "conjugate" | "bit_length" | "bit_count" | "to_bytes" | "as_integer_ratio"
            | "__trunc__" | "__floor__" | "__ceil__" | "__round__" | "__getnewargs__"
            | "__format__" | "__sizeof__" | "is_integer",
        ) => Some("method"),
        ("int", "from_bytes") => Some("class"),
        ("int", "real" | "imag" | "numerator" | "denominator") => Some("member"),
        ("complex", "__new__") => Some("new"),
        (
            "complex",
            "__repr__" | "__hash__" | "__lt__" | "__le__" | "__eq__" | "__ne__" | "__gt__"
            | "__ge__" | "__add__" | "__radd__" | "__sub__" | "__rsub__" | "__mul__" | "__rmul__"
            | "__pow__" | "__rpow__" | "__neg__" | "__pos__" | "__abs__" | "__bool__"
            | "__truediv__" | "__rtruediv__",
        ) => Some("wrapper"),
        ("complex", "from_number") => Some("class"),
        ("complex", "conjugate" | "__complex__" | "__getnewargs__" | "__format__") => {
            Some("method")
        }
        ("complex", "real" | "imag") => Some("member"),
        ("object", "__new__") => Some("new"),
        (
            "object",
            "__repr__" | "__hash__" | "__str__" | "__getattribute__" | "__setattr__"
            | "__delattr__" | "__lt__" | "__le__" | "__eq__" | "__ne__" | "__gt__" | "__ge__"
            | "__init__",
        ) => Some("wrapper"),
        (
            "object",
            "__reduce_ex__" | "__reduce__" | "__getstate__" | "__format__" | "__sizeof__"
            | "__dir__",
        ) => Some("method"),
        ("object", "__subclasshook__" | "__init_subclass__") => Some("class"),
        ("object", "__class__") => Some("member"),
        ("type", "__new__") => Some("new"),
        (
            "type",
            "__repr__" | "__call__" | "__getattribute__" | "__setattr__" | "__delattr__"
            | "__init__" | "__or__" | "__ror__",
        ) => Some("wrapper"),
        (
            "type",
            "mro" | "__subclasses__" | "__instancecheck__" | "__subclasscheck__" | "__dir__"
            | "__sizeof__",
        ) => Some("method"),
        ("type", "__prepare__") => Some("class"),
        (
            "type",
            "__basicsize__"
            | "__itemsize__"
            | "__flags__"
            | "__weakrefoffset__"
            | "__base__"
            | "__dictoffset__"
            | "__name__"
            | "__qualname__"
            | "__bases__"
            | "__mro__"
            | "__module__"
            | "__abstractmethods__"
            | "__dict__"
            | "__text_signature__"
            | "__annotations__"
            | "__annotate__"
            | "__type_params__",
        ) => Some("member"),
        _ => None,
    }
}
fn native_method_implemented(owner: &str, name: &str) -> bool {
    if [
        "__repr__",
        "__str__",
        "__iter__",
        "__len__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
        "__contains__",
        "__reversed__",
        "__format__",
    ]
    .contains(&name)
    {
        return true;
    }
    match owner {
        "dict" => [
            "get",
            "setdefault",
            "pop",
            "popitem",
            "keys",
            "items",
            "values",
            "update",
            "clear",
            "copy",
        ]
        .contains(&name),
        "list" => [
            "append", "extend", "insert", "pop", "remove", "clear", "index", "count", "sort",
            "reverse", "copy",
        ]
        .contains(&name),
        "tuple" => ["index", "count"].contains(&name),
        "set" => !name.starts_with("__"),
        "frozenset" => name != "__sizeof__",
        "str" => {
            !name.starts_with("__")
                && ![
                    "translate",
                    "format_map",
                    "maketrans",
                    "isascii",
                    "istitle",
                    "isprintable",
                    "expandtabs",
                ]
                .contains(&name)
        }
        "int" => [
            "bit_length",
            "bit_count",
            "__index__",
            "__int__",
            "conjugate",
        ]
        .contains(&name),
        "complex" => true,
        _ => false,
    }
}
fn native_exception_owns(owner: &str, name: &str) -> bool {
    match name {
        "__new__" => matches!(
            owner,
            "ArithmeticError"
                | "AssertionError"
                | "BaseException"
                | "BaseExceptionGroup"
                | "BufferError"
                | "BytesWarning"
                | "DeprecationWarning"
                | "EOFError"
                | "EncodingWarning"
                | "Exception"
                | "FloatingPointError"
                | "FutureWarning"
                | "GeneratorExit"
                | "ImportWarning"
                | "IndexError"
                | "KeyboardInterrupt"
                | "LookupError"
                | "MemoryError"
                | "NotImplementedError"
                | "OSError"
                | "OverflowError"
                | "PendingDeprecationWarning"
                | "PythonFinalizationError"
                | "RecursionError"
                | "ReferenceError"
                | "ResourceWarning"
                | "RuntimeError"
                | "RuntimeWarning"
                | "StopAsyncIteration"
                | "SyntaxWarning"
                | "SystemError"
                | "TypeError"
                | "UnicodeDecodeError"
                | "UnicodeEncodeError"
                | "UnicodeError"
                | "UnicodeTranslateError"
                | "UnicodeWarning"
                | "UserWarning"
                | "ValueError"
                | "Warning"
                | "ZeroDivisionError"
        ),
        "__init__" => matches!(
            owner,
            "AttributeError"
                | "BaseException"
                | "BaseExceptionGroup"
                | "ImportError"
                | "NameError"
                | "OSError"
                | "StopIteration"
                | "SyntaxError"
                | "SystemExit"
                | "UnicodeDecodeError"
                | "UnicodeEncodeError"
                | "UnicodeTranslateError"
        ),
        "__str__" => matches!(
            owner,
            "BaseException"
                | "BaseExceptionGroup"
                | "ImportError"
                | "KeyError"
                | "OSError"
                | "SyntaxError"
                | "UnicodeDecodeError"
                | "UnicodeEncodeError"
                | "UnicodeTranslateError"
        ),
        "__repr__" => matches!(owner, "BaseException" | "BaseExceptionGroup"),
        "derive" => matches!(owner, "BaseExceptionGroup"),
        "split" => matches!(owner, "BaseExceptionGroup"),
        "subgroup" => matches!(owner, "BaseExceptionGroup"),
        "add_note" => matches!(owner, "BaseException"),
        "with_traceback" => matches!(owner, "BaseException"),
        _ => false,
    }
}
fn native_attribute_parts(value: &Value) -> Option<(&str, &str, &str)> {
    let Value::Builtin(value) = value else {
        return None;
    };
    let value = value.strip_prefix("native_attr:")?;
    let mut parts = value.splitn(3, ':');
    Some((parts.next()?, parts.next()?, parts.next()?))
}
impl Runtime {
    fn native_own_attribute(&self, base: &Value, name: &str) -> Option<Value> {
        let Value::Builtin(owner) = base else {
            return None;
        };
        let kind = native_attribute_kind(owner, name)?;
        Some(if kind == "none" {
            Value::None
        } else {
            Value::Builtin(format!("native_attr:{kind}:{owner}:{name}"))
        })
    }
    fn class_own_attribute(&self, base: &Value, name: &str) -> Option<Value> {
        if let Value::Type(owner) = base {
            if native_exception_owns(owner, name) {
                return Some(Value::Builtin(format!("exception_type:{owner}:{name}")));
            }
        }
        if let Value::Obj(index) = base {
            if let Some(Object::Class(class)) = self.heap.get(*index).and_then(Option::as_ref) {
                return self.ns_get(class.attrs, name);
            }
        }
        self.native_own_attribute(base, name)
    }
    fn class_attribute_lookup(&self, class: &Value, name: &str) -> Option<Value> {
        for base in self.class_mro(class, 0)? {
            if let Some(value) = self.class_own_attribute(&base, name) {
                return Some(value);
            }
        }
        None
    }
    fn native_is_class(&self, value: &Value) -> bool {
        matches!(value, Value::Type(_))
            || matches!(value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))))
            || matches!(value,Value::Builtin(owner)if self.typename(value)=="type"||owner=="frozenset")
    }
    fn native_receiver_class(&self, value: &Value) -> Value {
        self.object_class(value)
            .unwrap_or_else(|| Value::Builtin(self.typename(value)))
    }
    fn native_validate_receiver(&mut self, owner: &str, value: &Value) -> PyResult<()> {
        if self.is_subclass(
            &self.native_receiver_class(value),
            &Value::Builtin(owner.into()),
        )? {
            Ok(())
        } else {
            Err(pyerr(
                "TypeError",
                format!("descriptor requires a '{owner}' object"),
            ))
        }
    }
    fn attribute_is_data(&self, value: &Value) -> bool {
        if let Some((kind, _, _)) = native_attribute_parts(value) {
            return kind == "member";
        }
        if let Value::Obj(index) = value {
            if matches!(
                self.heap.get(*index).and_then(Option::as_ref),
                Some(Object::Slot { .. } | Object::Property { .. })
            ) {
                return true;
            }
            if let Some(class) = self.object_class(value) {
                return self.class_lookup(&class, "__set__", 0).is_some()
                    || self.class_lookup(&class, "__delete__", 0).is_some();
            }
        }
        false
    }
    fn bind_native_attribute(
        &mut self,
        value: Value,
        instance: Option<Value>,
        class: Value,
    ) -> Option<PyResult<Value>> {
        let (kind, owner, name) = native_attribute_parts(&value)?;
        let (kind, owner, name) = (kind.to_owned(), owner.to_owned(), name.to_owned());
        Some((|| match kind.as_str() {
            "new" | "static" => Ok(value),
            "class" => {
                if !self.is_subclass(&class, &Value::Builtin(owner.clone()))? {
                    return Err(pyerr(
                        "TypeError",
                        "classmethod descriptor requires a subtype",
                    ));
                }
                Ok(self.obj_value(Object::Bound(value, class)))
            }
            "member" => {
                if let Some(instance) = instance {
                    self.native_validate_receiver(&owner, &instance)?;
                    let payload = self
                        .native_payload(&instance)
                        .unwrap_or_else(|| instance.clone());
                    match (owner.as_str(), name.as_str(), &payload) {
                        ("complex", "real", Value::Complex(number)) => {
                            Ok(Value::Float(number.real.into()))
                        }
                        ("complex", "imag", Value::Complex(number)) => {
                            Ok(Value::Float(number.imag.into()))
                        }
                        ("int", "real" | "numerator", Value::Int(_)) => Ok(payload),
                        ("int", "imag", _) => Ok(Value::Int(Int::from_i128(0).into())),
                        ("int", "denominator", _) => Ok(Value::Int(Int::from_i128(1).into())),
                        _ => Err(pyerr(
                            "NotImplementedError",
                            format!("native member {owner}.{name}"),
                        )),
                    }
                } else {
                    Ok(value)
                }
            }
            _ => {
                if let Some(instance) = instance {
                    self.native_validate_receiver(&owner, &instance)?;
                    Ok(self.obj_value(Object::Bound(value, instance)))
                } else {
                    Ok(value)
                }
            }
        })())
    }
    fn native_attribute_meta(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        let (kind, owner, method) = native_attribute_parts(&value)?;
        let (kind, owner, method) = (kind.to_owned(), owner.to_owned(), method.to_owned());
        Some(match name {
            "__name__" => Ok(Value::Str(method.into())),
            "__qualname__" => Ok(Value::Str(format!("{owner}.{method}").into())),
            "__module__" if kind == "new" => Ok(Value::None),
            "__self__" if kind == "new" => Ok(Value::Builtin(owner)),
            "__objclass__" if kind != "new" && kind != "static" => Ok(Value::Builtin(owner)),
            "__class__" => Ok(Value::Builtin(
                match kind.as_str() {
                    "new" => "builtin_function_or_method",
                    "wrapper" => "wrapper_descriptor",
                    "class" => "classmethod_descriptor",
                    "member" => "getset_descriptor",
                    _ => "method_descriptor",
                }
                .into(),
            )),
            "__get__" if kind != "new" && kind != "static" => Ok(self.obj_value(Object::Bound(
                Value::Builtin("native_attr_bind".into()),
                value,
            ))),
            "__set__" | "__delete__" if kind == "member" => Ok(self.obj_value(Object::Bound(
                Value::Builtin("native_attr_readonly".into()),
                value,
            ))),
            _ => Err(pyerr(
                "AttributeError",
                format!("native descriptor has no attribute '{name}'"),
            )),
        })
    }
    fn native_attribute_call(
        &mut self,
        value: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        let (kind, owner, name) = native_attribute_parts(&value)
            .ok_or_else(|| pyerr("TypeError", "expected native attribute"))?;
        let (kind, owner, name) = (kind.to_owned(), owner.to_owned(), name.to_owned());
        if kind == "new" {
            let class = args
                .first()
                .cloned()
                .ok_or_else(|| pyerr("TypeError", "__new__ requires a type argument"))?;
            if !self.native_is_class(&class) {
                return Err(pyerr("TypeError", "__new__ requires a type argument"));
            }
            if owner == "int" && matches!(&class,Value::Builtin(name)if name=="bool") {
                return Err(pyerr("TypeError", "int.__new__ is not safe for bool"));
            }
            if owner == "object" {
                if !self.is_subclass(&class, &Value::Builtin("object".into()))? {
                    return Err(pyerr("TypeError", "object.__new__ requires a type"));
                }
                let native = self
                    .class_mro(&class, 0)
                    .unwrap_or_default()
                    .iter()
                    .any(|base| {
                        matches!(base,Value::Builtin(name)if ["tuple","list","dict","set","frozenset","str","int","complex","float","bytes","bool","type"].contains(&name.as_str()))
                            || matches!(base, Value::Type(_))
                    });
                if native {
                    return Err(pyerr(
                        "TypeError",
                        "object.__new__ is not safe for this native subtype",
                    ));
                }
                if args.len() > 1 || !kwargs.is_empty() {
                    let new = self.class_attribute_lookup(&class, "__new__");
                    let init = self.class_attribute_lookup(&class, "__init__");
                    if !new.as_ref().is_some_and(|new| new.same_identity(&value))
                        || matches!(init,Some(Value::Builtin(ref name))if name=="native_attr:wrapper:object:__init__")
                    {
                        return Err(pyerr(
                            "TypeError",
                            "object.__new__ takes exactly one argument",
                        ));
                    }
                }
                let attrs = self.alloc(Object::Dict(Vec::new()));
                return Ok(self.obj_value(Object::Instance { class, attrs }));
            }
            if owner == "type" {
                return self.construct_class(class, args[1..].to_vec(), kwargs);
            }
            return self.builtin_instance_new(&owner, class, args[1..].to_vec(), kwargs);
        }
        if kind == "class" {
            let class = args
                .first()
                .cloned()
                .ok_or_else(|| pyerr("TypeError", "classmethod requires a type"))?;
            if !self.is_subclass(&class, &Value::Builtin(owner.clone()))? {
                return Err(pyerr(
                    "TypeError",
                    "classmethod descriptor requires a subtype",
                ));
            }
            match name.as_str() {
                "__class_getitem__" => {
                    if args.len() != 2 || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "__class_getitem__ takes one argument"));
                    }
                    return self.generic_alias(class, args[1].clone());
                }
                "__init_subclass__" => {
                    if args.len() != 1 || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "__init_subclass__ takes no arguments"));
                    }
                    return Ok(Value::None);
                }
                "__prepare__" if owner == "type" => {
                    if args.len() != 3 {
                        return Err(pyerr("TypeError", "__prepare__ needs name and bases"));
                    }
                    return Ok(self.obj_value(Object::Dict(Vec::new())));
                }
                "from_number" if owner == "complex" => {
                    return self.complex_from_number(args, kwargs)
                }
                "fromkeys" if owner == "dict" => {
                    if !(2..=3).contains(&args.len()) || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "fromkeys expected 1 or 2 arguments"));
                    }
                    let mapping = self.call(class, Vec::new(), Vec::new(), None)?;
                    return self.view_rooted(
                        vec![mapping.clone(), args[1].clone()],
                        |runtime, root| {
                            let iterator = runtime.iter(args[1].clone())?;
                            runtime.roots[root].push(iterator.clone());
                            let default = args.get(2).cloned().unwrap_or(Value::None);
                            runtime.roots[root].push(default.clone());
                            while let Some(key) = runtime.next(iterator.clone())? {
                                runtime.setitem(mapping.clone(), key, default.clone())?;
                            }
                            Ok(mapping)
                        },
                    );
                }
                _ => {
                    return Err(pyerr(
                        "NotImplementedError",
                        format!("native class method {owner}.{name}"),
                    ))
                }
            }
        }
        let receiver = args.first().cloned().ok_or_else(|| {
            pyerr(
                "TypeError",
                format!("descriptor {owner}.{name} requires an instance"),
            )
        })?;
        self.native_validate_receiver(&owner, &receiver)?;
        let rest = args[1..].to_vec();
        if name == "__init__" {
            if ["list", "dict", "set"].contains(&owner.as_str()) {
                return self.builtin_instance_init(&owner, receiver, rest, kwargs);
            }
            if owner == "object" && (!rest.is_empty() || !kwargs.is_empty()) {
                let class = self.native_receiver_class(&receiver);
                let init = self.class_attribute_lookup(&class, "__init__");
                let new = self.class_attribute_lookup(&class, "__new__");
                if !init.as_ref().is_some_and(|init| init.same_identity(&value))
                    || matches!(new,Some(Value::Builtin(ref name))if name=="native_attr:new:object:__new__")
                {
                    return Err(pyerr(
                        "TypeError",
                        "object.__init__ takes exactly one argument",
                    ));
                }
            }
            return Ok(Value::None);
        }
        if owner == "type" {
            match name.as_str() {
                "__getattribute__" => {
                    if rest.len() != 1 || !kwargs.is_empty() {
                        return Err(pyerr(
                            "TypeError",
                            "__getattribute__ takes one attribute name",
                        ));
                    }
                    let key = self.str_value(&rest[0])?;
                    return self.getattr_default(receiver, &key);
                }
                "__setattr__" => {
                    if rest.len() != 2 || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "__setattr__ takes name and value"));
                    }
                    let key = self.str_value(&rest[0])?;
                    self.setattr_default(receiver, &key, rest[1].clone())?;
                    return Ok(Value::None);
                }
                "__delattr__" => {
                    if rest.len() != 1 || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "__delattr__ takes one attribute name"));
                    }
                    let key = self.str_value(&rest[0])?;
                    self.delattr_default(receiver, &key)?;
                    return Ok(Value::None);
                }
                "mro" => {
                    if !rest.is_empty() || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "mro takes no arguments"));
                    }
                    let mro = self
                        .class_mro(&receiver, 0)
                        .ok_or_else(|| pyerr("TypeError", "invalid class MRO"))?;
                    return Ok(self.obj_value(Object::List(mro)));
                }
                _ => {}
            }
        }
        if owner == "object" {
            match name.as_str() {
                "__getattribute__" | "__setattr__" | "__delattr__" => {
                    return self.builtin(&format!("type_method:object:{name}"), args, kwargs, None)
                }
                "__str__" => {
                    if !rest.is_empty() || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "__str__ takes no arguments"));
                    }
                    return self.repr(&receiver).map(|s| Value::Str(s.into()));
                }
                "__eq__" | "__ne__" => {
                    if rest.len() != 1 || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "comparison requires one argument"));
                    }
                    return Ok(if receiver.same_identity(&rest[0]) {
                        Value::Bool(name == "__eq__")
                    } else {
                        Value::Builtin("NotImplemented".into())
                    });
                }
                _ => {
                    return Err(pyerr(
                        "NotImplementedError",
                        format!("native descriptor object.{name}"),
                    ))
                }
            }
        }
        // These primitive slots already have exact str implementations. Keep
        // their base-descriptor behavior when native MRO lookup selects them.
        if owner == "str"
            && ["__hash__", "__eq__", "__ne__", "__str__", "__repr__"].contains(&name.as_str())
        {
            let subtype = self.native_payload(&receiver);
            let payload = subtype.clone().unwrap_or(receiver);
            let payload = if name == "__str__" && subtype.is_some() {
                payload.fresh_primitive()
            } else {
                payload
            };
            return self.keyword_str_protocol(payload, &name, rest, kwargs).unwrap();
        }
        if owner == "dict" && name == "__getitem__" {
            if rest.len() != 1 || !kwargs.is_empty() {
                return Err(pyerr("TypeError", "__getitem__ takes one argument"));
            }
            return self.collection_dict_getitem(receiver, rest[0].clone());
        }
        if owner == "dict" && name == "copy" {
            if !rest.is_empty() || !kwargs.is_empty() {
                return Err(pyerr("TypeError", "copy takes no arguments"));
            }
            return self.dictionary_copy(receiver);
        }
        if !native_method_implemented(&owner, &name) {
            return Err(pyerr(
                "NotImplementedError",
                format!("native descriptor {owner}.{name}"),
            ));
        }
        if ["__iter__", "__len__", "__reversed__"].contains(&name.as_str())
            && (!rest.is_empty() || !kwargs.is_empty())
        {
            return Err(pyerr("TypeError", "descriptor takes no arguments"));
        }
        if ["__getitem__", "__delitem__", "__contains__"].contains(&name.as_str())
            && (rest.len() != 1 || !kwargs.is_empty())
        {
            return Err(pyerr("TypeError", "descriptor takes one argument"));
        }
        if name == "__setitem__" && (rest.len() != 2 || !kwargs.is_empty()) {
            return Err(pyerr("TypeError", "descriptor takes two arguments"));
        }
        if name == "__reversed__" {
            let result = self.builtin(
                "reversed",
                vec![self
                    .native_payload(&receiver)
                    .unwrap_or_else(|| receiver.clone())],
                Vec::new(),
                None,
            )?;
            return Ok(self.collection_keep(result, receiver));
        }
        let payload = self
            .native_payload(&receiver)
            .unwrap_or_else(|| receiver.clone());
        let payload = if owner == "int"
            && self.native_payload(&receiver).is_some()
            && ["__int__", "__index__", "conjugate"].contains(&name.as_str())
        {
            payload.fresh_primitive()
        } else {
            payload
        };
        let payload = if owner == "int" && matches!(payload, Value::Bool(_)) {
            Value::Int(self.as_int(&payload)?.into())
        } else {
            payload
        };
        if name == "__repr__" || name == "__str__" {
            if !rest.is_empty() || !kwargs.is_empty() {
                return Err(pyerr("TypeError", "string conversion takes no arguments"));
            }
            return (if name == "__repr__" && ["set", "frozenset"].contains(&owner.as_str()) {
                self.frozen_repr(&receiver, &mut Vec::new()).map(|body| {
                    if owner == "set" && self.native_payload(&receiver).is_some() {
                        let class = self.typename(&receiver);
                        if body == "set()" {
                            return format!("{class}()");
                        }
                        if body.starts_with('{') {
                            return format!("{class}({body})");
                        }
                    }
                    body
                })
            } else if name == "__repr__" {
                self.repr(&payload)
            } else {
                self.str_value(&payload)
            })
            .map(|s| Value::Str(s.into()));
        }
        let result = self.method(&name, payload, rest, kwargs)?;
        Ok(self.collection_keep(result, receiver))
    }
}
