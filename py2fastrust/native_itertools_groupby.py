"""itertools.groupby without a key function, following Modules/itertoolsmodule.c.

The outer state keeps tgtkey, currkey, currvalue and the identity of the only
live grouper (currgrouper). Advancing the outer iterator skips the rest of the
current group; an older grouper then yields nothing. Keys compare with the
same native equality as ``==`` on the element type.
"""
from .native_types import EmptyType


def bind(positional, keywords):
    keywords = list(keywords)
    values = dict(zip(('iterable', 'key'), positional))
    if len(positional) > 2:
        return None, f'TypeError: groupby() takes at most 2 arguments ({len(positional)} given)'
    for name, value in keywords:
        if name not in {'iterable', 'key'}:
            return None, f"TypeError: groupby() got an unexpected keyword argument '{name}'"
        if name in values:
            return None, f"TypeError: argument for groupby() given by name ('{name}') and position ({1 if name == 'iterable' else 2})"
        values[name] = value
    if 'iterable' not in values:
        return None, "TypeError: groupby() missing required argument 'iterable' (pos 1)"
    return (values['iterable'], values.get('key')), None


def analyze(model, plan, node, positional, keywords, environment, *, factory):
    from .native_classes import Cell, ClassUnsupported, shape
    from .native_itertools import ToolCall
    values, error = bind(positional, keywords)
    if error:
        return ToolCall(factory('none'), error=error)
    iterable, key = values
    if key is not None and shape(key) != 'none':
        if shape(key) is None and not model.final:
            return ToolCall(factory())
        raise ClassUnsupported(node, 'groupby() with a key function needs a captured per-element callback and its result-key equality; only the identity key is implemented',
                               types=(('key', shape(key)),), proof='groupby key callback protocol')
    registry = model.iterators
    from .native_iterator_hints import ABSENT
    outer = registry._record(plan, node, 'itertools_groupby')
    outer.hint_protocol = ABSENT
    outer.adapter = GroupbyState
    outer.tool = 'groupby'
    outer.input_types = (registry.source(plan, node, iterable, ('itertools', 'groupby', 0), environment=environment),)
    item = registry.item(outer.input_types[0])
    grouper = registry._record(plan, node, 'itertools_grouper')
    grouper.hint_protocol = ABSENT
    grouper.adapter = GrouperState
    grouper.tool = 'grouper'
    grouper.parent = outer
    outer.grouper = grouper
    registry._contribute(grouper.element, item, node)
    registry._contribute(outer.element, Cell('tuple', (item, Cell(grouper.kind))), node)
    return ToolCall(factory(outer.kind), outer)


def emit(emitter, node, call, positional, keywords):
    from .native_classes import Expression
    values, error = bind(positional, keywords)
    assert error is None
    record = call.iterator
    record.emitted = True
    record.grouper.emitted = True
    setup, cursor = emitter.capture(emitter.model.iterators.construct(emitter, node, values[0], kind=record.input_types[0]))
    state = ('Rc::new(RefCell::new(ClassIteratorState_' + str(record.index) + '{source:Some(' + cursor.code
             + '),tgtkey:None,currkey:None,currvalue:None,current:0,issued:0}))')
    return Expression('{' + setup + state + '}', record.kind)


def _key_equal(emitter, node, kind, left, right):
    import ast
    from .native_classes import Expression
    if isinstance(kind, EmptyType):
        return 'match ' + left + '{}'
    return emitter.comparison(ast.Eq(), Expression(left + '.clone()', kind), Expression(right + '.clone()', kind), node)


def _step(registry, emitter, node, outer, handle, active, label):
    """groupby_step: pull one value; on exhaustion leave the labeled block with None."""
    from .native_classes import Expression
    from .native_iterator_stop_policy import cleanup_pull
    source, value = emitter.fresh(), emitter.fresh()
    nested = registry.pull(emitter, node, Expression(source, outer.input_types[0]), active + (outer.index,))
    cleanup = '{' + handle + '.borrow_mut().source=None;}'
    nested = cleanup_pull(emitter, nested, cleanup)
    return ('let Some(' + source + ')=({' + handle + '.borrow().source.clone()})else{break \'' + label + ' None;};'
            + 'let Some(' + value + ')=(' + nested.code + ')else{' + cleanup + 'break \'' + label + ' None;};'
            + '{let mut state=' + handle + '.borrow_mut();state.currkey=Some(' + value + '.clone());state.currvalue=Some(' + value + ');}')


