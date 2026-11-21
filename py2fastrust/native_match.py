"""match statements with value, singleton, capture, wildcard and or-patterns.

The subject is evaluated once. Cases are tried in order: a value pattern
compares with ==, a singleton pattern with ``is``, a capture binds the subject,
and an or-pattern tries its alternatives left to right. A capture made before a
failing guard stays bound, as in CPython. Sequence, mapping and class patterns
remain positioned diagnostics.
"""
import ast


def _unsupported(node, what):
    from .native_classes import ClassUnsupported
    return ClassUnsupported(node, what + ' patterns need structural extraction and binding commits that are not implemented; value, singleton, capture, wildcard and or-patterns are',
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
    raise _unsupported(pattern, type(pattern).__name__.replace('Match', '').lower() or 'these')


def requires_frames(unit):
    return any(isinstance(node, ast.Match) for node in ast.walk(unit.tree))


def analyze(model, plan, node, environment):
    from .native_classes import Environment
    subject = model.expression(plan, node.subject, environment)
    sites = getattr(model, 'native_match_sites', None)
    if sites is None:
        sites = model.native_match_sites = {}
    sites[(plan.index, id(node))] = subject
    current = Environment(environment)
    outcome = None
    for case in node.cases:
        _check(case.pattern)
        attempt = Environment(current)
        for item in ast.walk(case.pattern):
            if isinstance(item, ast.MatchValue):
                model.expression(plan, item.value, attempt)
        for item in ast.walk(case.pattern):
            if isinstance(item, ast.MatchAs) and item.name is not None:
                model.bind_name(plan, item, subject, attempt)
        if case.guard is not None:
            model.condition(plan, case.guard, attempt)
        finished = model.block(plan, case.body, Environment(attempt))
        outcome = model.join(outcome, finished, node, 'match_case_exit')
        # Later cases see bindings made by this case's pattern before a failed guard.
        current = model.join(current, attempt, node, 'match_case_fallthrough')
    return model.join(outcome, current, node, 'match_exit')


def _test(emitter, pattern, subject):
    from .native_classes import Expression
    if isinstance(pattern, ast.MatchValue):
        before, value = emitter.capture(emitter.expression(pattern.value))
        return '{' + before + emitter.comparison(ast.Eq(), Expression(subject.code + '.clone()', subject.kind), value, pattern) + '}'
    if isinstance(pattern, ast.MatchSingleton):
        constant = {None: Expression('()', 'none'), True: Expression('true', 'bool'), False: Expression('false', 'bool')}[pattern.value]
        return emitter.comparison(ast.Is(), Expression(subject.code + '.clone()', subject.kind), constant, pattern)
    if isinstance(pattern, ast.MatchAs):
        return 'true' if pattern.pattern is None else _test(emitter, pattern.pattern, subject)
    if isinstance(pattern, ast.MatchOr):
        return '(' + '||'.join('(' + _test(emitter, alternative, subject) + ')' for alternative in pattern.patterns) + ')'
    raise _unsupported(pattern, type(pattern).__name__)


def emit(emitter, node):
    from .native_classes import Expression
    before, subject = emitter.capture(emitter.expression(node.subject))
    holder, matched = emitter.fresh(), emitter.fresh()
    code = before + 'let ' + holder + '=' + subject.code + ';let mut ' + matched + '=false;'
    value = Expression(holder, subject.kind)
    for case in node.cases:
        binds = ''.join(emitter.assign_name(item, Expression(holder + '.clone()', subject.kind))
                        for item in ast.walk(case.pattern) if isinstance(item, ast.MatchAs) and item.name is not None)
        guard = 'true' if case.guard is None else emitter.truth(emitter.expression(case.guard), case.guard)
        body = emitter.statements(case.body)
        code += ('if !' + matched + '{if ' + _test(emitter, case.pattern, value) + '{' + binds + 'if ' + guard + '{'
                 + matched + '=true;' + body + '}}}')
    return '{' + code + '}'
