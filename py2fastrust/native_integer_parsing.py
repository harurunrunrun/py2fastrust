"""Selected-width decimal parsing for already proved builtin conversions.

The Rust accumulator computes the mathematical integer modulo 2**INT_BITS.
Parsing never uses runtime values of the arbitrary-precision integer type.
"""
from functools import lru_cache
from importlib.resources import files
import re


def enable(generator):
    if generator.bits:
        generator.has_fixed_parsing = True


def parse_value(generator, value, node):
    """Choose one descriptive operand projection; the caller proved int identity."""
    if not generator.bits:
        return None
    enable(generator)
    if value.kind == "str" and value.char_code is not None:
        return generator.at(f"native_parse_integer_codepoint({value.char_code})", node)
    parser = "native_io_parse_text" if value.kind == "str" else "native_io_parse_bytes"
    return generator.at(f"{parser}(&({value.code}))", node)


@lru_cache(maxsize=2)
def render_helpers(string_mode="ascii"):
    if string_mode == "ascii":
        return _ascii_helpers()
    if string_mode != "unicode":
        raise ValueError(f"unknown string mode: {string_mode}")
    resources = files("py2fastrust").joinpath("runtime")
    integer = resources.joinpath("integer.rs").read_text(encoding="utf-8")
    decimal = re.search(r"fn decimal_digit\(.*?const ZEROES:\s*&\[u32\]\s*=\s*&\[(.*?)\];", integer, re.S)
    text = resources.joinpath("text.rs").read_text(encoding="utf-8")
    if 'const TEXT_UNICODE_VERSION: &str = "16.0.0";' not in text or decimal is None:
        raise RuntimeError("fixed integer parsing requires pinned Unicode 16.0 data")
    space = re.search(r"const TEXT_SPACE:\s*&\[\(u32,\s*u32\)\]\s*=\s*&\[(.*?)\n\];", text, re.S)
    if space is None:
        raise RuntimeError("missing pinned Unicode whitespace data")
    return ("// Unicode 16.0 decimal and whitespace data, shared with the integer/text runtimes.\n"
            "const NATIVE_FIXED_INT_ZEROES:&[u32]=&[" + decimal[1] + "];\n"
            "const NATIVE_FIXED_INT_SPACE:&[(u32,u32)]=&[" + space[1] + "\n];\n" + HELPERS)


HELPERS = r'''
#[inline]
fn native_fixed_int_space(byte:u8)->bool {matches!(byte,9..=13|32)}

#[inline]
fn native_fixed_parse_ascii(bytes:&[u8])->Option<NativeInt> {
    let mut first=0;let mut last=bytes.len();
    while first<last&&native_fixed_int_space(bytes[first]){first+=1;}
    while first<last&&native_fixed_int_space(bytes[last-1]){last-=1;}
    let bytes=&bytes[first..last];
    let negative=bytes.first()==Some(&b'-');
    let digits=if negative||bytes.first()==Some(&b'+'){&bytes[1..]}else{bytes};
    let mut value:NativeInt=0;let mut previous_digit=false;
    for &byte in digits {
        if byte.is_ascii_digit() {
            value=value.wrapping_mul(10).wrapping_add((byte-b'0') as NativeInt);
            previous_digit=true;
        }else if byte==b'_'&&previous_digit{previous_digit=false;}
        else{return None;}
    }
    if previous_digit{Some(if negative{value.wrapping_neg()}else{value})}else{None}
}

#[inline]
fn native_fixed_decimal_digit(code:u32)->Option<NativeInt> {
    if code<128{return if (48..=57).contains(&code){Some((code-48) as NativeInt)}else{None};}
    let index=NATIVE_FIXED_INT_ZEROES.partition_point(|&zero|zero<=code);
    if index==0{return None;}
    let digit=code-NATIVE_FIXED_INT_ZEROES[index-1];
    (digit<10).then_some(digit as NativeInt)
}

fn native_fixed_text_space(character:char)->bool {
    let code=character as u32;
    // str.isspace additionally includes C0 separators 1c..1f; int rejects them.
    if code<128{return native_fixed_int_space(code as u8);}
    let index=NATIVE_FIXED_INT_SPACE.partition_point(|&(_,last)|last<code);
    NATIVE_FIXED_INT_SPACE.get(index).is_some_and(|&(first,_)|first<=code)
}

fn native_fixed_parse_unicode(text:&str)->Option<NativeInt> {
    let text=text.trim_matches(native_fixed_text_space);
    let negative=text.starts_with('-');
    let digits=text.strip_prefix(['+','-']).unwrap_or(text);
    let mut value:NativeInt=0;let mut previous_digit=false;
    for character in digits.chars() {
        if let Some(digit)=native_fixed_decimal_digit(character as u32) {
            value=value.wrapping_mul(10).wrapping_add(digit);previous_digit=true;
        }else if character=='_'&&previous_digit{previous_digit=false;}
        else{return None;}
    }
    if previous_digit{Some(if negative{value.wrapping_neg()}else{value})}else{None}
}

#[cold]
fn native_fixed_int_invalid()->String {"ValueError: invalid literal for int()".to_owned()}

#[inline]
fn native_parse_integer(text:&str)->Result<NativeInt,String> {
    let value=if text.is_ascii(){native_fixed_parse_ascii(text.as_bytes())}else{native_fixed_parse_unicode(text)};
    value.ok_or_else(native_fixed_int_invalid)
}

#[inline]
fn native_parse_integer_codepoint(code:u32)->Result<NativeInt,String> {
    native_fixed_decimal_digit(code).ok_or_else(native_fixed_int_invalid)
}
'''


def _ascii_helpers():
    from .rust_pruning import _lex,_parse
    tokens,comments,pairs=_lex(HELPERS)
    replacements={
        "native_fixed_decimal_digit": r'''#[inline]
fn native_fixed_decimal_digit(code:u32)->Option<NativeInt> {
    if (48..=57).contains(&code){Some((code-48)as NativeInt)}else{None}
}''',
        "native_parse_integer": r'''#[inline]
fn native_parse_integer(text:&str)->Result<NativeInt,String> {
    native_fixed_parse_ascii(text.as_bytes()).ok_or_else(native_fixed_int_invalid)
}''',
    }
    unicode_only={"native_fixed_text_space","native_fixed_parse_unicode"}
    return "\n".join(replacements.get(item.name,HELPERS[item.start:item.end])
                     for item in _parse(HELPERS,tokens,comments,pairs)if item.name not in unicode_only)
