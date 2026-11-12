"""Real source state witnesses preserve lookup, mutation and cleanup semantics."""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from py2fastrust import transpile, TranspileOptions
from py2fastrust import native_source_state as state

SOURCES = {'integer': 'class Session:\n'
            '    stack = []\n'
            '    def __init__(self, base):\n'
            '        self.base = base\n'
            '    def __enter__(self):\n'
            '        self.stack.append(self.base)\n'
            '    def __exit__(self, kind, value, trace):\n'
            '        self.stack.pop()\n'
            '    @classmethod\n'
            '    def current(cls):\n'
            '        return cls.stack[-1]\n'
            '\n'
            'def pair():\n'
            '    return Session.current() + Session.current()\n'
            '\n'
            'class Parcel:\n'
            '    def __init__(self, value=0):\n'
            '        self.rule = Session.current()\n'
            '        self.value = value + self.rule + pair()\n'
            'with Session(int(input())):\n'
            '    left = Parcel(5)\n'
            '    right = Parcel(9)\n'
            '    print(left.rule, left.value, right.value)\n',
 'boolean': 'class Flags:\n'
            '    values = []\n'
            '    def __init__(self, enabled):\n'
            '        self.enabled = enabled\n'
            '    def __enter__(self):\n'
            '        self.values.append(self.enabled)\n'
            '    def __exit__(self, kind, value, trace):\n'
            '        self.values.pop()\n'
            '    @classmethod\n'
            '    def current(cls):\n'
            '        return cls.values[-1]\n'
            'def read_twice():\n'
            '    first = Flags.current()\n'
            '    second = Flags.current()\n'
            '    return first == second\n'
            "with Flags(input() == 'yes'):\n"
            '    print(Flags.current(), read_twice())\n',
 'local_augassign': 'class Stack:\n'
                    '    items = []\n'
                    '    def __init__(self, value):\n'
                    '        self.value = value\n'
                    '    def __enter__(self):\n'
                    '        self.items.append(self.value)\n'
                    '    def __exit__(self, kind, value, trace):\n'
                    '        self.items.pop()\n'
                    '    @classmethod\n'
                    '    def current(cls):\n'
                    '        return cls.items[-1]\n'
                    'def mutate(items):\n'
                    '    items *= 0\n'
                    'with Stack(13):\n'
                    '    mutate(Stack.items)\n'
                    '    print(Stack.items[-1])\n',
 'while_header': 'class Stack:\n'
                 '    items = []\n'
                 '    def __init__(self, value):\n'
                 '        self.value = value\n'
                 '    def __enter__(self):\n'
                 '        self.items.append(self.value)\n'
                 '    def __exit__(self, kind, value, trace):\n'
                 '        self.items.pop()\n'
                 '    @classmethod\n'
                 '    def current(cls):\n'
                 '        return cls.items[-1]\n'
                 'with Stack(13):\n'
                 '    while Stack.items[-1]:\n'
                 '        Stack.items.pop()\n',
 'comprehension': 'class Stack:\n'
                  '    items = []\n'
                  '    def __init__(self, value):\n'
                  '        self.value = value\n'
                  '    def __enter__(self):\n'
                  '        self.items.append(self.value)\n'
                  '    def __exit__(self, kind, value, trace):\n'
                  '        self.items.pop()\n'
                  '    @classmethod\n'
                  '    def current(cls):\n'
                  '        return cls.items[-1]\n'
                  'def clear_stack():\n'
                  '    Stack.items.clear()\n'
                  "    print('iterable')\n"
                  '    return 1\n'
                  'with Stack(13):\n'
                  '    values = [Stack.items[-1] for _ in [clear_stack()]]\n'
                  '    print(values)\n',
 'finite_native': 'import heapq\n'
                  'class Stack:\n'
                  '    items = []\n'
                  '    def __init__(self, value):\n'
                  '        self.value = value\n'
                  '    def __enter__(self):\n'
                  '        self.items.append(self.value)\n'
                  '    def __exit__(self, kind, value, trace):\n'
                  '        self.items.pop()\n'
                  '    @classmethod\n'
                  '    def current(cls):\n'
                  '        return cls.items[-1]\n'
                  'def unchanged(items, value):\n'
                  '    return Stack.current()\n'
                  'with Stack(13):\n'
                  '    operation = unchanged if int(input()) else heapq.heapreplace\n'
                  '    print(operation(Stack.items, 31))\n'
                  '    print(Stack.current())\n',
 'receiver_effect': 'class Stack:\n'
                    '    items = []\n'
                    '    def __init__(self, value):\n'
                    '        self.value = value\n'
                    '    def __enter__(self):\n'
                    '        self.items.append(self.value)\n'
                    '    def __exit__(self, kind, value, trace):\n'
                    '        self.items.pop()\n'
                    '    @classmethod\n'
                    '    def current(cls):\n'
                    '        return cls.items[-1]\n'
                    'def get_owner():\n'
                    "    print('receiver')\n"
                    '    return Stack\n'
                    'with Stack(13):\n'
                    '    print(get_owner().items[-1])\n',
 'unbound_owner': 'class Stack:\n'
                  '    items = []\n'
                  '    def __init__(self, value):\n'
                  '        self.value = value\n'
                  '    def __enter__(self):\n'
                  '        self.items.append(self.value)\n'
                  '    def __exit__(self, kind, value, trace):\n'
                  '        self.items.pop()\n'
                  '    @classmethod\n'
                  '    def current(cls):\n'
                  '        return cls.items[-1]\n'
                  'def run(enabled):\n'
                  '    if enabled:\n'
                  '        owner = Stack\n'
                  '    with Stack(13):\n'
                  '        print(owner.items[-1])\n'
                  'run(int(input()))\n',
 'unpack': 'class Stack:\n'
           '    items = []\n'
           '    def __init__(self, value):\n'
           '        self.value = value\n'
           '    def __enter__(self):\n'
           '        self.items.append(self.value)\n'
           '    def __exit__(self, kind, value, trace):\n'
           '        self.items.pop()\n'
           '    @classmethod\n'
           '    def current(cls):\n'
           '        return cls.items[-1]\n'
           '\n'
           'def clear_stack(value):\n'
           '    Stack.items.clear()\n'
           "    print('consume', value)\n"
           '    return 0\n'
           'iterator = map(clear_stack, [1, 2])\n'
           'destination = [0] * 14\n'
           'with Stack(13):\n'
           '    first, destination[Stack.items[-1]] = iterator\n'
           "    print('after targets')\n"}


