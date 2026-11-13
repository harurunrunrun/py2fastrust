"""Canonical integer-string conversion limits on typed native frames."""
NAMES = frozenset({'set_int_max_str_digits', 'get_int_max_str_digits'})


def active(model):
    return getattr(model, 'integer_digit_limits_required', False)


def binding_error(name, positional, keywords):
    if name == 'get_int_max_str_digits':
        if keywords:
            return 'TypeError: sys.get_int_max_str_digits() takes no keyword arguments'
        if positional:
            return ('TypeError: sys.get_int_max_str_digits() takes no arguments '
                    f'({positional} given)')
        return None
    total = positional + len(keywords)
    if total > 1:
        label = 'argument' if positional else 'keyword argument'
        return ('TypeError: set_int_max_str_digits() takes at most 1 ' + label + ' '
                f'({total} given)')
    if not positional and 'maxdigits' not in dict(keywords):
        return ("TypeError: set_int_max_str_digits() missing required argument "
                "'maxdigits' (pos 1)")
    return None


def analyze(model, plan, node, identity, positional, keywords, *, factory):
    from .native_linked_members import MemberCall
    model.integer_digit_limits_required = True
    error = binding_error(identity.name, len(positional), keywords)
    if identity.name == 'set_int_max_str_digits' and error is None:
        from .native_classes import ClassUnsupported, domain, shape
        from .native_types import alternatives
        value = positional[0] if positional else dict(keywords)['maxdigits']
        for kind in alternatives(shape(value)):
            if domain(kind) == 'object':
                raise ClassUnsupported(node,
                    'this digit limit requires the source object __index__ '
                    'protocol; the native integer-index callback is not implemented',
                    types=(('maxdigits', kind),), proof='digit limit integer-index conversion')
    return MemberCall(factory('none' if identity.name.startswith('set_') else 'int'), error)


def emit(emitter, node, identity, record, positional, keywords):
    from .native import _string
    from .native_classes import Expression, shape
    kind = shape(record.result)
    if record.error:
        return Expression(emitter.at('Err::<' + emitter.rust_type(kind) +
            ',String>(' + _string(record.error) + '.to_owned())', node), kind)
    if identity.name == 'get_int_max_str_digits':
        return Expression('class_from_usize(native_int_digit_limit())', 'int')
    from .native_index_protocol import frame
    value = positional[0] if positional else dict(keywords)['maxdigits']
    number = frame(emitter, value, node)
    call = 'native_set_int_digit_limit(&(' + number + '))'
    return Expression(emitter.at(call, node), 'none')


def parse_error(expression, invalid):
    return expression + '.map_err(|error|native_int_parse_error(error,||' + invalid + '))'


def _has_integer(kind, seen=frozenset()):
    from .native_types import alternatives, ListType, TupleType, TupleSequenceType
    if kind in {'int', 'int_bool'}:
        return True
    if id(kind) in seen:
        return False
    seen = seen | {id(kind)}
    parts = alternatives(kind)
    if len(parts) > 1:
        return any(_has_integer(part, seen) for part in parts)
    if isinstance(kind, (ListType, TupleSequenceType)):
        return _has_integer(kind.element, seen)
    if isinstance(kind, TupleType):
        return any(_has_integer(field, seen) for field in kind.fields)
    from .native_classes import shape
    record = getattr(kind, 'record', None)
    if getattr(kind, '_native_class_mapping', False):
        return _has_integer(shape(record.key), seen) or (
            record.category == 'dict' and _has_integer(shape(record.value), seen))
    if getattr(kind, '_native_mapping_view', False):
        return _has_integer(shape(record.element), seen)
    if getattr(kind, '_native_class_deque', False):
        return _has_integer(shape(record.element), seen)
    return False


def _pure_builtin_display(kind, seen=frozenset()):
    from .native_classes import shape
    from .native_types import alternatives, ListType, TupleType, TupleSequenceType
    if kind in {'int', 'int_bool', 'bool', 'none', 'str', 'bytes', 'float', 'complex'}:
        return True
    if id(kind) in seen:
        return False
    seen = seen | {id(kind)}
    parts = alternatives(kind)
    if len(parts) > 1:
        return all(_pure_builtin_display(part, seen) for part in parts)
    if isinstance(kind, (ListType, TupleSequenceType)):
        return _pure_builtin_display(kind.element, seen)
    if isinstance(kind, TupleType) and not getattr(kind, '_native_named_tuple', False):
        return all(_pure_builtin_display(part, seen) for part in kind.fields)
    if getattr(kind, '_native_class_mapping', False) and kind.record.flavor == 'dict':
        return (_pure_builtin_display(shape(kind.record.key), seen)
                and _pure_builtin_display(shape(kind.record.value), seen))
    return False


