"""Lexical cells preserve capture identity, defaults, nonlocal effects and errors."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames

CASES={
 'fresh_counter_environments':('def make_counter(start):\n value=start\n def step(delta):\n  nonlocal value\n  value+=delta\n  return value\n return step\nfirst=make_counter(3)\nsecond=make_counter(20)\nprint(first(1),second(3),first(2),second(-5))\n',('',)),
 'sibling_functions_share_nonlocal':('def make():\n total=0\n def add(value):\n  nonlocal total\n  total+=value\n  return total\n def read():return total\n return add,read\nadd,read=make()\nprint(read(),add(4),read(),add(-1),read())\n',('',)),
 'returned_capture_keeps_list_alias':('def maker(items):\n def append(value):\n  items.append(value)\n  return items\n return append\nvalues=[1]\nappend=maker(values)\nprint(append(2),values)\nvalues.append(3)\nprint(append(4),values,append(5) is values)\n',('',)),
 'nonlocal_unbound_capture':('def outer(flag):\n if flag:value=4\n def get():return value\n return get()\nprint(outer(int(input())))\n',('0\n', '1\n')),
 'nonlocal_deletion_shared_state':('def maker():\n value=3\n def read():return value\n def erase():\n  nonlocal value\n  del value\n return read,erase\nread,erase=maker()\nprint(read())\nerase()\nprint(read())\n',('',)),
 'defaults_belong_to_closure_instance':('def create(start):\n def take(value=start):return value\n return take\nfirst=create(3)\nsecond=create(9)\nprint(first(),second(),first(5),second())\n',('',)),
 'late_outer_value_is_shared':('def create():\n value=1\n def read():return value\n value=7\n return read\nprint(create()())\n',('',)),
 'recursive_query_has_fresh_accumulator':('def total(limit):\n answer=0\n def visit(value):\n  nonlocal answer\n  if value==0:return\n  answer+=value\n  visit(value-1)\n visit(limit)\n return answer\nprint(total(3),total(0),total(5),total(2))\n',('',)),
 'captured_finite_type_rebinding':("def choose(flag):\n value=1\n def get():return value\n if flag:value='changed'\n else:value=None\n return get()\nprint(choose(int(input())))\n",('0\n', '1\n')),
 'same_spelling_different_lexical_owners':('def first(value):\n def helper(delta):return value+delta\n return helper\ndef second(value):\n def helper(delta):return value*delta\n return helper\nadd=first(7)\nmultiply=second(5)\nprint(add(3),multiply(3),add(2),multiply(2))\n',('',)),
 'closure_identity_per_factory_call':('def maker():\n def value():return 1\n return value\nfirst=maker()\nsame=first\nsecond=maker()\nprint(first is same,first is second,first==same,first==second)\n',('',)),
 'mutable_defaults_per_closure_instance':('def create():\n def append(value,items=[]):\n  items.append(value)\n  return items\n return append\nfirst=create()\nsecond=create()\nprint(first(1),first(2),second(9))\nprint(first(3),second(8))\n',('',)),
 'nonlocal_augmented_reentrant_rhs':('def create():\n value=2\n def change():\n  nonlocal value\n  value=10\n  return 3\n def step():\n  nonlocal value\n  value+=change()\n  return value\n return step\nstep=create()\nprint(step(),step())\n',('',)),
 'captured_list_rebinding_keeps_old_alias':('def create():\n values=[1]\n def replace():\n  nonlocal values\n  old=values\n  values=[9]\n  old.append(2)\n  return old\n def read():return values\n return replace,read\nreplace,read=create()\nprint(replace(),read(),replace(),read())\n',('',)),
 'closure_composition_captures_callable':('def adder(delta):\n def add(value):return value+delta\n return add\ndef wrap(callback):\n def call(value):return callback(value)+1\n return call\nfirst=wrap(adder(3))\nsecond=wrap(adder(10))\nprint(first(2),second(2),first(5))\n',('',)),
 'conditional_nested_definition_unbound':('def create(flag):\n if flag:\n  def value():return 7\n return value\ncreated=create(int(input()))\nprint(created())\n',('0\n', '1\n')),
 'nested_signature_error_after_argument_effects':("def create():\n def target(value,*,other=2):return value+other\n return target\ndef mark(value):\n print('argument',value)\n return value\ncalled=create()\nprint(called(mark(1),mark(2)))\n",('',)),
}

REFERENCE="""import json,sys
try:exec(compile(sys.argv[1],sys.argv[2],'exec'),{'__name__':'__main__'})
except BaseException as error:
 frames=[];trace=error.__traceback__
 while trace is not None:
  if trace.tb_frame.f_code.co_filename==sys.argv[2]:frames.append((str(trace.tb_lineno),trace.tb_frame.f_code.co_name))
  trace=trace.tb_next
 print(json.dumps({'message':type(error).__name__+': '+str(error),'frames':frames}),file=sys.stderr);sys.exit(1)
