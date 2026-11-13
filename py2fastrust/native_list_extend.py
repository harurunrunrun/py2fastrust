"""Ordered canonical list.extend over concrete native iterable families."""
import ast


def direct_source(kind):
    from .native_classes import domain
    return domain(kind) in {'range', 'tuple', 'tuple_sequence', 'bytes', 'str'}


def requires_frames(unit, analysis):
    from .native_types import alternatives, list_type
    for node in ast.walk(unit.tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'extend'):
            continue
        for facts in analysis.scopes.values():
            receiver = facts.expressions.get(unit.ordinal(node.func.value))
            if not any(list_type(kind) for kind in alternatives(receiver)):
                continue
            if len(node.args) != 1 or node.keywords:
                return True
            source = facts.expressions.get(unit.ordinal(node.args[0]))
            if not all(list_type(kind) for kind in alternatives(source)):
                return True
    return False


def analyze(model, plan, node, receiver, source, environment):
    from .native_classes import Cell, shape, InstanceType, ClassUnsupported
    from .native_types import alternatives, list_type
    from .native_source_lengths import analyze_hint, member
    if not hasattr(model, 'list_extend_sites'):
        model.list_extend_sites = {}
    key = plan.index, id(node)
    model.list_extend_sites.pop(key, None)
    if list_type(shape(source)):
        model.contribute(receiver.root().args[0], model.item(source, node), node)
        return
    cursor = model.iterators.source(plan, node, source, identity='list_extend',
                                    environment=environment)
    # The original iterable supplies the hint, after its iterator is acquired.
    # A present custom hint must never be silently treated as a missing slot.
    for kind in alternatives(shape(source)):
        if isinstance(kind, InstanceType) and member(model, kind, ('__length_hint__',), node) is not None:
            raise ClassUnsupported(node, 'list.extend needs the original iterable __length_hint__ callback and its fallback/error protocol; this custom hint adapter is not implemented',
                                   types=(('iterable', kind),), proof='ordered original-iterable length hint')
    analyze_hint(model, plan, node, source, environment, 'list.extend')
    item = model.iterators.demand(plan, node, Cell(cursor), environment)
    if model.final:
        guard_dictionary_cursors(model,node)
    model.contribute(receiver.root().args[0], item, node)
    model.list_extend_sites[key] = cursor


def guard_dictionary_cursors(model,node):
    from .native_dictionary_positions import guard
    guard(model,node)


def emit(emitter, node, storage, source):
    from .native_classes import Expression, domain
    from .native_types import list_type
    if list_type(source.kind):
        return None
    model = emitter.model
    model.list_extend_runtime = True
    element = storage.element

    def reserve(hint):
        saved = emitter.fresh()
        return ('let ' + saved + '=' + hint + ';'
                + emitter.at('class_list_extend_reserve(' + storage.mutable + ',' + saved + ')', node) + ';')

    def append(value):
        converted = emitter.coerce(value, element, node)
        # Materialize before borrowing the destination. A future coercion
        # callback must not inherit a destination RefMut.
        name = emitter.fresh()
        return ('let ' + name + '=' + converted + ';'
                + emitter.at('native_typed_push(' + storage.mutable + ',' + name + ')', node) + ';')

    tag = domain(source.kind)
    # These actual builtin storage families cannot run source callbacks.
    # Use direct Rust loops, without allocating a shared cursor per extension.
    if tag == 'tuple':
        body = reserve(str(len(source.kind.fields)) + '_usize')
        for index, kind in enumerate(source.kind.fields):
            body += append(Expression(source.code + '.' + str(index) + '.clone()', kind))
        return Expression('{' + body + '()}', 'none')
    if tag in {'range', 'tuple_sequence', 'bytes', 'str'}:
        current, destination = emitter.fresh(), emitter.fresh()
        hint = hint_value(emitter, node, source)
        if tag == 'range':
            sequence = source.code + '.iter()'
            value = Expression(current, 'int')
        elif tag == 'tuple_sequence':
            sequence = source.code + '.as_slice().iter().cloned()'
            value = Expression(current, source.kind.element)
        elif tag == 'bytes':
            sequence = source.code + '.iter().copied()'
            value = Expression('class_from_usize(' + current + ' as usize)', 'int')
        else:
            sequence = (source.code + '.as_bytes().iter().copied()' if model.string_mode == 'ascii'
                        else source.code + '.chars()')
            value = Expression('NativeText::from(' + current + (' as char)' if model.string_mode == 'ascii' else ')'), 'str')
        converted = emitter.coerce(value, element, node)
        body = reserve(hint) + 'let ' + destination + '=' + storage.mutable + ';'
        body += ('for ' + current + ' in ' + sequence + '{'
                 + emitter.at('native_typed_push(' + destination + ',' + converted + ')', node) + ';}')
        return Expression('{' + body + '()}', 'none')
    cursor = model.list_extend_sites[emitter.plan.index, id(node)]
    before, iterator = emitter.capture(model.iterators.construct(emitter, node,
        Expression('(' + source.code + ').clone()', source.kind), kind=cursor))
    hint = hint_value(emitter, node, source)
    body = before + reserve(hint)
    pulled = model.iterators.pull(emitter, node, iterator)
    current = emitter.fresh()
    body += ('loop{let Some(' + current + ')=(' + pulled.code + ')else{break;};'
             + append(Expression(current, pulled.kind)) + '}')
    return Expression('{' + body + '()}', 'none')


