"""Bounded native depth elision preserves source calls, effects and frames."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

from py2fastrust import transpile, TranspileOptions
from py2fastrust.native_finite_depth_calls import _weighted_bounds, Unproved
import test_native_lambda_callbacks as helpers


CASES = {'plain_acyclic': 'class Token:\n'
                  ' def __init__(self,value):self.value=value\n'
                  ' def read(self):return self.value\n'
                  '\n'
                  'def leaf(item):return item.value+1\n'
                  'def middle(item):return leaf(item)*2\n'
                  'print(middle(Token(7)))\n',
 'error_frame_chain': 'class Token:\n'
                      ' def __init__(self,value):self.value=value\n'
                      ' def read(self):return self.value\n'
                      '\n'
                      'def leaf(item):return item.value//0\n'
                      'def middle(item):return leaf(item)\n'
                      'print(middle(Token(7)))\n',
 'implicit_constructor': 'def seed(value):\n'
                         ' print("seed",value)\n'
                         ' return value+1\n'
                         'class Token:\n'
                         ' def __init__(self,value):self.value=seed(value)\n'
                         'print(Token(7).value)\n',
 'context_protocol': 'class Guard:\n'
                     ' def __init__(self,value):self.value=value\n'
                     ' def __enter__(self):\n'
                     '  print("enter",self.value)\n'
                     '  return self.value\n'
                     ' def __exit__(self,a,b,c):print("exit",self.value)\n'
                     'def leaf(value):return value+1\n'
                     'with Guard(7)as value:\n'
                     ' print(leaf(value))\n',
 'classmethod_callback': 'class Reader:\n'
                         ' @classmethod\n'
                         ' def convert(cls,value):return value+1\n'
                         'print(list(map(Reader.convert,[2,3,5])))\n',
 'default_limit_getter': 'import sys\n'
                         'class Token:\n'
                         ' def __init__(self,value):self.value=value\n'
                         ' def read(self):return self.value\n'
                         '\n'
                         'print(sys.getrecursionlimit(),Token(7).read())\n',
 'direct_setter': 'import sys\n'
                  'class Token:\n'
                  ' def __init__(self,value):self.value=value\n'
                  ' def read(self):return self.value\n'
                  '\n'
                  'sys.setrecursionlimit(40)\n'
                  'print(sys.getrecursionlimit(),Token(7).read())\n',
 'classmethod_callback_setter': 'import sys\n'
                                'class Reader:\n'
                                ' @classmethod\n'
                                ' def convert(cls,value):\n'
                                '  sys.setrecursionlimit(value)\n'
                                '  return value\n'
                                'print(list(map(Reader.convert,[40,50])))\n'
                                'print(sys.getrecursionlimit())\n',
 'context_setter': 'import sys\n'
                   'class Guard:\n'
                   ' def __enter__(self):\n'
                   '  sys.setrecursionlimit(40)\n'
                   '  return 7\n'
                   ' def __exit__(self,a,b,c):sys.setrecursionlimit(1000)\n'
                   'def leaf(value):return value+1\n'
                   'with Guard()as value:\n'
                   ' print(leaf(value),sys.getrecursionlimit())\n'
                   'print(sys.getrecursionlimit())\n',
 'recursive_function': 'class Token:\n'
                       ' def __init__(self,value):self.value=value\n'
                       ' def read(self):return self.value\n'
                       '\n'
                       'def descend(item,n):\n'
                       ' if n:return descend(item,n-1)+1\n'
                       ' return item.value\n'
                       'print(descend(Token(7),8))\n',
 'mutual_recursion': 'class Token:\n'
                     ' def __init__(self,value):self.value=value\n'
                     ' def read(self):return self.value\n'
                     '\n'
                     'def even(item,n):\n'
                     ' if n:return odd(item,n-1)\n'
                     ' return item.value\n'
                     'def odd(item,n):return even(item,n-1)\n'
                     'print(even(Token(7),8))\n',
 'generator_expression': 'class Token:\n'
                         ' def __init__(self,value):self.value=value\n'
                         ' def read(self):return self.value\n'
                         '\n'
                         'def leaf(item):return item.value\n'
                         'items=[Token(i)for i in range(5)]\n'
                         'print(sum(leaf(item)for item in items))\n',
 'pure_sort_callback': 'class Token:\n'
                       ' def __init__(self,value):self.value=value\n'
                       ' def read(self):return self.value\n'
                       '\n'
                       'def key(item):return -item.value\n'
                       'a=[Token(2),Token(3),Token(1)]\n'
                       'a.sort(key=key)\n'
                       'print([item.value for item in a])\n',
 'pure_filter_callback': 'class Token:\n'
                         ' def __init__(self,value):self.value=value\n'
                         ' def read(self):return self.value\n'
                         '\n'
                         'def keep(item):return item.value%2==1\n'
                         'a=[Token(i)for i in range(5)]\n'
                         'print([item.value for item in filter(keep,a)])\n',
 'long_acyclic_future_chain': 'class Token:\n'
                              ' def __init__(self,value):self.value=value\n'
                              ' def read(self):return self.value\n'
                              '\n'
                              'def f0(item):return f1(item)\n'
                              'def f1(item):return f2(item)\n'
                              'def f2(item):return f3(item)\n'
                              'def f3(item):return f4(item)\n'
                              'def f4(item):return f5(item)\n'
                              'def f5(item):return f6(item)\n'
                              'def f6(item):return f7(item)\n'
                              'def f7(item):return f8(item)\n'
                              'def f8(item):return f9(item)\n'
                              'def f9(item):return f10(item)\n'
                              'def f10(item):return f11(item)\n'
                              'def f11(item):return f12(item)\n'
                              'def f12(item):return f13(item)\n'
                              'def f13(item):return f14(item)\n'
                              'def f14(item):return f15(item)\n'
                              'def f15(item):return f16(item)\n'
                              'def f16(item):return f17(item)\n'
                              'def f17(item):return f18(item)\n'
                              'def f18(item):return f19(item)\n'
                              'def f19(item):return f20(item)\n'
                              'def f20(item):return f21(item)\n'
                              'def f21(item):return f22(item)\n'
                              'def f22(item):return f23(item)\n'
                              'def f23(item):return f24(item)\n'
                              'def f24(item):return f25(item)\n'
                              'def f25(item):return f26(item)\n'
                              'def f26(item):return f27(item)\n'
                              'def f27(item):return f28(item)\n'
                              'def f28(item):return f29(item)\n'
                              'def f29(item):return f30(item)\n'
                              'def f30(item):return f31(item)\n'
                              'def f31(item):return f32(item)\n'
                              'def f32(item):return f33(item)\n'
                              'def f33(item):return f34(item)\n'
                              'def f34(item):return f35(item)\n'
                              'def f35(item):return f36(item)\n'
                              'def f36(item):return f37(item)\n'
                              'def f37(item):return f38(item)\n'
                              'def f38(item):return f39(item)\n'
                              'def f39(item):return f40(item)\n'
                              'def f40(item):return item.value\n'
                              'print(f0(Token(7)))\n'}
LINKED = {'linked_saved_setter': 'import sys\n'
                        'from atcoder.modint import Modint,ModContext\n'
                        '\n'
                        'setter=sys.setrecursionlimit\n'
                        'setter(40)\n'
                        'with ModContext(101):\n'
                        ' print((Modint(7)+Modint(9)).val(),sys.getrecursionlimit())\n',
 'linked_classmethod_callback_setter': 'import sys\n'
                                       'from atcoder.modint import Modint,ModContext\n'
                                       '\n'
                                       'setter=sys.setrecursionlimit\n'
                                       'class Limits:\n'
                                       ' @classmethod\n'
                                       ' def change(cls,value):\n'
                                       '  setter(value)\n'
                                       '  return value\n'
                                       'print(list(map(Limits.change,[40,50])))\n'
                                       'with '
                                       'ModContext(101):print(Modint(7).val(),sys.getrecursionlimit())\n',
 'linked_tuple_setter': 'import sys\n'
                        'from atcoder.modint import Modint,ModContext\n'
                        '\n'
                        'callbacks=(sys.setrecursionlimit,)\n'
                        'callbacks[0](40)\n'
                        'with ModContext(101):print(Modint(7).val(),sys.getrecursionlimit())\n',
 'linked_generator_with_setter': 'import sys\n'
                                 'from atcoder.modint import Modint,ModContext\n'
                                 '\n'
                                 'sys.setrecursionlimit(40)\n'
                                 'with ModContext(101):print(sum((Modint(i)+Modint(1)).val()for i '
                                 'in range(5)))\n',
 'linked_default_limit_getter': 'import sys\n'
                                'from atcoder.modint import Modint,ModContext\n'
                                '\n'
                                'with '
                                'ModContext(101):print(Modint(7).val(),sys.getrecursionlimit())\n'}
MODULES = {'chain': {'main.py': 'import bridge\nprint(bridge.answer())\n',
           'leaf.py': 'class Token:\n'
                      ' def __init__(self,value):self.value=value\n'
                      'def read(item):return item.value\n',
           'bridge.py': 'import leaf\ndef answer():return leaf.read(leaf.Token(7))+1\n'},
 'import_in_function': {'main.py': 'class Token:\n'
                                   ' def __init__(self,value):self.value=value\n'
                                   'def answer(item):\n'
                                   ' import leaf\n'
                                   ' return leaf.read(item.value)\n'
                                   'print(answer(Token(7)))\n',
                        'leaf.py': 'def read(value):return value+1\n'},
 'nested_setter': {'main.py': 'import sys\n'
                              'import bridge\n'
                              'class Token:\n'
                              ' def __init__(self,value):self.value=value\n'
                              'print(Token(7).value,bridge.value,sys.getrecursionlimit())\n',
                   'leaf.py': 'import sys\nsetter=sys.setrecursionlimit\nsetter(40)\nvalue=7\n',
                   'bridge.py': 'import leaf\nvalue=leaf.value+1\n'},
 'cycle': {'first.py': 'import second\n'
                       'class Token:\n'
                       ' def __init__(self,value):self.value=value\n'
                       'def read():return Token(second.value).value\n',
           'main.py': 'import first\nprint(first.read())\n',
           'second.py': 'import first\nvalue=7\n'}}


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeFiniteDepthTests(unittest.TestCase):
    setUpClass = classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)
    exercise = helpers.NativeLambdaCallbackTests.exercise

    def exercise_project(self, source, files=None, acl=False):
        folder = Path(self.directory.name) / hashlib.sha256(repr((source, files)).encode()).hexdigest()
        folder.mkdir(exist_ok=True)
        if files:
            for name, text in files.items():
                (folder / name).write_text(text)
        path = folder / "main.py"
        path.write_text(source)
        vendor = Path(__file__).resolve().parents[1] / "py2fastrust/vendor/ac_library_python"
        environment = {**os.environ, "PYTHONPATH": str(vendor) if acl else str(folder)}
        expected = subprocess.run([sys.executable, str(path)], text=True, capture_output=True,
                                  timeout=10, env=environment)
        for mode in ("i64", "i128", "bigint"):
            result = transpile(source, TranspileOptions(integer=mode, filename=str(path)))
            self.assertTrue(result.success, result.diagnostics)
            self.assertEqual(result.backend, "native")
            for optimize in (False, True):
                rust = folder / (mode + ("_opt" if optimize else "_debug") + ".rs")
                rust.write_text(result.rust_source)
                binary = rust.with_suffix("")
                built = subprocess.run(["rustc", "--edition=2021", "--crate-name", "depth_case",
                    *(["-O"] if optimize else []), str(rust), "-o", str(binary)],
                    text=True, capture_output=True, timeout=120)
                self.assertEqual(built.returncode, 0, built.stderr)
                actual = subprocess.run([str(binary)], text=True, capture_output=True, timeout=10,
                    env={**os.environ, "PATH": "/pytors-no-runtime-dependencies"})
                self.assertEqual(actual.stdout, expected.stdout)
                self.assertEqual(actual.returncode, expected.returncode, actual.stderr)
                if expected.returncode:
                    self.assertEqual(actual.stderr.splitlines()[-1].split(":")[0],
                                     expected.stderr.splitlines()[-1].split(":")[0])
                    frames = r'File ".*?", line (\d+), in ([^\n]+)'
                    self.assertEqual(re.findall(frames, actual.stderr), re.findall(frames, expected.stderr))
                else:
                    self.assertEqual(actual.stderr, "")

    def test_proved_finite_calls_remove_counter_only(self):
        result = transpile(CASES["plain_acyclic"])
        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("class_sync_call", result.rust_source)
        self.assertNotIn("let _depth=ClassSyncDepth(scope)", result.rust_source)
        self.assertIn("error.frames.push((line,caller))", result.rust_source)

    def test_setter_and_generator_keep_counters(self):
        for key in ("direct_setter", "generator_expression"):
            result = transpile(CASES[key])
            self.assertTrue(result.success, result.diagnostics)
            self.assertIn("let _depth=ClassSyncDepth(scope)", result.rust_source)

    def test_zero_counter_cycle_is_bounded(self):
        bounds, zeros = _weighted_bounds({0: {0}, 1: {0}}, {0: 0, 1: 2})
        self.assertEqual(bounds[1], 2)
        self.assertEqual(zeros, 1)

    def test_positive_counter_cycle_is_unproved(self):
        with self.assertRaises(Unproved):
            _weighted_bounds({0: {1}, 1: {0}}, {0: 1, 1: 0})

    def test_plain_acyclic(self):
        self.exercise(CASES['plain_acyclic'])

    def test_error_frame_chain(self):
        self.exercise(CASES['error_frame_chain'])

    def test_implicit_constructor(self):
        self.exercise(CASES['implicit_constructor'])

    def test_context_protocol(self):
        self.exercise(CASES['context_protocol'])

    def test_classmethod_callback(self):
        self.exercise(CASES['classmethod_callback'])

    def test_default_limit_getter(self):
        self.exercise(CASES['default_limit_getter'])

    def test_direct_setter(self):
        self.exercise(CASES['direct_setter'])

    def test_classmethod_callback_setter(self):
        self.exercise(CASES['classmethod_callback_setter'])

    def test_context_setter(self):
        self.exercise(CASES['context_setter'])

    def test_recursive_function(self):
        self.exercise(CASES['recursive_function'])

    def test_mutual_recursion(self):
        self.exercise(CASES['mutual_recursion'])

    def test_generator_expression(self):
        self.exercise(CASES['generator_expression'])

    def test_pure_sort_callback(self):
        self.exercise(CASES['pure_sort_callback'])

    def test_pure_filter_callback(self):
        self.exercise(CASES['pure_filter_callback'])

    def test_long_acyclic_future_chain(self):
        self.exercise(CASES['long_acyclic_future_chain'])

    def test_linked_saved_setter(self):
        self.exercise_project(LINKED['linked_saved_setter'], acl=True)

    def test_linked_classmethod_callback_setter(self):
        self.exercise_project(LINKED['linked_classmethod_callback_setter'], acl=True)

    def test_linked_tuple_setter(self):
        self.exercise_project(LINKED['linked_tuple_setter'], acl=True)

    def test_linked_generator_with_setter(self):
        self.exercise_project(LINKED['linked_generator_with_setter'], acl=True)

    def test_linked_default_limit_getter(self):
        self.exercise_project(LINKED['linked_default_limit_getter'], acl=True)

    def test_module_chain(self):
        self.exercise_project(MODULES['chain']["main.py"], files=MODULES['chain'])

    def test_module_import_in_function(self):
        self.exercise_project(MODULES['import_in_function']["main.py"], files=MODULES['import_in_function'])

    def test_module_nested_setter(self):
        self.exercise_project(MODULES['nested_setter']["main.py"], files=MODULES['nested_setter'])

    def test_module_cycle(self):
        self.exercise_project(MODULES['cycle']["main.py"], files=MODULES['cycle'])


if __name__ == "__main__":
    unittest.main()
