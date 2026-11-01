"""Direct numeric protocols over retained typed source function references."""
import shutil,unittest
from py2fastrust import transpile,TranspileOptions
from tests import test_native_context_managers as support

CASES = {'add_inplace_alias_and_new_result': {'main.py': 'class Number:\n'
                                                 ' def __init__(self,value):self.value=value\n'
                                                 ' def __add__(self,other):\n'
                                                 '  if isinstance(other,Number):return '
                                                 'Number(self.value+other.value)\n'
                                                 '  return Number(self.value+other)\n'
                                                 ' def __radd__(self,other):return '
                                                 'Number(other+self.value)\n'
                                                 ' def __iadd__(self,other):\n'
                                                 '  self.value=(self+other).value\n'
                                                 '  return self\n'
                                                 'a=Number(3)\n'
                                                 'old=a\n'
                                                 'a+=4\n'
                                                 'print(a is old,a.value,old.value)\n'
                                                 'a=a+5\n'
                                                 'print(a is old,a.value,old.value,(7+a).value)\n'},
 'finite_rhs_class_and_integer': {'main.py': 'class Number:\n'
                                             ' def __init__(self,value):self.value=value\n'
                                             ' def __add__(self,other):\n'
                                             '  if isinstance(other,Number):return '
                                             'Number(self.value+other.value)\n'
                                             '  return Number(self.value+other)\n'
                                             ' def __radd__(self,other):return '
                                             'Number(other+self.value)\n'
                                             ' def __iadd__(self,other):\n'
                                             '  self.value=(self+other).value\n'
                                             '  return self\n'
                                             'def combine(a,b):return (a+b).value\n'
                                             'print(combine(Number(3),Number(8)),combine(Number(5),2))\n'},
 'forward_then_reflected_order': {'main.py': 'events=[]\n'
                                             'class Left:\n'
                                             ' def '
                                             "__add__(self,other):events.append('left');return "
                                             'NotImplemented\n'
                                             'class Right:\n'
                                             ' def '
                                             "__radd__(self,other):events.append('right');return "
                                             '7\n'
                                             'print(Left()+Right(),events)\n'},
 'same_class_skips_reflected': {'main.py': 'class Number:\n'
                                           " def __add__(self,other):print('forward');return "
                                           'NotImplemented\n'
                                           " def __radd__(self,other):print('wrong "
                                           "reflected');return 9\n"
                                           'Number()+Number()\n'},
 'inplace_falls_back_normal_then_reflected': {'main.py': 'events=[]\n'
                                                         'class Left:\n'
                                                         ' def '
                                                         "__iadd__(self,other):events.append('inplace');return "
                                                         'NotImplemented\n'
                                                         ' def '
                                                         "__add__(self,other):events.append('normal');return "
                                                         'NotImplemented\n'
                                                         'class Right:\n'
                                                         ' def '
                                                         "__radd__(self,other):events.append('reflected');return "
                                                         '9\n'
                                                         'value=Left()\n'
                                                         'value+=Right()\n'
                                                         'print(value,events)\n'},
 'inplace_returns_replacement_without_forward': {'main.py': 'class Number:\n'
                                                            ' def __iadd__(self,other):return '
                                                            'other+1\n'
                                                            " def __add__(self,other):print('wrong "
                                                            "forward');return 0\n"
                                                            'value=Number()\n'
                                                            'old=value\n'
                                                            'value+=4\n'
                                                            'print(value,value is old)\n'},
 'left_error_stops_reflected': {'main.py': 'class Left:\n'
                                           " def __add__(self,other):print('forward');return 1//0\n"
                                           'class Right:\n'
                                           " def __radd__(self,other):print('wrong "
                                           "reflected');return 9\n"
                                           'Left()+Right()\n'},
 'arguments_execute_before_bad_operator_signature': {'main.py': 'class Number:\n'
                                                                ' def __add__(self):return 7\n'
                                                                "def right():print('right "
                                                                "argument');return 3\n"
                                                                'Number()+right()\n'},
 'normal_method_default_captured': {'main.py': "def mark():print('default');return 4\n"
                                               'class Number:\n'
                                               ' def __add__(self,other,extra=mark()):return '
                                               'other+extra\n'
                                               'print(Number()+3)\n'},
 'primitive_and_sequence_left_reflected': {'main.py': 'events=[]\n'
                                                      'class Right:\n'
                                                      ' def '
                                                      '__radd__(self,other):events.append(1);return '
                                                      '7\n'
                                                      'r=Right()\n'
                                                      "print(3+r,[1]+r,'x'+r,events)\n"},
 'builtin_list_inplace_does_not_reflect': {'main.py': 'class Right:\n'
                                                      " def __radd__(self,other):print('wrong "
                                                      "reflected');return 7\n"
                                                      'value=[1]\n'
                                                      'value+=Right()\n'},
 'notimplemented_singleton_alias_and_display': {'main.py': 'value=NotImplemented\n'
                                                           'print(value,value is '
                                                           'NotImplemented,str(value),repr(value))\n'
                                                           'print(value is '
                                                           'None,value==None,value!=None)\n'},
 'notimplemented_boolean_314': {'main.py': "print('before')\nprint(bool(NotImplemented))\n"},
 'operator_callable_uses_source_protocol': {'main.py': 'class Number:\n'
                                                       ' def '
                                                       '__init__(self,value):self.value=value\n'
                                                       ' def __add__(self,other):\n'
                                                       '  if isinstance(other,Number):return '
                                                       'Number(self.value+other.value)\n'
                                                       '  return Number(self.value+other)\n'
                                                       ' def __radd__(self,other):return '
                                                       'Number(other+self.value)\n'
                                                       ' def __iadd__(self,other):\n'
                                                       '  self.value=(self+other).value\n'
                                                       '  return self\n'
                                                       'import operator\n'
                                                       'function=operator.add\n'
                                                       'print(function(Number(4),7).value)\n'},
 'accumulate_uses_source_addition': {'main.py': 'class Number:\n'
                                                ' def __init__(self,value):self.value=value\n'
                                                ' def __add__(self,other):\n'
                                                '  if isinstance(other,Number):return '
                                                'Number(self.value+other.value)\n'
                                                '  return Number(self.value+other)\n'
                                                ' def __radd__(self,other):return '
                                                'Number(other+self.value)\n'
                                                ' def __iadd__(self,other):\n'
                                                '  self.value=(self+other).value\n'
                                                '  return self\n'
                                                'from itertools import accumulate\n'
                                                'items=list(accumulate([Number(1),Number(2),Number(4)]))\n'
                                                'print([x.value for x in items])\n'},
 'unary_pos_neg_invert_keep_results': {'main.py': 'class Number:\n'
                                                  ' def __init__(self,value):self.value=value\n'
                                                  ' def __pos__(self):return self\n'
                                                  ' def __neg__(self):return Number(-self.value)\n'
                                                  ' def __invert__(self):return ~self.value\n'
                                                  'n=Number(4)\n'
                                                  'print(+n is n,(-n).value,~n)\n'},
 'unary_returning_notimplemented_is_visible': {'main.py': 'class Number:\n'
                                                          ' def __neg__(self):return '
                                                          'NotImplemented\n'
                                                          'print(-Number())\n'},
 'rich_equality_notimplemented_and_identity_default': {'main.py': 'events=[]\n'
                                                                  'class Left:\n'
                                                                  ' def '
                                                                  "__eq__(self,other):events.append('left');return "
                                                                  'NotImplemented\n'
                                                                  'class Right:\n'
                                                                  ' def '
                                                                  "__eq__(self,other):events.append('right');return "
                                                                  'True\n'
                                                                  'left=Left();right=Right()\n'
                                                                  'print(left==right,left!=right,events)\n'},
 'rich_equality_same_type_tries_both': {'main.py': 'events=[]\n'
                                                   'class Number:\n'
                                                   ' def __init__(self,value):self.value=value\n'
                                                   ' def '
                                                   '__eq__(self,other):events.append(self.value);return '
                                                   'NotImplemented\n'
                                                   'a=Number(1);b=Number(2)\n'
                                                   'print(a==b,a==a,events)\n'},
 'comparison_returns_nonbool_value': {'main.py': 'class Number:\n'
                                                 ' def __eq__(self,other):return [1,2]\n'
                                                 'result=Number()==7\n'
                                                 'print(result,bool(result))\n'},
 'ordering_reflected_swaps_operator': {'main.py': 'events=[]\n'
                                                  'class Left:\n'
                                                  ' def '
                                                  "__lt__(self,other):events.append('left');return "
                                                  'NotImplemented\n'
                                                  'class Right:\n'
                                                  ' def '
                                                  "__gt__(self,other):events.append('right');return "
                                                  'True\n'
                                                  'print(Left()<Right(),events)\n'},
 'bitwise_and_division_protocols': {'main.py': 'class Number:\n'
                                               ' def __init__(self,value):self.value=value\n'
                                               ' def __sub__(self,other):return '
                                               'Number(self.value-other)\n'
                                               ' def __mul__(self,other):return '
                                               'Number(self.value*other)\n'
                                               ' def __floordiv__(self,other):return '
                                               'self.value//other\n'
                                               ' def __mod__(self,other):return self.value%other\n'
                                               ' def __lshift__(self,other):return '
                                               'self.value<<other\n'
                                               ' def __and__(self,other):return self.value&other\n'
                                               'x=Number(17)\n'
                                               'print((x-4).value,(x*3).value,x//5,x%5,x<<2,x&6)\n'},
 'bound_dunder_direct_call_is_not_operator_fallback': {'main.py': 'class Number:\n'
                                                                  ' def __add__(self,other):return '
                                                                  'NotImplemented\n'
                                                                  'value=Number()\n'
                                                                  'saved=value.__add__\n'
                                                                  'print(saved(3),value.__add__(4))\n'},
 'with_cleanup_survives_operator_error': {'main.py': 'class Guard:\n'
                                                     " def __enter__(self):print('enter')\n"
                                                     " def __exit__(self,a,b,c):print('exit')\n"
                                                     'class Number:\n'
                                                     ' def __add__(self,other):return 1//0\n'
                                                     'with Guard():Number()+4\n'},
 'list_concat_declined': {'main.py': 'class Right:\n'
                                     " def __radd__(self,other):print('reflected add');return "
                                     'NotImplemented\n'
                                     " def __rmul__(self,other):print('reflected mul');return "
                                     'NotImplemented\n'
                                     'print([1]+Right())\n'},
 'tuple_concat_declined': {'main.py': 'class Right:\n'
                                      " def __radd__(self,other):print('reflected add');return "
                                      'NotImplemented\n'
                                      " def __rmul__(self,other):print('reflected mul');return "
                                      'NotImplemented\n'
                                      'print((1,)+Right())\n'},
 'bytes_concat_declined': {'main.py': 'class Right:\n'
                                      " def __radd__(self,other):print('reflected add');return "
                                      'NotImplemented\n'
                                      " def __rmul__(self,other):print('reflected mul');return "
                                      'NotImplemented\n'
                                      "print(b'a'+Right())\n"},
 'str_concat_declined': {'main.py': 'class Right:\n'
                                    " def __radd__(self,other):print('reflected add');return "
                                    'NotImplemented\n'
                                    " def __rmul__(self,other):print('reflected mul');return "
                                    'NotImplemented\n'
                                    "print('a'+Right())\n"},
 'list_inplace_declined': {'main.py': 'class Right:\n'
                                      " def __radd__(self,other):print('reflected add');return "
                                      'NotImplemented\n'
                                      " def __rmul__(self,other):print('reflected mul');return "
                                      'NotImplemented\n'
                                      'value=[1]\n'
                                      'value+=Right()\n'},
 'sequence_repeat_declined': {'main.py': 'class Right:\n'
                                         " def __radd__(self,other):print('reflected add');return "
                                         'NotImplemented\n'
                                         " def __rmul__(self,other):print('reflected mul');return "
                                         'NotImplemented\n'
                                         'print([1]*Right())\n'},
 'reverse_sequence_repeat_error': {'main.py': 'class Left:\n'
                                              " def __mul__(self,other):print('forward');return "
                                              'NotImplemented\n'
                                              'print(Left()*[1])\n'},
 'callback_effect_inside_method_loop': {'main.py': 'class Counter:\n'
                                                   ' def __init__(self):self.value=0\n'
                                                   ' def '
                                                   '__add__(self,other):self.value+=other;return '
                                                   'self\n'
                                                   ' def run(self):\n'
                                                   '  result=0\n'
                                                   '  for i in range(4):\n'
                                                   '   result+=self.value\n'
                                                   '   self+1\n'
                                                   '   result+=self.value\n'
                                                   '  return result\n'
                                                   'c=Counter()\n'
                                                   'print(c.run(),c.value)\n'},
 'accumulate_effect_inside_method_loop': {'main.py': 'from itertools import accumulate\n'
                                                     'class Counter:\n'
                                                     ' def __init__(self):self.value=1\n'
                                                     ' def '
                                                     '__add__(self,other):self.value+=other.value;return '
                                                     'self\n'
                                                     ' def run(self):\n'
                                                     '  total=0\n'
                                                     '  for item in accumulate([self,self,self]):\n'
                                                     '   total+=self.value\n'
                                                     '  return total\n'
                                                     'c=Counter()\n'
                                                     'print(c.run(),c.value)\n'},
 'comparison_chain_false_retains_shared_result': {'main.py': 'events=[]\n'
                                                             'result=[]\n'
                                                             'class Item:\n'
                                                             ' def '
                                                             '__lt__(self,other):events.append(1);return '
                                                             'result\n'
                                                             'def later():events.append(2);return '
                                                             'Item()\n'
                                                             'actual=Item()<Item()<later()\n'
                                                             'actual.append(9)\n'
                                                             'print(actual is '
                                                             'result,result,events)\n'},
 'comparison_chain_true_returns_last_payload': {'main.py': 'events=[]\n'
                                                           'class Item:\n'
                                                           ' def __init__(self,n):self.n=n\n'
                                                           ' def '
                                                           '__lt__(self,other):events.append(self.n);return '
                                                           '[other.n]\n'
                                                           'def later():events.append(9);return '
                                                           'Item(3)\n'
                                                           'actual=Item(1)<Item(2)<later()\n'
                                                           'print(actual,events)\n'},
 'explicit_ne_nonbool': {'main.py': 'class Item:\n'
                                    ' def __ne__(self,other):return [7]\n'
                                    'print(Item()!=3)\n'},
 'default_ne_truth_tests_notimpl': {'main.py': 'class Item:\n'
                                               " def __eq__(self,other):print('equal');return []\n"
                                               'print(Item()!=3)\n'},
 'unary_mutates_payload_and_keeps_identity': {'main.py': 'class Item:\n'
                                                         ' def __init__(self):self.value=[2]\n'
                                                         ' def '
                                                         '__neg__(self):self.value.append(4);return '
                                                         'self.value\n'
                                                         'item=Item()\n'
                                                         'alias=item.value\n'
                                                         'result=-item\n'
                                                         'result.append(6)\n'
                                                         'print(result is alias,alias)\n'},
 'reflected_receives_original_mutated_operand': {'main.py': 'events=[]\n'
                                                            'class Left:\n'
                                                            ' def __init__(self):self.value=2\n'
                                                            ' def '
                                                            '__add__(self,other):self.value=8;events.append(1);return '
                                                            'NotImplemented\n'
                                                            'class Right:\n'
                                                            ' def '
                                                            '__radd__(self,other):events.append(other.value);return '
                                                            'other\n'
                                                            'left=Left()\n'
                                                            'result=left+Right()\n'
                                                            'print(result is left,events)\n'},
 'mixed_class_primitive_binary_and_comparison': {'main.py': 'class Item:\n'
                                                            ' def __init__(self,n):self.n=n\n'
                                                            ' def __add__(self,other):return '
                                                            'self.n+other\n'
                                                            ' def __eq__(self,other):return '
                                                            'self.n==other\n'
                                                            'def f(value):return value+2,value==3\n'
                                                            'print(f(Item(3)),f(3))\n'},
 'unary_missing_slot_error': {'main.py': 'class Item:pass\nprint(-Item())\n'},
 'rich_order_declined': {'main.py': 'class Item:\n'
                                    " def __lt__(self,other):print('lt');return NotImplemented\n"
                                    'print(Item()<3)\n'}}

