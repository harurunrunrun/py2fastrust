// Python math compatibility using Rust std, without an external crate or FFI.
//
// Lanczos coefficients, gamma/lgamma, sinpi, the error-function series and
// continued fraction, and compensated-sum rounding are adapted from CPython:
// https://github.com/python/cpython/blob/3.14/Modules/mathmodule.c
// https://github.com/python/cpython/blob/3.10/Modules/mathmodule.c
// Copyright (c) 2001-2026 Python Software Foundation. All rights reserved.
// Distributed under the Python Software Foundation License, Version 2.
// The complete license is distributed in py2fastrust/stdlib/PYTHON_LICENSE.txt and
// is included in the generated runtime notice by the source packager.

fn math_domain() -> PyException {
    pyerr("ValueError", "math domain error")
}
fn math_overflow() -> PyException {
    pyerr("OverflowError", "math range error")
}

// Error-free summation, followed by one nearest-even rounding of the expansion.
struct MathFsum {
    partials: Vec<f64>,
    infinity: f64,
    special: f64,
}
impl MathFsum {
    fn new() -> Self {
        Self {
            partials: Vec::new(),
            infinity: 0.0,
            special: 0.0,
        }
    }
    fn push(&mut self, mut x: f64) -> PyResult<()> {
        let original = x;
        let mut count = 0;
        for j in 0..self.partials.len() {
            let mut y = self.partials[j];
            if x.abs() < y.abs() {
                std::mem::swap(&mut x, &mut y);
            }
            let high = x + y;
            let low = y - (high - x);
            if low != 0.0 {
                self.partials[count] = low;
                count += 1;
            }
            x = high;
        }
        self.partials.truncate(count);
        if x != 0.0 {
            if !x.is_finite() {
                if original.is_finite() {
                    return Err(pyerr("OverflowError", "intermediate overflow in fsum"));
                }
                if original.is_infinite() {
                    self.infinity += original;
                }
                self.special += original;
                self.partials.clear();
            } else {
                self.partials.push(x);
            }
        }
        Ok(())
    }
    fn finish(mut self) -> PyResult<f64> {
        if self.special != 0.0 {
            if self.infinity.is_nan() {
                return Err(pyerr("ValueError", "-inf + inf in fsum"));
            }
            return Ok(self.special);
        }
        let mut high = self.partials.pop().unwrap_or(0.0);
        let mut low = 0.0;
        while let Some(y) = self.partials.pop() {
            let x = high;
            high = x + y;
            low = y - (high - x);
            if low != 0.0 {
                break;
            }
        }
        if self.partials.last().map_or(false, |&last| {
            (low < 0.0 && last < 0.0) || (low > 0.0 && last > 0.0)
        }) {
            let twice = low * 2.0;
            let rounded = high + twice;
            if rounded - high == twice {
                high = rounded;
            }
        }
        Ok(high)
    }
}

fn math_two_sum(a: f64, b: f64) -> (f64, f64) {
    let high = a + b;
    let z = high - a;
    (high, (a - (high - z)) + (b - z))
}
#[derive(Default)]
struct MathTriple {
    high: f64,
    low: f64,
    tiny: f64,
}
impl MathTriple {
    fn add_product(&mut self, x: f64, y: f64) -> bool {
        let product = x * y;
        if !product.is_finite() {
            return false;
        }
        let residual = x.mul_add(y, -product);
        let a = math_two_sum(self.high, product);
        let b = math_two_sum(self.low, residual);
        let c = math_two_sum(b.0, a.1);
        if !a.0.is_finite() || !c.0.is_finite() {
            return false;
        }
        self.high = a.0;
        self.low = c.0;
        self.tiny += b.1 + c.1;
        true
    }
    fn value(&self) -> f64 {
        let last = math_two_sum(self.low, self.high);
        self.tiny + last.1 + last.0
    }
}