def guard_deferred_repr(emitter, value, node, protocol):
    constant = getattr(value, 'constant', None)
    if type(constant) in {int, bool} and abs(constant).bit_length() <= 2126:
        return
    validate_payload(emitter.model, value.kind, node, protocol)


def validate_payload(model, kind, node, protocol):
    if active(model) and model.integer == 'bigint' and _has_integer(kind):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,
            protocol + ' retains its Python exception payload until the exception '
            'is displayed; digit-limited BigInt exception rendering is not '
            'implemented by this native error representation',
            types=(('payload', kind),), proof='deferred digit-limited exception payload display')


def guard_error_repr(emitter, key, node):
    guard_deferred_repr(emitter, key, node, 'A missing mapping key')


def show(emitter, value, node, representation):
    if not active(emitter.model):
        return None
    # Fixed-width values have at most 39 decimal digits, below every allowed
    # nonzero limit. Their existing callback-aware observers remain valid.
    if emitter.model.integer != 'bigint':
        return None
    from .native_classes import Expression, ClassUnsupported, shape
    from .native_types import ListType, TupleType, TupleSequenceType
    from .native_unions import project, union_kind
    kind = value.kind
    if not _has_integer(kind):
        return None
    if (isinstance(kind, (ListType, TupleSequenceType))
            or getattr(kind, '_native_class_mapping', False) and kind.record.flavor == 'dict'):
        if not _pure_builtin_display(kind):
            raise ClassUnsupported(node,
                'this integer-bearing container also has a source/custom '
                'representation callback; its checked live container display '
                'protocol is not implemented on the digit-limit native path',
                types=(('value', kind),), proof='callback-safe digit-limited container display')
    if kind == 'int':
        return emitter.at('native_int_decimal_text(&(' + value.code + '))', node)
    if kind == 'int_bool':
        integer = emitter.fresh()
        return ('match &(' + value.code + '){NativeScalar::Int(' + integer + ')=>'
                + emitter.at('native_int_decimal_text(' + integer + ')', node)
                + ',NativeScalar::Bool(value)=>if *value{"True"}else{"False"}.to_owned()}')
    if union_kind(kind):
        return project(kind, value.code, lambda part, code:
            emitter.show(Expression('(' + code + ').clone()', part), node, representation))
    if isinstance(kind, TupleType):
        # Fixed tuples already render each field in the enclosing Result
        # context, including source NamedTuple formatting protocols.
        return None
    if isinstance(kind, (ListType, TupleSequenceType)):
        owner, item, text, index = (emitter.fresh() for _ in range(4))
        shown = emitter.show(Expression(item + '.clone()', kind.element), node, True)
        opened, closed = ('[', ']') if isinstance(kind, ListType) else ('(', ')')
        code = ('{let ' + owner + '=(' + value.code + ').clone();let mut ' + text
                + '=String::from("' + opened + '");')
        values = owner + '.borrow().iter()' if isinstance(kind, ListType) else owner + '.iter()'
        code += ('for(' + index + ',' + item + ')in ' + values + '.enumerate(){'
                 'if ' + index + '>0{' + text + '.push_str(", ");}'
                 + text + '.push_str(&(' + shown + '));}')
        if isinstance(kind, TupleSequenceType):
            code += 'if ' + owner + '.len()==1{' + text + '.push(\',\');}'
        return code + text + '.push(\'' + closed + '\');' + text + '}'
    if getattr(kind, '_native_class_mapping', False) and kind.record.flavor == 'dict':
        owner, read, key, item, text, index = (emitter.fresh() for _ in range(6))
        record = kind.record
        a = emitter.show(Expression(key + '.clone()', shape(record.key)), node, True)
        b = emitter.show(Expression(item + '.clone()', shape(record.value)), node, True)
        return ('{let ' + owner + '=(' + value.code + ').clone();let ' + read + '='
                + owner + '.borrow();let mut ' + text + '=String::from("{");'
                'for(' + index + ',(' + key + ',' + item + '))in ' + read
                + '.entries.iter().enumerate(){if ' + index + '>0{' + text
                + '.push_str(", ");}' + text + '.push_str(&(' + a + '));'
                + text + '.push_str(": ");' + text + '.push_str(&(' + b + '));}'
                + text + '.push(\'}\');' + text + '}')
    raise ClassUnsupported(node,
        'this integer-bearing container needs a fallible digit-limited '
        'representation observer; that container display protocol is not implemented',
        types=(('value', kind),), proof='fallible integer-string conversion observer')


