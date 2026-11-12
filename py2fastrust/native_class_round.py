"""Integral round over captured arguments with decimal ties-to-even."""
from itertools import product

from .references import BuiltinIdentity
from .native_types import EMPTY, alternatives, union_type

INTEGRAL = frozenset({'int', 'bool', 'int_bool'})
SEALED = INTEGRAL | {'str', 'bytes', 'none', 'list', 'tuple', 'function', 'range', 'globals_dict', 'float'}


def requires_frames(analysis):
    return any(BuiltinIdentity('round') in call.identity.alternatives
               for facts in analysis.scopes.values() for call in facts.calls.values())


def bind(arguments, keywords, default):
    keywords = tuple(keywords)
    count = len(arguments) + len(keywords)
    if count > 2:
        return None, f'TypeError: round() takes at most 2 arguments ({count} given)'
    names = {key for key, _ in keywords}
    if not arguments and 'number' not in names:
        return None, "TypeError: round() missing required argument 'number' (pos 1)"
    for position, name in enumerate(('number', 'ndigits')):
        if position < len(arguments) and name in names:
            return None, f"TypeError: argument for round() given by name ('{name}') and position ({position + 1})"
    for name, _ in keywords:
        if name not in {'number', 'ndigits'}:
            return None, f"TypeError: round() got an unexpected keyword argument '{name}'"
    values = dict(zip(('number', 'ndigits'), arguments))
    values.update(keywords)
    return (values['number'], values.get('ndigits', default)), None


def _kind(number, digits, node):
    from .native_classes import ClassUnsupported, domain
    tags = domain(number), domain(digits)
    if None in tags:
        return None
    if not set(tags) <= SEALED:
        raise ClassUnsupported(node,
            'round() on these operands requires the __round__ or __index__ object protocol; that protocol is not implemented by the integral adapter',
            types=(('number', number), ('ndigits', digits)), proof='round operand and integer-index protocols')
    if tags[0] == 'float':
        raise ClassUnsupported(node,
            'round() of a binary64 value requires its decimal rounding, overflow and result-kind protocol; only integral round is implemented',
            types=(('number', number),), proof='binary64 round protocol')
    return 'int' if tags[0] in INTEGRAL and tags[1] in INTEGRAL | {'none'} else EMPTY


def analyze(model, plan, node, arguments, keywords, *, factory):
    from .native_classes import Cell, shape
    values, error = bind(arguments, keywords, Cell('none'))
    if error:
        return factory(EMPTY)
    kinds = tuple(shape(value) for value in values)
    if None in kinds and not model.final:
        return factory()
    outputs = [_kind(number, digits, node)
               for number, digits in product(*(alternatives(kind) for kind in kinds))]
    result = factory()
    model.contribute(result, model.cell_for_kind(union_type(*outputs)), node)
    return result


def _integral(emitter, number, digits):
    value = emitter.number(number)
    if digits.kind == 'none':
        return value
    count = emitter.number(digits)
    if emitter.model.integer == 'bigint':
        return ('{let class_round_value=' + value + ';let mut class_round_digits=' + count + ';'
                'if !class_round_digits.is_negative(){class_round_value}else{'
                'let class_round_magnitude=class_round_value.abs();'
                'let class_round_twice=class_round_magnitude.add(&class_round_magnitude);'
                'let mut class_round_unit=Int::from_i128(1);'
                'while class_round_digits.is_negative()&&class_round_unit<=class_round_twice{'
                'class_round_unit=class_round_unit.mul(&Int::from_i128(10));'
                'class_round_digits=class_round_digits.add(&Int::from_i128(1));}'
                'if class_round_unit>class_round_twice{Int::from_i128(0)}else{'
                'let(class_round_q,class_round_r)=class_round_magnitude.divmod(&class_round_unit).unwrap();'
                'let class_round_half=class_round_unit.divmod(&Int::from_i128(2)).unwrap().0;'
                'let class_round_odd=!class_round_q.modulo(&Int::from_i128(2)).unwrap().is_zero();'
                'let class_round_q=if class_round_r>class_round_half||'
                '(class_round_r==class_round_half&&class_round_odd){class_round_q.add(&Int::from_i128(1))}else{class_round_q};'
                'let class_round_result=class_round_q.mul(&class_round_unit);'
                'if class_round_value.is_negative(){class_round_result.neg()}else{class_round_result}}}}')
    unsigned = 'u64' if emitter.model.integer == 'i64' else 'u128'
    return ('{let class_round_value:NativeInt=' + value + ';let mut class_round_digits:NativeInt=' + count + ';'
            'if class_round_digits>=0{class_round_value}else{'
            'let class_round_magnitude=class_round_value.unsigned_abs();'
            f'let mut class_round_unit:{unsigned}=1;let mut class_round_overflow=false;'
            'while class_round_digits<0{match class_round_unit.checked_mul(10){'
            'Some(value)=>class_round_unit=value,None=>{class_round_overflow=true;break}}'
            'class_round_digits+=1;}'
            'if class_round_overflow{0}else{'
            'let class_round_q=class_round_magnitude/class_round_unit;'
            'let class_round_r=class_round_magnitude%class_round_unit;'
            'let class_round_half=class_round_unit/2;'
            'let class_round_q=class_round_q+if class_round_r>class_round_half||'
            '(class_round_r==class_round_half&&class_round_q%2!=0){1}else{0};'
            'let class_round_result=class_round_q.wrapping_mul(class_round_unit)as NativeInt;'
            'if class_round_value<0{class_round_result.wrapping_neg()}else{class_round_result}}}}')


def emit(emitter, node, arguments, keywords, wanted):
    from .native import _string
    from .native_classes import Expression, domain
    from .native_class_builtins import _error, _type_name
    from .native_unions import project, union_kind
    values, error = bind(arguments, keywords.items(), Expression('()', 'none'))
    if error:
        return _error(emitter, node, wanted, _string(error) + '.to_owned()')

    def lower(values):
        for index, value in enumerate(values):
            if union_kind(value.kind):
                return Expression(project(value.kind, value.code, lambda kind, code:
                    lower(values[:index] + [Expression(f'({code}).clone()', kind)] + values[index + 1:]).code), wanted)
        number, digits = values
        _kind(number.kind, digits.kind, node)
        if domain(number.kind) not in INTEGRAL:
            return _error(emitter, node, wanted,
                'format!("TypeError: type {} doesn\'t define __round__ method",' + _type_name(emitter, number, node) + ')')
        if domain(digits.kind) not in INTEGRAL | {'none'}:
            return _error(emitter, node, wanted,
                'format!("TypeError: \'{}\' object cannot be interpreted as an integer",' + _type_name(emitter, digits, node) + ')')
        return emitter.encoded(_integral(emitter, number, digits), 'int', wanted, node)
    return lower(list(values))
