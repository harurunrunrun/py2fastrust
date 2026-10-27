// Float and bytes subclasses reuse immutable primitive payloads inside the
// existing stable arena instance, with ordinary C3/descriptor lookup.
fn scalar_parse_float(source: &str, unicode: bool) -> PyResult<f64> {
    let source = source.trim_matches(|ch: char| {
        matches!(ch, '\t'..='\r' | ' ') || (unicode && ch as u32 > 127 && text_space(ch))
    });
    let normalized: String = source
        .chars()
        .map(|ch| {
            if unicode {
                Int::decimal_digit(ch)
                    .filter(|digit| *digit < 10)
                    .map(|digit| (b'0' + digit as u8) as char)
                    .unwrap_or(ch)
            } else {
                ch
            }
        })
        .collect();
    let input = normalized.as_bytes();
    let invalid = || pyerr("ValueError", "could not convert string to float");
    if input.iter().enumerate().any(|(index, ch)| {
        *ch == b'_'
            && (index == 0
                || index + 1 == input.len()
                || !input[index - 1].is_ascii_digit()
                || !input[index + 1].is_ascii_digit())
    }) {
        return Err(invalid());
    }
    let normalized = normalized.replace('_', "");
    let input = normalized.as_bytes();
    let mut at = if matches!(input.first(), Some(b'+' | b'-')) {
        1
    } else {
        0
    };
    if ["inf", "infinity", "nan"].contains(&normalized[at..].to_ascii_lowercase().as_str()) {
        return normalized.parse::<f64>().map_err(|_| invalid());
    }
    let before = at;
    while input.get(at).is_some_and(u8::is_ascii_digit) {
        at += 1;
    }
    let mut digits = at - before;
    if input.get(at) == Some(&b'.') {
        at += 1;
        let before = at;
        while input.get(at).is_some_and(u8::is_ascii_digit) {
            at += 1;
        }
        digits += at - before;
    }
    if digits == 0 {
        return Err(invalid());
    }
    if matches!(input.get(at), Some(b'e' | b'E')) {
        at += 1;
        if matches!(input.get(at), Some(b'+' | b'-')) {
            at += 1;
        }
        let before = at;
        while input.get(at).is_some_and(u8::is_ascii_digit) {
            at += 1;
        }
        if at == before {
            return Err(invalid());
        }
    }
    if at != input.len() {
        return Err(invalid());
    }
    normalized.parse().map_err(|_| invalid())
}
impl Runtime {
    fn scalar_bytes_hex(
        &mut self,
        data: &[u8],
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        let fields = codec_bind("hex", args, kwargs, &["sep", "bytes_per_sep"])?;
        let separator = if let Some(value) = &fields[0] {
            match self.native_payload(value).unwrap_or_else(|| value.clone()) {
                Value::Str(text) if text.chars().count() == 1 && text.is_ascii() => {
                    Some(text.as_bytes()[0])
                }
                Value::Bytes(bytes) if bytes.len() == 1 && bytes[0] < 128 => Some(bytes[0]),
                Value::Str(_) | Value::Bytes(_) => {
                    return Err(pyerr("ValueError", "sep must be length 1 and ASCII"))
                }
                _ => return Err(pyerr("TypeError", "sep must be str or bytes")),
            }
        } else {
            None
        };
        let group = if let Some(value) = &fields[1] {
            self.as_int(value)?
                .to_i128()
                .and_then(|value| i32::try_from(value).ok())
                .ok_or_else(|| pyerr("OverflowError", "bytes_per_sep is outside C int range"))?
        } else {
            1
        };
        let distance = group.unsigned_abs() as usize;
        let mut text = String::new();
        const DIGITS: &[u8] = b"0123456789abcdef";
        for (index, byte) in data.iter().enumerate() {
            if let Some(separator) = separator {
                if index > 0
                    && distance != 0
                    && (if group < 0 {
                        index % distance == 0
                    } else {
                        (data.len() - index) % distance == 0
                    })
                {
                    text.push(separator as char);
                }
            }
            text.push(DIGITS[(byte >> 4) as usize] as char);
            text.push(DIGITS[(byte & 15) as usize] as char);
        }
        Ok(Value::Str(text.into()))
    }
    fn scalar_float_constructor(
        &mut self,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        if args.len() > 1 || !kwargs.is_empty() {
            return Err(pyerr(
                "TypeError",
                "float() takes at most one positional argument",
            ));
        }
        let Some(value) = args.into_iter().next() else {
            return Ok(Value::Float(0.0.into()));
        };
        if matches!(value, Value::Float(_)) {
            return Ok(value);
        }
        self.view_rooted(vec![value.clone()], |runtime, _| {
            match runtime.special_method(value.clone(), "__float__") {
                Ok(method) => {
                    let result = runtime.call(method, Vec::new(), Vec::new(), None)?;
                    if matches!(result, Value::Float(_)) {
                        return Ok(result);
                    }
                    if let Some(Value::Float(number)) = runtime.native_payload(&result) {
                        return Ok(Value::Float(number.into_inner().into()));
                    }
                    return Err(pyerr("TypeError", "__float__ returned non-float"));
                }
                Err(error) if runtime.missing_special_method(&value, "__float__", &error) => (),
                Err(error) => return Err(error),
            }
            let payload = runtime
                .native_payload(&value)
                .unwrap_or_else(|| value.clone());
            match payload {
                Value::Str(text) => {
                    scalar_parse_float(&text, true).map(|number| Value::Float(number.into()))
                }
                Value::Bytes(data) => {
                    let text = std::str::from_utf8(&data)
                        .map_err(|_| pyerr("ValueError", "could not convert bytes to float"))?;
                    scalar_parse_float(text, false).map(|number| Value::Float(number.into()))
                }
                Value::Int(_) | Value::Bool(_) => runtime
                    .as_float(&payload)
                    .map(|number| Value::Float(number.into())),
                _ => {
                    if runtime.object_class(&value).and_then(|class|runtime.slot_definition(&class,"__index__",0)).is_none(){if let Some(data)=runtime.buffer_read(&value,true)?{let text=std::str::from_utf8(&data).map_err(|_|pyerr("ValueError","could not convert buffer to float"))?;return scalar_parse_float(text,false).map(|number|Value::Float(number.into()));}}
                    let number = runtime.as_int(&value)?;
                    runtime
                        .as_float(&Value::Int(number.into()))
                        .map(|number| Value::Float(number.into()))
                }
            }
        })
    }
    fn scalar_bytes_repeat(
        &mut self,
        op: &str,
        left: &Value,
        right: &Value,
    ) -> Option<PyResult<Value>> {
        if op != "*" && op != "*=" {
            return None;
        }
        let (data, count) = match (left, right) {
            (Value::Bytes(data), count) => (data, count),
            (count, Value::Bytes(data)) => (data, count),
            _ => return None,
        };
        Some((|| {
            let count = self.as_int(count)?;
            let count = count
                .to_i128()
                .filter(|count| isize::try_from(*count).is_ok())
                .ok_or_else(|| {
                    pyerr(
                        "OverflowError",
                        "cannot fit repetition count into an index-sized integer",
                    )
                })?
                .max(0) as usize;
            let length = data
                .len()
                .checked_mul(count)
                .filter(|length| *length <= isize::MAX as usize)
                .ok_or_else(|| pyerr("OverflowError", "repeated bytes are too long"))?;
            let mut result = Vec::new();
            result
                .try_reserve_exact(length)
                .map_err(|_| pyerr("MemoryError", "cannot allocate repeated bytes"))?;
            if !data.is_empty() {
                for _ in 0..count {
                    result.extend_from_slice(data);
                }
            }
            Ok(Value::Bytes(result.into()))
        })())
    }
    fn scalar_primitive_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        let owner = match &value {
            Value::Float(_) => "float",
            Value::Bytes(_) => "bytes",
            _ => return None,
        };
        let class = Value::Builtin(owner.into());
        let descriptor = self.native_own_attribute(&class, name)?;
        Some(self.bind_descriptor(descriptor, Some(value), class))
    }
    fn scalar_descriptor_call(
        &mut self,
        owner: &str,
        name: &str,
        receiver: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        if owner != "float" && owner != "bytes" {
            return None;
        }
        let subclass = self.native_payload(&receiver);
        let payload = subclass.clone().unwrap_or_else(|| receiver.clone());
        let known = if owner == "float" {
            [
                "__repr__",
                "__hash__",
                "__neg__",
                "__pos__",
                "__abs__",
                "__bool__",
                "__int__",
                "__float__",
                "conjugate",
                "__trunc__",
                "__floor__",
                "__ceil__",
                "__round__",
                "__getnewargs__",
                "__format__",
            ]
            .contains(&name)
        } else {
            [
                "__repr__",
                "__str__",
                "__hash__",
                "__bytes__",
                "__len__",
                "__iter__",
                "__getitem__",
                "__contains__",
                "__getnewargs__",
                "decode",
                "hex",
            ]
            .contains(&name)
        };
        if !known {
            if let Value::Bytes(bytes) = payload {
                return self.bytes_method(bytes.into_inner(), name, args, kwargs);
            }
            return None;
        }
        Some((|| {
            let maximum =
                if ["__round__", "__format__", "__getitem__", "__contains__"].contains(&name) {
                    1
                } else if name == "decode" || name == "hex" {
                    2
                } else {
                    0
                };
            if name != "decode" && name != "hex" && (!kwargs.is_empty() || args.len() > maximum) {
                return Err(pyerr("TypeError", "invalid scalar descriptor arguments"));
            }
            if ["__format__", "__getitem__", "__contains__"].contains(&name) && args.len() != 1 {
                return Err(pyerr("TypeError", "scalar descriptor requires an argument"));
            }
            match name {
                "__repr__" => self.repr(&payload).map(|text| Value::Str(text.into())),
                "__str__" => self.str_value(&payload).map(|text| Value::Str(text.into())),
                "__hash__" => self.builtin("hash", vec![payload], Vec::new(), None),
                "__float__" | "__bytes__" | "conjugate" => Ok(if subclass.is_some() {
                    payload.fresh_primitive()
                } else {
                    payload
                }),
                "__neg__" => self.unary("-", payload),
                "__pos__" => Ok(if subclass.is_some() {
                    payload.fresh_primitive()
                } else {
                    payload
                }),
                "__abs__" => self.builtin("abs", vec![payload], Vec::new(), None),
                "__bool__" => self.truth(&payload).map(Value::Bool),
                "__int__" | "__trunc__" | "__floor__" | "__ceil__" => {
                    let number = self.as_float(&payload)?;
                    let number = match name {
                        "__floor__" => number.floor(),
                        "__ceil__" => number.ceil(),
                        _ => number.trunc(),
                    };
                    Ok(Value::Int(Int::from_f64(number).map_err(int_error)?.into()))
                }
                "__round__" => {
                    let mut values = vec![payload];
                    values.extend(args);
                    self.builtin("round", values, Vec::new(), None)
                }
                "__format__" => {
                    let spec = self
                        .native_payload(&args[0])
                        .unwrap_or_else(|| args[0].clone());
                    let Value::Str(spec) = spec else {
                        return Err(pyerr("TypeError", "format specifier must be a string"));
                    };
                    self.format_value(payload, &spec)
                        .map(|text| Value::Str(text.into()))
                }
                "__getnewargs__" => {
                    Ok(self.obj_value(Object::Tuple(vec![if subclass.is_some() {
                        payload.fresh_primitive()
                    } else {
                        payload
                    }])))
                }
                "__len__" => self.builtin("len", vec![payload], Vec::new(), None),
                "__iter__" => {
                    let iterator = self.iter(payload)?;
                    Ok(self.collection_keep(iterator, receiver))
                }
                "__getitem__" => self.getitem(payload, args[0].clone()),
                "__contains__" => {
                    let Value::Bytes(bytes) = payload else {
                        return Err(pyerr("TypeError", "expected bytes"));
                    };
                    let needle = self.bytes_needle(&args[0], true)?;
                    Ok(Value::Bool(
                        text_find_slice(&bytes, &needle, false).is_some(),
                    ))
                }
                "decode" => self.codec_decode(payload, args, kwargs),
                "hex" => {
                    let Value::Bytes(bytes) = payload else {
                        return Err(pyerr("TypeError", "expected bytes"));
                    };
                    self.scalar_bytes_hex(&bytes, args, kwargs)
                }
                _ => unreachable!(),
            }
        })())
    }
}