class GroupbyState:
    @staticmethod
    def owned(record):
        return tuple(record.input_types)

    @staticmethod
    def demand(registry, plan, node, record, environment, active):
        from .native_classes import Cell
        registry.demand(plan, node, Cell(record.input_types[0]), environment, active + (record.index,))
        return record.element

    @staticmethod
    def may_call(registry, record, seen):
        return registry.may_call(record.input_types[0], seen | {record.index})

    @staticmethod
    def fields(emitter, record):
        from .native_classes import shape
        item = emitter.rust_type(shape(emitter.model.iterators.item(record.input_types[0])))
        return (f'source:Option<{emitter.rust_type(record.input_types[0])}>,tgtkey:Option<{item}>,'
                f'currkey:Option<{item}>,currvalue:Option<{item}>,current:usize,issued:usize')

    @staticmethod
    def pull(registry, emitter, node, value, active):
        from .native_classes import Expression, shape
        record = value.kind.record
        item_kind = shape(registry.item(record.input_types[0]))
        handle, current, target, label = emitter.fresh(), emitter.fresh(), emitter.fresh(), 'groupby_' + emitter.fresh()
        equal = _key_equal(emitter, node, item_kind, target, current)
        # groupby_next: clear currgrouper, then skip to the next key.
        code = ("'" + label + ':{let ' + handle + '=' + value.code + '.clone();' + handle + '.borrow_mut().current=0;'
                + 'loop{let (' + current + ',' + target + ')={let state=' + handle + '.borrow();(state.currkey.clone(),state.tgtkey.clone())};'
                + 'if let Some(' + current + ')=' + current + '{match ' + target + '{None=>break,Some(' + target + ')=>if !(' + equal + '){break;}}}'
                + _step(registry, emitter, node, record, handle, active, label) + '}'
                + '{let mut state=' + handle + '.borrow_mut();let key=state.currkey.clone().unwrap();state.tgtkey=Some(key.clone());'
                + 'state.issued+=1;state.current=state.issued;let id=state.issued;drop(state);'
                + 'Some((key.clone(),Rc::new(RefCell::new(ClassIteratorState_' + str(record.grouper.index)
                + '{parent:' + handle + '.clone(),id,tgtkey:key}))))}}')
        return Expression(code, shape(record.element))


class GrouperState:
    @staticmethod
    def owned(record):
        return (record.parent.kind,)

    @staticmethod
    def demand(registry, plan, node, record, environment, active):
        return record.element

    @staticmethod
    def may_call(registry, record, seen):
        return GroupbyState.may_call(registry, record.parent, seen | {record.index})

    @staticmethod
    def fields(emitter, record):
        from .native_classes import shape
        return f'parent:ClassIterator_{record.parent.index},id:usize,tgtkey:{emitter.rust_type(shape(record.element))}'

    @staticmethod
    def pull(registry, emitter, node, value, active):
        from .native_classes import Expression, shape
        record = value.kind.record
        outer = record.parent
        kind = shape(record.element)
        parent, target, current, label = emitter.fresh(), emitter.fresh(), emitter.fresh(), 'grouper_' + emitter.fresh()
        equal = _key_equal(emitter, node, kind, target, current)
        # _grouper_next: only the current grouper reads; fetch on demand,
        # then return currvalue while its key still equals this group's key.
        code = ("'" + label + ':{let (' + parent + ',' + target + ')={let state=' + value.code + '.borrow();'
                + 'if state.parent.borrow().current!=state.id{break \'' + label + ' None;}(state.parent.clone(),state.tgtkey.clone())};'
                + 'if ' + parent + '.borrow().currvalue.is_none(){' + _step(registry, emitter, node, outer, parent, active + (record.index,), label) + '}'
                + 'let ' + current + '=' + parent + '.borrow().currkey.clone().unwrap();'
                + 'if !(' + equal + '){break \'' + label + ' None;}let taken=' + parent + '.borrow_mut().currvalue.take();taken}')
        return Expression(code, kind)
