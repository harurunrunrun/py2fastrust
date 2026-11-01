"""Canonical cast type arguments preserve subscription validation and effects."""
import unittest,shutil
import test_native_class_iterators as iterator_tests
from py2fastrust import transpile,TranspileOptions
CASES={'tuple_builtin_types': 'from typing import cast,Tuple\n'
                        'x=(3,4)\n'
                        'y=cast(Tuple[int,int],x)\n'
                        'print(x,y,x is y)\n',
 'nested_source_type': 'from typing import cast,Tuple\n'
                       'class Outer:\n'
                       ' class Edge:pass\n'
                       'x=(3,Outer.Edge())\n'
                       'y=cast(Tuple[int,Outer.Edge],x)\n'
                       'print(y[0],y is x,y[1] is x[1])\n',
 'import_alias': 'from typing import cast as same,Tuple as Pair\n'
                 'x=[7]\n'
                 'y=same(Pair[int,str],x)\n'
                 'print(y,x is y)\n',
 'keyword_typ': 'from typing import cast,Tuple\n'
                'x=[7]\n'
                'y=cast(val=x,typ=Tuple[int,str])\n'
                'print(y,x is y)\n',
 'hoisted_alias': 'from typing import cast,Tuple\n'
                  'Alias=Tuple[int,str]\n'
                  'x=[7]\n'
                  'print(cast(Alias,x),cast(Alias,x) is x)\n',
 'copied_alias': 'from typing import cast,Tuple\n'
                 'Alias=Tuple[int,str]\n'
                 'Other=Alias\n'
                 'print(cast(Other,7))\n',
 'nested_aliases': 'from typing import cast,Tuple,List,Dict,Optional\n'
                   'Pair=Tuple[int,str]\n'
                   'Table=Dict[str,List[Optional[Pair]]]\n'
                   'print(cast(Table,[7]))\n',
 'raw_alias': 'from typing import cast,Tuple\nprint(cast(Tuple,7))\n',
 'tuple_empty': 'from typing import cast,Tuple\nprint(cast(Tuple[()],7))\n',
 'tuple_ellipsis': 'from typing import cast,Tuple\n'
                   'print(cast(Tuple[int,...],7))\n',
 'tuple_index_variable': 'from typing import cast,Tuple\n'
                         'parameters=(int,str)\n'
                         'print(cast(Tuple[parameters],7))\n',
 'callable_list': 'from typing import cast,Callable\n'
                  'print(cast(Callable[[int,str],bool],7))\n',
 'callable_scalar_allowed': 'from typing import cast,Callable\n'
                            'print(cast(Callable[int,str],7))\n',
 'literal_metadata': 'from typing import cast,Literal\n'
                     'print(cast(Literal[1,"x",True],7))\n',
 'annotated_metadata': 'from typing import cast,Annotated\n'
                       'print(cast(Annotated[int,"tag"],7))\n',
 'classvar_metadata': 'from typing import cast,ClassVar,Final\n'
                      'print(cast(ClassVar[int],7),cast(Final[int],8))\n',
 'none_type_parameter': 'from typing import cast,List\n'
                        'print(cast(List[None],7))\n',
 'non_type_integer_allowed': 'from typing import cast,List,Tuple\n'
                             'print(cast(List[42],7),cast(Tuple[42],8))\n',
 'too_many_list_parameters': 'from typing import cast,List\n'
                             'print(cast(List[int,str],7))\n',
 'too_few_dict_parameters': 'from typing import cast,Dict\n'
                            'print(cast(Dict[int],7))\n',
 'optional_many_parameters': 'from typing import cast,Optional\n'
                             'print(cast(Optional[int,str],7))\n',
 'union_empty': 'from typing import cast,Union\nprint(cast(Union[()],7))\n',
 'any_subscription': 'from typing import cast,Any\nprint(cast(Any[int],7))\n',
 'tuple_invalid_tuple_parameter': 'from typing import cast,Tuple\n'
                                  'print(cast(Tuple[(int,str),int],7))\n',
 'forbidden_classvar_parameter': 'from typing import cast,List,ClassVar\n'
                                 'print(cast(List[ClassVar[int]],7))\n',
 'forbidden_special_form': 'from typing import cast,List,TypeAlias\n'
                           'print(cast(List[TypeAlias],7))\n',
 'forward_reference': 'from typing import cast,List\n'
                      'print(cast(List["int"],7))\n',
 'invalid_forward_reference': 'from typing import cast,List\n'
                              'print(cast(List["("],7))\n',
 'parameter_effect_order': 'from typing import cast,Tuple\n'
                           'def mark(tag,value):\n'
                           ' print(tag,end="|")\n'
                           ' return value\n'
                           'x=[7]\n'
                           'print(cast(Tuple[mark("a",int),mark("b",str)],mark("v",x)))\n',
 'keyword_effect_order': 'from typing import cast,Tuple\n'
                         'def mark(tag,value):\n'
                         ' print(tag,end="|")\n'
                         ' return value\n'
                         'print(cast(val=mark("v",7),typ=Tuple[mark("t",int),str]))\n',
 'callee_captured_before_parameter_effects': 'import typing\n'
                                             'from typing import Tuple\n'
                                             'def replacement(typ,val):\n'
                                             ' print("replacement")\n'
                                             ' return -1\n'
                                             'def change():\n'
                                             ' typing.cast=replacement\n'
                                             ' print("change")\n'
                                             ' return int\n'
                                             'print(typing.cast(Tuple[change(),str],7))\n',
 'saved_cast_after_rebinding': 'from typing import cast,Tuple\n'
                               'saved=cast\n'
                               'def cast(typ,val):\n'
                               ' print("replacement")\n'
                               ' return -1\n'
                               'print(saved(Tuple[int,str],7))\n',
 'receiver_captured_before_index_effects': 'from typing import cast,Dict,List\n'
                                           'Alias=Dict\n'
                                           'def change():\n'
                                           ' global Alias\n'
                                           ' Alias=List\n'
                                           ' print("change")\n'
                                           ' return int\n'
                                           'print(cast(Alias[change(),str],7))\n',
 'cast_excess_argument_effects': 'from typing import cast,Tuple\n'
                                 'def mark(tag,value):\n'
                                 ' print(tag,end="|")\n'
                                 ' return value\n'
                                 'print(cast(Tuple[int,str],mark("val",7),mark("extra",8)))\n',
 'constructor_error_before_later_argument': 'from typing import cast,List\n'
                                            'def mark():\n'
                                            ' print("late")\n'
                                            ' return 7\n'
                                            'print(cast(List[int,str],mark(),99))\n',
 'shadow_alias_with_list': 'from typing import cast,Tuple\n'
                           'Tuple=[9,8]\n'
                           'def index():\n'
                           ' print("index")\n'
                           ' return 0\n'
                           'print(cast(Tuple[index()],7))\n',
 'shadow_typing_receiver': 'import typing\n'
                           'from typing import cast as same\n'
                           'class Fake:\n'
                           ' def __init__(self):self.Tuple=[9,8]\n'
                           'typing=Fake()\n'
                           'print(same(typing.Tuple[0],7))\n',
 'shadow_cast_with_plain_value': 'from typing import cast,Tuple\n'
                                 'def cast(typ,val):return len(typ)+val\n'
                                 'Tuple=[3,4]\n'
                                 'print(cast(Tuple[:1],7))\n',
 'returned_alias': 'from typing import cast,Tuple\n'
                   'def alias():\n'
                   ' print("alias")\n'
                   ' return Tuple[int,str]\n'
                   'print(cast(alias(),7))\n',
 'forwarded_alias': 'from typing import cast,Tuple\n'
                    'def mark(tag,value):\n'
                    ' print(tag)\n'
                    ' return value\n'
                    'print(cast(mark("type",Tuple[int,str]),7))\n',
 'builtin_generic_alias': 'from typing import cast\n'
                          'print(cast(tuple[int,str],7),cast(list[int],8))\n',
 'concrete_resubscription_error': 'from typing import cast,List\n'
                                  'print(cast(List[int][str],7))\n'}
