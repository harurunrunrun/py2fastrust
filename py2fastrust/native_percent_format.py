"""printf-style ``literal % values`` lowered onto canonical format specifications.

Only a literal format string is admitted; its directives are parsed at compile
time. Each directive maps to the format() mini-language with the same printf
meaning (explicit right alignment for text, sign-aware zero padding, ``#``
alternate forms, text precision as truncation). Argument count errors and
operand type errors keep CPython's TypeError messages.
"""
import ast
import re

DIRECTIVE = re.compile(r'%(?P<flags>[-+ 0#]*)(?P<width>\d*)(?:\.(?P<precision>\d*))?(?P<type>.)', re.S)
INTEGER = {'d', 'i', 'u', 'x', 'X', 'o'}
REAL = {'e', 'E', 'f', 'F', 'g', 'G'}
TEXT = {'s', 'r', 'a'}
CHARACTER = 'c'


def parse(text):
    """Literal runs and directives, or a reason this format is not admitted."""
    pieces, position = [], 0
    while True:
        start = text.find('%', position)
        if start < 0:
            pieces.append(text[position:])
            return pieces, None
        pieces.append(text[position:start])
        match = DIRECTIVE.match(text, start)
        if match is None or match.group('type') in {'*', '('} or '*' in text[start:match.end()]:
            return None, 'variable widths, mapping keys and incomplete directives'
        kind = match.group('type')
        if kind == '%' and match.end() - start == 2:
            pieces.append('%')
        elif kind in INTEGER | REAL | TEXT | {CHARACTER}:
            pieces.append(match.groupdict())
        else:
            return None, f'the %{kind} conversion'
        position = match.end()


def specification(directive):
    flags, width, precision, kind = directive['flags'], directive['width'], directive['precision'], directive['type']
    text = kind in TEXT or kind == CHARACTER
    spec = ''
    if '-' in flags:
        spec += '<'
    elif text:
        spec += '>'
    if not text:
        spec += '+' if '+' in flags else ' ' if ' ' in flags else ''
        spec += '#' if '#' in flags and kind in {'x', 'X', 'o'} | REAL else ''
        if '0' in flags and '-' not in flags:
            spec += '0'
    spec += width
    if precision is not None and kind != CHARACTER:
        spec += '.' + (precision or '0')
    if not text:
        spec += {'i': 'd', 'u': 'd'}.get(kind, kind)
    return spec


def _format_string(node):
    return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)


def requires_frames(unit):
    return any(_format_string(node) for node in ast.walk(unit.tree))


def analyze(model, plan, node, operator, left, right, identity):
    from .native_classes import ClassUnsupported, shape
    if not _format_string(node):
        return None
    pieces, reason = parse(node.left.value)
    if pieces is None:
        raise ClassUnsupported(node, 'this printf-style format uses ' + reason + '; only literal directives with fixed flags, width and precision are implemented',
                               proof='printf-style format directive protocol')
    kind = shape(right)
    if kind is None:
        return model.cell(plan, node, identity=identity) if not model.final else None
    return model.cell(plan, node, 'str', identity=identity)


def _directive(emitter, node, directive, value):
    from .native_classes import Expression, domain
    from .native_formatting import conversion, format_value
    from .native_class_builtins import _error, _type_name
    from .native_unions import project, union_kind
    if union_kind(value.kind):
        return Expression(project(value.kind, value.code, lambda kind, code:
            _directive(emitter, node, directive, Expression(f'({code}).clone()', kind)).code), 'str')
    kind = directive['type']
    spec = specification(directive)
    tag = domain(value.kind)
    from .native import _string
    literal = Expression('NativeText::from(' + _string(spec) + ')', 'str', spec)
    if kind in TEXT:
        shown = conversion(emitter, node, value, {'s': 115, 'r': 114, 'a': 97}[kind])
        return format_value(emitter, node, shown, literal)
    if kind == CHARACTER:
        return format_value(emitter, node, _character(emitter, node, value, tag), literal)
    numeric = {'int', 'bool', 'int_bool', 'float'}
    if tag not in numeric:
        name = _type_name(emitter, value, node)
        need = 'a real number' if kind in REAL or kind in {'d', 'i', 'u'} else 'an integer'
        return _error(emitter, node, 'str', f'format!("TypeError: %{kind} format: {need} is required, not {{}}",{name})')
    if kind in INTEGER and tag == 'float':
        if kind in {'x', 'X', 'o'}:
            return _error(emitter, node, 'str', f'"TypeError: %{kind} format: an integer is required, not float".to_owned()')
        operation = 'Int::from_f64' if emitter.model.integer == 'bigint' else 'native_float_integer'
        value = Expression(emitter.at(f'{operation}({emitter.scalar(value).code})', node), 'int')
    if kind in REAL and tag != 'float':
        value = Expression(emitter.coerce(value, 'float', node), 'float')
    if kind in INTEGER and directive['precision'] is not None:
        return _integer_precision(emitter, node, directive, value)
    return format_value(emitter, node, value, literal)


