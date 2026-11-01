"""Positional argument packs preserve normal call binding and tuple identity."""
import ast
import inspect
import random
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.call_semantics import FunctionSignature, CallBindingError, normalize_call
from py2fastrust.native_frame_selection import select_frames
import test_native_iterator_reductions as execution

SOURCES = {'original_length_and_representation': 'def collect(*items):\n'
                                       ' return items\n'
                                       'print(collect(),collect(1,2),collect(True,"x"))\n'
                                       'print(len(collect()),len(collect(1,2,3)))\n',
 'original_defaults_and_keyword_only': 'def collect(a=1,/,*items,scale=2):\n'
                                       ' return a,items,scale\n'
                                       'print(collect(),collect(4,5,6,scale=3))\n',
 'original_recursive': 'def fold(n,*items):\n'
                       ' if n==0:return len(items)\n'
                       ' return fold(n-1,7,8)\n'
                       'print(fold(4,1))\n',
 'original_method_and_bound_alias': 'class Counter:\n'
                                    ' def score(self,x,*items,k=2):\n'
                                    '  return x+sum(items)*k\n'
                                    'box=Counter()\n'
                                    'call=box.score\n'
                                    'print(box.score(1,2,3),call(4),call(4,5,k=3))\n',
 'original_constructor_and_instance_field': 'class Box:\n'
                                            ' def __init__(self,*items):self.items=items\n'
                                            ' def get(self):return self.items\n'
                                            'left=Box(1,2)\n'
                                            'right=Box()\n'
                                            'print(left.get(),right.get(),left.get()is '
                                            'left.get())\n',
 'original_fresh_tuple_identity': 'def collect(*items):return items\n'
                                  'first=collect(1)\n'
                                  'alias=first\n'
                                  'second=collect(1)\n'
                                  'print(first is alias,first is second,collect()is collect())\n'
                                  'print(first==second,collect(1,2)==(1,2))\n',
 'original_mutable_element_aliases': 'def collect(*items):return items\n'
                                     'values=[1]\n'
                                     'first=collect(values)\n'
                                     'second=collect(values)\n'
                                     'first[0].append(2)\n'
                                     'print(values,second,first is second,first[0]is values)\n',
 'original_lambda_and_closure': 'def maker(*items):return lambda:items\n'
                                'first=maker(1,2)\n'
                                'second=maker(3)\n'
                                'print(first(),second(),first()is first())\n'
                                'collect=lambda *items:items\n'
                                'print(collect(),collect("a","b"))\n',
 'original_argument_effects_and_error': 'def value(number):\n'
                                        ' print("value",number)\n'
                                        ' return number\n'
                                        'def call(first,*items,flag):print("called")\n'
                                        'saved=call\n'
                                        'saved(value(1),value(2),bad=value(3))\n',
 'original_empty_and_iterated_tuple': 'def visit(*items):\n'
                                      ' print(len(items),bool(items),list(items))\n'
                                      ' for value in items:print(value)\n'
                                      'visit()\n'
                                      'visit(1,2,3)\n',
 'extra_positional_only_and_keyword_effects': 'def mark(x):\n'
                                              ' print(x)\n'
                                              ' return x\n'
                                              'def f(first,/,*items,flag=3):return '
                                              'first,items,flag\n'
                                              'print(f(mark(1),mark(2),flag=mark(4)))\n',
 'extra_direct_unknown_keyword_after_arguments': 'def mark(x):\n'
                                                 ' print(x)\n'
                                                 ' return x\n'
                                                 'def f(*items):return items\n'
                                                 'f(mark(1),bad=mark(2))\n',
 'extra_direct_variadic_name_is_not_a_keyword_parameter': 'def mark(x):\n'
                                                          ' print(x)\n'
                                                          ' return x\n'
                                                          'def f(*items):return items\n'
                                                          'f(mark(1),items=mark(2))\n',
 'extra_direct_missing_required_keyword_only': 'def mark(x):\n'
                                               ' print(x)\n'
                                               ' return x\n'
                                               'def f(first,*items,flag):return first,items,flag\n'
                                               'f(mark(1),mark(2))\n',
 'extra_duplicate_normal_parameter': 'def mark(x):\n'
                                     ' print(x)\n'
                                     ' return x\n'
                                     'def f(first,*items):return first,items\n'
                                     'f(mark(1),mark(2),first=mark(3))\n',
 'extra_method_unknown_keyword_after_arguments': 'class Box:\n'
                                                 ' def f(self,*items):return items\n'
                                                 'def mark(x):\n'
                                                 ' print(x)\n'
                                                 ' return x\n'
                                                 'Box().f(mark(1),bad=mark(2))\n',
 'extra_only_variadic_receiver_method': 'class Box:\n'
                                        ' def f(*items):return len(items)\n'
                                        'box=Box()\n'
                                        'saved=box.f\n'
                                        'print(box.f(),box.f(1,2),saved(3))\n',
 'extra_local_argument_rebinding': 'def f(*items):\n'
                                   ' old=items\n'
                                   ' items="rebound"\n'
                                   ' print(items,old)\n'
                                   ' return old\n'
                                   'print(f(1,2))\n',
 'extra_del_argument_keeps_returned_alias': 'def f(*items):\n'
                                            ' old=items\n'
                                            ' del items\n'
                                            ' return old\n'
                                            'print(f(1,2))\n',
 'extra_shared_empty_and_distinct_factories': 'def left(*items):return items\n'
                                              'def right(*items):return items\n'
                                              'print(left()is right(),left(1)is '
                                              'right(1),left(1)==right(1))\n',
 'extra_empty_reductions_and_index_error': 'def f(*items):\n'
                                           ' print(sum(items),list(items),bool(items))\n'
                                           ' return items[0]\n'
                                           'f()\n',
 'extra_negative_index_and_unpack': 'def f(*items):\n'
                                    ' first,second=items\n'
                                    ' print(items[-1],items[0])\n'
                                    ' return first+second\n'
                                    'print(f(2,3))\n',
 'extra_unpack_too_many': 'def f(*items):\n'
                          ' first,second=items\n'
                          ' return first+second\n'
                          'print(f(1,2,3))\n',
 'extra_unpack_not_enough': 'def f(*items):\n'
                            ' first,second=items\n'
                            ' return first+second\n'
                            'print(f(1))\n',
 'extra_empty_filter_and_cursor': 'def f(*items):\n'
                                  ' cursor=filter(None,items)\n'
                                  ' return list(cursor)\n'
                                  'print(f())\n',
 'extra_lambda_default_and_keyword_only': 'f=lambda first=3,*items,last=4:(first,items,last)\n'
                                          'print(f(),f(1,2,3,last=8))\n',
 'extra_nested_function_varargs': 'def maker(seed):\n'
                                  ' def collect(*items):return seed,items\n'
                                  ' return collect\n'
                                  'first=maker(1)\n'
                                  'second=maker(2)\n'
                                  'print(first(3,4),second(),first(5))\n',
 'extra_input_chosen_argument_control': 'def f(*items):\n'
                                        ' if len(items)>1:return items[-1]\n'
                                        ' return 0\n'
                                        'print(f(1),f(2,3,4))\n',
 'extra_list_parameter_rebinding_preserves_alias': 'def f(*items):\n'
                                                   ' first=items\n'
                                                   ' items=3\n'
                                                   ' return first\n'
                                                   'values=[1]\n'
                                                   'out=f(values)\n'
                                                   'values.append(2)\n'
                                                   'print(out,out[0]is values)\n',
 'legacy_sum_items': 'def f(*items):return sum(items)\nprint(f(1))\n',
 'legacy_len_items': 'def f(*items):return len(items)\nprint(f(1))\n',
 'legacy_rebound_max': 'max=lambda *args:7\nprint(max(1,2))\n',
 'legacy_rebound_fixed_min': 'def min(a,b):return a+b\nprint(min(1,2))\n'}


