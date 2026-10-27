// compile/eval/exec argument validation. Source syntax uses the shared PEG.
impl Runtime {
    fn execution_unknown_keyword(
        &mut self,
        name: &str,
        keyword: &KeywordName,
        parameters: &[&str],
    ) -> PyResult<()> {
        // Recognized names are matched by native spelling before this check.
        // An unknown string subclass still participates in Python's validation
        // comparisons, including its exceptions and observable side effects.
        for parameter in parameters {
            if self.equal(&keyword.original, &Value::Str((*parameter).into()))? {
                return Err(pyerr(
                    "TypeError",
                    format!("invalid keyword argument for {name}()"),
                ));
            }
        }
        Err(pyerr(
            "TypeError",
            format!("{name}() got an unexpected keyword argument '{keyword}'"),
        ))
    }
    fn execution_parameters(
        &mut self,
        name: &str,
        args: &[Value],
        kwargs: &KeywordArgs,
    ) -> PyResult<[Value; 4]> {
        if args.is_empty() {
            return Err(pyerr(
                "TypeError",
                format!("{name}() takes at least 1 positional argument (0 given)"),
            ));
        }
        let maximum = if name == "exec" { 4 } else { 3 };
        if args.len() + kwargs.len() > maximum {
            return Err(pyerr(
                "TypeError",
                format!(
                    "{name}() takes at most {maximum} arguments ({} given)",
                    args.len() + kwargs.len()
                ),
            ));
        }
        if args.len() > 3 {
            return Err(pyerr(
                "TypeError",
                format!(
                    "{name}() takes at most 3 positional arguments ({} given)",
                    args.len()
                ),
            ));
        }
        let parameters: &[&str] = if name == "exec" {
            &["globals", "locals", "closure"]
        } else {
            &["globals", "locals"]
        };
        let mut result = [args[0].clone(), Value::None, Value::None, Value::None];
        let mut seen = [true, false, false, false];
        for (index, value) in args.iter().enumerate().skip(1) {
            result[index] = value.clone();
            seen[index] = true;
        }
        for parameter in parameters {
            let index = parameters
                .iter()
                .position(|name| name == parameter)
                .unwrap()
                + 1;
            for (key, value) in kwargs.iter().filter(|(key, _)| key.as_str() == *parameter) {
                if seen[index] {
                    return Err(pyerr(
                        "TypeError",
                        format!("{name}() got multiple values for argument '{key}'"),
                    ));
                }
                seen[index] = true;
                result[index] = value.clone();
            }
        }
        for (key, _) in kwargs {
            if !parameters.contains(&key.as_str()) {
                self.execution_unknown_keyword(name, key, parameters)?;
            }
        }
        Ok(result)
    }
    fn execution_compile_parameters(
        &mut self,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<[Option<Value>; 7]> {
        const PARAMETERS: [&str; 7] = [
            "source",
            "filename",
            "mode",
            "flags",
            "dont_inherit",
            "optimize",
            "_feature_version",
        ];
        if args.len() + kwargs.len() > PARAMETERS.len() {
            return Err(pyerr(
                "TypeError",
                format!(
                    "compile() takes at most 7 arguments ({} given)",
                    args.len() + kwargs.len()
                ),
            ));
        }
        let mut result: [Option<Value>; 7] = std::array::from_fn(|_| None);
        let mut duplicates = [false; 7];
        for (index, value) in args.into_iter().enumerate() {
            result[index] = Some(value);
        }
        for (key, value) in &kwargs {
            if let Some(index) = PARAMETERS.iter().position(|name| *name == key.as_str()) {
                if result[index].is_some() {
                    duplicates[index] = true;
                } else {
                    result[index] = Some(value.clone());
                }
            }
        }
        // Missing required parameters precede duplicate and unknown-key checks.
        for index in 0..3 {
            if result[index].is_none() {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "compile() missing required argument '{}' (pos {})",
                        PARAMETERS[index],
                        index + 1
                    ),
                ));
            }
        }
        for index in 0..7 {
            if duplicates[index] {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "argument for compile() given by name ('{}') and position ({})",
                        PARAMETERS[index],
                        index + 1
                    ),
                ));
            }
        }
        for (key, _) in &kwargs {
            if !PARAMETERS.contains(&key.as_str()) {
                self.execution_unknown_keyword("compile", key, &PARAMETERS)?;
            }
        }
        Ok(result)
    }
}

