// Original native attribute resolution for explicit class/instance/super
// access. Owned-member names and descriptor categories follow Python 3.14;
// the override-only class_lookup remains separate for payload proof checks.
fn native_attribute_kind(owner: &str, name: &str) -> Option<&'static str> {
    if let Some(kind)=buffer_native_kind(owner,name){return Some(kind);}
    if let Some(kind)=stdlib_attribute_kind(owner,name) {return Some(kind);}
    match (owner, name) {
        ("cell", "__new__")=>Some("new"),
        ("cell", "__repr__"|"__eq__"|"__ne__"|"__lt__"|"__le__"|"__gt__"|"__ge__")=>Some("wrapper"),
        ("cell", "cell_contents")=>Some("member"),
        ("cell", "__hash__")=>Some("none"),
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
        ("bool", "__and__" | "__rand__" | "__or__" | "__ror__" | "__xor__" | "__rxor__") => Some("wrapper"),
        ("float"|"bytes", "__new__") => Some("new"),
        ("float", "__repr__"|"__hash__"|"__lt__"|"__le__"|"__eq__"|"__ne__"|"__gt__"|"__ge__"
            |"__add__"|"__radd__"|"__sub__"|"__rsub__"|"__mul__"|"__rmul__"|"__mod__"|"__rmod__"
            |"__divmod__"|"__rdivmod__"|"__pow__"|"__rpow__"|"__neg__"|"__pos__"|"__abs__"|"__bool__"
            |"__int__"|"__float__"|"__floordiv__"|"__rfloordiv__"|"__truediv__"|"__rtruediv__")=>Some("wrapper"),
        ("float", "real"|"imag")=>Some("member"),
        ("float", "conjugate"|"__round__"|"__trunc__"|"__floor__"|"__ceil__"|"__format__"|"__getnewargs__")=>Some("method"),
        ("bytes", "__repr__"|"__hash__"|"__str__"|"__lt__"|"__le__"|"__eq__"|"__ne__"|"__gt__"|"__ge__"
            |"__iter__"|"__mod__"|"__rmod__"|"__len__"|"__getitem__"|"__add__"|"__mul__"|"__rmul__"|"__contains__")=>Some("wrapper"),
        ("bytes", "__bytes__"|"__getnewargs__"|"capitalize"|"center"|"count"|"decode"|"endswith"|"expandtabs"
            |"find"|"hex"|"index"|"isalnum"|"isalpha"|"isascii"|"isdigit"|"islower"|"isspace"|"istitle"|"isupper"
            |"join"|"ljust"|"lower"|"lstrip"|"partition"|"removeprefix"|"removesuffix"|"replace"|"rfind"|"rindex"
            |"rjust"|"rpartition"|"rsplit"|"rstrip"|"split"|"splitlines"|"startswith"|"strip"|"swapcase"|"title"|"translate"|"upper"|"zfill")=>Some("method"),
        ("float", "hex" | "is_integer" | "as_integer_ratio") => Some("method"),
        ("float", "fromhex" | "from_number") => Some("class"),
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
                return self.slot_override(&class, "__set__", 0).is_some()
                    || self.slot_override(&class, "__delete__", 0).is_some();
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
                    if owner=="memoryview"{self.native_validate_receiver(&owner,&instance)?;return self.buffer_getattr(instance,&name).unwrap();}
                    self.native_validate_receiver(&owner, &instance)?;
                    let payload = self
                        .native_payload(&instance)
                        .unwrap_or_else(|| instance.clone());
                    if let Some(result)=self.stdlib_member(&owner,&instance,&name) {return result;}
                    if owner=="cell"&&name=="cell_contents" {return self.cell_contents_get(&instance);}
                    match (owner.as_str(), name.as_str(), &payload) {
                        ("float", "real", Value::Float(_)) => Ok(if self.native_payload(&instance).is_some(){payload.fresh_primitive()}else{payload}),
                        ("float", "imag", Value::Float(_)) => Ok(Value::Float(0.0.into())),
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
            "__name__"|"__qualname__" if owner=="cell"&&kind!="new"=>Ok(self.cell_descriptor_metadata(&method,name)),
            "__doc__" if owner=="cell" => Ok(if kind=="member" {Value::None}else{Value::Str(match method.as_str() {"__new__"=>"Create and return a new object.  See help(type) for accurate signature.","__repr__"=>"Return repr(self).","__eq__"=>"Return self==value.","__ne__"=>"Return self!=value.","__lt__"=>"Return self<value.","__le__"=>"Return self<=value.","__gt__"=>"Return self>value.",_=>"Return self>=value."}.into())}),
            "__text_signature__" if owner=="cell"&&kind!="member" => Ok(Value::Str(if kind=="new" {"($type, *args, **kwargs)"}else if method=="__repr__" {"($self, /)"}else{"($self, value, /)"}.into())),
            "__set__"|"__delete__" if owner=="cell"&&kind=="member" => Ok(self.obj_value(Object::Bound(Value::Builtin(if name=="__set__" {"cell_contents_set"}else{"cell_contents_delete"}.into()),value))),
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
        if kind=="static"&&owner=="bytearray"&&name=="maketrans"{return self.buffer_maketrans(args,kwargs);}
        if kind=="class"&&owner=="bytearray"&&name=="fromhex"{let class=args.first().cloned().ok_or_else(||pyerr("TypeError","fromhex requires a class"))?;if !self.is_subclass(&class,&Value::Builtin("bytearray".into()))?{return Err(pyerr("TypeError","fromhex requires a bytearray subtype"));}return self.buffer_fromhex(class,args[1..].to_vec(),kwargs);}
        if owner=="cell" {
            if kind=="member" {return Err(pyerr("TypeError","'getset_descriptor' object is not callable"));}
            if kind=="new" {
                let class=args.first().ok_or_else(||pyerr("TypeError","cell.__new__(): not enough arguments"))?;
                if !self.native_is_class(class) {return Err(pyerr("TypeError",format!("cell.__new__(X): X is not a type object ({})",self.typename(class))));}
                if !self.is_cell_type(class) {return Err(pyerr("TypeError",format!("cell.__new__({}): {} is not a subtype of cell",self.class_name(class),self.class_name(class))));}
                return self.cell_constructor(args[1..].to_vec(),kwargs);
            }
            if cell_comparison_op(&name).is_some() {return self.cell_descriptor_compare_sync(value,args,kwargs);}
            if name=="__repr__" {let receiver=self.cell_wrapper_arguments(&name,&args,&kwargs)?;return self.cell_repr(&receiver).map(|value|Value::Str(value.into()));}
        }
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
            if owner=="memoryview"{if !Self::same_type(&class,&Value::Builtin("memoryview".into())){return Err(pyerr("TypeError","memoryview is not an acceptable base type"));}return self.builtin("memoryview",args[1..].to_vec(),kwargs,None);}
            if owner == "object" {
                if !self.is_subclass(&class, &Value::Builtin("object".into()))? {
                    return Err(pyerr("TypeError", "object.__new__ requires a type"));
                }
                let native = self
                    .class_mro(&class, 0)
                    .unwrap_or_default()
                    .iter()
                    .any(|base| {
                        matches!(base,Value::Builtin(name)if ["tuple","list","dict","set","frozenset","str","int","complex","float","bytes","bytearray","memoryview","bool","type","cell"].contains(&name.as_str()) || stdlib_type_name(name))
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
            if stdlib_type_name(&owner) {
                if !self.is_subclass(&class,&Value::Builtin(owner.clone()))? {return Err(pyerr("TypeError","__new__ requires a subtype"));}
                return self.stdlib_instance_new(&owner,class,args[1..].to_vec(),kwargs);
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
            if let Some(result)=self.numeric_descriptor_call(&owner,&name,class.clone(),args[1..].to_vec(),kwargs.clone()){return result;}
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
                "from_iterable" if owner == "itertools.chain" => {
                    if args.len()!=2 || !kwargs.is_empty() {return Err(pyerr("TypeError","from_iterable takes one argument"));}
                    let payload=self.itertools_call("chain.from_iterable",args[1..].to_vec(),kwargs)?;
                    return self.stdlib_wrap_instance(class,payload);
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
        if stdlib_type_name(&owner) {return self.stdlib_method(&owner,&name,receiver,rest,kwargs).unwrap();}
        if let Some(result)=self.buffer_descriptor_call(&owner,&name,receiver.clone(),rest.clone(),kwargs.clone()){return result;}
        if let Some(result)=self.scalar_descriptor_call(&owner,&name,receiver.clone(),rest.clone(),kwargs.clone()){return result;}
        if let Some(result)=self.numeric_descriptor_call(&owner,&name,receiver.clone(),rest.clone(),kwargs.clone()){return result;}
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
            if self.is_cell_type(&receiver) {
                match name.as_str() {
                    "__call__"=>return self.cell_constructor(rest,kwargs),
                    "__subclasses__"=>{
                        if !rest.is_empty()||!kwargs.is_empty(){return Err(pyerr("TypeError","__subclasses__() takes no arguments"));}
                        return Ok(self.obj_value(Object::List(Vec::new())));
                    },
                    "__instancecheck__"|"__subclasscheck__"=>{
                        if rest.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError","type check takes one argument"));}
                        if name=="__instancecheck__" {return Ok(Value::Bool(self.is_cell(&rest[0])));}
                        if !self.native_is_class(&rest[0]) {return Err(pyerr("TypeError","issubclass() arg 1 must be a class"));}
                        return self.is_subclass(&rest[0],&receiver).map(Value::Bool);
                    },
                    _=>{},
                }
            }
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
            if name=="__sizeof__"&&self.is_cell(&receiver) {
                if !kwargs.is_empty(){return Err(pyerr("TypeError","object.__sizeof__() takes no keyword arguments"));}
                if !rest.is_empty(){return Err(pyerr("TypeError",format!("object.__sizeof__() takes no arguments ({} given)",rest.len())));}
                return Ok(Value::Int(Int::from_i128(24).into()));
            }
            if let Some(result)=self.operand_attribute(&value,&receiver,&rest,&kwargs){return result;}
            if name=="__reduce_ex__"&&self.frozen_owner(&receiver).is_some_and(|(_,frozen)|frozen) {
                if rest.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError","__reduce_ex__ takes one positional argument"));}
                self.as_int(&rest[0])?;
                let reduce=self.getattr(receiver,"__reduce__")?;
                return self.call(reduce,Vec::new(),Vec::new(),None);
            }
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
        if owner=="complex"&&["__pow__","__rpow__"].contains(&name.as_str())&&rest.len()==2 {
            let payload=self.native_payload(&receiver).unwrap_or(receiver);
            return self.complex_method(payload,&name,rest,kwargs).unwrap();
        }
        if owner=="float" && ["__pow__","__rpow__"].contains(&name.as_str()) && rest.len()==2 && kwargs.is_empty(){
            if !matches!(rest[1],Value::None){return Err(pyerr("TypeError","pow() 3rd argument not allowed unless all arguments are integers"));}
            if let Some(result)=self.operand_attribute(&value,&receiver,&rest[..1],&kwargs){return result;}
        }
        if let Some(result)=self.operand_attribute(&value,&receiver,&rest,&kwargs){return result;}
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
        if owner=="frozenset"&&name=="__reduce__" {
            return self.frozen_method(receiver,&name,rest,kwargs).unwrap();
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
        let payload = if self.native_payload(&receiver).is_some()
            && ((owner=="int"&&["__int__", "__index__", "conjugate"].contains(&name.as_str()))
                || (owner=="complex"&&["__complex__","__pos__"].contains(&name.as_str())))
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
