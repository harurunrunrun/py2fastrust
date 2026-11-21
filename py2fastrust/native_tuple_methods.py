"""tuple.count(x) and tuple.index(x) following tuplecount/tupleindex in Objects/tupleobject.c.

Items are compared in order with ``==``; index reports
``ValueError: tuple.index(x): x not in tuple`` when nothing matches. The
optional start/stop arguments of index are not implemented.
"""
import ast

NAMES = frozenset({'count', 'index'})


def _tuple_kind(kind):
    from .native_types import TupleType, TupleSequenceType
    return isinstance(kind, (TupleType, TupleSequenceType))


def requires_frames(unit, analysis):
    from .native_constraints import MethodValue, TupleValue
    for facts in analysis.scopes.values():
        for call in facts.calls.values():
            for identity in call.identity.alternatives:
                if isinstance(identity, MethodValue) and identity.name in NAMES and not identity.receiver.unknown:
                    if identity.receiver.alternatives and all(isinstance(part, TupleValue) or getattr(part, 'category', None) == 'tuple_sequence'
                                                              for part in identity.receiver.alternatives):
                        return True
    return False


def analyze(model, plan, node, receiver, arguments, keywords):
    from .native_classes import ClassUnsupported, shape
    if node.func.attr not in NAMES or not _tuple_kind(shape(receiver)):
        return None
    if keywords or len(arguments) != 1:
        raise ClassUnsupported(node, f'tuple.{node.func.attr}() with start/stop or keyword arguments is not implemented; the one-argument form is',
                               proof='tuple method argument binding')
    sites = getattr(model, 'tuple_method_sites', None)
    if sites is None:
        sites = model.tuple_method_sites = set()
    sites.add((plan.index, id(node)))
    return model.cell(plan, node, 'int')


def emit(emitter, node, receiver, arguments, wanted):
    from .native_classes import Expression
    from .native_types import TupleType
    from .native import _string
    if (emitter.plan.index, id(node)) not in getattr(emitter.model, 'tuple_method_sites', ()) or not _tuple_kind(receiver.kind):
        return None
    before, target = emitter.capture(arguments[0])
    holder = emitter.fresh()
    if isinstance(receiver.kind, TupleType):
        tests = [emitter.comparison(ast.Eq(), Expression('(' + holder + ').' + str(index) + '.clone()', field), Expression(target.code + '.clone()', target.kind), node)
                 for index, field in enumerate(receiver.kind.fields)]
    else:
        item = emitter.fresh()
        test = emitter.comparison(ast.Eq(), Expression(item + '.clone()', receiver.kind.element), Expression(target.code + '.clone()', target.kind), node)
        tests = None
    count = emitter.fresh()
    if node.func.attr == 'count':
        if tests is not None:
            body = 'let mut ' + count + ':usize=0;' + ''.join('if ' + test + '{' + count + '+=1;}' for test in tests)
        else:
            body = 'let mut ' + count + ':usize=0;for ' + item + ' in ' + holder + '.iter(){if ' + test + '{' + count + '+=1;}}'
        result = 'class_from_usize(' + count + ')'
    else:
        missing = emitter.at('Err::<usize,String>(' + _string('ValueError: tuple.index(x): x not in tuple') + '.to_owned())', node)
        if tests is not None:
            chain = ''.join('if ' + test + '{' + str(index) + '}else ' for index, test in enumerate(tests))
            body = 'let ' + count + ':usize=' + chain + '{' + missing + '};'
        else:
            body = ('let ' + count + ':usize=match ' + holder + '.iter().position(|' + item + '|' + test + '){Some(position)=>position,None=>' + missing + '};')
        result = 'class_from_usize(' + count + ')'
    code = '{' + before + 'let ' + holder + '=(' + receiver.code + ').clone();' + body + result + '}'
    return Expression(emitter.coerce(Expression(code, 'int'), wanted, node), wanted)