"""


class LexicalClosureSelectionTests(unittest.TestCase):
    def test_nested_plans_are_selected_before_any_emitter_attempt(self):
        for source,inputs in CASES.values():
            unit=build_program(source,'lexical_closures.py').main
            selection=select_frames(unit)
            self.assertTrue(selection.required)
            self.assertIn('lexical closure environments',selection.reasons)


    def test_unentered_lexical_scope_preserves_ordinary_module_fastpath(self):
        source="from math import gcd\ndef unused(value):\n def add(other):return value+other\n return add\nprint(gcd(12,8))\n"
        unit=build_program(source,'unused_lexical.py').main
        self.assertFalse(select_frames(unit).required)
        for integer in('i64','i128','bigint'):
            with patch('py2fastrust.native_classes.try_generate_classes',side_effect=AssertionError('unnecessary lexical frame path')),patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                result=transpile(source,TranspileOptions(integer=integer,filename=unit.filename))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class LexicalClosureExecutionTests(unittest.TestCase):
    def test_unentered_nested_default_has_no_evaluation_or_storage(self):
        source="def unused(value):\n def inner(other=int(input())):return value+other\n return inner\ndef count(value):\n if value:return 1+count(value-1)\n return 0\nprint(count(3))\n"
        self.compare(source,('',),require_environment=False)

    def compare(self,source,inputs,*,require_environment=True):
        filename='lexical_closures.py'
        expected=[]
        for data in inputs:
            cp=subprocess.run([sys.executable,'-I','-S','-c',REFERENCE,source,filename],input=data,capture_output=True,text=True,timeout=10)
            expected.append((cp.returncode,cp.stdout,json.loads(cp.stderr)if cp.returncode else None))
        with tempfile.TemporaryDirectory(prefix='pytors-lexical-')as directory:
            for integer in('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=integer,filename=filename))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                if require_environment:self.assertIn('ClassLexicalEnvironment',result.rust_source)
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in('enum Value','enum Op','struct Runtime','struct PegParser'):self.assertNotIn(marker,result.rust_source)
                rust=Path(directory)/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in(False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(integer=integer,optimized=optimized,input=data):
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                            self.assertEqual((actual.returncode,actual.stdout),reference[:2],actual.stderr)
                            if reference[2] is None:self.assertEqual(actual.stderr,'')
                            else:
                                self.assertEqual(actual.stderr.splitlines()[-1],reference[2]['message'])
                                self.assertEqual(re.findall(r'File ".*?", line (\d+), in ([^\n]+)',actual.stderr),[tuple(item)for item in reference[2]['frames']])


def _case(name):
    def test(self):self.compare(*CASES[name])
    return test

for _name in CASES:setattr(LexicalClosureExecutionTests,'test_'+_name,_case(_name))


if __name__=='__main__':unittest.main()
