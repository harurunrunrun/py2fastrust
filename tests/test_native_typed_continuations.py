"""Owned typed continuation frames preserve ordinary source call semantics."""
import hashlib
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
from py2fastrust.native_class_calls import synchronous,entry_result

SOURCES={'annotation_target': ['values=[0]\n'
                       'def mark():\n'
                       " print('index')\n"
                       ' return 0\n'
                       'def count(depth):\n'
                       ' if depth:count(depth-1)\n'
                       ' values[mark()]:int\n'
                       ' return depth\n'
                       'print(count(2))\n',
                       ['']],
 'atomic_mutating_sort_global': ['values = [3, 1, 2]\n'
                                 'def walk(n):\n'
                                 '    if n == 0:\n'
                                 '        return 0\n'
                                 '    values.sort()\n'
                                 '    return values[0] + walk(n - 1)\n'
                                 'print(walk(3), values)\n',
                                 ['']],
 'atomic_sorted_global': ['values = [3, 1, 2]\n'
                          'def walk(n):\n'
                          '    if n == 0:\n'
                          '        return 0\n'
                          '    return sorted(values)[0] + walk(n - 1)\n'
                          'print(walk(3), values)\n',
                          ['']],
 'call_before_later_definition': ['def visit(value):\n'
                                  ' if value:return later(value-1)\n'
                                  ' return 0\n'
                                  'print(visit(1))\n'
                                  'def later(value):\n'
                                  ' return visit(value)\n',
                                  ['']],
 'captured_builtin_before_recursive_argument': ['operation = abs\n'
                                                '\n'
                                                'def visit(n):\n'
                                                '    global operation\n'
                                                '    if n:\n'
                                                '        return operation(visit(n - 1))\n'
                                                '    operation = int\n'
                                                '    return -3\n'
                                                '\n'
                                                'print(visit(1))\n',
                                                ['']],
 'captured_recursive_function': ['def make(offset):\n'
                                 ' def visit(depth):\n'
                                 '  if depth:return visit(depth-1)+offset\n'
                                 '  return offset\n'
                                 ' return visit\n'
                                 'first=make(3)\n'
                                 'second=make(8)\n'
                                 'print(first(4),second(2),first(0))\n',
                                 ['']],
 'comparison_suspend_keeps_old_path': ['def total(value):\n'
                                       ' if value==0:return 0\n'
                                       ' if total(value-1)>2:return 5\n'
                                       ' return value\n'
                                       'print(total(5))\n',
                                       ['']],
 'condition_boolop': ['def count(depth):\n'
                      ' if depth==0:return 0\n'
                      ' if count(depth-1) or depth<3:return 1\n'
                      ' return 2\n'
                      'print(count(5))\n',
                      ['']],
 'condition_not_boolop': ['def count(depth):\n'
                          ' if depth==0:return 0\n'
                          ' if not (count(depth-1) and depth>2):return 1\n'
                          ' return 2\n'
                          'print(count(5))\n',
                          ['']],
 'for_recursive_target_with_direct_edge': ['slots = [0]\n'
                                           '\n'
                                           'def visit(n):\n'
                                           '    if n == 0:\n'
                                           '        return 0\n'
                                           '    if n == 1:\n'
                                           '        return visit(0)\n'
                                           '    for slots[visit(n - 1)] in range(1):\n'
                                           '        pass\n'
                                           '    return 0\n'
                                           '\n'
                                           'print(visit(int(input())), slots)\n',
                                           ['3\n']],
 'global_inplace_alias': ['items=[1]\n'
                          'alias=items\n'
                          'def visit(depth):\n'
                          ' global items\n'
                          ' if depth:visit(depth-1)\n'
                          ' items *= 2\n'
                          ' return len(items)\n'
                          'print(visit(2),alias)\n',
                          ['']],
 'long_acyclic_module_data_40': ['OFFSET=int(input())\n'
                                 'def stage0(value):return stage1(value)+1\n'
                                 'def stage1(value):return stage2(value)+1\n'
                                 'def stage2(value):return stage3(value)+1\n'
                                 'def stage3(value):return stage4(value)+1\n'
                                 'def stage4(value):return stage5(value)+1\n'
                                 'def stage5(value):return stage6(value)+1\n'
                                 'def stage6(value):return stage7(value)+1\n'
                                 'def stage7(value):return stage8(value)+1\n'
                                 'def stage8(value):return stage9(value)+1\n'
                                 'def stage9(value):return stage10(value)+1\n'
                                 'def stage10(value):return stage11(value)+1\n'
                                 'def stage11(value):return stage12(value)+1\n'
                                 'def stage12(value):return stage13(value)+1\n'
                                 'def stage13(value):return stage14(value)+1\n'
                                 'def stage14(value):return stage15(value)+1\n'
                                 'def stage15(value):return stage16(value)+1\n'
                                 'def stage16(value):return stage17(value)+1\n'
                                 'def stage17(value):return stage18(value)+1\n'
                                 'def stage18(value):return stage19(value)+1\n'
                                 'def stage19(value):return stage20(value)+1\n'
                                 'def stage20(value):return stage21(value)+1\n'
                                 'def stage21(value):return stage22(value)+1\n'
                                 'def stage22(value):return stage23(value)+1\n'
                                 'def stage23(value):return stage24(value)+1\n'
                                 'def stage24(value):return stage25(value)+1\n'
                                 'def stage25(value):return stage26(value)+1\n'
                                 'def stage26(value):return stage27(value)+1\n'
                                 'def stage27(value):return stage28(value)+1\n'
                                 'def stage28(value):return stage29(value)+1\n'
                                 'def stage29(value):return stage30(value)+1\n'
                                 'def stage30(value):return stage31(value)+1\n'
                                 'def stage31(value):return stage32(value)+1\n'
                                 'def stage32(value):return stage33(value)+1\n'
                                 'def stage33(value):return stage34(value)+1\n'
                                 'def stage34(value):return stage35(value)+1\n'
                                 'def stage35(value):return stage36(value)+1\n'
                                 'def stage36(value):return stage37(value)+1\n'
                                 'def stage37(value):return stage38(value)+1\n'
                                 'def stage38(value):return stage39(value)+1\n'
                                 'def stage39(value):return 10//value+OFFSET\n'
                                 'print(stage0(int(input())))\n',
                                 ['2\n2\n', '2\n0\n']],
 'main_map_unpack': ['def walk(depth):\n'
                     ' if depth:return walk(depth-1)+1\n'
                     ' return 0\n'
                     'def main():\n'
                     ' n,m=map(int,input().split())\n'
                     ' print(walk(n)+m)\n'
                     'main()\n',
                     ['3 7\n']],
 'memoized_composition_dp': ['n=int(input())\n'
                             'memo=[-1]*(n+1)\n'
                             'def count(remaining):\n'
                             ' if remaining==0:return 1\n'
                             ' if memo[remaining]!=-1:return memo[remaining]\n'
                             ' total=0\n'
                             ' for step in (1,3,4):\n'
                             '  if step<=remaining:total+=count(remaining-step)\n'
                             ' memo[remaining]=total\n'
                             ' return total\n'
                             'print(count(n))\n',
                             ['0\n', '12\n']],
 'mutual_game_states': ['def left(remaining):\n'
                        ' if remaining==0:return False\n'
                        ' return not right(remaining-1)\n'
                        'def right(remaining):\n'
                        ' if remaining==0:return True\n'
                        ' return not left(remaining-1)\n'
                        'n=int(input())\n'
                        'print(left(n),right(n))\n',
                        ['0\n', '9\n']],
 'recursion_limit_boundary': ['import sys\n'
                              'sys.setrecursionlimit(int(input()))\n'
                              'def visit(depth):\n'
                              ' if depth:return visit(depth-1)+1\n'
                              ' return 0\n'
                              'print(visit(int(input())))\n',
                              ['30\n4\n', '30\n35\n']],
 'recursive_argument_order_error': ['def mark(label,value):\n'
                                    ' print(label,value)\n'
                                    ' return value\n'
                                    'def visit(depth):\n'
                                    ' if depth==0:return 10//int(input())\n'
                                    " return visit(mark('left',depth-1))+mark('right',depth)\n"
                                    'print(visit(int(input())))\n',
                                    ['3\n2\n', '3\n0\n']],
 'recursive_boolean_short_circuit': ['def descend(value):\n'
                                     ' print(value)\n'
                                     ' return value and descend(value-1)\n'
                                     'print(descend(int(input())))\n',
                                     ['0\n', '4\n']],
 'recursive_map_callback': ['def leaves(depth):\n'
                            ' if depth==0:return 1\n'
                            ' return sum(map(leaves,[depth-1,depth-1]))\n'
                            'print(leaves(int(input())))\n',
                            ['0\n', '4\n']],
 'recursive_range_loop_else_break': ['def total(value):\n'
                                     ' if value==0:return 1\n'
                                     ' result=0\n'
                                     ' for step in range(4):\n'
                                     '  if step==0:continue\n'
                                     '  if step>value:break\n'
                                     '  result+=total(value-step)\n'
                                     ' else:\n'
                                     '  result+=10\n'
                                     ' return result\n'
                                     'print(total(int(input())))\n',
                                     ['1\n', '4\n']],
 'recursive_with_cleanup': ['class Scope:\n'
                            " def __enter__(self):print('enter');return 0\n"
                            " def __exit__(self,kind,value,trace):print('exit');return False\n"
                            'def visit(depth,divisor):\n'
                            ' with Scope():\n'
                            '  if depth:return visit(depth-1,divisor)+1\n'
                            '  return 10//divisor\n'
                            'depth,divisor=map(int,input().split())\n'
                            'print(visit(depth,divisor))\n',
                            ['2 2\n', '2 0\n']],
 'tail_recursive_accumulator': ['import sys\n'
                                'sys.setrecursionlimit(100000)\n'
                                'def total(remaining,answer):\n'
                                ' if remaining:return total(remaining-1,answer+remaining)\n'
                                ' return answer\n'
                                'print(total(int(input()),0))\n',
                                ['20\n', '5000\n']],
 'tree_subtree_sizes': ['import sys\n'
                        'sys.setrecursionlimit(100000)\n'
                        'n=int(input())\n'
                        'graph=[[] for _ in range(n)]\n'
                        'for _ in range(n-1):\n'
                        ' a,b=map(int,input().split())\n'
                        ' graph[a].append(b)\n'
                        ' graph[b].append(a)\n'
                        'sizes=[0]*n\n'
                        'def dfs(vertex,parent):\n'
                        ' result=1\n'
                        ' for child in graph[vertex]:\n'
                        '  if child!=parent:result+=dfs(child,vertex)\n'
                        ' sizes[vertex]=result\n'
                        ' return result\n'
                        'dfs(0,-1)\n'
                        'print(*sizes)\n',
                        ['1\n', '7\n0 1\n0 2\n1 3\n1 4\n2 5\n5 6\n']],
 'type_change_keeps_old_path': ['def total(value):\n'
                                ' result=False\n'
                                ' if value:result=total(value-1)+1\n'
                                ' return int(result)\n'
                                'print(total(4))\n',
                                ['']],
 'unused_default_calls_recursion': ['def visit(value):\n'
                                    ' if value:return visit(value-1)+1\n'
                                    ' return 0\n'
                                    'def unused(value=visit(2)):return value\n'
                                    'print(visit(3))\n',
                                    ['']],
 'used_class_recursive_prefix': ['class Prefix:\n'
                                 ' def __init__(self,values):self.values=values\n'
                                 ' def total(self,index):\n'
                                 '  if index<0:return 0\n'
                                 '  return self.total(index-1)+self.values[index]\n'
                                 'values=list(map(int,input().split()))\n'
                                 'print(Prefix(values).total(len(values)-1))\n',
                                 ['\n', '2 7 1 8 2\n']]}


