// PEP 654 exception trees and except* state. Implemented from the language
// specification and observable Python 3.14 behavior, without external crates.
#[derive(Clone, Debug)]
struct ExceptionGroupData {
    message: Value,
    exceptions: Value,
    original: Value,
}
#[derive(Clone, Debug)]
struct ExceptStarState {
    original: Value,
    wrapped: Value,
    remainder: Option<Value>,
    raised: Vec<Value>,
    reraised: Vec<Value>,
    matched: Option<PyException>,
    handler_depth: usize,
    bare: bool,
    any_match: bool,
}
impl ExceptStarState {
    fn roots(&self, out: &mut Vec<Value>) {
        out.extend([self.original.clone(), self.wrapped.clone()]);
        out.extend(self.remainder.iter().cloned());
        out.extend(self.raised.iter().chain(self.reraised.iter()).cloned());
        if let Some(error) = &self.matched {
            Runtime::exception_roots(error, out);
        }
    }
}
fn group_type_name(name: &str) -> bool {
    matches!(name, "BaseExceptionGroup" | "ExceptionGroup")
}
impl Runtime {
    fn exception_has_native_class(&self,error:&PyException,name:&str)->bool{
        let class=error.class.clone().unwrap_or_else(||Value::Type(error.kind.clone()));
        self.class_mro(&class,0).is_some_and(|mro|mro.iter().any(|class|matches!(class,Value::Type(kind)if kind==name)))
    }
    fn exception_type_name(&self,error:&PyException)->String{
        error.class.as_ref().map(|class|self.class_name(class)).unwrap_or_else(||error.kind.clone())
    }
    fn exception_header_name(&self,error:&PyException)->String{
        if let Some(Value::Obj(index))=&error.class{
            if let Some(Object::Class(class))=self.heap.get(*index).and_then(Option::as_ref){
                let name=match self.ns_get(class.attrs,"__qualname__"){Some(Value::Str(name))=>name.to_string(),_=>class.name.to_string()};
                let module=match self.ns_get(class.attrs,"__module__"){Some(Value::Str(module))=>module.to_string(),_=>"<unknown>".into()};
                return if module=="builtins"||module=="__main__"{name}else{format!("{module}.{name}")};
            }
        }
        self.exception_type_name(error)
    }
    fn exception_native_traceback(&mut self,error:&mut PyException)->Value{
        let trace=self.exception_traceback(error);
        error.attributes.insert("__traceback__".into(),trace.clone());
        self.sync_exception(error);
        trace
    }
    fn exception_new_for_class(&mut self,class:Value,args:Vec<Value>)->PyResult<PyException>{
        let mut error=pyerr(&self.class_name(&class),"");
        error.class=Some(class);
        error.args=args;
        self.exception_initialize_fields(&mut error,false);
        error.message=self.exception_cached_message(&error)?;
        Ok(error)
    }
    fn exception_message_kind(&self,error:&PyException)->&'static str{
        for kind in ["KeyError","UnicodeDecodeError","UnicodeEncodeError","UnicodeTranslateError"]{
            if self.exception_has_native_class(error,kind){return kind;}
        }
        "BaseException"
    }
    fn exception_native_attribute(&self,error:&PyException,name:&str)->bool{
        match name{
            "value"=>self.exception_has_native_class(error,"StopIteration"),
            "code"=>self.exception_has_native_class(error,"SystemExit"),
            _=>false,
        }
    }
    fn exception_initialize_fields(&mut self,error:&mut PyException,replace:bool){
        if self.exception_has_native_class(error,"StopIteration") && (replace || !error.attributes.contains_key("value")){
            error.0.attributes.insert("value".into(),error.0.args.first().cloned().unwrap_or(Value::None));
        }
        if self.exception_has_native_class(error,"SystemExit") && (replace || !error.attributes.contains_key("code")){
            let code=match error.args.as_slice(){[]=>Value::None,[value]=>value.clone(),values=>self.obj_value(Object::Tuple(values.to_vec()))};
            error.attributes.insert("code".into(),code);
        }
    }
    fn exception_dict(&mut self, error: &mut PyException) -> usize {
        if let Some(index) = error.dict {
            return index;
        }
        let index = self.alloc(Object::Dict(Vec::new()));
        error.dict = Some(index);
        index
    }
    fn exception_dynamic_attr(&self, error: &PyException, name: &str) -> Option<Value> {
        error.dict.and_then(|index| self.ns_get(index, name))
    }
    fn is_exception_value(&self, value: &Value) -> bool {
        matches!(value,Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Exception(_))))
    }
    fn exception_data(&self, value: &Value) -> Option<PyException> {
        match value {
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::Exception(error)) => Some(error.clone()),
                _ => None,
            },
            _ => None,
        }
    }
    fn exception_actual_class(&self, value: &Value) -> Option<Value> {
        let error = self.exception_data(value)?;
        Some(error.class.clone().unwrap_or_else(|| Value::Type(error.kind.clone())))
    }
    fn exception_group_items(&self, value: &Value) -> Option<Vec<Value>> {
        let error = self.exception_data(value)?;
        let Value::Obj(index) = error.0.group?.exceptions else {
            return None;
        };
        match self.heap.get(index).and_then(Option::as_ref) {
            Some(Object::Tuple(items)) => Some(items.clone()),
            _ => None,
        }
    }
    fn exception_group_sequence(&self, value: &Value) -> bool {
        let value = self.native_payload(value).unwrap_or_else(|| value.clone());
        match value {
            Value::Str(_) | Value::Bytes(_) => true,
            Value::Obj(index) => match self.heap.get(index).and_then(Option::as_ref) {
                Some(Object::List(_) | Object::Tuple(_) | Object::Range(..)) => true,
                Some(Object::Instance { class, .. } | Object::BuiltinInstance { class, .. }) => {
                    self.class_lookup(class, "__getitem__", 0).is_some()
                }
                _ => false,
            },
            _ => false,
        }
    }
    fn exception_group_len(&self, group: &ExceptionGroupData) -> usize {
        match &group.exceptions {
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::Tuple(items)) => items.len(),
                _ => 0,
            },
            _ => 0,
        }
    }
    fn exception_object_message(&mut self, error: &PyException) -> PyResult<String> {
        if let Some(group) = &error.group {
            let count = self.exception_group_len(group);
            return Ok(format!(
                "{} ({} sub-exception{})",
                self.str_value(&group.message)?,
                count,
                if count == 1 { "" } else { "s" }
            ));
        }
        let kind=self.exception_message_kind(error);
        self.exception_message(kind, &error.args)
    }
    fn exception_cached_message(&mut self, error: &PyException) -> PyResult<String> {
        if let Some(group) = &error.group {
            let count = self.exception_group_len(group);
            let message = match self
                .native_payload(&group.message)
                .unwrap_or_else(|| group.message.clone())
            {
                Value::Str(text) => text.to_string(),
                _ => String::new(),
            };
            return Ok(format!(
                "{} ({} sub-exception{})",
                message,
                count,
                if count == 1 { "" } else { "s" }
            ));
        }
        if let Some(message) = codec_exception_message(self.exception_message_kind(error), &error.args) {
            return Ok(message);
        }
        match error.args.as_slice() {
            [] => Ok(String::new()),
            [Value::Str(text)] if self.exception_has_native_class(error,"KeyError") => Ok(text_repr_str(text)),
            [value @ (Value::None
            | Value::Bool(_)
            | Value::Int(_)
            | Value::Float(_)
            | Value::Str(_))] => self.str_value(value),
            _ => Ok(String::new()),
        }
    }
    fn exception_group_repr(
        &mut self,
        error: &PyException,
        seen: &mut Vec<usize>,
    ) -> PyResult<String> {
        let group = error.group.as_ref().unwrap();
        let root = self.roots.len();
        let mut roots = Vec::new();
        Self::exception_roots(error, &mut roots);
        self.roots.push(roots);
        let result = (|| {
            let original = self
                .native_payload(&group.original)
                .unwrap_or_else(|| group.original.clone());
            let sequence = if matches!(&original,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::List(_)|Object::Tuple(_))))
            {
                let argument = error.args.get(1).cloned().unwrap_or(Value::None);
                let argument = self.native_payload(&argument).unwrap_or(argument);
                if matches!(&argument,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::List(_))))
                {
                    let items = self.to_vec(group.exceptions.clone())?;
                    self.obj_value(Object::List(items))
                } else {
                    group.exceptions.clone()
                }
            } else {
                group.original.clone()
            };
            self.roots[root].push(sequence.clone());
            Ok(format!(
                "{}({}, {})",
                self.exception_type_name(error),
                self.repr_inner(&group.message, seen)?,
                self.repr_inner(&sequence, seen)?
            ))
        })();
        self.roots.truncate(root);
        result
    }
    fn exception_group_construct(
        &mut self,
        mut class: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        if args.len() != 2 {
            return Err(pyerr(
                "TypeError",
                format!(
                    "BaseExceptionGroup.__new__() takes exactly 2 arguments ({} given)",
                    args.len()
                ),
            ));
        }
        if !kwargs.is_empty() {
            return Err(pyerr(
                "TypeError",
                format!("{}() takes no keyword arguments", self.class_name(&class)),
            ));
        }
        let root = self.roots.len();
        self.roots.push(args.clone());
        self.roots[root].push(class.clone());
        let result = (|| {
            if !matches!(
                self.native_payload(&args[0])
                    .unwrap_or_else(|| args[0].clone()),
                Value::Str(_)
            ) {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "BaseExceptionGroup.__new__() argument 1 must be str, not {}",
                        self.typename(&args[0])
                    ),
                ));
            }
            if !self.exception_group_sequence(&args[1]) {
                return Err(pyerr(
                    "TypeError",
                    "second argument (exceptions) must be a sequence",
                ));
            }
            let items = self.to_vec(args[1].clone())?;
            self.roots[root].extend(items.iter().cloned());
            if items.is_empty() {
                return Err(pyerr(
                    "ValueError",
                    "second argument (exceptions) must be a non-empty sequence",
                ));
            }
            let exception_only = self.is_subclass(&class, &Value::Type("ExceptionGroup".into()))?;
            let mut all_exception = true;
            for (index, item) in items.iter().enumerate() {
                if !self.is_exception_value(item) {
                    return Err(pyerr(
                        "ValueError",
                        format!(
                            "Item {} of second argument (exceptions) is not an exception",
                            index
                        ),
                    ));
                }
                let cls = self.exception_actual_class(item).unwrap();
                let mut ordinary = self.is_subclass(&cls, &Value::Type("Exception".into()))?;
                if !ordinary {
                    let reported = self.getattr(item.clone(), "__class__")?;
                    ordinary = self.is_subclass(&reported, &Value::Type("Exception".into()))?;
                }
                all_exception &= ordinary;
                if exception_only && !ordinary {
                    let message = if matches!(&class,Value::Type(name)if name=="ExceptionGroup") {
                        "Cannot nest BaseExceptions in an ExceptionGroup".into()
                    } else {
                        format!(
                            "Cannot nest BaseExceptions in '{}'",
                            self.class_name(&class)
                        )
                    };
                    return Err(pyerr("TypeError", message));
                }
            }
            if matches!(&class,Value::Type(name)if name=="BaseExceptionGroup") && all_exception {
                class = Value::Type("ExceptionGroup".into());
            }
            let exceptions = if matches!(&args[1],Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_))))
            {
                args[1].clone()
            } else {
                self.obj_value(Object::Tuple(items))
            };
            let mut error = pyerr(&self.class_name(&class), "");
            if matches!(class, Value::Obj(_)) {
                error.class = Some(class);
            }
            error.args = args.clone();
            error.group = Some(Box::new(ExceptionGroupData {
                message: args[0].clone(),
                exceptions,
                original: args[1].clone(),
            }));
            error.message = self.exception_cached_message(&error)?;
            Ok(self.exception_value(&mut error))
        })();
        self.roots.truncate(root);
        result
    }
    fn exception_subclass_call(
        &mut self,
        class: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
        caller: Option<&Frame>,
    ) -> PyResult<Value> {
        let object = if let Some(new) = self.class_lookup(&class, "__new__", 0) {
            let mut positional = vec![class.clone()];
            positional.extend(args.clone());
            self.call(new, positional, kwargs.clone(), caller)?
        } else if self.is_subclass(&class, &Value::Type("BaseExceptionGroup".into()))? {
            self.exception_group_construct(class.clone(), args.clone(), kwargs.clone())?
        } else {
            if !kwargs.is_empty() {
                return Err(pyerr(
                    "TypeError",
                    format!("{}() takes no keyword arguments", self.class_name(&class)),
                ));
            }
            let mut error = self.exception_new_for_class(class.clone(), args.clone())?;
            self.exception_value(&mut error)
        };
        let root = self.roots.len();
        self.roots.push(vec![object.clone()]);
        let result = (|| {
            let actual = self
                .exception_actual_class(&object)
                .or_else(|| self.object_class(&object))
                .unwrap_or_else(|| Value::Builtin(self.typename(&object)));
            if self.is_subclass(&actual, &class)? {
                if let Some(init) = self.class_lookup(&class, "__init__", 0) {
                    let bound = self.bind_descriptor(init, Some(object.clone()), class.clone())?;
                    let value = self.call(bound, args, kwargs, caller)?;
                    if !matches!(value, Value::None) {
                        return Err(pyerr("TypeError", "__init__() should return None"));
                    }
                } else if let Some(mut error) = self.exception_data(&object) {
                    if !kwargs.is_empty() {
                        return Err(pyerr(
                            "TypeError",
                            format!("{}() takes no keyword arguments", self.class_name(&class)),
                        ));
                    }
                    error.args = args;
                    error.args_tuple = None;
                    self.exception_initialize_fields(&mut error,true);
                    error.message = self.exception_cached_message(&error)?;
                    self.sync_exception(&error);
                }
            }
            Ok(object)
        })();
        self.roots.truncate(root);
        result
    }
    fn exception_type_method(
        &mut self,
        name: &str,
        mut args: Vec<Value>,
        kwargs: KeywordArgs,
        caller: Option<&Frame>,
    ) -> PyResult<Value> {
        let (owner, method) = name.split_once(':').unwrap_or((name, ""));
        if args.is_empty() {
            return Err(pyerr(
                "TypeError",
                "unbound exception method needs an instance",
            ));
        }
        let first = args.remove(0);
        if ["__getattribute__", "__setattr__", "__delattr__"].contains(&method) {
            let name = args
                .first()
                .cloned()
                .ok_or_else(|| pyerr("TypeError", "missing attribute name"))?;
            let name = self.str_value(&name)?;
            return match method {
                "__getattribute__" => self.getattr_default(first, &name),
                "__setattr__" => {
                    let value = args
                        .get(1)
                        .cloned()
                        .ok_or_else(|| pyerr("TypeError", "missing attribute value"))?;
                    self.setattr_default(first, &name, value)?;
                    Ok(Value::None)
                }
                _ => {
                    self.delattr_default(first, &name)?;
                    Ok(Value::None)
                }
            };
        }
        if ["__str__", "__repr__"].contains(&method) {
            if !args.is_empty() || !kwargs.is_empty() {
                return Err(pyerr(
                    "TypeError",
                    "exception representation takes no arguments",
                ));
            }
            let error = self
                .exception_data(&first)
                .ok_or_else(|| pyerr("TypeError", "descriptor requires an exception instance"))?;
            if (owner=="KeyError" && method=="__str__" || group_type_name(owner)) && !self.exception_has_native_class(&error,owner){
                return Err(pyerr("TypeError",format!("descriptor '{method}' requires a '{owner}' object")));
            }
            let text = if method == "__str__" {
                if group_type_name(owner) {self.exception_object_message(&error)?}
                else {self.exception_message(if owner=="KeyError"{"KeyError"}else{"BaseException"},&error.args)?}
            } else if group_type_name(owner) && error.group.is_some() {
                self.exception_group_repr(&error, &mut Vec::new())?
            } else {
                let mut values = Vec::new();
                for arg in &error.args {
                    values.push(self.repr(arg)?);
                }
                format!("{}({})", self.exception_type_name(&error), values.join(", "))
            };
            return Ok(Value::Str(text.into()));
        }
        if method == "__new__" {
            if !self.is_subclass(&first, &Value::Type(owner.into()))? {
                return Err(pyerr("TypeError", "exception __new__ requires a subtype"));
            }
            if group_type_name(owner) {
                return self.exception_group_construct(first, args, Vec::new());
            }
            let mut error = if matches!(first,Value::Obj(_)){self.exception_new_for_class(first,args)?}
                else{self.new_exception(&self.class_name(&first),args)?};
            return Ok(self.exception_value(&mut error));
        }
        if method == "__init__" {
            if !self.is_exception_value(&first) {
                return Err(pyerr(
                    "TypeError",
                    "exception __init__ requires an exception instance",
                ));
            }
            let mut error = self.exception_data(&first).unwrap();
            if (matches!(owner,"StopIteration"|"SystemExit") || group_type_name(owner)) && !self.exception_has_native_class(&error,owner){
                return Err(pyerr("TypeError",format!("descriptor '__init__' requires a '{owner}' object")));
            }
            error.args = args;
            error.args_tuple = None;
            if matches!(owner,"StopIteration"|"SystemExit"){self.exception_initialize_fields(&mut error,true);}
            error.message = self.exception_cached_message(&error)?;
            self.sync_exception(&error);
            return Ok(Value::None);
        }
        let _ = caller;
        self.exception_group_method(first, method, args, kwargs)
            .unwrap_or_else(|| Err(pyerr("AttributeError", method)))
    }
    fn exception_group_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        if let Value::Type(class) = &value {
            if [
                "__new__",
                "__init__",
                "__getattribute__",
                "__setattr__",
                "__delattr__",
                "__str__",
                "__repr__",
                "add_note",
                "with_traceback",
            ]
            .contains(&name)
                || group_type_name(class) && ["derive", "split", "subgroup"].contains(&name)
            {
                return Some(Ok(Value::Builtin(format!(
                    "exception_type:{}:{}",
                    class, name
                ))));
            }
            return None;
        }
        let error = self.exception_data(&value)?;
        if let Some(class) = &error.class {
            if let Some(method) = self.class_lookup(class, name, 0) {
                let data = match &method {
                    Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                        Some(Object::Property { .. } | Object::Slot { .. }) => true,
                        Some(Object::Instance { class, .. }) => {
                            self.class_lookup(class, "__set__", 0).is_some()
                        }
                        _ => false,
                    },
                    _ => false,
                };
                if !data {
                    if let Some(stored) = self.exception_dynamic_attr(&error, name) {
                        return Some(Ok(stored));
                    }
                }
                return Some(self.bind_descriptor(method, Some(value), class.clone()));
            }
        }
        if let Some(group) = &error.group {
            if name == "message" {
                return Some(Ok(group.message.clone()));
            }
            if name == "exceptions" {
                return Some(Ok(group.exceptions.clone()));
            }
        }
        if ["add_note", "with_traceback"].contains(&name)
            || error.group.is_some() && ["derive", "split", "subgroup"].contains(&name)
        {
            if let Some(stored) = self.exception_dynamic_attr(&error, name) {
                return Some(Ok(stored));
            }
            return Some(Ok(self.obj_value(Object::Bound(
                Value::Builtin(format!("method:{}", name)),
                value,
            ))));
        }
        None
    }
    fn exception_group_method(
        &mut self,
        value: Value,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        let mut error = self.exception_data(&value)?;
        if !["derive", "split", "subgroup", "add_note", "with_traceback"].contains(&name) {
            return None;
        }
        if error.group.is_none() && ["derive", "split", "subgroup"].contains(&name) {
            return None;
        }
        Some((|| {
            if args.len() != 1 || !kwargs.is_empty() {
                return Err(pyerr(
                    "TypeError",
                    format!("{}() takes exactly one argument", name),
                ));
            }
            match name {
                "add_note" => {
                    if !matches!(
                        self.native_payload(&args[0])
                            .unwrap_or_else(|| args[0].clone()),
                        Value::Str(_)
                    ) {
                        return Err(pyerr(
                            "TypeError",
                            format!("note must be a str, not '{}'", self.typename(&args[0])),
                        ));
                    }
                    let notes =
                        if let Some(notes) = self.exception_dynamic_attr(&error, "__notes__") {
                            notes
                        } else {
                            let notes = self.obj_value(Object::List(Vec::new()));
                            let attrs = self.exception_dict(&mut error);
                            self.ns_set(attrs, "__notes__".into(), notes.clone());
                            self.sync_exception(&error);
                            notes
                        };
                    let Value::Obj(index) = notes else {
                        return Err(pyerr(
                            "TypeError",
                            "Cannot add note: __notes__ is not a list",
                        ));
                    };
                    let Some(Object::List(notes)) =
                        self.heap.get_mut(index).and_then(Option::as_mut)
                    else {
                        return Err(pyerr(
                            "TypeError",
                            "Cannot add note: __notes__ is not a list",
                        ));
                    };
                    notes.push(args[0].clone());
                    Ok(Value::None)
                }
                "with_traceback" => {
                    self.setattr(value.clone(), "__traceback__", args[0].clone())?;
                    Ok(value)
                }
                "derive" => {
                    let group = error.0.group.unwrap();
                    self.exception_group_construct(
                        Value::Type("BaseExceptionGroup".into()),
                        vec![group.message, args[0].clone()],
                        Vec::new(),
                    )
                }
                _ => {
                    self.exception_group_validate_condition(&args[0], false)?;
                    let (matched, rest) = self.exception_group_split(&value, &args[0])?;
                    if name == "subgroup" {
                        Ok(matched.unwrap_or(Value::None))
                    } else {
                        Ok(self.obj_value(Object::Tuple(vec![
                            matched.unwrap_or(Value::None),
                            rest.unwrap_or(Value::None),
                        ])))
                    }
                }
            }
        })())
    }
    fn exception_group_validate_condition(
        &mut self,
        condition: &Value,
        star: bool,
    ) -> PyResult<()> {
        let classes = if let Value::Obj(index) = condition {
            match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::Tuple(items)) => Some(items.clone()),
                _ => None,
            }
        } else {
            None
        };
        let classes = classes.unwrap_or_else(|| vec![condition.clone()]);
        let tuple = matches!(condition,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_))));
        for class in classes {
            let type_object = matches!(&class, Value::Type(_))
                || matches!(&class,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))));
            if type_object && self.is_subclass(&class, &Value::Type("BaseException".into()))? {
                if star && self.is_subclass(&class, &Value::Type("BaseExceptionGroup".into()))? {
                    return Err(pyerr(
                        "TypeError",
                        "catching ExceptionGroup with except* is not allowed. Use except instead.",
                    ));
                }
                continue;
            }
            if !star && !tuple && !type_object {
                let callable = self.builtin("callable", vec![class], Vec::new(), None)?;
                if self.truth(&callable)? {
                    continue;
                }
            }
            return Err(pyerr(
                "TypeError",
                if star {
                    "catching classes that do not inherit from BaseException is not allowed"
                } else {
                    "expected an exception type, a tuple of exception types, or a callable (other than a class)"
                },
            ));
        }
        Ok(())
    }
    fn exception_group_condition(&mut self, value: &Value, condition: &Value) -> PyResult<bool> {
        let is_class = matches!(condition, Value::Type(_))
            || matches!(condition,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_)|Object::Tuple(_))));
        if is_class {
            self.exception_match(value, condition)
        } else {
            let result = self.call(condition.clone(), vec![value.clone()], Vec::new(), None)?;
            self.truth(&result)
        }
    }
    fn exception_group_copy_metadata(&mut self, source: &Value, target: &Value) -> PyResult<()> {
        let mut original = self
            .exception_data(source)
            .ok_or_else(|| pyerr("TypeError", "expected an exception"))?;
        let mut derived = self.exception_data(target).ok_or_else(|| {
            pyerr(
                "TypeError",
                "derive must return an instance of BaseExceptionGroup",
            )
        })?;
        if derived.group.is_none() {
            return Err(pyerr(
                "TypeError",
                "derive must return an instance of BaseExceptionGroup",
            ));
        }
        let traceback = self.exception_traceback(&original);
        original
            .attributes
            .insert("__traceback__".into(), traceback.clone());
        self.sync_exception(&original);
        derived.trace = original.trace.clone();
        derived.cause = original.cause.clone();
        derived.context = original.context.clone();
        derived.suppress_context = original.suppress_context;
        derived.attributes.insert("__traceback__".into(), traceback);
        if let Some(notes) = self.exception_dynamic_attr(&original, "__notes__") {
            if self.exception_group_sequence(&notes) {
                let items = self.to_vec(notes)?;
                let copy = self.obj_value(Object::List(items));
                let attrs = self.exception_dict(&mut derived);
                self.ns_set(attrs, "__notes__".into(), copy);
            }
        }
        self.sync_exception(&derived);
        Ok(())
    }
    fn exception_group_derive(&mut self, source: &Value, items: Vec<Value>) -> PyResult<Value> {
        let root = self.roots.len();
        let mut roots = items.clone();
        roots.push(source.clone());
        self.roots.push(roots);
        let result = (|| {
            let items = self.obj_value(Object::List(items));
            self.roots[root].push(items.clone());
            let derive = self.getattr(source.clone(), "derive")?;
            let derived = self.call(derive, vec![items], Vec::new(), None)?;
            self.roots[root].push(derived.clone());
            self.exception_group_copy_metadata(source, &derived)?;
            Ok(derived)
        })();
        self.roots.truncate(root);
        result
    }
    fn exception_group_split(
        &mut self,
        value: &Value,
        condition: &Value,
    ) -> PyResult<(Option<Value>, Option<Value>)> {
        let root = self.roots.len();
        self.roots.push(vec![value.clone(), condition.clone()]);
        let result = (|| {
            if self.exception_group_condition(value, condition)? {
                return Ok((Some(value.clone()), None));
            }
            let Some(items) = self.exception_group_items(value) else {
                return Ok((None, Some(value.clone())));
            };
            let mut matching = Vec::new();
            let mut rest = Vec::new();
            for item in items {
                let (yes, no) = self.exception_group_split(&item, condition)?;
                if let Some(yes) = yes {
                    self.roots[root].push(yes.clone());
                    matching.push(yes);
                }
                if let Some(no) = no {
                    self.roots[root].push(no.clone());
                    rest.push(no);
                }
            }
            let yes = if matching.is_empty() {
                None
            } else {
                let result = self.exception_group_derive(value, matching)?;
                self.roots[root].push(result.clone());
                Some(result)
            };
            let no = if rest.is_empty() {
                None
            } else {
                Some(self.exception_group_derive(value, rest)?)
            };
            Ok((yes, no))
        })();
        self.roots.truncate(root);
        result
    }
    fn exception_star_state(&self, value: &Value) -> PyResult<ExceptStarState> {
        match value {
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::ExceptStarState(state)) => Ok((**state).clone()),
                _ => Err(pyerr("RuntimeError", "invalid except* state")),
            },
            _ => Err(pyerr("RuntimeError", "invalid except* state")),
        }
    }
    fn exception_star_save(&mut self, value: &Value, state: ExceptStarState) {
        if let Value::Obj(index) = value {
            self.heap[*index] = Some(Object::ExceptStarState(Box::new(state)));
        }
    }
    fn exception_star_begin(&mut self, frame: &mut Frame) -> PyResult<Value> {
        let mut error = frame
            .exception
            .clone()
            .ok_or_else(|| pyerr("RuntimeError", "no active exception"))?;
        let original = self.exception_value(&mut error);
        let bare = error.group.is_none();
        let wrapped = if bare {
            let items = self.obj_value(Object::Tuple(vec![original.clone()]));
            let cls = self.exception_actual_class(&original).unwrap();
            let kind = if self.is_subclass(&cls, &Value::Type("Exception".into()))? {
                "ExceptionGroup"
            } else {
                "BaseExceptionGroup"
            };
            let message = Value::Str("".into());
            let mut wrapped = pyerr(kind, "");
            wrapped.args = vec![message.clone(), items.clone()];
            wrapped.group = Some(Box::new(ExceptionGroupData {
                message,
                exceptions: items.clone(),
                original: items,
            }));
            wrapped.message = self.exception_cached_message(&wrapped)?;
            self.exception_value(&mut wrapped)
        } else {
            original.clone()
        };
        let state = self.obj_value(Object::ExceptStarState(Box::new(ExceptStarState {
            original,
            wrapped: wrapped.clone(),
            remainder: Some(wrapped),
            raised: Vec::new(),
            reraised: Vec::new(),
            matched: None,
            handler_depth: frame.handlers.len(),
            bare,
            any_match: false,
        })));
        frame.except_star.push(state.clone());
        Ok(state)
    }
    fn exception_star_split(
        &mut self,
        frame: &mut Frame,
        value: Value,
        condition: Value,
    ) -> PyResult<bool> {
        self.exception_group_validate_condition(&condition, true)?;
        let mut state = self.exception_star_state(&value)?;
        let Some(remainder) = state.remainder.clone() else {
            return Ok(false);
        };
        let (matched, rest) = self.exception_group_split(&remainder, &condition)?;
        state.remainder = rest;
        let found = matched.is_some();
        if let Some(matched) = matched {
            let mut error = self.as_exception(matched)?;
            let traceback = self.exception_traceback(&error);
            error.attributes.insert("__traceback__".into(), traceback);
            self.sync_exception(&error);
            state.matched = Some(error.clone());
            state.any_match = true;
            frame.exception = Some(error);
        }
        self.exception_star_save(&value, state);
        Ok(found)
    }
    fn exception_same_metadata(a: &PyException, b: &PyException) -> bool {
        let same = |x: &Option<Value>, y: &Option<Value>| match (x, y) {
            (None, None) => true,
            (Some(x), Some(y)) => x.same_identity(y),
            _ => false,
        };
        a.trace == b.trace
            && same(&a.cause, &b.cause)
            && same(&a.context, &b.context)
            && same(
                &a.attributes.get("__traceback__").cloned(),
                &b.attributes.get("__traceback__").cloned(),
            )
    }
    fn exception_star_record(
        &mut self,
        frame: &mut Frame,
        value: Value,
        raised: bool,
    ) -> PyResult<()> {
        if raised {
            let mut state = self.exception_star_state(&value)?;
            let mut error = frame
                .exception
                .clone()
                .ok_or_else(|| pyerr("RuntimeError", "no active except* exception"))?;
            let current = self.exception_value(&mut error);
            if state
                .matched
                .as_ref()
                .is_some_and(|matched| Self::exception_same_metadata(&error, matched))
            {
                state.reraised.push(current);
            } else {
                state.raised.push(current);
            }
            frame.exception = frame.exception_stack.pop().flatten();
            self.exception_star_save(&value, state);
        }
        Ok(())
    }
    fn exception_leaf_ids(&self, value: &Value, out: &mut std::collections::HashSet<usize>) {
        if let Some(items) = self.exception_group_items(value) {
            for item in items {
                self.exception_leaf_ids(&item, out);
            }
        } else if let Value::Obj(index) = value {
            out.insert(*index);
        }
    }
    fn exception_group_project(
        &mut self,
        value: &Value,
        ids: &std::collections::HashSet<usize>,
    ) -> PyResult<Option<Value>> {
        let Some(items) = self.exception_group_items(value) else {
            return Ok(if matches!(value,Value::Obj(index)if ids.contains(index)) {
                Some(value.clone())
            } else {
                None
            });
        };
        let root = self.roots.len();
        self.roots.push(vec![value.clone()]);
        let result = (|| {
            let mut kept = Vec::new();
            for item in items {
                if let Some(item) = self.exception_group_project(&item, ids)? {
                    self.roots[root].push(item.clone());
                    kept.push(item);
                }
            }
            if kept.is_empty() {
                Ok(None)
            } else {
                self.exception_group_derive(value, kept).map(Some)
            }
        })();
        self.roots.truncate(root);
        result
    }
    fn exception_star_end(&mut self, frame: &mut Frame, value: Value) -> PyResult<()> {
        let state = self.exception_star_state(&value)?;
        let root = self.roots.len();
        let mut roots = Vec::new();
        state.roots(&mut roots);
        self.roots.push(roots);
        frame.except_star.pop();
        frame.exception = frame.exception_stack.pop().flatten();
        let result = (|| {
            let mut raised = state.raised;
            if state.reraised.is_empty() {
                if let Some(rest) = state.remainder {
                    raised.push(if state.bare && !state.any_match {
                        state.original
                    } else {
                        rest
                    });
                }
            } else {
                let mut ids = std::collections::HashSet::new();
                for item in state.reraised.iter().chain(state.remainder.iter()) {
                    self.exception_leaf_ids(item, &mut ids);
                }
                if let Some(rebuilt) = self.exception_group_project(&state.wrapped, &ids)? {
                    self.roots[root].push(rebuilt.clone());
                    raised.push(rebuilt);
                }
            }
            let outgoing = match raised.len() {
                0 => return Ok(()),
                1 => raised.remove(0),
                _ => {
                    let errors = self.obj_value(Object::List(raised));
                    self.exception_group_construct(
                        Value::Type("BaseExceptionGroup".into()),
                        vec![Value::Str("".into()), errors],
                        Vec::new(),
                    )?
                }
            };
            let mut error = self.as_exception(outgoing)?;
            error.skip_trace = true;
            Err(error)
        })();
        self.roots.truncate(root);
        result
    }
    fn exception_star_unwind(&mut self, frame: &mut Frame) {
        while let Some(value) = frame.except_star.last() {
            let Ok(state) = self.exception_star_state(value) else {
                frame.except_star.pop();
                continue;
            };
            if frame.handlers.len() > state.handler_depth {
                break;
            }
            frame.except_star.pop();
            frame.exception = frame.exception_stack.pop().flatten();
        }
    }
}
