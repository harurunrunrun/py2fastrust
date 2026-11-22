"""match statements with value, singleton, capture, wildcard, or- and sequence patterns.

The subject is evaluated once. Cases are tried in order: a value pattern
compares with ==, a singleton pattern with ``is``, a capture binds the matched
value, and an or-pattern tries its alternatives left to right. A sequence
pattern (Python/ceval.c MATCH_SEQUENCE, CPython 3.14) matches a list or tuple,
never str/bytes or non-sequence values; it checks the length (exactly, or at
least the fixed part with one star) and then its subpatterns left to right.
A star capture binds a new list of the middle items. Names are bound only after
the whole pattern matched, and a capture made before a failing guard stays
bound, as in CPython. Mapping and class patterns, and sequence patterns on
values whose type is a union, remain positioned diagnostics.
"""
import ast


def _unsupported(node, what):
    from .native_classes import ClassUnsupported
    return ClassUnsupported(node, what + ' patterns need structural extraction and binding commits that are not implemented; value, singleton, capture, wildcard, or- and sequence patterns are',
                            operation='match pattern', proof='native structural pattern matching')


def _check(pattern, captures_allowed=True):
    if isinstance(pattern, (ast.MatchValue, ast.MatchSingleton)):
        return
    if isinstance(pattern, ast.MatchAs):
        if pattern.pattern is not None:
            _check(pattern.pattern, captures_allowed)
        if pattern.name is not None and not captures_allowed:
            raise _unsupported(pattern, 'capturing or-alternative')
        return
    if isinstance(pattern, ast.MatchOr):
        for alternative in pattern.patterns:
            _check(alternative, False)
        return
    if isinstance(pattern, ast.MatchSequence):
        for item in pattern.patterns:
            if isinstance(item, ast.MatchStar):
                if item.name is not None and not captures_allowed:
                    raise _unsupported(item, 'capturing or-alternative')
            else:
                _check(item, captures_allowed)
        return
    raise _unsupported(pattern, type(pattern).__name__.replace('Match', '').lower() or 'these')


def requires_frames(unit):
    return any(isinstance(node, ast.Match) for node in ast.walk(unit.tree))


_NEVER_SEQUENCE = frozenset({'int', 'bool', 'int_bool', 'float', 'none', 'str', 'bytes', 'complex'})


def _layout(model, pattern, kind):
    """(item kinds, star list kind or None) when ``pattern`` can match ``kind``; None when it never can."""
    from .native_classes import InstanceType
    from .native_types import ListType, TupleSequenceType, TupleType, alternatives
    if kind is None:return None
    if len(alternatives(kind)) > 1:
        raise _unsupported(pattern, 'sequence patterns on a value of union type; this sequence')
    star = next((index for index, item in enumerate(pattern.patterns) if isinstance(item, ast.MatchStar)), None)
    fixed = len(pattern.patterns) - (star is not None)
    if isinstance(kind, TupleType):
        count = len(kind.fields)
        if count < fixed or star is None and count != fixed:return None
        if star is None:return list(kind.fields), None
        after = fixed - star
        rest = kind.fields[star:count - after]
        rest_kind = None
        if pattern.patterns[star].name is not None:
            if not rest or any(item != rest[0] for item in rest):
                raise _unsupported(pattern.patterns[star], 'star captures of empty or mixed tuple slices; this')
            rest_kind = ListType(rest[0])
        return list(kind.fields[:star]) + list(kind.fields[count - after:]), rest_kind
    if isinstance(kind, (ListType, TupleSequenceType)):
        return [kind.element] * fixed, ListType(kind.element)
    if kind in _NEVER_SEQUENCE or isinstance(kind, InstanceType) or getattr(kind, '_native_class_mapping', False):
        return None
    raise _unsupported(pattern, 'sequence patterns on this value type; this sequence')


def _visit(model, plan, pattern, kind, subject, attempt, captures, top):
    """Analyze value expressions and bind captures of ``pattern`` matched against ``kind``."""
    if isinstance(pattern, ast.MatchValue):
        model.expression(plan, pattern.value, attempt)
    elif isinstance(pattern, ast.MatchAs):
        if pattern.pattern is not None:
            _visit(model, plan, pattern.pattern, kind, subject, attempt, captures, top)
        if pattern.name is not None:
            cell = subject if top else model.cell_for_kind(kind)
            captures[id(pattern)] = kind
            model.bind_name(plan, pattern, cell, attempt)
    elif isinstance(pattern, ast.MatchOr):
        for alternative in pattern.patterns:
            _visit(model, plan, alternative, kind, subject, attempt, captures, top)
    elif isinstance(pattern, ast.MatchSequence):
        layout = _layout(model, pattern, kind)
        if layout is None:
            # The pattern never matches this value; its subpatterns are never tried.
            return
        kinds, rest = layout
        position = 0
        for item in pattern.patterns:
            if isinstance(item, ast.MatchStar):
                if item.name is not None:
                    captures[id(item)] = rest
                    model.bind_name(plan, item, model.cell_for_kind(rest), attempt)
                continue
            _visit(model, plan, item, kinds[position], subject, attempt, captures, False)
            position += 1


