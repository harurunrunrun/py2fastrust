// Float quotient/remainder algorithm adapted from CPython 3.14.0,
// Objects/floatobject.c: float_rem and _float_div_mod.
// https://github.com/python/cpython/blob/v3.14.0/Objects/floatobject.c
// Copyright Python Software Foundation; distributed under PSF License Version 2.
// The full PSF license accompanies this project and generated runtime output.
fn float_div_mod(left: f64, right: f64) -> PyResult<(f64, f64)> {
    if right == 0.0 {
        return Err(pyerr("ZeroDivisionError", "division by zero"));
    }
    let mut remainder = left % right;
    let mut quotient = (left - remainder) / right;
    if remainder != 0.0 {
        if (right < 0.0) != (remainder < 0.0) {
            remainder += right;
            quotient -= 1.0;
        }
    } else {
        remainder = 0.0f64.copysign(right);
    }
    let rounded = if quotient != 0.0 {
        let floor = quotient.floor();
        if quotient - floor > 0.5 {
            floor + 1.0
        } else {
            floor
        }
    } else {
        0.0f64.copysign(left / right)
    };
    Ok((rounded, remainder))
}

impl Runtime {
    // Only exact numeric payloads enter here. User subclasses first go through
    // normal/reflected slot dispatch, which resolves their current definitions.
    fn float_divmod_values(&mut self, left: &Value, right: &Value) -> Option<PyResult<Value>> {
        if !matches!(left, Value::Float(_) | Value::Int(_) | Value::Bool(_))
            || !matches!(right, Value::Float(_) | Value::Int(_) | Value::Bool(_))
            || (!matches!(left, Value::Float(_)) && !matches!(right, Value::Float(_)))
        {
            return None;
        }
        Some((|| {
            let (quotient, remainder) = float_div_mod(self.as_float(left)?, self.as_float(right)?)?;
            Ok(self.obj_value(Object::Tuple(vec![
                Value::Float(quotient.into()),
                Value::Float(remainder.into()),
            ])))
        })())
    }
}
