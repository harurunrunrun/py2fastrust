"""Exact integer range proofs may narrow arithmetic without narrowing Python ints."""
import shutil
import unittest
import ast
from types import SimpleNamespace

from py2fastrust import transpile, TranspileOptions
from py2fastrust.native_scalar_constant_facts import Graph, Scalar, UNKNOWN
from py2fastrust.native_scalar_heap_constants import Registry
from py2fastrust.native_classes import Cell
from py2fastrust.frontend import build_program
import test_native_stdio as stdio_tests


class BoundedScalarContracts(unittest.TestCase):
    def test_unknown_integer_mod_has_range_but_unproved_operator_does_not(self):
        for bits in (64, 128):
            graph = Graph(bits)
            graph.unknown('value')
            graph.seed('modulus', 'int', 97)
            graph.add('closed', 'Mod', ('value', 'modulus'), 'closed_integer_operands')
            graph.add('unproved', 'Mod', ('value', 'modulus'))
            graph.finalize()
            self.assertEqual(graph.values['closed'], Scalar('int', 0, 96))
            self.assertIs(graph.values['unproved'], UNKNOWN)

    def test_negative_mod_and_batched_literal_bounds(self):
        graph = Graph(128)
        graph.unknown('value')
        graph.seed('modulus', 'int', -97)
        graph.add('residue', 'Mod', ('value', 'modulus'), 'closed_integer_operands')
        for index in range(40):
            graph.seed(('item', index), 'int', index - 20)
        graph.add('elements', 'join', tuple(('item', index) for index in range(40)))
        graph.finalize()
        self.assertEqual(graph.values['residue'], Scalar('int', -96, 0))
        self.assertEqual(graph.values['elements'], Scalar('int', -20, 19))

    def test_unknown_heap_writer_is_not_discarded_by_batched_bounds(self):
        graph = Graph(128)
        graph.seed('literal', 'int', 3)
        graph.unknown('write')
        graph.add('elements', 'join', ('literal', 'write'))
        graph.finalize()
        self.assertIs(graph.values['elements'], UNKNOWN)

    def test_range_and_shift_intervals_preserve_wrap_boundary(self):
        graph = Graph(128)
        graph.unknown('input')
        graph.add('bounded', 'restrict_integer', ('input',), (0, 96))
        graph.seed('start', 'int', 1)
        graph.seed('step', 'int', 1)
        graph.seed('shift', 'int', 4)
        graph.add('stop', 'Add', ('bounded', 'step'))
        graph.add('items', 'range_items', ('start', 'stop', 'step'))
        graph.add('shifted', 'RShift', ('bounded', 'shift'))
        graph.seed('huge', 'int', 1 << 125)
        graph.add('wrapped_product', 'Mult', ('huge', 'bounded'))
        graph.finalize()
        self.assertEqual(graph.values['items'], Scalar('int', 1, 96))
        self.assertEqual(graph.values['shifted'], Scalar('int', 0, 6))
        self.assertIs(graph.values['wrapped_product'], UNKNOWN)


