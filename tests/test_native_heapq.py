"""Heap protocol, object storage and operation order against CPython3.14."""
import os
import random
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions


class HeapProofTests(unittest.TestCase):
    def test_unsupported_public_stream_selection_and_payloads_are_explicit(self):
        sources=["import heapq\nprint(list(heapq.merge([1],[2])))\n",
                 "from heapq import nlargest\nprint(nlargest(2,[1,2]))\n",
                 "import heapq\nheapq.nsmallest(2,[1,2])\n",
                 "import heapq\nh=[1,'x']\nheapq.heapify(h)\n",
                 "import heapq\nh=[(1.0,),(2.0,)]\nheapq.heapify(h)\n",
                 "import heapq\nh=[]\nxs=[1]\nout=heapq.heappushpop(h,xs)\nprint(xs,out)\n"]
        for source in sources:
            for mode in ('i64','i128','bigint'):
                with self.subTest(mode=mode,source=source):
                    result=transpile(source,TranspileOptions(integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertGreater(result.diagnostics[0].line,0)

    def test_unimplemented_assignment_expression_remains_an_explicit_boundary(self):
        source='''import heapq
heap=[3]
original=heap
heapq.heappush(heap,(heap:=[10])[0])
print(original,heap)
print(heapq.heappushpop(original,(heap:=[2,8])[0]))
print(original,heap)
'''
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')

@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class HeapExecutionTests(unittest.TestCase):
    def compare(self,source,inputs=('',),modes=('i64','i128','bigint')):
        with tempfile.TemporaryDirectory(prefix='pytors-heapq-')as directory:
            for mode in modes:
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=mode,filename='heap_case.py'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                path=Path(directory)/(mode+'.rs');path.write_text(result.rust_source)
                for release in (False,True):
                    binary=path.with_name(mode+str(release))
                    build=subprocess.run(['rustc','--edition=2021',*(['-O']if release else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    for data in inputs:
                        expected=subprocess.run([sys.executable,'-I','-c',source],input=data,capture_output=True,text=True,timeout=10)
                        actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                        self.assertEqual((actual.stdout,actual.returncode),(expected.stdout,expected.returncode),actual.stderr+expected.stderr)
                        if expected.returncode:self.assertEqual(actual.stderr.splitlines()[-1].split(':')[0],expected.stderr.splitlines()[-1].split(':')[0])

    def test_core_min_heap_operations_and_observable_list_layout(self):
        self.compare('''import heapq
h=[7,1,5,1,3]
print(heapq.heapify(h),h)
print(heapq.heappush(h,-2),h)
print(heapq.heappop(h),h)
print(heapq.heappushpop(h,4),h)
print(heapq.heapreplace(h,-9),h)
while h:print(heapq.heappop(h),end='|')
print()
''')

    def test_314_max_heap_operations_and_layout(self):
        self.compare('''import heapq
h=[7,1,5,1,3]
print(heapq.heapify_max(h),h)
print(heapq.heappush_max(h,9),h)
print(heapq.heappop_max(h),h)
print(heapq.heappushpop_max(h,4),h)
print(heapq.heapreplace_max(h,-9),h)
while h:print(heapq.heappop_max(h),end='|')
print()
''')

    def test_module_member_assignment_aliases_and_function_local_imports(self):
        self.compare('''import sys,heapq as hq
from heapq import heappush as add,heappop as take
module=hq
push=module.heappush
h=[]
add(h,3)
push(h,1)
print(take(h),hq.heappop(h))
def run():
 import heapq as local
 q=[8,2,4]
 local.heapify(q)
 return local.heappop(q)
print(run())
''')

    def test_integer_bool_ties_keep_python_identity_tags(self):
        self.compare('''import heapq
h=[False,0,True,1,-1,1]
heapq.heapify(h)
print(h)
print(heapq.heappushpop(h,True),h)
while h:print(heapq.heappop(h),end='|')
print()
h=[False,0,True,1]
heapq.heapify_max(h)
print(h)
while h:print(heapq.heappop_max(h),end='|')
''')

    def test_tuple_priorities_and_shared_runtime_tuple_tie_identity(self):
        self.compare('''import heapq
h=[(2,'z'),(1,'b'),(1,'a')]
heapq.heapify(h)
while h:print(heapq.heappop(h))
a=tuple([1])
b=tuple([1])
c=tuple([1])
d=tuple([1])
h=[a,b,c]
heapq.heapify(h)
print([x is a for x in h],[x is b for x in h],[x is c for x in h])
x=heapq.heappushpop(h,d)
print(x is d)
print(heapq.heappop(h) is c,heapq.heappop(h) is b,heapq.heappop(h) is a)
''')

    def test_arguments_evaluate_before_borrow_and_empty_pushpop_is_lazy_about_heap(self):
        self.compare('''import heapq
def mark(x):
 print('item',x)
 return x
h=[]
print(heapq.heappushpop(h,mark(8)),h)
h=[2]
print(heapq.heappush(h,heapq.heappop(h)),h)
print(heapq.heappushpop(h,heapq.heapreplace(h,4)),h)
''')

    def test_combined_operation_checks_heap_emptiness_after_argument_mutation(self):
        self.compare('''import heapq
h=[]
print(heapq.heappushpop(h,(heapq.heappush(h,5),10)[1]),h)
h=[]
print(heapq.heappushpop_max(h,(heapq.heappush_max(h,5),0)[1]),h)
h=[2]
print(heapq.heappush(h,(h.clear(),1)[1]),h)
print(heapq.heappushpop([],7),heapq.heappushpop([],None))
''')

    def test_empty_pop_replace_and_unbound_heap_preserve_error_order(self):
        for call in ['heapq.heappop(h)','heapq.heapreplace(h,mark(8))',
                     'heapq.heappop_max(h)','heapq.heapreplace_max(h,mark(8))']:
            source="import heapq\ndef mark(x):\n print('item',x)\n return x\nh=[]\nprint("+call+")\n"
            self.compare(source)
        self.compare('''import heapq
def mark(x):
 print('wrong item')
 return x
if int(input()):h=[1]
heapq.heappush(h,mark(7))
print(h)
''',('0\n','1\n'))

    def test_zero_loop_after_heap_mutation_does_not_keep_stale_cardinality(self):
        self.compare('''import heapq
h=[1]
print(heapq.heappop(h))
for x in h:print('wrong')
print(heapq.heappushpop(h,9))
for x in h:print('wrong')
heapq.heappush(h,2)
print([x for x in h])
''')

    def test_shared_heaps_keep_aliases_functions_and_parent_mutation_semantics(self):
        self.compare('''from heapq import heappush as insert,heappop as remove
import heapq
def add(queue,item):
 insert(queue,item)
def take(queue):
 return remove(queue)
def same(queue):
 return queue
queue=[]
add(queue,5)
add(queue,2)
print(take(queue),queue)
print(take(queue),queue)
heap=[5,1,5]
alias=heap
heapq.heapify(alias)
print(heap is alias,heap)
print(heapq.heappop(heap),alias)
heapq.heappush(alias,0)
print(heap)
rows=[[]]
row=rows[0]
heapq.heappush(row,4)
print(next(iter(row)))
rows.clear()
heapq.heappush(row,1)
print(row,rows)
rows=[[3],[9]]
heapq.heappush(rows[0],(rows.clear(),4)[1])
print(rows)
heap=[4,2]
saved=same(heap)
heapq.heapify(saved)
print(saved is heap,heap)
print(heapq.heappop(heap),saved)
heap=[1,3,5]
alias=heap
heapq.heappush(heap,heapq.heappop(alias))
print(heap,alias)
print(heapq.heappushpop(alias,heapq.heapreplace(heap,2)))
print(heap,alias)
''')

    def test_bare_float_less_preserves_nan_and_signed_zero_behavior(self):
        self.compare('''import heapq
h=[float(input()) for _ in range(6)]
heapq.heapify(h)
print(h)
print(heapq.heappushpop(h,-0.0),h)
while h:print(heapq.heappop(h),end='|')
print()
h=[0,1.5,2,False]
heapq.heapify_max(h)
print(h)
while h:print(heapq.heappop_max(h),end='|')
''',('nan\n1\n-0.0\n0.0\ninf\n-2\n','3\n2\n1\n0\n-1\n-2\n'),modes=('i64','i128'))

    def test_seeded_operation_sequences_use_both_heap_directions(self):
        source='''import heapq
maximum=int(input())
n,q=map(int,input().split())
h=list(map(int,input().split()))
if maximum:heapq.heapify_max(h)
else:heapq.heapify(h)
print(h)
for _ in range(q):
 command=list(map(int,input().split()))
 op=command[0]
 if op==0:
  if maximum:heapq.heappush_max(h,command[1])
  else:heapq.heappush(h,command[1])
 elif op==1:
  if maximum:print(heapq.heappop_max(h))
  else:print(heapq.heappop(h))
 elif op==2:
  if maximum:print(heapq.heappushpop_max(h,command[1]))
  else:print(heapq.heappushpop(h,command[1]))
 elif op==3:
  if maximum:print(heapq.heapreplace_max(h,command[1]))
  else:print(heapq.heapreplace(h,command[1]))
 else:
  if maximum:heapq.heapify_max(h)
  else:heapq.heapify(h)
 print(h)
'''
        rng=random.Random(2026102951);inputs=[]
        for case in range(48):
            initial=[rng.randrange(-20,21)for _ in range(rng.randrange(9))]
            commands=[]
            for _ in range(30):
                op=rng.randrange(5)
                commands.append(str(op)+(' '+str(rng.randrange(-20,21))if op in {0,2,3}else''))
            inputs.append(f'{case%2}\n{len(initial)} {len(commands)}\n'+' '.join(map(str,initial))+'\n'+'\n'.join(commands)+'\n')
        self.compare(source,tuple(inputs))


if __name__=='__main__':unittest.main()
