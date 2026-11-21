"""zip(*iterables) with a runtime number of argument iterators.

Like zip_new/zip_next in CPython, iter() is taken for every argument when
zip() is called, and each pull advances the iterators in order until one is
exhausted. Without strict=, exhaustion is not remembered: a later pull tries
the earlier iterators again. Items are variable-length tuples.
"""


def analyze(model, plan, node, site, environment):
    from .native_classes import Cell
    from .native_iterator_hints import ABSENT
    registry = model.iterators
    record = registry._record(plan, node, 'zip_expanded')
    record.hint_protocol = ABSENT
    record.adapter = ZipExpanded
    record.input_types = (registry.source(plan, node, site.element, ('zip_expanded', 0), environment=environment),)
    registry._contribute(record.element, Cell('tuple_sequence', (registry.item(record.input_types[0]),)), node)
    return record


def emit(emitter, node, record, vector, element):
    from .native_classes import Expression
    record.emitted = True
    emitter.model.materialized_tuple = True
    registry = emitter.model.iterators
    sources, item = emitter.fresh(), emitter.fresh()
    constructed = registry.construct(emitter, node, Expression(item, element), kind=record.input_types[0])
    return ('{let mut ' + sources + '=Vec::new();for ' + item + ' in ' + vector + '.into_iter(){let '
            + item + '=' + constructed.code + ';' + sources + '.push(' + item + ');}'
            + 'Rc::new(RefCell::new(ClassIteratorState_' + str(record.index) + '{sources:' + sources + '}))}')


class ZipExpanded:
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
        return 'sources:Vec<' + emitter.rust_type(record.input_types[0]) + '>'

    @staticmethod
    def pull(registry, emitter, node, value, active):
        from .native_classes import Expression, shape
        record = value.kind.record
        kind = shape(record.element)
        count, values, position, source, current, label = (emitter.fresh() for _ in range(6))
        nested = registry.pull(emitter, node, Expression(source, record.input_types[0]), active + (record.index,))
        code = ("'" + label + ':{let ' + count + '=' + value.code + '.borrow().sources.len();if ' + count + '==0{break \'' + label + ' None;}'
                + 'let mut ' + values + '=Vec::with_capacity(' + count + ');for ' + position + ' in 0..' + count + '{'
                + 'let ' + source + '=' + value.code + '.borrow().sources[' + position + '].clone();'
                + 'let Some(' + current + ')=(' + nested.code + ')else{break \'' + label + ' None;};'
                + values + '.push(' + current + ');}Some(NativeTuple::from_vec(' + values + '))}')
        return Expression(code, kind)