fn math_frexp(x: f64) -> (f64, i32) {
    if x == 0.0 || !x.is_finite() {
        return (x, 0);
    }
    let (value, correction) = if x.abs() < f64::MIN_POSITIVE {
        (x * 18014398509481984.0, -54)
    } else {
        (x, 0)
    };
    let bits = value.to_bits();
    (
        f64::from_bits((bits & ((1u64 << 63) | ((1u64 << 52) - 1))) | (1022u64 << 52)),
        ((bits >> 52) & 0x7ff) as i32 - 1022 + correction,
    )
}
fn math_scale(mut x: f64, mut exponent: i64) -> f64 {
    if x == 0.0 || !x.is_finite() {
        return x;
    }
    if exponent > 1023 {
        x *= f64::from_bits(2046u64 << 52);
        exponent -= 1023;
        if exponent > 1023 {
            x *= f64::from_bits(2046u64 << 52);
            exponent = (exponent - 1023).min(1023);
        }
    }
    if exponent < -1022 {
        // Keep the intermediate normal so subnormal results are rounded once.
        x *= f64::from_bits(54u64 << 52);
        exponent += 969;
        if exponent < -1022 {
            x *= f64::from_bits(54u64 << 52);
            exponent = (exponent + 969).max(-1022);
        }
    }
    x * f64::from_bits(((exponent + 1023) as u64) << 52)
}
fn math_nextafter(x: f64, y: f64, steps: u64) -> f64 {
    if steps == 0 {
        return x;
    }
    if x.is_nan() {
        return x;
    }
    if y.is_nan() || x == y {
        return y;
    }
    let sign = 1u64 << 63;
    let a = x.to_bits();
    let b = y.to_bits();
    let ax = a & !sign;
    let ay = b & !sign;
    if (a ^ b) & sign != 0 {
        if ax + ay <= steps {
            y
        } else if ax < steps {
            f64::from_bits((b & sign) | (steps - ax))
        } else {
            f64::from_bits((a & sign) | (ax - steps))
        }
    } else if ax > ay {
        if steps >= ax - ay {
            y
        } else {
            f64::from_bits((a & sign) | (ax - steps))
        }
    } else if steps >= ay - ax {
        y
    } else {
        f64::from_bits((a & sign) | (ax + steps))
    }
}
fn math_remainder(x: f64, y: f64) -> PyResult<f64> {
    if x.is_nan() {
        return Ok(x);
    }
    if y.is_nan() {
        return Ok(y);
    }
    if x.is_infinite() || y == 0.0 {
        return Err(math_domain());
    }
    if y.is_infinite() {
        return Ok(x);
    }
    let a = x.abs();
    let b = y.abs();
    let remainder = a % b;
    let complement = b - remainder;
    let r = if remainder < complement {
        remainder
    } else if remainder > complement {
        -complement
    } else if (0.5 * (a - remainder)) % b == 0.0 {
        remainder
    } else {
        -remainder
    };
    Ok(if x.is_sign_negative() { -r } else { r })
}

