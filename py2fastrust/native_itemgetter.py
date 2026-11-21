"""operator.itemgetter objects (Modules/_operator.c itemgetter_new/itemgetter_call, CPython 3.14).

``itemgetter(i)`` stores its item and returns ``obj[i]`` when called;
``itemgetter(i, j, ...)`` returns the tuple ``(obj[i], obj[j], ...)``. A call
takes exactly one positional argument. The native adapter covers integer
literal items applied to fixed-shape tuples and builtin lists, which is how the
objects are used as sort and extremum keys, and to tuples built from iterables; each creation site is its own
callable kind whose items are compile-time constants. Other items or receivers
remain positioned diagnostics.
"""
import ast
from dataclasses import dataclass

from .native_types import EMPTY, ListType, TupleSequenceType, TupleType, alternatives


@dataclass(frozen=True)
class ItemGetter:
    index: int
    items: tuple
    _native_item_getter = True
    _native_stored_reference = True
    _native_reference_cloneable = True
    _native_python_type_name = 'operator.itemgetter'

    @property
    def _native_kind_tag(self):
        return 'itemgetter_' + str(self.index)

    @property
    def rust(self):
        return 'Rc<NativeItemGetter' + str(self.index) + '>'


@dataclass
class Invocation:
    result: object
    error: str | None = None


def is_item_getter(kind):
    return getattr(kind, '_native_item_getter', False)


def _literal(node):
    negative = isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
    value = node.operand if negative else node
    if isinstance(value, ast.Constant) and type(value.value) is int:
        return -value.value if negative else value.value
    return None


def create(model, plan, node, positional, keywords, factory):
    """Analyze ``itemgetter(...)``; returns (result cell, error text or None)."""
    from .native_classes import ClassUnsupported
    if keywords:
        return factory(EMPTY), 'TypeError: itemgetter() takes no keyword arguments'
    if not positional:
        return factory(EMPTY), 'TypeError: itemgetter expected 1 argument, got 0'
    if not isinstance(node, ast.Call) or len(node.args) != len(positional) or any(isinstance(item, ast.Starred) for item in node.args):
        raise ClassUnsupported(node, 'itemgetter() items must be written as literal arguments for the native adapter',
                               proof='itemgetter constant items')
    items = tuple(_literal(item) for item in node.args)
    if any(item is None for item in items):
        raise ClassUnsupported(node, 'itemgetter() with non-integer-literal items needs a general subscript protocol over captured keys; integer literal items are implemented',
                               proof='itemgetter constant items')
    registry = getattr(model, 'item_getters', None)
    if registry is None:
        registry = model.item_getters = {}
    kind = registry.get((plan.index, id(node)))
    if kind is None:
        kind = registry[(plan.index, id(node))] = ItemGetter(len(registry), items)
    result = factory()
    model.contribute(result, model.cell_for_kind(kind), node)
    return result, None


def emit_create(emitter, node, record):
    from .native_classes import Expression
    kind = emitter.model.item_getters[(emitter.plan.index, id(node))]
    return Expression('Rc::new(NativeItemGetter' + str(kind.index) + ')', kind)


def _item_kind(model, node, receiver, item):
    from .native_classes import ClassUnsupported
    if isinstance(receiver, TupleType):
        if -len(receiver.fields) <= item < len(receiver.fields):
            return receiver.fields[item]
        return EMPTY
    if isinstance(receiver, (ListType, TupleSequenceType)):
        return receiver.element
    raise ClassUnsupported(node, 'calling an itemgetter on this value needs its __getitem__ protocol; fixed tuples and builtin lists are implemented',
                           types=(('receiver', receiver),), proof='itemgetter receiver subscript')


def analyze_call(model, plan, node, kind, positional, keywords):
    from .native_classes import Cell, ClassUnsupported, shape
    result = model.cell(plan, node, identity=('itemgetter_call', kind))
    if keywords:
        error = 'TypeError: itemgetter() takes no keyword arguments'
    elif len(positional) != 1:
        error = 'TypeError: itemgetter expected 1 argument, got ' + str(len(positional))
    else:
        error = None
    if error:
        model.contribute(result, Cell(EMPTY), node)
        return Invocation(result, error)
    receiver = shape(positional[0])
    if receiver is None:
        return Invocation(result)
    for choice in alternatives(receiver):
        if choice is None or choice is EMPTY:
            continue
        values = [_item_kind(model, node, choice, item) for item in kind.items]
        cells = [model.cell_for_kind(value) for value in values]
        value = cells[0] if len(cells) == 1 else Cell('tuple', tuple(cells))
        if any(item is EMPTY for item in values) and len(values) > 1:
            value = Cell(EMPTY)
        model.contribute(result, value, node)
    return Invocation(result)


def emit_call(emitter, node, kind, record, positional, keywords, wanted):
    from .native_classes import Expression
    from .native_class_builtins import _error
    from .native_unions import project, union_kind
    from .native import _string
    if record.error:
        return _error(emitter, node, wanted, _string(record.error) + '.to_owned()')
    argument = positional[0]

    def one(choice, code, item, holder):
        if isinstance(choice, TupleType):
            count = len(choice.fields)
            if not -count <= item < count:
                return None, emitter.at('Err::<' + emitter.rust_type(wanted) + ',String>("IndexError: tuple index out of range".to_owned())', node)
            position = item % count
            return choice.fields[position], '(' + holder + ').' + str(position) + '.clone()'
        if isinstance(choice, TupleSequenceType):
            borrow, label = '.as_slice()', 'tuple'
        else:
            if not emitter.rust_type(choice).startswith('ClassList<'):
                from .native_classes import ClassUnsupported
                raise ClassUnsupported(node, 'this list uses a specialized storage layout that the itemgetter adapter does not read', proof='itemgetter list storage')
            borrow, label = '.borrow()', 'list'
        values, length, position = emitter.fresh(), emitter.fresh(), emitter.fresh()
        missing = emitter.at('Err::<usize,String>("IndexError: ' + label + ' index out of range".to_owned())', node)
        lookup = ('{let ' + values + '=(' + holder + ')' + borrow + ';let ' + length + '=' + values + '.len() as i128;'
                  + 'let ' + position + ':usize=if (' + str(item) + '_i128)<(-' + length + ')||(' + str(item) + '_i128)>=' + length + '{' + missing + '}'
                  + 'else{((' + str(item) + '_i128)+if (' + str(item) + '_i128)<0{' + length + '}else{0}) as usize};'
                  + values + '[' + position + '].clone()}')
        return choice.element, lookup

    def branch(choice, code):
        holder = emitter.fresh()
        parts = []
        for item in kind.items:
            field, value = one(choice, code, item, holder)
            if field is None:
                return '{let ' + holder + '=(' + code + ').clone();' + value + '}'
            parts.append(Expression(value, field))
        if len(parts) == 1:
            produced = parts[0]
        else:
            produced = Expression('(' + ''.join(part.code + ',' for part in parts) + ')', TupleType(tuple(part.kind for part in parts)))
        return '{let ' + holder + '=(' + code + ').clone();' + emitter.coerce(produced, wanted, node) + '}'
    code = project(argument.kind, argument.code, branch) if union_kind(argument.kind) else branch(argument.kind, argument.code)
    return Expression(code, wanted)


def show(kind):
    from .native import _string
    return _string('operator.itemgetter(' + ', '.join(repr(item) for item in kind.items) + ')') + '.to_owned()'


def runtime(model):
    return '\n'.join('struct NativeItemGetter' + str(kind.index) + ';' for kind in sorted(getattr(model, 'item_getters', {}).values(), key=lambda kind: kind.index))
