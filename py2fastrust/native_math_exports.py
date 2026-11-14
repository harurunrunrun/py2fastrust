"""CPython 3.14.4 canonical math export facts and concrete float module data.

The factual inventory follows the official v3.14.4 Modules/mathmodule.c method
and constant tables. No submitted module is imported to discover its exports.
"""
from dataclasses import dataclass

PUBLIC_NAMES = ('acos', 'acosh', 'asin', 'asinh', 'atan', 'atan2', 'atanh', 'cbrt', 'ceil', 'copysign', 'cos', 'cosh', 'degrees', 'dist', 'erf', 'erfc', 'exp', 'exp2', 'expm1', 'fabs', 'factorial', 'floor', 'fma', 'fmod', 'frexp', 'fsum', 'gamma', 'gcd', 'hypot', 'isclose', 'isfinite', 'isinf', 'isnan', 'isqrt', 'lcm', 'ldexp', 'lgamma', 'log', 'log1p', 'log10', 'log2', 'modf', 'pow', 'radians', 'remainder', 'sin', 'sinh', 'sqrt', 'tan', 'tanh', 'sumprod', 'trunc', 'prod', 'perm', 'comb', 'nextafter', 'ulp', 'pi', 'e', 'tau', 'inf', 'nan')
FUNCTION_NAMES = frozenset(('acos', 'acosh', 'asin', 'asinh', 'atan', 'atan2', 'atanh', 'cbrt', 'ceil', 'copysign', 'cos', 'cosh', 'degrees', 'dist', 'erf', 'erfc', 'exp', 'exp2', 'expm1', 'fabs', 'factorial', 'floor', 'fma', 'fmod', 'frexp', 'fsum', 'gamma', 'gcd', 'hypot', 'isclose', 'isfinite', 'isinf', 'isnan', 'isqrt', 'lcm', 'ldexp', 'lgamma', 'log', 'log1p', 'log10', 'log2', 'modf', 'pow', 'radians', 'remainder', 'sin', 'sinh', 'sqrt', 'tan', 'tanh', 'sumprod', 'trunc', 'prod', 'perm', 'comb', 'nextafter', 'ulp'))
CONSTANT_BITS = {'pi': '400921fb54442d18', 'e': '4005bf0a8b145769', 'tau': '401921fb54442d18', 'inf': '7ff0000000000000', 'nan': '7ff8000000000000'}


def canonical(module):
    return module.name == 'math' and module.origin == 'builtin'


@dataclass
class Constant:
    module: object
    name: str
    key: object
    value: object


def seed(linker, module, name):
    if not (module.native_adapter and canonical(module) and name in CONSTANT_BITS):
        return False
    from .native_classes import Cell
    records = getattr(linker.model, 'math_constant_data', None)
    if records is None:
        records = linker.model.math_constant_data = {}
    key = linker.unit.global_name(module.name, name)
    record = records.setdefault(key, Constant(module, name, key, Cell('float')))
    namespace = linker.model.namespace
    namespace.incoming.setdefault(key, {})[('canonical_math_constant', name)] = record.value
    namespace.active.add(key)
    namespace.refresh(key, linker.model.tree)
    return True


def initializer(model, emitter, module):
    records = [row for row in getattr(model, 'math_constant_data', {}).values()
               if row.module.number == module.number]
    if not records:
        return None
    from .native_classes import Expression
    from .native_float_identity import enabled
    fields = dict(model.namespace.fields())
    body = ''
    for row in records:
        raw = 'f64::from_bits(0x' + CONSTANT_BITS[row.name] + '_u64)'
        if enabled(model):
            # A canonical module NaN gets one checked identity in its cached
            # import lifecycle. Finite constants have no NaN identity demand.
            raw = ('native_identity_float(' + raw + ')?' if row.name == 'nan'
                   else 'NativeIdentityFloat::constant(' + raw + ')')
        value = emitter.fresh()
        body += 'let ' + value + '=' + raw + ';'
        stored = emitter.coerce(Expression(value, 'float'), fields[row.key], model.tree)
        body += 'globals.borrow_mut().value_' + str(model.namespace.index(row.key)) + '=Some(' + stored + ');'
    # This shared builtin initializer has no source statement. The existing
    # import-call wrapper adds the actual caller's original source location.
    return ('native_at((||->Result<(),String>{' + body + 'Ok(())})(),'
            '0,("<math>","<module>"))')


def guard_observation(model, node, module):
    if canonical(module) and model.namespace.globals_observed:
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,
            'globals() observes the complete namespace published by math import *; '
            'the complete builtin-function value and namespace-order observer protocol is not implemented',
            proof='complete canonical math star namespace observation')