def convert(source, integer='i64', *, enabled=True, filename='source_state.py'):
    models=[];reads=[];exports=[]
    original_prepare=state.prepare
    original_read=state.total_read
    original_export=state.append_export
    def prepare(model):
        if enabled:original_prepare(model)
        else:model.source_state=None
        models.append(model)
    def read(emitter,node):
        result=original_read(emitter,node)
        if result is not None:reads.append((node,result))
        return result
    def export(emitter,node,method,bound):
        result=original_export(emitter,node,method,bound)
        if result:exports.append((node,result))
        return result
    with mock.patch.object(state,'prepare',side_effect=prepare),mock.patch.object(state,'total_read',side_effect=read),mock.patch.object(state,'append_export',side_effect=export),mock.patch('py2fastrust.codegen.generate',side_effect=AssertionError('general codegen entered')):
        result=transpile(source,TranspileOptions(filename=filename,integer=integer,license='none'))
    return result,models[-1]if models else None,reads,exports


class NativeSourceStateProofTests(unittest.TestCase):
    def test_runtime_integer_append_helper_and_constructor_select_real_entries(self):
        for integer in ('i64','i128','bigint'):
            with self.subTest(integer=integer):
                result,model,reads,exports=convert(SOURCES['integer'],integer)
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertIsNotNone(model)
                registry=model.source_state
                self.assertIsNone(registry.barrier)
                if integer=='bigint':
                    self.assertFalse(registry.bridges)
                    self.assertFalse(reads)
                    continue
                self.assertEqual(len(registry.producers),1)
                self.assertEqual(len(registry.bridges),1)
                self.assertEqual(len(exports),1)
                self.assertTrue(reads)
                self.assertTrue(any(abi.plan.scope=='__init__'for abi in registry.abis.values()))
                self.assertIn('fn class_state_construct_',result.rust_source)
                self.assertIn('fn class_state_enter_',result.rust_source)
                for node,value in reads:
                    self.assertIsInstance(node,ast.Subscript)
                    self.assertRegex(value.code,r'^class_state_value_\d+$')
                    self.assertNotIn('class_slice_get(',value.code)
                    self.assertNotIn('.last()',value.code)

    def test_boolean_witness_is_selected_in_every_integer_mode(self):
        for integer in ('i64','i128','bigint'):
            with self.subTest(integer=integer):
                result,model,reads,exports=convert(SOURCES['boolean'],integer)
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(len(model.source_state.producers),1)
                self.assertEqual(len(model.source_state.bridges),1)
                self.assertEqual(len(exports),1)
                self.assertTrue(reads)
                self.assertTrue(all(value.kind=='bool'for _,value in reads))

    def test_mutation_repeated_tests_comprehensions_and_unpack_keep_checked_paths(self):
        for name in ('local_augassign','while_header','comprehension','unpack'):
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result,model,reads,exports=convert(SOURCES[name],integer)
                    baseline,_,_,_=convert(SOURCES[name],integer,enabled=False)
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertTrue(baseline.success,baseline.diagnostics)
                    self.assertFalse(reads)
                    self.assertFalse(exports)
                    # An independent single-publication metadata proof can
                    # change constructors even when no context witness is
                    # transported. Check the actual rejected capability.
                    self.assertFalse(model.source_state.bridges)
                    self.assertNotIn('fn class_state_function_',result.rust_source)
                    self.assertNotIn('fn class_state_enter_',result.rust_source)
                    self.assertNotIn('fn class_state_construct_',result.rust_source)

    def test_all_finite_callable_roles_invalidate_postcall_facts(self):
        result,model,_,_=convert(SOURCES['finite_native'])
        self.assertTrue(result.success,result.diagnostics)
        registry=model.source_state
        operation=next(node for node in registry.nodes.values()if isinstance(node,ast.Call)
                       and isinstance(node.func,ast.Name)and node.func.id=='operation')
        self.assertEqual(registry.local_effect(model.module,operation),set(registry.slots))
        following=max((node for node in registry.nodes.values()if isinstance(node,ast.Call)
                       and isinstance(node.func,ast.Attribute)and node.func.attr=='current'),key=lambda node:node.lineno)
        for key,mode in registry.modes.items():
            if key[0]=='with':self.assertNotIn(id(following),mode.calls)

    def test_generated_private_entries_do_not_add_owned_scope_transport(self):
        for name in ('integer','boolean'):
            result,_,_,_=convert(SOURCES[name])
            self.assertTrue(result.success,result.diagnostics)
            headers=re.findall(r'fn (class_state_(?:function|enter|construct)_\d+)\(class_scope:(&?ClassScope)',result.rust_source)
            self.assertTrue(headers)
            self.assertTrue(all(kind=='&ClassScope'for _,kind in headers),headers)
            for symbol,_ in headers:
                self.assertNotIn(symbol+'(class_scope.clone()',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeSourceStateExecutionTests(unittest.TestCase):
    def exercise(self,name,inputs):
        source=SOURCES[name]
        with tempfile.TemporaryDirectory(prefix='pytors-state-witness-')as temporary:
            directory=Path(temporary);main=directory/'main.py';main.write_text(source)
            expected=[subprocess.run([sys.executable,'-I','-S',str(main)],input=data,text=True,capture_output=True,timeout=15)for data in inputs]
            for integer in ('i64','i128','bigint'):
                result,_,_,_=convert(source,integer,filename=str(main))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','fn step('):self.assertNotIn(marker,result.rust_source)
                rust=directory/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=directory/(integer+('.opt'if optimized else'.debug'))
                    built=subprocess.run(['rustc','--edition=2021','--crate-name','state_witness_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(name=name,integer=integer,optimized=optimized,data=data):
                            actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=15,env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
                            self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
                            frames=lambda text:re.findall('File "([^"]+)", line (\\d+), in ([^\\n]+)',text)
                            self.assertEqual(frames(actual.stderr),frames(reference.stderr))
                            self.assertEqual(actual.stderr.rstrip().splitlines()[-1:],reference.stderr.rstrip().splitlines()[-1:])

    def test_runtime_integer_constructor_and_repeated_helper_reads(self):
        self.exercise('integer',('7\n', '13\n'))

    def test_runtime_boolean_values(self):
        self.exercise('boolean',('yes\n', 'no\n'))

    def test_effectful_receiver_is_evaluated_once(self):
        self.exercise('receiver_effect',('',))

    def test_unbound_owner_load_still_raises(self):
        self.exercise('unbound_owner',('0\n', '1\n'))

    def test_mutation_loop_and_unpack_errors_preserve_cleanup(self):
        for name in ('local_augassign','while_header','unpack'):
            self.exercise(name,('',))