def frames(text):
    result=[]
    for line in text.splitlines():
        match=re.search(r'File "([^"]+)", line (\d+), in (.+)',line)
        if match:
            result.append(match.groups())
            continue
        repeated=re.fullmatch(r'\s*\[Previous line repeated (\d+) more times\]\s*',line)
        if repeated:
            if not result:raise AssertionError('a repeated traceback has no preceding frame')
            result.extend([result[-1]]*int(repeated.group(1)))
    return result


class TypedContinuationProofTests(unittest.TestCase):
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

    def test_result_entry_does_not_grant_no_suspend_or_borrow_traits(self):
        result,model=self.capture('mutual_game_states')
        registry=model.typed_continuations
        self.assertTrue(registry.plans)
        for plan in registry.plans.values():
            self.assertTrue(entry_result(model,plan))
            self.assertFalse(synchronous(model,plan))
            builder=registry.builders[plan.index]
            fields=builder.frame().split('impl ClassNativeFrame_',1)[0]
            self.assertNotIn('&',fields)
        self.assertIn('Vec<ClassNativeContinuation>',result.rust_source)
        for obsolete in ('Box::pin','dyn Future','struct ClassCall','fn class_call('):
            self.assertNotIn(obsolete,result.rust_source)

    def test_original_scalar_algorithms_select_owned_native_frames(self):
        for name in ('tree_subtree_sizes','memoized_composition_dp','mutual_game_states',
                     'tail_recursive_accumulator','long_acyclic_module_data_40',
                     'recursive_boolean_short_circuit','condition_boolop','condition_not_boolop',
                     'recursive_range_loop_else_break'):
            for mode in ('i64','i128','bigint'):
                with self.subTest(source=name,integer=mode):
                    result,model=self.capture(name,mode)
                    self.assertTrue(model.typed_continuations.plans)
                    self.assertIn('fn class_native_region(',result.rust_source)
                    self.assertNotIn('Box::pin',result.rust_source)
                    self.assertNotIn('enum Value',result.rust_source)

    def test_unclosed_source_features_preserve_previous_native_products(self):
        for name in ('recursive_map_callback','captured_recursive_function','recursive_with_cleanup',
                     'used_class_recursive_prefix','unused_default_calls_recursion',
                     'type_change_keeps_old_path','comparison_suspend_keeps_old_path',
                     'call_before_later_definition','for_recursive_target_with_direct_edge'):
            with self.subTest(source=name):
                result,model=self.capture(name)
                self.assertFalse(model.typed_continuations.plans)
                self.assertTrue(model.typed_continuations.reason)
                with patch.object(continuations,'prepare',lambda model:setattr(model,'typed_continuations',None)):
                    prior=transpile(SOURCES[name][0],TranspileOptions(license='none'))
                self.assertTrue(prior.success,prior.diagnostics)
                self.assertEqual(result.rust_source,prior.rust_source)

    def test_recursive_for_target_has_a_suspension_place_barrier(self):
        _,model=self.capture('for_recursive_target_with_direct_edge')
        self.assertIn('target',model.typed_continuations.reason)
        self.assertIn('place',model.typed_continuations.reason)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class TypedContinuationExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temporary.name)
        cls.products={}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def exercise(self,name):
        source,inputs=SOURCES[name]
        source_path=self.root/(name+'.py')
        source_path.write_text(source)
        # Isolated ordinary CPython execution avoids system excepthooks. No
        # wrapper, custom hook, or source rewrite changes the Python call stack.
        expected=[subprocess.run([sys.executable,'-I','-S',str(source_path)],input=data,
                    text=True,capture_output=True,timeout=20)for data in inputs]
        for integer in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=integer,filename=str(source_path),license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')
            self.assertLess(len(result.rust_source.encode()),512*1024)
            for optimized in (False,True):
                with self.subTest(source=name,integer=integer,optimized=optimized):
                    rust=self.root/(name+'_'+integer+('_O'if optimized else'')+'.rs')
                    binary=rust.with_suffix('.bin')
                    rust.write_text(result.rust_source)
                    command=['rustc','--edition=2021','--crate-name','continuations',
                             *(['-O']if optimized else[]),str(rust),'-o',str(binary)]
                    built=subprocess.run(command,text=True,capture_output=True,timeout=180)
                    self.assertEqual(built.returncode,0,built.stderr)
                    for data,cp in zip(inputs,expected):
                        actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=20)
                        self.assertEqual(actual.returncode,cp.returncode,actual.stderr)
                        self.assertEqual(actual.stdout,cp.stdout)
                        self.assertEqual(frames(actual.stderr),frames(cp.stderr))
                        final=lambda text:text.rstrip().splitlines()[-1]if text.strip()else''
                        self.assertEqual(final(actual.stderr),final(cp.stderr))

    def test_deep_tail_frames_do_not_use_the_host_call_stack(self):
        self.exercise('tail_recursive_accumulator')

    def test_scalar_dfs_and_live_global_list_iteration(self):
        self.exercise('tree_subtree_sizes')

    def test_argument_order_and_recursive_error_frames(self):
        self.exercise('recursive_argument_order_error')

    def test_runtime_recursion_limit_is_checked_per_source_activation(self):
        self.exercise('recursion_limit_boundary')

    def test_atomic_inplace_list_statement_preserves_aliases(self):
        self.exercise('global_inplace_alias')

    def test_atomic_fused_input_unpack_remains_supported(self):
        self.exercise('main_map_unpack')

    def test_annotation_only_targets_preserve_input_effects(self):
        self.exercise('annotation_target')

    def test_atomic_sorted_expression_uses_the_result_abi(self):
        self.exercise('atomic_sorted_global')

    def test_atomic_mutating_sort_uses_the_result_abi(self):
        self.exercise('atomic_mutating_sort_global')

    def test_callee_is_captured_before_recursive_argument_effects(self):
        self.exercise('captured_builtin_before_recursive_argument')


if __name__=='__main__':unittest.main()
