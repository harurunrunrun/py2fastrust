"""Typed call-site expansion preserves Python argument capture and binding."""
import ast
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.call_semantics import normalize_call,CallBindingError
from py2fastrust.native_frame_selection import select_frames
from py2fastrust.native_classes import Model,try_generate_classes
from py2fastrust.native_module_linking import needs_linking
import test_native_iterator_reductions as execution

SOURCES = {'basic_print_list_tuple_range': 'answers=[2,3,5]\n'
                                 'print(*answers)\n'
                                 'print(*(7,11),sep=":",end="!")\n'
                                 'print(*range(3))\n'
                                 'print(*[],end="empty\\n")\n',
 'basic_print_multiple_segments': 'values=[2,3]\nprint(1,*values,4,*(5,6),7,sep="/")\n',
 'basic_fixed_function_signature': 'def f(a,b=9,*,scale=2):return (a+b)*scale\n'
                                   'print(f(*[3,4]),f(*(5,),scale=3),f(*[],scale=4))\n',
 'basic_variadic_function': 'def f(first,*items,last=8):return first,items,last\n'
                            'print(f(1,*[2,3],last=9))\n'
                            'print(f(*(4,5),6,*range(7,9)))\n',
 'basic_only_variadic_function': 'def f(*items):return items\n'
                                 'print(f(*[1,2]),f(3,*(),4),f(*range(3)))\n',
 'basic_bound_method_and_alias': 'class Box:\n'
                                 ' def f(self,a,b=5,*items):return a,b,items\n'
                                 'box=Box()\n'
                                 'saved=box.f\n'
                                 'print(box.f(*[1,2]),saved(*(3,4),5,*[6]))\n',
 'basic_closure_and_lambda': 'def make(seed):\n'
                             ' def f(a,*items):return seed,a,items\n'
                             ' return f\n'
                             'f=make(7)\n'
                             'print(f(*[1,2,3]))\n'
                             'g=lambda a,b=8:(a,b)\n'
                             'print(g(*(3,4)))\n',
 'basic_captured_callee_before_arguments': 'def f(*items):return items\n'
                                           'saved=f\n'
                                           'def change():\n'
                                           ' global f\n'
                                           ' f=3\n'
                                           ' return [1,2]\n'
                                           'print(f(*change()),saved(*[3]))\n',
 'basic_keyword_textual_order': 'def mark(label,value):\n'
                                ' print(label)\n'
                                ' return value\n'
                                'def f(*items,flag=0):print(items,flag)\n'
                                'f(flag=mark("keyword",9),*mark("star",[1,2]))\n'
                                'f(*mark("star1",[3]),flag=mark("keyword2",8),*mark("star2",[4]))\n',
 'basic_single_star_mutation_is_deferred': 'values=[1]\n'
                                           'def change():\n'
                                           ' values.append(2)\n'
                                           ' return "!"\n'
                                           'print(*values,end=change())\n'
                                           'print(values)\n',
 'basic_multiple_star_materialization_is_eager': 'values=[1]\n'
                                                 'def change():\n'
                                                 ' values.append(2)\n'
                                                 ' return "!"\n'
                                                 'print(0,*values,end=change())\n'
                                                 'print(values)\n',
 'basic_iteration_error_after_keyword': 'def item(value):\n'
                                        ' print("item",value)\n'
                                        ' return 1//value\n'
                                        'def keyword():\n'
                                        ' print("keyword")\n'
                                        ' return 8\n'
                                        'def f(a):print("body",a)\n'
                                        'f(*map(item,[1,0]),bad=keyword())\n',
 'basic_keyword_error_after_full_iteration': 'def item(value):\n'
                                             ' print("item",value)\n'
                                             ' return value\n'
                                             'def keyword():\n'
                                             ' print("keyword")\n'
                                             ' return 8\n'
                                             'def f(a):print("body",a)\n'
                                             'f(*map(item,[1,2]),bad=keyword())\n',
 'basic_multiple_star_error_before_keyword': 'def item(value):\n'
                                             ' print("item",value)\n'
                                             ' return 1//value\n'
                                             'def keyword():\n'
                                             ' print("keyword")\n'
                                             ' return 8\n'
                                             'def f(a):print("body",a)\n'
                                             'f(*map(item,[1,0]),*[2],bad=keyword())\n',
 'basic_noniterable_single_star': 'def keyword():\n'
                                  ' print("keyword")\n'
                                  ' return 8\n'
                                  'def f(*items):return items\n'
                                  'f(*3,bad=keyword())\n',
 'basic_noniterable_multiple_star': 'def keyword():\n'
                                    ' print("keyword")\n'
                                    ' return 8\n'
                                    'def f(*items):return items\n'
                                    'f(*3,*[4],bad=keyword())\n',
 'basic_noncallable_after_expansion': 'def item(value):\n'
                                      ' print("item",value)\n'
                                      ' return value\n'
                                      'def keyword():\n'
                                      ' print("keyword")\n'
                                      ' return 8\n'
                                      'f=3\n'
                                      'f(*map(item,[1,2]),bad=keyword())\n',
 'basic_noncallable_and_noniterable': 'def keyword():\n'
                                      ' print("keyword")\n'
                                      ' return 8\n'
                                      'f=3\n'
                                      'f(*7,bad=keyword())\n',
 'basic_source_function_named_print': 'def print(*items):return len(items)\n'
                                      'count=print(*[1,2],3)\n'
                                      'import builtins\n'
                                      'builtins.print(count)\n',
 'basic_print_saved_alias': 'emit=print\nprint=3\nemit(*[1,2],sep=":")\n',
 'basic_print_sep_end_error_priority': 'def item(value):\n'
                                       ' print("item",value)\n'
                                       ' return value\n'
                                       'def keyword():\n'
                                       ' print("keyword")\n'
                                       ' return 8\n'
                                       'print(*map(item,[1,2]),sep=keyword(),bad=9)\n',
 'basic_fixed_too_many_positional': 'def f(a,b=2):return a+b\nf(*[1,2,3])\n',
 'basic_fixed_missing_parameters': 'def f(a,b,*,flag):return a+b\nf(*[])\n',
 'basic_fixed_positional_keyword_duplicate': 'def mark(value):\n'
                                             ' print(value)\n'
                                             ' return value\n'
                                             'def f(a,b):return a+b\n'
                                             'f(*[1,2],a=mark(3))\n',
 'basic_star_text_and_bytes': 'def f(*items):return items\n'
                              'print(*"abc",sep="-")\n'
                              'print(*b"ab")\n'
                              'print(f(*"xy"),f(*b"cd"))\n',
 'basic_nested_star_call': 'def total(*items):return sum(items)\n'
                           'print(total(*[total(*[1,2]),3]))\n',
 'basic_empty_print_and_keyword_values': 'def mark(value):\n'
                                         ' print("mark",value)\n'
                                         ' return value\n'
                                         'print(*[],sep=mark(None),end=mark("!"),flush=mark(False))\n',
 'extra_fixed_noniterable': 'def f(a):return a+1\nf(*3)\n',
 'extra_fixed_none_noniterable': 'def f(a):return a+1\nf(*None)\n',
 'extra_union_valid_and_invalid_sources': 'def f(a):return a+1\n'
                                          'def run(flag):\n'
                                          ' values=[4]if flag else 3\n'
                                          ' return f(*values)\n'
                                          'print(run(True))\n'
                                          'run(False)\n',
 'extra_noniterable_stops_later_positionals': 'def later():\n'
                                              ' print("later")\n'
                                              ' return 3\n'
                                              'def f(*items):return items\n'
                                              'f(1,*3,later())\n',
 'extra_positional_only_keywords': 'def mark(x):\n'
                                   ' print(x)\n'
                                   ' return x\n'
                                   'def f(a,/,b,*items,flag=9):return a,b,items,flag\n'
                                   'f(*[1],bad=mark(2),a=mark(3))\n',
 'extra_prior_duplicate_wins': 'def mark(x):\n'
                               ' print(x)\n'
                               ' return x\n'
                               'def f(a,/,b,*items):return a,b,items\n'
                               'f(*[1,2],b=mark(3),a=mark(4))\n',
 'extra_prior_positional_only_wins': 'def mark(x):\n'
                                     ' print(x)\n'
                                     ' return x\n'
                                     'def f(a,/,b,*items):return a,b,items\n'
                                     'f(*[1,2],a=mark(3),b=mark(4))\n',
 'extra_missing_three_positional': 'def f(a,b,c):return a+b+c\nf(*())\n',
 'extra_missing_three_keyword_only': 'def f(*,a,b,c):return a+b+c\nf(*())\n',
 'extra_excess_with_keyword_only': 'def f(a,b,*,flag=8,other=9):return a+b\n'
                                   'f(*[1,2,3],flag=7,other=6)\n',
 'extra_bound_implicit_duplicate': 'class Box:\n def f(self,a):return a\nBox().f(*[1],self=2)\n',
 'extra_bound_only_variadic': 'class Box:\n'
                              ' def f(*items,flag=3):return len(items),flag\n'
                              'box=Box()\n'
                              'print(box.f(*[1,2]),box.f(*(),flag=7))\n',
 'extra_bound_noniterable': 'class Box:\n def f(self,a):return a\nBox().f(*3)\n',
 'extra_callee_alias_choice': 'def f(a,b):return a+b\n'
                              'def g(a,b):return a*b\n'
                              'for flag in [True,False]:\n'
                              ' call=f if flag else g\n'
                              ' print(call(*[2,3]))\n',
 'extra_single_star_rebinding_does_not_replace_owner': 'values=[1]\n'
                                                       'def change():\n'
                                                       ' global values\n'
                                                       ' values=[2]\n'
                                                       ' return "!"\n'
                                                       'print(*values,end=change())\n'
                                                       'print(values)\n',
 'extra_late_map_callback_sees_keyword_rebind': 'value=1\n'
                                                'def read(x):return value+x\n'
                                                'def change():\n'
                                                ' global value\n'
                                                ' value=5\n'
                                                ' return "!"\n'
                                                'print(*map(read,[1,2]),end=change())\n',
 'extra_eager_map_callback_precedes_keyword_rebind': 'value=1\n'
                                                     'def read(x):return value+x\n'
                                                     'def change():\n'
                                                     ' global value\n'
                                                     ' value=5\n'
                                                     ' return "!"\n'
                                                     'print(0,*map(read,[1,2]),end=change())\n',
 'extra_shared_empty_and_fresh_nonempty_tuple': 'def f(*items):return items\n'
                                                'values=(1,2)\n'
                                                'print(f(*values)is values,f(*())is '
                                                'f(),f(*f(1,2)))\n',
 'extra_mixed_types_fixed_prefix': 'def f(a,*items):return a,items\nprint(f("head",*[1,2,3]))\n',
 'extra_keyword_before_star_changes_owner_after_capture': 'values=[1]\n'
                                                          'def change():\n'
                                                          ' values.append(2)\n'
                                                          ' return "!"\n'
                                                          'print(end=change(),*values)\n',
 'extra_multiline_iterator_error': 'def item(value):\n'
                                   ' print("item",value)\n'
                                   ' return 1//value\n'
                                   'print(\n'
                                   ' *map(item,[1,0]),\n'
                                   ' sep=":"\n'
                                   ')\n',
 'extra_multiline_multiple_star_error': 'def item(value):\n'
                                        ' print("item",value)\n'
                                        ' return 1//value\n'
                                        'print(\n'
                                        ' *map(item,[1,0]),\n'
                                        ' *[2],\n'
                                        ' sep=":"\n'
                                        ')\n',
 'extra_separator_type_error': 'def item(value):\n'
                               ' print("item",value)\n'
                               ' return value\n'
                               'print(*map(item,[1,2]),sep=3)\n',
 'extra_end_type_error': 'def item(value):\n'
                         ' print("item",value)\n'
                         ' return value\n'
                         'print(*map(item,[1,2]),end=3)\n',
 'compat_ordinary_integer_print': 'answers=[3,1,4]\n'
                                  'print(*answers)\n'
                                  'print("prefix",*answers,"suffix",sep=":",end="!",flush=True)\n',
 'compat_ordinary_deque_print': 'from collections import deque\n'
                                'answers=deque([3,1,4])\n'
                                'print(*answers)\n'
                                'print("prefix",*answers,"suffix",sep=":")\n'
                                'print(*deque([8,9]),end="!",flush=True)\n',
 'compat_fixed_tuple_mixed_fields': 'def f(a,b,c):return a,b,c\nprint(f(*("a",True,3)))\n',
 'compat_empty_sources_and_keyword_filling': 'def f(a,b=3,*,c=4):return a,b,c\n'
                                             'print(f(*[],a=2),f(*(),a=3,c=8))\n',
 'compat_nested_mutable_argument_alias': 'def f(a,*items):\n'
                                         ' a.append(5)\n'
                                         ' items[0].append(6)\n'
                                         ' return a is items[0],items\n'
                                         'values=[1]\n'
                                         'print(f(*[values,values]))\n'
                                         'print(values)\n',
 'compat_dormant_expanded_function': 'def dormant():\n print(*3)\nprint(4)\n',
 'compat_preexisting_print_capture': 'values=[1,2,3]\n'
                                     'print(values,values.pop())\n'
                                     'print(*values,values.pop())\n'
                                     'print(values)\n',
 'legacy_promoted_exact_former_boundary': 'def f(*items):return len(items)\nprint(f(*[1,2]))\n',
 'compat_ordinary_existing_deque_capture': 'from collections import deque\n'
                                           'q=deque([1,2,3])\n'
                                           'print(q,q.pop(),q)\n'
                                           'q=deque([1,2,3])\n'
                                           'print(q,*q,q.pop(),q)\n'
                                           'values=[1,2]\n'
                                           'print(values,values.pop(),values)\n'
                                           'values=[1,2]\n'
                                           'print(*values,values.pop(),values)\n',
 'compat_ordinary_printable_sequences': 'from collections import deque\n'
                                        'strings=["a","b"]\n'
                                        'print(*strings,sep=":")\n'
                                        'print(*deque([True,False]))\n'
                                        'print(*[1.5,None,b"x"])\n'
                                        'print(*((1,2),(3,4)))\n',
 'compat_ordinary_tuple_later_effect': 'values=[1,2]\nprint(*(values,),values.pop())\n',
 'compat_finite_nested_variadic_pack': 'def f(*items):return items\n'
                                       'values=[1,2]\n'
                                       'print(f(*[values],values.pop()))\n'}