class GuardWriterBoundaryContracts(unittest.TestCase):
    """Exercise official AST/bindings even for unsupported control backends."""
    def bounds(self, body):
        source = 'def f(x):\n if x<0:return 0\n if x>=100:return 0\n'
        source += ''.join(' '+line+'\n' for line in body.splitlines())
        unit = build_program(source, 'guard_contract.py').main
        function = unit.tree.body[0]
        plan = SimpleNamespace(index=0, node=function)
        registry = Registry.__new__(Registry)
        registry.graph = Graph(128)
        registry.model = SimpleNamespace(unit=unit, records={})
        registry.source_plan = lambda item: item
        registry.binding_rows = unit.bindings
        registry.bindings = {binding.node: binding for binding in unit.bindings}
        registry.bindings_by_node = {}
        for binding in unit.bindings:
            registry.bindings_by_node.setdefault(binding.node, []).append(binding)
        registry.class_scopes = {}
        registry.guard_writes = {}
        registry.values = SimpleNamespace(parents={id(child): parent for parent in ast.walk(unit.tree)
                                                   for child in ast.iter_child_nodes(parent)})
        for node in ast.walk(unit.tree):
            if isinstance(node, ast.Name):
                registry.model.records[0, id(node)] = Cell('int')
        operation = next(node for node in ast.walk(function)
                         if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod))
        name = operation.left
        self.assertIsInstance(name, ast.Name)
        return registry.local_bounds(plan, name, registry.binding(plan, name))

    def test_scalar_left_operand_writer_blocks_outer_guards(self):
        self.assertIsNone(self.bounds('return (x := 1<<100) + x%998244353'))

    def test_dictionary_key_writer_blocks_value_guard(self):
        self.assertIsNone(self.bounds('return {(x := 1<<100): x%998244353}'))

    def test_call_positional_writer_blocks_keyword_guard(self):
        self.assertIsNone(self.bounds('return pack((x := 1<<100), second=x%998244353)'))

    def test_if_test_writer_blocks_outer_guards(self):
        self.assertIsNone(self.bounds('if (x := 1<<100):\n return x%998244353\nreturn 0'))

    def test_for_iterable_writer_blocks_outer_guards(self):
        self.assertIsNone(self.bounds('for index in range((x := 1<<100), (1<<100)+1):\n return x%998244353\nreturn 0'))

    def test_try_body_writer_blocks_finally_outer_guards(self):
        self.assertIsNone(self.bounds('try:\n x=1<<100\nfinally:\n print(x%998244353)\nreturn 0'))

    def test_with_item_writer_blocks_body_outer_guards(self):
        self.assertIsNone(self.bounds('with scope((x := 1<<100)):\n return x%998244353'))

    def test_match_subject_writer_blocks_case_outer_guards(self):
        self.assertIsNone(self.bounds('match (x := 1<<100):\n case value:\n  return x%998244353\nreturn 0'))

    def test_post_write_inner_guards_remain_eligible(self):
        body = '''if (x := int(input())):
 if x<0:return 0
 if x>=100:return 0
 return x%998244353
return 0'''
        self.assertEqual(self.bounds(body), (0, 99))

    def test_post_write_finally_guards_remain_eligible(self):
        body = '''try:
 x=1<<100
finally:
 if x<0:return 0
 if x>=100:return 0
 return x%998244353'''
        self.assertEqual(self.bounds(body), (0, 99))


def runner(body, prefix=''):
    return prefix + 'class Runner:\n def run(self,n):\n' + ''.join('  '+line+'\n' for line in body.splitlines()) + 'print(Runner().run(int(input())))\n'


