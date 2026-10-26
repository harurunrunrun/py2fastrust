// Complex arithmetic uses binary64 components and the Python numeric protocol.
// Parsing, formatting, and object conversions require no host Python runtime.
// Independent implementation of the documented numeric semantics, checked
// against Python 3.14: https://docs.python.org/3.14/library/stdtypes.html#numeric-types-int-float-complex
#[derive(Clone, Copy, Debug, PartialEq)]
struct Complex {
    real: f64,
    imag: f64,
}
impl Complex {
    fn new(real: f64, imag: f64) -> Self {
        Self { real, imag }
    }
    fn mul(self, other: Self) -> Self {
        let (a, b, c, d) = (self.real, self.imag, other.real, other.imag);
        let (mut real, mut imag) = (a * c - b * d, a * d + b * c);
        if real.is_nan() && imag.is_nan() {
            let (mut a, mut b, mut c, mut d) = (a, b, c, d);
            let mut recover = false;
            if a.is_infinite() || b.is_infinite() {
                a = if a.is_infinite() {
                    1.0f64.copysign(a)
                } else {
                    0.0f64.copysign(a)
                };
                b = if b.is_infinite() {
                    1.0f64.copysign(b)
                } else {
                    0.0f64.copysign(b)
                };
                if c.is_nan() {
                    c = 0.0f64.copysign(c);
                }
                if d.is_nan() {
                    d = 0.0f64.copysign(d);
                }
                recover = true;
            }
            if c.is_infinite() || d.is_infinite() {
                c = if c.is_infinite() {
                    1.0f64.copysign(c)
                } else {
                    0.0f64.copysign(c)
                };
                d = if d.is_infinite() {
                    1.0f64.copysign(d)
                } else {
                    0.0f64.copysign(d)
                };
                if a.is_nan() {
                    a = 0.0f64.copysign(a);
                }
                if b.is_nan() {
                    b = 0.0f64.copysign(b);
                }
                recover = true;
            }
            if !recover && [a * c, b * d, a * d, b * c].iter().any(|x| x.is_infinite()) {
                if a.is_nan() {
                    a = 0.0f64.copysign(a);
                }
                if b.is_nan() {
                    b = 0.0f64.copysign(b);
                }
                if c.is_nan() {
                    c = 0.0f64.copysign(c);
                }
                if d.is_nan() {
                    d = 0.0f64.copysign(d);
                }
                recover = true;
            }
            if recover {
                real = f64::INFINITY * (a * c - b * d);
                imag = f64::INFINITY * (a * d + b * c);
            }
        }
        Self::new(real, imag)
    }
    fn div(self, other: Self) -> PyResult<Self> {
        let (a, b, c, d) = (self.real, self.imag, other.real, other.imag);
        if c == 0.0 && d == 0.0 {
            return Err(pyerr("ZeroDivisionError", "complex division by zero"));
        }
        let (mut real, mut imag) = if c.abs() >= d.abs() {
            let ratio = d / c;
            let divisor = c + d * ratio;
            ((a + b * ratio) / divisor, (b - a * ratio) / divisor)
        } else {
            let ratio = c / d;
            let divisor = c * ratio + d;
            ((a * ratio + b) / divisor, (b * ratio - a) / divisor)
        };
        if real.is_nan() && imag.is_nan() {
            if (a.is_infinite() || b.is_infinite()) && c.is_finite() && d.is_finite() {
                let aa = if a.is_infinite() {
                    1.0f64.copysign(a)
                } else {
                    0.0f64.copysign(a)
                };
                let bb = if b.is_infinite() {
                    1.0f64.copysign(b)
                } else {
                    0.0f64.copysign(b)
                };
                real = f64::INFINITY * (aa * c + bb * d);
                imag = f64::INFINITY * (bb * c - aa * d);
            } else if (c.is_infinite() || d.is_infinite()) && a.is_finite() && b.is_finite() {
                let cc = if c.is_infinite() {
                    1.0f64.copysign(c)
                } else {
                    0.0f64.copysign(c)
                };
                let dd = if d.is_infinite() {
                    1.0f64.copysign(d)
                } else {
                    0.0f64.copysign(d)
                };
                real = 0.0 * (a * cc + b * dd);
                imag = 0.0 * (b * cc - a * dd);
            }
        }
        Ok(Self::new(real, imag))
    }
    fn pow(self, other: Self) -> PyResult<Self> {
        if other.real == 0.0 && other.imag == 0.0 {
            return Ok(Self::new(1.0, 0.0));
        }
        if self.real == 0.0 && self.imag == 0.0 {
            if other.imag != 0.0 || other.real < 0.0 {
                return Err(pyerr(
                    "ZeroDivisionError",
                    "zero to a negative or complex power",
                ));
            }
            if other.real.fract() != 0.0 || other.real.abs() > 100.0 {
                return Ok(Self::new(0.0, 0.0));
            }
        }
        let result = if other.imag == 0.0 && other.real.fract() == 0.0 && other.real.abs() <= 100.0
        {
            let mut power = other.real.abs() as u32;
            let mut factor = self;
            let mut result = Self::new(1.0, 0.0);
            while power != 0 {
                if power & 1 != 0 {
                    result = result.mul(factor);
                }
                power >>= 1;
                if power != 0 {
                    factor = factor.mul(factor);
                }
            }
            if other.real < 0.0 {
                Self::new(1.0, 0.0).div(result)?
            } else {
                result
            }
        } else {
            let length = self.real.hypot(self.imag);
            let angle = self.imag.atan2(self.real);
            let mut magnitude = length.powf(other.real);
            let mut phase = angle * other.real;
            if other.imag != 0.0 {
                magnitude /= (angle * other.imag).exp();
                phase += other.imag * length.ln();
            }
            if phase.is_infinite() {
                return Err(pyerr(
                    "ZeroDivisionError",
                    "zero to a negative or complex power",
                ));
            }
            Self::new(magnitude * phase.cos(), magnitude * phase.sin())
        };
        if result.real.is_infinite() || result.imag.is_infinite() {
            return Err(pyerr("OverflowError", "complex exponentiation"));
        }
        Ok(result)
    }
}
fn complex_float_repr(value: f64) -> String {
    if value.is_nan() {
        return "nan".into();
    }
    if value.is_infinite() {
        return if value.is_sign_negative() {
            "-inf"
        } else {
            "inf"
        }
        .into();
    }
    let mut text = text_format_exponent(&format!("{:?}", value), false);
    if text.ends_with(".0") {
        text.truncate(text.len() - 2);
    }
    text
}
fn complex_repr(value: Complex) -> String {
    let imag = complex_float_repr(value.imag);
    if value.real == 0.0 && !value.real.is_sign_negative() {
        return format!("{}j", imag);
    }
    format!(
        "({}{}{}j)",
        complex_float_repr(value.real),
        if value.imag.is_sign_negative() && !value.imag.is_nan() {
            ""
        } else {
            "+"
        },
        imag
    )
}
fn numeric_float_hash(number: f64, identity: u64) -> i64 {
    if number.is_nan() {
        return identity as i64;
    }
    if number.is_infinite() {
        return if number.is_sign_negative() {
            -314159
        } else {
            314159
        };
    }
    let bits = number.to_bits();
    let exponent = ((bits >> 52) & 0x7ff) as i32;
    let fraction = (bits & ((1u64 << 52) - 1)) | if exponent == 0 { 0 } else { 1u64 << 52 };
    let power = if exponent == 0 {
        -1074
    } else {
        exponent - 1023 - 52
    };
    let modulus = (1u128 << 61) - 1;
    let shift = power.rem_euclid(61) as u32;
    let residue = (((fraction as u128) << shift) % modulus) as i64;
    let value = if number.is_sign_negative() {
        -residue
    } else {
        residue
    };
    if value == -1 {
        -2
    } else {
        value
    }
}
fn numeric_int_hash(number: &Int) -> i64 {
    let modulus = (1u128 << 61) - 1;
    let mut residue = 0u128;
    for word in number.magnitude().iter().rev() {
        residue = ((residue << 32) + *word as u128) % modulus;
    }
    let hash = if number.is_negative() {
        -(residue as i64)
    } else {
        residue as i64
    };
    if hash == -1 {
        -2
    } else {
        hash
    }
}
fn complex_parse_float(source: &str) -> Option<f64> {
    if source.is_empty() {
        return None;
    }
    let chars: Vec<char> = source.chars().collect();
    for (index, ch) in chars.iter().enumerate() {
        if *ch == '_'
            && (index == 0
                || index + 1 == chars.len()
                || !chars[index - 1].is_ascii_digit()
                || !chars[index + 1].is_ascii_digit())
        {
            return None;
        }
    }
    let source = source.replace('_', "").to_ascii_lowercase();
    source.parse::<f64>().ok()
}
fn complex_parse(source: &str) -> PyResult<Complex> {
    let normalized: String = source
        .chars()
        .map(|ch| {
            if ch.is_whitespace() {
                ' '
            } else if let Some(digit) = Int::decimal_digit(ch).filter(|digit| *digit < 10) {
                char::from(b'0' + digit as u8)
            } else {
                ch
            }
        })
        .collect();
    let mut source = normalized.trim();
    if source.starts_with('(') && source.ends_with(')') {
        source = source[1..source.len() - 1].trim();
    }
    let invalid = || pyerr("ValueError", "complex() arg is a malformed string");
    if source.is_empty()
        || source
            .chars()
            .any(|ch| ch.is_whitespace() || ch == '(' || ch == ')')
    {
        return Err(invalid());
    }
    if source.ends_with('j') || source.ends_with('J') {
        let body = &source[..source.len() - 1];
        let split = body
            .char_indices()
            .filter(|(index, ch)| {
                *index != 0
                    && (*ch == '+' || *ch == '-')
                    && !matches!(body.as_bytes().get(*index - 1), Some(b'e' | b'E'))
            })
            .map(|(index, _)| index)
            .last();
        let imag = |text: &str| {
            if text.is_empty() || text == "+" {
                Some(1.0)
            } else if text == "-" {
                Some(-1.0)
            } else {
                complex_parse_float(text)
            }
        };
        if let Some(index) = split {
            return Ok(Complex::new(
                complex_parse_float(&body[..index]).ok_or_else(invalid)?,
                imag(&body[index..]).ok_or_else(invalid)?,
            ));
        }
        Ok(Complex::new(0.0, imag(body).ok_or_else(invalid)?))
    } else {
        Ok(Complex::new(
            complex_parse_float(source).ok_or_else(invalid)?,
            0.0,
        ))
    }
}
impl Runtime {
    fn complex_numeric(&mut self, value: &Value) -> PyResult<Option<Complex>> {
        Ok(match value {
            Value::Complex(number) => Some(**number),
            Value::Int(_) | Value::Float(_) | Value::Bool(_) => {
                Some(Complex::new(self.as_float(value)?, 0.0))
            }
            _ => None,
        })
    }
    fn complex_convert(&mut self, value: &Value, first: bool) -> PyResult<(Complex, bool)> {
        if let Value::Complex(number) = value {
            return Ok((**number, true));
        }
        if first {
            match self.special_method(value.clone(), "__complex__") {
                Ok(method) => {
                    let converted = self.call(method, Vec::new(), Vec::new(), None)?;
                    let payload = self.native_payload(&converted).unwrap_or(converted);
                    if let Value::Complex(number) = payload {
                        return Ok((*number, true));
                    }
                    return Err(pyerr("TypeError", "__complex__ returned non-complex"));
                }
                Err(error) if error.kind == "AttributeError" => {}
                Err(error) => return Err(error),
            }
        }
        if let Some(payload) = self.native_payload(value) {
            if matches!(payload, Value::Complex(_) | Value::Float(_) | Value::Int(_)) {
                return self.complex_convert(&payload, first);
            }
        }
        if let Some(number) = self.complex_numeric(value)? {
            return Ok((number, false));
        }
        for method in ["__float__", "__index__"] {
            match self.special_method(value.clone(), method) {
                Ok(function) => {
                    let result = self.call(function, Vec::new(), Vec::new(), None)?;
                    let payload = self.native_payload(&result).unwrap_or(result);
                    if method == "__float__" && !matches!(payload, Value::Float(_)) {
                        return Err(pyerr("TypeError", "__float__ returned non-float"));
                    }
                    if method == "__index__" && !matches!(payload, Value::Int(_) | Value::Bool(_)) {
                        return Err(pyerr("TypeError", "__index__ returned non-int"));
                    }
                    return Ok((Complex::new(self.as_float(&payload)?, 0.0), false));
                }
                Err(error) if error.kind == "AttributeError" => {}
                Err(error) => return Err(error),
            }
        }
        Err(pyerr(
            "TypeError",
            format!(
                "complex() argument must be a string or a number, not '{}'",
                self.typename(value)
            ),
        ))
    }
    fn complex_constructor(
        &mut self,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        let positional = args.len();
        let string_form = positional == 1 && kwargs.is_empty();
        let fields = codec_bind("complex", args, kwargs, &["real", "imag"])?;
        let single = fields[1].is_none();
        let real = fields[0].clone().unwrap_or(Value::Float(0.0.into()));
        let payload = self.native_payload(&real).unwrap_or_else(|| real.clone());
        if let Value::Str(text) = payload {
            if !string_form {
                return Err(pyerr(
                    "TypeError",
                    "complex() can't take second arg if first is a string",
                ));
            }
            return Ok(Value::Complex(complex_parse(&text)?.into()));
        }
        if single && matches!(real, Value::Complex(_)) {
            return Ok(real);
        }
        let (a, a_complex) = self.complex_convert(&real, true)?;
        let number = if let Some(imag) = &fields[1] {
            if matches!(
                self.native_payload(imag).unwrap_or_else(|| imag.clone()),
                Value::Str(_)
            ) {
                return Err(pyerr("TypeError", "complex() second arg can't be a string"));
            }
            let (b, b_complex) = self.complex_convert(imag, false)?;
            Complex::new(
                if b_complex { a.real - b.imag } else { a.real },
                if a_complex { a.imag + b.real } else { b.real },
            )
        } else {
            a
        };
        Ok(Value::Complex(number.into()))
    }
    fn complex_from_number(
        &mut self,
        mut args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        if args.len() != 2 || !kwargs.is_empty() {
            return Err(pyerr(
                "TypeError",
                "complex.from_number() takes exactly one positional argument",
            ));
        }
        let value = args.pop().unwrap();
        let class = args.pop().unwrap();
        if matches!(
            self.native_payload(&value).unwrap_or_else(|| value.clone()),
            Value::Str(_) | Value::Bytes(_)
        ) {
            return Err(pyerr(
                "TypeError",
                format!("must be real number, not {}", self.typename(&value)),
            ));
        }
        let number = if matches!(&value, Value::Complex(_)) {
            value
        } else {
            Value::Complex(self.complex_convert(&value, true)?.0.into())
        };
        self.call(class, vec![number], Vec::new(), None)
    }
    fn complex_binary(&mut self, op: &str, a: &Value, b: &Value) -> Option<PyResult<Value>> {
        if !matches!(a, Value::Complex(_)) && !matches!(b, Value::Complex(_)) {
            return None;
        }
        if !matches!(
            a,
            Value::Complex(_) | Value::Float(_) | Value::Int(_) | Value::Bool(_)
        ) || !matches!(
            b,
            Value::Complex(_) | Value::Float(_) | Value::Int(_) | Value::Bool(_)
        ) {
            return None;
        }
        Some((|| {
            let left = self.complex_numeric(a)?.unwrap();
            let right = self.complex_numeric(b)?.unwrap();
            let (ac, bc) = (
                matches!(a, Value::Complex(_)),
                matches!(b, Value::Complex(_)),
            );
            let result = match op {
                "+" | "+=" => Complex::new(
                    left.real + right.real,
                    if ac && bc {
                        left.imag + right.imag
                    } else if ac {
                        left.imag
                    } else {
                        right.imag
                    },
                ),
                "-" | "-=" => Complex::new(
                    left.real - right.real,
                    if ac && bc {
                        left.imag - right.imag
                    } else if ac {
                        left.imag
                    } else {
                        -right.imag
                    },
                ),
                "*" | "*=" => {
                    if ac && bc {
                        left.mul(right)
                    } else if ac {
                        Complex::new(left.real * right.real, left.imag * right.real)
                    } else {
                        Complex::new(left.real * right.real, left.real * right.imag)
                    }
                }
                "/" => {
                    if !bc {
                        if right.real == 0.0 {
                            return Err(pyerr("ZeroDivisionError", "complex division by zero"));
                        }
                        Complex::new(left.real / right.real, left.imag / right.real)
                    } else {
                        left.div(right)?
                    }
                }
                "**" => left.pow(right)?,
                _ => {
                    return Err(pyerr(
                        "TypeError",
                        format!(
                            "unsupported operand type(s) for {}: '{}' and '{}'",
                            op,
                            self.typename(a),
                            self.typename(b)
                        ),
                    ))
                }
            };
            Ok(Value::Complex(result.into()))
        })())
    }
    fn complex_equal(&self, a: &Value, b: &Value) -> Option<bool> {
        let (complex, other) = match (a, b) {
            (Value::Complex(value), other) | (other, Value::Complex(value)) => (**value, other),
            _ => return None,
        };
        Some(match other {
            Value::Complex(value) => complex.real == value.real && complex.imag == value.imag,
            Value::Float(value) => complex.imag == 0.0 && complex.real == **value,
            Value::Bool(value) => {
                complex.imag == 0.0 && complex.real == if *value { 1.0 } else { 0.0 }
            }
            Value::Int(value) => {
                complex.imag == 0.0
                    && value.cmp_f64(complex.real) == Some(std::cmp::Ordering::Equal)
            }
            _ => false,
        })
    }
    fn complex_hash(&mut self, value: &Value) -> PyResult<Value> {
        let Value::Complex(number) = value else {
            unreachable!()
        };
        let identity = self.identity_number(value);
        let hash = numeric_float_hash(number.real, identity)
            .wrapping_add(numeric_float_hash(number.imag, identity).wrapping_mul(1_000_003));
        Ok(Value::Int(
            Int::from_i128(if hash == -1 { -2 } else { hash as i128 }).into(),
        ))
    }
    fn complex_format(&self, number: Complex, specification: &str) -> PyResult<String> {
        let options = TextFormatSpec::parse(specification, true)?;
        if options.fill == '0' {
            return Err(pyerr(
                "ValueError",
                "Zero padding is not allowed in complex format specifier",
            ));
        }
        if options.align == '=' {
            return Err(pyerr(
                "ValueError",
                "'=' alignment flag is not allowed in complex format specifier",
            ));
        }
        if options
            .presentation
            .is_some_and(|ch| !"eEfFgGn".contains(ch))
        {
            return Err(pyerr(
                "ValueError",
                "Unknown format code for object of type 'complex'",
            ));
        }
        let has_real =
            options.presentation.is_some() || number.real != 0.0 || number.real.is_sign_negative();
        let part = |value: f64, sign: Option<char>| -> PyResult<String> {
            let part = TextFormatSpec {
                fill: ' ',
                align: '>',
                sign,
                negative_zero: options.negative_zero,
                alternate: options.alternate,
                width: 0,
                integer_group: options.integer_group,
                precision: options.precision,
                fractional_group: options.fractional_group,
                presentation: if options.presentation.is_none() && options.precision.is_some() {
                    Some('g')
                } else {
                    options.presentation
                },
            };
            let mut text = text_format_float(value, &part)?;
            if options.presentation.is_none() && options.precision.is_none() && text.ends_with(".0")
            {
                text.truncate(text.len() - if options.alternate { 1 } else { 2 });
            }
            Ok(text)
        };
        let text = if has_real {
            let text = format!(
                "{}{}j",
                part(number.real, options.sign)?,
                part(number.imag, Some('+'))?
            );
            if options.presentation.is_none() {
                format!("({})", text)
            } else {
                text
            }
        } else {
            format!("{}j", part(number.imag, options.sign)?)
        };
        text_format_pad(text, &options, 0)
    }
    fn complex_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        if name == "from_number" {
            let class = match &value {
                Value::Complex(_) => Some(Value::Builtin("complex".into())),
                Value::Builtin(class) if class == "complex" => Some(value.clone()),
                Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                    Some(Object::Class(_)) => Some(value.clone()),
                    Some(Object::BuiltinInstance {
                        class,
                        payload: Value::Complex(_),
                        ..
                    }) => Some(class.clone()),
                    _ => None,
                },
                _ => None,
            }?;
            if self.class_lookup(&class, name, 0).is_some() {
                return None;
            }
            match self.is_subclass(&class, &Value::Builtin("complex".into())) {
                Ok(true) => {}
                Ok(false) => return None,
                Err(error) => return Some(Err(error)),
            }
            return Some(Ok(self.obj_value(Object::Bound(
                Value::Builtin("complex:from_number".into()),
                class,
            ))));
        }
        if matches!(&value,Value::Builtin(class)if class=="complex") {
            if [
                "conjugate",
                "__complex__",
                "__getnewargs__",
                "__repr__",
                "__str__",
                "__format__",
                "__abs__",
                "__bool__",
                "__pos__",
                "__neg__",
                "__hash__",
                "__eq__",
                "__ne__",
                "__add__",
                "__radd__",
                "__sub__",
                "__rsub__",
                "__mul__",
                "__rmul__",
                "__truediv__",
                "__rtruediv__",
                "__pow__",
                "__rpow__",
            ]
            .contains(&name)
            {
                return Some(Ok(Value::Builtin(format!("unbound:complex:{}", name))));
            }
            return None;
        }
        let Value::Complex(number) = &value else {
            return None;
        };
        Some(match name {
            "real" => Ok(Value::Float(number.real.into())),
            "imag" => Ok(Value::Float(number.imag.into())),
            "conjugate" | "__complex__" | "__getnewargs__" | "__repr__" | "__str__"
            | "__format__" | "__abs__" | "__bool__" | "__pos__" | "__neg__" | "__hash__"
            | "__eq__" | "__ne__" | "__add__" | "__radd__" | "__sub__" | "__rsub__" | "__mul__"
            | "__rmul__" | "__truediv__" | "__rtruediv__" | "__pow__" | "__rpow__" => Ok(self
                .obj_value(Object::Bound(
                    Value::Builtin(format!("method:{}", name)),
                    value,
                ))),
            _ => return None,
        })
    }
    fn complex_method(
        &mut self,
        value: Value,
        name: &str,
        mut args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> Option<PyResult<Value>> {
        let Value::Complex(number) = &value else {
            return None;
        };
        let number = **number;
        Some((|| {
            if !kwargs.is_empty() {
                return Err(pyerr(
                    "TypeError",
                    "complex method takes no keyword arguments",
                ));
            }
            if ["__pow__", "__rpow__"].contains(&name) && args.len() == 2 {
                let modulus = args.pop().unwrap();
                if !matches!(modulus, Value::None) {
                    return Err(pyerr("ValueError", "complex modulo"));
                }
            }
            let arity = if [
                "__format__",
                "__eq__",
                "__ne__",
                "__add__",
                "__radd__",
                "__sub__",
                "__rsub__",
                "__mul__",
                "__rmul__",
                "__truediv__",
                "__rtruediv__",
                "__pow__",
                "__rpow__",
            ]
            .contains(&name)
            {
                1
            } else {
                0
            };
            if args.len() != arity {
                return Err(pyerr(
                    "TypeError",
                    format!("{}() takes {} arguments", name, arity),
                ));
            }
            match name {
                "conjugate" => Ok(Value::Complex(
                    Complex::new(number.real, -number.imag).into(),
                )),
                "__complex__" | "__pos__" => Ok(value),
                "__neg__" => Ok(Value::Complex(
                    Complex::new(-number.real, -number.imag).into(),
                )),
                "__repr__" | "__str__" => Ok(Value::Str(complex_repr(number).into())),
                "__bool__" => Ok(Value::Bool(number.real != 0.0 || number.imag != 0.0)),
                "__hash__" => self.complex_hash(&value),
                "__getnewargs__" => Ok(self.obj_value(Object::Tuple(vec![
                    Value::Float(number.real.into()),
                    Value::Float(number.imag.into()),
                ]))),
                "__abs__" => {
                    let magnitude = number.real.hypot(number.imag);
                    if magnitude.is_infinite() && number.real.is_finite() && number.imag.is_finite()
                    {
                        Err(pyerr("OverflowError", "absolute value too large"))
                    } else {
                        Ok(Value::Float(magnitude.into()))
                    }
                }
                "__format__" => {
                    let Value::Str(specification) = &args[0] else {
                        return Err(pyerr("TypeError", "format specifier must be str"));
                    };
                    Ok(Value::Str(
                        self.complex_format(number, specification)?.into(),
                    ))
                }
                "__eq__" | "__ne__" => {
                    let other = self
                        .native_payload(&args[0])
                        .unwrap_or_else(|| args[0].clone());
                    if matches!(
                        &other,
                        Value::Complex(_) | Value::Float(_) | Value::Int(_) | Value::Bool(_)
                    ) {
                        let equal = self.complex_equal(&value, &other).unwrap();
                        Ok(Value::Bool(if name == "__eq__" { equal } else { !equal }))
                    } else {
                        Ok(Value::Builtin("NotImplemented".into()))
                    }
                }
                _ => {
                    let (op, reflected) = match name {
                        "__add__" => ("+", false),
                        "__radd__" => ("+", true),
                        "__sub__" => ("-", false),
                        "__rsub__" => ("-", true),
                        "__mul__" => ("*", false),
                        "__rmul__" => ("*", true),
                        "__truediv__" => ("/", false),
                        "__rtruediv__" => ("/", true),
                        "__pow__" => ("**", false),
                        "__rpow__" => ("**", true),
                        _ => return Err(pyerr("AttributeError", name)),
                    };
                    let other = self
                        .native_payload(&args[0])
                        .unwrap_or_else(|| args[0].clone());
                    let result = if reflected {
                        self.complex_binary(op, &other, &value)
                    } else {
                        self.complex_binary(op, &value, &other)
                    };
                    result.unwrap_or(Ok(Value::Builtin("NotImplemented".into())))
                }
            }
        })())
    }
}