def analyze(model, plan, node, environment):
    from .native_classes import Environment, shape
    subject = model.expression(plan, node.subject, environment)
    sites = getattr(model, 'native_match_sites', None)
    if sites is None:
        sites = model.native_match_sites = {}
    sites[(plan.index, id(node))] = subject
    if any(isinstance(item, ast.MatchSequence) for case in node.cases for item in ast.walk(case.pattern)) and shape(subject) is None:
        if not model.final:
            from .native_guard_flow import AnalysisPending
            raise AnalysisPending()
    captures = model.__dict__.setdefault('native_match_captures', {})
    current = Environment(environment)
    outcome = None
    for case in node.cases:
        _check(case.pattern)
        attempt = Environment(current)
        _visit(model, plan, case.pattern, shape(subject), subject, attempt, captures, True)
        if case.guard is not None:
            model.condition(plan, case.guard, attempt)
        finished = model.block(plan, case.body, Environment(attempt))
        outcome = model.join(outcome, finished, node, 'match_case_exit')
        # Later cases see bindings made by this case's pattern before a failed guard.
        current = model.join(current, attempt, node, 'match_case_fallthrough')
    return model.join(outcome, current, node, 'match_exit')


def _items(emitter, pattern, value):
    """(length test, item expression factory, star expression factory) for a list or tuple value."""
    from .native_classes import Expression
    from .native_types import ListType, TupleSequenceType, TupleType
    kind = value.kind
    star = next((index for index, item in enumerate(pattern.patterns) if isinstance(item, ast.MatchStar)), None)
    fixed = len(pattern.patterns) - (star is not None)
    if isinstance(kind, TupleType):
        count = len(kind.fields)
        after = fixed - (star if star is not None else fixed)
        def item(position):
            index = position if star is None or position < star else count - (fixed - position)
            return Expression('(' + value.code + ').' + str(index) + '.clone()', kind.fields[index])
        def rest():
            values = ['(' + value.code + ').' + str(index) + '.clone()' for index in range(star, count - after)]
            return 'class_list(vec![' + ','.join(values) + '])'
        return 'true', item, rest
    if isinstance(kind, ListType):
        if not emitter.rust_type(kind).startswith('ClassList<'):
            raise _unsupported(pattern, 'sequence patterns on this specialized list storage; this sequence')
        borrow = '.borrow()'
    else:
        borrow = '.as_slice()'
    length = '(' + value.code + ')' + borrow + '.len()'
    test = length + ('==' if star is None else '>=') + str(fixed)
    def item(position):
        if star is None or position < star:
            index = str(position)
        else:
            index = length + '-' + str(fixed - position)
        return Expression('(' + value.code + ')' + borrow + '[' + index + '].clone()', kind.element)
    def rest():
        return 'class_list((' + value.code + ')' + borrow + '[' + str(star) + '..' + length + '-' + str(fixed - star) + '].to_vec())'
    return test, item, rest


def _match(emitter, pattern, value, binds):
    """Rust test for ``pattern`` against ``value``; appends capture stores to ``binds``."""
    from .native_classes import Expression
    from .native_types import ListType
    if isinstance(pattern, ast.MatchValue):
        before, constant = emitter.capture(emitter.expression(pattern.value))
        return '{' + before + emitter.comparison(ast.Eq(), Expression(value.code + '.clone()', value.kind), constant, pattern) + '}'
    if isinstance(pattern, ast.MatchSingleton):
        constant = {None: Expression('()', 'none'), True: Expression('true', 'bool'), False: Expression('false', 'bool')}[pattern.value]
        return emitter.comparison(ast.Is(), Expression(value.code + '.clone()', value.kind), constant, pattern)
    if isinstance(pattern, ast.MatchAs):
        test = 'true' if pattern.pattern is None else _match(emitter, pattern.pattern, value, binds)
        if pattern.name is not None:
            binds.append(emitter.assign_name(pattern, Expression(value.code + '.clone()', value.kind)))
        return test
    if isinstance(pattern, ast.MatchOr):
        return '(' + '||'.join('(' + _match(emitter, alternative, value, []) + ')' for alternative in pattern.patterns) + ')'
    if isinstance(pattern, ast.MatchSequence):
        layout = _layout(emitter.model, pattern, value.kind)
        if layout is None:return 'false'
        test, item, rest = _items(emitter, pattern, value)
        parts = [test]
        position = 0
        for sub in pattern.patterns:
            if isinstance(sub, ast.MatchStar):
                if sub.name is not None:
                    binds.append(emitter.assign_name(sub, Expression(rest(), layout[1])))
                continue
            # Item reads are guarded by the length test before them; captures
            # read the item again after the whole pattern matched.
            check = _match(emitter, sub, item(position), binds)
            if check != 'true':
                parts.append(check)
            position += 1
        return '(' + '&&'.join(parts) + ')'
    raise _unsupported(pattern, type(pattern).__name__)


def emit(emitter, node):
    from .native_classes import Expression
    before, subject = emitter.capture(emitter.expression(node.subject))
    holder, matched = emitter.fresh(), emitter.fresh()
    code = before + 'let ' + holder + '=' + subject.code + ';let mut ' + matched + '=false;'
    value = Expression(holder, subject.kind)
    for case in node.cases:
        binds = []
        test = _match(emitter, case.pattern, value, binds)
        guard = 'true' if case.guard is None else emitter.truth(emitter.expression(case.guard), case.guard)
        body = emitter.statements(case.body)
        code += ('if !' + matched + '{if ' + test + '{' + ''.join(binds) + 'if ' + guard + '{'
                 + matched + '=true;' + body + '}}}')
    return '{' + code + '}'
