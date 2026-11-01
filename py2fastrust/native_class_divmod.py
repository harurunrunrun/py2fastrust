"""Captured divmod calls share the integer and binary64 quotient kernels."""
from itertools import product

from .native_types import TupleType, alternatives, union_type
from .references import BuiltinIdentity

INTEGRAL = frozenset({'int', 'bool', 'int_bool'})
NUMERIC = INTEGRAL | {'float'}
SEALED = NUMERIC | {'str', 'bytes', 'none', 'list', 'tuple', 'function', 'range', 'globals_dict'}


def requires_frames(analysis):
    return any(BuiltinIdentity('divmod') in fact.identity.alternatives
               for facts in analysis.scopes.values() for fact in facts.calls.values())


def binding_error(arguments, keywords):
    if keywords:
        return 'TypeError: divmod() takes no keyword arguments'
    if len(arguments) != 2:
        return f'TypeError: divmod expected 2 arguments, got {len(arguments)}'
    return None


def _kind(left, right, integer, node):
    from .native_classes import ClassUnsupported, domain
    tags = {domain(left), domain(right)}
    if not tags <= SEALED:
        raise ClassUnsupported(node, 'divmod on these operands requires __divmod__/__rdivmod__ special-method dispatch; that object protocol is not implemented',
                               types=(('left', left), ('right', right)), proof='divmod operand special-method protocol')
    if tags <= INTEGRAL:
        return TupleType(('int', 'int'))
    if tags <= NUMERIC:
        if integer == 'bigint' and tags != {'float'}:
            raise ClassUnsupported(node, 'mixed BigInt/float divmod requires checked arbitrary-precision integer to binary64 conversion; that numeric interoperation is not implemented',
                                   types=(('left', left), ('right', right)), proof='BigInt/binary64 divmod conversion')
        return TupleType(('float', 'float'))
    return 'none'


def analyze(model, plan, node, arguments, keywords, *, factory):
    from .native_classes import shape
    if binding_error(arguments, keywords):
        return factory('none')
    kinds = tuple(shape(value) for value in arguments)
    if None in kinds and not model.final:
        return factory()
    result = factory()
    outputs = [_kind(left, right, model.integer, node)
               for left, right in product(*(alternatives(kind) for kind in kinds))]
    model.contribute(result, model.cell_for_kind(union_type(*outputs)), node)
    return result


def emit(emitter, node, arguments, keywords, wanted):
    from .native import _string
    from .native_class_builtins import _error, _type_name
    from .native_classes import Expression, domain
    from .native_unions import project, union_kind
    error = binding_error(arguments, keywords)
    if error:
        return _error(emitter, node, wanted, _string(error) + '.to_owned()')

    def lower(left, right):
        if union_kind(left.kind):
            return Expression(project(left.kind, left.code, lambda kind, code:
                lower(Expression(f'({code}).clone()', kind), right).code), wanted)
        if union_kind(right.kind):
            return Expression(project(right.kind, right.code, lambda kind, code:
                lower(left, Expression(f'({code}).clone()', kind)).code), wanted)
        kind = _kind(left.kind, right.kind, emitter.model.integer, node)
        if kind == 'none':
            return _error(emitter, node, wanted,
                'format!("TypeError: unsupported operand type(s) for divmod(): \'{}\' and \'{}\'",'
                + _type_name(emitter, left, node) + ',' + _type_name(emitter, right, node) + ')')
        if kind.fields[0] == 'int':
            a, b = emitter.number(left), emitter.number(right)
            call = (f'({a}).divmod(&({b}))' if emitter.model.integer == 'bigint'
                    else f'native_divmod({a},{b})')
        else:
            emitter.model.divmod_float_required = True
            def number(value):
                return value.code if domain(value.kind) == 'float' else f'({emitter.number(value)})as f64'
            call = f'native_float_divmod({number(left)},{number(right)})'
        code = emitter.at(call, node)
        return emitter.encoded(code, kind, wanted, node)
    return lower(*arguments)
