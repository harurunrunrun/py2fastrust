"""sum() over int/bool/float items with CPython 3.14.4 builtin_sum_impl semantics.

The default start is int 0. Integer items accumulate as integers until the first
float, which is added with the ordinary int + float operation; from then on a
CompensatedSum (Neumaier) adds floats and integers converted with
PyLong_AsDouble rounding, and cs_to_double finishes the result.
"""
import ast

NUMBERS = frozenset({'int', 'bool', 'int_bool', 'float'})


def analyze(model, node, item_kinds, start, cell):
    from .native_classes import Cell, ClassUnsupported
    if 'float' not in item_kinds and start.root().tag != 'float':
        return None
    if not set(item_kinds) <= NUMBERS:
        raise ClassUnsupported(node, 'sum of floats mixed with non-numeric items needs the generic __add__ protocol; only builtin int, bool and float items are implemented',
                               proof='floating sum addition protocol')
    start_tag = start.root().tag
    if start_tag not in {None, 'int', 'bool', 'int_bool', 'float'}:
        raise ClassUnsupported(node, 'this sum start needs its numeric addition protocol; only builtin int, bool and float starts are implemented',
                               proof='sum start and addition result representation')
    result = cell()
    model.contribute(result, Cell('float'), node)
    if start_tag != 'float':
        model.contribute(result, start, node)
    return result


def emit(emitter, node, start, kind, wanted, member, accumulator):
    """Return (setup, action, finish) code around the item loop."""
    from .native_classes import Expression
    from .native_types import alternatives
    from .native_unions import project, union_kind
    floating, ints, hi, lo = (emitter.fresh() for _ in range(4))
    bigint = emitter.model.integer == 'bigint'

    def to_double(code):
        if bigint:
            return emitter.at('(' + code + ').ratio(&Int::exact_small(1)).map_err(|_|"OverflowError: int too large to convert to float".to_owned())', node)
        return '((' + code + ') as f64)'

    def cs_add(value):
        return ('{let x=' + value + ';let t=' + hi + '+x;if ' + hi + '.abs()>=x.abs(){' + lo + '+=(' + hi + '-t)+x;}else{'
                + lo + '+=(x-t)+' + hi + ';}' + hi + '=t;}')

    if start.kind == 'float':
        setup = (f'let mut {floating}=true;let mut {ints}:NativeInt={emitter.literal(0)};'
                 f'let mut {hi}:f64={emitter.scalar(start).code};let mut {lo}:f64=0.0;')
    else:
        setup = (f'let mut {floating}=false;let mut {ints}:NativeInt={emitter.number(start)};'
                 f'let mut {hi}:f64=0.0;let mut {lo}:f64=0.0;')

    def branch(item_kind, code):
        value = Expression('(' + code + ').clone()', item_kind)
        if item_kind == 'float':
            x = emitter.scalar(value).code
            return ('{let x=' + x + ';if ' + floating + '{' + cs_add('x') + '}else{' + floating + '=true;'
                    + hi + '=' + to_double(ints + '.clone()') + '+x;' + lo + '=0.0;}}')
        number = emitter.number(value)
        added = emitter.numeric.binary(ast.Add(), Expression(ints + '.clone()', 'int'), Expression(number, 'int'), node)
        return ('{if ' + floating + '{' + cs_add(to_double(number)) + '}else{' + ints + '=' + added.code + ';}}')

    action = (project(kind, member, branch) if union_kind(kind) else branch(kind, member)) + ';'
    total = '(if ' + lo + '!=0.0&&' + lo + '.is_finite(){' + hi + '+' + lo + '}else{' + hi + '})'
    # Identity-tracking float programs carry NativeIdentityFloat values; the sum is a fresh float.
    from .native_float_identity import wrap
    total = wrap(emitter, total, node)
    if start.kind == 'float':
        finish = accumulator + '=' + emitter.coerce(Expression(total, 'float'), wanted, node) + ';'
    else:
        finish = (accumulator + '=if ' + floating + '{' + emitter.coerce(Expression(total, 'float'), wanted, node) + '}else{'
                  + emitter.coerce(Expression(ints, 'int'), wanted, node) + '};')
    return setup, action, finish


def requires_frames(unit, analysis):
    """Route sum() calls whose items may be floats to the framed reducer."""
    from .native_types import ListType, TupleType, TupleSequenceType, alternatives
    def floating(kind):
        for choice in alternatives(kind):
            if choice == 'float':
                return True
            if isinstance(choice, (ListType, TupleSequenceType)) and floating(choice.element):
                return True
            if isinstance(choice, TupleType) and any(floating(field) for field in choice.fields):
                return True
        return False
    for node in ast.walk(unit.tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'sum' and node.args):
            continue
        source = node.args[0]
        probes = [source.elt] if isinstance(source, (ast.GeneratorExp, ast.ListComp, ast.SetComp)) else [source]
        if len(node.args) > 1:
            probes.append(node.args[1])
        for probe in probes:
            try:
                ordinal = unit.ordinal(probe)
            except KeyError:
                continue
            if any(floating(facts.expressions.get(ordinal)) for facts in analysis.scopes.values()):
                return True
    return False