class ExpandedCallProofTests(unittest.TestCase):
    def test_actual_recursive_lists_keep_the_explicit_storage_boundary(self):
        for source in ("class Marker:pass\nvalues=[]\nvalues.append(values)\n","class Marker:pass\nvalues=[1]\nother=[values]\nvalues.append(other)\n"):
            for integer in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=integer,filename="cycle.py"))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,"E006")
                self.assertIn("recursive",result.diagnostics[0].message)

    def test_normalization_is_opt_in_and_preserves_original_segments(self):
        node=ast.parse("f(a=keyword(),*left(),*right())",mode="eval").body
        before=ast.dump(node,include_attributes=True)
        with self.assertRaises(CallBindingError):normalize_call(node)
        arguments=normalize_call(node,allow_starred=True)
        self.assertTrue(arguments.expanded)
        self.assertEqual([argument.spread for argument in arguments.positional],[True,True])
        self.assertIs(arguments.positional[0].expression,node.args[0].value)
        self.assertIs(arguments.positional[1].expression,node.args[1].value)
        self.assertIs(arguments.keywords[0].expression,node.keywords[0].value)
        self.assertEqual(arguments.evaluation_order,arguments.positional+arguments.keywords)
        self.assertEqual(ast.dump(node,include_attributes=True),before)

    def test_proved_ordinary_integer_print_retains_its_direct_adapter(self):
        source="values=[1,2]\nprint(*values)\n"
        program=build_program(source)
        for integer in ("i64","i128","bigint"):
            self.assertFalse(select_frames(program.main,integer=integer).required)
            self.assertFalse(needs_linking(program,integer=integer))
            with patch("py2fastrust.native_classes.try_generate_classes",side_effect=AssertionError("ordinary print needs no frame")),patch("py2fastrust.codegen.generate",side_effect=AssertionError("VM entered")):
                result=transpile(source,TranspileOptions(integer=integer))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')

    def test_imported_deque_keeps_its_canonical_linked_type(self):
        source="from collections import deque\nvalues=deque([1,2])\nprint(*values,sep=':')\n"
        program=build_program(source)
        for integer in ("i64","i128","bigint"):
            self.assertFalse(select_frames(program.main,integer=integer).required)
            self.assertTrue(needs_linking(program,integer=integer))
            with patch("py2fastrust.native_classes.try_generate_classes",wraps=try_generate_classes)as frames,patch("py2fastrust.codegen.generate",side_effect=AssertionError("VM entered")):
                result=transpile(source,TranspileOptions(integer=integer))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')
            self.assertEqual(frames.call_count,1)

    def test_reached_general_expansion_selects_frames_before_lowering(self):
        for source in ("print(*range(3))\n","def f(a,b):return a+b\nprint(f(*[1,2]))\n","def print(*items):return len(items)\nprint(*[1,2])\n"):
            selected=select_frames(build_program(source).main)
            self.assertTrue(selected.required)
            self.assertIn("expanded positional call arguments",selected.reasons)
        source="def dormant():print(*3)\nprint(4)\n"
        self.assertFalse(select_frames(build_program(source).main).required)

    def test_single_star_materialization_policy_uses_original_ast(self):
        source="def f(*items):return items\nprint(f(*[1]),f(0,*[2]))\n"
        unit=build_program(source).main;before=ast.dump(unit.tree,include_attributes=True)
        model=Model(unit.tree,unit.filename,"i64",unit.native_imports,unit=unit);model.run()
        sites=list(model.expanded_calls.sites.values())
        self.assertEqual(len(sites),2)
        self.assertEqual(sorted(site.deferred for site in sites),[False,True])
        self.assertTrue(all(site.node in list(ast.walk(unit.tree))for site in sites))
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)

    def test_selected_expansion_failure_never_retries_an_emitter(self):
        for integer in ("i64","i128","bigint"):
            with patch("py2fastrust.native_classes.try_generate_classes",return_value=None)as frames,patch("py2fastrust.native_scalar.ScalarGenerator.statements",side_effect=AssertionError("scalar retry")),patch("py2fastrust.native_bigint.try_generate_bigint",side_effect=AssertionError("BigInt retry")),patch("py2fastrust.codegen.generate",side_effect=AssertionError("VM entered")):
                result=transpile("print(*range(3))\n",TranspileOptions(integer=integer))
            self.assertFalse(result.success);self.assertEqual(frames.call_count,1)
            self.assertEqual(result.diagnostics[0].code,"E006")

    def test_remaining_keyword_and_builtin_protocols_name_the_boundary(self):
        for source,detail in (("def f(*items):return items\nprint(f(*[1],**{}))\n","expanded keyword"),("print(min(*[1,2]))\n","builtin 'min'")):
            for integer in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(integer=integer,filename="boundary.py"))
                self.assertFalse(result.success)
                diagnostic=result.diagnostics[0]
                self.assertEqual(diagnostic.code,"E006");self.assertGreater(diagnostic.line,0)
                self.assertEqual(diagnostic.filename,"boundary.py")
                self.assertIn(detail,diagnostic.message)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ExpandedCallExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness=execution.NativeIteratorReductionTests();cls.harness.setUpClass()
    @classmethod
    def tearDownClass(cls):cls.harness.tearDownClass()
    def compare(self,source):
        expected=subprocess.run([sys.executable,"-I","-c",source],capture_output=True,text=True,timeout=10)
        frame=lambda text:re.findall(r'File "[^\"]+", line (\d+), in ([^\n]+)',text)
        final=lambda text:text.rstrip().splitlines()[-1]if text.strip()else""
        for integer in ("i64","i128","bigint"):
            for optimize in (False,True):
                with self.subTest(integer=integer,optimize=optimize),patch("py2fastrust.codegen.generate",side_effect=AssertionError("general backend entered")):
                    generated=self.harness.compile(source,integer,release=optimize)
                    self.assertNotIn("enum Value",generated[2]);self.assertLess(len(generated[2].encode()),512*1024)
                    actual=subprocess.run([str(generated[1])],capture_output=True,text=True,timeout=10)
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                    self.assertEqual(final(actual.stderr),final(expected.stderr));self.assertEqual(frame(actual.stderr),frame(expected.stderr))


def case(source):
    def run(self):self.compare(source)
    return run
SOURCES['basic_canonical_linked_integer_deque_print']="from collections import deque\nvalues=deque([1,2])\nprint(*values,sep=':')\n"
for name,source in SOURCES.items():setattr(ExpandedCallExecutionTests,"test_"+name,case(source))

if __name__=="__main__":unittest.main()
