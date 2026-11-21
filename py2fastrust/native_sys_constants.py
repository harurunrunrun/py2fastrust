"""``sys.maxsize``: Py_ssize_t's maximum on the 64-bit target (2**63 - 1)."""
from dataclasses import dataclass

CONSTANTS = {'maxsize': 2**63 - 1}


@dataclass
class Constant:
    module: object
    name: str
    key: object
    value: object


def seed(linker, module, name):
    if not (module.native_adapter and module.name == 'sys' and module.origin == 'builtin' and name in CONSTANTS):
        return False
    from .native_classes import Cell
    records = getattr(linker.model, 'sys_constant_data', None)
    if records is None:
        records = linker.model.sys_constant_data = {}
    key = linker.unit.global_name(module.name, name)
    record = records.setdefault(key, Constant(module, name, key, Cell('int')))
    namespace = linker.model.namespace
    namespace.incoming.setdefault(key, {})[('canonical_sys_constant', name)] = record.value
    namespace.active.add(key)
    namespace.refresh(key, linker.model.tree)
    return True


def initializer(model, emitter, module):
    records = [row for row in getattr(model, 'sys_constant_data', {}).values() if row.module.number == module.number]
    if not records:
        return None
    from .native_classes import Expression
    fields = dict(model.namespace.fields())
    body = ''
    for row in records:
        value = Expression(emitter.literal(CONSTANTS[row.name]), 'int', CONSTANTS[row.name])
        body += 'globals.borrow_mut().value_' + str(model.namespace.index(row.key)) + '=Some(' + emitter.coerce(value, fields[row.key], model.tree) + ');'
    return 'native_at((||->Result<(),String>{' + body + 'Ok(())})(),0,("<sys>","<module>"))'
