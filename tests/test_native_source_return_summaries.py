import unittest
import test_native_class_iterators as iterator_tests

CASES={'branch_return_dependencies': 'def choose(condition,left,right):\n'
                               ' if condition:return left\n'
                               ' return right\n'
                               'a=choose(True,lambda x:x+1,lambda x:x+2)\n'
                               'b=choose(False,[1],[2])\n'
                               'print(a(5),b[0])\n',
 'default_and_keyword_binding': 'def identity(tag,value=3):\n'
                                ' print(tag)\n'
                                ' return value\n'
                                'print(identity("default"),identity(value="text",tag="keyword"))\n',
 'default_capture_identity': 'seed=[1]\n'
                             'def identity(value=seed):return value\n'
                             'seed=[9]\n'
                             'print(identity() is seed,identity(),identity("text").split("e"))\n',
 'fallthrough_is_none': 'def choose(condition,value):\n'
                        ' if condition:return value\n'
                        'print(choose(True,3),choose(False,4))\n',
 'identity_mixed_arguments': 'def mark(label,value):\n'
                             ' print(label)\n'
                             ' return value\n'
                             'f=mark("callback",lambda x:x+1)\n'
                             'values=mark("list",[3,4])\n'
                             'number=mark("int",7)\n'
                             'print(f(9),values[0],number+1)\n',
 'literal_return_alternatives': 'def choose(condition,value):\n'
                                ' if condition:return value\n'
                                ' return None\n'
                                'print(choose(True,3),choose(False,"text"))\n',
 'loop_rebinding_guard': 'def choose(value):\n'
                         ' for value in ["changed"]:pass\n'
                         ' return value\n'
                         'print(choose(3))\n',
 'loop_return_paths': 'def choose(values,seed):\n'
                      ' for value in values:\n'
                      '  if value:return seed\n'
                      ' return seed\n'
                      'print(choose([0,1],3),choose([],"text").split("e"))\n',
 'mutable_parameter_identity': 'def identity(value,item):\n'
                               ' value.append(item)\n'
                               ' return value\n'
                               'a=[]\n'
                               'b=identity(a,3)\n'
                               'print(a,b,b is a,identity(["x"],"y"))\n',
 'nested_nonlocal_write_not_projected': 'def convert(value):\n'
                                        ' def change():\n'
                                        '  nonlocal value\n'
                                        '  value="changed"\n'
                                        ' change()\n'
                                        ' return value\n'
                                        'print(convert(3))\n',
 'rebound_formal_not_projected': 'def convert(value):\n'
                                 ' value="changed"\n'
                                 ' return value\n'
                                 'print(convert(3),convert([1]))\n',
 'side_effect_error_preserved': 'def identity(value):\n'
                                ' print("before")\n'
                                ' print(1//0)\n'
                                ' return value\n'
                                'print(identity(3))\n'}