GUARDS={'observe_constructed_alias': 'from typing import Tuple\n'
                              'Alias=Tuple[int,str]\n'
                              'print(Alias)\n',
 'observe_raw_alias': 'from typing import Tuple\nprint(bool(Tuple))\n',
 'shadow_cast_observes_alias': 'from typing import cast,Tuple\n'
                               'def cast(typ,val):\n'
                               ' print(typ)\n'
                               ' return val\n'
                               'print(cast(Tuple[int,str],7))\n',
 'observing_nested_operation': 'from typing import cast,Tuple\n'
                               'print(cast(bool(Tuple),7))\n',
 'cast_value_observed': 'from typing import cast,Tuple\n'
                        'print(cast(int,Tuple[int,str]))\n'}
@unittest.skipUnless(shutil.which("rustc"),"rustc required")
class CastTypeMetadata(unittest.TestCase):
    cases=CASES
    check=iterator_tests.IteratorExecutionTests.check
    def test_import_alias(self):self.check('import_alias')
    def test_keyword_typ(self):self.check('keyword_typ')
    def test_hoisted_alias(self):self.check('hoisted_alias')
    def test_copied_alias(self):self.check('copied_alias')
    def test_nested_aliases(self):self.check('nested_aliases')
    def test_raw_alias(self):self.check('raw_alias')
    def test_tuple_empty(self):self.check('tuple_empty')
    def test_tuple_ellipsis(self):self.check('tuple_ellipsis')
    def test_tuple_index_variable(self):self.check('tuple_index_variable')
    def test_callable_list(self):self.check('callable_list')
    def test_callable_scalar_allowed(self):self.check('callable_scalar_allowed')
    def test_literal_metadata(self):self.check('literal_metadata')
    def test_annotated_metadata(self):self.check('annotated_metadata')
    def test_classvar_metadata(self):self.check('classvar_metadata')
    def test_none_type_parameter(self):self.check('none_type_parameter')
    def test_non_type_integer_allowed(self):self.check('non_type_integer_allowed')
    def test_too_many_list_parameters(self):self.check('too_many_list_parameters')
    def test_too_few_dict_parameters(self):self.check('too_few_dict_parameters')
    def test_optional_many_parameters(self):self.check('optional_many_parameters')
    def test_union_empty(self):self.check('union_empty')
    def test_any_subscription(self):self.check('any_subscription')
    def test_tuple_invalid_tuple_parameter(self):self.check('tuple_invalid_tuple_parameter')
    def test_forbidden_classvar_parameter(self):self.check('forbidden_classvar_parameter')
    def test_forbidden_special_form(self):self.check('forbidden_special_form')
    def test_forward_reference(self):self.check('forward_reference')
    def test_invalid_forward_reference(self):self.check('invalid_forward_reference')
    def test_parameter_effect_order(self):self.check('parameter_effect_order')
    def test_keyword_effect_order(self):self.check('keyword_effect_order')
    def test_callee_captured_before_parameter_effects(self):self.check('callee_captured_before_parameter_effects')
    def test_saved_cast_after_rebinding(self):self.check('saved_cast_after_rebinding')
    def test_receiver_captured_before_index_effects(self):self.check('receiver_captured_before_index_effects')
    def test_cast_excess_argument_effects(self):self.check('cast_excess_argument_effects')
    def test_constructor_error_before_later_argument(self):self.check('constructor_error_before_later_argument')
    def test_shadow_alias_with_list(self):self.check('shadow_alias_with_list')
    def test_shadow_typing_receiver(self):self.check('shadow_typing_receiver')
    def test_shadow_cast_with_plain_value(self):self.check('shadow_cast_with_plain_value')
    def test_returned_alias(self):self.check('returned_alias')
    def test_forwarded_alias(self):self.check('forwarded_alias')
    def test_builtin_generic_alias(self):self.check('builtin_generic_alias')
    def test_concrete_resubscription_error(self):self.check('concrete_resubscription_error')

class MetadataObservation(unittest.TestCase):
    def test_runtime_observations_remain_explicit(self):
        for name,source in GUARDS.items():
            with self.subTest(name=name):
                result=transpile(source,TranspileOptions(filename="metadata_observation.py",license="none"))
                self.assertFalse(result.success)
                self.assertIn("metadata",result.diagnostics[0].message)

class PreservedTupleIdentityBoundaries(unittest.TestCase):
    def test_unrelated_tuple_identity_boundary(self):
        for name in ('tuple_builtin_types','nested_source_type'):
            for mode in ('i64','i128','bigint'):
                with self.subTest(name=name,mode=mode):
                    result=transpile(CASES[name],TranspileOptions(integer=mode,filename="metadata_tuple_identity.py",license="none"))
                    self.assertFalse(result.success)
                    self.assertIn("comparison 'is'",result.diagnostics[0].message)
                    self.assertIn("tuple[",result.diagnostics[0].message)
