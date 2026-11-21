"""itertools.groupby, following Modules/itertoolsmodule.c.

The outer state keeps tgtkey, currkey, currvalue and the identity of the only
live grouper (currgrouper). Advancing the outer iterator skips the rest of the
current group; an older grouper then yields nothing. groupby_step calls the key
function once per pulled element (identity when it is None); keys compare with
the same native equality as ``==`` on the key type.
"""
from .call_semantics import Argument, CallArguments
from .native_types import EmptyType, alternatives


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
    from .native_classes import Cell
    from .native_itertools import ToolCall
    values, error = bind(positional, keywords)
    if error:
        return ToolCall(factory('none'), error=error)
    iterable, key = values
    registry = model.iterators
    from .native_iterator_hints import ABSENT
    outer = registry._record(plan, node, 'itertools_groupby')
    outer.hint_protocol = ABSENT
    outer.adapter = GroupbyState
    outer.tool = 'groupby'
    if outer.callback is None:
        outer.callback = Cell()
    if not hasattr(outer, 'keys'):
        outer.keys = Cell()
    registry._contribute(outer.callback, key if key is not None else Cell('none'), node)
    outer.input_types = (registry.source(plan, node, iterable, ('itertools', 'groupby', 0), environment=environment),)
    item = registry.item(outer.input_types[0])
    if key is None or 'none' in alternatives(shape_of(key)):
        registry._contribute(outer.keys, item, node)
    grouper = registry._record(plan, node, 'itertools_grouper')
    grouper.hint_protocol = ABSENT
    grouper.adapter = GrouperState
    grouper.tool = 'grouper'
    grouper.parent = outer
    outer.grouper = grouper
    registry._contribute(grouper.element, item, node)
    registry._contribute(outer.element, Cell('tuple', (outer.keys, Cell(grouper.kind))), node)
    return ToolCall(factory(outer.kind), outer)


def emit(emitter, node, call, positional, keywords):
    from .native_classes import Expression
    values, error = bind(positional, keywords)
    assert error is None
    record = call.iterator
    record.emitted = True
    record.grouper.emitted = True
    setup, cursor = emitter.capture(emitter.model.iterators.construct(emitter, node, values[0], kind=record.input_types[0]))
    callback = values[1] if values[1] is not None else Expression('()', 'none')
    before, callback = emitter.capture(callback)
    state = ('Rc::new(RefCell::new(ClassIteratorState_' + str(record.index) + '{source:Some(' + cursor.code
             + '),callback:' + callback.code + ',tgtkey:None,currkey:None,currvalue:None,current:0,issued:0}))')
    return Expression('{' + setup + before + state + '}', record.kind)


def shape_of(cell):
    from .native_classes import shape
    return shape(cell)


def _key_equal(emitter, node, kind, left, right):
    import ast
    from .native_classes import Expression
    if isinstance(kind, EmptyType):
        return 'match ' + left + '{}'
    return emitter.comparison(ast.Eq(), Expression(left + '.clone()', kind), Expression(right + '.clone()', kind), node)


def _step(registry, emitter, node, outer, handle, active, label):
    """groupby_step: pull one value; on exhaustion leave the labeled block with None."""
    from .native_classes import ClassUnsupported, Expression, shape
    from .native_iterator_stop_policy import cleanup_pull
    from .native_unions import project, union_kind
    from .native_aot_callables import emit_values
    source, value, key, callback = emitter.fresh(), emitter.fresh(), emitter.fresh(), emitter.fresh()
    nested = registry.pull(emitter, node, Expression(source, outer.input_types[0]), active + (outer.index,))
    cleanup = '{' + handle + '.borrow_mut().source=None;}'
    nested = cleanup_pull(emitter, nested, cleanup)
    wanted = shape(outer.keys)
    item = shape(registry.item(outer.input_types[0]))

    def branch(kind, code):
        if kind == 'none':
            return emitter.coerce(Expression(value + '.clone()', item), wanted, node)
        site = outer.demands.get((emitter.plan.index, id(node), kind))
        if site is None:
            raise ClassUnsupported(node, 'the deferred groupby key callback has no matching typed demand proof',
                                   proof='deferred groupby key callback demand site')
        return emit_values(emitter, node, site, Expression('(' + code + ').clone()', kind), [Expression(value + '.clone()', item)], [], wanted).code
    kind = shape(outer.callback)
    computed = project(kind, callback, branch) if union_kind(kind) else branch(kind, callback)
    return ('let Some(' + source + ')=({' + handle + '.borrow().source.clone()})else{break \'' + label + ' None;};'
            + 'let Some(' + value + ')=(' + nested.code + ')else{' + cleanup + 'break \'' + label + ' None;};'
            + 'let ' + callback + '={' + handle + '.borrow().callback.clone()};let ' + key + '=' + computed + ';'
            + '{let mut state=' + handle + '.borrow_mut();state.currkey=Some(' + key + ');state.currvalue=Some(' + value + ');}')


