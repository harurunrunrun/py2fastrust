"""Finite source-function identities retain binding/default and call order."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

from py2fastrust import transpile,TranspileOptions
import test_native_lambda_callbacks as helpers

CASES={'required_cross_scope_rebinding': ('def first(n):\n'
                                    ' if n<=0:return 0\n'
                                    ' return 1+first(n-1)\n'
                                    'def second(n):return 100+n\n'
                                    'alias=first\n'
                                    'def switch():\n'
                                    ' global alias\n'
                                    ' alias=second\n'
                                    'switch()\n'
                                    'print(alias(2),first(3))\n',
                                    ('',)),
 'current_callee_before_argument_effects': ('def first(value):\n'
                                            ' print("first",value)\n'
                                            ' return value+1\n'
                                            'def second(value):\n'
                                            ' print("second",value)\n'
                                            ' return value+100\n'
                                            'alias=first\n'
                                            'def switch():\n'
                                            ' global alias\n'
                                            ' print("switch")\n'
                                            ' alias=second\n'
                                            ' return 4\n'
                                            'print(alias(switch()))\n'
                                            'print(alias(5))\n',
                                            ('',)),
 'captured_alias_keeps_function_identity': ('def first(value):return value+1\n'
                                            'def second(value):return value+100\n'
                                            'alias=first\n'
                                            'saved=alias\n'
                                            'def switch():\n'
                                            ' global alias\n'
                                            ' alias=second\n'
                                            'switch()\n'
                                            'print(saved(3),alias(3),saved is first,alias is '
                                            'second,saved==first,saved is alias)\n',
                                            ('',)),
 'per_function_default_identity': ('def first(value=3):return value+1\n'
                                   'def second(value=20):return value+100\n'
                                   'alias=first\n'
                                   'saved=alias\n'
                                   'def switch():\n'
                                   ' global alias\n'
                                   ' alias=second\n'
                                   'switch()\n'
                                   'print(saved(),alias(),saved(5),alias(5))\n',
                                   ('',)),
 'mutable_defaults_stay_with_function': ('def first(values=[1]):\n'
                                         ' values.append(2)\n'
                                         ' return values\n'
                                         'def second(values=[7]):\n'
                                         ' values.append(9)\n'
                                         ' return values\n'
                                         'alias=first\n'
                                         'saved=alias\n'
                                         'def switch():\n'
                                         ' global alias\n'
                                         ' alias=second\n'
                                         'print(alias())\n'
                                         'switch()\n'
                                         'print(saved(),alias())\n'
                                         'print(saved(),alias())\n',
                                         ('',)),
 'function_parameter_and_return': ('def first(value):return value+1\n'
                                   'def second(value):return value+100\n'
                                   'def apply(function,value):return function(value)\n'
                                   'def choose(selected):\n'
                                   ' if selected:return first\n'
                                   ' return second\n'
                                   'print(apply(choose(int(input())),3))\n',
                                   ('0\n', '1\n')),
 'conditional_local_reference': ('def first(value):return value+1\n'
                                 'def second(value):return value+100\n'
                                 'def run(selected):\n'
                                 ' callback=first\n'
                                 ' if selected:callback=second\n'
                                 ' return callback(3)\n'
                                 'print(run(int(input())))\n',
                                 ('0\n', '1\n')),
 'mutual_recursion_through_cells': ('def first(value):\n'
                                    ' if value:return alias(value-1)+1\n'
                                    ' return 0\n'
                                    'def second(value):\n'
                                    ' if value:return first(value-1)+2\n'
                                    ' return 10\n'
                                    'alias=first\n'
                                    'def switch():\n'
                                    ' global alias\n'
                                    ' alias=second\n'
                                    'switch()\n'
                                    'print(first(int(input())))\n',
                                    ('0\n', '1\n', '6\n')),
 'unbound_callee_precedes_arguments': ('def mark():\n'
                                       ' print("argument")\n'
                                       ' return 3\n'
                                       'def first(value):return value+1\n'
                                       'print("before")\n'
                                       'print(alias(mark()))\n'
                                       'alias=first\n',
                                       ('',)),
 'function_definition_callee_before_definition': ('def mark():\n'
                                                  ' print("argument")\n'
                                                  ' return 3\n'
                                                  'print("before")\n'
                                                  'print(first(mark()))\n'
                                                  'def first(value):return value+1\n',
                                                  ('',)),
 'callee_deleted_and_rebound': ('def first(value):return value+1\n'
                                'def second(value):return value+100\n'
                                'alias=first\n'
                                'def clear():\n'
                                ' global alias\n'
                                ' del alias\n'
                                'clear()\n'
                                'if int(input()):\n'
                                ' alias=second\n'
                                'print(alias(3))\n',
                                ('0\n', '1\n')),
 'signature_dispatch_order': ('def mark(label,value):\n'
                              ' print(label)\n'
                              ' return value\n'
                              'def first(value):return value+1\n'
                              'def second(value,extra=20):return value+extra\n'
                              'alias=first\n'
                              'def switch():\n'
                              ' global alias\n'
                              ' alias=second\n'
                              'if int(input()):switch()\n'
                              'print(alias(mark("left",2),mark("right",4)))\n',
                              ('0\n', '1\n')),
 'keyword_and_positional_only': ('def first(value,/,*,scale=2):return value*scale\n'
                                 'def second(value,/,*,scale=5):return value+scale\n'
                                 'alias=first\n'
                                 'def switch():\n'
                                 ' global alias\n'
                                 ' alias=second\n'
                                 'if int(input()):switch()\n'
                                 'print(alias(3,scale=4))\n',
                                 ('0\n', '1\n')),
 'function_name_binding_rebound': ('def first(value):return value+1\n'
                                   'def second(value):return value+100\n'
                                   'saved=first\n'
                                   'def switch():\n'
                                   ' global first\n'
                                   ' first=second\n'
                                   'switch()\n'
                                   'print(saved(3),first(3),saved is first)\n',
                                   ('',)),
 'reference_collections': ('def first(value):return value+1\n'
                           'def second(value):return value+100\n'
                           'callbacks=[first,second]\n'
                           'print(callbacks[0](3),callbacks[1](3))\n'
                           'for callback in callbacks:print(callback(4))\n',
                           ('',)),
 'definition_mixed_with_integer': ('def first(value):return value+1\n'
                                   'saved=first\n'
                                   'first=7\n'
                                   'print(saved(3),saved is first)\n'
                                   'first(2)\n',
                                   ('',)),
 'alias_optional_function': ('def first(value):return value+1\n'
                             'alias=first\n'
                             'if int(input()):alias=None\n'
                             'print(bool(alias),alias is None)\n'
                             'print(alias(3))\n',
                             ('0\n', '1\n')),
 'local_callable_delete': ('def first(value):return value+1\n'
                           'def run(flag):\n'
                           ' callback=first\n'
                           ' del callback\n'
                           ' if flag:callback=first\n'
                           ' return callback(3)\n'
                           'print(run(int(input())))\n',
                           ('0\n', '1\n')),
 'local_parameter_builtin_spelling': ('def first(value):return value+1\n'
                                      'def apply(len):return len(3)\n'
                                      'print(apply(first))\n',
                                      ('',)),
 'effectful_callable_field': ('def first(value):return value+1\n'
                              'def second(value):return value+100\n'
                              'class Box:\n'
                              ' def __init__(self):self.callback=first\n'
                              ' def change(self):\n'
                              '  print("change")\n'
                              '  self.callback=second\n'
                              '  return 3\n'
                              'box=Box()\n'
                              'print(box.callback(box.change()))\n'
                              'print(box.callback(3))\n',
                              ('',)),
 'self_name_rebinding_recursion': ('def second(value):return value+100\n'
                                   'def first(value):\n'
                                   ' global first\n'
                                   ' if value:\n'
                                   '  first=second\n'
                                   '  return first(value-1)\n'
                                   ' return 0\n'
                                   'saved=first\n'
                                   'print(saved(3),first(3),saved(0))\n',
                                   ('',)),
 'signature_unexpected_before_toomany': ('def first(value):return value\n'
                                         'alias=first\n'
                                         'alias(1,2,extra=3)\n',
                                         ('',)),
 'signature_duplicate_before_toomany': ('def first(value):return value\n'
                                        'alias=first\n'
                                        'alias(1,2,value=3)\n',
                                        ('',)),
 'signature_keywordonly_toomany': ('def first(value,*,extra=4):return value+extra\n'
                                   'alias=first\n'
                                   'alias(1,2,extra=3)\n',
                                   ('',)),
 'signature_positionalonly_error_priority': ('def first(one,two,/,third):return one+two+third\n'
                                             'alias=first\n'
                                             'alias(1,one=3,extra=4,two=5)\n',
                                             ('',)),
 'signature_unexpected_then_duplicate': ('def first(one,two):return one+two\n'
                                         'alias=first\n'
                                         'alias(1,extra=4,one=3)\n',
                                         ('',)),
 'signature_missing_multiple_positional': ('def first(one,two,three,four):return '
                                           'one+two+three+four\n'
                                           'alias=first\n'
                                           'alias()\n',
                                           ('',)),
 'signature_missing_multiple_keywordonly': ('def first(*,one,two,three):return one+two+three\n'
                                            'alias=first\n'
                                            'alias()\n',
                                            ('',)),
 'noncallable_captures_all_arguments': ('def mark(name):\n'
                                        ' print(name)\n'
                                        ' return 3\n'
                                        'def first(value):return value\n'
                                        'alias=first\n'
                                        'alias=5\n'
                                        'alias(mark("one"),other=mark("two"))\n',
                                        ('',)),
 'delete_source_function_retains_saved': ('def first(value):return value+1\n'
                                          'saved=first\n'
                                          'del first\n'
                                          'print(saved(3))\n'
                                          'first(2)\n',
                                          ('',)),
 'function_identity_membership': ('def first(value):return value+1\n'
                                  'def second(value):return value+100\n'
                                  'items=[first,second]\n'
                                  'saved=first\n'
                                  'print(saved in items,first==second,first==3,first is '
                                  'None,first!=None)\n',
                                  ('',)),
 'conditional_source_definition_builtin': ('write=print\n'
                                           'result=write("alias",sep=":",end="|",flush=True)\n'
                                           'print(result)\n'
                                           'def print(x):\n'
                                           ' return x+3\n'
                                           'write(print(4))\n',
                                           ('',)),
 'definition_mixed_with_integer_call': ('def first(value):return value+1\n'
                                        'saved=first\n'
                                        'first=7\n'
                                        'print(saved(3))\n'
                                        'first(2)\n',
                                        ('',)),
 'local_delete_parameter': ('def first(value):return value+1\n'
                            'def run(callback):\n'
                            ' del callback\n'
                            ' return callback(3)\n'
                            'print(run(first))\n',
                            ('',)),
 'local_delete_unbound': ('def first(value):return value+1\n'
                          'def run():\n'
                          ' del callback\n'
                          ' callback=first\n'
                          ' return callback(3)\n'
                          'print(run())\n',
                          ('',)),
 'required_original_alias_deletion': ('def first(n):\n'
                                      ' if n<=0:return 0\n'
                                      ' return 1+first(n-1)\n'
                                      'alias=first\n'
                                      'del alias\n'
                                      'if False:alias=7\n'
                                      'print(first(2))\n',
                                      ('',)),
 'function_default_reference_identity': ('def first(value):return value+1\n'
                                         'def second(value):return value+100\n'
                                         'def apply(value,callback=first):return callback(value)\n'
                                         'first=second\n'
                                         'print(apply(3),apply(3,first))\n',
                                         ('',)),
 'signature_default_range_toomany': ('def first(one,two=3):return one+two\n'
                                     'alias=first\n'
                                     'alias(1,2,3)\n',
                                     ('',)),
 'callback_keyword_callee_capture': ('def first(value=3):return value+1\n'
                                     'def second(value=7):return value+100\n'
                                     'alias=first\n'
                                     'def switch():\n'
                                     ' global alias\n'
                                     ' alias=second\n'
                                     ' print("switch")\n'
                                     ' return 4\n'
                                     'print(alias(value=switch()),alias())\n',
                                     ('',)),
 'module_comprehension_source_function_rebinding': ('def first(value):return value+1\n'
                                                    'saved=first\n'
                                                    'values=[(first:=7)for unused in '
                                                    'range(int(input()))]\n'
                                                    'print(saved(3),values)\n'
                                                    'print(first(2))\n',
                                                    ('0\n', '1\n')),
 'computed_callee_is_captured': ('def first(value):return value+1\n'
                                 'def second(value):return value+100\n'
                                 'alias=first\n'
                                 'def choose():\n'
                                 ' print("choose")\n'
                                 ' return alias\n'
                                 'def switch():\n'
                                 ' global alias\n'
                                 ' alias=second\n'
                                 ' print("switch")\n'
                                 ' return 3\n'
                                 'print(choose()(switch()),alias(4))\n',
                                 ('',)),
 'conditional_callee': ('def first(value):return value+1\n'
                        'def second(value):return value+100\n'
                        'def mark():\n'
                        ' print("argument")\n'
                        ' return 3\n'
                        'print((first if int(input()) else second)(mark()))\n',
                        ('0\n', '1\n')),
 'effectful_receiver_callable_field': ('def first(value):return value+1\n'
                                       'class Box:\n'
                                       ' def __init__(self):self.callback=first\n'
                                       'box=Box()\n'
                                       'def receiver():\n'
                                       ' print("receiver")\n'
                                       ' return box\n'
                                       'def argument():\n'
                                       ' print("argument")\n'
                                       ' return 3\n'
                                       'print(receiver().callback(argument()))\n',
                                       ('',)),
 'function_reference_list_pop_dispatch': ('def first(value):return value+1\n'
                                          'def second(value):return value+100\n'
                                          'callbacks=[first,second]\n'
                                          'print(callbacks[0](callbacks.pop(0)(3)))\n'
                                          'print(callbacks[0](3),len(callbacks))\n',
                                          ('',))}


def frames(stderr):
    result=[]
    for line in stderr.splitlines():
        match=re.search(r'File ".*?", line (\d+), in ([^\n]+)',line)
        if match:result.append((int(match[1]),match[2]))
        repeated=re.search(r'\[Previous line repeated (\d+) more times\]',line)
        if repeated and result:result.extend([result[-1]]*int(repeated[1]))
    return result


def final_error(stderr):
    text=stderr.rstrip().splitlines()[-1]if stderr.strip()else ""
    # Suggestions belong to CPython's display hook, not the exception message.
    return re.sub(r"\. Did you mean: .*$", "",text)


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class NativeCallableCellTests(unittest.TestCase):
    setUpClass=classmethod(helpers.NativeLambdaCallbackTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.NativeLambdaCallbackTests.tearDownClass.__func__)

    def exercise(self,name,*,prune=True):
        source,inputs=CASES[name]
        # Capture CP outcomes before the converter sees this ordinary source.
        expected=[subprocess.run([sys.executable,"-I","-S","-c",source],input=data,
                  text=True,capture_output=True,timeout=15)for data in inputs]
        for mode in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode,optimize=prune,filename="callables.py"))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,"native")
            if prune:self.assertLess(len(result.rust_source.encode()),512*1024)
            for marker in ("enum Value","enum Op","struct Runtime","struct PegParser"):
                self.assertNotIn(marker,result.rust_source)
            for optimized in (False,True):
                key=(source,mode,optimized,prune)
                if key not in self.cache:
                    stem=hashlib.sha256(repr(key).encode()).hexdigest()
                    rust=Path(self.directory.name)/(stem+".rs");rust.write_text(result.rust_source)
                    binary=rust.with_suffix("")
                    build=subprocess.run(["rustc","--edition=2021","--crate-name","callables",
                        *(["-O"]if optimized else[]),str(rust),"-o",str(binary)],
                        capture_output=True,text=True,timeout=180)
                    self.assertEqual(build.returncode,0,build.stderr)
                    self.cache[key]=binary
                for data,reference in zip(inputs,expected):
                    with self.subTest(case=name,integer=mode,optimized=optimized,input=data,prune=prune):
                        actual=subprocess.run([str(self.cache[key])],input=data,text=True,capture_output=True,
                            timeout=15,env={**os.environ,"PATH":"/pytors-no-runtime-dependencies"})
                        self.assertEqual(actual.stdout,reference.stdout)
                        self.assertEqual(actual.returncode,reference.returncode,actual.stderr)
                        self.assertEqual(frames(actual.stderr),frames(reference.stderr))
                        self.assertEqual(final_error(actual.stderr),final_error(reference.stderr))

    def test_required_cross_scope_rebinding_and_deletion(self):
        for name in ("required_cross_scope_rebinding","required_original_alias_deletion"):
            self.exercise(name)

    def test_callee_is_captured_before_argument_effects(self):
        for name in ("current_callee_before_argument_effects","effectful_callable_field"):
            self.exercise(name)

    def test_saved_identity_and_mutable_defaults(self):
        for name in ("captured_alias_keeps_function_identity","per_function_default_identity","mutable_defaults_stay_with_function"):
            self.exercise(name)

    def test_parameter_return_and_conditional_references(self):
        for name in ("function_parameter_and_return","conditional_local_reference","local_parameter_builtin_spelling"):
            self.exercise(name)

    def test_recursive_current_bindings(self):
        for name in ("mutual_recursion_through_cells","self_name_rebinding_recursion"):
            self.exercise(name)

    def test_unbound_callee_precedes_arguments(self):
        for name in ("unbound_callee_precedes_arguments","function_definition_callee_before_definition"):
            self.exercise(name)

    def test_module_deletion_and_rebinding(self):
        for name in ("callee_deleted_and_rebound","delete_source_function_retains_saved"):
            self.exercise(name)

    def test_local_deletion(self):
        for name in ("local_callable_delete","local_delete_parameter","local_delete_unbound"):
            self.exercise(name)

    def test_selected_signature_and_explicit_argument_effects(self):
        for name in ("signature_dispatch_order","keyword_and_positional_only","noncallable_captures_all_arguments"):
            self.exercise(name)

    def test_signature_error_priority_and_missing_parameters(self):
        for name in ("signature_unexpected_before_toomany","signature_duplicate_before_toomany",
                     "signature_keywordonly_toomany","signature_positionalonly_error_priority",
                     "signature_unexpected_then_duplicate","signature_missing_multiple_positional",
                     "signature_missing_multiple_keywordonly"):
            self.exercise(name)

    def test_mixed_function_and_noncallable_slots(self):
        for name in ("alias_optional_function","definition_mixed_with_integer_call"):
            self.exercise(name)

    def test_reference_collections_and_source_name_rebinding(self):
        for name in ("reference_collections","function_name_binding_rebound","function_identity_membership"):
            self.exercise(name)

    def test_no_pruning_uses_same_callable_semantics(self):
        self.exercise("current_callee_before_argument_effects",prune=False)

    def test_function_reference_defaults_and_keyword_capture(self):
        for name in ("function_default_reference_identity","signature_default_range_toomany","callback_keyword_callee_capture"):
            self.exercise(name)

    def test_comprehension_rebinds_current_module_function(self):
        self.exercise("module_comprehension_source_function_rebinding")

    def test_computed_and_conditional_callees(self):
        for name in ("computed_callee_is_captured","conditional_callee"):
            self.exercise(name)

    def test_effectful_receiver_and_function_list_pop(self):
        for name in ("effectful_receiver_callable_field","function_reference_list_pop_dispatch"):
            self.exercise(name)

    def test_builtin_capture_is_an_explicit_required_boundary(self):
        source,_=CASES["conditional_source_definition_builtin"]
        for mode in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode,filename="callables.py"))
            self.assertFalse(result.success)
            self.assertTrue(any("builtin"in str(diagnostic)and"definition"in str(diagnostic)for diagnostic in result.diagnostics),result.diagnostics)

    def test_ambiguous_integer_identity_is_an_explicit_required_boundary(self):
        source,_=CASES["definition_mixed_with_integer"]
        for mode in ("i64","i128","bigint"):
            result=transpile(source,TranspileOptions(integer=mode,filename="callables.py"))
            self.assertFalse(result.success)
            self.assertTrue(any("comparison 'is'"in str(diagnostic)for diagnostic in result.diagnostics),result.diagnostics)

    def test_reference_cloneability_does_not_imply_object_immutability(self):
        from py2fastrust.native_aot_callables import AotFunctionType
        from py2fastrust.native_types import TupleType,immutable,reference_cloneable
        kind=AotFunctionType((1,2))
        self.assertTrue(reference_cloneable(kind))
        self.assertTrue(reference_cloneable(TupleType((kind,"int"))))
        self.assertFalse(immutable(kind))
        self.assertFalse(immutable(TupleType((kind,"int"))))
        from py2fastrust.native_diagnostics import kind_name
        self.assertEqual(kind_name(kind),"function")
