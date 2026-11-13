"""Canonical builtin list extension preserves ordered iterable protocols."""
import unittest
import test_native_annotations_assertions as support
from py2fastrust import TranspileOptions, transpile

CASES = {
    'range_tuple_and_text': ('''values = [9]
values.extend(range(2, 9, 3))
values.extend((True, 12, 'tail'))
print(values)
letters = []
letters.extend('Az')
print(letters)
octets = []
octets.extend(b'a\\x00z')
print(octets)
''', ('',)),
    'map_callback_sees_partial_mutation': ('''values = [10]
def transform(value):
 print(value, values)
 return value + 1
values.extend(map(transform, (2, 4, 6)))
print(values)
''', ('',)),
    'filter_callback_mutates_receiver': ('''values = [0]
def keep(value):
 values.append(-value)
 return value % 2
values.extend(filter(keep, range(1, 5)))
print(values)
''', ('',)),
    'generator_failure_retains_partial_extension': ('''values = [5]
def items():
 yield 7
 print(values)
 yield 9
 raise ValueError('finished badly')
try:
 values.extend(items())
except ValueError as error:
 print(str(error), values)
''', ('',)),
    'source_iteration_then_original_length': ('''values = [1]
class Items:
 def __iter__(self):
  print('iter', values)
  values.append(2)
  return iter((7, 8))
 def __len__(self):
  print('len', values)
  values.append(3)
  return 2
values.extend(Items())
print(values)
''', ('',)),
    'length_typeerror_is_suppressed': ('''class Items:
 def __iter__(self):
  print('iter')
  return iter((4, 6))
 def __len__(self):
  print('len')
  raise TypeError('no length')
values = [1]
values.extend(Items())
print(values)
''', ('',)),
    'negative_length_prevents_pulls': ('''class Items:
 def __iter__(self):
  print('iter')
  return iter((4, 6))
 def __len__(self):
  print('len')
  return -1
values = [1]
try:
 values.extend(Items())
except ValueError as error:
 print(str(error), values)
''', ('',)),
    'captured_receiver_survives_argument_rebind': ('''values = [1]
old = values
def argument():
 global values
 values = [99]
 print('argument')
 return (2, 3)
values.extend(argument())
print(old, values)
''', ('',)),
    'shared_mutable_tuple_elements': ('''row = [1]
values = [row]
values.extend((row, row))
row.append(7)
print(values, values[0] is values[1], values[1] is values[2])
''', ('',)),
    'finite_iterable_alternatives': ('''def choose(flag):
 if flag:
  return (2, 4)
 return range(1, 5, 2)
values = [0]
values.extend(choose(int(input())))
print(values)
''', ('0\n', '1\n')),
    'noniterable_error_after_argument_effect': ('''values = [1]
def argument():
 print('argument')
 return 7
try:
 values.extend(argument())
except TypeError as error:
 print(str(error), values)
''', ('',)),
    'self_extension_and_empty_live_cursor': ('''values = [1, 2]
values.extend(values)
print(values)
empty = []
empty.extend(iter(empty))
print(empty)
''', ('',)),
    'callback_failure_stops_before_append': ('''values = [3]
def divide(value):
 print(value, values)
 return 12 // value
try:
 values.extend(map(divide, (2, 0, 4)))
except ZeroDivisionError as error:
 print(str(error), values)
''', ('',)),
}

BOUNDARIES = {
    'custom_length_hint': '''class Items:
 def __iter__(self):return iter((3, 4))
 def __length_hint__(self):
  print('hint')
  return 2
values = [1]
values.extend(Items())
print(values)
''',
}

# These original CP-first witnesses retain pre-existing suspended raise / try
# boundaries. Uncaught variants below independently verify failure semantics.
BOUNDARY_NAMES = frozenset({
    'generator_failure_retains_partial_extension',
    'negative_length_prevents_pulls',
    'noniterable_error_after_argument_effect',
    'callback_failure_stops_before_append',
})

SUPPLEMENTAL = {
    'generator_arithmetic_failure': ('''values = [5]
def items():
 yield 7
 print(values)
 yield 12 // int(input())
values.extend(items())
print(values)
''', ('0\n', '3\n')),
    'negative_length_uncaught': ('''class Items:
 def __iter__(self):
  print('iter')
  return iter((4, 6))
 def __len__(self):
  print('len')
  return -1
values = [1]
values.extend(Items())
''', ('',)),
    'noniterable_uncaught': ('''values = [1]
def argument():
 print('argument', values)
 return 7
values.extend(argument())
''', ('',)),
    'callback_failure_uncaught': ('''values = [3]
def divide(value):
 print(value, values)
 return 12 // value
values.extend(map(divide, (2, 0, 4)))
''', ('',)),
    'wrong_arity_preserves_argument_effects': ('''values = [1]
def argument(value):
 print(value, values)
 return (value,)
values.extend(argument(2), argument(3))
''', ('',)),
    'keyword_rejection_preserves_argument_effects': ('''values = [1]
def argument():
 print('argument')
 return (2,)
values.extend(iterable=argument())
''', ('',)),
    'range_length_capacity_failure': ('''values = []
values.extend(range(9223372036854775807))
''', ('',)),
}

