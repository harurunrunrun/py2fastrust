"""Native recursion is selected from lexical identities before code generation."""
import shutil
import unittest
from unittest.mock import patch

from py2fastrust import TranspileOptions,transpile
from py2fastrust.frontend import build_program
from py2fastrust.native_frame_selection import select_frames
from tests import test_native_heapq as _heap


FACTORIAL='''def factorial(n):
 if n<=1:return 1
 return n*factorial(n-1)
print(factorial(int(input())))
'''


class FrameSelectionProofTests(unittest.TestCase):
    def select(self,source):return select_frames(build_program(source,'selection.py').main)

    def test_direct_mutual_and_proved_alias_cycles_use_shared_function_identities(self):
        sources=[FACTORIAL,
                 'def even(n):\n if n==0:return True\n return odd(n-1)\ndef odd(n):\n if n==0:return False\n return even(n-1)\nprint(even(4))\n',
                 'def count(n):\n if n==0:return 0\n return 1+again(n-1)\nagain=count\nprint(count(5))\n']
        for source in sources:
            with self.subTest(source=source):
                selection=self.select(source)
                self.assertTrue(selection.required)
                self.assertTrue(selection.recursive_definitions)
                self.assertTrue(selection.call_targets)

    def test_nonrecursive_functions_and_same_spelling_local_bindings_keep_fastpath(self):
        sources=['def inc(n):return n+1\nprint(inc(3))\n',
                 'def choose(choose):return choose+1\nprint(choose(3))\n',
                 'def step(n):return n+1\nalias=step\nprint(alias(3))\n',
                 'def unused(n):return unused(n)\nprint(3)\n']
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(self.select(source).required)
                with patch('py2fastrust.native_classes.try_generate_classes',side_effect=AssertionError('unnecessary frame path')):
                    self.assertTrue(transpile(source).success)

    def test_selected_frame_failure_never_retries_an_ordinary_or_vm_emitter(self):
        for mode in('i64','i128','bigint'):
            with patch('py2fastrust.native_classes.try_generate_classes',return_value=None)as frames, \
                 patch('py2fastrust.native_scalar.ScalarGenerator.statements',side_effect=AssertionError('scalar retry')), \
                 patch('py2fastrust.native_bigint.try_generate_bigint',side_effect=AssertionError('BigInt retry')), \
                 patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                result=transpile(FACTORIAL,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(frames.call_count,1)
            self.assertEqual(result.diagnostics[0].code,'E006')

    def test_unknown_callable_has_no_invented_recursive_edge(self):
        source='def call_it(fn,n):return fn(n)\nprint(call_it(int(input()),2))\n'
        selection=self.select(source)
        self.assertFalse(selection.required)
        result=transpile(source)
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertGreater(result.diagnostics[0].line,0)

    def test_escaping_or_ambiguous_function_objects_have_explicit_diagnostics(self):
        sources=['def rec(n):\n if n==0:return 0\n return rec(n-1)\nalias=rec\nprint(alias,rec(2))\n',
                 'def rec(n):\n if n==0:return 0\n return dispatch(n-1)\ndef other(n):return rec(n)\nif input():dispatch=rec\nelse:dispatch=other\nprint(rec(2))\n']
        for source in sources:
            for mode in('i64','i128','bigint'):
                with self.subTest(source=source,mode=mode):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)

    def test_cross_scope_callable_writes_do_not_reuse_stale_module_call_facts(self):
        source='''def first(n):
 if n<=0:return 0
 return 1+first(n-1)
def second(n):return 100+n
alias=first
def switch():
 global alias
 alias=second
switch()
print(alias(2),first(3))
'''
        for mode in('i64','i128','bigint'):
            with self.subTest(mode=mode):
                result=transpile(source,TranspileOptions(integer=mode))
                self.assertFalse(result.success)
                self.assertEqual(result.diagnostics[0].code,'E006')
                self.assertIn('callable binding versions',result.diagnostics[0].message)

    def test_callable_binding_deletion_is_not_erased_as_an_unused_value(self):
        source='''def first(n):
 if n<=0:return 0
 return 1+first(n-1)
alias=first
del alias
if False:alias=7
print(first(2))
'''
        for mode in('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('binding existence and lifetime',result.diagnostics[0].message)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class FrameSelectionExecutionTests(unittest.TestCase):
    def compare(self,*args,**kwargs):return _heap.HeapExecutionTests.compare(self,*args,**kwargs)

    def test_ordinary_scalar_recursion_has_no_class_declaration(self):
        self.compare(FACTORIAL,tuple(str(n)+'\n'for n in(-3,0,1,2,7,12)))

    def test_mutual_forward_calls_and_keyword_defaults(self):
        self.compare('''def even(n):
 if n==0:return True
 return odd(n-1)
def odd(n):
 if n==0:return False
 return even(n-1)
def total(n,step=2):
 if n<=0:return 0
 return n+total(n-step,step=step)
n=int(input())
print(even(n),odd(n),total(n),total(n,step=3))
''',tuple(str(n)+'\n'for n in(0,1,6,11,34)))

    def test_proved_module_and_local_callable_aliases_keep_definition_defaults(self):
        self.compare('''def count(n,step=2):
 if n<=0:return 0
 return step+again(n-1,step=step)
again=count
third=again
def descend(n):
 next_call=descend
 if n<=0:return 0
 return 1+next_call(n-1)
n=int(input())
print(third(n),again(n,step=3),descend(n))
''',('0\n','1\n','5\n','28\n'))

    def test_frame_local_arguments_and_assignments_can_shadow_module_functions(self):
        self.compare('''def recurse(n):
 if n==0:return 0
 return 1+recurse(n-1)
def choose(choose):
 recurse=choose+2
 return recurse
print(recurse(3),choose(5))
''')

    def test_module_local_callable_rebinding_and_function_local_shadowing_are_proved(self):
        self.compare('''def first(n):
 if n<=0:return 0
 return 1+first(n-1)
def second(n):return 100+n
alias=first
def switch():
 alias=second
 return alias(4)
print(switch(),alias(2))
alias=second
print(alias(2),first(3))
''')

    def test_nullable_recursive_return_uses_its_typed_result(self):
        self.compare('''def find(n):
 if n<0:return None
 if n==0:return 0
 return find(n-2)
print(find(int(input())))
''',('-1\n','0\n','2\n','3\n','24\n'))

    def test_recursive_errors_keep_prior_effects_and_exception_kind(self):
        self.compare('''def divide(n):
 print('enter',n)
 if n==0:return 1//0
 return divide(n-1)
print(divide(int(input())))
''',('0\n','3\n','bad\n'))


if __name__=='__main__':unittest.main()
