"""Shared parameter binding and argument evaluation, checked against Python."""
import ast
import inspect
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile, TranspileOptions
from py2fastrust.call_semantics import (CallBindingError, FunctionSignature,
                                       CallPlan, normalize_call)
from py2fastrust.frontend import build_program


class CallSemanticsTests(unittest.TestCase):
    def test_signature_binding_matches_official_python_for_random_fixed_calls(self):
        source="def f(a,b=20,/,c=30,*,d,e=None):pass\n"
        namespace={};exec(source,namespace)
        official=inspect.signature(namespace["f"])
        unit=build_program(source).main
        signature=unit.signature_for(unit.tree.body[0])
        rng=random.Random(71933)
        defaults={"b":20,"c":30,"e":None}
        for _ in range(1500):
            positional=list(range(rng.randrange(6)))
            names=rng.sample(["a","b","c","d","e","unknown"],rng.randrange(7))
            keywords=[(name,rng.choice([None,3,7]))for name in names]
            try:
                expected=official.bind(*positional,**dict(keywords));expected.apply_defaults()
            except TypeError:
                with self.assertRaises(CallBindingError):signature.bind(positional,keywords,defaults)
            else:
                actual=signature.bind(positional,keywords,defaults)
                self.assertEqual(dict(actual.by_name),dict(expected.arguments))

    def test_projection_captures_keyword_effects_once_in_source_order(self):
        unit=build_program("def f(a,b,*,c=7):pass\nf(b=mark(2),a=mark(1))\n").main
        signature=unit.signature_for(unit.tree.body[0])
        plan=signature.plan(normalize_call(unit.tree.body[1].value))
        seen=[]
        def evaluate(expression,parameter):
            seen.append((parameter,ast.unparse(expression)))
            return expression.args[0].value
        result=plan.capture(evaluate,defaults={"c":7})
        self.assertEqual(seen,[("b","mark(2)"),("a","mark(1)")])
        self.assertEqual(result.parameters,("a","b","c"))
        self.assertEqual(result.values,(1,2,7))
        self.assertEqual(result.defaults,frozenset({"c"}))

    def test_defaults_are_captured_values_and_preserve_identity_across_calls(self):
        signature=FunctionSignature.declaration(("values",),default_names=("values",))
        plan=signature.plan(normalize_call(ast.parse("f()",mode="eval").body))
        captured=[]
        def forbidden(*args):raise AssertionError("default expression was reevaluated")
        first=plan.capture(forbidden,defaults={"values":captured})
        first["values"].append(3)
        second=plan.capture(forbidden,defaults={"values":captured})
        self.assertIs(first["values"],second["values"])
        self.assertEqual(second["values"],[3])

    def test_none_is_a_value_and_is_distinct_from_a_missing_capture(self):
        signature=FunctionSignature.declaration(("value",),default_names=("value",))
        default=signature.bind([],defaults={"value":None})
        explicit=signature.bind([None])
        self.assertEqual(default.values,explicit.values)
        self.assertEqual(default.defaults,frozenset({"value"}))
        self.assertEqual(explicit.defaults,frozenset())
        with self.assertRaises(CallBindingError):signature.bind([])

    def test_method_receiver_and_constructor_projection_share_the_same_signature(self):
        source="class C:\n def __init__(self,first=3,/,*,second=4):pass\n"
        unit=build_program(source).main
        signature=unit.signature_for(unit.tree.body[0].body[0])
        call=normalize_call(ast.parse("f(second=9)",mode="eval").body)
        receiver=object()
        method=signature.plan(call,implicit_count=1).capture(lambda node,name:node.value,
                 implicit=(receiver,),defaults={"first":3,"second":4})
        constructor=signature.without_receiver().plan(call).capture(lambda node,name:node.value,
                 defaults={"first":3,"second":4})
        self.assertIs(method.values[0],receiver)
        self.assertEqual(method.values[1:],constructor.values)
        self.assertEqual(constructor.values,(3,9))

    def test_parameter_private_names_are_canonical_but_call_keywords_are_literal(self):
        source="class C:\n def f(self,__first=2,/,*,__second=3):pass\n"
        unit=build_program(source).main
        signature=unit.signature_for(unit.tree.body[0].body[0])
        self.assertEqual(signature.parameters,("self","_C__first","_C__second"))
        self.assertEqual(signature.bind([None],[("_C__second",9)],{"_C__first":2,"_C__second":3}).values,(None,2,9))
        with self.assertRaises(CallBindingError):signature.bind([None],[("__second",9)],{"_C__first":2,"_C__second":3})

    def test_default_slots_retain_definition_scope_and_evaluation_order(self):
        unit=build_program("value=3\ndef f(first=value,*,second=4):return first\n").main
        signature=unit.signature_for(unit.tree.body[1])
        self.assertEqual([slot.name for slot in signature.defaults],["first","second"])
        self.assertTrue(all(slot.definition_scope==0 for slot in signature.defaults))
        self.assertIs(signature.defaults[0].expression,unit.tree.body[1].args.defaults[0])
        self.assertEqual(signature.defaults[0].ordinal,unit.ordinal(signature.defaults[0].expression))

    def test_invalid_bindings_and_dynamic_expansion_are_explicit_boundaries(self):
        signature=FunctionSignature.declaration(("a","b"),positional_only=("a",),keyword_only=("c",))
        for args,keywords in [([],[]),([1,2,3],[("c",4)]),([1,2],[("c",3),("c",4)]),
                              ([1],[("a",2),("b",3),("c",4)]),([1,2],[("unknown",4)])]:
            with self.subTest(args=args,keywords=keywords),self.assertRaises(CallBindingError):signature.bind(args,keywords)
        for source in ("f(*values)","f(**values)"):
            with self.assertRaises(CallBindingError):normalize_call(ast.parse(source,mode="eval").body)
        unit=build_program("def f(*args,**kwargs):pass\n").main
        signature=unit.signature_for(unit.tree.body[0])
        self.assertEqual((signature.variadic_positional,signature.variadic_keyword),("args","kwargs"))
        with self.assertRaises(CallBindingError):signature.bind([])

    def test_all_native_planners_and_emitters_use_the_shared_binding_plan(self):
        sources=("def f(a,b=3,/,*,c=4):return a+b+c\nprint(f(1,c=9))\n",
                 "class C:\n def f(self,a=3,*,b=4):return a+b\nprint(C().f(b=9))\n",
                 "import math,bisect\nxs=[1,3,5]\nprint(math.perm(5),bisect.bisect_left(xs,3,hi=None,key=None))\n")
        real_bind,real_capture=FunctionSignature.bind,CallPlan.capture
        for source in sources:
            for mode in ("i64","i128","bigint"):
                with self.subTest(source=source,mode=mode), \
                     patch.object(FunctionSignature,"bind",autospec=True,side_effect=real_bind)as bind, \
                     patch.object(CallPlan,"capture",autospec=True,side_effect=real_capture)as capture:
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertGreater(bind.call_count,0)
                    self.assertGreater(capture.call_count,0)

    def test_invalid_unary_default_in_an_unused_method_is_not_silently_ignored(self):
        source="class C:\n def unused(self,value=-None):pass\nprint(7)\n"
        result=transpile(source)
        self.assertFalse(result.success)
        self.assertIsNone(result.rust_source)
        self.assertEqual(result.diagnostics[0].code,"E006")


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class CallSemanticsExecutionTests(unittest.TestCase):
    def compare(self,source):
        expected=subprocess.run([sys.executable,"-c",source],capture_output=True,text=True,timeout=5)
        with tempfile.TemporaryDirectory(prefix="pytors-call-semantics-")as directory:
            root=Path(directory)
            for mode in ("i64","i128","bigint"):
                with self.subTest(mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode,filename="calls.py"))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.backend,"native")
                    self.assertNotIn("struct Runtime",result.rust_source)
                    path=root/"program.rs";path.write_text(result.rust_source)
                    built=subprocess.run(["rustc","--edition=2021",str(path),"-o",str(root/"program")],capture_output=True,text=True,timeout=60)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(root/"program")],capture_output=True,text=True,timeout=5)
                    self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr+expected.stderr)

    def test_function_keyword_order_positional_only_defaults_and_void_calls(self):
        self.compare('''def mark(value):
 print(value)
 return value
def combine(a,b=3,/,*,c=4):
 print(a,b,c)
 return a+b+c
def notify(value=5):
 print(value)
print(combine(mark(1),c=mark(2)))
print(combine(mark(3),mark(4),c=mark(5)))
notify()
''')

    def test_constructor_and_method_keywords_keep_source_order(self):
        self.compare('''def mark(value):
 print(value)
 return value
class C:
 def __init__(self,a=2,*,b=3):
  self.value=a+b
 def method(self,a=4,/,*,b=5):
  return self.value+a+b
c=C(b=mark(7),a=mark(6))
print(c.method(b=mark(9)))
''')

    def test_module_builtin_binding_uses_the_same_projection(self):
        self.compare('''import math,bisect
def mark(value):
 print(value)
 return value
values=[1,3,5,7]
print(math.perm(mark(5)),math.perm(mark(5),None))
print(bisect.bisect_left(values,3,hi=mark(4),lo=mark(1),key=None))
print(bisect.bisect_right(values,3,mark(0),hi=None))
''')

    def test_class_defaults_are_captured_once_and_keep_private_parameter_names(self):
        self.compare('''class C:
 def __init__(self,__value=3):self.value=__value
 def read(self,__delta=4,/,*,__extra=5):
  return self.value+__delta+__extra
c=C(_C__value=7)
print(c.read(_C__extra=8),c.read())
''')

    def test_definition_defaults_are_independent_of_later_local_bindings(self):
        self.compare('''def f(value=7):return value
value=100
print(f(),f(value=9),f())
''')


if __name__=="__main__":unittest.main()
