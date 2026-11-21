"""``dict.fromkeys(iterable[, value])`` following dict_fromkeys in Objects/dictobject.c (3.14).

The receiver is the builtin dict type. The iterable is consumed in order and
each key is stored with the same value object (None by default), so a mutable
value is shared by every key. Later duplicates keep the first insertion.
"""
import ast


def _receiver(model, plan, node, environment):
    from .references import BuiltinIdentity
    function = node.func
    return (isinstance(function, ast.Attribute) and function.attr == 'fromkeys' and isinstance(function.value, ast.Name)
            and model.builtin_identity(plan, function.value, environment) == BuiltinIdentity('dict'))


def requires_frames(unit):
    for node in ast.walk(unit.tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'fromkeys'
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'dict'):
            return True
    return False


def analyze(model, plan, node, environment):
    from .native_classes import Cell, ClassUnsupported
    if not _receiver(model, plan, node, environment):
        return None
    if node.keywords or not 1 <= len(node.args) <= 2 or any(isinstance(argument, ast.Starred) for argument in node.args):
        raise ClassUnsupported(node, 'this dict.fromkeys binding is invalid or uses expanded arguments; one iterable and an optional value are implemented',
                               proof='dict.fromkeys argument binding')
    source = model.expression(plan, node.args[0], environment)
    fill = model.expression(plan, node.args[1], environment) if len(node.args) == 2 else Cell('none')
    record = model.mappings.record(plan, node, 'dict', 'fromkeys')
    record.source = source
    iterator = model.iterators.source(plan, node, source, ('dict_fromkeys',), environment=environment)
    record.source_type = iterator
    item = model.iterators.demand(plan, node, Cell(iterator), environment)
    model.mappings.contribute_key(record, item, node)
    model.contribute(record.value, fill, node)
    sites = getattr(model, 'dict_fromkeys_sites', None)
    if sites is None:
        sites = model.dict_fromkeys_sites = {}
    sites[(plan.index, id(node))] = (record, iterator)
    return model.cell(plan, node, record.kind)


def emit(emitter, node):
    from .native_classes import Expression, shape
    site = getattr(emitter.model, 'dict_fromkeys_sites', {}).get((emitter.plan.index, id(node)))
    if site is None:
        return None
    record, iterator = site
    record.emitted = True
    before, source = emitter.capture(emitter.expression(node.args[0]))
    if len(node.args) == 2:
        more, fill = emitter.capture(emitter.expression(node.args[1]))
        before += more
    else:
        fill = Expression('()', 'none')
    owner, key = emitter.fresh(), emitter.fresh()
    mappings = emitter.model.mappings
    code = before + 'let ' + owner + '=' + mappings._new(emitter, record) + ';'
    more, cursor = emitter.capture(emitter.model.iterators.construct(emitter, node, source, kind=iterator))
    code += more
    pulled = emitter.model.iterators.pull(emitter, node, cursor)
    target = Expression(owner, record.kind)
    value = Expression(emitter.coerce(fill, shape(record.value), node), shape(record.value))
    code += 'loop{let Some(' + key + ')=(' + pulled.code + ')else{break;};' + mappings._set(emitter, node, target, Expression(key, pulled.kind), value) + '}'
    wanted = emitter.kind(node)
    return Expression(emitter.coerce(Expression('{' + code + owner + '}', record.kind), wanted, node), wanted)
