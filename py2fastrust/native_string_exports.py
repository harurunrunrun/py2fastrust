"""The str constants of the canonical ``string`` module (Lib/string/__init__.py, CPython 3.14).

They are ordinary module globals initialized when the module is first
imported; reading one yields the literal text below.
"""
from dataclasses import dataclass

_LOWER = 'abcdefghijklmnopqrstuvwxyz'
_UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
_PUNCTUATION = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
_WHITESPACE = ' \t\n\r\x0b\x0c'
CONSTANTS = {
    'whitespace': _WHITESPACE,
    'ascii_lowercase': _LOWER,
    'ascii_uppercase': _UPPER,
    'ascii_letters': _LOWER + _UPPER,
    'digits': '0123456789',
    'hexdigits': '0123456789abcdefABCDEF',
    'octdigits': '01234567',
    'punctuation': _PUNCTUATION,
    'printable': '0123456789' + _LOWER + _UPPER + _PUNCTUATION + _WHITESPACE,
}


@dataclass
class Constant:
    module: object
    name: str
    key: object
    value: object


def canonical(module):
    return module.name == 'string' and module.origin == 'builtin'


def seed(linker, module, name):
    if not (module.native_adapter and canonical(module) and name in CONSTANTS):
        return False
    from .native_classes import Cell
    records = getattr(linker.model, 'string_constant_data', None)
    if records is None:
        records = linker.model.string_constant_data = {}
    key = linker.unit.global_name(module.name, name)
    record = records.setdefault(key, Constant(module, name, key, Cell('str')))
    namespace = linker.model.namespace
    namespace.incoming.setdefault(key, {})[('canonical_string_constant', name)] = record.value
    namespace.active.add(key)
    namespace.refresh(key, linker.model.tree)
    return True


def initializer(model, emitter, module):
    records = [row for row in getattr(model, 'string_constant_data', {}).values() if row.module.number == module.number]
    if not records:
        return None
    from .native_classes import Expression
    from .native import _string
    fields = dict(model.namespace.fields())
    body = ''
    for row in records:
        value = Expression('NativeText::from(' + _string(CONSTANTS[row.name]) + ')', 'str')
        stored = emitter.coerce(value, fields[row.key], model.tree)
        body += 'globals.borrow_mut().value_' + str(model.namespace.index(row.key)) + '=Some(' + stored + ');'
    return 'native_at((||->Result<(),String>{' + body + 'Ok(())})(),0,("<string>","<module>"))'