fn math_sinpi(x: f64) -> f64 {
    let y = x.abs() % 2.0;
    let result = match (2.0 * y).round() as u32 {
        0 => (std::f64::consts::PI * y).sin(),
        1 => (std::f64::consts::PI * (y - 0.5)).cos(),
        2 => (std::f64::consts::PI * (1.0 - y)).sin(),
        3 => -(std::f64::consts::PI * (y - 1.5)).cos(),
        _ => (std::f64::consts::PI * (y - 2.0)).sin(),
    };
    if x.is_sign_negative() {
        -result
    } else {
        result
    }
}
fn math_lanczos(x: f64) -> f64 {
    const NUM: [f64; 13] = [
        23531376880.410759688572007674451636754734846804940,
        42919803642.649098768957899047001988850926355848959,
        35711959237.355668049440185451547166705960488635843,
        17921034426.037209699919755754458931112671403265390,
        6039542586.3520280050642916443072979210699388420708,
        1439720407.3117216736632230727949123939715485786772,
        248874557.86205415651146038641322942321632125127801,
        31426415.585400194380614231628318205362874684987640,
        2876370.6289353724412254090516208496135991145378768,
        186056.26539522349504029498971604569928220784236328,
        8071.6720023658162106380029022722506138218516325024,
        210.82427775157934587250973392071336271166969580291,
        2.5066282746310002701649081771338373386264310793408,
    ];
    const DEN: [f64; 13] = [
        0.0,
        39916800.0,
        120543840.0,
        150917976.0,
        105258076.0,
        45995730.0,
        13339535.0,
        2637558.0,
        357423.0,
        32670.0,
        1925.0,
        66.0,
        1.0,
    ];
    let (mut numerator, mut denominator) = (0.0, 0.0);
    if x < 5.0 {
        for i in (0..13).rev() {
            numerator = numerator * x + NUM[i];
            denominator = denominator * x + DEN[i];
        }
    } else {
        for i in 0..13 {
            numerator = numerator / x + NUM[i];
            denominator = denominator / x + DEN[i];
        }
    }
    numerator / denominator
}
fn math_gamma(x: f64, logarithm: bool) -> PyResult<f64> {
    const G: f64 = 6.024680040776729583740234375;
    const GM: f64 = 5.524680040776729583740234375;
    if x.is_nan() {
        return Ok(x);
    }
    if x.is_infinite() {
        return if logarithm {
            Ok(f64::INFINITY)
        } else if x > 0.0 {
            Ok(x)
        } else {
            Err(math_domain())
        };
    }
    if x <= 0.0 && x == x.floor() {
        return Err(math_domain());
    }
    if logarithm && (x == 1.0 || x == 2.0) {
        return Ok(0.0);
    }
    if !logarithm && x > 0.0 && x <= 23.0 && x == x.floor() {
        let mut result = 1.0;
        for i in 2..x as usize {
            result *= i as f64;
        }
        return Ok(result);
    }
    let a = x.abs();
    if logarithm {
        let mut result = if a < 1e-20 {
            -a.ln()
        } else {
            math_lanczos(a).ln() - G + (a - 0.5) * ((a + G - 0.5).ln() - 1.0)
        };
        if x < 0.0 && a >= 1e-20 {
            result = 1.144729885849400174143427351353058711647
                - math_sinpi(a).abs().ln()
                - a.ln()
                - result;
        }
        return if result.is_infinite() {
            Err(math_overflow())
        } else {
            Ok(result)
        };
    }
    if a < 1e-20 {
        let result = 1.0 / x;
        return if result.is_infinite() {
            Err(math_overflow())
        } else {
            Ok(result)
        };
    }
    if a > 200.0 {
        return if x < 0.0 {
            Ok(0.0 / math_sinpi(x))
        } else {
            Err(math_overflow())
        };
    }
    let y = a + GM;
    let error = if a > GM { (y - a) - GM } else { (y - GM) - a } * G / y;
    let mut result;
    if x < 0.0 {
        result = -std::f64::consts::PI / math_sinpi(a) / a * y.exp() / math_lanczos(a);
        result -= error * result;
        if a < 140.0 {
            result /= y.powf(a - 0.5);
        } else {
            let half = y.powf(a / 2.0 - 0.25);
            result /= half;
            result /= half;
        }
    } else {
        result = math_lanczos(a) / y.exp();
        result += error * result;
        if a < 140.0 {
            result *= y.powf(a - 0.5);
        } else {
            let half = y.powf(a / 2.0 - 0.25);
            result *= half;
            result *= half;
        }
    }
    if result.is_infinite() {
        Err(math_overflow())
    } else {
        Ok(result)
    }
}
fn math_erf_series(x: f64) -> f64 {
    let square = x * x;
    let mut sum = 0.0;
    let mut denominator = 25.5;
    for _ in 0..25 {
        sum = 2.0 + square * sum / denominator;
        denominator -= 1.0;
    }
    sum * x * (-square).exp() / 1.772453850905516027298167483341145182798
}
fn math_erfc_fraction(x: f64) -> f64 {
    if x >= 30.0 {
        return 0.0;
    }
    let square = x * x;
    let (mut a, mut delta, mut p, mut previous_p, mut q, mut previous_q) =
        (0.0, 0.5, 1.0, 0.0, 0.5 + square, 1.0);
    for _ in 0..50 {
        a += delta;
        delta += 2.0;
        let b = delta + square;
        let old_p = p;
        p = b * p - a * previous_p;
        previous_p = old_p;
        let old_q = q;
        q = b * q - a * previous_q;
        previous_q = old_q;
    }
    p / q * x * (-square).exp() / 1.772453850905516027298167483341145182798
}
fn math_erf(x: f64, complement: bool) -> f64 {
    if x.is_nan() {
        return x;
    }
    if x.abs() < 1.5 {
        let result = math_erf_series(x);
        return if complement { 1.0 - result } else { result };
    }
    let result = math_erfc_fraction(x.abs());
    if complement {
        if x > 0.0 {
            result
        } else {
            2.0 - result
        }
    } else if x > 0.0 {
        1.0 - result
    } else {
        result - 1.0
    }
}
fn math_norm(values: &[f64]) -> f64 {
    let largest = values.iter().fold(0.0f64, |n, x| n.max(x.abs()));
    if largest.is_infinite() {
        return largest;
    }
    if values.iter().any(|x| x.is_nan()) {
        return f64::NAN;
    }
    if largest == 0.0 {
        return 0.0;
    }
    let exponent = math_frexp(largest).1 as i64;
    let mut total = MathTriple::default();
    for &x in values {
        let scaled = math_scale(x, -exponent);
        total.add_product(scaled, scaled);
    }
    math_scale(total.value().sqrt(), exponent)
}