fn execution_cookie(line: &[u8]) -> Option<String> {
    let start = line
        .iter()
        .position(|byte| !matches!(byte, b' ' | b'\t' | b'\x0c'))
        .unwrap_or(line.len());
    if line.get(start) != Some(&b'#') {
        return None;
    }
    for index in start..line.len().saturating_sub(6) {
        if line.get(index..index + 6) != Some(b"coding") {
            continue;
        }
        if !matches!(line.get(index + 6), Some(b':' | b'=')) {
            continue;
        }
        let mut begin = index + 7;
        while matches!(line.get(begin), Some(b' ' | b'\t')) {
            begin += 1;
        }
        let mut end = begin;
        while line
            .get(end)
            .is_some_and(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        {
            end += 1;
        }
        if end > begin {
            return Some(String::from_utf8(line[begin..end].to_vec()).unwrap());
        }
    }
    None
}

fn execution_line(source: &[u8]) -> (&[u8], &[u8]) {
    let end = source
        .iter()
        .position(|byte| matches!(byte, b'\r' | b'\n'))
        .unwrap_or(source.len());
    let mut next = end;
    if source.get(next) == Some(&b'\r') {
        next += 1;
    }
    if source.get(next) == Some(&b'\n') {
        next += 1;
    }
    (&source[..end], &source[next..])
}

impl Runtime {
    fn execution_c_int(&mut self, value: &Value) -> PyResult<i32> {
        // Native int subclasses use their stored integer, without consulting
        // an overridden __index__. Other objects use the index protocol.
        let payload = self.native_payload(value).unwrap_or_else(|| value.clone());
        let integer = match payload {
            Value::Int(number) => number.inner().clone(),
            Value::Bool(number) => Int::from_i128(if number { 1 } else { 0 }),
            _ => {
                let method = match self.special_method(value.clone(), "__index__") {
                    Ok(method) => method,
                    Err(error) if self.missing_special_method(value, "__index__", &error) => {
                        return Err(pyerr(
                            "TypeError",
                            format!(
                                "'{}' object cannot be interpreted as an integer",
                                self.typename(value)
                            ),
                        ))
                    }
                    Err(error) => return Err(error),
                };
                let result = self.call(method, Vec::new(), Vec::new(), None)?;
                match self
                    .native_payload(&result)
                    .unwrap_or_else(|| result.clone())
                {
                    Value::Int(number) => number.into_inner(),
                    Value::Bool(number) => Int::from_i128(if number { 1 } else { 0 }),
                    _ => {
                        return Err(pyerr(
                            "TypeError",
                            format!(
                                "__index__ returned non-int (type {})",
                                self.typename(&result)
                            ),
                        ))
                    }
                }
            }
        };
        integer
            .to_i128()
            .and_then(|value| i32::try_from(value).ok())
            .ok_or_else(|| pyerr("OverflowError", "Python int too large to convert to C int"))
    }
    // Execution phase ordering follows CPython 3.14.4 (PSF license):
    // Python/pythonrun.c run_eval_code_obj, Python/ceval.c PyEval_EvalCode,
    // and Objects/funcobject.c _PyFunction_FromConstructor.
    // https://github.com/python/cpython/tree/v3.14.4
    // String compilation rechecks presence before selecting the execution
    // builtins; constructing the internal function then reads __name__.
    fn execution_ensure_builtins(&mut self,globals:usize)->PyResult<()> {
        if self.global_name_get(globals,"__builtins__")?.is_none() {
            self.global_name_set(globals,"__builtins__".into(),self.active_builtins.clone())?;
        }
        Ok(())
    }
    fn execution_run_code(&mut self,code:usize,globals:usize,locals:usize,discard:bool)->PyResult<Value> {
        self.view_rooted(vec![Value::Obj(globals),Value::Obj(locals)],|runtime,root|{
            let builtins=runtime.capture_builtins(globals,runtime.active_builtins.clone())?;
            runtime.roots[root].push(builtins.clone());
            let module=runtime.global_name_get(globals,"__name__")?.unwrap_or(Value::None);
            runtime.roots[root].push(module.clone());
            // The internal function owns its metadata for the whole frame,
            // including a generator whose first iteration happens much later.
            let function=Function {
                annotate:None,annotations_evaluated:true,
                attrs:runtime.alloc(Object::Dict(Vec::new())),
                name:Value::Str(runtime.codes[code].name.clone().into()),qualname:Value::Str(runtime.codes[code].qualname.clone().into()),
                module,doc:Value::None,annotations:Value::None,type_params:Value::None,
                code,globals,builtins:builtins.clone(),closure:None,
                defaults:Vec::new(),defaults_set:false,kwdefaults:HashMap::new(),
            };
            let owner=runtime.obj_value(Object::Function(function.clone()));
            runtime.roots[root].push(owner.clone());
            // A code object carries no defaults. Use ordinary argument binding
            // for fresh fast locals and empty *args/**kwargs in function code.
            let frame=if matches!(runtime.codes[code].kind,ScopeKind::Function|ScopeKind::Comprehension) {
                runtime.bind_function(&function,owner,Vec::new(),Vec::new())?
            }else{
                Frame {
                    function:Some(owner),generator_names:None,code_handle:runtime.code_object_index(code),code,pc:0,locals,
                    temps:runtime.alloc(Object::Namespace(OrderedNamespace::new(),None)),
                    globals,builtins,closure:None,stack:Vec::new(),handlers:Vec::new(),pending:Vec::new(),
                    exception:None,exception_stack:Vec::new(),inherited_exception:None,except_star:Vec::new(),
                    next_call:None,cache_returns:Vec::new(),comprehensions:Vec::new(),resume_value:None,injected_exception:None,finally_regions:Vec::new(),
                }
            };
            let value=if runtime.codes[code].is_generator {
                runtime.obj_value(Object::Generator(Box::new(frame)))
            }else{
                match runtime.execute(frame)?.0 {FrameExit::Return(value)|FrameExit::Yield(value)=>value}
            };
            Ok(if discard {Value::None}else{value})
        })
    }
    fn execution_filename(&mut self, value: Value) -> PyResult<String> {
        let mut payload = self.native_payload(&value).unwrap_or_else(|| value.clone());
        if !matches!(payload, Value::Str(_) | Value::Bytes(_)) {
            let method = match self.special_method(value.clone(), "__fspath__") {
                Ok(method) => method,
                Err(error) if self.missing_special_method(&value, "__fspath__", &error) => {
                    return Err(pyerr(
                        "TypeError",
                        format!(
                            "expected str, bytes or os.PathLike object, not {}",
                            self.typename(&value)
                        ),
                    ));
                }
                Err(error) => return Err(error),
            };
            let result = self.call(method, Vec::new(), Vec::new(), None)?;
            payload = self
                .native_payload(&result)
                .unwrap_or_else(|| result.clone());
            if !matches!(payload, Value::Str(_) | Value::Bytes(_)) {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "expected {}.__fspath__() to return str or bytes, not {}",
                        self.typename(&value),
                        self.typename(&result)
                    ),
                ));
            }
        }
        let filename = match payload {
            Value::Str(text) => text.into_inner(),
            Value::Bytes(bytes) => String::from_utf8(bytes.into_inner()).map_err(|_| {
                pyerr(
                    "NotImplementedError",
                    "filenames containing surrogate-escaped bytes are not implemented",
                )
            })?,
            _ => unreachable!(),
        };
        if filename.contains('\0') {
            return Err(pyerr("ValueError", "embedded null character"));
        }
        Ok(filename)
    }
    fn execution_mode(&self, value: Value) -> PyResult<String> {
        let payload = self.native_payload(&value).unwrap_or_else(|| value.clone());
        let Value::Str(text) = payload else {
            return Err(pyerr(
                "TypeError",
                format!(
                    "compile() argument 'mode' must be str, not {}",
                    self.typename(&value)
                ),
            ));
        };
        let mode = text.into_inner();
        if mode.contains('\0') {
            return Err(pyerr("ValueError", "embedded null character"));
        }
        Ok(mode)
    }
    fn execution_globals(
        &self,
        value: &Value,
        caller: Option<&Frame>,
        name: &str,
    ) -> PyResult<usize> {
        if matches!(value, Value::None) {
            return Ok(caller.map(|frame| frame.globals).unwrap_or(self.globals));
        }
        let payload = self.native_payload(value).unwrap_or_else(|| value.clone());
        if let Value::Obj(index) = payload {
            if matches!(
                self.heap.get(index).and_then(Option::as_ref),
                Some(Object::Dict(_) | Object::Namespace(..))
            ) {
                if let Value::Obj(original) = value {
                    return Ok(*original);
                }
            }
        }
        Err(pyerr(
            "TypeError",
            if name == "eval" {
                "globals must be a real dict; try eval(expr, {}, mapping)".into()
            } else {
                format!(
                    "exec() globals must be a dict, not {}",
                    self.typename(value)
                )
            },
        ))
    }
    fn execution_locals(&mut self, value: Value) -> PyResult<usize> {
        let payload = self.native_payload(&value).unwrap_or_else(|| value.clone());
        let native = match &payload {
            Value::Str(_) | Value::Bytes(_) => true,
            Value::Obj(index) => matches!(
                self.heap.get(*index).and_then(Option::as_ref),
                Some(
                    Object::List(_)
                        | Object::Tuple(_)
                        | Object::Dict(_)
                        | Object::Namespace(..)
                        | Object::MappingProxy { .. }
                        | Object::Range(..)
                        | Object::Record { .. }
                )
            ),
            _ => false,
        };
        let custom = self
            .object_class(&value)
            .and_then(|class| self.slot_override(&class, "__getitem__", 0))
            .is_some();
        if native || custom {
            return Ok(match value {
                Value::Obj(index) => index,
                value => self.alloc(Object::ExecutionLocals(value)),
            });
        }
        Err(pyerr(
            "TypeError",
            format!(
                "locals must be a mapping or None, not {}",
                self.typename(&value)
            ),
        ))
    }
    fn execution_locals_value(&self, index: usize) -> Value {
        match self.heap.get(index).and_then(Option::as_ref) {
            Some(Object::ExecutionLocals(value)) => value.clone(),
            _ => Value::Obj(index),
        }
    }
    fn execution_text(&mut self, value: Value, name: &str) -> PyResult<String> {
        let value = self.native_payload(&value).unwrap_or(value);
        match value {
            Value::Str(text) => Ok(text.into_inner()),
            Value::Bytes(bytes) => {
                let bom = bytes.starts_with(b"\xef\xbb\xbf");
                let bytes = if bom {
                    bytes[3..].to_vec()
                } else {
                    bytes.into_inner()
                };
                let (first, remaining) = execution_line(&bytes);
                let can_second = first
                    .iter()
                    .find(|byte| !matches!(byte, b' ' | b'\t' | b'\x0c'))
                    .is_none_or(|byte| *byte == b'#');
                let encoding = execution_cookie(first)
                    .or_else(|| {
                        if can_second {
                            execution_cookie(execution_line(remaining).0)
                        } else {
                            None
                        }
                    })
                    .unwrap_or_else(|| "utf-8".into());
                let codec = TextCodec::lookup(&encoding)
                    .map_err(|_| pyerr("SyntaxError", format!("unknown encoding: {encoding}")))?;
                if bom && !matches!(codec, TextCodec::Utf8) {
                    return Err(pyerr(
                        "SyntaxError",
                        format!("encoding problem: {encoding} with BOM"),
                    ));
                }
                let value = self
                    .codec_decode(
                        Value::Bytes(bytes.into()),
                        vec![Value::Str(codec.name().into())],
                        Vec::new(),
                    )
                    .map_err(|error| {
                        if self.exception_has_native_class(&error, "UnicodeDecodeError") {
                            pyerr("SyntaxError", error.0.message)
                        } else {
                            error
                        }
                    })?;
                match value {
                    Value::Str(text) => Ok(text.into_inner()),
                    _ => unreachable!(),
                }
            }
            _ => Err(pyerr(
                "TypeError",
                format!(
                    "{name}() arg 1 must be a string, bytes or {} object",
                    if name == "compile" { "AST" } else { "code" }
                ),
            )),
        }
    }
}
