"""Closed metadata transport and unsupported observable/dynamic values."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions
CASES={'source_class_parameter': 'from typing import cast,Tuple\n'
                           'class Outer:\n'
                           ' class Edge:pass\n'
                           'x=[Outer.Edge()]\n'
                           'y=cast(Tuple[int,Outer.Edge],x)\n'
                           'print(y is x,y[0] is x[0])\n',
 'source_class_parameter_error': 'from typing import cast,Tuple\n'
                                 'class Edge:pass\n'
                                 'print(cast(Tuple[(Edge,int),int],7))\n',
 'source_class_instance_hash_unobserved': 'from typing import cast,Tuple\n'
                                          'class Edge:\n'
                                          ' def __hash__(self):\n'
                                          '  print("instance hash")\n'
                                          '  return 1\n'
                                          'print(cast(Tuple[Edge,int],7))\n',
 'metadata_identity_transport': 'from typing import cast,Tuple\n'
                                'def forward(value):return value\n'
                                'Alias=forward(Tuple[int,str])\n'
                                'print(cast(Alias,7))\n',
 'union_scalar_allowed': 'from typing import cast,Union,Optional\n'
                         'print(cast(Union[42],7),cast(Optional[42],8))\n',
 'union_duplicate_type': 'from typing import cast,Union\n'
                         'print(cast(Union[int,int],7))\n',
 'callable_nontype_first_parameter': 'from typing import cast,Callable\n'
                                     'print(cast(Callable[42,str],7))\n',
 'builtin_forward_string_not_compiled': 'from typing import cast\n'
                                        'print(cast(list["("],7))\n',
 'builtin_generic_many_parameters': 'from typing import cast\n'
                                    'print(cast(list[int,str,bool],7))\n',
 'annotated_nested': 'from typing import cast,Annotated,List\n'
                     'Alias=Annotated[List[int],"outer",42]\n'
                     'print(cast(Alias,7))\n',
 'raw_alias_return': 'from typing import cast,Tuple\n'
                     'def alias():return Tuple\n'
                     'print(cast(alias(),7))\n',
 'keyword_binding_error_effects': 'from typing import cast,Tuple\n'
                                  'def mark(value):\n'
                                  ' print("value")\n'
                                  ' return value\n'
                                  'print(cast(Tuple[int,str],val=mark(7),unknown=mark(8)))\n',
 'function_type_parameter': 'from typing import cast,List\n'
                            'def choose():\n'
                            ' print("choose")\n'
                            ' return int\n'
                            'print(cast(List[choose()],7))\n',
 'container_transport': 'from typing import cast,Tuple\n'
                        'def select(pair):return pair[0]\n'
                        'print(cast(select((Tuple[int,str],9)),7))\n',
 'branch_receiver_dict': 'from typing import cast,List,Dict\n'
                         'Alias=List\n'
                         'if int(input()):Alias=Dict\n'
                         'print(cast(Alias[int,str],7))\n',
 'branch_receiver_list_error': 'from typing import cast,List,Dict\n'
                               'Alias=List\n'
                               'if int(input()):Alias=Dict\n'
                               'print(cast(Alias[int,str],7))\n',
 'branch_function_type': 'from typing import cast,List\n'
                         'kind=int\n'
                         'if int(input()):kind=str\n'
                         'print(cast(List[kind],7))\n',
 'captured_builtin_alias': 'from typing import cast\n'
                           'Kind=list\n'
                           'list=[1]\n'
                           'print(cast(Kind[int],7),list)\n',
 'source_type_same_name_distinct': 'from typing import cast,Tuple,Union\n'
                                   'class Old:pass\n'
                                   'Saved=Old\n'
                                   'class New:pass\n'
                                   'print(cast(Tuple[Saved,New],7),cast(Union[Saved,New],8))\n',
 'ellipsis_alias_parameter': 'from typing import cast,Tuple\n'
                             'Rest=Tuple[int,...]\n'
                             'print(cast(Rest,7))\n'}
GUARDS={'dynamic_forward_reference': 'from typing import cast,List\n'
                              'name=input()\n'
                              'print(cast(List[name],7))\n',
 'instance_hash_parameter': 'from typing import cast,List\n'
                            'class Edge:\n'
                            ' def __hash__(self):\n'
                            '  print("hash")\n'
                            '  return 1\n'
                            'print(cast(List[Edge()],7))\n',
 'observed_container': 'from typing import Tuple\n'
                       'pair=(Tuple[int,str],7)\n'
                       'print(pair)\n',
 'observed_return': 'from typing import Tuple\n'
                    'def alias():return Tuple[int,str]\n'
                    'print(alias())\n',
 'observed_equality': 'from typing import Tuple\n'
                      'Alias=Tuple[int,str]\n'
                      'print(Alias==Alias)\n',
 'observed_identity': 'from typing import Tuple\n'
                      'Alias=Tuple[int,str]\n'
                      'print(Alias is Alias)\n',
 'observed_attribute': 'from typing import Tuple\n'
                       'Alias=Tuple[int,str]\n'
                       'print(Alias.__args__)\n',
 'observed_callee': 'from typing import Tuple\n'
                    'Alias=Tuple[int,str]\n'
                    'print(Alias())\n',
 'observed_source_function': 'from typing import cast,Tuple\n'
                             'def observe(value):\n'
                             ' print(value)\n'
                             ' return value\n'
                             'print(cast(observe(Tuple[int,str]),7))\n',
 'dynamic_scalar_metadata': 'from typing import cast,Literal\n'
                            'value=int(input())\n'
                            'print(cast(Literal[value],7))\n',
 'alias_forwardref_rebound_string': 'from typing import cast,List\n'
                                    'name="int"\n'
                                    'name=input()\n'
                                    'print(cast(List[name],7))\n'}
INPUTS={'branch_receiver_dict': '1\n', 'branch_receiver_list_error': '0\n', 'branch_function_type': '1\n', 'dynamic_forward_reference': 'int\n', 'dynamic_scalar_metadata': '42\n', 'alias_forwardref_rebound_string': 'str\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class MetadataEdges(unittest.TestCase):
    cases=CASES
    inputs=INPUTS
    check=iterator_tests.IteratorExecutionTests.check
    def test_source_class_parameter(self):self.check('source_class_parameter')
    def test_source_class_parameter_error(self):self.check('source_class_parameter_error')
    def test_metadata_identity_transport(self):self.check('metadata_identity_transport')
    def test_union_scalar_allowed(self):self.check('union_scalar_allowed')
    def test_union_duplicate_type(self):self.check('union_duplicate_type')
    def test_callable_nontype_first_parameter(self):self.check('callable_nontype_first_parameter')
    def test_builtin_forward_string_not_compiled(self):self.check('builtin_forward_string_not_compiled')
    def test_builtin_generic_many_parameters(self):self.check('builtin_generic_many_parameters')
    def test_annotated_nested(self):self.check('annotated_nested')
    def test_raw_alias_return(self):self.check('raw_alias_return')
    def test_keyword_binding_error_effects(self):self.check('keyword_binding_error_effects')
    def test_function_type_parameter(self):self.check('function_type_parameter')
    def test_container_transport(self):self.check('container_transport')
    def test_branch_receiver_dict(self):self.check('branch_receiver_dict')
    def test_branch_receiver_list_error(self):self.check('branch_receiver_list_error')
    def test_branch_function_type(self):self.check('branch_function_type')
    def test_captured_builtin_alias(self):self.check('captured_builtin_alias')
    def test_source_type_same_name_distinct(self):self.check('source_type_same_name_distinct')
    def test_ellipsis_alias_parameter(self):self.check('ellipsis_alias_parameter')

class MetadataGuards(unittest.TestCase):
    def test_unproved_or_observed_metadata_is_explicit(self):
        for name,source in GUARDS.items():
            with self.subTest(name=name):
                result=transpile(source,TranspileOptions(filename="metadata_edges.py",license="none"))
                self.assertFalse(result.success)
                self.assertIn('__hash__' if name=='instance_hash_parameter' else 'metadata',result.diagnostics[0].message)

class ExistingHashOverrideBoundary(unittest.TestCase):
    def test_class_type_argument_retains_special_method_boundary(self):
        for mode in ('i64','i128','bigint'):
            result=transpile(CASES['source_class_instance_hash_unobserved'],TranspileOptions(integer=mode,filename="metadata_hash_override.py",license="none"))
            self.assertFalse(result.success)
            self.assertIn('__hash__',result.diagnostics[0].message)
