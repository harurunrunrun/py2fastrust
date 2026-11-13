"""Typed calls to captured, canonical standard-input readers.

Reader tags originate from proved stdin attributes, never a source spelling.
The callable and arguments have already been evaluated by each caller.
"""

from .native_class_stdout import CALLABLES as OUTPUT_CALLABLES

READERS = {
    'reader_text': (False, True),
    'reader_bytes': (True, True),
    'read_text': (False, False),
    'read_bytes': (True, False),
}
CALLABLES = frozenset(READERS) | OUTPUT_CALLABLES


def _imports(model, node):
    import ast
    if (isinstance(node, ast.ImportFrom) and node.module == 'sys' and not node.level
            and 'sys' in model.trusted_imports and all(alias.name in {'stdin', 'stdout'} for alias in node.names)):
        return node.names
    return None


def import_statement(model, plan, node, environment):
    aliases = _imports(model, node)
    if aliases is None:
        return False
    from .native_classes import Cell
    for alias in aliases:
        model.bind_name(plan, alias, Cell(alias.name), environment)
    model.namespace.import_event(plan, node, environment)
    return True


def emit_import(emitter, node):
    aliases = _imports(emitter.model, node)
    if aliases is None:
        return None
    from .native_classes import Expression
    from .native_globals_view import store
    return ''.join(emitter.assign_name(alias, Expression('()', alias.name)) + store(emitter, alias)
                   for alias in aliases)


def member(receiver, name):
    from .native_class_stdout import member as output_member
    output = output_member(receiver, name)
    if output is not None:
        return output
    if receiver not in {'stdin', 'stdin_buffer'} or name not in {'read', 'readline'}:
        return None
    return ('reader_' if name == 'readline' else 'read_') + ('bytes' if receiver == 'stdin_buffer' else 'text')


def _binding(node, reader, arguments, keywords):
    from .native_classes import ClassUnsupported
    if len(arguments) > 1 or keywords:
        raise ClassUnsupported(node, 'this canonical standard-input reader accepts at most one positional size argument; native reader keyword/invalid-arity call errors are not implemented',
                               types=(('reader', reader),), proof='standard-input reader argument binding')


def analyze(model, plan, node, reader, arguments, keywords, *, factory=None):
    if reader in OUTPUT_CALLABLES:
        from .native_class_stdout import analyze as analyze_output
        return analyze_output(model, plan, node, reader, arguments, keywords, factory=factory)
    if reader not in READERS:
        return None
    from .native_classes import ClassUnsupported, domain, shape
    from .native_types import alternatives
    _binding(node, reader, arguments, keywords)
    if arguments:
        for kind in alternatives(shape(arguments[0])):
            if domain(kind) == 'object':
                raise ClassUnsupported(node, 'this read size requires the user-defined __index__ protocol; the native standard-input adapter currently accepts builtin integers, booleans and the reader-specific None default',
                                       types=(('size', kind),), proof='standard-input size index protocol')
    cell = (lambda tag: model.cell(plan, node, tag)) if factory is None else factory
    return cell('bytes' if READERS[reader][0] else 'str')


def emit(emitter, node, reader, arguments, keywords, wanted):
    if reader in OUTPUT_CALLABLES:
        from .native_class_stdout import emit as emit_output
        return emit_output(emitter, node, reader, arguments, keywords, wanted)
    if reader not in READERS:
        return None
    from .native_classes import Expression, domain
    from .native_class_builtins import _type_name
    from .native_unions import project, union_kind
    _binding(node, reader, arguments, keywords)
    binary, line = READERS[reader]
    kind = 'bytes' if binary else 'str'
    if not arguments:
        call = (f'class_read_bytes(&class_scope,{str(line).lower()})' if binary else
                f'class_read_text(&class_scope,{str(line).lower()},false)')
        code = emitter.at(call, node)
    else:
        def size(kind, code):
            tag = domain(kind)
            if tag == 'none' and (binary or not line):
                return 'None'
            if tag not in {'int', 'bool', 'int_bool'}:
                name = _type_name(emitter, Expression(code, kind), node)
                failure = 'format!("TypeError: \'{}\' object cannot be interpreted as an integer",' + name + ')'
                return emitter.at('Err::<Option<usize>,String>(' + failure + ')', node)
            number = emitter.number(Expression(code, kind))
            wide = '(' + number + ').to_i128()' if emitter.model.integer == 'bigint' else 'Some((' + number + ') as i128)'
            overflow = '"OverflowError: cannot fit \'int\' into an index-sized integer".to_owned()'
            converted = wide + '.and_then(|value|isize::try_from(value).ok()).ok_or_else(||' + overflow + ')'
            value = emitter.fresh()
            negative = ''
            if binary and not line:
                negative = 'if ' + value + '< -1{return Err("ValueError: read length must be non-negative or -1".to_owned());}'
            count = '(||->Result<Option<usize>,String>{let ' + value + '=' + converted + '?;' + negative
            count += 'Ok(if ' + value + '<0{None}else{Some(' + value + ' as usize)})})()'
            return emitter.at(count, node)

        argument = arguments[0]
        count = (project(argument.kind, argument.code, size) if union_kind(argument.kind) else
                 size(argument.kind, argument.code))
        count_name, io = emitter.fresh(), emitter.fresh()
        setup = 'let ' + count_name + ':Option<usize>=' + count + ';'
        if binary:
            call = '{let mut ' + io + '=class_scope.io.borrow_mut();' + io + '.input.read_binary(' + count_name + ',' + str(line).lower() + ').map_err(StandardInputError::native_message)}'
        else:
            text = emitter.fresh()
            call = '{let mut ' + io + '=class_scope.io.borrow_mut();let mut ' + text + '=String::new();'
            call += io + '.input.read_text_into(&mut ' + text + ',' + count_name + ',' + str(line).lower() + ').map(|()|' + text + ').map_err(StandardInputError::native_message)}'
        code = '{' + setup + emitter.at(call, node) + '}'
    if kind == 'str':
        code = 'NativeText::from(' + code + ')'
    return Expression(emitter.coerce(Expression(code, kind), wanted, node), wanted)
