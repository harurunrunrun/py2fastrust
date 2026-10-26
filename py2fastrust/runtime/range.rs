// Range coordinates, lengths, and indices are structural integers. They must
// never use the selected wrapping arithmetic for user numeric expressions.
fn range_nonempty(start: &Int, stop: &Int, step: &Int) -> bool {
    if step.is_negative() {
        start > stop
    } else {
        start < stop
    }
}

fn range_cursor_next(current: &Int, stop: &Int, step: &Int) -> Int {
    let next = if let (Some(current), Some(step)) = (current.to_i128(), step.to_i128()) {
        if let Some(next) = current.checked_add(step) {
            Int::exact_small(next)
        } else if stop.to_i128().is_some() {
            return stop.clone();
        } else {
            Int::exact_small(current).exact_add(&Int::exact_small(step))
        }
    } else {
        current.exact_add(step)
    };
    if range_nonempty(&next, stop, step) {
        next
    } else {
        stop.clone()
    }
}

fn range_length_exact(start: &Int, stop: &Int, step: &Int) -> Int {
    if !range_nonempty(start, stop, step) {
        return Int::exact_small(0);
    }
    if let (Some(start), Some(stop), Some(step)) = (start.to_i128(), stop.to_i128(), step.to_i128())
    {
        let distance = if step < 0 {
            (start as u128).wrapping_sub(stop as u128)
        } else {
            (stop as u128).wrapping_sub(start as u128)
        };
        let length = (distance - 1) / step.unsigned_abs() + 1;
        if length <= i128::MAX as u128 {
            return Int::exact_small(length as i128);
        }
        return Int::exact_parts(
            false,
            vec![
                length as u32,
                (length >> 32) as u32,
                (length >> 64) as u32,
                (length >> 96) as u32,
            ],
        );
    }
    let distance = if step.is_negative() {
        start.exact_add(&stop.exact_neg())
    } else {
        stop.exact_add(&start.exact_neg())
    };
    let magnitude = if step.is_negative() {
        step.exact_neg()
    } else {
        step.clone()
    };
    distance
        .exact_add(&Int::exact_small(-1))
        .exact_divmod(&magnitude)
        .unwrap()
        .0
        .exact_add(&Int::exact_small(1))
}

fn range_length(start: &Int, stop: &Int, step: &Int) -> Result<usize, String> {
    let length = range_length_exact(start, stop, step);
    let value = length
        .to_usize()
        .filter(|n| *n <= isize::MAX as usize)
        .ok_or("OverflowError: Python int too large to convert to C ssize_t")?;
    Ok(value)
}

fn range_contains_integer(start: &Int, stop: &Int, step: &Int, value: &Int) -> bool {
    if !range_nonempty(start, stop, step) {
        return false;
    }
    let in_bounds = if step.is_negative() {
        value <= start && value > stop
    } else {
        value >= start && value < stop
    };
    in_bounds
        && value
            .exact_add(&start.exact_neg())
            .exact_divmod(step)
            .unwrap()
            .1
            .is_zero()
}

fn range_item(start: &Int, stop: &Int, step: &Int, index: &Int) -> Result<Int, String> {
    let length = range_length_exact(start, stop, step);
    let index = if index.is_negative() {
        index.exact_add(&length)
    } else {
        index.clone()
    };
    if index.is_negative() || index >= length {
        return Err("IndexError: range object index out of range".into());
    }
    Ok(start.exact_add(&step.exact_mul(&index)))
}

fn range_slice(
    start: &Int,
    stop: &Int,
    step: &Int,
    lower: Option<Int>,
    upper: Option<Int>,
    stride: Option<Int>,
) -> Result<(Int, Int, Int), String> {
    let stride = stride.unwrap_or_else(|| Int::exact_small(1));
    if stride.is_zero() {
        return Err("ValueError: slice step cannot be zero".into());
    }
    let length = range_length_exact(start, stop, step);
    let last = length.exact_add(&Int::exact_small(-1));
    let floor = if stride.is_negative() {
        Int::exact_small(-1)
    } else {
        Int::exact_small(0)
    };
    let ceiling = if stride.is_negative() {
        last.clone()
    } else {
        length.clone()
    };
    let adjust = |bound: Option<Int>, default: Int| {
        let Some(mut bound) = bound else {
            return default;
        };
        if bound.is_negative() {
            bound = bound.exact_add(&length);
        }
        bound.max(floor.clone()).min(ceiling.clone())
    };
    let lower = adjust(
        lower,
        if stride.is_negative() {
            last
        } else {
            Int::exact_small(0)
        },
    );
    let upper = adjust(
        upper,
        if stride.is_negative() {
            Int::exact_small(-1)
        } else {
            length.clone()
        },
    );
    Ok((
        start.exact_add(&step.exact_mul(&lower)),
        start.exact_add(&step.exact_mul(&upper)),
        step.exact_mul(&stride),
    ))
}

