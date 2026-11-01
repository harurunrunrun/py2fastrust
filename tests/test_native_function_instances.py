"""Each executed nested definition retains its identity and default payload."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions
CASES={'keyword_defaults_varargs': 'def make():\n'
                             ' functions=[]\n'
                             ' for i in range(3):\n'
                             '  def read(*values,scale=i):return '
                             'sum(values)+scale\n'
                             '  functions.append(read)\n'
                             ' return functions\n'
                             'a,b,c=make()\n'
                             'print(a(1,2),b(1,2),c(1,2),b(1,scale=10))\n',
 'positional_only_defaults': 'def make():\n'
                             ' functions=[]\n'
                             ' for i in range(3):\n'
                             '  def read(x=i,/,*,y=i+10):return x+y\n'
                             '  functions.append(read)\n'
                             ' return functions\n'
                             'a,b,c=make()\n'
                             'print(a(),b(),c(),a(100,y=3))\n',
 'mutable_defaults': 'def make():\n'
                     ' functions=[]\n'
                     ' for i in range(2):\n'
                     '  def read(value,items=[]):\n'
                     '   items.append(value)\n'
                     '   return items\n'
                     '  functions.append(read)\n'
                     ' return functions\n'
                     'a,b=make()\n'
                     'print(a(1),b(2),a(3),b(4))\n',
 'getter_keeps_binding': 'def make():\n'
                         ' for i in range(3):\n'
                         '  def current(x=i):return x\n'
                         ' def getter():return current\n'
                         ' return getter\n'
                         'getter=make()\n'
                         'a=getter()\n'
                         'b=getter()\n'
                         'print(a(),b(),a is b)\n',
 'definition_failure_effects': 'def mark(x):\n'
                               ' print("default",x)\n'
                               ' return x\n'
                               'def make():\n'
                               ' for i in range(3):\n'
                               '  def current(value=mark(i),other=int("bad") '
                               'if i==1 else 0):return value+other\n'
                               '  print(current())\n'
                               'make()\n',
 'definition_failure_preserves_old': 'saved=[]\n'
                                     'def build(_):\n'
                                     ' for i in range(3):\n'
                                     '  def current(value=next(iter(())) if '
                                     'i==1 else i):return value\n'
                                     '  saved.append(current)\n'
                                     '  saved.append(lambda:current())\n'
                                     'print(list(map(build,[0])))\n'
                                     'print([read() for read in saved])\n',
 'shared_default_item_identity': 'def make(values):\n'
                                 ' functions=[]\n'
                                 ' for i in range(2):\n'
                                 '  def read(item=values[i]):return item\n'
                                 '  functions.append(read)\n'
                                 ' return functions\n'
                                 'values=[[1],[2]]\n'
                                 'a,b=make(values)\n'
                                 'a().append(7)\n'
                                 'print(values,a() is values[0],b() is '
                                 'values[1])\n',
 'nonlocal_counter': 'def make():\n'
                     ' state=0\n'
                     ' functions=[]\n'
                     ' for i in range(3):\n'
                     '  def add(x=i):\n'
                     '   nonlocal state\n'
                     '   state+=x\n'
                     '   return state\n'
                     '  functions.append(add)\n'
                     ' return functions\n'
                     'a,b,c=make()\n'
                     'print(a(),b(),c(),a(5),b())\n',
 'legacy_immediate_key_loop': 'from functools import cmp_to_key\n'
                              'def solve(values):\n'
                              ' for direction in (1,-1):\n'
                              '  def compare(a,b):return direction*(a-b)\n'
                              '  '
                              'values=sorted(values,key=cmp_to_key(compare))\n'
                              ' return values\n'
                              'print(solve([3,1,2]))\n',
 'legacy_default_key_loop': 'from functools import cmp_to_key\n'
                            'def solve(values):\n'
                            ' for direction in (1,-1):\n'
                            '  def compare(a,b,direction=direction):return '
                            'direction*(a-b)\n'
                            '  values=sorted(values,key=cmp_to_key(compare))\n'
                            ' return values\n'
                            'print(solve([3,1,2]))\n',
 'legacy_saved_factories': 'from functools import cmp_to_key\n'
                           'def keys():\n'
                           ' result=[]\n'
                           ' for direction in (1,-1):\n'
                           '  def compare(a,b,direction=direction):return '
                           'direction*(a-b)\n'
                           '  result.append(cmp_to_key(compare))\n'
                           ' return result\n'
                           'for key in keys():print(sorted([3,1,2],key=key))\n',
 'legacy_direct_repeated_call': 'def solve():\n'
                                ' result=[]\n'
                                ' for i in range(3):\n'
                                '  def value():return i\n'
                                '  result.append(value())\n'
                                ' return result\n'
                                'print(solve())\n',
 'legacy_per_definition_identity': 'def solve():\n'
                                   ' result=[]\n'
                                   ' previous=None\n'
                                   ' for i in range(3):\n'
                                   '  def value():return i\n'
                                   '  result.append(value is previous)\n'
                                   '  previous=value\n'
                                   ' return result\n'
                                   'print(solve())\n',
 'legacy_late_binding_saved_functions': 'def solve():\n'
                                        ' result=[]\n'
                                        ' for i in range(3):\n'
                                        '  def value():return i\n'
                                        '  result.append(value)\n'
                                        ' return result\n'
                                        'for callback in '
                                        'solve():print(callback())\n'}
CYCLE_SOURCE='def make():\n state=7\n for i in range(2):\n  def current(read=lambda:state):return read()\n return current\nprint(make()())\n'
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class FunctionInstances(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_keyword_defaults_varargs(self):self.check('keyword_defaults_varargs')
    def test_positional_only_defaults(self):self.check('positional_only_defaults')
    def test_mutable_defaults(self):self.check('mutable_defaults')
    def test_getter_keeps_binding(self):self.check('getter_keeps_binding')
    def test_definition_failure_effects(self):self.check('definition_failure_effects')
    def test_definition_failure_preserves_old(self):self.check('definition_failure_preserves_old')
    def test_shared_default_item_identity(self):self.check('shared_default_item_identity')
    def test_nonlocal_counter(self):self.check('nonlocal_counter')
    def test_legacy_immediate_key_loop(self):self.check('legacy_immediate_key_loop')
    def test_legacy_default_key_loop(self):self.check('legacy_default_key_loop')
    def test_legacy_saved_factories(self):self.check('legacy_saved_factories')
    def test_legacy_direct_repeated_call(self):self.check('legacy_direct_repeated_call')
    def test_legacy_per_definition_identity(self):self.check('legacy_per_definition_identity')
    def test_legacy_late_binding_saved_functions(self):self.check('legacy_late_binding_saved_functions')

class DefaultOwnership(unittest.TestCase):
    def test_default_closure_environment_cycle_remains_explicit(self):
        result=transpile(CYCLE_SOURCE,TranspileOptions(filename="default_cycle.py",license="none"))
        self.assertFalse(result.success)
        self.assertIn("captured object/function fields can form a reference cycle",result.diagnostics[0].message)
