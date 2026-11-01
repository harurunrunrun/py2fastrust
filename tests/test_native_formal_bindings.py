import unittest
import test_native_class_iterators as iterator_tests

CASES={'branch_rebinding': 'def choose(values,flag):\n'
                     ' if flag:values="changed"\n'
                     ' return values\n'
                     'print(choose([1],False),choose([2],True))\n',
 'copy_does_not_rebind_formal': 'def read(values):\n'
                                ' copy=values.copy()\n'
                                ' copy.append(9)\n'
                                ' return len(values),len(copy)\n'
                                'print(read([1,2]))\n',
 'delete_formal_preserves_alias': 'def take(values):\n'
                                  ' old=values\n'
                                  ' del values\n'
                                  ' return old\n'
                                  'a=[1]\n'
                                  'print(take(a),a)\n',
 'mutation_then_rebinding': 'def change(values):\n'
                            ' values.append(2)\n'
                            ' values="done"\n'
                            ' return values\n'
                            'a=[1]\n'
                            'print(change(a),a)\n',
 'named_expression_formal': 'def choose(values,flag):\n'
                            ' if flag:(values:="changed")\n'
                            ' return values\n'
                            'print(choose([1],False),choose([2],True))\n',
 'nullable_default_rebinding': 'def choose(values=None):\n'
                               ' if values is None:values=[1]\n'
                               ' return values\n'
                               'print(choose(),choose([2]))\n',
 'scalar_rebinding_keeps_ordinary_path': 'def change(value):\n'
                                         ' value="changed"\n'
                                         ' return value\n'
                                         'print(change(3))\n',
 'shadowed_inner_formal': 'def read(values):\n'
                          ' def inner(values):return len(values)\n'
                          ' return inner(values)\n'
                          'print(read([1,2]))\n',
 'unreached_rebinding': 'def unused(values):\n values="changed"\n return values\nprint(3)\n',
 'zero_trip_formal_target': 'def choose(values,count):\n'
                            ' for values in range(count):pass\n'
                            ' return values\n'
                            'print(choose([1],0),choose([2],2))\n'}

class FormalBindingTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_branch_rebinding(self):self.check('branch_rebinding')

    def test_zero_trip_formal_target(self):self.check('zero_trip_formal_target')

    def test_delete_formal_preserves_alias(self):self.check('delete_formal_preserves_alias')

    def test_mutation_then_rebinding(self):self.check('mutation_then_rebinding')

    def test_nullable_default_rebinding(self):self.check('nullable_default_rebinding')

    def test_shadowed_inner_formal(self):self.check('shadowed_inner_formal')

    def test_copy_does_not_rebind_formal(self):self.check('copy_does_not_rebind_formal')

    def test_unreached_rebinding(self):self.check('unreached_rebinding')

    def test_scalar_rebinding_keeps_ordinary_path(self):self.check('scalar_rebinding_keeps_ordinary_path')

    def test_named_expression_formal(self):self.check('named_expression_formal')

    def test_preselection_uses_reached_lexical_formal_writes(self):
        from py2fastrust.frontend import parse_source
        from py2fastrust.native_frame_selection import select_frames
        for name in ('branch_rebinding','zero_trip_formal_target','delete_formal_preserves_alias','mutation_then_rebinding','nullable_default_rebinding','named_expression_formal'):
            self.assertIn('container formal binding changes',select_frames(parse_source(CASES[name],name+'.py')).reasons,name)
        for name in ('shadowed_inner_formal','copy_does_not_rebind_formal','unreached_rebinding','scalar_rebinding_keeps_ordinary_path'):
            self.assertNotIn('container formal binding changes',select_frames(parse_source(CASES[name],name+'.py')).reasons,name)
