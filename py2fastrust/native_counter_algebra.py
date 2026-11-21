"""Counter ``+ - | &`` between two Counters, following Lib/collections/__init__.py (3.14).

Each operator builds a new Counter. The left operand's items are visited
first in insertion order, combining each count with the right operand's count
(a missing key counts as zero without being inserted) and keeping only
positive results. The right operand's items whose keys are absent from the
left operand follow: + and | keep positive counts, - keeps the negation of
negative counts, and & adds nothing.
"""
import ast

OPERATORS = (ast.Add, ast.Sub, ast.BitOr, ast.BitAnd)


def _counter_kinds(value):
    from .native_classes import shape
    from .native_class_mappings import mapping_kind
    from .native_types import alternatives
    kinds = alternatives(shape(value))
    if kinds and all(mapping_kind(kind) and kind.record.flavor == 'Counter' for kind in kinds):
        return kinds
    return None


def analyze(model, plan, node, operator, left, right, identity):
    from .native_classes import Cell
    if not isinstance(node, ast.BinOp) or not isinstance(operator, OPERATORS):
        return None
    first, second = _counter_kinds(left), _counter_kinds(right)
    if first is None or second is None:
        return None
    record = model.mappings.record(plan, node, 'dict', 'counter_operator', flavor='Counter')
    record.operands = (left, right)
    for kind in first + second:
        model.mappings.contribute_key(record, kind.record.key, node)
    model.contribute(record.value, Cell('int'), node)
    return model.cell(plan, node, record.kind, identity=identity)


def _count(emitter, node, code, kind):
    from .native_classes import Expression
    return emitter.coerce(Expression(code, kind), 'int', node)


def _entries(emitter, node, owner, body):
    """Visit (key, count) of one Counter through the checked dictionary cursor."""
    from .native_classes import shape
    emitter.model.mappings.views.require_positions(owner.kind, node)
    record = owner.kind.record
    cursor, item, key, value = (emitter.fresh() for _ in range(4))
    pull = emitter.at(cursor + '.next(|key,value|(key.clone(),value.clone()))', node)
    return ('{let mut ' + cursor + '=ClassMappingCursor::new((' + owner.code + ').clone());loop{let Some(' + item + ')=(' + pull
            + ')else{break;};let (' + key + ',' + value + ')=' + item + ';'
            + body(key, shape(record.key), _count(emitter, node, value, shape(record.value))) + '}}')


def _combine(emitter, node, operator, result, left, right):
    from .native_classes import Expression
    from .native_primitive_ops import emit as primitive
    zero = Expression(emitter.literal(0), 'int', 0)

    def positive(code):
        return emitter.comparison(ast.Gt(), Expression(code + '.clone()', 'int'), zero, node)

    def store(key, key_kind, count):
        return emitter.model.mappings._set(emitter, node, result, Expression(key, key_kind), Expression(count, 'int'))

    def own(key, key_kind, count):
        current, other, combined = emitter.fresh(), emitter.fresh(), emitter.fresh()
        lookup = emitter.model.mappings.emit_get(emitter, node, right, Expression(key + '.clone()', key_kind), 'int').code
        if isinstance(operator, (ast.Add, ast.Sub)):
            value = primitive(emitter, operator, Expression(current + '.clone()', 'int'), Expression(other + '.clone()', 'int'), node, 'int').code
        else:
            # __or__ keeps the larger count, __and__ the smaller; ties keep the left count.
            smaller = emitter.comparison(ast.Lt(), Expression(current + '.clone()', 'int'), Expression(other + '.clone()', 'int'), node)
            chosen = (other, current) if isinstance(operator, ast.BitOr) else (current, other)
            value = 'if ' + smaller + '{' + chosen[0] + '.clone()}else{' + chosen[1] + '.clone()}'
        return ('let ' + current + '=' + count + ';let ' + other + '=' + lookup + ';let ' + combined + '=' + value + ';'
                + 'if ' + positive(combined) + '{' + store(key, key_kind, combined) + '}')

    def extra(key, key_kind, count):
        current = emitter.fresh()
        absent = '!(' + emitter.model.mappings.comparison(emitter, ast.In(), Expression(key + '.clone()', key_kind), left, node) + ')'
        if isinstance(operator, ast.Sub):
            negated = primitive(emitter, ast.Sub(), zero, Expression(current + '.clone()', 'int'), node, 'int').code
            kept = emitter.comparison(ast.Lt(), Expression(current + '.clone()', 'int'), zero, node)
            return 'let ' + current + '=' + count + ';if ' + absent + '&&' + kept + '{' + store(key, key_kind, '(' + negated + ')') + '}'
        return 'let ' + current + '=' + count + ';if ' + absent + '&&' + positive(current) + '{' + store(key, key_kind, current) + '}'

    code = _entries(emitter, node, left, own)
    if not isinstance(operator, ast.BitAnd):
        code += _entries(emitter, node, right, extra)
    return code


def emit(emitter, operator, left, right, node, wanted):
    from .native_classes import Expression
    from .native_unions import project, union_kind
    if not isinstance(node, ast.BinOp) or not isinstance(operator, OPERATORS):
        return None
    record = emitter.model.mappings.sites.get((emitter.plan.index, id(node), 'dict', 'Counter'))
    if record is None or _counter_kinds_of(left.kind) is None or _counter_kinds_of(right.kind) is None:
        return None
    record.emitted = True
    first, second, result = emitter.fresh(), emitter.fresh(), emitter.fresh()
    owner = Expression(result, record.kind)

    def with_right(left_value):
        def branch(kind, code):
            return '{' + _combine(emitter, node, operator, owner, left_value, Expression('(' + code + ')', kind)) + '}'
        return project(right.kind, second, branch) if union_kind(right.kind) else branch(right.kind, second)

    def with_left(kind, code):
        return with_right(Expression('(' + code + ')', kind))
    body = project(left.kind, first, with_left) if union_kind(left.kind) else with_left(left.kind, first)
    code = ('{let ' + first + '=(' + left.code + ').clone();let ' + second + '=(' + right.code + ').clone();let ' + result + '='
            + emitter.model.mappings._new(emitter, record) + ';' + body + ';' + result + '}')
    return Expression(emitter.coerce(Expression(code, record.kind), wanted, node), wanted)


def _counter_kinds_of(kind):
    from .native_class_mappings import mapping_kind
    from .native_types import alternatives
    kinds = alternatives(kind)
    if kinds and all(mapping_kind(item) and item.record.flavor == 'Counter' for item in kinds):
        return kinds
    return None