fn range_reversed(start: &Int, stop: &Int, step: &Int) -> (Int, Int, Int) {
    let length = range_length_exact(start, stop, step);
    let last = start.exact_add(&step.exact_mul(&length.exact_add(&Int::exact_small(-1))));
    (last, start.exact_add(&step.exact_neg()), step.exact_neg())
}

fn range_equal(a: (&Int, &Int, &Int), b: (&Int, &Int, &Int)) -> bool {
    let alen = range_length_exact(a.0, a.1, a.2);
    let blen = range_length_exact(b.0, b.1, b.2);
    alen == blen && (alen.is_zero() || (a.0 == b.0 && (alen == Int::exact_small(1) || a.2 == b.2)))
}

impl Runtime {
    fn range_hash(&mut self, start: Int, stop: Int, step: Int) -> PyResult<Value> {
        let length = range_length_exact(&start, &stop, &step);
        let first = if length.is_zero() {
            Value::None
        } else {
            Value::Int(start)
        };
        let stride = if length <= Int::exact_small(1) {
            Value::None
        } else {
            Value::Int(step)
        };
        let parts = self.obj_value(Object::Tuple(vec![Value::Int(length), first, stride]));
        self.call(Value::Builtin("hash".into()), vec![parts], Vec::new(), None)
    }

    fn range_getitem(&mut self, start: Int, stop: Int, step: Int, key: Value) -> PyResult<Value> {
        if let Value::Obj(index) = &key {
            if let Object::Slice(lower, upper, stride) = self.object(*index)? {
                let (start, stop, step) =
                    range_slice(&start, &stop, &step, lower, upper, stride).map_err(int_error)?;
                return Ok(self.obj_value(Object::Range(start, stop, step)));
            }
        }
        let index = self.as_int(&key)?;
        Ok(Value::Int(
            range_item(&start, &stop, &step, &index).map_err(int_error)?,
        ))
    }

    fn range_numeric_value(&self, value: &Value) -> Option<Int> {
        match value {
            Value::Int(value) => Some(value.clone()),
            Value::Bool(value) => Some(Int::exact_small(if *value { 1 } else { 0 })),
            Value::Float(value) if value.is_finite() && value.fract() == 0.0 => {
                Int::exact_from_f64(*value).ok()
            }
            _ => None,
        }
    }

    fn range_contains(&mut self, start: Int, stop: Int, step: Int, value: Value) -> PyResult<bool> {
        if let Some(number) = self.range_numeric_value(&value) {
            return Ok(range_contains_integer(&start, &stop, &step, &number));
        }
        if matches!(value, Value::Float(_)) {
            return Ok(false);
        }
        let mut current = start;
        while range_nonempty(&current, &stop, &step) {
            if self.equal(&Value::Int(current.clone()), &value)? {
                return Ok(true);
            }
            current = range_cursor_next(&current, &stop, &step);
        }
        Ok(false)
    }

    fn range_method(
        &mut self,
        start: Int,
        stop: Int,
        step: Int,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        if !kwargs.is_empty() || args.len() != 1 {
            return Err(pyerr(
                "TypeError",
                "range method expects one positional argument",
            ));
        }
        let value = &args[0];
        if let Some(number) = self.range_numeric_value(value) {
            let contains = range_contains_integer(&start, &stop, &step, &number);
            if name == "count" {
                return Ok(Value::Int(Int::exact_small(if contains { 1 } else { 0 })));
            }
            if contains {
                return Ok(Value::Int(
                    number
                        .exact_add(&start.exact_neg())
                        .exact_divmod(&step)
                        .map_err(int_error)?
                        .0,
                ));
            }
            return Err(pyerr("ValueError", "value is not in range"));
        }
        if matches!(value, Value::Float(_)) {
            return if name == "count" {
                Ok(Value::Int(Int::exact_small(0)))
            } else {
                Err(pyerr("ValueError", "value is not in range"))
            };
        }
        let mut current = start;
        let mut index = Int::exact_small(0);
        let mut count = Int::exact_small(0);
        while range_nonempty(&current, &stop, &step) {
            if self.equal(&Value::Int(current.clone()), value)? {
                if name == "index" {
                    return Ok(Value::Int(index));
                }
                count = count.exact_add(&Int::exact_small(1));
            }
            current = range_cursor_next(&current, &stop, &step);
            index = index.exact_add(&Int::exact_small(1));
        }
        if name == "count" {
            Ok(Value::Int(count))
        } else {
            Err(pyerr("ValueError", "value is not in range"))
        }
    }
}