@unittest.skipUnless(shutil.which('rustc'), 'rustc required')
class BoundedRemainderSourceTests(unittest.TestCase):
    setUpClass = classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass = classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile = stdio_tests.NativeStdioTests.compile
    differential = stdio_tests.NativeStdioTests.differential

    def check(self, source, inputs, *, narrow):
        result = transpile(source, TranspileOptions(integer='i128', filename='bounded.py', license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual(result.backend, 'native')
        self.assertEqual('wrapping_rem((97_i64))' in result.rust_source or
                         'wrapping_rem((-97_i64))' in result.rust_source, narrow)
        self.differential(source, inputs, modes=('i128',), profiles=(False, True))

    def test_guarded_factorial_and_zero_iterations(self):
        source = runner('''if n < 0:
 return -1
if n >= 97:
 print("large")
 return 0
now = 1
for j in range(1, n+1):
 now = now*j%97
return now''')
        self.check(source, [b'-1\n', b'0\n', b'1\n', b'19\n', b'96\n', b'97\n'], narrow=True)

    def test_literal_table_and_shifted_range(self):
        source = runner('''if n < 0:
 return -1
if n >= 97:
 return 0
section = n >> 4
now = table[section]
start = section << 4
for j in range(start+1, n+1):
 now = now*j%97
return now''', 'table=[3,1,4,1,5,9,2,6]\n')
        self.check(source, [b'0\n', b'1\n', b'31\n', b'96\n'], narrow=True)

    def test_negative_divisor_keeps_python_floor_remainder(self):
        source = runner('''if n < 0:
 return -1
if n >= 97:
 return 0
now = 1
for j in range(1,n+1):
 now = now*j%-97
return now''')
        self.check(source, [b'0\n', b'1\n', b'13\n', b'96\n'], narrow=True)

    def test_wide_pre_mod_product_is_not_inferred_from_its_small_result(self):
        source = runner('''if n < 0:
 return -1
if n >= 97:
 return 0
now = n
for j in range(1,4):
 now = now*4611686018427387904%97
return now''')
        self.check(source, [b'1\n', b'70\n'], narrow=False)

    def test_assignment_after_guard_invalidates_the_guard(self):
        source = runner('''if n < 97:
 n = 1180591620717411303424
 return n*31%97
return 0''')
        self.check(source, [b'1\n', b'100\n'], narrow=False)

    def test_loop_backedge_write_invalidates_an_outer_guard(self):
        source = runner('''if n < 0:
 return -1
if n >= 97:
 return 0
answer = 0
for j in range(2):
 answer += n*31%97
 n += 36893488147419103232
return answer''')
        self.check(source, [b'1\n', b'96\n'], narrow=False)

    def test_nonlocal_writer_disables_local_guard_certificate(self):
        source = runner('''if n < 0:
 return -1
if n >= 97:
 return 0
def change():
 nonlocal n
 n = 1180591620717411303424
change()
return n*31%97''')
        self.check(source, [b'1\n', b'96\n'], narrow=False)

    def test_literal_table_alias_mutation_contributes_all_values(self):
        source = runner('''if n < 0:
 return -1
if n >= 8:
 return 0
alias = table
alias[0] = 1180591620717411303424
now = table[n]
for j in range(1,4):
 now = now*j%97
return now''', 'table=[3,1,4,1,5,9,2,6]\n')
        self.check(source, [b'0\n', b'1\n'], narrow=False)

    def test_user_mod_result_is_not_assumed_to_be_a_residue(self):
        source = runner('''value = Weird()%97
return value*31%97''', '''class Weird:
 def __mod__(self,divisor):
  print("custom modulo")
  return 1180591620717411303424
''')
        self.check(source, [b'0\n'], narrow=False)

    def test_selected_i128_wrap_occurs_before_modulo(self):
        source = runner('''if n < 633825300114114700748351602688:
 return 0
if n > 1267650600228229401496703205376:
 return 0
return n*1125899906842624%97''')
        value = (1 << 99) + 123
        result = transpile(source, TranspileOptions(integer='i128', license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertNotIn('wrapping_rem((97_i64))', result.rust_source)
        wrapped = (value * (1 << 50)) % (1 << 128)
        if wrapped >= 1 << 127:
            wrapped -= 1 << 128
        expected = str(wrapped % 97).encode() + b'\n'
        import subprocess
        for release in (False, True):
            binary = self.compile(source, 'i128', release)
            actual = subprocess.run([str(binary)], input=str(value).encode()+b'\n', capture_output=True, timeout=5)
            self.assertEqual((actual.returncode, actual.stdout, actual.stderr), (0, expected, b''))


PEER_BINARY_LEFT_WALRUS = '''class Marker:
 def __init__(self):self.value=1
marker=Marker()
def f(x):
 if x<0:return 0
 if x>=100:return 0
 return (x := 1<<100) + x%998244353
print(f(int(input())))
'''
PEER_IF_TEST_WALRUS = '''class Marker:
 def __init__(self):self.value=1
marker=Marker()
def f(x):
 if x<0:return 0
 if x>=100:return 0
 if (x := 1<<100):return x%998244353
 return 0
print(f(int(input())))
'''


@unittest.skipUnless(shutil.which('rustc'), 'rustc required')
class GuardWriterExecutionTests(unittest.TestCase):
    setUpClass = classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass = classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile = stdio_tests.NativeStdioTests.compile
    differential = stdio_tests.NativeStdioTests.differential

    def check(self, source, inputs=(b'1\n', b'100\n'), *, narrow=False):
        result = transpile(source, TranspileOptions(integer='i128', filename='peer_case.py', license='none'))
        self.assertTrue(result.success, result.diagnostics)
        self.assertEqual('wrapping_rem((998244353_i64))' in result.rust_source, narrow)
        self.differential(source, inputs, modes=('i128',), profiles=(False, True))

    def test_exact_peer_binary_left_walrus(self):
        self.check(PEER_BINARY_LEFT_WALRUS)

    def test_exact_peer_if_test_walrus(self):
        self.check(PEER_IF_TEST_WALRUS)

    def test_dictionary_key_then_value(self):
        self.check(PEER_BINARY_LEFT_WALRUS.replace('return (x := 1<<100) + x%998244353',
                                                'return {(x := 1<<100): x%998244353}'))

    def test_call_positional_then_keyword(self):
        source = 'def pack(first,*,second):return first+second\n' + PEER_BINARY_LEFT_WALRUS.replace(
            'return (x := 1<<100) + x%998244353', 'return pack((x := 1<<100), second=x%998244353)')
        self.check(source)

    def test_for_iterable_writer(self):
        source = PEER_BINARY_LEFT_WALRUS.replace(' return (x := 1<<100) + x%998244353',
                                               ' for index in range((x := 1<<100), (1<<100)+1):\n  return x%998244353\n return 0')
        self.check(source)

    def test_with_context_prefix_writer(self):
        prefix = '''class Scope:
 def __init__(self,value):pass
 def __enter__(self):return self
 def __exit__(self,kind,value,trace):return False
'''
        source = prefix + PEER_BINARY_LEFT_WALRUS.replace(' return (x := 1<<100) + x%998244353',
                                                        ' with Scope((x := 1<<100)):\n  return x%998244353')
        self.check(source)

    def test_new_guards_after_if_test_writer(self):
        body = ''' if (x := int(input())):
  if x<0:return 0
  if x>=100:return 0
  return x%998244353
 return 0'''
        source = PEER_BINARY_LEFT_WALRUS.replace(' return (x := 1<<100) + x%998244353', body)
        self.check(source, (b'1\n3\n', b'1\n1267650600228229401496703205376\n', b'1\n0\n'), narrow=True)


@unittest.skipUnless(shutil.which('rustc'), 'rustc required')
class ConstantModuloEffectTests(unittest.TestCase):
    """A constant successful value never proves its producer is effect-free."""
    setUpClass = classmethod(stdio_tests.NativeStdioTests.setUpClass.__func__)
    tearDownClass = classmethod(stdio_tests.NativeStdioTests.tearDownClass.__func__)
    compile = stdio_tests.NativeStdioTests.compile
    differential = stdio_tests.NativeStdioTests.differential

    def test_constructor_keeps_noisy_input_and_next_read(self):
        source = '''def noisy():
 print("read")
 return int(input())
class Holder:
 def __init__(self):self.v=noisy()%1
holder=Holder()
print(holder.v,int(input()))
'''
        self.differential(source, (b'123\n456\n', b'-9\n7\n', b'invalid\n7\n'), profiles=(False, True))

    def test_setter_keeps_noisy_input_and_next_read(self):
        source = '''def noisy():
 print("read")
 return int(input())
class Holder:
 def __init__(self):self.v=0
 def assign(self):self.v=noisy()%1
holder=Holder()
holder.assign()
print(holder.v,int(input()))
'''
        self.differential(source, (b'123\n456\n', b'-9\n7\n', b'invalid\n7\n'), profiles=(False, True))

    def test_division_error_before_constant_modulo_is_retained(self):
        source = '''class Holder:
 def __init__(self,x):
  print("init")
  self.v=(10//x)%1
  print("assigned")
print("before")
holder=Holder(int(input()))
print(holder.v,int(input()))
'''
        self.differential(source, (b'0\n456\n', b'2\n456\n', b'-3\n7\n'), profiles=(False, True))

    def test_captured_local_keeps_noisy_input_and_next_read(self):
        source = '''def noisy():
 print("read")
 return int(input())
def make():
 stored=noisy()%1
 def get():return stored
 return get
get=make()
print(get(),int(input()))
'''
        self.differential(source, (b'123\n456\n', b'-9\n7\n', b'invalid\n7\n'), profiles=(False, True))


if __name__ == '__main__':
    unittest.main()