def _integer_precision(emitter, node, directive, value):
    """Integer precision is a minimum digit count after sign and prefix; width pads the result."""
    from .native_classes import Expression
    from .native_formatting import format_value
    from .native import _string
    flags, kind = directive['flags'], directive['type']
    prefixed = '#' in flags and kind in {'x', 'X', 'o'}
    inner = ('+' if '+' in flags else ' ' if ' ' in flags else '') + ('#' if prefixed else '') + {'i': 'd', 'u': 'd'}.get(kind, kind)
    before, text = emitter.capture(format_value(emitter, node, value, Expression('NativeText::from(' + _string(inner) + ')', 'str', inner)))
    emitter.model.native_percent_precision_used = True
    arguments = ','.join((directive['precision'] or '0', directive['width'] or '0', str('-' in flags).lower(),
                          str('0' in flags and '-' not in flags).lower(), str(prefixed).lower()))
    return Expression('{' + before + 'NativeText::from(native_percent_precision(&(' + text.code + '),' + arguments + '))}', 'str')


RUNTIME = r'''
fn native_percent_precision(text:&str,precision:usize,width:usize,left:bool,zero:bool,prefixed:bool)->String{
    let sign=if text.starts_with(['+','-',' ']){1}else{0};
    let head=sign+if prefixed{2}else{0};
    let digits=&text[head..];
    let mut body=String::with_capacity(width.max(precision+head));
    body.push_str(&text[..head]);
    for _ in digits.len()..precision{body.push('0');}
    body.push_str(digits);
    let length=body.len();
    if length>=width{return body;}
    if left{body.extend(std::iter::repeat(' ').take(width-length));return body;}
    let fill=if zero{'0'}else{' '};
    let padding:String=std::iter::repeat(fill).take(width-length).collect();
    if zero{body.insert_str(head,&padding);body}else{padding+&body}
}
'''


def runtime(model):
    return RUNTIME if getattr(model, 'native_percent_precision_used', False) else ''


def _character(emitter, node, value, tag):
    """%c: an integer code point or a one-character string (formatchar in unicodeobject.c)."""
    from .native_classes import Expression
    from .native_class_builtins import _error, _type_name
    if tag == 'str':
        holder = emitter.fresh()
        failure = _error(emitter, node, 'str', 'format!("TypeError: %c requires an int or a unicode character, not a string of length {}",' + holder + '.chars().count())').code
        return Expression('{let ' + holder + '=' + value.code + '.clone();if ' + holder + '.chars().count()==1{' + holder + '}else{' + failure + '}}', 'str')
    if tag not in {'int', 'bool', 'int_bool'}:
        name = _type_name(emitter, value, node)
        return _error(emitter, node, 'str', 'format!("TypeError: %c requires an int or a unicode character, not {}",' + name + ')')
    before, number = emitter.capture(Expression(emitter.number(value), 'int'))
    wide = f'{number.code}.to_i128()' if emitter.model.integer == 'bigint' else f'Some({number.code} as i128)'
    point, character = emitter.fresh(), emitter.fresh()
    outside = _error(emitter, node, 'str', '"OverflowError: %c arg not in range(0x110000)".to_owned()').code
    surrogate = _error(emitter, node, 'str', '"NotImplementedError: native text cannot hold a lone surrogate code point from %c".to_owned()').code
    return Expression('{' + before + f'match {wide}.filter(|{point}|(0..=0x10FFFF).contains({point})){{None=>{outside},Some({point})=>'
                      + f'match char::from_u32({point} as u32){{Some({character})=>NativeText::from({character}.to_string()),None=>{surrogate}}}}}}}', 'str')


def emit(emitter, operator, left, right, node, wanted):
    from .native_classes import Expression
    from .native_types import TupleType
    if not _format_string(node):
        return None
    pieces, _ = parse(node.left.value)
    directives = [piece for piece in pieces if isinstance(piece, dict)]
    from .native import _string
    from .native_types import tuple_field
    setup, holder = emitter.capture(right)
    if isinstance(right.kind, TupleType):
        values = [Expression(tuple_field(holder.code, index) + '.clone()', field) for index, field in enumerate(right.kind.fields)]
    else:
        values = [holder]
    if len(values) < len(directives):
        return Expression(emitter.at(f'Err::<{emitter.rust_type(wanted)},String>("TypeError: not enough arguments for format string".to_owned())', node), wanted)
    if len(values) > len(directives):
        return Expression(emitter.at(f'Err::<{emitter.rust_type(wanted)},String>("TypeError: not all arguments converted during string formatting".to_owned())', node), wanted)
    result = emitter.fresh()
    parts = [setup, f'let mut {result}=String::new();']
    remaining = iter(values)
    for piece in pieces:
        if isinstance(piece, dict):
            before, text = emitter.capture(_directive(emitter, node, piece, next(remaining)))
            parts.append(before + f'{result}.push_str(&({text.code}));')
        elif piece:
            parts.append(f'{result}.push_str({_string(piece)});')
    return Expression(emitter.coerce(Expression('{' + ''.join(parts) + f'NativeText::from({result})' + '}', 'str'), wanted, node), wanted)
