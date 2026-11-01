"""Canonical character codes and integer radix output over captured native values."""
from .native_types import alternatives, union_type
from .references import BuiltinIdentity

NAMES = frozenset({'ord', 'bin', 'oct', 'hex'})


def requires_frames(analysis):
    return any(BuiltinIdentity(name) in fact.identity.alternatives
               for scope in analysis.scopes.values() for fact in scope.calls.values() for name in NAMES)


def binding_error(name, count, keywords):
    if keywords:
        return f'TypeError: {name}() takes no keyword arguments'
    if count != 1:
        return f'TypeError: {name}() takes exactly one argument ({count} given)'
    return None


def analyze(model, plan, node, name, arguments, keywords, *, factory):
    from .native_classes import ClassUnsupported, domain, shape
    if binding_error(name, len(arguments), keywords):
        return factory('none')
    kind = shape(arguments[0])
    if kind is None and not model.final:
        return factory()
    results = []
    for choice in alternatives(kind):
        tag = domain(choice)
        if name != 'ord' and tag == 'object':
            raise ClassUnsupported(node, f'{name} on this object needs its __index__ special-method protocol; the native adapter currently accepts builtin integers and booleans',
                                   types=(('argument', choice),), proof='radix integer-index object protocol')
        accepted = tag in ({'str', 'bytes'} if name == 'ord' else {'int', 'bool', 'int_bool'})
        results.append(('int' if name == 'ord' else 'str') if accepted else 'none')
    result = factory()
    model.contribute(result, model.cell_for_kind(union_type(*results)), node)
    return result


def emit(emitter, node, name, arguments, keywords, wanted):
    from .native import _string
    from .native_classes import Expression, domain
    from .native_class_builtins import _error, _type_name
    from .native_unions import project, union_kind
    error = binding_error(name, len(arguments), keywords)
    if error:
        return _error(emitter, node, wanted, _string(error) + '.to_owned()')

    def lower(kind, code):
        value = Expression(f'({code}).clone()', kind)
        tag = domain(kind)
        if name == 'ord':
            if tag not in {'str', 'bytes'}:
                return _error(emitter, node, wanted,
                    'format!("TypeError: ord() expected string of length 1, but {} found",'
                    + _type_name(emitter, value, node) + ')').code
            before, value = emitter.capture(value)
            length = emitter.fresh()
            if tag == 'bytes':
                size = f'{value.code}.len()'
                ordinal = f'{value.code}[0] as usize'
            else:
                size = f'{value.code}.chars().count()'
                ordinal = f'{value.code}.chars().next().unwrap() as usize'
            fail = _error(emitter, node, wanted,
                'format!("TypeError: ord() expected a character, but string of length {} found",' + length + ')').code
            success = emitter.coerce(Expression(f'class_from_usize({ordinal})', 'int'), wanted, node)
            if tag == 'str':
                fast = emitter.coerce(Expression(f'class_from_usize({value.code}.as_bytes()[0] as usize)', 'int'), wanted, node)
                body = f'if {value.code}.byte_len()==1{{{fast}}}else{{let {length}={size};if {length}==1{{{success}}}else{{{fail}}}}}'
            else:
                body = f'let {length}={size};if {length}==1{{{success}}}else{{{fail}}}'
            return '{' + before + body + '}'
        if tag not in {'int', 'bool', 'int_bool'}:
            return _error(emitter, node, wanted,
                'format!("TypeError: \'{}\' object cannot be interpreted as an integer",'
                + _type_name(emitter, value, node) + ')').code
        before, number = emitter.capture(Expression(emitter.number(value), 'int'))
        prefix = {'bin': '0b', 'oct': '0o', 'hex': '0x'}[name]
        base = {'bin': 2, 'oct': 8, 'hex': 16}[name]
        if emitter.model.integer == 'bigint':
            negative = f'{number.code}.is_negative()'
            digits = f'{number.code}.unsigned_radix({base},false)'
        else:
            negative = f'{number.code}<0'
            digits = 'format!("{:' + {'bin': 'b', 'oct': 'o', 'hex': 'x'}[name] + '}",' + number.code + '.unsigned_abs())'
        rendered = f'NativeText::from(format!("{{}}{prefix}{{}}",if {negative}{{"-"}}else{{""}},{digits}))'
        return '{' + before + emitter.coerce(Expression(rendered, 'str'), wanted, node) + '}'

    value = arguments[0]
    return Expression(project(value.kind, value.code, lower) if union_kind(value.kind) else lower(value.kind, value.code), wanted)
