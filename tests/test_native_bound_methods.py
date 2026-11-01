"""Bound methods share compiled signatures and preserve receiver/object lifetime."""
import ast
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.native_classes import Model,InstanceType
from py2fastrust.native_types import immutable,reference_cloneable


CASES={'argument_and_container_aliases': 'class Counter:\n'
                                   ' def __init__(self,value):self.value=value\n'
                                   ' def add(self,amount):\n'
                                   '  self.value+=amount\n'
                                   '  return self.value\n'
                                   'def invoke(callback,value):return callback(value)\n'
                                   'item=Counter(1)\n'
                                   'method=item.add\n'
                                   'pair=(method,[method,method])\n'
                                   'print(pair[0] is '
                                   'pair[1][0],invoke(pair[1][1],2),pair[0](4),item.value)\n',
 'bound_alias_recursive_calls': 'class Counter:\n'
                                ' def total(self,count):\n'
                                '  if count==0:return 0\n'
                                '  return saved(count-1)+count\n'
                                'item=Counter()\n'
                                'saved=item.total\n'
                                'print(saved(6))\n',
 'bound_method_type_error_uses_method_name': 'class Counter:\n'
                                             ' def value(self):return 3\n'
                                             'item=Counter()\n'
                                             "print('before')\n"
                                             'abs(item.value)\n',
 'callee_is_captured_before_argument_rebinding': 'class Counter:\n'
                                                 ' def __init__(self,value):self.value=value\n'
                                                 ' def add(self,amount):\n'
                                                 '  self.value+=amount\n'
                                                 '  return self.value\n'
                                                 'first=Counter(1)\n'
                                                 'second=Counter(10)\n'
                                                 'selected=first.add\n'
                                                 'def switch():\n'
                                                 ' global selected\n'
                                                 ' selected=second.add\n'
                                                 ' return 2\n'
                                                 'print(selected(switch()),selected(3),first.value,second.value)\n',
 'comprehension_reads_make_fresh_method_objects': 'class Counter:\n'
                                                  ' def __init__(self,value):self.value=value\n'
                                                  ' def add(self,amount):return self.value+amount\n'
                                                  'item=Counter(3)\n'
                                                  'callbacks=[item.add for _ in range(2)]\n'
                                                  'print(callbacks[0]is '
                                                  'callbacks[1],callbacks[0]==callbacks[1],callbacks[0](4),callbacks[1](5))\n',
 'different_receiver_classes_and_mixed_callable_kinds': 'class First:\n'
                                                        ' def add(self,value):return value+3\n'
                                                        'class Second:\n'
                                                        ' def add(self,value):return value*3\n'
                                                        'first=First()\n'
                                                        'second=Second()\n'
                                                        'callbacks=[first.add,second.add,lambda '
                                                        'value:value*2,abs]\n'
                                                        'for callback in '
                                                        'callbacks:print(callback(-4))\n'
                                                        'print(first.add==second.add,first.add is '
                                                        'second.add)\n',
 'direct_self_saved_cycle': 'class Counter:\n'
                            ' def value(self):return 3\n'
                            ' def remember(self):self.saved=self.value\n'
                            'item=Counter()\n'
                            'item.remember()\n'
                            'print(item.saved())\n',
 'duplicate_receiver_keyword': 'class Counter:\n'
                               ' def value(self,first):return first\n'
                               'item=Counter()\n'
                               'callback=item.value\n'
                               'callback(3,self=item)\n',
 'enumerated_bound_filter_observes_each_callback_effect': 'class Counter:\n'
                                                          ' def __init__(self):self.value=0\n'
                                                          ' def accept(self,value):\n'
                                                          '  self.value+=value\n'
                                                          '  return True\n'
                                                          'item=Counter()\n'
                                                          'stream=filter(item.accept,[1,2,3])\n'
                                                          'for index,value in '
                                                          'enumerate(stream):print(index,value,item.value)\n',
 'excess_arguments_preserve_effect_order': 'class Counter:\n'
                                           ' def value(self,first):return first\n'
                                           'item=Counter()\n'
                                           'callback=item.value\n'
                                           'def mark(value):\n'
                                           " print('arg',value)\n"
                                           ' return value\n'
                                           'callback(mark(1),mark(2))\n',
 'filter_bound_predicate_without_cycle': 'class Predicate:\n'
                                         ' def __init__(self,limit):self.limit=limit\n'
                                         ' def accept(self,value):return value>self.limit\n'
                                         'class Holder:\n'
                                         ' def '
                                         '__init__(self,callback):self.stream=filter(callback,[1,4,2,5])\n'
                                         'item=Predicate(2)\n'
                                         'holder=Holder(item.accept)\n'
                                         'item.limit=3\n'
                                         'print(list(holder.stream))\n',
 'finite_function_and_method_alternatives': 'class Counter:\n'
                                            ' def __init__(self,value):self.value=value\n'
                                            ' def add(self,amount):return self.value+amount\n'
                                            'def plain(amount):return amount*2\n'
                                            'item=Counter(3)\n'
                                            'callbacks=[item.add,plain]\n'
                                            'for callback in callbacks:print(callback(4))\n'
                                            'print(callbacks[0]==callbacks[1],callbacks[0]is '
                                            'callbacks[1])\n',
 'fresh_method_reads_in_a_loop': 'class Counter:\n'
                                 ' def add(self,amount):return amount+1\n'
                                 'item=Counter()\n'
                                 'first=item.add\n'
                                 'for _ in range(3):\n'
                                 ' current=item.add\n'
                                 ' print(current is first,current==first,current(2))\n',
 'identity_equality_and_mutable_receiver': 'class Counter:\n'
                                           ' def __init__(self,value):self.value=value\n'
                                           ' def add(self,amount):\n'
                                           '  self.value+=amount\n'
                                           '  return self.value\n'
                                           ' def read(self):return self.value\n'
                                           'first=Counter(1)\n'
                                           'other=Counter(1)\n'
                                           'a=first.add\n'
                                           'b=first.add\n'
                                           'alias=a\n'
                                           'print(a is b,a==b,a is '
                                           'alias,a==alias,a==other.add,a==first.read)\n'
                                           'print(a(2),b(3),first.read())\n',
 'iterator_bound_receiver_cycle': 'class Holder:\n'
                                  ' def accept(self,value):return value>0\n'
                                  ' def initialize(self):self.stream=filter(self.accept,[1,2])\n'
                                  'item=Holder()\n'
                                  'item.initialize()\n'
                                  'print(list(item.stream))\n',
 'lambda_escaping_bound_method': 'class Counter:\n'
                                 ' def __init__(self,value):self.value=value\n'
                                 ' def add(self,amount):return self.value+amount\n'
                                 'def make():\n'
                                 ' item=Counter(7)\n'
                                 ' return lambda:item.add\n'
                                 'factory=make()\n'
                                 'first=factory()\n'
                                 'second=factory()\n'
                                 'print(first(2),first is second,first==second)\n',
 'list_bound_receiver_cycle': 'class Counter:\n'
                              ' def value(self):return 3\n'
                              ' def remember(self):self.callbacks=[self.value]\n'
                              'item=Counter()\n'
                              'item.remember()\n'
                              'print(item.callbacks[0]())\n',
 'method_returns_its_mutable_receiver': 'class Counter:\n'
                                        ' def __init__(self,value):self.value=value\n'
                                        ' def myself(self):return self\n'
                                        'item=Counter(3)\n'
                                        'callback=item.myself\n'
                                        'alias=callback()\n'
                                        'alias.value=8\n'
                                        'print(alias is item,item.value)\n',
 'method_text_state_and_none_result': 'class Text:\n'
                                      " def __init__(self):self.value='a'\n"
                                      ' def append(self,suffix):self.value+=suffix\n'
                                      'item=Text()\n'
                                      'callback=item.append\n'
                                      "print(callback('b'),item.value)\n"
                                      "print(callback('cd'),item.value)\n",
 'missing_argument_evaluates_keywords_first': 'class Counter:\n'
                                              ' def combine(self,first,second):return '
                                              'first+second\n'
                                              'item=Counter()\n'
                                              'callback=item.combine\n'
                                              'def mark(value):\n'
                                              " print('arg',value)\n"
                                              ' return value\n'
                                              'callback(second=mark(4))\n',
 'mutable_method_default_is_shared': 'class Counter:\n'
                                     ' def __init__(self,value):self.value=value\n'
                                     ' def collect(self,values=[]):\n'
                                     '  values.append(self.value)\n'
                                     '  return values\n'
                                     'first=Counter(2)\n'
                                     'second=Counter(5)\n'
                                     'a=first.collect\n'
                                     'b=second.collect\n'
                                     'print(a(),b(),a(),a is first.collect,a==first.collect)\n',
 'private_method_return_and_builtin_named_alias': 'class Counter:\n'
                                                  ' def __init__(self,value):self.value=value\n'
                                                  ' def __hidden(self,amount):return '
                                                  'self.value+amount\n'
                                                  ' def capture(self):return self.__hidden\n'
                                                  'item=Counter(7)\n'
                                                  'int=item.capture()\n'
                                                  'print(int(2),int==item.capture(),int is '
                                                  'item.capture())\n',
 'receiver_expression_is_evaluated_once': 'class Counter:\n'
                                          ' def __init__(self,value):self.value=value\n'
                                          ' def add(self,amount):return self.value+amount\n'
                                          'items=[Counter(1),Counter(10)]\n'
                                          'callback=items.pop().add\n'
                                          'print(callback(2),len(items),items[0].value)\n',
 'returned_method_retains_receiver': 'class Counter:\n'
                                     ' def __init__(self,value):self.value=value\n'
                                     ' def add(self,amount=1):\n'
                                     '  self.value+=amount\n'
                                     '  return self.value\n'
                                     'def make():return Counter(4).add\n'
                                     'method=make()\n'
                                     'print(method(),method(3),method())\n',
 'separate_holder_keeps_shared_receiver': 'class Counter:\n'
                                          ' def __init__(self,value):self.value=value\n'
                                          ' def add(self,amount):\n'
                                          '  self.value+=amount\n'
                                          '  return self.value\n'
                                          'class Holder:\n'
                                          ' def __init__(self,callback):self.callback=callback\n'
                                          'item=Counter(2)\n'
                                          'holder=Holder(item.add)\n'
                                          'print(holder.callback(3),holder.callback is '
                                          'holder.callback,holder.callback==item.add,item.value)\n',
 'signature_defaults_and_keywords': 'class Counter:\n'
                                    ' def __init__(self,value):self.value=value\n'
                                    ' def add(self,amount=2,/,*,scale=3):return '
                                    'self.value+amount*scale\n'
                                    'item=Counter(4)\n'
                                    'callback=item.add\n'
                                    'print(callback(),callback(5),callback(5,scale=2))\n'}

