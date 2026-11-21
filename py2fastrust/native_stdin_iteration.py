"""Iteration over sys.stdin and sys.stdin.buffer as successive readline results.

TextIOWrapper/BufferedReader iteration returns readline() until it yields an
empty string or bytes at end of file. The cursor reads through the same native
input buffer as input() and readline(), so interleaved reads keep their order.
"""

TAGS = {'stdin': 'str', 'stdin_buffer': 'bytes', 'stdin_file': 'str'}


def source_cursor(registry, plan, node, value, identity, operation):
    from .native_classes import shape, domain
    kind = shape(value)
    if domain(kind) not in TAGS or operation != 'source':
        return None
    record = registry._record(plan, node, 'stdin_lines', identity)
    from .native_iterator_hints import ABSENT
    record.hint_protocol = ABSENT
    record.adapter = StdinCursor
    registry._contribute(record.source, value, node)
    registry._contribute(record.element, registry.model.cell_for_kind(TAGS[domain(kind)]), node)
    return record.kind


def construct_cursor(registry, emitter, node, value, kind):
    from .native_classes import Expression, domain
    if domain(value.kind) not in TAGS:
        return None
    if kind is None:
        kind = registry.sites[emitter.plan.index, id(node), 'stdin_lines', None].kind
    if getattr(kind.record, 'adapter', None) is not StdinCursor:
        return None
    kind.record.emitted = True
    return Expression('Rc::new(RefCell::new(ClassIteratorState_' + str(kind.index) + '{done:false}))', kind)


class StdinCursor:
    @staticmethod
    def owned(record):
        return ()

    @staticmethod
    def demand(registry, plan, node, record, environment, active):
        return record.element

    @staticmethod
    def may_call(registry, record, seen):
        return False

    @staticmethod
    def fields(emitter, record):
        return 'done:bool'

    @staticmethod
    def pull(registry, emitter, node, value, active):
        from .native_classes import Expression, shape, domain
        record = value.kind.record
        wanted = shape(record.element)
        binary = domain(shape(record.source)) == 'stdin_buffer'
        source_tag = domain(shape(record.source))
        read = emitter.at('class_read_bytes(&class_scope,true)' if binary else 'class_file0_readline(&class_scope)' if source_tag == 'stdin_file'
                          else 'class_read_text(&class_scope,true,false)', node)
        line = emitter.fresh()
        item = Expression(line if binary else 'NativeText::from(' + line + ')', 'bytes' if binary else 'str')
        converted = emitter.coerce(item, wanted, node)
        code = ('if ' + value.code + '.borrow().done{None}else{let ' + line + '=' + read + ';if ' + line
                + '.is_empty(){' + value.code + '.borrow_mut().done=true;None}else{Some(' + converted + ')}}')
        return Expression(code, wanted)


def requires_frames(unit):
    """Route loops over, and readlines() calls on, a stdin stream attribute."""
    import ast
    for node in ast.walk(unit.tree):
        source = node.iter if isinstance(node, (ast.For, ast.comprehension)) else None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'readlines':
            source = node.func.value
        if isinstance(source, ast.Attribute) and source.attr in {'stdin', 'buffer'}:
            return True
    return False
