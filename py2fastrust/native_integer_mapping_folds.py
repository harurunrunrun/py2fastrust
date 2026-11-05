"""Builtin integer folds over registered mapping/set storage and live views.

The caller has captured both iterable and start before this adapter runs.
The held mapping loan contains only builtin scalar addition, never source code.
"""
import ast

from .native_types import EmptyType, alternatives


def registered(model, kind):
    from .native_class_mappings import mapping_kind
    from .native_mapping_views import view_kind
    if mapping_kind(kind):
        records = model.mappings.records
        return (0 <= kind.index < len(records) and records[kind.index] is kind.record
                and kind.record.category in {'dict', 'set'})
    if view_kind(kind):
        records = model.mappings.views.records
        if not (0 <= kind.index < len(records) and records[kind.index] is kind.record):
            return False
        owners = alternatives(_shape(kind.record.source))
        return bool(owners) and all(registered(model, owner) and owner.record.category == 'dict'
                                    for owner in owners)
    return False


def _shape(cell):
    from .native_classes import shape
    return shape(cell)


def element(model, node, source):
    """A MAY family is usable only when every runtime arm has a builtin owner."""
    from .native_classes import Cell
    from .native_class_mappings import mapping_kind
    choices = alternatives(_shape(source))
    if not choices or not all(registered(model, kind) for kind in choices):
        return None
    result = Cell()
    for kind in choices:
        item = kind.record.key if mapping_kind(kind) else kind.record.element
        model.contribute(result, item, node)
    return result


def integer(kind):
    return isinstance(kind, EmptyType) or kind in {'int', 'bool', 'int_bool'}


def emit(emitter, node, source, accumulator, wanted):
    """Return a scalar-only fold body, or leave the existing iterable adapter."""
    from .native_classes import Expression, ClassUnsupported
    from .native_class_mappings import mapping_kind
    from .native_unions import project, union_kind
    choices = alternatives(source.kind)
    if not choices or not all(registered(emitter.model, kind) for kind in choices):
        return None

    def owner_body(kind, text, mode):
        owner, read, key, value = (emitter.fresh() for _ in range(4))
        item = emitter.model.mappings.views.project(emitter, kind, mode, key, value)
        if not integer(item.kind):
            raise ClassUnsupported(node, 'this sum() mapping/set element needs a non-integer addition protocol; only builtin integer and boolean elements have a closed native fold',
                                   proof='integer mapping/set sum element representation')
        if isinstance(item.kind, EmptyType):
            action = 'match ' + item.code + '{};'
        else:
            added = emitter.numeric.binary(ast.Add(),
                emitter.scalar(Expression(accumulator + '.clone()', wanted)), emitter.scalar(item), node)
            action = accumulator + '=' + emitter.coerce(added, wanted, node) + ';'
        return ('{let ' + owner + '=' + text + ';let ' + read + '=' + owner + '.borrow();'
                + 'for (' + key + ',' + value + ') in ' + read + '.entries.iter(){' + action + '}}')

    def branch(kind, text):
        if mapping_kind(kind):
            return owner_body(kind, text, 'keys')
        view = kind.record
        owner_kind = _shape(view.source)
        owner_text = '(' + text + ').source.clone()'
        body = lambda owner, code: owner_body(owner, code, view.mode)
        return project(owner_kind, owner_text, body) if union_kind(owner_kind) else body(owner_kind, owner_text)

    return (project(source.kind, source.code, branch) if union_kind(source.kind)
            else branch(source.kind, source.code)) + ';'
