// Python's binary %-formatting. The format owner stays exported across Python
// callbacks: resizing a bytearray is forbidden, while equal-length changes are
// visible to subsequent directives, as for CPython's live buffer pointer.
fn bytes_percent_argument(arguments: &[Value], cursor: &mut usize) -> PyResult<Value> {
    let value = arguments.get(*cursor).cloned().ok_or_else(|| {
        pyerr("TypeError", "not enough arguments for format string")
    })?;
    *cursor += 1;
    Ok(value)
}

fn bytes_percent_extend(output: &mut Vec<u8>, source: &[u8]) -> PyResult<()> {
    output.try_reserve(source.len()).map_err(|_| {
        pyerr("MemoryError", "cannot allocate formatted bytes")
    })?;
    output.extend_from_slice(source);
    Ok(())
}

fn bytes_percent_padding(output: &mut Vec<u8>, byte: u8, count: usize) -> PyResult<()> {
    let length = output.len().checked_add(count).filter(|n| *n <= isize::MAX as usize)
        .ok_or_else(|| pyerr("OverflowError", "formatted bytes are too long"))?;
    output.try_reserve(count).map_err(|_| pyerr("MemoryError", "cannot allocate formatted bytes"))?;
    output.resize(length, byte);
    Ok(())
}

impl Runtime {
    fn bytes_percent_mapping(&self, value: &Value) -> bool {
        let payload = self.native_payload(value).unwrap_or_else(|| value.clone());
        if matches!(&payload, Value::Str(_) | Value::Bytes(_))
            || self.buffer_kind(&payload) == Some("bytearray") { return false; }
        if let Value::Obj(index) = &payload {
            match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::Tuple(_)) => return false,
                Some(Object::Dict(_) | Object::Namespace(..) | Object::List(_)
                    | Object::Range(..) | Object::MemoryView(_) | Object::MappingProxy{..}) => return true,
                _ => (),
            }
        }
        self.object_class(value).and_then(|class| self.slot_definition(&class,"__getitem__",0)).is_some()
    }

    fn bytes_percent_integer(&mut self, value: Value, decimal: bool) -> PyResult<Int> {
        let payload = self.native_payload(&value).unwrap_or_else(|| value.clone());
        if matches!(&payload, Value::Int(_) | Value::Bool(_)) { return self.as_int(&payload); }
        if !decimal { return self.as_int(&value); }
        if let Value::Float(number) = &value { return Int::from_f64(**number).map_err(int_error); }
        if self.object_class(&value).is_some_and(|class| {
            self.slot_definition(&class,"__int__",0).is_some()
                || self.slot_definition(&class,"__index__",0).is_some()
        }) {
            let converted = self.builtin("int",vec![value],Vec::new(),None)?;
            return self.as_int(&converted);
        }
        Err(pyerr("TypeError", "a real number is required"))
    }

    fn bytes_percent_float(&mut self, value: Value) -> PyResult<f64> {
        let kind = self.typename(&value);
        let result = (|| {
            let payload = self.native_payload(&value).unwrap_or_else(|| value.clone());
            // PyFloat_Check bypasses overrides on float subclasses; integer
            // subclasses still participate in their __float__ protocol.
            if matches!(&payload, Value::Float(_))
                || matches!(&value, Value::Int(_) | Value::Bool(_)) {
                return self.as_float(&payload);
            }
            if self.object_class(&value).is_some_and(|class| {
                self.slot_definition(&class,"__float__",0).is_some()
                    || self.slot_definition(&class,"__index__",0).is_some()
            }) {
                let converted = self.builtin("float",vec![value],Vec::new(),None)?;
                return self.as_float(&converted);
            }
            Err(pyerr("TypeError", "float argument required"))
        })();
        // Binary printf replaces every PyFloat_AsDouble failure, including a
        // callback exception or an overflowing integer, with its TypeError.
        result.map_err(|_| pyerr("TypeError",format!("float argument required, not {kind}")))
    }

    fn bytes_percent_bytes(&mut self, value: Value) -> PyResult<Vec<u8>> {
        let payload = self.native_payload(&value).unwrap_or_else(|| value.clone());
        if let Value::Bytes(bytes) = &payload { return Ok(bytes.to_vec()); }
        if self.buffer_kind(&payload) == Some("bytearray") { return self.buffer_owner_data(&payload); }
        match self.special_method(value.clone(),"__bytes__") {
            Ok(method) => {
                let converted = self.call(method,Vec::new(),Vec::new(),None)?;
                let converted = self.native_payload(&converted).unwrap_or(converted);
                return match converted {
                    Value::Bytes(bytes) => Ok(bytes.to_vec()),
                    _ => Err(pyerr("TypeError", "__bytes__ returned non-bytes")),
                };
            }
            Err(error) if self.missing_special_method(&value,"__bytes__",&error) => (),
            Err(error) => return Err(error),
        }
        self.buffer_read(&value,false)?.ok_or_else(|| {
            pyerr("TypeError", "%b requires a bytes-like object or __bytes__")
        })
    }

    fn bytes_percent_format(&mut self, format: Value, values: Value) -> PyResult<Value> {
        let mutable = self.buffer_kind(&format) == Some("bytearray");
        let view = self.buffer_memoryview(format.clone(),0)?;
        let result = self.view_rooted(vec![format.clone(),values.clone(),view.clone()],|runtime,root| {
            let result = runtime.bytes_percent_inner(format,values,root)?;
            Ok(if mutable { runtime.obj_value(Object::ByteArray(result)) }
                else { Value::Bytes(result.into()) })
        });
        let released = self.buffer_release(view);
        match result { Ok(result) => { released?; Ok(result) }, Err(error) => Err(error) }
    }

    fn bytes_percent_inner(&mut self, format: Value, values: Value, root: usize) -> PyResult<Vec<u8>> {
        let mut source = self.buffer_owner_data(&format)?;
        let mapping = if self.bytes_percent_mapping(&values) { Some(values.clone()) } else { None };
        let payload = self.native_payload(&values).unwrap_or_else(|| values.clone());
        let mut arguments = match payload {
            Value::Obj(index) => match self.heap.get(index).and_then(Option::as_ref) {
                Some(Object::Tuple(items)) => items.clone(), _ => vec![values],
            },
            _ => vec![values],
        };
        let mut cursor = 0;
        let mut position = 0;
        let mut output = Vec::new();
        while position < source.len() {
            if source[position] != b'%' {
                bytes_percent_extend(&mut output,&source[position..position+1])?;
                position += 1;
                continue;
            }
            position += 1;
            if source.get(position) == Some(&b'%') {
                bytes_percent_extend(&mut output,b"%")?;
                position += 1;
                continue;
            }
            if source.get(position) == Some(&b'(') {
                let mapping = mapping.as_ref().ok_or_else(|| pyerr("TypeError","format requires a mapping"))?;
                let start = position + 1;
                position += 1;
                let mut nesting = 1usize;
                while position < source.len() && nesting != 0 {
                    match source[position] { b'(' => nesting += 1, b')' => nesting -= 1, _ => () }
                    position += 1;
                }
                if nesting != 0 { return Err(pyerr("ValueError","incomplete format key")); }
                let key = Value::Bytes(source[start..position-1].to_vec().into());
                let value = self.getitem(mapping.clone(),key)?;
                self.roots[root].push(value.clone());
                arguments = vec![value]; cursor = 0;
                source = self.buffer_owner_data(&format)?;
            }
            let (mut left,mut zero,mut alternate,mut plus,mut space) = (false,false,false,false,false);
            while let Some(byte) = source.get(position) {
                match byte { b'-'=>left=true,b'0'=>zero=true,b'#'=>alternate=true,b'+'=>plus=true,b' '=>space=true,_=>break }
                position += 1;
            }
            let mut width = 0usize;
            if source.get(position) == Some(&b'*') {
                position += 1;
                let value = bytes_percent_argument(&arguments,&mut cursor)?;
                let payload = self.native_payload(&value).unwrap_or(value);
                if !matches!(&payload,Value::Int(_) | Value::Bool(_)) { return Err(pyerr("TypeError","* wants int")); }
                let number = self.as_int(&payload)?.to_i128().filter(|n|isize::try_from(*n).is_ok())
                    .ok_or_else(||pyerr("OverflowError","Python int too large to convert to C ssize_t"))?;
                left |= number < 0;
                // CPython leaves a C ssize_t minimum width as a zero-width left field.
                width = if number == isize::MIN as i128 { 0 } else { number.abs() as usize };
            } else {
                while let Some(byte @ b'0'..=b'9') = source.get(position) {
                    width = width.checked_mul(10).and_then(|n|n.checked_add((byte-b'0') as usize))
                        .filter(|n|*n<=isize::MAX as usize).ok_or_else(||pyerr("ValueError","width too big"))?;
                    position += 1;
                }
            }
            let mut precision = None;
            if source.get(position) == Some(&b'.') {
                position += 1;
                let mut digits = 0usize;
                if source.get(position) == Some(&b'*') {
                    position += 1;
                    let value = bytes_percent_argument(&arguments,&mut cursor)?;
                    let payload = self.native_payload(&value).unwrap_or(value);
                    if !matches!(&payload,Value::Int(_) | Value::Bool(_)) { return Err(pyerr("TypeError","* wants int")); }
                    digits = self.as_int(&payload)?.to_i128().filter(|n|i32::try_from(*n).is_ok())
                        .ok_or_else(||pyerr("OverflowError","Python int too large to convert to C int"))?.max(0) as usize;
                } else {
                    while let Some(byte @ b'0'..=b'9') = source.get(position) {
                        digits = digits.checked_mul(10).and_then(|n|n.checked_add((byte-b'0') as usize))
                            .filter(|n|*n<=i32::MAX as usize).ok_or_else(||pyerr("ValueError","precision too big"))?;
                        position += 1;
                    }
                }
                precision = Some(digits);
            }
            if source.get(position).is_some_and(|byte|matches!(byte,b'h'|b'l'|b'L')) { position += 1; }
            let kind = *source.get(position).ok_or_else(||pyerr("ValueError","incomplete format"))?;
            position += 1;
            let value = bytes_percent_argument(&arguments,&mut cursor)?;
            self.roots[root].push(value.clone());
            let numeric = b"diuoxXeEfFgG".contains(&kind);
            let mut field = match kind {
                b'b' | b's' => self.bytes_percent_bytes(value)?,
                b'a' | b'r' => text_ascii_escape(&self.repr(&value)?).into_bytes(),
                b'c' => {
                    let payload = self.native_payload(&value).unwrap_or_else(||value.clone());
                    let bytes = if let Value::Bytes(bytes) = &payload { Some(bytes.to_vec()) }
                        else if self.buffer_kind(&payload)==Some("bytearray") { Some(self.buffer_owner_data(&payload)?) } else { None };
                    if let Some(bytes) = bytes {
                        if bytes.len()!=1 { return Err(pyerr("TypeError","%c requires an integer in range(256) or a single byte")); }
                        bytes
                    } else {
                        let byte = self.as_int(&value)?.to_usize().filter(|n|*n<=255)
                            .ok_or_else(||pyerr("OverflowError","%c arg not in range(256)"))?;
                        vec![byte as u8]
                    }
                }
                b'd' | b'i' | b'u' | b'o' | b'x' | b'X' => {
                    let number = self.bytes_percent_integer(value,matches!(kind,b'd'|b'i'|b'u'))?;
                    let magnitude = Int::exact_parts(false,number.magnitude().into_owned());
                    let presentation = match kind { b'o'=>"o",b'x'=>"x",b'X'=>"X",_=>"d" };
                    let digits = magnitude.format_integer(presentation).map_err(int_error)?.unwrap();
                    let mut field = Vec::new();
                    if number.is_negative(){field.push(b'-');}else if plus{field.push(b'+');}else if space{field.push(b' ');}
                    if alternate { match kind {b'o'=>bytes_percent_extend(&mut field,b"0o")?,b'x'=>bytes_percent_extend(&mut field,b"0x")?,b'X'=>bytes_percent_extend(&mut field,b"0X")?,_=>()} }
                    bytes_percent_padding(&mut field,b'0',precision.unwrap_or(0).saturating_sub(digits.len()))?;
                    bytes_percent_extend(&mut field,digits.as_bytes())?;
                    field
                }
                b'e' | b'E' | b'f' | b'F' | b'g' | b'G' => {
                    let number = self.bytes_percent_float(value)?;
                    let mut specification = String::new();
                    if plus { specification.push('+'); } else if space { specification.push(' '); }
                    if alternate { specification.push('#'); }
                    specification.push('.'); specification.push_str(&precision.unwrap_or(6).to_string());
                    specification.push(kind as char);
                    text_format_float(number,&TextFormatSpec::parse(&specification,true)?)?.into_bytes()
                }
                _ => return Err(if kind>=128 { pyerr("OverflowError","character argument not in range(0x110000)") }
                    else { pyerr("ValueError",format!("unsupported format character '{}' (0x{kind:x}) at index {}",kind as char,position-1)) }),
            };
            if !numeric && kind!=b'c' { if let Some(precision)=precision { field.truncate(precision); } }
            let padding = width.saturating_sub(field.len());
            if left {
                bytes_percent_extend(&mut output,&field)?;
                bytes_percent_padding(&mut output,b' ',padding)?;
            } else if zero && numeric {
                let sign = usize::from(field.first().is_some_and(|byte|matches!(byte,b'-'|b'+'|b' ')));
                let prefix = if field.get(sign)==Some(&b'0') && field.get(sign+1).is_some_and(|byte|matches!(byte,b'x'|b'X'|b'o')) {2} else {0};
                bytes_percent_extend(&mut output,&field[..sign+prefix])?;
                bytes_percent_padding(&mut output,b'0',padding)?;
                bytes_percent_extend(&mut output,&field[sign+prefix..])?;
            } else {
                bytes_percent_padding(&mut output,b' ',padding)?;
                bytes_percent_extend(&mut output,&field)?;
            }
            self.roots[root].pop();
            source = self.buffer_owner_data(&format)?;
        }
        if mapping.is_none() && cursor < arguments.len() {
            return Err(pyerr("TypeError","not all arguments converted during bytes formatting"));
        }
        Ok(output)
    }
}