INDEPENDENT = {'length_rebind_owner': ("values=[1]\nold=values\nclass Items:\n def __iter__(self):return iter((4,5))\n def __len__(self):\n  global values\n  values=[99]\n  print('length',old,values)\n  return 2\nvalues.extend(Items())\nprint(old,values)\n", ('',)), 'generator_live_list_changes': ('values=[1,2,3]\ndef items():\n for value in values:\n  print(value,values)\n  if len(values)>3:values.clear()\n  yield value+10\nvalues.extend(items())\nprint(values)\n', ('',)), 'cursor_advance_and_zip': ('values=[]\nstream=iter((2,4,6))\nprint(next(stream))\nvalues.extend(stream)\nprint(values)\npairs=[]\npairs.extend(enumerate(zip((2,3),(4,5)),7))\nprint(pairs)\n', ('',)), 'range_length_overflow': ('values=[1]\nvalues.extend(range(-9223372036854775807,9223372036854775807))\n', ('',)), 'retained_expression': ('values=[1]\nstream=(x*x for x in range(4) if x%2)\nvalues.extend(stream)\nprint(values,list(stream))\n', ('',)), 'noncanonical_user_extend': ("class Custom:\n def extend(self,value):\n  print('own',value)\n  return 7\nprint(Custom().extend((2,3)))\n", ('',))}

OWNERSHIP = {'owned_vec_extension': ('def build(n):\n values=[]\n values.extend(range(n))\n values.extend((n,n+1))\n return values\nprint(build(int(input())))\n', ('0\n', '4\n')), 'owned_vec_argument_observes_previous_values': ('def solve():\n values=[2,3]\n values.extend(range(values[0],values[-1]+3))\n print(values[-1],len(values))\nsolve()\n', ('',)), 'alias_forces_shared_storage': ('def solve():\n values=[2]\n alias=values\n def mutate(value):\n  alias.append(value+10)\n  return value\n values.extend(map(mutate,(4,6)))\n print(values,alias,values is alias)\nsolve()\n', ('',)), 'length_wrong_type_is_suppressed': ("class Items:\n def __iter__(self):return iter((4,5))\n def __len__(self):\n  print('length')\n  return 'not an index'\nvalues=[1]\nvalues.extend(Items())\nprint(values)\n", ('',))}

class ListExtendExecutionTests(unittest.TestCase):
    pass


class ListExtendBoundaryTests(unittest.TestCase):
    def test_original_suspended_raise_and_handlers_remain_positioned_boundaries(self):
        for name in sorted(BOUNDARY_NAMES):
            source = CASES[name][0]
            for integer in ('i64', 'i128', 'bigint'):
                with self.subTest(name=name, integer=integer):
                    result = transpile(source, TranspileOptions(integer=integer))
                    self.assertFalse(result.success)
                    self.assertTrue(any(d.code == 'E006' and d.line > 0
                        and ('exception handler' in d.message or 'source generator raise' in d.message)
                        for d in result.diagnostics), result.diagnostics)

    def test_custom_hint_never_silently_skips_its_callback(self):
        for integer in ('i64', 'i128', 'bigint'):
            result = transpile(BOUNDARIES['custom_length_hint'], TranspileOptions(integer=integer))
            self.assertFalse(result.success)
            self.assertTrue(any(d.code == 'E006' and d.line == 3
                and '__length_hint__' in d.message for d in result.diagnostics), result.diagnostics)

    def test_reverse_cursor_hint_preserves_the_original_positive_case(self):
        source = 'values=[]\nvalues.extend(reversed((1,2,3)))\nprint(values)\n'
        support.AnnotationAndAssertionExecutionTests.compare(self, source, ('',))

    def test_callback_free_owned_extension_uses_a_vec_and_no_shared_cursor(self):
        source = OWNERSHIP['owned_vec_extension'][0]
        for integer in ('i64', 'i128', 'bigint'):
            result = transpile(source, TranspileOptions(integer=integer, license='none'))
            self.assertTrue(result.success, result.diagnostics)
            self.assertRegex(result.rust_source, r'let mut class_local_\d+:Option<Vec<NativeInt>>')
            self.assertNotIn('struct ClassIteratorState_', result.rust_source)

def _case(values):
    def test(self):
        support.AnnotationAndAssertionExecutionTests.compare(self, *values)
    return test

for _name in CASES:
    if _name not in BOUNDARY_NAMES:
        setattr(ListExtendExecutionTests, 'test_' + _name, _case(CASES[_name]))
for _name in SUPPLEMENTAL:
    setattr(ListExtendExecutionTests, 'test_' + _name, _case(SUPPLEMENTAL[_name]))

for _name in INDEPENDENT:
    setattr(ListExtendExecutionTests, 'test_' + _name, _case(INDEPENDENT[_name]))

for _name in OWNERSHIP:
    setattr(ListExtendExecutionTests, 'test_' + _name, _case(OWNERSHIP[_name]))

if __name__ == '__main__':
    unittest.main()
