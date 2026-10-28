"""Proved, ordinary Rust strings and binary64 scalars.

This layer extends the integer/container proof without introducing a boxed
object representation. Unknown types, observable identity, and unproved callbacks
require further direct lowering. Expressions keep
their Python evaluation order even when Rust needs a temporary or a clone.
"""

from .native_constraint_lowering import result_shapes

import ast
from .native_types import (TupleType,ListType,MaybeType,TypedListInfo,rust_type,kind_tag,
                           is_maybe,unmaybe,maybe_type,immutable,list_type,default_value)
from .literal_semantics import float_literal

from .native import _Binding, _Expression, _Generator, _Unsupported, _string, _text_expression


TEXT_INPUT_HELPERS = r'''
struct NativeInput { reader: StandardInput, line: String }
impl NativeInput {
    fn new() -> Self { Self { reader: StandardInput::new(), line: String::new() } }
    fn line(&mut self, output: &mut String) -> Result<&str, String> {
        if !output.is_empty() { native_flush_output(output)?; }
        self.reader.read_text_into(&mut self.line, None, true).map_err(StandardInputError::native_message)?;
        if self.line.is_empty() { return Err("EOFError: EOF when reading a line".into()); }
        if self.line.ends_with('\n') { self.line.pop(); }
        Ok(&self.line)
    }
}
'''


