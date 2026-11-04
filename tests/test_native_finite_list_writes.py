"""Builtin finite receiver stores preserve actual target and operand order."""
import ast
import re
import shutil
import subprocess
import sys
import unittest

from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
import test_native_iterator_reductions as _execution

CASES = {'augmented_rhs_mutation': ('def change(row):\n'
                            ' print("rhs")\n'
                            ' row[0]=20\n'
                            ' return 3\n'
                            'def main():\n'
                            ' row=[1]\n'
                            ' owners=[row,"text"]\n'
                            ' other=owners[0]\n'
                            ' other[0]+=change(row)\n'
                            ' print(row,other[0])\n'
                            'main()\n',
                            ''),
 'bool_index': ('def main():\n'
                ' row=[1,2]\n'
                ' owners=[row,"text"]\n'
                ' other=owners[0]\n'
                ' other[True]=7\n'
                ' print(row)\n'
                'main()\n',
                ''),
 'bounds_error': ('def main():\n'
                  ' row=[1,2]\n'
                  ' owners=[row,"text"]\n'
                  ' other=owners[0]\n'
                  ' other[-3]=7\n'
                  ' print(row)\n'
                  'main()\n',
                  ''),
 'capture_owner_before_index': ('def replace(owners):\n'
                                ' print("index")\n'
                                ' owners[0]=[20]\n'
                                ' return 0\n'
                                'def main():\n'
                                ' row=[1]\n'
                                ' owners=[row,"text"]\n'
                                ' other=owners[0]\n'
                                ' other[replace(owners)]=7\n'
                                ' print(row,owners[0])\n'
                                'main()\n',
                                ''),
 'float_index_error': ('def main():\n'
                       ' row=[1,2]\n'
                       ' owners=[row,"text"]\n'
                       ' other=owners[0]\n'
                       ' other[1.0]=7\n'
                       ' print(row)\n'
                       'main()\n',
                       ''),
 'integer_target_error': ('def main():\n'
                          ' row=[1]\n'
                          ' owners=[row,12]\n'
                          ' other=owners[int(input())]\n'
                          ' other[0]=8\n'
                          ' print(row)\n'
                          'main()\n',
                          '1\n'),
 'nested_child_alias': ('def main():\n'
                        ' row=[1]\n'
                        ' record=[row,"child"]\n'
                        ' other=record[0]\n'
                        ' other[0]=8\n'
                        ' print(row[0],record[0][0],record[1])\n'
                        'main()\n',
                        ''),
 'none_target_error': ('def mark(label,value):\n'
                       ' print(label)\n'
                       ' return value\n'
                       'def main():\n'
                       ' row=[1]\n'
                       ' owners=[row,None]\n'
                       ' other=owners[int(input())]\n'
                       ' other[mark("index",0)]=mark("rhs",9)\n'
                       'main()\n',
                       '1\n'),
 'selected_list': ('def rhs():\n'
                   ' print("rhs")\n'
                   ' return 9\n'
                   'def main():\n'
                   ' row=[1,2]\n'
                   ' owners=[row,"text"]\n'
                   ' other=owners[int(input())]\n'
                   ' other[0]=rhs()\n'
                   ' print(row,other)\n'
                   'main()\n',
                   '0\n'),
 'selected_text_error': ('def rhs():\n'
                         ' print("rhs")\n'
                         ' return 9\n'
                         'def index():\n'
                         ' print("index")\n'
                         ' return 0\n'
                         'def main():\n'
                         ' row=[1,2]\n'
                         ' owners=[row,"text"]\n'
                         ' other=owners[int(input())]\n'
                         ' other[index()]=rhs()\n'
                         ' print(row)\n'
                         'main()\n',
                         '1\n'),
 'shared_leaf_identity': ('def main():\n'
                          ' leaf=[1]\n'
                          ' row=[leaf]\n'
                          ' owners=[row,"text"]\n'
                          ' other=owners[0]\n'
                          ' other[0]=leaf\n'
                          ' leaf.append(2)\n'
                          ' print(row[0] is leaf,other[0],leaf)\n'
                          'main()\n',
                          ''),
 'string_index_error': ('def main():\n'
                        ' row=[1,2]\n'
                        ' owners=[row,"text"]\n'
                        ' other=owners[0]\n'
                        ' other["0"]=7\n'
                        ' print(row)\n'
                        'main()\n',
                        ''),
 'tuple_target_error': ('def main():\n'
                        ' row=[1]\n'
                        ' owners=[row,(2,)]\n'
                        ' other=owners[int(input())]\n'
                        ' other[0]=8\n'
                        ' print(row)\n'
                        'main()\n',
                        '1\n'),
 'two_list_element_carriers': ('def main():\n'
                               ' numbers=[1]\n'
                               ' labels=["a"]\n'
                               ' owners=[numbers,labels,None]\n'
                               ' other=owners[int(input())]\n'
                               ' other[0]=7\n'
                               ' print(numbers,labels)\n'
                               'main()\n',
                               '1\n'),
 'widen_child_element': ('def main():\n'
                         ' row=[1]\n'
                         ' owners=[row,"text"]\n'
                         ' other=owners[0]\n'
                         ' other[0]="changed"\n'
                         ' print(row,other)\n'
                         'main()\n',
                         '')}


