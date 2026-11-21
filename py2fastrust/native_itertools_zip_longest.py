"""itertools.zip_longest, following zip_longest_new/zip_longest_next in Modules/itertoolsmodule.c.

iter() is taken for every argument when zip_longest() is called. Each pull
advances the remaining iterators in order; an exhausted iterator is dropped and
never pulled again, and its position yields ``fillvalue``. The pull that
exhausts the last active iterator ends the iteration without a tuple.
"""


def bind(positional, keywords):
    keywords = list(keywords)
    fill = None
    for name, value in keywords:
        if name != 'fillvalue':
            return None, f"TypeError: zip_longest() got an unexpected keyword argument '{name}'"
        fill = value
    return (list(positional), fill), None


def analyze(model, plan, node, positional, keywords, environment, *, factory):
    from .native_classes import Cell
    from .native_itertools import ToolCall
    from .native_iterator_hints import ABSENT
    values, error = bind(positional, keywords)
    if error:
        return ToolCall(factory('none'), error=error)
    sources, fill = values
    registry = model.iterators
    record = registry._record(plan, node, 'itertools_zip_longest')
    record.hint_protocol = ABSENT
    record.adapter = ZipLongestState
    record.tool = 'zip_longest'
    if not hasattr(record, 'fill'):
        record.fill = Cell()
        record.fields = tuple(Cell() for _ in sources)
    registry._contribute(record.fill, fill if fill is not None else Cell('none'), node)
    record.input_types = tuple(registry.source(plan, node, source, ('itertools', 'zip_longest', index), environment=environment)
                               for index, source in enumerate(sources))
    for field, source in zip(record.fields, record.input_types):
        registry._contribute(field, registry.item(source), node)
        registry._contribute(field, record.fill, node)
    registry._contribute(record.element, Cell('tuple', record.fields), node)
    return ToolCall(factory(record.kind), record)


def emit(emitter, node, call, positional, keywords):
    from .native_classes import Expression
    values, error = bind(positional, keywords)
    assert error is None
    sources, fill = values
    record = call.iterator
    record.emitted = True
    setup, fields = '', []
    for index, (source, kind) in enumerate(zip(sources, record.input_types)):
        before, cursor = emitter.capture(emitter.model.iterators.construct(emitter, node, source, kind=kind))
        setup += before
        fields.append('s' + str(index) + ':Some(' + cursor.code + ')')
    fill = fill if fill is not None else Expression('()', 'none')
    before, fill = emitter.capture(fill)
    setup += before
    fields += ['fill:' + fill.code, 'active:' + str(len(sources))]
    state = 'Rc::new(RefCell::new(ClassIteratorState_' + str(record.index) + '{' + ','.join(fields) + '}))'
    return Expression('{' + setup + state + '}', record.kind)


class ZipLongestState:
    @staticmethod
    def owned(record):
        from .native_classes import shape
        return (*record.input_types, shape(record.fill))

    @staticmethod
    def demand(registry, plan, node, record, environment, active):
        from .native_classes import Cell
        for source in record.input_types:
            registry.demand(plan, node, Cell(source), environment, active + (record.index,))
        return record.element

    @staticmethod
    def may_call(registry, record, seen):
        return any(registry.may_call(source, seen | {record.index}) for source in record.input_types)

    @staticmethod
    def fields(emitter, record):
        from .native_classes import shape
        parts = ['s' + str(index) + ':Option<' + emitter.rust_type(source) + '>' for index, source in enumerate(record.input_types)]
        return ','.join(parts + ['fill:' + emitter.rust_type(shape(record.fill)), 'active:usize'])

    @staticmethod
    def pull(registry, emitter, node, value, active):
        from .native_classes import Expression, shape
        record = value.kind.record
        kind = shape(record.element)
        label = 'zip_longest_' + emitter.fresh()
        fill = Expression(value.code + '.borrow().fill.clone()', shape(record.fill))
        code = "'" + label + ':{if ' + value.code + '.borrow().active==0{break \'' + label + ' None;}'
        items = []
        for index, (source_kind, field) in enumerate(zip(record.input_types, record.fields)):
            source, item, current = emitter.fresh(), emitter.fresh(), emitter.fresh()
            slot = 's' + str(index)
            nested = registry.pull(emitter, node, Expression(source, source_kind), active + (record.index,))
            wanted = shape(field)
            filled = emitter.coerce(fill, wanted, node)
            pulled = emitter.coerce(Expression(current, nested.kind), wanted, node)
            code += ('let ' + item + '={let ' + source + '=' + value.code + '.borrow().' + slot + '.clone();match ' + source
                     + '{Some(' + source + ')=>match (' + nested.code + '){Some(' + current + ')=>' + pulled + ','
                     + 'None=>{{let mut state=' + value.code + '.borrow_mut();state.' + slot + '=None;state.active-=1;'
                     + 'if state.active==0{break \'' + label + ' None;}}' + filled + '}},None=>' + filled + '}};')
            items.append(item)
        code += 'Some((' + ''.join(item + ',' for item in items) + '))}'
        return Expression(code, kind)
