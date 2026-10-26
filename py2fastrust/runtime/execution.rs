// compile/eval/exec argument validation. Source syntax uses the shared PEG.
fn execution_parameters(
    name: &str,
    args: &[Value],
    kwargs: &[(String, Value)],
) -> PyResult<[Value; 4]> {
    if args.is_empty() {
        return Err(pyerr(
            "TypeError",
            format!("{name}() takes at least 1 positional argument (0 given)"),
        ));
    }
    if args.len() > 3 {
        return Err(pyerr(
            "TypeError",
            format!("{name}() takes at most 3 arguments ({} given)", args.len()),
        ));
    }
    let mut result = [args[0].clone(), Value::None, Value::None, Value::None];
    let mut seen = [true, false, false, false];
    for (index, value) in args.iter().enumerate().skip(1) {
        result[index] = value.clone();
        seen[index] = true;
    }
    for (key, value) in kwargs {
        let index = match key.as_str() {
            "globals" => 1,
            "locals" => 2,
            "closure" if name == "exec" => 3,
            _ => {
                return Err(pyerr(
                    "TypeError",
                    format!("{name}() got an unexpected keyword argument '{key}'"),
                ))
            }
        };
        if seen[index] {
            return Err(pyerr(
                "TypeError",
                format!("{name}() got multiple values for argument '{key}'"),
            ));
        }
        seen[index] = true;
        result[index] = value.clone();
    }
    Ok(result)
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
    fn execution_function_frame(&mut self, code: usize, globals: usize) -> PyResult<Frame> {
        // A code object carries no defaults. Reuse ordinary argument binding
        // for fresh fast locals and empty *args/**kwargs when executing it.
        let function = Function {
            annotate: None,
            annotations_evaluated: true,
            attrs: self.builtins,
            name: self.codes[code].name.clone().into(),
            qualname: self.codes[code].name.clone().into(),
            module: Value::None,
            doc: Value::None,
            annotations: Value::None,
            type_params: Value::None,
            code,
            globals,
            closure: None,
            defaults: Vec::new(),
            kwdefaults: HashMap::new(),
        };
        self.bind_function(&function, Vec::new(), Vec::new())
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
            .and_then(|class| self.class_lookup(&class, "__getitem__", 0))
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
