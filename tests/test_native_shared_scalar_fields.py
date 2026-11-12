"""Shared scalar instances keep aliases while eliminating proved presence checks."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_packed_value_fields as packed
import test_native_source_state as state_tests


SOURCES = {
    'map_aliases': '''class Number:
    def __init__(self, value):
        self.base = 17
        if value == 0:
            self.value = 0
        else:
            self.value = value % self.base
    def read(self):
        return self.value
numbers = list(map(Number, [0, 23, 37]))
alias = numbers[1]
alias.value += 4
print(list(map(lambda item: item.read(), numbers)), alias is numbers[1])
''',
    'mutation_during_borrow': '''class Number:
    def __init__(self, value):
        self.value = value
def read(number, change):
    before = number.value
    change()
    return before, number.value
number = Number(7)
alias = number
def change():
    alias.value += 5
print(read(number, change), alias.value, alias is number)
''',
    'missing_branch': '''class Number:
    def __init__(self, value):
        if value:
            self.value = value
    def read(self):
        return self.value
number = Number(0)
alias = number
print(alias.read())
''',
    'deletion': '''class Number:
    def __init__(self, value):
        self.value = value
    def read(self):
        return self.value
number = Number(7)
alias = number
del alias.value
print(number.read())
''',
    'partly_initialized_escape': '''saved = []
class Number:
    def __init__(self, value):
        saved.append(self)
        self.value = value
    def read(self):
        return self.value
Number(13)
print(saved[0].read())
''',
}


def convert(source, integer='i64'):
    models = []
    original = packed.prepare
    def prepare(model):
        original(model)
        models.append(model)
    with patch.object(packed, 'prepare', prepare):
        result = transpile(source, TranspileOptions(integer=integer, license='none'))
    return result, models[-1] if models else None


class NativeSharedScalarFieldsTests(unittest.TestCase):
    def test_shared_aliases_pack_without_copying_the_object(self):
        for name in ('map_aliases', 'mutation_during_borrow'):
            for integer in ('i64', 'i128'):
                with self.subTest(name=name, integer=integer):
                    result, model = convert(SOURCES[name], integer)
                    self.assertTrue(result.success, result.diagnostics)
                    owner = next(owner for owner in model.classes.values()
                                 if owner.node.name == 'Number')
                    self.assertNotIn(owner.index, model.value_classes.selected)
                    self.assertIn(owner.index, model.packed_value_fields.selected)

    def test_missing_deleted_and_published_partial_instances_keep_checks(self):
        for name in ('missing_branch', 'deletion', 'partly_initialized_escape'):
            with self.subTest(name=name):
                result, model = convert(SOURCES[name])
                self.assertTrue(result.success, result.diagnostics)
                owner = next(owner for owner in model.classes.values()
                             if owner.node.name == 'Number')
                self.assertNotIn(owner.index, model.packed_value_fields.selected)

    def test_native_alias_mutation_and_errors_match_python(self):
        with patch.dict(state_tests.SOURCES, SOURCES):
            for name in SOURCES:
                with self.subTest(name=name):
                    state_tests.NativeSourceStateExecutionTests.exercise(self, name, ('',))


if __name__ == '__main__':
    unittest.main()