SCALAR_HELPERS = r'''
fn native_float_divmod(a: f64, b: f64) -> Result<(f64, f64), String> {
    // Quotient/remainder adaptation: CPython 3.14 Objects/floatobject.c,
    // _float_div_mod, Copyright Python Software Foundation, PSF License Version 2.
    // Modified to use Rust f64 and return Python errors through Result.
    // The complete PSF license accompanies this generated source.
    if b == 0.0 { return Err("ZeroDivisionError: division by zero".into()); }
    let mut r = a % b;
    let mut q = (a - r) / b;
    if r != 0.0 {
        if (b < 0.0) != (r < 0.0) { r += b; q -= 1.0; }
    } else { r = 0.0_f64.copysign(b); }
    q = if q != 0.0 {
        let floor = q.floor();
        if q - floor > 0.5 { floor + 1.0 } else { floor }
    } else { 0.0_f64.copysign(a / b) };
    Ok((q, r))
}
fn native_float_div(a: f64, b: f64) -> Result<f64, String> {
    if b == 0.0 { Err("ZeroDivisionError: division by zero".into()) } else { Ok(a / b) }
}
// Exact bounded-integer quotient, rounded once to nearest binary64 (ties even).
// Scaling uses a remainder below 2^127, so each doubling fits u128.
fn native_integer_ratio(a: NativeInt, b: NativeInt) -> Result<f64, String> {
    if b == 0 { return Err("ZeroDivisionError: division by zero".into()); }
    let sign = if (a < 0) != (b < 0) { 1_u64 << 63 } else { 0 };
    let (a, b) = (a.unsigned_abs() as u128, b.unsigned_abs() as u128);
    if a == 0 { return Ok(f64::from_bits(sign)); }
    let mut exponent = (127 - a.leading_zeros()) as i32 - (127 - b.leading_zeros()) as i32;
    let below = if exponent >= 0 { a >> exponent < b }
                else { a << (-exponent) < b };
    if below { exponent -= 1; }
    let scale = 52 - exponent;
    let (mut q, r, d) = if scale >= 0 {
        let (mut q, mut r) = (a / b, a % b);
        for _ in 0..scale {
            r *= 2;
            q = (q << 1) | (r >= b) as u128;
            if r >= b { r -= b; }
        }
        (q, r, b)
    } else {
        let d = b << (-scale);
        (a / d, a % d, d)
    };
    if r > d - r || r == d - r && q & 1 != 0 { q += 1; }
    if q == 1_u128 << 53 { q >>= 1; exponent += 1; }
    Ok(f64::from_bits(sign | ((exponent + 1023) as u64) << 52 | (q as u64 & ((1_u64 << 52) - 1))))
}
fn native_float_integer(value: f64) -> Result<NativeInt, String> {
    if value.is_nan() { return Err("ValueError: cannot convert float NaN to integer".into()); }
    if value.is_infinite() { return Err("OverflowError: cannot convert float infinity to integer".into()); }
    let bits = value.to_bits();
    let exponent = ((bits >> 52) & 2047) as i32 - 1023;
    if exponent < 0 { return Ok(0); }
    let mantissa = (bits & ((1_u64 << 52) - 1)) | 1_u64 << 52;
    let magnitude = if exponent < 52 { (mantissa >> (52 - exponent)) as NativeInt }
                    else if exponent - 52 >= INT_BITS as i32 { 0 }
                    else { (mantissa as NativeInt).wrapping_shl((exponent - 52) as u32) };
    Ok(if bits >> 63 != 0 { magnitude.wrapping_neg() } else { magnitude })
}
// Never round a large integer to f64 merely to compare it with a float.
fn native_integer_float_compare(integer: NativeInt, float: f64) -> Option<std::cmp::Ordering> {
    use std::cmp::Ordering::{Less, Equal, Greater};
    if float.is_nan() { return None; }
    if float.is_infinite() { return Some(if float.is_sign_negative() { Greater } else { Less }); }
    if integer == 0 && float == 0.0 { return Some(Equal); }
    if (integer < 0) != (float < 0.0) { return Some(if integer < 0 { Less } else { Greater }); }
    let magnitude = integer.unsigned_abs() as u128;
    let bits = float.to_bits();
    let exponent = ((bits >> 52) & 2047) as i32 - 1023;
    let mantissa = ((bits & ((1_u64 << 52) - 1)) | (if exponent == -1023 { 0 } else { 1_u64 << 52 })) as u128;
    let order = if exponent < 0 { if magnitude == 0 { Less } else { Greater } }
                else if exponent >= 128 { Less }
                else if exponent >= 52 { magnitude.cmp(&(mantissa << (exponent - 52))) }
                else {
                    let shift = 52 - exponent;
                    let whole = mantissa >> shift;
                    let order = magnitude.cmp(&whole);
                    if order == Equal && mantissa != whole << shift { Less } else { order }
                };
    Some(if integer < 0 { order.reverse() } else { order })
}
fn native_float_text(value: f64) -> String {
    if value.is_nan() { return "nan".into(); }
    if value.is_infinite() { return if value.is_sign_negative() { "-inf" } else { "inf" }.into(); }
    if value == 0.0 { return if value.is_sign_negative() { "-0.0" } else { "0.0" }.into(); }
    let text = value.abs().to_string();
    let point = text.find('.').unwrap_or(text.len());
    let mut digits: String = text.chars().filter(|&c| c != '.').collect();
    let first = digits.bytes().position(|c| c != b'0').unwrap();
    let mut exponent = point as i32 - first as i32 - 1;
    digits.drain(..first);
    while digits.len() > 1 && digits.ends_with('0') { digits.pop(); }
    // Rust's shortest conversion can choose the upper decimal at an exact
    // midpoint (for example 1288281069789064.25 -> ...64.3). Python chooses
    // an even last decimal digit. Compare odd integer significands exactly;
    // casting either candidate back to f64 would lose this distinction.
    let decimal = digits.parse::<u128>().unwrap();
    if decimal & 1 != 0 {
        let scale = exponent - digits.len() as i32 + 1;
        let bits = value.abs().to_bits();
        let stored_exponent = ((bits >> 52) & 2047) as i32;
        let mut mantissa = (bits & ((1_u64 << 52) - 1)) | if stored_exponent == 0 { 0 } else { 1_u64 << 52 };
        let mut power = if stored_exponent == 0 { -1074 } else { stored_exponent - 1075 };
        let zeroes = mantissa.trailing_zeros();
        mantissa >>= zeroes;
        power += zeroes as i32;
        if (-24..=24).contains(&scale) && power == scale - 1 {
            let five = 5_u128.pow(scale.unsigned_abs());
            let equal = |candidate| if scale >= 0 { candidate * five == mantissa as u128 }
                                     else { mantissa as u128 * five == candidate };
            let rounded = if equal(2 * decimal - 1) { Some(decimal - 1) }
                          else if equal(2 * decimal + 1) { Some(decimal + 1) } else { None };
            if let Some(rounded) = rounded {
                let old_length = digits.len();
                digits = rounded.to_string();
                exponent += digits.len() as i32 - old_length as i32;
                while digits.len() > 1 && digits.ends_with('0') { digits.pop(); }
            }
        }
    }
    let mut out = if value.is_sign_negative() { "-".to_owned() } else { String::new() };
    if exponent < -4 || exponent >= 16 {
        out.push(digits.as_bytes()[0] as char);
        if digits.len() > 1 { out.push('.'); out.push_str(&digits[1..]); }
        out.push('e');
        out.push(if exponent < 0 { '-' } else { '+' });
        if exponent.unsigned_abs() < 10 { out.push('0'); }
        out.push_str(&exponent.unsigned_abs().to_string());
    } else if exponent < 0 {
        out.push_str("0.");
        out.extend(std::iter::repeat('0').take((-exponent - 1) as usize));
        out.push_str(&digits);
    } else {
        let count = exponent as usize + 1;
        if digits.len() > count { out.push_str(&digits[..count]); out.push('.'); out.push_str(&digits[count..]); }
        else { out.push_str(&digits); out.extend(std::iter::repeat('0').take(count - digits.len())); out.push_str(".0"); }
    }
    out
}
fn native_scalar_space(c: char) -> bool { c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c) }
fn native_scalar_digit(c: char) -> Option<u32> {
    if c.is_ascii_digit() { return Some(c as u32 - '0' as u32); }
    // Unicode 16.0 Nd zeroes, shared with the project's integer runtime.
    const ZEROES: &[u32] = &[
        0x660,0x6f0,0x7c0,0x966,0x9e6,0xa66,0xae6,0xb66,0xbe6,0xc66,0xce6,0xd66,
        0xde6,0xe50,0xed0,0xf20,0x1040,0x1090,0x17e0,0x1810,0x1946,0x19d0,0x1a80,
        0x1a90,0x1b50,0x1bb0,0x1c40,0x1c50,0xa620,0xa8d0,0xa900,0xa9d0,0xa9f0,0xaa50,
        0xabf0,0xff10,0x104a0,0x10d30,0x10d40,0x11066,0x110f0,0x11136,0x111d0,0x112f0,
        0x11450,0x114d0,0x11650,0x116c0,0x116d0,0x116da,0x11730,0x118e0,0x11950,
        0x11bf0,0x11c50,0x11d50,0x11da0,0x11f50,0x16130,0x16a60,0x16ac0,0x16b50,
        0x16d70,0x1ccf0,0x1d7ce,0x1d7d8,0x1d7e2,0x1d7ec,0x1d7f6,0x1e140,0x1e2f0,
        0x1e4f0,0x1e5f1,0x1e950,0x1fbf0,
    ];
    ZEROES.iter().find_map(|&zero| (c as u32).checked_sub(zero).filter(|&n| n < 10))
}
fn native_scalar_float(text: &str) -> Result<f64, String> {
    let text = text.trim_matches(char::is_whitespace);
    if text.is_empty() { return Err("ValueError: could not convert string to float".into()); }
    let chars: Vec<char> = text.chars().collect();
    let mut normalized = String::new();
    for (i, &c) in chars.iter().enumerate() {
        if c == '_' {
            if i == 0 || i + 1 == chars.len() || native_scalar_digit(chars[i-1]).is_none() || native_scalar_digit(chars[i+1]).is_none() {
                return Err("ValueError: could not convert string to float".into());
            }
        } else if let Some(digit) = native_scalar_digit(c) { normalized.push((b'0' + digit as u8) as char); }
        else { normalized.push(c); }
    }
    let unsigned = normalized.strip_prefix(['+', '-']).unwrap_or(&normalized);
    if unsigned.eq_ignore_ascii_case("nan") { return Ok(if normalized.starts_with('-') { -f64::NAN } else { f64::NAN }); }
    if unsigned.eq_ignore_ascii_case("inf") || unsigned.eq_ignore_ascii_case("infinity") {
        return Ok(if normalized.starts_with('-') { f64::NEG_INFINITY } else { f64::INFINITY });
    }
    if unsigned.is_empty() || unsigned.chars().any(|c| !c.is_ascii_digit() && !matches!(c, '.'|'e'|'E'|'+'|'-')) {
        return Err("ValueError: could not convert string to float".into());
    }
    normalized.parse::<f64>().map_err(|_| "ValueError: could not convert string to float".into())
}
fn native_scalar_integer(text: &str) -> Result<NativeInt, String> {
    native_parse_integer(text).map_err(|_|"ValueError: invalid literal for int() with base 10".to_owned())
}

fn native_string_add(mut left: String, right: &str) -> Result<String, String> {
    left.try_reserve(right.len()).map_err(|_| "MemoryError: string is too large".to_owned())?;
    left.push_str(right);
    Ok(left)
}
fn native_string_extend(left: &mut String, right: &str) -> Result<(), String> {
    left.try_reserve(right.len()).map_err(|_| "MemoryError: string is too large".to_owned())?;
    left.push_str(right);
    Ok(())
}
fn native_string_repeat(value: &str, count: NativeInt) -> Result<String, String> {
    let count = isize::try_from(count).map_err(|_| "OverflowError: cannot fit 'int' into an index-sized integer".to_owned())?;
    if count <= 0 || value.is_empty() { return Ok(String::new()); }
    let length = value.len().checked_mul(count as usize).filter(|&n| n <= isize::MAX as usize)
        .ok_or_else(|| "OverflowError: repeated string is too long".to_owned())?;
    let mut output = String::new();
    output.try_reserve_exact(length).map_err(|_| "MemoryError: string is too large".to_owned())?;
    for _ in 0..count { output.push_str(value); }
    Ok(output)
}
fn native_string_item(value: &str, index: NativeInt) -> Result<String, String> {
    let length = if value.is_ascii() { value.len() } else { value.chars().count() };
    let index = if index < 0 {
        let magnitude = index.unsigned_abs() as u128;
        if magnitude > length as u128 { return Err("IndexError: string index out of range".into()); }
        length - magnitude as usize
    } else { usize::try_from(index).unwrap_or(usize::MAX) };
    if index >= length { return Err("IndexError: string index out of range".into()); }
    if value.is_ascii() { Ok((value.as_bytes()[index] as char).to_string()) }
    else { Ok(value.chars().nth(index).unwrap().to_string()) }
}
'''