STATE = r'''
thread_local! {static NATIVE_INT_DIGIT_LIMIT:std::cell::Cell<usize>=const {std::cell::Cell::new(4300)};}
#[inline]
fn native_int_digit_limit()->usize {NATIVE_INT_DIGIT_LIMIT.with(std::cell::Cell::get)}
fn native_set_int_digit_limit(value:&NativeInt)->Result<(),String> {
    let value=NATIVE_DIGIT_LIMIT_WIDE;
    let value=value.filter(|value|(-2147483648..=2147483647).contains(value))
        .ok_or_else(||"OverflowError: Python int too large to convert to C int".to_owned())?;
    if value!=0&&value<640{return Err("ValueError: maxdigits must be >= 640 or 0 for unlimited".to_owned());}
    NATIVE_INT_DIGIT_LIMIT.with(|limit|limit.set(value as usize));Ok(())
}
#[cold]
fn native_int_parse_limit_error(limit:usize,count:usize)->String {
    format!("ValueError: Exceeds the limit ({limit} digits) for integer string conversion: value has {count} digits; use sys.set_int_max_str_digits() to increase the limit")
}
fn native_int_parse_error<F:FnOnce()->String>(error:String,invalid:F)->String {
    if error.starts_with("ValueError: Exceeds the limit "){error}else{invalid()}
}
fn native_int_digit_preflight<I,D,S>(characters:I,base:u32,digit:D,space:S)->Result<(),String>
where I:Iterator<Item=char>,D:Fn(char)->Option<u32>,S:Fn(char)->bool {
    if base.is_power_of_two()||characters.size_hint().1.is_some_and(|upper|upper<=640){return Ok(());}
    let limit=native_int_digit_limit();if limit==0{return Ok(());}
    let invalid=||"ValueError: invalid literal for int()".to_owned();
    let mut count=0usize;let mut previous=false;let mut trailing=false;
    for character in characters {
        if character=='\0'{break;}
        if space(character){if !previous{return Err(invalid());}trailing=true;continue;}
        if trailing{return Err(invalid());}
        if character=='_'{if !previous{return Err(invalid());}previous=false;continue;}
        digit(character).filter(|&number|number<base).ok_or_else(invalid)?;
        count+=1;previous=true;
    }
    if !previous{return Err(invalid());}
    if count>limit{return Err(native_int_parse_limit_error(limit,count));}Ok(())
}
'''

BIG_TEXT = r'''
#[cold]
fn native_int_format_limit_error(limit:usize)->String {
    format!("ValueError: Exceeds the limit ({limit} digits) for integer string conversion; use sys.set_int_max_str_digits() to increase the limit")
}
fn native_int_decimal_text(value:&Int)->Result<String,String> {
    if value.bit_length()<=2126{return Ok(value.to_string());}
    let limit=native_int_digit_limit();
    if limit==0{return Ok(value.to_string());}
    if value.bit_length()>limit.saturating_mul(4){return Err(native_int_format_limit_error(limit));}
    let text=value.to_string();
    if text.len()-usize::from(value.is_negative())>limit{return Err(native_int_format_limit_error(limit));}
    Ok(text)
}
'''

PREFLIGHT = r'''
        native_int_digit_preflight(initial.into_iter().chain(characters.clone()),base,&digit,space)?;
'''


def _replace(source, old, new, count=1):
    actual = source.count(old)
    if actual != count:
        raise RuntimeError(f'integer digit-limit runtime hook changed: {old[:70]!r}, {actual}')
    return source.replace(old, new)


