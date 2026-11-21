"""copy.copy and copy.deepcopy for builtin lists, tuples and immutable scalars (Lib/copy.py, 3.14).

Immutable values (int, bool, float, None, str, bytes) are returned as they are.
copy.copy of a list builds a new list holding the same element objects.
copy.deepcopy keeps a memo keyed by object identity, as CPython does, so a list
reached twice inside the copied structure is copied once and stays shared in
the result, and a self-reference stays a self-reference. Tuples are copied
field by field. Other containers and objects remain positioned diagnostics.
"""
from .native_types import ListType, TupleType, TupleSequenceType, alternatives

NAMES = frozenset({'copy', 'deepcopy'})
IMMUTABLE = frozenset({'int', 'bool', 'int_bool', 'float', 'none', 'str', 'bytes'})


def _supported(kind, deep):
    from .native_unions import union_kind
    if kind in IMMUTABLE:
        return True
    if union_kind(kind):
        return all(part in IMMUTABLE for part in alternatives(kind))
    if isinstance(kind, TupleType):
        return all(_supported(field, deep) for field in kind.fields)
    if isinstance(kind, TupleSequenceType):
        return _supported(kind.element, deep)
    if isinstance(kind, ListType):
        return not deep or _supported(kind.element, deep)
    return False


class CopyAdapter:
    NAMES = NAMES

    @staticmethod
    def analyze(model, plan, node, identity, call_arguments, arguments, keywords, environment, *, factory):
        from .native_classes import ClassUnsupported, shape
        if keywords or len(arguments) != 1:
            raise ClassUnsupported(node, f'copy.{identity.name}() with a memo or keyword arguments is not implemented; the one-argument form is',
                                   proof='copy module argument binding')
        result = factory()
        model.contribute(result, arguments[0], node)
        kind = shape(arguments[0])
        if model.final and kind is not None and not _supported(kind, identity.name == 'deepcopy'):
            raise ClassUnsupported(node, f'copy.{identity.name}() of this value needs its __reduce_ex__/__deepcopy__ protocol; builtin lists, tuples and immutable scalars are implemented',
                                   types=(('value', kind),), proof='copy module reduction protocol')
        from types import SimpleNamespace
        return SimpleNamespace(result=result)

    @staticmethod
    def emit(emitter, node, identity, record, arguments, keywords):
        from .native_classes import Expression, ClassUnsupported
        value = arguments[0]
        wanted = emitter.kind(node)
        before, source = emitter.capture(value)
        if identity.name == 'copy':
            code = _shallow(emitter, node, source.kind, source.code)
        else:
            memo = emitter.fresh()
            code = ('{let mut ' + memo + ':std::collections::HashMap<usize,Box<dyn std::any::Any>>=std::collections::HashMap::new();'
                    + _deep(emitter, node, source.kind, source.code, memo) + '}')
        if code is None:
            raise ClassUnsupported(node, 'this copied value has no builtin list/tuple storage representation', proof='copy module storage')
        return Expression(emitter.coerce(Expression('{' + before + code + '}', source.kind), wanted, node), wanted)


def _list_type(emitter, kind, node):
    from .native_classes import ClassUnsupported
    rust = emitter.rust_type(kind)
    if not rust.startswith('ClassList<'):
        raise ClassUnsupported(node, 'this list uses a specialized storage layout that the copy adapter does not rebuild', proof='copy module list storage')
    return rust


def _shallow(emitter, node, kind, code):
    if isinstance(kind, ListType):
        _list_type(emitter, kind, node)
        values = emitter.fresh()
        return '{let ' + values + '=(' + code + ').borrow().clone();class_list(' + values + ')}'
    return '(' + code + ').clone()'


def _deep(emitter, node, kind, code, memo):
    from .native_types import tuple_field
    if not isinstance(kind, (ListType, TupleType, TupleSequenceType)):
        return '(' + code + ').clone()'
    if isinstance(kind, TupleType):
        holder = emitter.fresh()
        fields = [_deep(emitter, node, field, tuple_field(holder, index) + '.clone()', memo) for index, field in enumerate(kind.fields)]
        return '{let ' + holder + '=(' + code + ').clone();(' + ''.join(field + ',' for field in fields) + ')}'
    if isinstance(kind, TupleSequenceType):
        holder, item = emitter.fresh(), emitter.fresh()
        emitter.model.materialized_tuple = True
        return ('{let ' + holder + '=(' + code + ').clone();let mut values=Vec::new();for ' + item + ' in ' + holder + '.iter().cloned(){values.push('
                + _deep(emitter, node, kind.element, item, memo) + ');}NativeTuple::from_vec(values)}')
    rust = _list_type(emitter, kind, node)
    source, key, target, items, item = (emitter.fresh() for _ in range(5))
    return ('{let ' + source + '=(' + code + ').clone();let ' + key + '=Rc::as_ptr(&' + source + ') as *const () as usize;'
            + 'if let Some(found)=' + memo + '.get(&' + key + '){found.downcast_ref::<' + rust + '>().expect("deepcopy memo type").clone()}'
            + 'else{let ' + target + ':' + rust + '=class_list(Vec::new());' + memo + '.insert(' + key + ',Box::new(' + target + '.clone()));'
            + 'let ' + items + '=' + source + '.borrow().clone();' + target + '.borrow_mut().reserve(' + items + '.len());'
            + 'for ' + item + ' in ' + items + '{let value=' + _deep(emitter, node, kind.element, item, memo) + ';' + target + '.borrow_mut().push(value);}'
            + target + '}}')