class VariadicBindingTests(unittest.TestCase):
    def test_opt_in_packing_retains_original_arguments_and_order(self):
        unit=build_program("def f(first,/,*items,flag=8):pass\nf(mark(1),mark(2),flag=mark(3))\n").main
        signature=unit.signature_for(unit.tree.body[0]);call=unit.tree.body[1].value
        with self.assertRaises(CallBindingError):signature.plan(normalize_call(call))
        plan=signature.plan(normalize_call(call),allow_variadic=True);events=[]
        def evaluate(node,parameter):
            events.append(("evaluate",node.args[0].value,parameter));return node.args[0].value
        def pack(values):events.append(("pack",values));return tuple(values)
        bound=plan.capture(evaluate,defaults={"flag":8},pack_positional=pack)
        self.assertEqual(bound.parameters,("first","items","flag"))
        self.assertEqual(bound.values,(1,(2,),3))
        self.assertEqual(events,[("evaluate",1,"first"),("evaluate",2,"items"),("evaluate",3,"flag"),("pack",(2,))])
        self.assertTrue(all(argument.expression is actual for argument,actual in zip(plan.arguments.evaluation_order,[*call.args,call.keywords[0].value])))

    def test_random_variadic_binding_matches_python(self):
        source="def f(first=7,/,second=8,*items,last,option=None):pass\n";namespace={};exec(source,namespace)
        expected=inspect.signature(namespace["f"]);unit=build_program(source).main;signature=unit.signature_for(unit.tree.body[0]);rng=random.Random(61101)
        for _ in range(1200):
            args=list(range(rng.randrange(7)));names=rng.sample(["first","second","items","last","option","bad"],rng.randrange(7));kwargs={name:rng.choice([None,3,9])for name in names}
            try:official=expected.bind(*args,**kwargs);official.apply_defaults()
            except TypeError:
                with self.assertRaises(CallBindingError):signature.bind(args,list(kwargs.items()),{"first":7,"second":8,"option":None},pack_positional=tuple)
            else:
                actual=signature.bind(args,list(kwargs.items()),{"first":7,"second":8,"option":None},pack_positional=tuple)
                self.assertEqual(dict(actual.by_name),dict(official.arguments))

    def test_frames_are_selected_from_the_original_reached_signature(self):
        source="def f(*items):return len(items)\nprint(f(1,2))\n";unit=build_program(source).main;before=ast.dump(unit.tree,include_attributes=True)
        self.assertTrue(select_frames(unit).required)
        from py2fastrust.native_classes import Model
        Model(unit.tree,unit.filename,"i64",unit.native_imports,unit=unit).run()
        result=transpile(source);self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertIn("NativeTuple",result.rust_source)

    def test_cycles_and_remaining_keyword_expansion_are_precise_boundaries(self):
        sources=("def f(*items):return items\nclass Box:pass\nbox=Box()\nbox.saved=f(box)\n", "def f(**items):return 1\nprint(f(a=1))\n")
        for source in sources:
            for integer in ("i64","i128","bigint"):
                with self.subTest(source=source,integer=integer):
                    result=transpile(source,TranspileOptions(integer=integer,filename="boundary.py"))
                    self.assertFalse(result.success);self.assertEqual(result.diagnostics[0].code,"E006");self.assertEqual(result.diagnostics[0].filename,"boundary.py");self.assertGreater(result.diagnostics[0].line,0)
                    self.assertIn("Source:",result.diagnostics[0].message)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class VariadicExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=execution.NativeIteratorReductionTests();cls.harness.setUpClass()
    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()
    def compare(self,source):
        expected=subprocess.run([sys.executable,"-I","-c",source],capture_output=True,text=True,timeout=10)
        frame=lambda text:re.findall(r'File "[^"]+", line (\d+), in ([^\n]+)',text)
        final=lambda text:text.rstrip().splitlines()[-1]if text.strip()else""
        for integer in ("i64","i128","bigint"):
            for optimize in (False,True):
                with self.subTest(integer=integer,optimize=optimize),patch("py2fastrust.codegen.generate",side_effect=AssertionError("general backend entered")):
                    generated=self.harness.compile(source,integer,release=optimize)
                    if expected.returncode==0 and any(isinstance(node,(ast.FunctionDef,ast.Lambda))and node.args.vararg for node in ast.walk(ast.parse(source))):self.assertIn("NativeTuple",generated[2])
                    self.assertNotIn("enum Value",generated[2]);self.assertLess(len(generated[2].encode()),512*1024)
                    actual=subprocess.run([str(generated[1])],capture_output=True,text=True,timeout=10)
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                    self.assertEqual(final(actual.stderr),final(expected.stderr));self.assertEqual(frame(actual.stderr),frame(expected.stderr))


def case(source):
    def run(self):self.compare(source)
    return run
for name,source in SOURCES.items():setattr(VariadicExecutionTests,"test_"+name,case(source))

if __name__=="__main__":unittest.main()