def runtime(source, model):
    if not active(model):
        return source
    bigint = model.integer == 'bigint'
    state = STATE.replace('NATIVE_DIGIT_LIMIT_WIDE',
        'value.to_i128()' if bigint else 'Some(*value as i128)')
    source = _replace(source,
        'fn parse_digits<I, D>(characters: I, mut base: u32, digit: D)',
        'fn parse_digits<I, D, S>(characters: I, mut base: u32, digit: D, space: S)')
    source = _replace(source, 'where I: Iterator<Item = char>, D: Fn(char) -> Option<u32> {',
        'where I: Iterator<Item = char>+Clone, D: Fn(char) -> Option<u32>, S: Fn(char)->bool {')
    source = _replace(source, 'Self::parse_digits(text.trim().chars(), base, Self::decimal_digit)',
        'Self::parse_digits(text.trim().chars(), base, Self::decimal_digit, char::is_whitespace)')
    source = _replace(source, '|character| character.to_digit(36))',
        '|character| character.to_digit(36), |character|matches!(character as u32,9..=13|32))')
    source = _replace(source, '        let packed_bits = if base.is_power_of_two()',
        PREFLIGHT + '        let packed_bits = if base.is_power_of_two()')
    if bigint:
        source += '\n' + BIG_TEXT
        source = _replace(source, 'return Ok(Some(self.to_string()));',
            'return Ok(Some(native_int_decimal_text(self)?));')
        source = _replace(source, "self.unsigned_radix(base, kind == 'X')",
            "if base==10{native_int_decimal_text(self)?.trim_start_matches('-').to_owned()}else{self.unsigned_radix(base, kind == 'X')}")
        if getattr(model, 'formatting_required', False):
            source = _replace(source, 'return Ok(Some(value.to_string()));',
                'return Ok(Some(native_int_decimal_text(value)?));')
            source = _replace(source, "value.unsigned_radix(base, kind == 'X')",
                "if base==10{native_int_decimal_text(value)?.trim_start_matches('-').to_owned()}else{value.unsigned_radix(base, kind == 'X')}")
    else:
        # Only long tokens need a lexical preflight. The original short
        # parsing loop is retained without per-digit counter/state overhead.
        source = _replace(source, 'fn native_parse_integer(', 'fn native_unlimited_parse_integer(')
        source = _replace(source, 'fn native_parse_bytes_integer(', 'fn native_unlimited_parse_bytes_integer(')
        state += r'''
fn native_parse_integer(value:&str)->Result<NativeInt,String> {
    if value.len()>640 {
        let digits=value.trim_matches(NATIVE_DECIMAL_SPACE);
        let digits=digits.strip_prefix(['+','-']).unwrap_or(digits);
        native_int_digit_preflight(digits.chars(),10,|character|native_fixed_decimal_digit(character as u32).map(|value|value as u32),NATIVE_DECIMAL_SPACE)?;
    }
    native_unlimited_parse_integer(value)
}
fn native_parse_bytes_integer(value:&[u8])->Result<NativeInt,String> {
    if value.len()>640 {
        let mut first=0;let mut last=value.len();
        while first<last&&native_fixed_int_space(value[first]){first+=1;}
        while first<last&&native_fixed_int_space(value[last-1]){last-=1;}
        if first<last&&matches!(value[first],b'+'|b'-'){first+=1;}
        native_int_digit_preflight(value[first..last].iter().map(|&byte|byte as char),10,
            |character|character.to_digit(10),|character|matches!(character as u32,9..=13|32))?;
    }
    native_unlimited_parse_bytes_integer(value)
}
'''
        state = state.replace('NATIVE_DECIMAL_SPACE', 'native_fixed_text_space'
            if model.string_mode == 'unicode' else '|character:char|matches!(character as u32,9..=13|32)')
        if getattr(model, 'explicit_radix_used', False):
            source = _replace(source,
                'fn native_fixed_parse_radix<I,D>(characters:I,mut base:u32,digit:D)',
                'fn native_fixed_parse_radix<I,D,S>(characters:I,mut base:u32,digit:D,space:S)')
            source = _replace(source,
                'where I:Iterator<Item=char>,D:Fn(char)->Option<u32>{',
                'where I:Iterator<Item=char>+Clone,D:Fn(char)->Option<u32>,S:Fn(char)->bool{')
            source = _replace(source, '    let mut seen=false;\n    for character in initial.into_iter().chain(characters){',
                '    let mut seen=false;\n    native_int_digit_preflight(initial.into_iter().chain(characters.clone()),base,&digit,space)?;\n    for character in initial.into_iter().chain(characters){')
            source = _replace(source, 'base,|character|character.to_digit(36))',
                'base,|character|character.to_digit(36),|character|matches!(character as u32,9..=13|32))')
            if model.string_mode == 'unicode':
                source = _replace(source, '.or_else(||character.to_digit(36)))',
                    '.or_else(||character.to_digit(36)),native_fixed_text_space)')
    for parser, representation in (('native_parse_integer(value)', 'text_repr_str(value)'),
                                  ('native_parse_bytes_integer(value)', 'text_repr_bytes(value)')):
        old = parser + '.map_err(|_|format!("ValueError: invalid literal for int() with base 10: {:.200}",' + representation + '))'
        new = parse_error(parser, 'format!("ValueError: invalid literal for int() with base 10: {:.200}",' + representation + ')')
        source = _replace(source, old, new)
    return source + '\n' + state