def hint_value(emitter, node, value):
    from .native_classes import Expression, InstanceType, domain, shape, ClassUnsupported
    from .native_unions import union_kind, project
    from .native_class_iterators import iterator_kind
    if union_kind(value.kind):
        return project(value.kind, value.code,
                       lambda kind, code: hint_value(emitter, node, Expression(code, kind)))
    tag = domain(value.kind)
    if isinstance(value.kind, InstanceType):
        from .native_source_lengths import emit_hint
        return emit_hint(emitter, node, value, 'list.extend')
    if tag == 'range':
        emitter.model.list_extend_range = True
        return emitter.at('class_list_extend_range_length(&' + value.code + '.start,&' + value.code + '.stop,&' + value.code + '.step)', node)
    if tag == 'tuple':
        return str(len(value.kind.fields)) + '_usize'
    if tag == 'tuple_sequence':
        return value.code + '.as_slice().len()'
    if tag in {'array', 'bytearray'}:
        return value.code + '.0.borrow().len()'
    if tag in {'bytes', 'str'}:
        return value.code + ('.codepoint_len()' if tag == 'str' and emitter.model.string_mode != 'ascii' else '.len()')
    if tag in {'list', 'dict', 'set', 'deque'}:
        return value.code + '.borrow().len()'
    if tag == 'dict_view':
        return emitter.model.mappings.views.length(emitter, value)
    if iterator_kind(value.kind):
        from .native_iterator_hints import emit as cursor_hint
        return cursor_hint(emitter, node, value)
    # Noniterable construction raises before this default is reached.
    return '8_usize'


def runtime(model):
    extending = getattr(model, 'list_extend_runtime', False)
    if not extending and not getattr(model, 'list_extend_range', False) and not getattr(model, 'iterator_hint_reverse_range', False):
        return ''
    reserve = '''fn class_list_extend_reserve<T>(values:&mut Vec<T>,hint:usize)->Result<(),String>{
        if let Some(total)=values.len().checked_add(hint).filter(|total|*total<=isize::MAX as usize){
            if total>isize::MAX as usize/std::mem::size_of::<usize>(){return Err("MemoryError".to_owned());}
            values.try_reserve(hint).map_err(|_|"MemoryError".to_owned())?;
        }Ok(())}
    ''' if extending else ''
    from .native_iterator_hints import runtime as hint_runtime
    reserve += hint_runtime(model)
    if not getattr(model, 'list_extend_range', False):
        return reserve
    from .native_materializer_hints import range_count
    count = range_count(model.integer)
    return reserve + 'fn class_list_extend_range_length(start:&NativeInt,stop:&NativeInt,step:&NativeInt)->Result<usize,String>{(' + '{' + count + '}' + ').ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())}'