class FiniteListWriteSelectionTests(unittest.TestCase):
    def test_dynamic_and_unresolved_receivers_select_before_emission(self):
        for name in ('selected_list', 'augmented_rhs_mutation'):
            source, _ = CASES[name]
            unit = build_program(source, 'case.py').main
            original = ast.dump(unit.tree, include_attributes=True)
            for mode in ('i64', 'i128', 'bigint'):
                selected = select_frames(unit, integer=mode)
                self.assertIn('finite builtin indexed assignment targets', selected.reasons)
            self.assertEqual(ast.dump(unit.tree, include_attributes=True), original)
            unit.check_identity(source, 'case.py')

    def test_uniform_array_keeps_its_ordinary_selection(self):
        source = 'values=[1,2]\nvalues[0]=7\nprint(values)\n'
        selection = select_frames(build_program(source, 'case.py').main)
        self.assertNotIn('finite builtin indexed assignment targets', selection.reasons)


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class FiniteListWriteExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = _execution.NativeIteratorReductionTests()
        cls.harness.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.harness.tearDownClass()

    def check(self, *names):
        for name in names:
            source, data = CASES[name]
            expected = subprocess.run([sys.executable, '-I', '-c', source], input=data,
                                      capture_output=True, text=True, timeout=10)
            for mode in ('i64', 'i128', 'bigint'):
                for release in (False, True):
                    with self.subTest(case=name, integer=mode, optimized=release):
                        compiled = self.harness.compile(source, mode, release=release)
                        binary = compiled[1]
                        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=10)
                        self.assertEqual(actual.stdout, expected.stdout)
                        self.assertEqual(actual.returncode, expected.returncode)
                        if expected.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1], expected.stderr.splitlines()[-1])
                            frames = r'File "[^"]+", line (\d+), in ([^\n]+)'
                            self.assertEqual(re.findall(frames, actual.stderr), re.findall(frames, expected.stderr))

    def test_shared_nested_children_keep_identity(self):
        self.check('nested_child_alias', 'shared_leaf_identity')

    def test_receiver_capture_precedes_index_and_store(self):
        self.check('selected_list', 'capture_owner_before_index')

    def test_immutable_receivers_fail_after_operand_effects(self):
        self.check('selected_text_error', 'none_target_error', 'tuple_target_error', 'integer_target_error')

    def test_index_types_bounds_and_boolean_index(self):
        self.check('bool_index', 'string_index_error', 'float_index_error', 'bounds_error')

    def test_augmented_read_precedes_rhs_and_store(self):
        self.check('augmented_rhs_mutation')

    def test_per_list_destination_can_widen_without_copying(self):
        self.check('widen_child_element', 'two_list_element_carriers')


if __name__ == '__main__':
    unittest.main()