def _demand_key(registry, plan, node, outer, item, environment):
    """Analyze the key callback for one pull site; identity keys are the elements."""
    from .native_classes import Environment, shape
    from .native_aot_callables import analyze_values
    if isinstance(shape(item), EmptyType) or shape(item) is None:
        return
    model = registry.model
    for kind in alternatives(shape(outer.callback)):
        if kind is None or kind == 'none':
            continue
        inside = Environment(environment)
        metadata = CallArguments((Argument(outer.node),), ())
        site = analyze_values(model.callable_cells, plan, node, model.cell_for_kind(kind), metadata, [item], [], inside,
                              identity=('groupby_key', outer.index, kind))
        outer.demands[(plan.index, id(node), kind)] = site
        model.replace_environment(environment, model.join(environment, inside, node, 'groupby_key'))
        registry._contribute(outer.keys, site.result, node)


class GroupbyState:
    @staticmethod
    def owned(record):
        from .native_classes import shape
        return (*record.input_types, shape(record.callback), shape(record.keys))

    @staticmethod
    def demand(registry, plan, node, record, environment, active):
        from .native_classes import Cell
        item = registry.demand(plan, node, Cell(record.input_types[0]), environment, active + (record.index,))
        _demand_key(registry, plan, node, record, item, environment)
        return record.element

    @staticmethod
    def may_call(registry, record, seen):
        from .native_classes import shape
        return shape(record.callback) != 'none' or registry.may_call(record.input_types[0], seen | {record.index})

    @staticmethod
    def fields(emitter, record):
        from .native_classes import shape
        item = emitter.rust_type(shape(emitter.model.iterators.item(record.input_types[0])))
        key = emitter.rust_type(shape(record.keys))
        return (f'source:Option<{emitter.rust_type(record.input_types[0])}>,callback:{emitter.rust_type(shape(record.callback))},'
                f'tgtkey:Option<{key}>,currkey:Option<{key}>,currvalue:Option<{item}>,current:usize,issued:usize')

    @staticmethod
    def pull(registry, emitter, node, value, active):
        from .native_classes import Expression, shape
        record = value.kind.record
        item_kind = shape(record.keys)
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
        GroupbyState.demand(registry, plan, node, record.parent, environment, active)
        return record.element

    @staticmethod
    def may_call(registry, record, seen):
        return GroupbyState.may_call(registry, record.parent, seen | {record.index})

    @staticmethod
    def fields(emitter, record):
        from .native_classes import shape
        return f'parent:ClassIterator_{record.parent.index},id:usize,tgtkey:{emitter.rust_type(shape(record.parent.keys))}'

    @staticmethod
    def pull(registry, emitter, node, value, active):
        from .native_classes import Expression, shape
        record = value.kind.record
        outer = record.parent
        kind = shape(outer.keys)
        parent, target, current, label = emitter.fresh(), emitter.fresh(), emitter.fresh(), 'grouper_' + emitter.fresh()
        equal = _key_equal(emitter, node, kind, target, current)
        # _grouper_next: only the current grouper reads; fetch on demand,
        # then return currvalue while its key still equals this group's key.
        code = ("'" + label + ':{let (' + parent + ',' + target + ')={let state=' + value.code + '.borrow();'
                + 'if state.parent.borrow().current!=state.id{break \'' + label + ' None;}(state.parent.clone(),state.tgtkey.clone())};'
                + 'if ' + parent + '.borrow().currvalue.is_none(){' + _step(registry, emitter, node, outer, parent, active + (record.index,), label) + '}'
                + 'let ' + current + '=' + parent + '.borrow().currkey.clone().unwrap();'
                + 'if !(' + equal + '){break \'' + label + ' None;}let taken=' + parent + '.borrow_mut().currvalue.take();taken}')
        return Expression(code, shape(record.element))
