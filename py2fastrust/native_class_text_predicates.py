"""str/bytes is*() predicates in framed programs, sharing the pinned Unicode helpers.

The receiver is evaluated once; an argument-free call returns the same result
as the ordinary path's helper for the configured string profile (ASCII, or the
pinned Unicode 16.0.0 property tables in Unicode mode).
"""
from .native_text_predicates import STR_PREDICATES, BYTES_PREDICATES


def _kind(receiver_kind, name):
    from .native_classes import domain
    tag = domain(receiver_kind)
    if tag == 'str' and name in STR_PREDICATES or tag == 'bytes' and name in BYTES_PREDICATES:
        return tag
    return None


def analyze(model, plan, node, receiver, arguments, keywords):
    from .native_classes import shape
    if arguments or keywords:
        return None
    kind = _kind(shape(receiver), node.func.attr)
    if kind is None:
        return None
    requests = getattr(model, 'framed_text_predicates', None)
    if requests is None:
        requests = model.framed_text_predicates = set()
    requests.add((kind, node.func.attr, False))
    return model.cell(plan, node, 'bool')


def emit(emitter, node, receiver, arguments, keywords, wanted):
    from .native_classes import Expression
    if arguments or keywords:
        return None
    name = node.func.attr
    kind = _kind(receiver.kind, name)
    if kind is None or (kind, name, False) not in getattr(emitter.model, 'framed_text_predicates', ()):
        return None
    view = '.as_str()' if kind == 'str' else '.as_slice()'
    code = 'native_' + kind + '_' + name + '(({0}){1})'.format(receiver.code, view)
    return Expression(emitter.coerce(Expression(code, 'bool'), wanted, node), wanted)


def runtime(model):
    from .native_text_predicates import render_helpers
    requests = getattr(model, 'framed_text_predicates', None)
    return render_helpers(requests, model.string_mode) if requests else ''
