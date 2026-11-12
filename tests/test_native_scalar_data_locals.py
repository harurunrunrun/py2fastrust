"""Loop snapshots keep aliases, source mutations and escaping bindings correct."""
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_scalar_data_locals as snapshots
import test_native_source_state as state_tests


PREFIX='''class Number:
    def __init__(self, value):
        self.value = value
    def increase(self):
        self.value += 1
    def read(self):
        return self.value
    def __add__(self, right):
        return Number(self.value + right.value)
    def __sub__(self, right):
        return Number(self.value - right.value)
seed = Number(0)
seed.increase()
'''

SOURCE=PREFIX+'''def run(items):
    for i in range(len(items) // 2):
        left = items[2 * i]
        right = items[2 * i + 1] + seed
        items[2 * i] = left + right
        items[2 * i + 1] = Number(left.read() - right.read())
items = [Number(i) for i in range(8)]
held = items[0]
run(items)
held.increase()
print([item.value for item in items], held.value)
'''

MUTATION=PREFIX+'''def mutate(item):
    item.increase()
    return Number(item.value)
def run(items):
    for i in range(len(items)):
        left = items[i]
        right = mutate(items[i])
        items[i] = left + right
items = [Number(i) for i in range(4)]
run(items)
print([item.value for item in items])
'''

AFTER=PREFIX+'''def run(items, count):
    last = Number(90)
    for i in range(count):
        last = items[i]
        items[i] = last + seed
    return last.value
items = [Number(i) for i in range(4)]
print(run(items, 0), run(items, 4), [item.value for item in items])
'''

CAPTURE=PREFIX+'''def run(items):
    saved = []
    for i in range(len(items)):
        left = items[i]
        def read():
            return left.value
        saved.append(read)
        items[i] = left + seed
    return [callback() for callback in saved]
items = [Number(i) for i in range(4)]
print(run(items))
'''

BEFORE=PREFIX+'''def run(items):
    for i in range(len(items)):
        print(left.value)
        left = items[i]
items = [Number(3)]
run(items)
'''

TRUTH=PREFIX.replace('    def __add__(self, right):\n',
    '    def __add__(self, right):\n        if switch:\n            pass\n')+'''switch = seed
def run(items):
    for i in range(len(items)):
        left = items[i]
        right = left + seed
        items[i] = left + right
items = [seed, Number(3)]
run(items)
print([item.value for item in items], seed.value)
'''

OWNED=PREFIX+'''def solve():
    items = [Number(i) for i in range(4)]
    for i in range(4):
        left = items[i]
        right = items[0] + seed
        items[i] = left + right
    print([item.value for item in items])
solve()
'''

MIXED='''class Reading:
    def __init__(self, amount, enabled):
        self.amount = amount
        self.enabled = enabled
    def flip(self):
        self.enabled = not self.enabled
    def __add__(self, right):
        return Reading(self.amount + right.amount, self.enabled or right.enabled)
seed = Reading(0.5, False)
seed.flip()
def run(items):
    for i in range(len(items)):
        left = items[i]
        right = items[i] + seed
        items[i] = left + right
items = [Reading(1.25, False), Reading(3.75, True)]
held = items[0]
run(items)
held.flip()
print([(item.amount, item.enabled) for item in items], held.amount, held.enabled)
'''


class NativeScalarDataLocalTests(unittest.TestCase):
    def models(self,source):
        models=[];original=snapshots.prepare
        def prepare(model):original(model);models.append(model)
        with patch.object(snapshots,'prepare',prepare):
            result=transpile(source,TranspileOptions(license='none'))
        self.assertTrue(result.success,result.diagnostics)
        return models[-1],result

    def test_iteration_private_readonly_bindings_use_concrete_payloads(self):
        model,result=self.models(SOURCE)
        names={name for _,name in model.scalar_data_locals.locals}
        self.assertTrue({'left','right'}<=names)
        self.assertIn('Option<ClassData_',result.rust_source)

    def test_existing_mutation_or_escape_declines_snapshots(self):
        for source in (MUTATION,AFTER,CAPTURE,BEFORE,TRUTH):
            model,_=self.models(source)
            self.assertFalse(model.scalar_data_locals.locals)

    def test_aliases_mutations_zero_trip_and_captures_in_all_integer_modes(self):
        sources={'local_data_aliases':SOURCE,'local_data_mutation':MUTATION,
                 'local_data_after':AFTER,'local_data_capture':CAPTURE,
                 'local_data_before':BEFORE,'local_data_truth':TRUTH,'local_data_owned':OWNED,
                 'local_data_mixed':MIXED}
        with patch.dict(state_tests.SOURCES,sources):
            for name in sources:
                with self.subTest(name=name):
                    state_tests.NativeSourceStateExecutionTests.exercise(self,name,('',))


if __name__=='__main__':unittest.main()
