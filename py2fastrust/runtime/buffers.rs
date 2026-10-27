// Mutable buffer owners and shared, strided buffer leases. All references are
// stable arena handles and participate in the same collector as other values.
#[derive(Clone, Debug)]
struct MemoryViewData {
    lease: usize,
    offset: isize,
    shape: Vec<usize>,
    strides: Vec<isize>,
    format: String,
    itemsize: usize,
    readonly: bool,
    released: bool,
    exports: usize,
    hash: Option<Int>,
}
#[derive(Clone, Debug)]
struct BufferLeaseData {
    owner: Value,
    obj: Value,
    exporter: Option<Value>,
    exported_view: Option<Value>,
    active: bool,
    native_export: bool,
}
fn buffer_format(format: &str) -> PyResult<(char, usize)> {
    let plain = format.strip_prefix('@').unwrap_or(format);
    let mut chars = plain.chars();
    let code = chars.next().ok_or_else(|| {
        pyerr(
            "ValueError",
            "destination format must be a native single character format",
        )
    })?;
    if chars.next().is_some() {
        return Err(pyerr(
            "ValueError",
            "destination format must be a native single character format",
        ));
    }
    let size = match code {
        'B' | 'b' | 'c' | '?' => 1,
        'h' | 'H' | 'e' => 2,
        'i' | 'I' | 'f' => 4,
        'q' | 'Q' | 'd' => 8,
        'l' | 'L' => std::mem::size_of::<std::os::raw::c_long>(),
        'n' | 'N' | 'P' => std::mem::size_of::<usize>(),
        _ => {
            return Err(pyerr(
                "ValueError",
                "destination format must be a native single character format",
            ))
        }
    };
    Ok((code, size))
}
fn buffer_native_kind(owner: &str, name: &str) -> Option<&'static str> {
    if owner == "bytes" && name == "__buffer__" {
        return Some("method");
    }
    if owner != "bytearray" && owner != "memoryview" {
        return None;
    }
    if name == "__new__" {
        return Some("new");
    }
    if owner == "bytearray" {
        if name == "__hash__" {
            return Some("none");
        }
        if name == "fromhex" {
            return Some("class");
        }
        if name == "maketrans" {
            return Some("static");
        }
        if [
            "__init__",
            "__repr__",
            "__str__",
            "__lt__",
            "__le__",
            "__eq__",
            "__ne__",
            "__gt__",
            "__ge__",
            "__iter__",
            "__len__",
            "__getitem__",
            "__setitem__",
            "__delitem__",
            "__add__",
            "__mul__",
            "__rmul__",
            "__iadd__",
            "__imul__",
            "__contains__",
            "__mod__",
            "__rmod__",
        ]
        .contains(&name)
        {
            return Some("wrapper");
        }
        if [
            "append",
            "capitalize",
            "center",
            "clear",
            "copy",
            "count",
            "decode",
            "endswith",
            "expandtabs",
            "extend",
            "find",
            "hex",
            "index",
            "insert",
            "isalnum",
            "isalpha",
            "isascii",
            "isdigit",
            "islower",
            "isspace",
            "istitle",
            "isupper",
            "join",
            "ljust",
            "lower",
            "lstrip",
            "partition",
            "pop",
            "remove",
            "removeprefix",
            "removesuffix",
            "replace",
            "resize",
            "reverse",
            "rfind",
            "rindex",
            "rjust",
            "rpartition",
            "rsplit",
            "rstrip",
            "split",
            "splitlines",
            "startswith",
            "strip",
            "swapcase",
            "title",
            "translate",
            "upper",
            "zfill",
            "__buffer__",
            "__release_buffer__",
        ]
        .contains(&name)
        {
            return Some("method");
        }
    } else {
        if [
            "c_contiguous",
            "f_contiguous",
            "contiguous",
            "format",
            "itemsize",
            "nbytes",
            "ndim",
            "obj",
            "readonly",
            "shape",
            "strides",
            "suboffsets",
        ]
        .contains(&name)
        {
            return Some("member");
        }
        if [
            "__len__",
            "__getitem__",
            "__setitem__",
            "__delitem__",
            "__iter__",
            "__hash__",
            "__eq__",
            "__ne__",
        ]
        .contains(&name)
        {
            return Some("wrapper");
        }
        if [
            "cast",
            "count",
            "hex",
            "index",
            "release",
            "tobytes",
            "tolist",
            "toreadonly",
            "__enter__",
            "__exit__",
            "__buffer__",
            "__release_buffer__",
        ]
        .contains(&name)
        {
            return Some("method");
        }
    }
    None
}
fn buffer_half_read(bits: u16) -> f64 {
    let sign = if bits & 0x8000 != 0 { -1.0 } else { 1.0 };
    let exponent = (bits >> 10) & 31;
    let fraction = bits & 1023;
    sign * if exponent == 0 {
        (fraction as f64) * 2.0f64.powi(-24)
    } else if exponent == 31 {
        if fraction == 0 {
            f64::INFINITY
        } else {
            f64::NAN
        }
    } else {
        (1024 + fraction) as f64 * 2.0f64.powi(exponent as i32 - 25)
    }
}
fn buffer_half_write(value: f64) -> PyResult<u16> {
    let sign = if value.is_sign_negative() { 0x8000 } else { 0 };
    let magnitude = value.abs();
    if magnitude.is_nan() {
        return Ok(sign | 0x7e00);
    }
    if magnitude.is_infinite() {
        return Ok(sign | 0x7c00);
    }
    if magnitude < 2.0f64.powi(-14) {
        return Ok(sign | (magnitude * 2.0f64.powi(24)).round_ties_even() as u16);
    }
    let mut exponent = ((magnitude.to_bits() >> 52) & 2047) as i32 - 1023;
    let mut significand = (magnitude / 2.0f64.powi(exponent - 10)).round_ties_even() as u32;
    if significand == 2048 {
        significand = 1024;
        exponent += 1;
    }
    if exponent > 15 {
        return Err(pyerr(
            "ValueError",
            "memoryview: invalid value for format 'e'",
        ));
    }
    Ok(sign | (((exponent + 15) as u16) << 10) | ((significand - 1024) as u16))
}
impl Runtime {
    fn buffer_requested_view(mut view: MemoryViewData, flags: i128) -> PyResult<MemoryViewData> {
        if flags & 1 != 0 && view.readonly {
            return Err(pyerr("BufferError", "underlying buffer is not writable"));
        }
        let c = Self::buffer_contiguous(&view, false);
        let f = Self::buffer_contiguous(&view, true);
        if (flags & 0x38 == 0x38 && !c)
            || (flags & 0x58 == 0x58 && !f)
            || (flags & 0x98 == 0x98 && !c && !f)
            || (flags & 0x18 != 0x18 && !c)
        {
            return Err(pyerr("BufferError", "underlying buffer is not contiguous"));
        }
        if flags & 8 == 0 {
            if flags & 4 != 0 {
                return Err(pyerr("BufferError", "cannot request format without dimensions"));
            }
            view.shape = vec![view.shape.iter().product()];
            view.strides = vec![view.itemsize as isize];
        }
        if flags & 4 == 0 {
            view.format = "B".into();
        }
        Ok(view)
    }
    fn buffer_export(&mut self, source: Value, payload: Value, flags: &Value) -> PyResult<Value> {
        let flags = self.as_int(flags)?.to_i128()
            .filter(|flags| i32::try_from(*flags).is_ok())
            .ok_or_else(|| pyerr("OverflowError", "buffer flags out of range"))?;
        if self.buffer_kind(&payload) == Some("memoryview") {
            let mut view = Self::buffer_requested_view(self.buffer_view(&payload)?, flags)?;
            let previous = self.buffer_lease(view.lease)?;
            if let Value::Obj(index) = &payload {
                if let Some(Object::MemoryView(original)) = self.heap[*index].as_mut() {
                    original.exports += 1;
                }
            }
            view.lease = self.alloc(Object::BufferLease(Box::new(BufferLeaseData {
                owner: previous.owner,
                obj: source,
                exporter: None,
                exported_view: Some(payload),
                active: true,
                native_export: false,
            })));
            view.exports = 0;
            view.hash = None;
            return Ok(self.obj_value(Object::MemoryView(Box::new(view))));
        }
        if flags & 1 != 0 && matches!(payload, Value::Bytes(_)) {
            return Err(pyerr("BufferError", "underlying buffer is not writable"));
        }
        if flags == 256 || flags == 512 {
            return Err(pyerr("SystemError", "bad argument to internal function"));
        }
        self.buffer_new_native_view(source, payload)
    }
    fn buffer_release_from(&mut self, owner: Value, value: Value) -> PyResult<()> {
        let view = self.buffer_view(&value)?;
        let lease = self.buffer_lease(view.lease)?;
        if !owner.same_identity(&lease.obj) {
            return Err(pyerr("ValueError", "memoryview's buffer is not this object"));
        }
        self.buffer_release(value)
    }
    fn buffer_mutating_method(
        &mut self,
        value: &Value,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        if ![
            "append", "extend", "insert", "pop", "remove", "clear", "reverse", "resize",
        ]
        .contains(&name)
        {
            return None;
        }
        Some((|| {
            let Value::Obj(owner) = value else {
                return Err(pyerr("TypeError", "expected bytearray"));
            };
            let owner = *owner;
            self.text_arity(
                name,
                &args,
                &kwargs,
                if ["clear", "reverse", "pop"].contains(&name) {
                    0
                } else {
                    1
                },
                if name == "insert" {
                    2
                } else if ["clear", "reverse"].contains(&name) {
                    0
                } else {
                    1
                },
            )?;
            if name == "insert" && args.len() != 2 {
                return Err(pyerr("TypeError", "insert requires two arguments"));
            }
            let mut result = Value::None;
            match name {
                "append" => {
                    let byte = self.buffer_byte(&args[0])?;
                    self.buffer_check_resize(owner)?;
                    let Some(Object::ByteArray(data)) = self.heap[owner].as_mut() else {
                        unreachable!()
                    };
                    data.try_reserve(1)
                        .map_err(|_| pyerr("MemoryError", "cannot extend bytearray"))?;
                    data.push(byte);
                }
                "extend" => {
                    let extra = self.buffer_sequence(args[0].clone())?;
                    if !extra.is_empty() {
                        self.buffer_check_resize(owner)?;
                    }
                    let Some(Object::ByteArray(data)) = self.heap[owner].as_mut() else {
                        unreachable!()
                    };
                    data.len()
                        .checked_add(extra.len())
                        .filter(|length| *length <= isize::MAX as usize)
                        .ok_or_else(|| pyerr("OverflowError", "bytearray is too large"))?;
                    data.try_reserve(extra.len())
                        .map_err(|_| pyerr("MemoryError", "cannot extend bytearray"))?;
                    data.extend(extra);
                }
                "insert" => {
                    let position = self
                        .as_int(&args[0])?
                        .to_i128()
                        .filter(|position| isize::try_from(*position).is_ok())
                        .ok_or_else(|| pyerr("OverflowError", "index out of range"))?;
                    let byte = self.buffer_byte(&args[1])?;
                    self.buffer_check_resize(owner)?;
                    let Some(Object::ByteArray(data)) = self.heap[owner].as_mut() else {
                        unreachable!()
                    };
                    let at = if position < 0 {
                        position.saturating_add(data.len() as i128)
                    } else {
                        position
                    }
                    .clamp(0, data.len() as i128) as usize;
                    data.try_reserve(1)
                        .map_err(|_| pyerr("MemoryError", "cannot extend bytearray"))?;
                    data.insert(at, byte);
                }
                "pop" => {
                    let key = args
                        .first()
                        .cloned()
                        .unwrap_or(Value::Int(Int::from_i128(-1).into()));
                    let key = self.as_int(&key)?;
                    let length = self.buffer_owner_slice(value)?.len();
                    let at = self.index(&Value::Int(key.into()), length)?;
                    self.buffer_check_resize(owner)?;
                    let Some(Object::ByteArray(data)) = self.heap[owner].as_mut() else {
                        unreachable!()
                    };
                    if at >= data.len() {
                        return Err(pyerr("IndexError", "pop index out of range"));
                    }
                    result = Value::Int(Int::from_i128(data.remove(at) as i128).into());
                }
                "remove" => {
                    let byte = self.buffer_byte(&args[0])?;
                    let at = self
                        .buffer_owner_slice(value)?
                        .iter()
                        .position(|item| *item == byte)
                        .ok_or_else(|| pyerr("ValueError", "value not found in bytearray"))?;
                    self.buffer_check_resize(owner)?;
                    let Some(Object::ByteArray(data)) = self.heap[owner].as_mut() else {
                        unreachable!()
                    };
                    if data.get(at) != Some(&byte) {
                        return Err(pyerr("ValueError", "bytearray changed during remove"));
                    }
                    data.remove(at);
                }
                "clear" => {
                    if !self.buffer_owner_slice(value)?.is_empty() {
                        self.buffer_check_resize(owner)?;
                    }
                    let Some(Object::ByteArray(data)) = self.heap[owner].as_mut() else {
                        unreachable!()
                    };
                    data.clear();
                }
                "reverse" => {
                    let Some(Object::ByteArray(data)) = self.heap[owner].as_mut() else {
                        unreachable!()
                    };
                    data.reverse();
                }
                "resize" => {
                    let count = self.as_int(&args[0])?;
                    if count.is_negative() {
                        return Err(pyerr("ValueError", "size must be non-negative"));
                    }
                    let count = count
                        .to_usize()
                        .filter(|count| *count <= isize::MAX as usize)
                        .ok_or_else(|| pyerr("OverflowError", "size out of range"))?;
                    if count != self.buffer_owner_slice(value)?.len() {
                        self.buffer_check_resize(owner)?;
                    }
                    let Some(Object::ByteArray(data)) = self.heap[owner].as_mut() else {
                        unreachable!()
                    };
                    if count > data.len() {
                        data.try_reserve_exact(count - data.len())
                            .map_err(|_| pyerr("MemoryError", "cannot resize bytearray"))?;
                    }
                    data.resize(count, 0);
                }
                _ => unreachable!(),
            }
            Ok(result)
        })())
    }
    fn buffer_owner_slice<'a>(&'a self, owner: &'a Value) -> PyResult<&'a [u8]> {
        match owner {
            Value::Bytes(data) => Ok(data),
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::ByteArray(data)) => Ok(data),
                _ => Err(pyerr("TypeError", "invalid buffer owner")),
            },
            _ => Err(pyerr("TypeError", "invalid buffer owner")),
        }
    }
    fn buffer_fromhex(
        &mut self,
        class: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        self.text_arity("fromhex", &args, &kwargs, 1, 1)?;
        let source = self
            .native_payload(&args[0])
            .unwrap_or_else(|| args[0].clone());
        let input = match source {
            Value::Str(text) => text.as_bytes().to_vec(),
            _ => self.buffer_read(&args[0], true)?.ok_or_else(|| {
                pyerr(
                    "TypeError",
                    "fromhex argument must be str or ASCII bytes-like object",
                )
            })?,
        };
        let mut data = Vec::new();
        let mut at = 0;
        while at < input.len() {
            if bytes_space(input[at]) {
                at += 1;
                continue;
            }
            let high = (input[at] as char).to_digit(16).ok_or_else(|| {
                pyerr(
                    "ValueError",
                    format!("non-hexadecimal number found at position {at}"),
                )
            })?;
            at += 1;
            let low = input
                .get(at)
                .and_then(|byte| (*byte as char).to_digit(16))
                .ok_or_else(|| {
                    pyerr(
                        "ValueError",
                        format!("non-hexadecimal number found at position {at}"),
                    )
                })?;
            data.push((high * 16 + low) as u8);
            at += 1;
        }
        if Self::same_type(&class, &Value::Builtin("bytearray".into())) {
            Ok(self.obj_value(Object::ByteArray(data)))
        } else {
            self.call(class, vec![Value::Bytes(data.into())], Vec::new(), None)
        }
    }
    fn buffer_maketrans(&mut self, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        self.text_arity("maketrans", &args, &kwargs, 2, 2)?;
        let first = self
            .buffer_read(&args[0], true)?
            .ok_or_else(|| pyerr("TypeError", "expected bytes-like argument"))?;
        let second = self
            .buffer_read(&args[1], true)?
            .ok_or_else(|| pyerr("TypeError", "expected bytes-like argument"))?;
        if first.len() != second.len() {
            return Err(pyerr(
                "ValueError",
                "maketrans arguments must have same length",
            ));
        }
        let mut table: Vec<u8> = (0..=255).collect();
        for (first, second) in first.into_iter().zip(second) {
            table[first as usize] = second;
        }
        Ok(Value::Bytes(table.into()))
    }
    fn buffer_ascii_method(
        &mut self,
        value: &Value,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        let names = [
            "lower",
            "upper",
            "swapcase",
            "capitalize",
            "title",
            "isascii",
            "isalpha",
            "isalnum",
            "isdigit",
            "isspace",
            "islower",
            "isupper",
            "istitle",
            "ljust",
            "rjust",
            "center",
            "zfill",
            "expandtabs",
            "splitlines",
            "partition",
            "rpartition",
            "removeprefix",
            "removesuffix",
            "translate",
        ];
        if !names.contains(&name) {
            return None;
        }
        Some((|| {
            if [
                "lower",
                "upper",
                "swapcase",
                "capitalize",
                "title",
                "isascii",
                "isalpha",
                "isalnum",
                "isdigit",
                "isspace",
                "islower",
                "isupper",
                "istitle",
            ]
            .contains(&name)
            {
                self.text_arity(name, &args, &kwargs, 0, 0)?;
                let mut data = self.buffer_owner_data(value)?;
                if name.starts_with("is") {
                    let valid = match name {
                        "isascii" => data.is_ascii(),
                        "isalpha" => !data.is_empty() && data.iter().all(u8::is_ascii_alphabetic),
                        "isalnum" => !data.is_empty() && data.iter().all(u8::is_ascii_alphanumeric),
                        "isdigit" => !data.is_empty() && data.iter().all(u8::is_ascii_digit),
                        "isspace" => !data.is_empty() && data.iter().all(|byte| bytes_space(*byte)),
                        "islower" => {
                            data.iter().any(u8::is_ascii_lowercase)
                                && !data.iter().any(u8::is_ascii_uppercase)
                        }
                        "isupper" => {
                            data.iter().any(u8::is_ascii_uppercase)
                                && !data.iter().any(u8::is_ascii_lowercase)
                        }
                        _ => {
                            let mut previous = false;
                            let mut cased = false;
                            let mut valid = true;
                            for byte in &data {
                                if byte.is_ascii_alphabetic() {
                                    cased = true;
                                    if byte.is_ascii_uppercase() == previous {
                                        valid = false;
                                        break;
                                    }
                                    previous = true;
                                } else {
                                    previous = false;
                                }
                            }
                            valid && cased
                        }
                    };
                    return Ok(Value::Bool(valid));
                }
                let mut previous = false;
                for (index, byte) in data.iter_mut().enumerate() {
                    let cased = byte.is_ascii_alphabetic();
                    *byte = match name {
                        "lower" => byte.to_ascii_lowercase(),
                        "upper" => byte.to_ascii_uppercase(),
                        "swapcase" => {
                            if byte.is_ascii_lowercase() {
                                byte.to_ascii_uppercase()
                            } else {
                                byte.to_ascii_lowercase()
                            }
                        }
                        "capitalize" => {
                            if index == 0 {
                                byte.to_ascii_uppercase()
                            } else {
                                byte.to_ascii_lowercase()
                            }
                        }
                        _ => {
                            if previous {
                                byte.to_ascii_lowercase()
                            } else {
                                byte.to_ascii_uppercase()
                            }
                        }
                    };
                    previous = cased;
                }
                return Ok(self.obj_value(Object::ByteArray(data)));
            }
            if ["ljust", "rjust", "center", "zfill"].contains(&name) {
                self.text_arity(name, &args, &kwargs, 1, if name == "zfill" { 1 } else { 2 })?;
                let width = self
                    .as_int(&args[0])?
                    .to_i128()
                    .filter(|width| isize::try_from(*width).is_ok())
                    .ok_or_else(|| pyerr("OverflowError", "width out of range"))?
                    .max(0) as usize;
                let fill = if let Some(fill) = args.get(1) {
                    let fill = self.buffer_read(fill, true)?.ok_or_else(|| {
                        pyerr(
                            "TypeError",
                            "fill character must be a byte string of length 1",
                        )
                    })?;
                    if fill.len() != 1 {
                        return Err(pyerr(
                            "TypeError",
                            "fill character must be a byte string of length 1",
                        ));
                    }
                    fill[0]
                } else {
                    if name == "zfill" {
                        b'0'
                    } else {
                        b' '
                    }
                };
                let data = self.buffer_owner_data(value)?;
                let padding = width.saturating_sub(data.len());
                let mut result = Vec::new();
                result
                    .try_reserve_exact(width.max(data.len()))
                    .map_err(|_| pyerr("MemoryError", "cannot allocate padded bytearray"))?;
                if name == "zfill" {
                    let sign = data.first().is_some_and(|byte| [b'+', b'-'].contains(byte));
                    if sign {
                        result.push(data[0]);
                    }
                    result.extend(std::iter::repeat(fill).take(padding));
                    result.extend_from_slice(&data[usize::from(sign)..]);
                } else {
                    let left = match name {
                        "rjust" => padding,
                        "center" => padding / 2 + usize::from(padding % 2 != 0 && width % 2 != 0),
                        _ => 0,
                    };
                    result.extend(std::iter::repeat(fill).take(left));
                    result.extend_from_slice(&data);
                    result.extend(std::iter::repeat(fill).take(padding - left));
                }
                return Ok(self.obj_value(Object::ByteArray(result)));
            }
            if name == "expandtabs" {
                let fields = codec_bind(name, args, kwargs, &["tabsize"])?;
                let size = if let Some(size) = &fields[0] {
                    self.as_int(size)?
                        .to_i128()
                        .and_then(|size| i32::try_from(size).ok())
                        .ok_or_else(|| pyerr("OverflowError", "tabsize out of C int range"))?
                        .max(0) as usize
                } else {
                    8
                };
                let data = self.buffer_owner_data(value)?;
                let mut result = Vec::new();
                let mut column = 0usize;
                for byte in data {
                    if byte == b'\t' {
                        let padding = if size == 0 { 0 } else { size - column % size };
                        result
                            .try_reserve(padding)
                            .map_err(|_| pyerr("MemoryError", "expanded bytearray is too large"))?;
                        result.extend(std::iter::repeat(b' ').take(padding));
                        column = column
                            .checked_add(padding)
                            .ok_or_else(|| pyerr("OverflowError", "expanded line is too large"))?;
                    } else {
                        result.push(byte);
                        column = if [b'\r', b'\n'].contains(&byte) {
                            0
                        } else {
                            column.checked_add(1).ok_or_else(|| {
                                pyerr("OverflowError", "expanded line is too large")
                            })?
                        };
                    }
                }
                return Ok(self.obj_value(Object::ByteArray(result)));
            }
            if name == "splitlines" {
                let fields = codec_bind(name, args, kwargs, &["keepends"])?;
                let keep = fields[0]
                    .as_ref()
                    .map(|value| self.truth(value))
                    .transpose()?
                    .unwrap_or(false);
                let data = self.buffer_owner_data(value)?;
                let mut parts = Vec::new();
                let mut start = 0;
                let mut at = 0;
                while at < data.len() {
                    if [b'\r', b'\n'].contains(&data[at]) {
                        let end = at;
                        at += 1;
                        if data[end] == b'\r' && data.get(at) == Some(&b'\n') {
                            at += 1;
                        }
                        parts.push(self.obj_value(Object::ByteArray(
                            data[start..if keep { at } else { end }].to_vec(),
                        )));
                        start = at;
                    } else {
                        at += 1;
                    }
                }
                if start < data.len() {
                    parts.push(self.obj_value(Object::ByteArray(data[start..].to_vec())));
                }
                return Ok(self.obj_value(Object::List(parts)));
            }
            if ["partition", "rpartition", "removeprefix", "removesuffix"].contains(&name) {
                self.text_arity(name, &args, &kwargs, 1, 1)?;
                let needle = self
                    .buffer_read(&args[0], true)?
                    .ok_or_else(|| pyerr("TypeError", "expected bytes-like argument"))?;
                let data = self.buffer_owner_data(value)?;
                if name.starts_with("remove") {
                    let result = if name == "removeprefix" && data.starts_with(&needle) {
                        data[needle.len()..].to_vec()
                    } else if name == "removesuffix"
                        && !needle.is_empty()
                        && data.ends_with(&needle)
                    {
                        data[..data.len() - needle.len()].to_vec()
                    } else {
                        data
                    };
                    return Ok(self.obj_value(Object::ByteArray(result)));
                }
                if needle.is_empty() {
                    return Err(pyerr("ValueError", "empty separator"));
                }
                let needle_len = needle.len();
                let position = text_find_slice(&data, &needle, name == "rpartition");
                let parts = if let Some(position) = position {
                    vec![
                        data[..position].to_vec(),
                        needle,
                        data[position + needle_len..].to_vec(),
                    ]
                } else if name == "partition" {
                    vec![data, Vec::new(), Vec::new()]
                } else {
                    vec![Vec::new(), Vec::new(), data]
                };
                let values = parts
                    .into_iter()
                    .map(|part| self.obj_value(Object::ByteArray(part)))
                    .collect();
                return Ok(self.obj_value(Object::Tuple(values)));
            }
            if args.is_empty() {
                return Err(pyerr("TypeError", "translate requires table argument"));
            }
            if kwargs.iter().any(|(name, _)| name == "table") {
                return Err(pyerr("TypeError", "table is positional-only"));
            }
            let fields = codec_bind(name, args, kwargs, &["table", "delete"])?;
            let table = match fields[0].as_ref().unwrap() {
                Value::None => None,
                value => {
                    let data = self
                        .buffer_read(value, true)?
                        .ok_or_else(|| pyerr("TypeError", "table must be bytes-like"))?;
                    if data.len() != 256 {
                        return Err(pyerr(
                            "ValueError",
                            "translation table must be 256 characters long",
                        ));
                    }
                    Some(data)
                }
            };
            let delete = fields[1]
                .as_ref()
                .map(|value| {
                    self.buffer_read(value, true).and_then(|value| {
                        value.ok_or_else(|| pyerr("TypeError", "delete must be bytes-like"))
                    })
                })
                .transpose()?
                .unwrap_or_default();
            let data = self.buffer_owner_data(value)?;
            Ok(self.obj_value(Object::ByteArray(
                data.into_iter()
                    .filter(|byte| !delete.contains(byte))
                    .map(|byte| {
                        table
                            .as_ref()
                            .map(|table| table[byte as usize])
                            .unwrap_or(byte)
                    })
                    .collect(),
            )))
        })())
    }
    fn buffer_hash(&mut self, value: Value) -> PyResult<Value> {
        let Value::Obj(index) = value.clone() else {
            return Err(pyerr("TypeError", "expected memoryview"));
        };
        let Some(Object::MemoryView(metadata)) = self.heap.get(index).and_then(Option::as_ref)
        else {
            return Err(pyerr("TypeError", "unhashable type: bytearray"));
        };
        if let Some(hash) = &metadata.hash {
            return Ok(Value::Int(hash.clone().into()));
        }
        let view = self.buffer_view(&value)?;
        if !view.readonly {
            return Err(pyerr(
                "ValueError",
                "cannot hash writable memoryview object",
            ));
        }
        let (format, _) = buffer_format(&view.format)?;
        if !['B', 'b', 'c'].contains(&format) {
            return Err(pyerr(
                "ValueError",
                "hashing is restricted to formats B, b or c",
            ));
        }
        let lease = self.buffer_lease(view.lease)?;
        let hash_owner = if matches!(lease.obj, Value::None) {
            Value::Obj(view.lease)
        } else {
            lease.obj
        };
        self.builtin("hash", vec![hash_owner], Vec::new(), None)?;
        let data = self.buffer_view_bytes(&view, false)?;
        let result = self.builtin("hash", vec![Value::Bytes(data.into())], Vec::new(), None)?;
        let hash = self.as_int(&result)?;
        if let Some(Object::MemoryView(view)) = self.heap[index].as_mut() {
            view.hash = Some(hash);
        }
        Ok(result)
    }
    fn buffer_compare_native(
        &mut self,
        owner: &str,
        op: &str,
        left: &Value,
        right: &Value,
    ) -> PyResult<Option<Value>> {
        if owner == "bytearray" {
            let Some(a) = self.buffer_read(left, false)? else {
                return Ok(None);
            };
            let Some(b) = self.buffer_read(right, false)? else {
                return Ok(None);
            };
            return Ok(Some(Value::Bool(match op {
                "==" => a == b,
                "!=" => a != b,
                "<" => a < b,
                "<=" => a <= b,
                ">" => a > b,
                _ => a >= b,
            })));
        }
        if owner != "memoryview" || !["==", "!="].contains(&op) {
            return Ok(None);
        }
        let left = self.native_payload(left).unwrap_or_else(|| left.clone());
        let left_view = match self.buffer_view(&left) {
            Ok(view) => view,
            Err(_) => {
                return Ok(Some(Value::Bool(if op == "==" {
                    left.same_identity(right)
                } else {
                    !left.same_identity(right)
                })))
            }
        };
        let other = match self.buffer_memoryview(right.clone(), 284) {
            Ok(view) => view,
            Err(error)
                if self.exception_has_native_class(&error, "TypeError")
                    || self.exception_has_native_class(&error, "ValueError") =>
            {
                return Ok(Some(Value::Bool(op == "!=")))
            }
            Err(error) => return Err(error),
        };
        let result = (|| {
            let right_view = self.buffer_view(&other)?;
            if left_view.shape != right_view.shape {
                return Ok(false);
            }
            for (a, b) in Self::buffer_offsets(&left_view, false)?
                .into_iter()
                .zip(Self::buffer_offsets(&right_view, false)?)
            {
                let a = self.buffer_scalar_at(&left_view, a)?;
                let b = self.buffer_scalar_at(&right_view, b)?;
                if !self.equal(&a, &b)? {
                    return Ok(false);
                }
            }
            Ok(true)
        })();
        self.buffer_release(other)?;
        result.map(|equal| Some(Value::Bool(if op == "==" { equal } else { !equal })))
    }
    fn buffer_compare(&mut self, op: &str, left: &Value, right: &Value) -> Option<PyResult<bool>> {
        if !["==", "!=", "<", "<=", ">", ">="].contains(&op) {
            return None;
        }
        let left_kind = self.buffer_kind(left);
        let right_kind = self.buffer_kind(right);
        let (owner, a, b, op) = if matches!(left_kind, Some("bytearray" | "memoryview")) {
            (left_kind.unwrap(), left, right, op)
        } else if matches!(right_kind, Some("bytearray" | "memoryview")) {
            (
                right_kind.unwrap(),
                right,
                left,
                match op {
                    "<" => ">",
                    ">" => "<",
                    "<=" => ">=",
                    ">=" => "<=",
                    _ => op,
                },
            )
        } else {
            return None;
        };
        Some((|| match self.buffer_compare_native(owner, op, a, b)? {
            Some(value) => self.truth(&value),
            None if ["==", "!="].contains(&op) => Ok(op == "!="),
            None => Err(pyerr("TypeError", "buffer ordering is not supported")),
        })())
    }
    fn buffer_binary(&mut self, op: &str, left: Value, right: Value) -> Option<PyResult<Value>> {
        let left_kind = self.buffer_kind(&left);
        let right_kind = self.buffer_kind(&right);
        if left_kind != Some("bytearray") && !(op == "*" && right_kind == Some("bytearray")) {
            return None;
        }
        Some((|| {
            let (value, argument) = if left_kind == Some("bytearray") {
                (left, right)
            } else {
                (right, left)
            };
            if op == "+=" {
                let exported = self.buffer_memoryview(argument.clone(), 0)?;
                let result = self.view_rooted(
                    vec![value.clone(), argument, exported.clone()],
                    |runtime, _| {
                        let extra =
                            runtime.buffer_view_bytes(&runtime.buffer_view(&exported)?, false)?;
                        let mut data = runtime.buffer_owner_data(&value)?;
                        data.try_reserve_exact(extra.len()).map_err(|_| {
                            pyerr("MemoryError", "cannot allocate concatenated bytearray")
                        })?;
                        data.extend(extra);
                        runtime.buffer_replace(value.clone(), data)?;
                        Ok(value)
                    },
                );
                self.buffer_release(exported)?;
                return result;
            }
            let mut data = self.buffer_owner_data(&value)?;
            match op {
                "+" | "+=" => {
                    let extra = self.buffer_read(&argument, true)?.ok_or_else(|| {
                        pyerr("TypeError", "can only concatenate bytes-like values")
                    })?;
                    data = self.buffer_owner_data(&value)?;
                    data.try_reserve_exact(extra.len()).map_err(|_| {
                        pyerr("MemoryError", "cannot allocate concatenated bytearray")
                    })?;
                    data.extend(extra);
                }
                "*" | "*=" => {
                    let count = self
                        .as_int(&argument)?
                        .to_i128()
                        .filter(|count| isize::try_from(*count).is_ok())
                        .ok_or_else(|| pyerr("OverflowError", "repetition count out of range"))?
                        .max(0) as usize;
                    let original = self.buffer_owner_data(&value)?;
                    let length = original
                        .len()
                        .checked_mul(count)
                        .filter(|length| *length <= isize::MAX as usize)
                        .ok_or_else(|| pyerr("OverflowError", "repeated bytearray is too large"))?;
                    data = Vec::new();
                    data.try_reserve_exact(length)
                        .map_err(|_| pyerr("MemoryError", "cannot allocate repeated bytearray"))?;
                    if !original.is_empty() {
                        for _ in 0..count {
                            data.extend_from_slice(&original);
                        }
                    }
                }
                _ => {
                    return Err(pyerr(
                        "NotImplementedError",
                        format!("bytearray operator {op}"),
                    ))
                }
            }
            if op.ends_with('=') {
                self.buffer_replace(value.clone(), data)?;
                Ok(value)
            } else {
                Ok(self.obj_value(Object::ByteArray(data)))
            }
        })())
    }
    fn buffer_descriptor_call(
        &mut self,
        owner: &str,
        name: &str,
        receiver: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        if !["bytearray", "memoryview"].contains(&owner)
            && !(owner == "bytes" && name == "__buffer__")
        {
            return None;
        }
        let payload = self
            .native_payload(&receiver)
            .unwrap_or_else(|| receiver.clone());
        Some((|| {
            if let Some(result) = self.operand_attribute(
                &Value::Builtin(format!("native_attr:wrapper:{owner}:{name}")),
                &receiver,
                &args,
                &kwargs,
            ) {
                return result;
            }
            if name == "__init__" {
                return self.buffer_bytearray_init(payload, args, kwargs);
            }
            if ["__repr__", "__str__"].contains(&name) {
                self.text_arity(name, &args, &kwargs, 0, 0)?;
                let data = self.buffer_owner_data(&payload)?;
                return Ok(Value::Str(
                    format!("{}({})", self.typename(&receiver), buffer_repr_bytes(&data)).into(),
                ));
            }
            if name == "__buffer__" {
                self.text_arity(name, &args, &kwargs, 1, 1)?;
                return self.buffer_export(receiver, payload, &args[0]);
            }
            if name == "__release_buffer__" {
                self.text_arity(name, &args, &kwargs, 1, 1)?;
                self.buffer_release_from(receiver, args[0].clone())?;
                return Ok(Value::None);
            }
            let result = self
                .buffer_method(payload, name, args, kwargs)
                .ok_or_else(|| {
                    pyerr(
                        "NotImplementedError",
                        format!("native buffer method {owner}.{name}"),
                    )
                })??;
            Ok(self.collection_keep(result, receiver))
        })())
    }
    fn buffer_cast(
        &mut self,
        value: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        if args.is_empty() {
            return Err(pyerr("TypeError", "cast requires a format argument"));
        }
        if kwargs.iter().any(|(name, _)| name == "format") {
            return Err(pyerr("TypeError", "format is positional-only"));
        }
        let mut fields = codec_bind("cast", args, kwargs, &["format", "shape"])?;
        let format_value = fields[0].take().unwrap();
        let format = match self.native_payload(&format_value).unwrap_or(format_value) {
            Value::Str(format) => format.into_inner(),
            _ => return Err(pyerr("TypeError", "cast format must be str")),
        };
        let (code, itemsize) = buffer_format(&format)?;
        let mut view = self.buffer_view(&value)?;
        if !Self::buffer_contiguous(&view, false) {
            return Err(pyerr(
                "TypeError",
                "casts are restricted to C-contiguous views",
            ));
        }
        let (old, _) = buffer_format(&view.format)?;
        if !['B', 'b', 'c'].contains(&code) && !['B', 'b', 'c'].contains(&old) {
            return Err(pyerr(
                "TypeError",
                "cannot cast between two non-byte formats",
            ));
        }
        let length = view.shape.iter().product::<usize>() * view.itemsize;
        if length % itemsize != 0 {
            return Err(pyerr("TypeError", "length is not a multiple of itemsize"));
        }
        let shape = if let Some(shape) = fields[1].take() {
            if view.shape.contains(&0) {
                return Err(pyerr(
                    "TypeError",
                    "cannot cast view with zeros in shape or strides",
                ));
            }
            if !matches!(&shape,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::List(_)|Object::Tuple(_))))
            {
                return Err(pyerr("TypeError", "shape must be a list or a tuple"));
            }
            let dimensions = self.to_vec(shape)?;
            if dimensions.len() > 64 {
                return Err(pyerr("ValueError", "number of dimensions exceeds 64"));
            }
            let mut result = Vec::new();
            let mut count = 1usize;
            for value in dimensions {
                let value = self.native_payload(&value).unwrap_or(value);
                if !matches!(value, Value::Int(_) | Value::Bool(_)) {
                    return Err(pyerr("TypeError", "shape elements must be integers"));
                }
                let size = self
                    .as_int(&value)?
                    .to_usize()
                    .filter(|size| *size > 0 && *size <= isize::MAX as usize)
                    .ok_or_else(|| {
                        pyerr("ValueError", "shape elements must be positive integers")
                    })?;
                count = count
                    .checked_mul(size)
                    .filter(|count| *count <= isize::MAX as usize)
                    .ok_or_else(|| pyerr("ValueError", "shape is too large"))?;
                result.push(size);
            }
            if count != length / itemsize {
                return Err(pyerr(
                    "TypeError",
                    "product(shape) * itemsize does not equal buffer size",
                ));
            }
            result
        } else {
            vec![length / itemsize]
        };
        let mut strides = vec![0isize; shape.len()];
        let mut stride = itemsize as isize;
        for axis in (0..shape.len()).rev() {
            strides[axis] = stride;
            stride = stride
                .checked_mul(shape[axis] as isize)
                .ok_or_else(|| pyerr("OverflowError", "shape is too large"))?;
        }
        self.buffer_view(&value)?;
        view.shape = shape;
        view.strides = strides;
        view.format = format;
        view.itemsize = itemsize;
        view.exports = 0;
        view.hash = None;
        Ok(self.obj_value(Object::MemoryView(Box::new(view))))
    }
    fn buffer_getattr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        let kind = self.buffer_kind(&value)?;
        if kind == "_buffer_wrapper" {
            return None;
        }
        if kind == "memoryview" {
            let attributes = [
                "obj",
                "nbytes",
                "readonly",
                "itemsize",
                "format",
                "ndim",
                "shape",
                "strides",
                "suboffsets",
                "c_contiguous",
                "f_contiguous",
                "contiguous",
            ];
            if attributes.contains(&name) {
                return Some((|| {
                    let view = self.buffer_view(&value)?;
                    let lease = self.buffer_lease(view.lease)?;
                    Ok(match name {
                        "obj" => {
                            if matches!(lease.obj, Value::None) {
                                Value::Obj(view.lease)
                            } else {
                                lease.obj
                            }
                        }
                        "readonly" => Value::Bool(view.readonly),
                        "format" => Value::Str(view.format.into()),
                        "nbytes" => Value::Int(
                            Int::from_i128(
                                (view.shape.iter().product::<usize>() * view.itemsize) as i128,
                            )
                            .into(),
                        ),
                        "itemsize" => Value::Int(Int::from_i128(view.itemsize as i128).into()),
                        "ndim" => Value::Int(Int::from_i128(view.shape.len() as i128).into()),
                        "shape" => self.obj_value(Object::Tuple(
                            view.shape
                                .iter()
                                .map(|size| Value::Int(Int::from_i128(*size as i128).into()))
                                .collect(),
                        )),
                        "strides" => self.obj_value(Object::Tuple(
                            view.strides
                                .iter()
                                .map(|stride| Value::Int(Int::from_i128(*stride as i128).into()))
                                .collect(),
                        )),
                        "suboffsets" => self.obj_value(Object::Tuple(Vec::new())),
                        "c_contiguous" => Value::Bool(Self::buffer_contiguous(&view, false)),
                        "f_contiguous" => Value::Bool(Self::buffer_contiguous(&view, true)),
                        _ => Value::Bool(
                            Self::buffer_contiguous(&view, false)
                                || Self::buffer_contiguous(&view, true),
                        ),
                    })
                })());
            }
        }
        let class = Value::Builtin(kind.into());
        if let Some(descriptor) = self.native_own_attribute(&class, name) {
            return Some(self.bind_descriptor(descriptor, Some(value), class));
        }
        let methods = if kind == "memoryview" {
            &[
                "release",
                "tobytes",
                "tolist",
                "hex",
                "toreadonly",
                "cast",
                "count",
                "index",
                "__len__",
                "__getitem__",
                "__setitem__",
                "__iter__",
                "__enter__",
                "__exit__",
                "__hash__",
                "__eq__",
                "__ne__",
                "__buffer__",
                "__release_buffer__",
            ][..]
        } else {
            &[
                "append",
                "extend",
                "insert",
                "pop",
                "remove",
                "clear",
                "reverse",
                "resize",
                "copy",
                "decode",
                "hex",
                "__len__",
                "__getitem__",
                "__setitem__",
                "__delitem__",
                "__iter__",
                "__repr__",
                "__str__",
                "__contains__",
                "__buffer__",
                "__release_buffer__",
                "count",
                "find",
                "rfind",
                "index",
                "rindex",
                "startswith",
                "endswith",
                "split",
                "rsplit",
                "strip",
                "lstrip",
                "rstrip",
                "replace",
                "join",
            ][..]
        };
        if methods.contains(&name) {
            return Some(Ok(self.obj_value(Object::Bound(
                Value::Builtin(format!("method:{name}")),
                value,
            ))));
        }
        None
    }
    fn buffer_method(
        &mut self,
        value: Value,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        let kind = self.buffer_kind(&value)?;
        if kind == "_buffer_wrapper" {
            return None;
        }
        Some((|| {
            if name == "__hash__" {
                self.text_arity(name, &args, &kwargs, 0, 0)?;
                return self.buffer_hash(value);
            }
            if name == "release" {
                self.text_arity(name, &args, &kwargs, 0, 0)?;
                self.buffer_release(value)?;
                return Ok(Value::None);
            }
            if name == "__len__" {
                self.text_arity(name, &args, &kwargs, 0, 0)?;
                let length = self.buffer_length(&value).unwrap()?;
                return Ok(Value::Int(Int::from_i128(length as i128).into()));
            }
            if name == "__getitem__" {
                self.text_arity(name, &args, &kwargs, 1, 1)?;
                return self.buffer_getitem(value, args[0].clone()).unwrap();
            }
            if name == "__setitem__" {
                self.text_arity(name, &args, &kwargs, 2, 2)?;
                self.buffer_setitem(value, args[0].clone(), args[1].clone())
                    .unwrap()?;
                return Ok(Value::None);
            }
            if name == "__delitem__" {
                self.text_arity(name, &args, &kwargs, 1, 1)?;
                self.buffer_delitem(value, args[0].clone()).unwrap()?;
                return Ok(Value::None);
            }
            if name == "__iter__" {
                self.text_arity(name, &args, &kwargs, 0, 0)?;
                self.buffer_length(&value).unwrap()?;
                return Ok(self.obj_value(Object::Iterator(IteratorState::Buffer(value, 0))));
            }
            if name == "__buffer__" {
                self.text_arity(name, &args, &kwargs, 1, 1)?;
                return self.buffer_export(value.clone(), value, &args[0]);
            }
            if name == "__release_buffer__" {
                self.text_arity(name, &args, &kwargs, 1, 1)?;
                self.buffer_release_from(value, args[0].clone())?;
                return Ok(Value::None);
            }
            if kind == "memoryview" {
                match name {
                    "cast" => return self.buffer_cast(value, args, kwargs),
                    "__enter__" | "tolist" | "toreadonly" => self.text_arity(name, &args, &kwargs, 0, 0)?,
                    "__exit__" => self.text_arity(name, &args, &kwargs, 3, 3)?,
                    "count" => self.text_arity(name, &args, &kwargs, 1, 1)?,
                    "index" => self.text_arity(name, &args, &kwargs, 1, 3)?,
                    "tobytes" => {
                        let fields = codec_bind(name, args.clone(), kwargs.clone(), &["order"])?;
                        codec_argument(self, fields[0].as_ref(), "C", "order")?;
                    }
                    "hex" => {codec_bind(name, args.clone(), kwargs.clone(), &["sep", "bytes_per_sep"])?;}
                    _ => (),
                }
                let view = self.buffer_view(&value)?;
                match name {
                    "__enter__" => {
                        self.text_arity(name, &args, &kwargs, 0, 0)?;
                        return Ok(value);
                    }
                    "__exit__" => {
                        self.text_arity(name, &args, &kwargs, 3, 3)?;
                        self.buffer_release(value)?;
                        return Ok(Value::None);
                    }
                    "toreadonly" => {
                        self.text_arity(name, &args, &kwargs, 0, 0)?;
                        let mut view = view;
                        view.readonly = true;
                        view.exports = 0;
                        view.hash = None;
                        return Ok(self.obj_value(Object::MemoryView(Box::new(view))));
                    }
                    "tobytes" => {
                        let fields = codec_bind(name, args, kwargs, &["order"])?;
                        let order = codec_argument(self, fields[0].as_ref(), "C", "order")?;
                        if !["C", "F", "A"].contains(&order.as_str()) {
                            return Err(pyerr("ValueError", "order must be C, F or A"));
                        }
                        return self
                            .buffer_view_bytes(
                                &view,
                                order == "F"
                                    || (order == "A"
                                        && Self::buffer_contiguous(&view, true)
                                        && !Self::buffer_contiguous(&view, false)),
                            )
                            .map(|data| Value::Bytes(data.into()));
                    }
                    "count" | "index" => {
                        self.text_arity(
                            name,
                            &args,
                            &kwargs,
                            1,
                            if name == "count" { 1 } else { 3 },
                        )?;
                        let length = view
                            .shape
                            .first()
                            .copied()
                            .ok_or_else(|| pyerr("TypeError", "0-dim memory has no length"))?;
                        let normalize = |number: &Int| {
                            let mut number = number.to_i128().unwrap_or(if number.is_negative() {
                                i128::MIN
                            } else {
                                i128::MAX
                            });
                            if number < 0 {
                                number = number.saturating_add(length as i128);
                            }
                            number.clamp(0, length as i128) as usize
                        };
                        let start = args
                            .get(1)
                            .map(|value| self.as_int(value).map(|number| normalize(&number)))
                            .transpose()?
                            .unwrap_or(0);
                        let stop = args
                            .get(2)
                            .map(|value| self.as_int(value).map(|number| normalize(&number)))
                            .transpose()?
                            .unwrap_or(length);
                        let mut count = 0;
                        for at in start..stop {
                            let item = self
                                .buffer_getitem(
                                    value.clone(),
                                    Value::Int(Int::from_i128(at as i128).into()),
                                )
                                .unwrap()?;
                            if self.equal(&item, &args[0])? {
                                if name == "index" {
                                    return Ok(Value::Int(Int::from_i128(at as i128).into()));
                                }
                                count += 1;
                            }
                        }
                        return if name == "count" {
                            Ok(Value::Int(Int::from_i128(count).into()))
                        } else {
                            Err(pyerr("ValueError", "value is not in memoryview"))
                        };
                    }
                    "tolist" => {
                        self.text_arity(name, &args, &kwargs, 0, 0)?;
                        let offsets = Self::buffer_offsets(&view, false)?;
                        let mut items = Vec::new();
                        for offset in offsets {
                            items.push(self.buffer_scalar_at(&view, offset)?);
                        }
                        let mut at = 0;
                        return self.buffer_shape_list(&view.shape, &items, &mut at);
                    }
                    "hex" => {
                        let data = self.buffer_view_bytes(&view, false)?;
                        return self.scalar_bytes_hex(&data, args, kwargs);
                    }
                    "cast" => return self.buffer_cast(value, args, kwargs),
                    _ => return Err(pyerr("NotImplementedError", format!("memoryview.{name}"))),
                }
            }
            if let Some(result) =
                self.buffer_mutating_method(&value, name, args.clone(), kwargs.clone())
            {
                return result;
            }
            if let Some(result) =
                self.buffer_ascii_method(&value, name, args.clone(), kwargs.clone())
            {
                return result;
            }
            let mut data = self.buffer_owner_data(&value)?;
            match name {
                "__repr__" | "__str__" => {
                    self.text_arity(name, &args, &kwargs, 0, 0)?;
                    return Ok(Value::Str(
                        format!("bytearray({})", buffer_repr_bytes(&data)).into(),
                    ));
                }
                "append" => {
                    self.text_arity(name, &args, &kwargs, 1, 1)?;
                    let byte = self.buffer_byte(&args[0])?;
                    data = self.buffer_owner_data(&value)?;
                    data.push(byte);
                }
                "extend" => {
                    self.text_arity(name, &args, &kwargs, 1, 1)?;
                    let extra = self.buffer_sequence(args[0].clone())?;
                    data = self.buffer_owner_data(&value)?;
                    data.extend(extra);
                }
                "insert" => {
                    self.text_arity(name, &args, &kwargs, 2, 2)?;
                    let position = self
                        .as_int(&args[0])?
                        .to_i128()
                        .ok_or_else(|| pyerr("OverflowError", "index out of range"))?;
                    let byte = self.buffer_byte(&args[1])?;
                    data = self.buffer_owner_data(&value)?;
                    let position = if position < 0 {
                        position.saturating_add(data.len() as i128)
                    } else {
                        position
                    }
                    .clamp(0, data.len() as i128) as usize;
                    data.insert(position, byte);
                }
                "pop" => {
                    self.text_arity(name, &args, &kwargs, 0, 1)?;
                    let key = args
                        .first()
                        .cloned()
                        .unwrap_or(Value::Int(Int::from_i128(-1).into()));
                    let index = self.index(&key, data.len())?;
                    data = self.buffer_owner_data(&value)?;
                    if index >= data.len() {
                        return Err(pyerr("IndexError", "pop index out of range"));
                    }
                    let byte = data.remove(index);
                    self.buffer_replace(value, data)?;
                    return Ok(Value::Int(Int::from_i128(byte as i128).into()));
                }
                "remove" => {
                    self.text_arity(name, &args, &kwargs, 1, 1)?;
                    let byte = self.buffer_byte(&args[0])?;
                    data = self.buffer_owner_data(&value)?;
                    let index = data
                        .iter()
                        .position(|item| *item == byte)
                        .ok_or_else(|| pyerr("ValueError", "value not found in bytearray"))?;
                    data.remove(index);
                }
                "clear" => {
                    self.text_arity(name, &args, &kwargs, 0, 0)?;
                    data.clear();
                }
                "reverse" => {
                    self.text_arity(name, &args, &kwargs, 0, 0)?;
                    data.reverse();
                }
                "resize" => {
                    self.text_arity(name, &args, &kwargs, 1, 1)?;
                    let count = self.as_int(&args[0])?;
                    if count.is_negative() {
                        return Err(pyerr("ValueError", "size must be non-negative"));
                    }
                    let count = count
                        .to_usize()
                        .filter(|count| *count <= isize::MAX as usize)
                        .ok_or_else(|| pyerr("OverflowError", "size out of range"))?;
                    data = self.buffer_owner_data(&value)?;
                    if count > data.len() {
                        data.try_reserve_exact(count - data.len())
                            .map_err(|_| pyerr("MemoryError", "cannot resize bytearray"))?;
                    }
                    data.resize(count, 0);
                }
                "copy" => {
                    self.text_arity(name, &args, &kwargs, 0, 0)?;
                    return Ok(self.obj_value(Object::ByteArray(data)));
                }
                "decode" => return self.codec_decode(Value::Bytes(data.into()), args, kwargs),
                "hex" => return self.scalar_bytes_hex(&data, args, kwargs),
                "__contains__" => {
                    self.text_arity(name, &args, &kwargs, 1, 1)?;
                    let needle = self.bytes_needle(&args[0], true)?;
                    return Ok(Value::Bool(
                        text_find_slice(&data, &needle, false).is_some(),
                    ));
                }
                _ => {
                    if let Some(result) = self.bytes_method(data, name, args, kwargs) {
                        return result.map(|value| self.buffer_result_bytearrays(value));
                    }
                    return Err(pyerr("NotImplementedError", format!("bytearray.{name}")));
                }
            }
            self.buffer_replace(value, data)?;
            Ok(Value::None)
        })())
    }
    fn buffer_shape_list(
        &mut self,
        shape: &[usize],
        items: &[Value],
        at: &mut usize,
    ) -> PyResult<Value> {
        if shape.is_empty() {
            let result = items
                .get(*at)
                .cloned()
                .ok_or_else(|| pyerr("ValueError", "invalid buffer shape"))?;
            *at += 1;
            return Ok(result);
        }
        let mut result = Vec::new();
        for _ in 0..shape[0] {
            result.push(self.buffer_shape_list(&shape[1..], items, at)?);
        }
        Ok(self.obj_value(Object::List(result)))
    }
    fn buffer_result_bytearrays(&mut self, value: Value) -> Value {
        match value {
            Value::Bytes(data) => self.obj_value(Object::ByteArray(data.into_inner())),
            Value::Obj(index) => match self.heap.get(index).and_then(Option::as_ref).cloned() {
                Some(Object::List(items)) => {
                    let items = items
                        .into_iter()
                        .map(|item| self.buffer_result_bytearrays(item))
                        .collect();
                    self.obj_value(Object::List(items))
                }
                Some(Object::Tuple(items)) => {
                    let items = items
                        .into_iter()
                        .map(|item| self.buffer_result_bytearrays(item))
                        .collect();
                    self.obj_value(Object::Tuple(items))
                }
                _ => Value::Obj(index),
            },
            _ => value,
        }
    }
    fn buffer_length(&self, value: &Value) -> Option<PyResult<usize>> {
        let Value::Obj(index) = value else {
            return None;
        };
        match self.heap.get(*index).and_then(Option::as_ref) {
            Some(Object::ByteArray(data)) => Some(Ok(data.len())),
            Some(Object::MemoryView(_)) => Some(self.buffer_view(value).and_then(|view| {
                view.shape
                    .first()
                    .copied()
                    .ok_or_else(|| pyerr("TypeError", "0-dim memory has no length"))
            })),
            _ => None,
        }
    }
    fn buffer_slice(
        &mut self,
        key: &Value,
        length: usize,
    ) -> PyResult<Option<(Vec<usize>, isize, isize)>> {
        let Value::Obj(index) = key else {
            return Ok(None);
        };
        let Object::Slice(start, stop, step) = self.object(*index)? else {
            return Ok(None);
        };
        let step = step
            .map(|value| {
                value.to_i128().unwrap_or(if value.is_negative() {
                    i128::MIN
                } else {
                    i128::MAX
                })
            })
            .unwrap_or(1)
            .clamp(isize::MIN as i128, isize::MAX as i128) as isize;
        if step == 0 {
            return Err(pyerr("ValueError", "slice step cannot be zero"));
        }
        let indices = self.slice_indices(
            start.clone(),
            stop,
            Some(Int::from_i128(step as i128)),
            length,
        )?;
        let origin = if let Some(first) = indices.first() {
            *first as isize
        } else {
            let mut origin = start
                .map(|value| {
                    value.to_i128().unwrap_or(if value.is_negative() {
                        i128::MIN
                    } else {
                        i128::MAX
                    })
                })
                .unwrap_or(if step > 0 { 0 } else { length as i128 - 1 });
            if origin < 0 {
                origin = origin.saturating_add(length as i128);
            }
            origin.clamp(
                if step > 0 { 0 } else { -1 },
                if step > 0 {
                    length as i128
                } else {
                    length as i128 - 1
                },
            ) as isize
        };
        Ok(Some((indices, step, origin)))
    }
    fn buffer_scalar_at(&mut self, view: &MemoryViewData, offset: usize) -> PyResult<Value> {
        let lease = self.buffer_lease(view.lease)?;
        let data = self.buffer_owner_slice(&lease.owner)?;
        let bytes = data
            .get(
                offset
                    ..offset
                        .checked_add(view.itemsize)
                        .ok_or_else(|| pyerr("OverflowError", "buffer offset is too large"))?,
            )
            .ok_or_else(|| pyerr("IndexError", "buffer offset out of range"))?;
        match view.format.trim_start_matches('@') {
            "B" => Ok(Value::Int(Int::from_i128(bytes[0] as i128).into())),
            "b" => Ok(Value::Int(Int::from_i128(bytes[0] as i8 as i128).into())),
            "c" => Ok(Value::Bytes(vec![bytes[0]].into())),
            "?" => Ok(Value::Bool(bytes[0] != 0)),
            _ => {
                let (format, _) = buffer_format(&view.format)?;
                let mut raw = 0u64;
                for (at, byte) in bytes.iter().enumerate() {
                    let shift = if cfg!(target_endian = "little") {
                        at
                    } else {
                        bytes.len() - 1 - at
                    };
                    raw |= (*byte as u64) << (8 * shift);
                }
                if format == 'f' {
                    return Ok(Value::Float((f32::from_bits(raw as u32) as f64).into()));
                }
                if format == 'd' {
                    return Ok(Value::Float(f64::from_bits(raw).into()));
                }
                if format == 'e' {
                    return Ok(Value::Float(buffer_half_read(raw as u16).into()));
                }
                let bits = bytes.len() * 8;
                let integer = if ['h', 'i', 'l', 'q', 'n'].contains(&format)
                    && raw & (1u64 << (bits - 1)) != 0
                {
                    raw as i128 - (1i128 << bits)
                } else {
                    raw as i128
                };
                Ok(Value::Int(Int::from_i128(integer).into()))
            }
        }
    }
    fn buffer_scalar_bytes(&mut self, view: &MemoryViewData, value: Value) -> PyResult<Vec<u8>> {
        match view.format.trim_start_matches('@') {
            "B" => self.buffer_byte(&value).map(|value| vec![value]),
            "b" => {
                let value = self
                    .as_int(&value)?
                    .to_i128()
                    .filter(|value| (-128..=127).contains(value))
                    .ok_or_else(|| pyerr("ValueError", "memoryview: invalid value for format b"))?;
                Ok(vec![value as i8 as u8])
            }
            "c" => match self.native_payload(&value).unwrap_or(value) {
                Value::Bytes(bytes) if bytes.len() == 1 => Ok(bytes.to_vec()),
                _ => Err(pyerr("TypeError", "memoryview: invalid type for format c")),
            },
            "?" => self.truth(&value).map(|value| vec![value as u8]),
            _ => {
                let (format, size) = buffer_format(&view.format)?;
                let raw = if ['e', 'f', 'd'].contains(&format) {
                    let number = self.math_float(&value)?;
                    if format == 'd' {
                        number.to_bits()
                    } else if format == 'e' {
                        buffer_half_write(number)? as u64
                    } else {
                        (number as f32).to_bits() as u64
                    }
                } else {
                    let bits = size * 8;
                    let signed = ['h', 'i', 'l', 'q', 'n'].contains(&format);
                    let minimum = if signed { -(1i128 << (bits - 1)) } else { 0 };
                    let maximum = if signed {
                        (1i128 << (bits - 1)) - 1
                    } else {
                        (1i128 << bits) - 1
                    };
                    self.as_int(&value)?
                        .to_i128()
                        .filter(|number| *number >= minimum && *number <= maximum)
                        .ok_or_else(|| {
                            pyerr(
                                "ValueError",
                                format!("memoryview: invalid value for format {format}"),
                            )
                        })? as u64
                };
                Ok((0..size)
                    .map(|at| {
                        let shift = if cfg!(target_endian = "little") {
                            at
                        } else {
                            size - 1 - at
                        };
                        (raw >> (8 * shift)) as u8
                    })
                    .collect())
            }
        }
    }
    fn buffer_view_offset(&mut self, view: &MemoryViewData, key: Value) -> PyResult<usize> {
        let keys = match &key {
            Value::Obj(index) => match self.object(*index)? {
                Object::Tuple(values) => values,
                _ => vec![key],
            },
            _ => vec![key],
        };
        if keys.len() != view.shape.len() {
            return Err(pyerr("TypeError", "invalid number of indices"));
        }
        let mut offset = view.offset;
        for (axis, key) in keys.iter().enumerate() {
            let index = self.index(key, view.shape[axis])?;
            offset = offset
                .checked_add(
                    view.strides[axis]
                        .checked_mul(index as isize)
                        .ok_or_else(|| pyerr("OverflowError", "buffer offset overflow"))?,
                )
                .ok_or_else(|| pyerr("OverflowError", "buffer offset overflow"))?;
        }
        usize::try_from(offset).map_err(|_| pyerr("IndexError", "invalid buffer offset"))
    }
    fn buffer_getitem(&mut self, value: Value, key: Value) -> Option<PyResult<Value>> {
        let kind = self.buffer_kind(&value)?;
        Some((|| {
            if kind == "bytearray" {
                let length = self.buffer_owner_slice(&value)?.len();
                return if let Some((indices, _, _)) = self.buffer_slice(&key, length)? {
                    let data = self.buffer_owner_slice(&value)?;
                    let output = indices.iter().map(|index| data[*index]).collect();
                    Ok(self.obj_value(Object::ByteArray(output)))
                } else {
                    let index = self.index(&key, length)?;
                    let byte = *self
                        .buffer_owner_slice(&value)?
                        .get(index)
                        .ok_or_else(|| pyerr("IndexError", "bytearray index out of range"))?;
                    Ok(Value::Int(Int::from_i128(byte as i128).into()))
                };
            }
            if kind != "memoryview" {
                return Err(pyerr("TypeError", "buffer wrapper is not subscriptable"));
            }
            let mut view = self.buffer_view(&value)?;
            if let Some(length) = view.shape.first().copied() {
                if let Some((indices, step, origin)) = self.buffer_slice(&key, length)? {
                    view.offset = view
                        .offset
                        .checked_add(
                            view.strides[0]
                                .checked_mul(origin)
                                .ok_or_else(|| pyerr("OverflowError", "buffer stride overflow"))?,
                        )
                        .ok_or_else(|| pyerr("OverflowError", "buffer offset overflow"))?;
                    view.strides[0] = view.strides[0]
                        .checked_mul(step)
                        .ok_or_else(|| pyerr("OverflowError", "buffer stride overflow"))?;
                    view.shape[0] = indices.len();
                    view.exports = 0;
                    view.hash = None;
                    return Ok(self.obj_value(Object::MemoryView(Box::new(view))));
                }
            }
            if view.shape.len() > 1
                && !matches!(&key,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_))))
            {
                return Err(pyerr(
                    "NotImplementedError",
                    "multi-dimensional sub-views are not implemented",
                ));
            }
            let offset = self.buffer_view_offset(&view, key)?;
            self.buffer_scalar_at(&view, offset)
        })())
    }
    fn buffer_setitem(&mut self, value: Value, key: Value, item: Value) -> Option<PyResult<()>> {
        let kind = self.buffer_kind(&value)?;
        Some((|| {
            if kind == "bytearray" {
                let mut data = self.buffer_owner_data(&value)?;
                if let Some((indices, step, origin)) = self.buffer_slice(&key, data.len())? {
                    let replacement = self.buffer_sequence(item)?;
                    data = self.buffer_owner_data(&value)?;
                    if step == 1 {
                        let origin = origin as usize;
                        let stop = origin
                            .checked_add(indices.len())
                            .ok_or_else(|| pyerr("OverflowError", "slice is too large"))?;
                        if stop > data.len() {
                            return Err(pyerr("IndexError", "bytearray changed during assignment"));
                        }
                        data.splice(origin..stop, replacement);
                    } else {
                        if indices.len() != replacement.len() {
                            return Err(pyerr(
                                "ValueError",
                                "attempt to assign bytes of size different from extended slice",
                            ));
                        }
                        for (index, byte) in indices.into_iter().zip(replacement) {
                            let slot = data.get_mut(index).ok_or_else(|| {
                                pyerr("IndexError", "bytearray changed during assignment")
                            })?;
                            *slot = byte;
                        }
                    }
                } else {
                    let index = self.index(&key, data.len())?;
                    let item = self.buffer_byte(&item)?;
                    data = self.buffer_owner_data(&value)?;
                    *data
                        .get_mut(index)
                        .ok_or_else(|| pyerr("IndexError", "bytearray index out of range"))? = item;
                }
                return self.buffer_replace(value, data);
            }
            let view = self.buffer_view(&value)?;
            if view.readonly {
                return Err(pyerr("TypeError", "cannot modify read-only memory"));
            }
            let lease = self.buffer_lease(view.lease)?;
            let (offsets, replacement, copy_size) = if view.shape.len() == 1
                && self.buffer_slice(&key, view.shape[0])?.is_some()
            {
                let selected = self.buffer_getitem(value.clone(), key).unwrap()?;
                self.view_rooted(vec![selected.clone(), item.clone()], |runtime, root| {
                        let result=(|| {
                            let selected_view = runtime.buffer_view(&selected)?;
                            let offsets = Self::buffer_offsets(&selected_view, false)?;
                            let other = runtime.buffer_memoryview(item, 284)?;
                            runtime.roots[root].push(other.clone());
                            let other_view = runtime.buffer_view(&other)?;
                            let result = if other_view.shape != selected_view.shape
                                || other_view.format != selected_view.format
                                || other_view.itemsize != selected_view.itemsize
                            {
                                Err(pyerr(
                                    "ValueError",
                                    "memoryview assignment: lvalue and rvalue have different structures",
                                ))
                            } else {
                                runtime.buffer_view_bytes(&other_view, false)
                            };
                            runtime.buffer_release(other)?;
                            Ok((offsets, result?, selected_view.itemsize))
                        })();
                        runtime.buffer_release(selected)?;
                        result
                    })?
            } else {
                let offset = self.buffer_view_offset(&view, key)?;
                let bytes = self.buffer_scalar_bytes(&view, item)?;
                let size = bytes.len();
                (vec![offset], bytes, size)
            };
            self.buffer_view(&value)?;
            let Value::Obj(owner) = lease.owner else {
                return Err(pyerr("TypeError", "cannot modify read-only memory"));
            };
            let Some(Object::ByteArray(data)) = self.heap.get_mut(owner).and_then(Option::as_mut)
            else {
                return Err(pyerr("TypeError", "invalid writable buffer owner"));
            };
            for (position, offset) in offsets.into_iter().enumerate() {
                let end = offset
                    .checked_add(copy_size)
                    .ok_or_else(|| pyerr("OverflowError", "buffer offset overflow"))?;
                let target = data
                    .get_mut(offset..end)
                    .ok_or_else(|| pyerr("IndexError", "buffer offset out of range"))?;
                target.copy_from_slice(
                    &replacement[position * copy_size..(position + 1) * copy_size],
                );
            }
            Ok(())
        })())
    }
    fn buffer_delitem(&mut self, value: Value, key: Value) -> Option<PyResult<()>> {
        let kind = self.buffer_kind(&value)?;
        Some((|| {
            if kind != "bytearray" {
                return Err(pyerr("TypeError", "cannot delete memory"));
            }
            let mut data = self.buffer_owner_data(&value)?;
            if let Some((mut indices, _, _)) = self.buffer_slice(&key, data.len())? {
                indices.sort_unstable();
                for index in indices.into_iter().rev() {
                    data.remove(index);
                }
            } else {
                let index = self.index(&key, data.len())?;
                data = self.buffer_owner_data(&value)?;
                if index >= data.len() {
                    return Err(pyerr("IndexError", "bytearray index out of range"));
                }
                data.remove(index);
            }
            self.buffer_replace(value, data)
        })())
    }
}
impl Runtime {
    fn buffer_invalidate_lease_views(&mut self, index: usize) {
        for object in &mut self.heap {
            if let Some(Object::MemoryView(view)) = object {
                if view.lease == index {
                    view.released = true;
                }
            }
        }
    }
    fn buffer_collect_dead_leases(&mut self, marked: &[bool]) {
        // Python callbacks observe their returned view before its underlying
        // native lease closes. Keep ordinary finalizer resurrection decisions
        // made by the collector, then re-mark after these callbacks as well.
        let mut candidates: Vec<_> = self
            .heap
            .iter()
            .enumerate()
            .filter_map(|(index, object)| match object {
                Some(Object::BufferLease(lease)) if lease.active && !marked[index] => {
                    Some((lease.native_export, index))
                }
                _ => None,
            })
            .collect();
        candidates.sort_unstable();
        for (_, index) in candidates {
            if self.gc_marks(&[]).get(index).copied().unwrap_or(false) {
                continue;
            }
            self.buffer_invalidate_lease_views(index);
            let _ = self.buffer_close_lease(index);
        }
    }
    fn buffer_reclaim_exports(&mut self, owner: usize) -> PyResult<()> {
        if self.buffer_exports.get(&owner).copied().unwrap_or(0) == 0 {
            return Ok(());
        }
        let marked = self.gc_marks(&[]);
        let targets: Vec<_> = self
            .heap
            .iter()
            .enumerate()
            .filter_map(|(index, object)| match object {
                Some(Object::BufferLease(lease))
                    if lease.active
                        && lease.native_export
                        && !marked[index]
                        && matches!(lease.owner,Value::Obj(index)if index==owner) =>
                {
                    Some(index)
                }
                _ => None,
            })
            .collect();
        self.buffer_reclaim_targets(targets, marked)
    }
    fn buffer_reclaim_view_exports(&mut self, view: usize) -> PyResult<()> {
        let marked = self.gc_marks(&[]);
        let targets = self
            .heap
            .iter()
            .enumerate()
            .filter_map(|(index, object)| match object {
                Some(Object::BufferLease(lease))
                    if lease.active
                        && !marked[index]
                        && matches!(&lease.exported_view,Some(Value::Obj(owner))if *owner==view) =>
                {
                    Some(index)
                }
                _ => None,
            })
            .collect();
        self.buffer_reclaim_targets(targets, marked)
    }
    fn buffer_reclaim_targets(&mut self, targets: Vec<usize>, marked: Vec<bool>) -> PyResult<()> {
        if targets.is_empty() {
            return Ok(());
        }
        let size = self.heap.len();
        let mut graph = vec![Vec::new(); size];
        let mut reverse = vec![Vec::new(); size];
        for index in 0..size {
            if !marked[index] && self.heap[index].is_some() {
                let mut values = Vec::new();
                self.gc_children(index, &mut values, &mut std::collections::HashSet::new());
                for value in values {
                    if let Value::Obj(child) = value {
                        if child < size && !marked[child] {
                            graph[index].push(child);
                            reverse[child].push(index);
                        }
                    }
                }
            }
        }
        let mut ancestor = vec![false; size];
        let mut pending = targets;
        while let Some(index) = pending.pop() {
            if ancestor[index] {
                continue;
            }
            ancestor[index] = true;
            pending.extend(reverse[index].iter().copied());
        }
        let mut indegree = vec![0usize; size];
        for index in 0..size {
            if ancestor[index] {
                for child in &graph[index] {
                    if ancestor[*child] {
                        indegree[*child] += 1;
                    }
                }
            }
        }
        let mut ready: Vec<_> = (0..size)
            .filter(|index| ancestor[*index] && indegree[*index] == 0)
            .collect();
        let mut order = Vec::new();
        while let Some(index) = ready.pop() {
            order.push(index);
            for child in &graph[index] {
                if ancestor[*child] {
                    indegree[*child] -= 1;
                    if indegree[*child] == 0 {
                        ready.push(*child);
                    }
                }
            }
        }
        // An unreachable cycle keeps its export until a normal/explicit GC.
        // This also preserves gc.disable(), rather than collecting unrelated
        // cycles just because a live bytearray is about to change size.
        if order.len() != ancestor.iter().filter(|value| **value).count() {
            return Ok(());
        }
        let root = self.roots.len();
        self.roots.push(Vec::new());
        let previous_gc = self.gc_running;
        self.gc_running = true;
        for index in &order {
            if self.finalized.contains(index) {
                continue;
            }
            let value = Value::Obj(*index);
            if self
                .object_class(&value)
                .and_then(|class| self.slot_override(&class, "__del__", 0))
                .is_some()
            {
                self.finalized.insert(*index);
                self.roots[root].push(value.clone());
                if let Ok(method) = self.special_method(value, "__del__") {
                    if let Err(error) = self.call(method, Vec::new(), Vec::new(), None) {
                        eprintln!("Exception ignored during finalization:");
                        self.report_exception(&error);
                    }
                }
                self.roots[root].clear();
            }
        }
        self.gc_running = previous_gc;
        self.roots.truncate(root);
        let marked = self.gc_marks(&[]);
        for index in order {
            if !marked[index] && matches!(self.heap[index], Some(Object::BufferLease(_))) {
                self.buffer_invalidate_lease_views(index);
                self.buffer_close_lease(index)?;
            }
        }
        Ok(())
    }
    fn buffer_kind(&self, value: &Value) -> Option<&'static str> {
        let Value::Obj(index) = value else {
            return None;
        };
        match self.heap.get(*index).and_then(Option::as_ref) {
            Some(Object::ByteArray(_)) => Some("bytearray"),
            Some(Object::MemoryView(_)) => Some("memoryview"),
            Some(Object::BufferLease(_)) => Some("_buffer_wrapper"),
            _ => None,
        }
    }
    fn buffer_view(&self, value: &Value) -> PyResult<MemoryViewData> {
        let Value::Obj(index) = value else {
            return Err(pyerr("TypeError", "expected memoryview"));
        };
        let Some(Object::MemoryView(view)) = self.heap.get(*index).and_then(Option::as_ref) else {
            return Err(pyerr("TypeError", "expected memoryview"));
        };
        if view.released {
            return Err(pyerr(
                "ValueError",
                "operation forbidden on released memoryview object",
            ));
        }
        Ok((**view).clone())
    }
    fn buffer_lease(&self, index: usize) -> PyResult<BufferLeaseData> {
        let Some(Object::BufferLease(lease)) = self.heap.get(index).and_then(Option::as_ref) else {
            return Err(pyerr("ValueError", "buffer has been released"));
        };
        if !lease.active {
            return Err(pyerr("ValueError", "buffer has been released"));
        }
        Ok((**lease).clone())
    }
    fn buffer_owner_data(&self, owner: &Value) -> PyResult<Vec<u8>> {
        match owner {
            Value::Bytes(data) => Ok(data.to_vec()),
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::ByteArray(data)) => Ok(data.clone()),
                _ => Err(pyerr("TypeError", "invalid buffer owner")),
            },
            _ => Err(pyerr("TypeError", "invalid buffer owner")),
        }
    }
    fn buffer_offsets(view: &MemoryViewData, fortran: bool) -> PyResult<Vec<usize>> {
        let count = view
            .shape
            .iter()
            .try_fold(1usize, |count, size| count.checked_mul(*size))
            .ok_or_else(|| pyerr("OverflowError", "buffer shape is too large"))?;
        let mut output = Vec::new();
        output
            .try_reserve_exact(count)
            .map_err(|_| pyerr("MemoryError", "buffer is too large"))?;
        for index in 0..count {
            let mut remainder = index;
            let mut offset = view.offset;
            for axis in if fortran {
                (0..view.shape.len()).collect::<Vec<_>>()
            } else {
                (0..view.shape.len()).rev().collect::<Vec<_>>()
            } {
                let position = remainder % view.shape[axis];
                remainder /= view.shape[axis];
                offset = offset
                    .checked_add(
                        view.strides[axis]
                            .checked_mul(position as isize)
                            .ok_or_else(|| pyerr("OverflowError", "buffer offset is too large"))?,
                    )
                    .ok_or_else(|| pyerr("OverflowError", "buffer offset is too large"))?;
            }
            output.push(
                usize::try_from(offset)
                    .map_err(|_| pyerr("ValueError", "invalid buffer offset"))?,
            );
        }
        Ok(output)
    }
    fn buffer_contiguous(view: &MemoryViewData, fortran: bool) -> bool {
        if view.shape.iter().any(|size| *size == 0) {
            return true;
        }
        let mut stride = view.itemsize as isize;
        let axes: Vec<_> = if fortran {
            (0..view.shape.len()).collect()
        } else {
            (0..view.shape.len()).rev().collect()
        };
        for axis in axes {
            if view.shape[axis] > 1 && view.strides[axis] != stride {
                return false;
            }
            let Some(next) = stride.checked_mul(view.shape[axis] as isize) else {
                return false;
            };
            stride = next;
        }
        true
    }
    fn buffer_view_bytes(&self, view: &MemoryViewData, fortran: bool) -> PyResult<Vec<u8>> {
        let lease = self.buffer_lease(view.lease)?;
        let data = self.buffer_owner_slice(&lease.owner)?;
        let mut output = Vec::new();
        for offset in Self::buffer_offsets(view, fortran)? {
            let end = offset
                .checked_add(view.itemsize)
                .ok_or_else(|| pyerr("OverflowError", "buffer offset is too large"))?;
            output.extend_from_slice(
                data.get(offset..end)
                    .ok_or_else(|| pyerr("ValueError", "invalid buffer offset"))?,
            );
        }
        Ok(output)
    }
    fn buffer_new_native_view(&mut self, source: Value, payload: Value) -> PyResult<Value> {
        if self.buffer_kind(&payload) == Some("memoryview") {
            let mut view = self.buffer_view(&payload)?;
            view.exports = 0;
            view.hash = None;
            return Ok(self.obj_value(Object::MemoryView(Box::new(view))));
        }
        let data = self.buffer_owner_data(&payload)?;
        let readonly = matches!(payload, Value::Bytes(_));
        if let Value::Obj(owner) = &payload {
            *self.buffer_exports.entry(*owner).or_default() += 1;
        }
        let lease = self.alloc(Object::BufferLease(Box::new(BufferLeaseData {
            owner: payload,
            obj: source,
            exporter: None,
            exported_view: None,
            active: true,
            native_export: true,
        })));
        Ok(self.obj_value(Object::MemoryView(Box::new(MemoryViewData {
            lease,
            offset: 0,
            shape: vec![data.len()],
            strides: vec![1],
            format: "B".into(),
            itemsize: 1,
            readonly,
            released: false,
            exports: 0,
            hash: None,
        }))))
    }
    fn buffer_memoryview(&mut self, source: Value, flags: i128) -> PyResult<Value> {
        self.view_rooted(vec![source.clone()], |runtime, root| {
            if let Some(class) = runtime.object_class(&source) {
                if let Some(method) = runtime.slot_override(&class, "__buffer__", 0) {
                    let method = runtime.bind_descriptor(method, Some(source.clone()), class)?;
                    let returned = runtime.call(
                        method,
                        vec![Value::Int(Int::from_i128(flags).into())],
                        Vec::new(),
                        None,
                    )?;
                    runtime.roots[root].push(returned.clone());
                    if runtime.buffer_kind(&returned) != Some("memoryview") {
                        return Err(pyerr(
                            "TypeError",
                            "__buffer__ returned non-memoryview object",
                        ));
                    }
                    let mut view = Self::buffer_requested_view(runtime.buffer_view(&returned)?, flags)?;
                    if let Value::Obj(index) = &returned {
                        if let Some(Object::MemoryView(original)) = runtime.heap[*index].as_mut() {
                            original.exports += 1;
                        }
                    }
                    let previous = runtime.buffer_lease(view.lease)?;
                    let lease = runtime.alloc(Object::BufferLease(Box::new(BufferLeaseData {
                        owner: previous.owner,
                        obj: Value::None,
                        exporter: Some(source),
                        exported_view: Some(returned),
                        active: true,
                        native_export: false,
                    })));
                    view.lease = lease;
                    view.exports = 0;
                    view.hash = None;
                    return Ok(runtime.obj_value(Object::MemoryView(Box::new(view))));
                }
            }
            let payload = runtime
                .native_payload(&source)
                .unwrap_or_else(|| source.clone());
            if !matches!(payload, Value::Bytes(_))
                && !matches!(
                    runtime.buffer_kind(&payload),
                    Some("bytearray" | "memoryview")
                )
            {
                return Err(pyerr("TypeError", "a bytes-like object is required"));
            }
            let view = runtime.buffer_new_native_view(source, payload)?;
            let metadata = match Self::buffer_requested_view(runtime.buffer_view(&view)?, flags) {
                Ok(metadata) => metadata,
                Err(error) => {runtime.buffer_release(view)?;return Err(error);}
            };
            if let Value::Obj(index) = &view {
                runtime.heap[*index] = Some(Object::MemoryView(Box::new(metadata)));
            }
            Ok(view)
        })
    }
    fn buffer_close_lease(&mut self, index: usize) -> PyResult<()> {
        let Some(Object::BufferLease(lease)) = self.heap.get(index).and_then(Option::as_ref) else {
            return Ok(());
        };
        if !lease.active {
            return Ok(());
        }
        let lease = (**lease).clone();
        if let Some(Object::BufferLease(current)) = self.heap[index].as_mut() {
            current.active = false;
            current.owner = Value::None;
            current.obj = Value::None;
            current.exporter = None;
            current.exported_view = None;
        }
        if lease.native_export {
            if let Value::Obj(owner) = lease.owner {
                if let Some(count) = self.buffer_exports.get_mut(&owner) {
                    *count = count.saturating_sub(1);
                    if *count == 0 {
                        self.buffer_exports.remove(&owner);
                    }
                }
            }
        }
        if let Some(Value::Obj(index)) = &lease.exported_view {
            if let Some(Object::MemoryView(view)) = self.heap[*index].as_mut() {
                view.exports = view.exports.saturating_sub(1);
            }
        }
        if let (Some(exporter), Some(view)) = (lease.exporter, lease.exported_view) {
            self.view_rooted(vec![exporter.clone(), view.clone()], |runtime, _| {
                match runtime.special_method(exporter.clone(), "__release_buffer__") {
                    Ok(method) => {
                        if let Err(error) = runtime.call(method, vec![view], Vec::new(), None) {
                            eprintln!("Exception ignored in __release_buffer__:");
                            runtime.report_exception(&error);
                        }
                    }
                    Err(error)
                        if runtime.missing_special_method(
                            &exporter,
                            "__release_buffer__",
                            &error,
                        ) =>
                    {
                        ()
                    }
                    Err(error) => {
                        eprintln!("Exception ignored in __release_buffer__:");
                        runtime.report_exception(&error);
                    }
                }
                Ok(())
            })?;
        }
        Ok(())
    }
    fn buffer_release(&mut self, value: Value) -> PyResult<()> {
        let Value::Obj(index) = value else {
            return Err(pyerr("TypeError", "expected memoryview"));
        };
        if matches!(self.heap.get(index).and_then(Option::as_ref),Some(Object::MemoryView(view))if view.exports>0)
        {
            self.buffer_reclaim_view_exports(index)?;
        }
        let Some(Object::MemoryView(view)) = self.heap.get(index).and_then(Option::as_ref) else {
            return Err(pyerr("TypeError", "expected memoryview"));
        };
        if view.released {
            return Ok(());
        }
        if view.exports > 0 {
            return Err(pyerr("BufferError", "memoryview has exported buffers"));
        }
        let lease = view.lease;
        if let Some(Object::MemoryView(view)) = self.heap[index].as_mut() {
            view.released = true;
        }
        if !self.heap.iter().any(|object|matches!(object,Some(Object::MemoryView(view))if !view.released&&view.lease==lease)){self.buffer_close_lease(lease)?;}
        Ok(())
    }
    fn buffer_read(&mut self, value: &Value, contiguous: bool) -> PyResult<Option<Vec<u8>>> {
        let payload = self.native_payload(value).unwrap_or_else(|| value.clone());
        let custom = self
            .object_class(value)
            .and_then(|class| self.slot_override(&class, "__buffer__", 0))
            .is_some();
        if !custom
            && !matches!(payload, Value::Bytes(_))
            && !matches!(self.buffer_kind(&payload), Some("bytearray" | "memoryview"))
        {
            return Ok(None);
        }
        let view = self.buffer_memoryview(value.clone(), if contiguous { 0 } else { 284 })?;
        let result = self
            .buffer_view(&view)
            .and_then(|view| self.buffer_view_bytes(&view, false));
        self.buffer_release(view)?;
        result.map(Some)
    }
    fn buffer_byte(&mut self, value: &Value) -> PyResult<u8> {
        self.as_int(value)?
            .to_usize()
            .filter(|value| *value < 256)
            .map(|value| value as u8)
            .ok_or_else(|| pyerr("ValueError", "byte must be in range(0, 256)"))
    }
    fn buffer_sequence(&mut self, value: Value) -> PyResult<Vec<u8>> {
        if let Some(data) = self.buffer_read(&value, false)? {
            return Ok(data);
        }
        self.view_rooted(vec![value.clone()], |runtime, root| {
            let iterator = runtime.iter(value)?;
            runtime.roots[root].push(iterator.clone());
            let mut result = Vec::new();
            while let Some(value) = runtime.next(iterator.clone())? {
                runtime.roots[root].truncate(2);
                runtime.roots[root].push(value.clone());
                result.push(runtime.buffer_byte(&value)?);
            }
            Ok(result)
        })
    }
    fn buffer_bytearray_constructor(
        &mut self,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        let value = self.obj_value(Object::ByteArray(Vec::new()));
        self.view_rooted(vec![value.clone()], |runtime, _| {
            runtime.buffer_bytearray_init(value.clone(), args, kwargs)?;
            Ok(value)
        })
    }
    fn buffer_bytearray_init(
        &mut self,
        value: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        let mut fields = codec_bind("bytearray", args, kwargs, &["source", "encoding", "errors"])?;
        let data = if let Some(source) = fields[0].take() {
            let payload = self.native_capability_payload(&source,"str")
                .or_else(||self.native_payload(&source))
                .unwrap_or_else(|| source.clone());
            if matches!(payload, Value::Str(_)) {
                let encoding = fields[1]
                    .take()
                    .ok_or_else(|| pyerr("TypeError", "string argument without an encoding"))?;
                let mut args = vec![encoding];
                if let Some(errors) = fields[2].take() {
                    args.push(errors);
                }
                let encoded = self.codec_encode(payload, args, Vec::new())?;
                let Value::Bytes(data) = encoded else {
                    unreachable!()
                };
                data.into_inner()
            } else {
                if fields[1].is_some() || fields[2].is_some() {
                    return Err(pyerr(
                        "TypeError",
                        "encoding or errors without a string argument",
                    ));
                }
                let index = matches!(payload, Value::Int(_) | Value::Bool(_))
                    || self
                        .object_class(&source)
                        .and_then(|class| self.slot_definition(&class, "__index__", 0))
                        .is_some();
                if index {
                    let count = self.as_int(&source)?;
                    if count.is_negative() {
                        return Err(pyerr("ValueError", "negative count"));
                    }
                    let count = count
                        .to_usize()
                        .filter(|count| *count <= isize::MAX as usize)
                        .ok_or_else(|| {
                            pyerr("OverflowError", "cannot fit count into index-sized integer")
                        })?;
                    let mut data = Vec::new();
                    data.try_reserve_exact(count)
                        .map_err(|_| pyerr("MemoryError", "cannot allocate bytearray"))?;
                    data.resize(count, 0);
                    data
                } else {
                    self.buffer_sequence(source)?
                }
            }
        } else {
            if fields[1].is_some() || fields[2].is_some() {
                return Err(pyerr(
                    "TypeError",
                    "encoding or errors without a string argument",
                ));
            }
            Vec::new()
        };
        self.buffer_replace(value, data)?;
        Ok(Value::None)
    }
    fn buffer_replace(&mut self, value: Value, data: Vec<u8>) -> PyResult<()> {
        let payload = self.native_payload(&value).unwrap_or(value);
        let Value::Obj(index) = payload else {
            return Err(pyerr("TypeError", "expected bytearray"));
        };
        let Some(Object::ByteArray(previous)) = self.heap.get(index).and_then(Option::as_ref)
        else {
            return Err(pyerr("TypeError", "expected bytearray"));
        };
        if previous.len() != data.len() {
            self.buffer_check_resize(index)?;
        }
        self.heap[index] = Some(Object::ByteArray(data));
        Ok(())
    }
    fn buffer_check_resize(&mut self, index: usize) -> PyResult<()> {
        self.buffer_reclaim_exports(index)?;
        if self.buffer_exports.get(&index).copied().unwrap_or(0) > 0 {
            return Err(pyerr(
                "BufferError",
                "Existing exports of data: object cannot be re-sized",
            ));
        }
        Ok(())
    }
}

// bytearray's repr retains escaped apostrophes even when the byte literal
// selects double quotes. bytes repr itself does not add those escapes.
fn buffer_repr_bytes(source: &[u8]) -> String {
    let representation = text_repr_bytes(source);
    if representation.starts_with("b\"") { representation.replace("'", "\\'") }
    else { representation }
}
