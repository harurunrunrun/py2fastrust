"""Typed source invocation producers own class receivers across suspension."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust import native_typed_continuations as continuations
from py2fastrust.native_class_calls import entry_result,synchronous
from py2fastrust.native_classes import InstanceType
from test_native_typed_continuations import frames

SOURCES={'argument_mutates_retained_receiver': ['class Counter:\n'
                                        ' def __init__(self):self.value=0\n'
                                        ' def walk(self,n):\n'
                                        '  if n:return self.walk(mark(self,n-1))+1\n'
                                        '  return self.value\n'
                                        'def mark(counter,n):\n'
                                        ' counter.value+=3\n'
                                        ' print("argument",n,counter.value)\n'
                                        ' return n\n'
                                        'counter=Counter()\n'
                                        'print(counter.walk(3),counter.value)\n',
                                        ['']],
 'bound_method_iterator_callback': ['class Number:\n'
                                    ' def __init__(self,value):self.value=value\n'
                                    ' def count(self,n):\n'
                                    '  if n:return self.count(n-1)+1\n'
                                    '  return self.value\n'
                                    'number=Number(4)\n'
                                    'print(list(map(number.count,[0,2,5])))\n',
                                    ['']],
 'bound_receiver_before_argument_rebinding': ['class Counter:\n'
                                              ' def __init__(self,value):self.value=value\n'
                                              ' def walk(self,n):\n'
                                              '  if n:return self.walk(n-1)+1\n'
                                              '  return self.value\n'
                                              'first=Counter(2)\n'
                                              'second=Counter(9)\n'
                                              'current=[first]\n'
                                              'def argument():\n'
                                              ' print("argument")\n'
                                              ' current[0]=second\n'
                                              ' return 3\n'
                                              'print(current[0].walk(argument()),current[0].value)\n',
                                              ['']],
 'classmethod_recursion': ['class Sequence:\n'
                           ' offset=7\n'
                           ' @classmethod\n'
                           ' def count(cls,n):\n'
                           '  if n:return cls.count(n-1)+1\n'
                           '  return cls.offset\n'
                           'print(Sequence.count(int(input())))\n',
                           ['0\n', '6\n']],
 'constructor_captured_default': ['events=[]\n'
                                  'def seed():\n'
                                  ' events.append(5)\n'
                                  ' return 5\n'
                                  'class Total:\n'
                                  ' def __init__(self,n,value=seed()):\n'
                                  '  self.value=value\n'
                                  '  if n:self.value+=Total(n-1).value\n'
                                  'print(Total(int(input())).value,events)\n',
                                  ['3\n']],
 'constructor_only_observer': ['class Counter:\n'
                               ' def __init__(self,value):self.value=value\n'
                               ' def walk(self,n):\n'
                               '  if n:return self.walk(n-1)+int(Counter(id(self)).value>0)\n'
                               '  return 0\n'
                               'print(Counter(2).walk(3))\n',
                               ['']],
 'deep_shared_receiver': ['import sys\n'
                          'sys.setrecursionlimit(100000)\n'
                          'class Accumulator:\n'
                          ' def __init__(self):self.total=0\n'
                          ' def walk(self,n):\n'
                          '  self.total+=n\n'
                          '  if n:return self.walk(n-1)+1\n'
                          '  return 0\n'
                          'value=Accumulator()\n'
                          'print(value.walk(int(input())),value.total)\n',
                          ['0\n', '5000\n']],
 'default_string_observation': ['class Counter:\n'
                                ' def __init__(self):self.value=2\n'
                                ' def walk(self,n):\n'
                                '  if n:return self.walk(n-1)+1\n'
                                '  return self.value\n'
                                'counter=Counter()\n'
                                'saved=str(counter)\n'
                                'print(saved==str(counter),counter.walk(3))\n',
                                ['']],
 'empty_method_loop_and_unbound': ['class Counter:\n'
                                   ' def walk(self,n):\n'
                                   '  if n:return self.walk(n-1)\n'
                                   '  for value in range(0):pass\n'
                                   '  return value\n'
                                   'print(Counter().walk(2))\n',
                                   ['']],
 'explicit_initializer_reentry': ['class Counter:\n'
                                  ' def __init__(self,n):\n'
                                  '  print("init",n)\n'
                                  '  self.value=n\n'
                                  '  if n:self.__init__(n-1)\n'
                                  ' def reset(self,n):\n'
                                  '  self.__init__(n)\n'
                                  '  return self.value\n'
                                  'counter=Counter(0)\n'
                                  'print(counter.reset(int(input())))\n',
                                  ['3\n']],
 'finite_bound_method_family': ['class Ascending:\n'
                                ' def walk(self,n):\n'
                                '  if n:return self.walk(n-1)+1\n'
                                '  return 2\n'
                                'class Descending:\n'
                                ' def walk(self,n):\n'
                                '  if n:return self.walk(n-1)-1\n'
                                '  return 9\n'
                                'if int(input()):item=Ascending()\n'
                                'else:item=Descending()\n'
                                'method=item.walk\n'
                                'print(method(3))\n',
                                ['0\n', '1\n']],
 'fixed_local_list_inside_method': ['class Counter:\n'
                                    ' def __init__(self):self.value=2\n'
                                    ' def walk(self,n):\n'
                                    '  pair=[n,self.value]\n'
                                    '  if n:return self.walk(n-1)+pair[0]\n'
                                    '  return pair[1]\n'
                                    'print(Counter().walk(4))\n',
                                    ['']],
 'identity_builtin_callback': ['class Counter:\n'
                               ' def __init__(self):self.value=2\n'
                               ' def walk(self,n):\n'
                               '  if n:return self.walk(n-1)+1\n'
                               '  return self.value\n'
                               'counter=Counter()\n'
                               'seen=list(map(id,[counter]))\n'
                               'print(seen[0]>0,counter.walk(3))\n',
                               ['']],
 'instance_parameter_and_result_alias': ['class Counter:\n'
                                         ' def __init__(self,value):self.value=value\n'
                                         ' def step(self,n):\n'
                                         '  self.value+=1\n'
                                         '  if n:return visit(self,n-1)\n'
                                         '  return self\n'
                                         'def visit(counter,n):return counter.step(n)\n'
                                         'original=Counter(2)\n'
                                         'result=visit(original,int(input()))\n'
                                         'print(result is original,original.value,result.value)\n',
                                         ['0\n', '6\n']],
 'low_limit_method_recursion': ['import sys\n'
                                'class Number:\n'
                                ' def walk(self,n):\n'
                                '  if n:return self.walk(n-1)+1\n'
                                '  return 0\n'
                                'sys.setrecursionlimit(30)\n'
                                'print(Number().walk(int(input())))\n',
                                ['3\n', '35\n']],
 'method_memo_list': ['class Paths:\n'
                      ' def __init__(self,n):self.memo=[-1]*(n+1)\n'
                      ' def count(self,n):\n'
                      '  if n==0:return 1\n'
                      '  if self.memo[n]>=0:return self.memo[n]\n'
                      '  result=self.count(n-1)\n'
                      '  if n>=2:result+=self.count(n-2)\n'
                      '  self.memo[n]=result\n'
                      '  return result\n'
                      'n=int(input())\n'
                      'paths=Paths(n)\n'
                      'print(paths.count(n),paths.memo)\n',
                      ['0\n', '9\n']],
 'mutable_field_augmented_suspension': ['class Counter:\n'
                                        ' def __init__(self):self.data=[1]\n'
                                        ' def walk(self,n):\n'
                                        '  if n:self.data[0]+=self.walk(n-1)\n'
                                        '  return self.data[0]\n'
                                        'counter=Counter()\n'
                                        'print(counter.walk(3),counter.data[0])\n',
                                        ['']],
 'mutual_instance_methods': ['class Game:\n'
                             ' def even(self,n):\n'
                             '  if n:return not self.odd(n-1)\n'
                             '  return True\n'
                             ' def odd(self,n):\n'
                             '  if n:return not self.even(n-1)\n'
                             '  return False\n'
                             'game=Game()\n'
                             'print(game.even(int(input())),game.odd(5))\n',
                             ['0\n', '8\n']],
 'non_tail_method_argument_error': ['class Number:\n'
                                    ' def divide(self,n,divisor):\n'
                                    '  print("visit",n)\n'
                                    '  if n:return self.combine(self.divide(n-1,divisor),n)\n'
                                    '  return 12//divisor\n'
                                    ' def combine(self,a,b):return a+b\n'
                                    'print(Number().divide(3,int(input())))\n',
                                    ['2\n', '0\n']],
 'owned_field_suspending_index': ['class Counter:\n'
                                  ' def __init__(self):self.data=[3,7]\n'
                                  ' def walk(self,n):\n'
                                  '  if n:return self.data[self.walk(n-1)]\n'
                                  '  return 0\n'
                                  'print(Counter().walk(int(input())))\n',
                                  ['1\n', '2\n']],
 'private_recursive_method': ['class Counter:\n'
                              ' def __init__(self):self.value=2\n'
                              ' def __walk(self,n):\n'
                              '  if n:return self.__walk(n-1)+1\n'
                              '  return self.value\n'
                              ' def run(self,n):return self.__walk(n)\n'
                              'print(Counter().run(int(input())))\n',
                              ['4\n']],
 'receiver_alias_rebinding': ['class Counter:\n'
                              ' def __init__(self,value):self.value=value\n'
                              ' def walk(self,n,other):\n'
                              '  original=self\n'
                              '  if n:\n'
                              '   self=other\n'
                              '   return original.walk(n-1,self)+1\n'
                              '  return original.value\n'
                              'first=Counter(2)\n'
                              'second=Counter(9)\n'
                              'print(first.walk(4,second),first.value,second.value)\n',
                              ['']],
 'recursive_constructor': ['class Total:\n'
                           ' def __init__(self,n):\n'
                           '  self.value=n\n'
                           '  if n:\n'
                           '   child=Total(n-1)\n'
                           '   self.value+=child.value\n'
                           'print(Total(int(input())).value)\n',
                           ['0\n', '6\n']],
 'recursive_method_cleanup': ['class Guard:\n'
                              ' def __enter__(self):\n'
                              '  print("enter")\n'
                              '  return self\n'
                              ' def __exit__(self,t,v,b):\n'
                              '  print("exit")\n'
                              '  return False\n'
                              'class Number:\n'
                              ' def walk(self,n):\n'
                              '  with Guard():\n'
                              '   if n:return self.walk(n-1)+1\n'
                              '   return 8\n'
                              'print(Number().walk(int(input())))\n',
                              ['2\n']],
 'recursive_numeric_add': ['class Number:\n'
                           ' def __init__(self,value):self.value=value\n'
                           ' def __add__(self,other):\n'
                           '  if self.value:return Number(self.value-1)+other\n'
                           '  return Number(other.value+10)\n'
                           'print((Number(int(input()))+Number(4)).value)\n',
                           ['0\n', '5\n']],
 'recursive_rich_comparison': ['class Number:\n'
                               ' def __init__(self,value):self.value=value\n'
                               ' def __lt__(self,other):\n'
                               '  print("compare",self.value,other.value)\n'
                               '  if self.value:return Number(self.value-1)<other\n'
                               '  return other.value>2\n'
                               'print(Number(int(input()))<Number(4))\n',
                               ['3\n']],
 'recursive_unary': ['class Number:\n'
                     ' def __init__(self,value):self.value=value\n'
                     ' def __neg__(self):\n'
                     '  if self.value:return -Number(self.value-1)\n'
                     '  return 4\n'
                     'print(-Number(int(input())))\n',
                     ['4\n']],
 'reflected_notimplemented_recursion': ['class Left:\n'
                                        ' def __add__(self,other):\n'
                                        '  print("left")\n'
                                        '  return NotImplemented\n'
                                        'class Right:\n'
                                        ' def __init__(self,n):self.n=n\n'
                                        ' def __radd__(self,other):\n'
                                        '  print("right",self.n)\n'
                                        '  if self.n:return other+Right(self.n-1)\n'
                                        '  return 11\n'
                                        'print(Left()+Right(int(input())))\n',
                                        ['0\n', '3\n']],
 'representation_builtin_callback': ['class Counter:\n'
                                     ' def __init__(self):self.value=2\n'
                                     ' def walk(self,n):\n'
                                     '  if n:return self.walk(n-1)+1\n'
                                     '  return self.value\n'
                                     'counter=Counter()\n'
                                     'texts=list(map(str,[counter]))\n'
                                     'print(texts[0].startswith("<__main__.Counter object at '
                                     '"),counter.walk(3))\n',
                                     ['']],
 'saved_bound_method_identity': ['class Counter:\n'
                                 ' def __init__(self,value):self.value=value\n'
                                 ' def walk(self,n):\n'
                                 '  if n:return self.walk(n-1)+1\n'
                                 '  return self.value\n'
                                 'counter=Counter(3)\n'
                                 'saved=counter.walk\n'
                                 'other=counter.walk\n'
                                 'print(saved is saved,saved is '
                                 'other,saved==other,saved(int(input())))\n',
                                 ['4\n']],
 'scalar_receiver_recursion': ['class Counter:\n'
                               ' def __init__(self):self.total=0\n'
                               ' def walk(self,n):\n'
                               '  self.total+=n\n'
                               '  if n:return self.walk(n-1)+1\n'
                               '  return 0\n'
                               'counter=Counter()\n'
                               'alias=counter\n'
                               'print(counter.walk(int(input())),alias.total,counter is alias)\n',
                               ['0\n', '7\n']],
 'unused_definition_default': ['events=[]\n'
                               'def stamp():\n'
                               ' events.append(3)\n'
                               ' return 3\n'
                               'class Counter:\n'
                               ' def unused(self,value=stamp()):return value\n'
                               ' def walk(self,n):\n'
                               '  if n:return self.walk(n-1)+1\n'
                               '  return 2\n'
                               'print(Counter().walk(3),events)\n',
                               ['']]}


class NativeClassContinuationProofTests(unittest.TestCase):
    def capture(self,name,integer='i64'):
        models=[]
        original=continuations.prepare
        def prepare(model):
            original(model)
            models.append(model)
        with patch.object(continuations,'prepare',prepare):
            result=transpile(SOURCES[name][0],TranspileOptions(integer=integer,license='none'))
        self.assertTrue(result.success,result.diagnostics)
        self.assertTrue(models)
        return result,models[-1]

    def test_shared_instance_arguments_and_results_use_owned_typed_frames(self):
        for mode in ('i64','i128','bigint'):
            result,model=self.capture('instance_parameter_and_result_alias',mode)
            registry=model.typed_continuations
            self.assertTrue(registry.plans)
            self.assertTrue(registry.invocations.complete())
            for plan in registry.plans.values():
                self.assertTrue(entry_result(model,plan))
                self.assertFalse(synchronous(model,plan))
                fields=registry.builders[plan.index].frame().split('impl ClassNativeFrame_',1)[0]
                self.assertNotIn('&',fields)
            self.assertIn('ClassHandle_',result.rust_source)
            self.assertIn('Vec<ClassNativeContinuation>',result.rust_source)
            for obsolete in ('Box::pin','dyn Future','fn class_call('):
                self.assertNotIn(obsolete,result.rust_source)

    def test_direct_method_producer_owns_the_original_receiver_first(self):
        _,model=self.capture('bound_receiver_before_argument_rebinding')
        registry=model.typed_continuations
        methods=[producer for producer in registry.invocations.producers.values()
                 if producer.role=='direct_method']
        self.assertTrue(methods)
        for producer in methods:
            self.assertIs(producer.receiver,producer.node.func.value)
            self.assertIs(producer.argument_nodes[0],producer.receiver)
            self.assertEqual(producer.argument_nodes[1:],tuple(producer.node.args))
            self.assertEqual(producer.logical_activation,'source')
            self.assertIsNotNone(producer.physical_result)

    def test_constructor_result_role_is_distinct_from_initializer_result(self):
        _,model=self.capture('scalar_receiver_recursion')
        registry=model.typed_continuations
        constructors=[producer for producer in registry.invocations.producers.values()
                      if producer.role=='constructor']
        self.assertTrue(constructors)
        for producer in constructors:
            self.assertIsInstance(producer.physical_result,InstanceType)
            self.assertEqual(producer.logical_activation,'constructor')
            self.assertTrue(synchronous(model,producer.callee))
            self.assertNotIn(producer.callee.index,registry.plans)

    def test_constructor_without_initializer_still_has_an_object_result_role(self):
        _,model=self.capture('mutual_instance_methods')
        producers=[producer for producer in model.typed_continuations.invocations.producers.values()
                   if producer.role=='constructor']
        self.assertTrue(producers)
        for producer in producers:
            self.assertIsNone(producer.callee)
            self.assertIsInstance(producer.physical_result,InstanceType)
            self.assertEqual(producer.logical_activation,'constructor')

    def test_builtin_callbacks_cannot_hide_identity_or_representation_observers(self):
        for name in ('identity_builtin_callback','representation_builtin_callback'):
            _,model=self.capture(name)
            self.assertFalse(model.typed_continuations.plans)
            self.assertRegex(model.typed_continuations.reason,'observer|callback')

    def test_method_store_policy_covers_aliases_and_every_receiver_alternative(self):
        from py2fastrust.native_invocation_control import method_slot_write_closed
        from py2fastrust.native_module_linking import ClassReferenceType
        from py2fastrust.native_types import union_type
        _,model=self.capture('finite_bound_method_family')
        kinds=[]
        for key,owner in model.classes.items():
            kind=InstanceType(key)
            kinds.append(kind)
            for method in owner.methods:
                self.assertFalse(method_slot_write_closed(model.classes,kind,method))
            self.assertFalse(method_slot_write_closed(model.classes,ClassReferenceType(owner.index),'walk'))
            self.assertFalse(method_slot_write_closed(model.classes,ClassReferenceType(owner.index),'new_data'))
            self.assertTrue(method_slot_write_closed(model.classes,kind,'new_data'))
        self.assertFalse(method_slot_write_closed(model.classes,union_type(*kinds),'walk'))
        self.assertFalse(method_slot_write_closed(model.classes,union_type(kinds[0],'none'),'walk'))
        self.assertFalse(method_slot_write_closed(model.classes,None,'walk'))
        self.assertFalse(method_slot_write_closed(model.classes,'int','walk'))

    def test_method_store_uses_canonical_private_names_and_requires_receiver_facts(self):
        import ast
        from py2fastrust.native_invocation_control import method_binding_write_closed
        _,model=self.capture('private_recursive_method')
        private_reads=[(plan,node)for plan in model.plans if plan.reachable
                       for node in model.value_classes.own_nodes(plan)
                       if isinstance(node,ast.Attribute)and node.attr=='__walk']
        self.assertTrue(private_reads)
        for plan,node in private_reads:
            self.assertFalse(method_binding_write_closed(model,plan,node))
        _,model=self.capture('scalar_receiver_recursion')
        writes=[(plan,node)for plan in model.plans if plan.reachable
                for node in model.value_classes.own_nodes(plan)
                if isinstance(node,ast.Attribute)and isinstance(node.ctx,ast.Store)]
        self.assertTrue(writes)
        for plan,node in writes:
            self.assertTrue(method_binding_write_closed(model,plan,node))
            key=plan.index,id(node.value)
            fact=model.records.pop(key)
            try:self.assertFalse(method_binding_write_closed(model,plan,node))
            finally:model.records[key]=fact

    def test_plain_self_and_mutual_methods_select_without_problem_names(self):
        for name in ('scalar_receiver_recursion','method_memo_list','mutual_instance_methods',
                     'receiver_alias_rebinding','argument_mutates_retained_receiver',
                     'private_recursive_method','empty_method_loop_and_unbound'):
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=name,integer=mode):
                    result,model=self.capture(name,mode)
                    self.assertTrue(model.typed_continuations.plans)
                    self.assertNotIn('Box::pin',result.rust_source)

    def test_unconverted_protocols_keep_the_previous_exact_native_program(self):
        for name in ('recursive_constructor','constructor_captured_default','explicit_initializer_reentry',
                     'saved_bound_method_identity','finite_bound_method_family','classmethod_recursion',
                     'recursive_numeric_add','reflected_notimplemented_recursion','recursive_unary',
                     'recursive_rich_comparison','bound_method_iterator_callback','recursive_method_cleanup',
                     'owned_field_suspending_index','mutable_field_augmented_suspension',
                     'fixed_local_list_inside_method','default_string_observation','constructor_only_observer','unused_definition_default','identity_builtin_callback','representation_builtin_callback'):
            with self.subTest(source=name):
                result,model=self.capture(name)
                self.assertFalse(model.typed_continuations.plans)
                self.assertTrue(model.typed_continuations.reason)
                with patch.object(continuations,'prepare',lambda model:setattr(model,'typed_continuations',None)):
                    prior=transpile(SOURCES[name][0],TranspileOptions(license='none'))
                self.assertTrue(prior.success,prior.diagnostics)
                self.assertEqual(result.rust_source,prior.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeClassContinuationExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def exercise(self,name):
        source,inputs=SOURCES[name]
        path=self.root/(name+'.py')
        path.write_text(source)
        expected=[subprocess.run([sys.executable,'-I','-S',str(path)],input=data,
                    text=True,capture_output=True,timeout=20)for data in inputs]
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(filename=str(path),integer=integer,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')
            self.assertNotIn('Box::pin',result.rust_source)
            for optimized in (False,True):
                with self.subTest(source=name,integer=integer,optimized=optimized):
                    rust=self.root/(name+'_'+integer+('_O'if optimized else'')+'.rs')
                    binary=rust.with_suffix('.bin')
                    rust.write_text(result.rust_source)
                    built=subprocess.run(['rustc','--edition=2021','--crate-name','class_continuations',
                                *(['-O']if optimized else[]),str(rust),'-o',str(binary)],
                                text=True,capture_output=True,timeout=180)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,cp in zip(inputs,expected):
                        actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=20)
                        self.assertEqual(actual.returncode,cp.returncode,actual.stderr)
                        self.assertEqual(actual.stdout,cp.stdout)
                        self.assertEqual(frames(actual.stderr),frames(cp.stderr))
                        final=lambda text:text.rstrip().splitlines()[-1]if text.strip()else''
                        self.assertEqual(final(actual.stderr),final(cp.stderr))

    def test_mutable_receiver_fields(self):self.exercise('scalar_receiver_recursion')
    def test_instance_parameter_and_result_alias(self):self.exercise('instance_parameter_and_result_alias')
    def test_receiver_before_argument_rebinding(self):self.exercise('bound_receiver_before_argument_rebinding')
    def test_rebound_self_and_local_alias(self):self.exercise('receiver_alias_rebinding')
    def test_mutating_argument_leaf(self):self.exercise('argument_mutates_retained_receiver')
    def test_atomic_memo_field_access(self):self.exercise('method_memo_list')
    def test_original_method_error_frames(self):self.exercise('non_tail_method_argument_error')
    def test_deep_shared_receiver(self):self.exercise('deep_shared_receiver')
    def test_private_method_binding(self):self.exercise('private_recursive_method')
    def test_unbound_local_after_empty_loop(self):self.exercise('empty_method_loop_and_unbound')


if __name__=='__main__':unittest.main()