CYCLES=('direct_self_saved_cycle', 'iterator_bound_receiver_cycle', 'list_bound_receiver_cycle')

MODULES={'counter_module.py': 'BASE=10\n'
                      'class Counter:\n'
                      ' def __init__(self,value):self.value=value\n'
                      ' def add(self,amount=BASE):return self.value+amount+BASE\n'
                      'def change_base():\n'
                      ' global BASE\n'
                      ' BASE=20\n',
 'main.py': 'from counter_module import Counter,change_base\n'
            'BASE=1000\n'
            'item=Counter(3)\n'
            'method=item.add\n'
            'print(method(),method(2))\n'
            'change_base()\n'
            'print(method(),method(2),method==item.add,method is item.add)\n'}

def frames(text):return re.findall(r'File "[^\"]+", line (\d+), in ([^\n]+)',text)

def final_error(text):
    line=text.rstrip().splitlines()[-1]if text.strip()else''
    return re.sub(r"\. Did you mean: .*$",'',line)


class BoundMethodMetadataTests(unittest.TestCase):
    def test_original_method_nodes_signatures_and_mutable_reference_capability(self):
        source=CASES['identity_equality_and_mutable_receiver']
        unit=build_program(source,'methods.py').main
        before=ast.dump(unit.tree,include_attributes=True)
        model=Model(unit.tree,unit.filename,'i64',unit.native_imports,unit=unit).run()
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),before)
        self.assertTrue(model.callable_cells.bound_methods.used)
        for target in model.callable_cells.bound_methods.used:
            plan=model.callable_cells.plans[target.definition]
            self.assertEqual(unit.ordinal(plan.node),target.definition)
            self.assertIs(plan.signature,unit.signature_for(plan.node))
            from py2fastrust.native_aot_callables import AotFunctionType
            kind=AotFunctionType.from_targets((target,))
            self.assertTrue(reference_cloneable(kind))
            self.assertFalse(immutable(kind))
            self.assertEqual(kind._native_owned_kinds,(InstanceType(target.owner),))

    def test_bound_method_metadata_has_a_precise_required_boundary(self):
        for expression in ('callback.__self__','callback.__func__','callback.__call__(2)'):
            source='class Counter:\n def add(self,value):return value+1\nitem=Counter()\ncallback=item.add\nprint('+expression+')\n'
            for mode in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=mode,filename='metadata.py'))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].line,5)
                self.assertRegex(str(result.diagnostics),'bound-method attribute.*metadata lookup')
                self.assertNotIn('bound-method carrier',str(result.diagnostics))

    def test_real_receiver_ownership_cycles_remain_a_collector_boundary(self):
        for name in CYCLES:
            for mode in ('i64','i128','bigint'):
                result=transpile(CASES[name],TranspileOptions(integer=mode,filename='methods.py'))
                self.assertFalse(result.success,name)
                self.assertRegex(str(result.diagnostics),'reference cycle')
                self.assertRegex(str(result.diagnostics),'collector|collection')
                self.assertNotIn('bound-method carrier',str(result.diagnostics))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class BoundMethodExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-bound-methods-')
        cls.cache={}

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def compare_run(self,binary,reference,**details):
        actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
        with self.subTest(**details):
            self.assertEqual((actual.returncode,actual.stdout),(reference.returncode,reference.stdout),actual.stderr)
            self.assertEqual(frames(actual.stderr),frames(reference.stderr))
            self.assertEqual(final_error(actual.stderr),final_error(reference.stderr))

    def check(self,name,*,prune=True):
        source=CASES[name]
        reference=subprocess.run([sys.executable,'-I','-S','-c',source],text=True,capture_output=True,timeout=10)
        for mode in ('i64','i128','bigint'):
            with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend')):
                result=transpile(source,TranspileOptions(integer=mode,filename='methods.py',optimize=prune))
            self.assertTrue(result.success,result.diagnostics)
            for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                self.assertNotIn(marker,result.rust_source)
            for optimized in (False,True):
                key=source,mode,optimized,prune
                if key not in self.cache:
                    rust=Path(self.directory.name,hashlib.sha256(repr(key).encode()).hexdigest()+'.rs');rust.write_text(result.rust_source)
                    binary=rust.with_suffix('')
                    build=subprocess.run(['rustc','--edition=2021','--crate-name','methods',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    self.cache[key]=binary
                self.compare_run(self.cache[key],reference,name=name,mode=mode,optimized=optimized,prune=prune)

    def test_fresh_method_identity_equality_and_receiver_mutation(self):
        self.check('identity_equality_and_mutable_receiver')

    def test_returned_argument_and_container_method_references(self):
        for name in ('returned_method_retains_receiver','argument_and_container_aliases','separate_holder_keeps_shared_receiver'):
            with self.subTest(name=name):self.check(name)

    def test_original_signature_and_shared_definition_defaults(self):
        for name in ('signature_defaults_and_keywords','mutable_method_default_is_shared'):
            with self.subTest(name=name):self.check(name)

    def test_callee_capture_precedes_argument_rebinding_and_receiver_read_is_once(self):
        for name in ('callee_is_captured_before_argument_rebinding','receiver_expression_is_evaluated_once'):
            with self.subTest(name=name):self.check(name)

    def test_bound_and_plain_function_targets_and_recursive_alias_calls(self):
        for name in ('finite_function_and_method_alternatives','bound_alias_recursive_calls'):
            with self.subTest(name=name):self.check(name)

    def test_binding_errors_keep_implicit_receiver_count_and_argument_effects(self):
        for name in ('missing_argument_evaluates_keywords_first','excess_arguments_preserve_effect_order','duplicate_receiver_keyword'):
            with self.subTest(name=name):self.check(name)

    def test_lazy_filter_uses_the_same_captured_bound_call(self):self.check('filter_bound_predicate_without_cycle')

    def test_lambda_factory_and_repeated_comprehension_and_loop_reads(self):
        for name in ('lambda_escaping_bound_method','comprehension_reads_make_fresh_method_objects','fresh_method_reads_in_a_loop'):
            with self.subTest(name=name):self.check(name)

    def test_private_method_returned_to_a_builtin_spelled_binding(self):self.check('private_method_return_and_builtin_named_alias')

    def test_no_optimize_preserves_fresh_bound_reference_identity(self):self.check('identity_equality_and_mutable_receiver',prune=False)

    def test_defining_module_context_and_definition_time_defaults(self):
        with tempfile.TemporaryDirectory(prefix='pytors-method-modules-')as directory:
            directory=Path(directory)
            for name,source in MODULES.items():(directory/name).write_text(source)
            main=directory/'main.py'
            driver='import sys,runpy;sys.path.insert(0,'+repr(str(directory))+');runpy.run_path('+repr(str(main))+',run_name="__main__")'
            reference=subprocess.run([sys.executable,'-I','-S','-c',driver],text=True,capture_output=True,timeout=10)
            self.assertEqual(reference.returncode,0,reference.stderr)
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM backend')):
                    result=transpile(MODULES['main.py'],TranspileOptions(integer=mode,filename=str(main),module_paths=(directory,)))
                self.assertTrue(result.success,result.diagnostics)
                rust=directory/(mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    build=subprocess.run(['rustc','--edition=2021','--crate-name','method_modules',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    self.compare_run(binary,reference,mode=mode,optimized=optimized,module=True)

    def test_bound_calls_return_shared_instances_text_and_none(self):
        for name in ('method_returns_its_mutable_receiver','method_text_state_and_none_result'):
            with self.subTest(name=name):self.check(name)

    def test_mixed_method_classes_lambda_and_builtin_share_one_carrier(self):self.check('different_receiver_classes_and_mixed_callable_kinds')

    def test_bound_method_type_error_has_the_python_method_type_name(self):self.check('bound_method_type_error_uses_method_name')

    def test_enumerated_bound_filter_observes_each_deferred_callback_effect(self):self.check('enumerated_bound_filter_observes_each_callback_effect')


if __name__=='__main__':unittest.main()