class ScalarGenerator(_Generator):
    BUILTINS = _Generator.BUILTINS | {"float", "str", "bool"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_extended_scalars = False

    def slot(self, kind):
        if kind not in {"float", "str"}:
            return super().slot(kind)
        self.has_extended_scalars = True
        slot = f"native_var_{len(self.bindings)}"
        self.bindings[slot] = kind
        return slot

    @staticmethod
    def coerce(value, kind):
        if value.kind == kind == "str":
            return f"({value.code}).clone()"
        return _Generator.coerce(value, kind)

    def scalar_kind(self, values):
        kinds = {value.kind for value in values}
        if len(kinds) == 1 and next(iter(kinds)) in {"float", "str"}:
            return next(iter(kinds))
        return super().scalar_kind(values)

    @staticmethod
    def truth(value):
        from .native_characters import truth as character_truth
        character=character_truth(value)
        if character is not None:return character
        from .native_unions import truth
        finite=truth(value,ScalarGenerator.truth)
        if finite is not None:return finite
        if value.kind == "str":
            return f"!({value.code}).is_empty()"
        if value.kind == "float":
            return f"({value.code}) != 0.0"
        return _Generator.truth(value)

    @staticmethod
    def floating(value):
        if value.kind == "float":
            return value.code
        return f"({ScalarGenerator.number(value)}) as f64"

    def read_expression(self, node, environment):
        """Read a scalar without making an owned copy of an immutable string.

        Only immediate consumers use these references: they never enter a
        Python binding or cross a generated function's by-value signature.
        The native proof excludes namespace writes and callbacks that could
        rebind these caller locals during a later operand's evaluation.
        A borrowed fresh String is bound directly in a let initializer so
        Rust extends that temporary's lifetime through the consuming block.
        """
        from .native_characters import read_local
        character=read_local(self,node,environment,borrowed=True)
        if character is not None:return character
        if isinstance(node, ast.Name):
            binding = environment.get(node.id)
            if isinstance(binding, _Binding) and binding.kind == "str":
                from .native_regions import owner_view_for_slot
                return _Expression(f"&{binding.slot}","str",owned=False,stable_borrow=True,
                                   text_view=owner_view_for_slot(self,binding.slot))
        if isinstance(node, ast.Constant) and type(node.value) is str:
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is None:raise _Unsupported
            self.has_extended_scalars = True
            from .native_regions import literal_char
            # The UTF-8 view is static. Borrowing the temporary NativeText
            # wrapper inside an indexing block would shorten its lifetime.
            return _Expression("&("+literal.rust_atom(self.literal,_string)+")",literal.kind,owned=False,stable_borrow=True,
                               char_code=literal_char(literal.value),text_view=_string(literal.value))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "str" and len(node.args) == 1 and not node.keywords):
            value = self.read_expression(node.args[0], environment)
            if value.kind == "str":
                return value
        if (self.string_mode == "ascii" and isinstance(node, ast.Subscript)
                and not isinstance(node.slice, ast.Slice)):
            from .native_regions import owner_view,char_projection
            view=owner_view(self,node)
            owner = _Expression(view,"str",owned=False,stable_borrow=True) if view else self.read_expression(node.value, environment)
            if owner.kind == "str" and owner.stable_borrow:
                index = self.expression(node.slice, environment)
                first, second = self.temporary(), self.temporary()
                self.has_extended_scalars = True
                call = self.at(f"native_string_item_ref({first},{second})", node)
                prefix=f"{{ {self.read_binding(first,owner)} let {second}={self.number(index)}; "
                code=prefix+call+" }"
                projected=prefix+self.at(f"native_ascii_codepoint({first},({second}) as i128)",node)+" }"
                return _Expression(code,"str",owned=False,stable_borrow=True,char_code=char_projection(self,node,code,projected))
        value = self.expression(node, environment)
        if value.kind == "str":
            return _Expression(f"&({value.code})", "str", owned=False,char_code=value.char_code)
        return value

    @staticmethod
    def read_binding(name, value):
        kind = ": &str" if value.kind == "str" else ""
        code=value.text_view if value.kind=="str"and value.text_view is not None else value.code
        return f"let {name}{kind} = {code};"

    @result_shapes
    def expression(self, node, environment):
        from .native_characters import read_local
        character=read_local(self,node,environment)
        if character is not None:return character
        from .native_text_predicates import try_expression as predicate_expression
        predicate=predicate_expression(self,node,environment)
        if predicate is not None:return predicate
        from .native_constraint_lowering import allocation_expression
        allocated=allocation_expression(self,node,environment)
        if allocated is not None:return allocated
        from .native_unions import leaf_expression
        leaf=leaf_expression(self,node,environment)
        if leaf is not None:return leaf
        from .native_stdio import try_expression
        stdio=try_expression(self,node,environment)
        if stdio is not None:
            return stdio
        from .native_key_containers import try_expression as key_expression
        keyed=key_expression(self,node,environment)
        if keyed is not None:return keyed
        from .native_typed_lists import try_expression
        typed=try_expression(self,node,environment)
        if typed is not None:return typed
        from .native_next import try_expression
        following=try_expression(self,node,environment)
        if following is not None:return following
        from .native_tuples import try_expression
        structural=try_expression(self,node,environment)
        if structural is not None:return structural
        from .native_text_methods import try_text_method
        text = try_text_method(self, node, environment)
        if text is not None:
            return text
        if isinstance(node, ast.Constant) and type(node.value) in {str, float}:
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is None:raise _Unsupported
            self.has_extended_scalars = True
            from .native_regions import literal_char
            return _Expression(literal.rust_atom(self.literal,_string),literal.kind,char_code=literal_char(literal.value))
        if isinstance(node, ast.Name):
            binding = environment.get(node.id)
            if isinstance(binding, _Binding) and binding.kind == "str":
                return _Expression(f"{binding.slot}.clone()", "str")
        if isinstance(node, ast.UnaryOp) and not isinstance(node.op, ast.Not):
            value = self.expression(node.operand, environment)
            if value.kind == "float":
                if isinstance(node.op, (ast.UAdd, ast.USub)):
                    return _Expression(value.code if isinstance(node.op, ast.UAdd) else f"(-({value.code}))", "float")
                raise _Unsupported
        if isinstance(node, ast.Compare):
            values = [self.read_expression(n, environment) for n in [node.left, *node.comparators]]
            from .native_unions import compare
            finite=compare(self,node,values)
            if finite is not None:return finite
            if any(value.kind in {"str", "float"} for value in values):
                return self.compare(node, values)
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            value=(self.read_expression(node.value,environment)if self.string_mode=="unicode"else self.expression(node.value,environment))
            if value.kind == "str":
                index = self.expression(node.slice, environment)
                first, second = self.temporary(), self.temporary()
                call = self.at(f"native_string_item({first}, {second})", node)
                owner=value.code if not value.owned else f"&({value.code})"
                prefix=f"{{ let {first}:&NativeText={owner}; let {second}={self.number(index)}; "
                code=prefix+call+" }"
                from .native_regions import char_projection
                helper="native_text_codepoint" if self.string_mode=="unicode" else "native_ascii_codepoint"
                direct=prefix+self.at(f"{helper}({first},({second}) as i128)",node)+" }"
                return _Expression(code,"str",char_code=char_projection(self,node,code,direct))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if (name == "int" and len(node.args) == 1 and isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == "input"
                    and not node.args[0].args and not node.args[0].keywords):
                # Keep the existing decimal contest-input fast path. Merely
                # extending scalar support must not enlarge integer programs.
                return super().expression(node, environment)
            if name == "input" and not node.args:
                self.has_input = self.has_extended_scalars = True
                return _text_expression(self.at("native_input.line(&mut native_output)",node))
            if name in {"str", "float", "bool"} and not node.args:
                self.has_extended_scalars = True
                return _Expression({"str": "NativeText::new()", "float": "0.0_f64", "bool": "false"}[name], name)
            if name in {"str", "float", "bool", "int", "len", "abs"} and len(node.args) == 1:
                try:
                    value = (self.read_expression(node.args[0], environment)
                             if name in {"len", "bool", "float", "int"}
                             else self.expression(node.args[0], environment))
                except _Unsupported:
                    # Some existing consumers prove an immediate iterable
                    # without materializing it as an expression, such as
                    # len(d.items()). Keep those consumer-specific proofs.
                    return super().expression(node, environment)
                if name == "bool":
                    return _Expression(self.truth(value), "bool")
                if name == "str" and value.kind in {"int", "bool", "int_bool", "float", "str"}:
                    self.has_extended_scalars = True
                    if value.kind == "str":
                        return value
                    code = (f"native_float_text({value.code})" if value.kind == "float" else
                            f'(if {value.code} {{ "True" }} else {{ "False" }}).to_owned()' if value.kind == "bool" else
                            f"({value.code}).to_string()")
                    return _text_expression(code)
                if name == "float" and value.kind in {"int", "bool", "int_bool", "float", "str"}:
                    self.has_extended_scalars = True
                    code = self.at(f"native_scalar_float(&({value.code}))", node) if value.kind == "str" else self.floating(value)
                    return _Expression(code, "float")
                if name == "int" and value.kind in {"float", "str"}:
                    self.has_extended_scalars = True
                    code = (f"native_float_integer({value.code})" if value.kind == "float" else f"native_scalar_integer(&({value.code}))")
                    return _Expression(self.at(code, node), "int")
                if name == "len" and value.kind == "str":
                    from .native_characters import length as character_length
                    projected=character_length(self,value)
                    if projected is not None:return projected
                    from .native_cached_text import text_length
                    return _Expression(f"({text_length(value,self.string_mode)} as NativeInt)","int")
                if name == "abs" and value.kind == "float":
                    return _Expression(f"({value.code}).abs()", "float")
        return super().expression(node, environment)

    def binary(self, operator, left, right, node):
        if left.kind == right.kind == "str" and isinstance(operator, ast.Add):
            self.has_extended_scalars = True
            first, second = self.temporary(), self.temporary()
            call = self.at(f"native_string_add({first}, &{second})", node)
            return _Expression(f"{{ let {first} = {left.code}; let {second} = {right.code}; {call} }}", "str")
        if "str" in (left.kind, right.kind) and isinstance(operator, ast.Mult):
            text, count = (left, right) if left.kind == "str" else (right, left)
            self.number(count)
            first, second = self.temporary(), self.temporary()
            a, b = (first, second) if left.kind == "str" else (second, first)
            call = self.at(f"native_string_repeat(&{a}, {b})", node)
            left_code = left.code if left.kind == "str" else self.number(left)
            right_code = right.code if right.kind == "str" else self.number(right)
            return _text_expression(f"{{ let {first} = {left_code}; let {second} = {right_code}; {call} }}")
        numeric = {"int", "bool", "int_bool", "float"}
        if left.kind in numeric and right.kind in numeric and ("float" in (left.kind, right.kind) or isinstance(operator, ast.Div)):
            self.has_extended_scalars = True
            first, second = self.temporary(), self.temporary()
            if isinstance(operator, ast.Div) and "float" not in (left.kind, right.kind):
                call = self.at(f"native_integer_ratio({first}, {second})", node)
                return _Expression(f"{{ let {first} = {self.number(left)}; let {second} = {self.number(right)}; {call} }}", "float")
            if isinstance(operator, (ast.Add, ast.Sub, ast.Mult)):
                symbol = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(operator)]
                calculation = f"{first} {symbol} {second}"
            elif isinstance(operator, ast.Div):
                calculation = self.at(f"native_float_div({first}, {second})", node)
            elif isinstance(operator, (ast.FloorDiv, ast.Mod)):
                calculation = self.at(f"native_float_divmod({first}, {second})", node) + (".0" if isinstance(operator, ast.FloorDiv) else ".1")
            else:
                raise _Unsupported
            return _Expression(f"{{ let {first} = {self.floating(left)}; let {second} = {self.floating(right)}; {calculation} }}", "float")
        return super().binary(operator, left, right, node)

    def compare(self, node, values):
        from .native_regions import compare_characters
        projected=compare_characters(self,node,values)
        if projected is not None:return projected
        symbols = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
        names = [self.temporary() for _ in values]
        tail = "true"
        for i in reversed(range(len(node.ops))):
            a, b, op = values[i], values[i+1], node.ops[i]
            x, y = names[i], names[i+1]
            if isinstance(op, (ast.In, ast.NotIn)) and a.kind == b.kind == "str":
                test = f"{y}.contains({x})"
                if isinstance(op, ast.NotIn): test = f"!{test}"
            elif isinstance(op,(ast.Lt,ast.LtE,ast.Gt,ast.GtE)):
                from .native_comparisons import ordering
                test=ordering(self,_Expression(x,a.kind,owned=False),_Expression(y,b.kind,owned=False),op,node)
            elif type(op) not in symbols:
                raise _Unsupported
            elif a.kind == b.kind == "str":
                test = f"{x} {symbols[type(op)]} {y}"
            elif "str" in (a.kind, b.kind):
                if not isinstance(op, (ast.Eq, ast.NotEq)) or ({a.kind, b.kind} - {"str", "float", "int", "bool", "int_bool"}):
                    raise _Unsupported
                test = "true" if isinstance(op, ast.NotEq) else "false"
            elif a.kind == "float" and b.kind == "float":
                test = f"{x} {symbols[type(op)]} {y}"
            elif "float" in (a.kind, b.kind):
                integer, floating = (self.number(_Expression(y, b.kind)), x) if a.kind == "float" else (self.number(_Expression(x, a.kind)), y)
                order = f"native_integer_float_compare({integer}, {floating})"
                if a.kind == "float": order += ".map(std::cmp::Ordering::reverse)"
                variant = {ast.Eq: "Some(std::cmp::Ordering::Equal)", ast.NotEq: "Some(std::cmp::Ordering::Equal)",
                           ast.Lt: "Some(std::cmp::Ordering::Less)", ast.Gt: "Some(std::cmp::Ordering::Greater)",
                           ast.LtE: "Some(std::cmp::Ordering::Less | std::cmp::Ordering::Equal)",
                           ast.GtE: "Some(std::cmp::Ordering::Greater | std::cmp::Ordering::Equal)"}[type(op)]
                test = f"{'!' if isinstance(op, ast.NotEq) else ''}matches!({order}, {variant})"
            else:
                test = f"{self.number(_Expression(x, a.kind))} {symbols[type(op)]} {self.number(_Expression(y, b.kind))}"
            tail = f"{{ {self.read_binding(y, b)} ({test}) && ({tail}) }}"
        return _Expression(f"{{ {self.read_binding(names[0], values[0])} {tail} }}", "bool")

    def statement(self, node, environment):
        from .native_module_calls import try_statement as module_statement
        module=module_statement(self,node,environment)
        if module is not None:return module
        from .native_stdio import try_statement
        stdio=try_statement(self,node,environment)
        if stdio is not None:
            return stdio
        from .native_key_containers import try_statement as key_statement
        keyed=key_statement(self,node,environment)
        if keyed is not None:return keyed
        from .native_typed_lists import try_statement
        typed=try_statement(self,node,environment)
        if typed is not None:return typed
        from .native_tuples import try_statement
        structural=try_statement(self,node,environment)
        if structural is not None:return structural
        alias = self.function_alias_assignment(node, environment)
        if alias is not None:
            return alias
        if isinstance(node, ast.Assign) and all(isinstance(target, ast.Name) for target in node.targets):
            value = self.expression(node.value, environment)
            if value.kind == "str":
                temp = self.temporary()
                lines = [f"let {temp} = {value.code};"]
                for index, target in enumerate(node.targets):
                    if target.id in self.iterating_lists: raise _Unsupported
                    code = f"{temp}.clone()" if index + 1 < len(node.targets) else temp
                    lines.append(f"{self.bind(target.id, value, environment)} = {code};")
                return "\n".join(lines), environment
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
            binding = environment.get(node.target.id)
            if isinstance(binding, _Binding) and binding.kind == "str":
                right = self.expression(node.value, environment)
                if right.kind != "str": raise _Unsupported
                temp = self.temporary()
                call = self.at(f"native_string_extend(&mut {binding.slot}, &{temp})", node)
                return f"let {temp} = {right.code};\n{call};", environment
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "print":
            call = node.value
            # Preserve the established starred-container path unchanged.
            if not any(isinstance(arg, ast.Starred) for arg in call.args):
                values = [self.read_expression(arg, environment) for arg in call.args]
                if any(value.kind in {"str", "float"} for value in values):
                    if any(value.kind not in {"int", "bool", "int_bool", "float", "str"} for value in values): raise _Unsupported
                    sep, end, flush = " ", "\n", False
                    seen = set()
                    for key in call.keywords:
                        if key.arg in seen or key.arg not in {"sep", "end", "flush"} or not isinstance(key.value, ast.Constant): raise _Unsupported
                        seen.add(key.arg)
                        value = key.value.value
                        if key.arg == "flush":
                            if type(value) is not bool: raise _Unsupported
                            flush = value
                        else:
                            if type(value) is not str: raise _Unsupported
                            if any(0xD800 <= ord(c) <= 0xDFFF for c in value): raise _Unsupported
                            if key.arg == "sep": sep = value
                            else: end = value
                    names = [self.temporary() for _ in values]
                    lines = [self.read_binding(name, value) for name, value in zip(names, values)]
                    for index, (name, value) in enumerate(zip(names, values)):
                        if index: lines.append(f"native_output.push_str({_string(sep)});")
                        text = (f"native_float_text({name})" if value.kind == "float" else
                                f'if {name} {{ "True" }} else {{ "False" }}' if value.kind == "bool" else name)
                        lines.append(f'write!(&mut native_output, "{{}}", {text}).unwrap();')
                    lines.append(f"native_output.push_str({_string(end)});")
                    if flush: lines.append(self.at("native_flush_output(&mut native_output)", node) + ";")
                    return "\n".join(lines), environment
        return super().statement(node, environment)