UNSUPPORTED = {'payload_equality_can_mutate_list': 'items=[]\n'
                                     'class Number:\n'
                                     ' def __init__(self,value):self.value=value\n'
                                     ' def __eq__(self,other):items.append(9);return '
                                     'self.value==other.value\n'
                                     'left=[Number(3)]\n'
                                     'right=[Number(3)]\n'
                                     'print(left==right,items)\n',
 'descriptor_operator_guard': 'class Number:\n'
                              ' value=3\n'
                              ' @classmethod\n'
                              ' def __add__(cls,other):return cls.value+other\n'
                              'print(Number()+4)\n'}


class SourceOperatorBoundaryTests(unittest.TestCase):
    def test_unsupported_implicit_protocols_explain_the_missing_contract(self):
        for name,source in UNSUPPORTED.items():
            for mode in ("i64","i128","bigint"):
                with self.subTest(case=name,integer=mode):
                    result=transpile(source,TranspileOptions(filename="main.py",integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,"E006")
                    self.assertGreater(result.diagnostics[0].line,0)
                    self.assertIn("descriptor" if name=="descriptor_operator_guard" else "rich-comparison",result.diagnostics[0].message)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class SourceOperatorExecutionTests(unittest.TestCase):
    exercise=support.ContextManagerExecutionTests.exercise


def _execution(files):
    def test(self):self.exercise(files)
    return test


for _name,_files in CASES.items():setattr(SourceOperatorExecutionTests,"test_"+_name,_execution(_files))