class ReturnSummaryTests(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_identity_mixed_arguments(self):self.check('identity_mixed_arguments')

    def test_branch_return_dependencies(self):self.check('branch_return_dependencies')

    def test_fallthrough_is_none(self):self.check('fallthrough_is_none')

    def test_default_capture_identity(self):self.check('default_capture_identity')

    def test_rebound_formal_not_projected(self):self.check('rebound_formal_not_projected')

    def test_nested_nonlocal_write_not_projected(self):self.check('nested_nonlocal_write_not_projected')

    def test_mutable_parameter_identity(self):self.check('mutable_parameter_identity')

    def test_default_and_keyword_binding(self):self.check('default_and_keyword_binding')

    def test_loop_return_paths(self):self.check('loop_return_paths')

    def test_loop_rebinding_guard(self):self.check('loop_rebinding_guard')

    def test_literal_return_alternatives(self):self.check('literal_return_alternatives')

    def test_side_effect_error_preserved(self):self.check('side_effect_error_preserved')


ADVERSARIAL_CASES={'alias_parameter_mutation_before_return': 'def mutate(value,other):\n'
                                           ' other.append("x")\n'
                                           ' return value\n'
                                           'a=[1]\n'
                                           'b=mutate(a,a)\n'
                                           'print(a,b,b is a)\n',
 'callback_mutation_before_return': 'def change(values):values.append("x")\n'
                                    'def mutate(value,callback):\n'
                                    ' callback(value)\n'
                                    ' return value\n'
                                    'a=[1]\n'
                                    'b=mutate(a,change)\n'
                                    'print(a,b,b is a)\n',
 'default_alias_mutation_before_return': 'seed=[1]\n'
                                         'def mutate(value,other=seed):\n'
                                         ' other.append("x")\n'
                                         ' return value\n'
                                         'result=mutate(seed)\n'
                                         'print(result,seed,result is seed)\n',
 'early_return_and_other_branch_effect': 'def mutate(condition,value):\n'
                                         ' if condition:return value\n'
                                         ' value.append("x")\n'
                                         ' return value\n'
                                         'a=[1]\n'
                                         'b=mutate(True,a)\n'
                                         'c=mutate(False,a)\n'
                                         'print(a,b,c,b is a,c is a)\n',
 'function_and_scalar_branch_family': 'def choose(condition,a,b):\n'
                                      ' if condition:return a\n'
                                      ' return b\n'
                                      'x=choose(True,lambda v:v+1,3)\n'
                                      'y=choose(False,[1],"text")\n'
                                      'print(x(4),y.split("e"))\n',
 'mixed_item_mutation_before_return': 'def mutate(value):\n'
                                      ' value.append("x")\n'
                                      ' return value\n'
                                      'a=[1]\n'
                                      'b=mutate(a)\n'
                                      'print(a,b,b is a)\n',
 'structured_return_family': 'def identity(value):return value\n'
                             'a=identity((3,"word"))\n'
                             'b=identity(("text",4))\n'
                             'c=identity(lambda x:x+1)\n'
                             'print(a[0]+2,a[1].split("o"),b[0].split("e"),b[1]+3,c(5))\n'}

class ReturnSummaryAdversarialTests(unittest.TestCase):
    cases=ADVERSARIAL_CASES
    check=iterator_tests.IteratorExecutionTests.check

    def test_mixed_item_mutation_before_return(self):self.check('mixed_item_mutation_before_return')

    def test_alias_parameter_mutation_before_return(self):self.check('alias_parameter_mutation_before_return')

    def test_default_alias_mutation_before_return(self):self.check('default_alias_mutation_before_return')

    def test_callback_mutation_before_return(self):self.check('callback_mutation_before_return')

    def test_early_return_and_other_branch_effect(self):self.check('early_return_and_other_branch_effect')

    def test_structured_return_family(self):self.check('structured_return_family')

    def test_function_and_scalar_branch_family(self):
        from py2fastrust import transpile,TranspileOptions
        for mode in ('i64','i128','bigint'):
            result=transpile(self.cases['function_and_scalar_branch_family'],TranspileOptions(integer=mode,license='none'))
            self.assertFalse(result.success)
            message=' '.join(str(value)for value in result.diagnostics)
            self.assertIn('y.split',message)
            self.assertIn('list[int] | str',message)



class ReturnSummaryProofTests(unittest.TestCase):
    def test_return_dependencies_and_lexical_rebinding_guards(self):
        import ast
        from types import SimpleNamespace
        from py2fastrust.frontend import parse_source
        from py2fastrust.native_source_returns import summary
        for name in ('rebound_formal_not_projected','nested_nonlocal_write_not_projected','loop_rebinding_guard'):
            unit=parse_source(CASES[name],name+'.py')
            node=next(value for value in unit.tree.body if isinstance(value,ast.FunctionDef))
            signature=unit.signature_for(node)
            model=SimpleNamespace(unit=unit)
            callee=SimpleNamespace(index=0,node=node,arguments=dict.fromkeys(signature.parameters),signature=signature)
            self.assertIsNone(summary(model,callee),name)
        for name,parameters,literals in [('branch_return_dependencies',{'left','right'},set()),('fallthrough_is_none',{'value'},{'none'}),('mutable_parameter_identity',{'value'},set()),('default_capture_identity',{'value'},set())]:
            unit=parse_source(CASES[name],name+'.py')
            node=next(value for value in unit.tree.body if isinstance(value,ast.FunctionDef))
            signature=unit.signature_for(node)
            model=SimpleNamespace(unit=unit)
            callee=SimpleNamespace(index=0,node=node,arguments=dict.fromkeys(signature.parameters),signature=signature)
            proof=summary(model,callee)
            self.assertIsNotNone(proof,name)
            self.assertEqual(proof.parameters,parameters,name)
            self.assertEqual(proof.literals,literals,name)