impl Runtime {
    fn math_keep(&mut self, root: usize, slot: usize, value: Value) -> Value {
        if self.roots[root].len() <= slot {
            self.roots[root].resize_with(slot + 1, || Value::None);
        }
        self.roots[root][slot] = value.clone();
        value
    }
    fn math_float(&mut self, value: &Value) -> PyResult<f64> {
        if matches!(value, Value::Float(_) | Value::Int(_) | Value::Bool(_)) {
            return self.as_float(value);
        }
        match self.getattr(value.clone(), "__float__") {
            Ok(method) => {
                let result = self.call(method, Vec::new(), Vec::new(), None)?;
                if let Value::Float(x) = result {
                    return Ok(*x);
                }
                return Err(pyerr("TypeError", "__float__ returned non-float"));
            }
            Err(error) if error.kind != "AttributeError" => return Err(error),
            _ => {}
        }
        let integer = self.as_int(value)?;
        self.as_float(&Value::Int(integer.into()))
    }
    fn math_log(&mut self, value: &Value, base: &str) -> PyResult<f64> {
        if let Value::Int(n) = value {
            if n.is_negative() || n.is_zero() {
                return Err(math_domain());
            }
            let bits = n.bit_length();
            if bits > 1023 {
                let scale = Int::exact_parts(false, Int::nat_shl(&[1], bits));
                let fraction = n.ratio(&scale).map_err(int_error)?;
                return Ok(match base {
                    "log2" => fraction.log2() + bits as f64,
                    "log10" => fraction.log10() + bits as f64 * std::f64::consts::LOG10_2,
                    _ => fraction.ln() + bits as f64 * std::f64::consts::LN_2,
                });
            }
        }
        let x = self.math_float(value)?;
        if x <= 0.0 {
            return Err(math_domain());
        }
        Ok(match base {
            "log2" => x.log2(),
            "log10" => x.log10(),
            _ => x.ln(),
        })
    }
    fn math_call(
        &mut self,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        let root = self.roots.len();
        let mut values = args.clone();
        values.extend(kwargs.iter().map(|(_, value)| value.clone()));
        self.roots.push(values);
        let result = self.math_dispatch(name, args, kwargs, root);
        self.roots.truncate(root);
        result
    }
    fn math_dispatch(
        &mut self,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
        root: usize,
    ) -> PyResult<Value> {
        let base = self.roots[root].len();
        let (minimum, maximum) = match name {
            "gcd" | "lcm" | "hypot" => (0, usize::MAX),
            "comb" | "atan2" | "copysign" | "fmod" | "remainder" | "pow" | "ldexp" | "isclose"
            | "dist" | "sumprod" | "nextafter" => (2, 2),
            "fma" => (3, 3),
            "log" | "perm" => (1, 2),
            _ => (1, 1),
        };
        if args.len() < minimum || args.len() > maximum {
            return Err(pyerr(
                "TypeError",
                format!("math.{}() received an invalid number of arguments", name),
            ));
        }
        let allowed: &[&str] = match name {
            "isclose" => &["rel_tol", "abs_tol"],
            "prod" => &["start"],
            "nextafter" => &["steps"],
            _ => &[],
        };
        let mut seen = std::collections::HashSet::new();
        for (keyword, _) in &kwargs {
            if !allowed.contains(&keyword.as_str()) || !seen.insert(keyword.as_str()) {
                return Err(pyerr(
                    "TypeError",
                    format!("invalid keyword argument for math.{}(): {}", name, keyword),
                ));
            }
        }
        match name {
            "gcd" | "lcm" => {
                let mut result = Int::exact_small(if name == "gcd" { 0 } else { 1 });
                for value in &args {
                    let n = self.as_int(value)?;
                    let n = if n.is_negative() { n.exact_neg() } else { n };
                    let (mut a, mut b) = (result.clone(), n.clone());
                    while !b.is_zero() {
                        let remainder = a.exact_divmod(&b).map_err(int_error)?.1;
                        a = b;
                        b = remainder;
                    }
                    result = if name == "gcd" {
                        a
                    } else if a.is_zero() {
                        Int::exact_small(0)
                    } else {
                        result.exact_divmod(&a).map_err(int_error)?.0.exact_mul(&n)
                    };
                }
                return Ok(Value::Int(result.normalized().into()));
            }
            "factorial" | "comb" | "perm" => {
                let n = self.as_int(&args[0])?;
                if n.is_negative() {
                    return Err(pyerr("ValueError", "n must be a non-negative integer"));
                }
                let mut k = if name == "factorial"
                    || args.len() == 1
                    || (name == "perm" && matches!(args[1], Value::None))
                {
                    n.clone()
                } else {
                    self.as_int(&args[1])?
                };
                if k.is_negative() {
                    return Err(pyerr("ValueError", "k must be a non-negative integer"));
                }
                if k > n {
                    return Ok(Value::Int(Int::from_i128(0).into()));
                }
                if name == "comb" {
                    let complement = n.exact_add(&k.exact_neg());
                    if complement < k {
                        k = complement;
                    }
                }
                let count = k
                    .to_usize()
                    .ok_or_else(|| pyerr("OverflowError", "integer argument is too large"))?;
                let mut result = Int::exact_small(1);
                for i in 0..count {
                    result = result.exact_mul(&n.exact_add(&Int::exact_small(-(i as i128))));
                    if name == "comb" {
                        result = result
                            .exact_divmod(&Int::exact_small((i + 1) as i128))
                            .map_err(int_error)?
                            .0;
                    }
                }
                return Ok(Value::Int(result.normalized().into()));
            }
            "isqrt" => {
                let n = self.as_int(&args[0])?;
                if n.is_negative() {
                    return Err(pyerr("ValueError", "isqrt() argument must be nonnegative"));
                }
                if n.is_zero() {
                    return Ok(Value::Int(n.into()));
                }
                let mut x = Int::exact_parts(false, Int::nat_shl(&[1], (n.bit_length() + 1) / 2));
                loop {
                    let y = x
                        .exact_add(&n.exact_divmod(&x).map_err(int_error)?.0)
                        .exact_divmod(&Int::exact_small(2))
                        .map_err(int_error)?
                        .0;
                    if y >= x {
                        return Ok(Value::Int(x.normalized().into()));
                    }
                    x = y;
                }
            }
            "ceil" | "floor" | "trunc" => {
                if let Value::Int(n) = &args[0] {
                    return Ok(Value::Int(n.clone()));
                }
                if let Value::Bool(b) = &args[0] {
                    return Ok(Value::Int(Int::from_i128(i128::from(*b)).into()));
                }
                if !matches!(args[0], Value::Float(_)) {
                    match self.getattr(args[0].clone(), &format!("__{}__", name)) {
                        Ok(method) => return self.call(method, Vec::new(), Vec::new(), None),
                        Err(error) if error.kind != "AttributeError" => return Err(error),
                        _ => {}
                    }
                    if name == "trunc" {
                        return Err(pyerr("TypeError", "type does not define __trunc__ method"));
                    }
                }
                let x = self.math_float(&args[0])?;
                let result = match name {
                    "ceil" => x.ceil(),
                    "floor" => x.floor(),
                    _ => x.trunc(),
                };
                return Ok(Value::Int(Int::from_f64(result).map_err(int_error)?.into()));
            }
            "prod" => {
                let mut result = kwargs
                    .iter()
                    .find(|(key, _)| key == "start")
                    .map(|(_, value)| value.clone())
                    .unwrap_or(Value::Int(Int::from_i128(1).into()));
                let iterator = self.iter(args[0].clone())?;
                self.math_keep(root, base, iterator.clone());
                self.math_keep(root, base + 1, result.clone());
                while let Some(value) = self.next(iterator.clone())? {
                    let value = self.math_keep(root, base + 2, value);
                    result = self.binary("*", result, value)?;
                    self.math_keep(root, base + 1, result.clone());
                }
                return Ok(result);
            }
            "fsum" => {
                let mut accumulator = MathFsum::new();
                let iterator = self.iter(args[0].clone())?;
                self.math_keep(root, base, iterator.clone());
                while let Some(value) = self.next(iterator.clone())? {
                    let value = self.math_keep(root, base + 1, value);
                    accumulator.push(self.math_float(&value)?)?;
                }
                return Ok(Value::Float(accumulator.finish()?.into()));
            }
            "sumprod" => {
                let first = self.iter(args[0].clone())?;
                self.math_keep(root, base, first.clone());
                let second = self.iter(args[1].clone())?;
                self.math_keep(root, base + 1, second.clone());
                let mut integer = Int::exact_small(0);
                let mut triple = MathTriple::default();
                let mut floating = false;
                let mut generic = None;
                loop {
                    let a = self.next(first.clone())?;
                    if let Some(ref a) = a {
                        self.math_keep(root, base + 2, a.clone());
                    }
                    let b = self.next(second.clone())?;
                    if let Some(ref b) = b {
                        self.math_keep(root, base + 3, b.clone());
                    }
                    let (a, b) = match (a, b) {
                        (None, None) => break,
                        (Some(a), Some(b)) => (a, b),
                        _ => return Err(pyerr("ValueError", "Inputs are not the same length")),
                    };
                    let both_int = matches!(a, Value::Int(_) | Value::Bool(_))
                        && matches!(b, Value::Int(_) | Value::Bool(_));
                    if generic.is_none() && !floating && both_int {
                        let a = self.as_int(&a)?;
                        let b = self.as_int(&b)?;
                        integer = integer.exact_add(&a.exact_mul(&b));
                        continue;
                    }
                    let numeric = matches!(a, Value::Int(_) | Value::Bool(_) | Value::Float(_))
                        && matches!(b, Value::Int(_) | Value::Bool(_) | Value::Float(_));
                    if generic.is_none() && numeric {
                        if !floating {
                            let seed = self.math_float(&Value::Int(integer.clone().into()))?;
                            triple.add_product(seed, 1.0);
                            floating = true;
                        }
                        let x = self.math_float(&a)?;
                        let y = self.math_float(&b)?;
                        if triple.add_product(x, y) {
                            continue;
                        }
                        generic = Some(Value::Float((triple.value() + x * y).into()));
                        floating = false;
                        continue;
                    }
                    let current = generic.take().unwrap_or_else(|| {
                        if floating {
                            Value::Float(triple.value().into())
                        } else {
                            Value::Int(integer.clone().into())
                        }
                    });
                    self.math_keep(root, base + 4, current.clone());
                    let product = self.binary("*", a, b)?;
                    let product = self.math_keep(root, base + 5, product);
                    let result = self.binary("+", current, product)?;
                    self.math_keep(root, base + 4, result.clone());
                    generic = Some(result);
                }
                return Ok(generic.unwrap_or_else(|| {
                    if floating {
                        Value::Float(triple.value().into())
                    } else {
                        Value::Int(integer.normalized().into())
                    }
                }));
            }
            "hypot" | "dist" => {
                let mut coordinates = Vec::new();
                if name == "hypot" {
                    for value in &args {
                        coordinates.push(self.math_float(value)?);
                    }
                } else {
                    let first = self.iter(args[0].clone())?;
                    self.math_keep(root, base, first.clone());
                    let second = self.iter(args[1].clone())?;
                    self.math_keep(root, base + 1, second.clone());
                    loop {
                        let a = self.next(first.clone())?;
                        if let Some(ref a) = a {
                            self.math_keep(root, base + 2, a.clone());
                        }
                        let b = self.next(second.clone())?;
                        if let Some(ref b) = b {
                            self.math_keep(root, base + 3, b.clone());
                        }
                        match (a, b) {
                            (None, None) => break,
                            (Some(a), Some(b)) => {
                                let a = self.math_float(&a)?;
                                let b = self.math_float(&b)?;
                                coordinates.push(a - b);
                            }
                            _ => {
                                return Err(pyerr(
                                    "ValueError",
                                    "both points must have the same number of dimensions",
                                ))
                            }
                        }
                    }
                }
                return Ok(Value::Float(math_norm(&coordinates).into()));
            }
            "log" | "log2" | "log10" => {
                let mut result = self.math_log(&args[0], name)?;
                if args.len() == 2 {
                    let base = self.math_log(&args[1], "log")?;
                    if base == 0.0 {
                        return Err(pyerr("ZeroDivisionError", "float division by zero"));
                    }
                    result /= base;
                }
                return Ok(Value::Float(result.into()));
            }
            "isclose" => {
                let x = self.math_float(&args[0])?;
                let y = self.math_float(&args[1])?;
                let mut relative = 1e-9;
                let mut absolute = 0.0;
                for (key, value) in &kwargs {
                    let tolerance = self.math_float(value)?;
                    if key == "rel_tol" {
                        relative = tolerance;
                    } else {
                        absolute = tolerance;
                    }
                }
                if relative < 0.0 || absolute < 0.0 {
                    return Err(pyerr("ValueError", "tolerances must be non-negative"));
                }
                let difference = (x - y).abs();
                return Ok(Value::Bool(
                    x == y
                        || (!x.is_infinite()
                            && !y.is_infinite()
                            && (difference <= (relative * x).abs()
                                || difference <= (relative * y).abs()
                                || difference <= absolute)),
                ));
            }
            "ldexp" => {
                let x = self.math_float(&args[0])?;
                let exponent = self.as_int(&args[1])?;
                let exponent = exponent
                    .to_i128()
                    .map(|n| n.clamp(-10000, 10000) as i64)
                    .unwrap_or(if exponent.is_negative() {
                        -10000
                    } else {
                        10000
                    });
                let result = math_scale(x, exponent);
                return if result.is_infinite() && x.is_finite() {
                    Err(math_overflow())
                } else {
                    Ok(Value::Float(result.into()))
                };
            }
            "nextafter" => {
                let x = self.math_float(&args[0])?;
                let y = self.math_float(&args[1])?;
                let steps = kwargs
                    .iter()
                    .find(|(key, _)| key == "steps")
                    .map(|(_, value)| value.clone())
                    .unwrap_or(Value::None);
                let steps = if matches!(steps, Value::None) {
                    1
                } else {
                    let n = self.as_int(&steps)?;
                    if n.is_negative() {
                        return Err(pyerr("ValueError", "steps must be a non-negative integer"));
                    }
                    n.to_i128()
                        .map(|n| n.min(u64::MAX as i128) as u64)
                        .unwrap_or(u64::MAX)
                };
                return Ok(Value::Float(math_nextafter(x, y, steps).into()));
            }
            _ => {}
        }
        let x = self.math_float(&args[0])?;
        if name == "isfinite" {
            return Ok(Value::Bool(x.is_finite()));
        }
        if name == "isinf" {
            return Ok(Value::Bool(x.is_infinite()));
        }
        if name == "isnan" {
            return Ok(Value::Bool(x.is_nan()));
        }
        if name == "frexp" {
            let (mantissa, exponent) = math_frexp(x);
            return Ok(Value::Obj(self.alloc(Object::Tuple(vec![
                Value::Float(mantissa.into()),
                Value::Int(Int::from_i128(exponent as i128).into()),
            ]))));
        }
        if name == "modf" {
            let fraction = if x.is_infinite() {
                0.0f64.copysign(x)
            } else {
                x.fract().copysign(x)
            };
            return Ok(Value::Obj(self.alloc(Object::Tuple(vec![
                Value::Float(fraction.into()),
                Value::Float(x.trunc().into()),
            ]))));
        }
        if name == "ulp" {
            let a = x.abs();
            let result = if a.is_nan() || a.is_infinite() {
                a
            } else if a == f64::MAX {
                a - f64::from_bits(a.to_bits() - 1)
            } else {
                f64::from_bits(a.to_bits() + 1) - a
            };
            return Ok(Value::Float(result.into()));
        }
        if name == "gamma" || name == "lgamma" {
            return math_gamma(x, name == "lgamma").map(|value| Value::Float(value.into()));
        }
        if name == "erf" || name == "erfc" {
            return Ok(Value::Float(math_erf(x, name == "erfc").into()));
        }
        let y = if args.len() > 1 {
            self.math_float(&args[1])?
        } else {
            0.0
        };
        if name == "remainder" {
            return math_remainder(x, y).map(|value| Value::Float(value.into()));
        }
        if name == "fmod" {
            if x.is_nan() {
                return Ok(Value::Float(x.into()));
            }
            if y.is_nan() {
                return Ok(Value::Float(y.into()));
            }
            if x.is_infinite() || y == 0.0 {
                return Err(math_domain());
            }
            return Ok(Value::Float((x % y).into()));
        }
        if name == "fma" {
            let z = self.math_float(&args[2])?;
            let result = x.mul_add(y, z);
            if result.is_nan() && !x.is_nan() && !y.is_nan() && !z.is_nan() {
                return Err(math_domain());
            }
            if result.is_infinite() && x.is_finite() && y.is_finite() && z.is_finite() {
                return Err(math_overflow());
            }
            return Ok(Value::Float(result.into()));
        }
        if (name == "log1p" && x <= -1.0) || (name == "atanh" && x.abs() >= 1.0) {
            return Err(math_domain());
        }
        let result = match name {
            "sqrt" => x.sqrt(),
            "fabs" => x.abs(),
            "cbrt" => x.cbrt(),
            "sin" => x.sin(),
            "cos" => x.cos(),
            "tan" => x.tan(),
            "asin" => x.asin(),
            "acos" => x.acos(),
            "atan" => x.atan(),
            "atan2" => x.atan2(y),
            "sinh" => x.sinh(),
            "cosh" => x.cosh(),
            "tanh" => x.tanh(),
            "asinh" => x.asinh(),
            "acosh" => x.acosh(),
            "atanh" => x.atanh(),
            "exp" => x.exp(),
            "exp2" => x.exp2(),
            "expm1" => x.exp_m1(),
            "log1p" => {
                if x == 0.0 {
                    x
                } else {
                    x.ln_1p()
                }
            }
            "degrees" => x * (180.0 / std::f64::consts::PI),
            "radians" => x * (std::f64::consts::PI / 180.0),
            "copysign" => x.copysign(y),
            "pow" => x.powf(y),
            _ => return Err(pyerr("NotImplementedError", format!("math.{}", name))),
        };
        if result.is_nan() && !x.is_nan() && (args.len() < 2 || !y.is_nan()) {
            return Err(math_domain());
        }
        if name == "pow" && x == 0.0 && y < 0.0 && y.is_finite() {
            return Err(math_domain());
        }
        if result.is_infinite()
            && x.is_finite()
            && (args.len() < 2 || y.is_finite())
            && matches!(name, "exp" | "exp2" | "expm1" | "cosh" | "sinh" | "pow")
        {
            return Err(math_overflow());
        }
        Ok(Value::Float(result.into()))
    }
}
