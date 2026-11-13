"""Canonical retained standard-output text calls over the shared output buffer."""

CALLABLES = frozenset({'write_text', 'flush_text'})


def member(receiver, name):
    if receiver == 'stdout':
        return {'write': 'write_text', 'flush': 'flush_text'}.get(name)
    return None


def guard_attribute(kind, node, *, writing=False):
    from .native_classes import ClassUnsupported
    if kind != 'stdout':
        return
    detail = ('changing a canonical standard-output attribute requires replaceable stream state'
              if writing else 'the binary output buffer protocol is not implemented'
              if node.attr == 'buffer' else 'the standard-output ' + repr(node.attr) + ' protocol is not implemented')
    raise ClassUnsupported(node, detail + '; this native stream adapter supports canonical text write and flush calls',
                           proof='canonical standard-output stream identity and protocol')


def binding_error(identity, arguments, keywords):
    name = 'write' if identity == 'write_text' else 'flush'
    if keywords:
        return 'TypeError: TextIOWrapper.' + name + '() takes no keyword arguments'
    count = len(arguments)
    if name == 'write' and count != 1:
        return f'TypeError: TextIOWrapper.write() takes exactly one argument ({count} given)'
    if name == 'flush' and count:
        return f'TypeError: TextIOWrapper.flush() takes no arguments ({count} given)'
    return None


def analyze(model, plan, node, identity, arguments, keywords, *, factory=None):
    if identity not in CALLABLES:
        return None
    cell = (lambda tag: model.cell(plan, node, tag)) if factory is None else factory
    return cell('int' if identity == 'write_text' else 'none')


def emit(emitter, node, identity, arguments, keywords, wanted):
    if identity not in CALLABLES:
        return None
    from .native import _string
    from .native_classes import Expression
    from .native_class_builtins import _type_name
    from .native_types import EmptyType
    from .native_unions import project
    error = binding_error(identity, arguments, keywords)
    if error:
        return Expression(emitter.at('Err::<' + emitter.rust_type(wanted) + ',String>('
                                      + _string(error) + '.to_owned())', node), wanted)
    if identity == 'flush_text':
        code = emitter.at('native_flush_output(&mut class_scope.io.borrow_mut().output)', node)
        return Expression(emitter.coerce(Expression(code, 'none'), wanted, node), wanted)

    def leaf(kind, code):
        if isinstance(kind, EmptyType):
            return 'native_empty::<' + emitter.rust_type(wanted) + '>(' + code + ')'
        if kind != 'str':
            name = ('"_io.TextIOWrapper"' if kind == 'stdout' else
                    '"builtin_function_or_method"' if kind in CALLABLES else
                    _type_name(emitter, Expression(code, kind), node))
            return emitter.at('Err::<' + emitter.rust_type(wanted)
                              + ',String>(format!("TypeError: write() argument must be str, not {}",'
                              + name + '))', node)
        value, count = emitter.fresh(), emitter.fresh()
        length = '.len()' if emitter.model.string_mode == 'ascii' else '.codepoint_len()'
        output = ('{let ' + value + '=&(' + code + ');let ' + count + '=class_from_usize('
                  + value + length + ');class_scope.io.borrow_mut().output.push_str(&'
                  + value + ');' + count + '}')
        return emitter.coerce(Expression(output, 'int'), wanted, node)

    value = arguments[0]
    return Expression(project(value.kind, value.code, leaf), wanted)


def emit_expanded(emitter, node, identity, vector, element, keywords, wanted):
    """Bind the existing expanded positional vector after all argument effects."""
    from .native_classes import Expression
    if keywords:
        return emit(emitter, node, identity, [], keywords, wanted).code
    expected = 1 if identity == 'write_text' else 0
    message = ('format!("TypeError: TextIOWrapper.write() takes exactly one argument ({} given)",'
               + vector + '.len())' if expected else
               'format!("TypeError: TextIOWrapper.flush() takes no arguments ({} given)",'
               + vector + '.len())')
    failed = emitter.at('Err::<' + emitter.rust_type(wanted) + ',String>(' + message + ')', node)
    arguments = [Expression(vector + '[0].clone()', element)] if expected else []
    result = emit(emitter, node, identity, arguments, [], wanted)
    return 'if ' + vector + '.len()!=' + str(expected) + '{' + failed + '}else{' + result.code + '}'
