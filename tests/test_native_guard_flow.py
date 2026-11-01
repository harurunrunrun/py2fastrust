"""Canonical type guards refine finite local types without rewriting the AST."""
import shutil
import unittest
import test_native_union_ordering as helpers
from py2fastrust import transpile


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class GuardFlowExecutionTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeUnionOrderingTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeUnionOrderingTests.tearDownClass.__func__)
    compile=helpers.NativeUnionOrderingTests.compile
    exercise=helpers.NativeUnionOrderingTests.exercise

    def test_normalize_string_or_list(self):
        self.exercise('def normalize(s):\n if isinstance(s,str):s=[ord(c) for c in s]\n return s.copy()\nprint(normalize("cab"),normalize([3,1,2]))\n',("",))

    def test_string_input_only(self):
        self.exercise('def f(s):\n if isinstance(s,str):return s[::-1]\n return s.copy()\nprint(f("abc"))\n',("",))

    def test_list_input_only(self):
        self.exercise('def f(s):\n if isinstance(s,str):return ord(s[0])\n return s.copy()\nprint(f([4,5]))\n',("",))

    def test_separate_list_and_text_arms(self):
        self.exercise('def f(x):\n if isinstance(x,list):return x.copy()\n return x[::-1]\nprint(f("abc"),f([4,5]))\n',("",))

    def test_guard_not(self):
        self.exercise('def f(x):\n if not isinstance(x,str):return x.copy()\n return x[::-1]\nprint(f("abc"),f([4,5]))\n',("",))

    def test_same_spelling_user_predicate(self):
        self.exercise('def isinstance(value,info):return True\ndef f(x):\n if isinstance(x,str):return x+1\n return 99\nprint(f(5))\n',("",))

    def test_classinfo_shadow(self):
        self.exercise('str=int\ndef f(x):\n if isinstance(x,str):return x+1\n return len(x)\nprint(f(3))\n',("",))

    def test_captured_builtin_predicate(self):
        self.exercise('check=isinstance\ndef f(x):\n if check(x,list):return x.copy()\n return x[::-1]\nprint(f([4,5]),f("abc"))\n',("",))

    def test_captured_type_alias(self):
        self.exercise('Text=str\ndef f(x):\n if isinstance(x,Text):return x[::-1]\n return x.copy()\nprint(f([4,5]),f("abc"))\n',("",))

    def test_classinfo_effects(self):
        self.exercise('def info():\n print("type",end="|")\n return str\ndef f(x):\n if isinstance(x,info()):return x[0]\n return x[-1]\nprint(f("abc"))\n',("",))

    def test_callee_effects(self):
        self.exercise('def predicate():\n print("callee",end="|")\n return isinstance\ndef f(x):\n if predicate()(x,str):return x[0]\n return x[-1]\nprint(f("abc"))\n',("",))

    def test_bool_is_an_int(self):
        self.exercise('def f(x):\n if isinstance(x,int):return int(x)+1\n return 99\nprint(f(True),f(3))\n',("",))

    def test_tuple_classinfo(self):
        self.exercise('def f(x):\n if isinstance(x,(str,bytes)):return x[0]\n return x.copy()\nprint(f("abc"),f([4,5]))\n',("",))

    def test_tuple_order_short_circuit_invalid(self):
        self.exercise('def f(x):\n if isinstance(x,(str,3)):return x[0]\n return 99\nprint(f("abc"))\n',("",))

    def test_classinfo_rebinds_subject(self):
        self.exercise('def f(x):\n if isinstance(x,(x:=str)):return 1\n return x is str\nprint(f(3))\n',("",))

    def test_list_alias_preserved(self):
        self.exercise('def f(x):\n if isinstance(x,str):return [ord(c) for c in x]\n x.append(7)\n return x\na=[1,2]\nb=f(a)\nprint(a,b,a is b,f("ab"))\n',("",))

    def test_guard_after_call_result(self):
        self.exercise('def source(flag):\n if flag:return "cab"\n return [1,2]\ndef f(x):\n if isinstance(x,str):x=[ord(c) for c in x]\n return x.copy()\nprint(f(source(True)),f(source(False)))\n',("",))

    def test_captured_local_normalization(self):
        self.exercise('def f(s):\n def at(i):return s[i]\n if isinstance(s,str):s=[ord(c) for c in s]\n return s.copy(),at(0)\nprint(f("ab"),f([4,5]))\n',("",))

    def test_captured_readonly_branches(self):
        self.exercise('def f(s):\n def at(i):return s[i]\n if isinstance(s,str):return s[::-1],at(0)\n return s.copy(),at(0)\nprint(f("ab"),f([4,5]))\n',("",))

    def test_descendant_type_rebinding(self):
        self.exercise('def f(x):\n def mutate():\n  nonlocal x\n  x="done"\n if isinstance(x,list):mutate()\n return x[0]\nprint(f([1,2]),f("abc"))\n',("",))

    def test_lambda_readonly_capture(self):
        self.exercise('def f(s):\n at=lambda i:s[i]\n if isinstance(s,str):s=[ord(c) for c in s]\n return s.copy(),at(0)\nprint(f("ab"),f([4,5]))\n',("",))

    def test_source_class_guard(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef f(x):\n if isinstance(x,Box):return x.n\n return x+1\nprint(f(Box(7)),f(3))\n',("",))

    def test_source_class_guard_not(self):
        self.exercise('class Box:\n def __init__(self,n):self.n=n\ndef f(x):\n if not isinstance(x,Box):return x+1\n return x.n\nprint(f(Box(7)),f(3))\n',("",))

    def test_bytes_classinfo(self):
        self.exercise('def f(x):\n if isinstance(x,bytes):return x[::-1]\n return x.copy()\nprint(f(b"ab"),f([1,2]))\n',("",))


class GuardFlowCapabilityTests(unittest.TestCase):
    def test_zero_trip_loop_join_still_names_its_unsupported_operand(self):
        result=transpile('def f(flag):\n if flag:x="abc"\n else:x=[1,2]\n for i in range(2):\n  if isinstance(x,str):x=[ord(c) for c in x]\n return x.copy()\nprint(f(True),f(False))\n')
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertIn('copy',str(result.diagnostics[0]))
        self.assertIn('list[int] | str',str(result.diagnostics[0]))
