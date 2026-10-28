"""Dictionary deletion, update order, retained keys and bounded churn."""
import os
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeMappingMutationTests(unittest.TestCase):
    def compare(self,source,inputs=('',),*,optimize=True,integer_policy=False):
        # Compare the exception object's message, not the interpreter's optional
        # traceback-renderer spelling suggestions. The source itself is intact.
        reference='''import json,sys
try:
 exec(compile(sys.argv[1],'mapping.py','exec'),{'__name__':'__main__'})
except BaseException as error:
 frames=[]
 trace=error.__traceback__
 while trace is not None:
  if trace.tb_frame.f_code.co_filename=='mapping.py':frames.append((str(trace.tb_lineno),trace.tb_frame.f_code.co_name))
  trace=trace.tb_next
 print(json.dumps({'message':type(error).__name__+': '+str(error),'frames':frames}),file=sys.stderr)
 sys.exit(1)
'''
        references=[subprocess.run([sys.executable,'-I','-S','-c',reference,source],input=data,
                    text=True,capture_output=True,timeout=10)for data in inputs]
        with tempfile.TemporaryDirectory(prefix='pytors-mapping-')as directory:
            for mode in('i64','i128','bigint'):
                if integer_policy:
                    from wrapping_reference import execute
                    selected=[execute(source,mode,data)for data in inputs]
                else:selected=references
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM selected')):
                    result=transpile(source,TranspileOptions(integer=mode,filename='mapping.py',optimize=optimize))
                self.assertTrue(result.success,result.diagnostics)
                self.assertLess(len(result.rust_source.encode()),512*1024)
                path=Path(directory)/(mode+'.rs');path.write_text(result.rust_source)
                for release in(False,True):
                    binary=path.with_name(mode+str(release))
                    build=subprocess.run(['rustc','--crate-name','mapping','--edition=2021',
                        *(['-O']if release else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    for data,expected in zip(inputs,selected):
                        with self.subTest(mode=mode,release=release,data=data[:100]):
                            actual=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=10,
                                env={**os.environ,'PATH':'/no-python-runtime','PYTHONPATH':'/unavailable'})
                            self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                            if expected.returncode:
                                exception=json.loads(expected.stderr)
                                self.assertEqual(actual.stderr.splitlines()[-1],exception['message'])
                                frames=r'File ".*?", line (\d+), in ([^\n]+)'
                                self.assertEqual(re.findall(frames,actual.stderr),[tuple(item)for item in exception['frames']])
                            else:self.assertEqual(actual.stderr,'')

    def test_head_middle_tail_delete_reinsert_and_mapping_consumers(self):
        self.compare('''d={1:10,2:20,3:30,4:40}
del d[2]
d[2]=200
del d[1],d[4]
d[5]=50
print(d,list(d),list(d.items()),list(d.values()))
print(len(d),sum(d),sum(d.values()),2 in d,1 in d)
del d[3],d[2],d[5]
print(d,len(d),bool(d))
d[7]=70
print(d)
''')

    def test_bool_integer_equal_keys_keep_original_key_and_reinsert_identity(self):
        self.compare('''d={True:10,2:20,False:30}
d[1]+=1
print(d)
del d[1]
d[1]=100
del d[0]
d[False]=300
print(d,list(d.items()))
d[False]+=(d.clear(),5)[1]
print(d)
''')

    def test_text_tuple_and_runtime_tuple_keys(self):
        self.compare('''d={'first':1,'middle':2,'last':3}
del d['middle']
d['middle']=7
print(d,list(d.items()))
p={(1,'a'):2,(2,'b'):3}
del p[(1,'a')]
p[(1,'a')]=8
print(p)
key=tuple([1,2])
q={key:5,tuple([2,3]):7}
del q[tuple([1,2])]
q[tuple([1,2])]=9
print(q)
''')

    def test_multiple_targets_stop_at_first_error_and_keys_run_once(self):
        self.compare('''def mark(label,key):
 print(label)
 return key
d={1:2,3:4}
first,second=map(int,input().split())
print('before')
del d[mark('first',first)],d[mark('second',second)]
print(d)
''',('1 3\n','2 3\n','1 2\n','1 1\n'))

    def test_missing_tuple_and_text_key_error_messages(self):
        self.compare("d={'known':1}\ndel d[input()]\n",("absent\n","a'b\n","known\n"))
        self.compare("d={(1,'a'):2}\ndel d[(int(input()),'a')]\n",('1\n','2\n'))

    def test_unbound_receiver_lookup_precedes_key_effects(self):
        self.compare('''def key():
 print('key')
 return 1
if int(input()):d={1:2}
del d[key()]
print(d)
''',('0\n','1\n'))
        self.compare('''def key():
 print('key')
 return 1
def run(flag):
 if flag:d={1:2}
 del d[key()]
 print(d)
run(int(input()))
''',('0\n','1\n'))

    def test_key_can_clear_dictionary_before_deletion_borrows_it(self):
        self.compare("d={1:2}\nprint('before')\ndel d[(d.clear(),1)[1]]\nprint(d)\n")

    def test_owned_dictionary_producer_runs_once_before_key(self):
        self.compare('''def make():
 print('make')
 return {1:2}
def key():
 print('key')
 return int(input())
del make()[key()]
print('done')
''',('1\n','2\n'))

    def test_augmented_get_precedes_rhs_and_store_observes_rhs_clear(self):
        self.compare('''def right():
 print('rhs')
 return 7
d={1:10}
print('before')
d[int(input())]+=right()
print(d)
d[1]+=(d.clear(),3)[1]
print(d)
''',('1\n','2\n'))
        self.compare("d={}\nprint('before')\nd[1]+=(print('wrong rhs'),7)[1]\n")

    def test_augmented_numeric_operations_follow_selected_integer_mode(self):
        self.compare('''d={1:int(input())}
d[1]+=3
d[1]-=1
d[1]*=2
d[1]//=3
d[1]%=5
d[1]**=2
d[1]<<=3
d[1]>>=2
d[1]|=2
d[1]&=15
d[1]^=3
print(d)
''',('0\n','-8\n','19\n'))

    def test_random_update_delete_clear_churn_against_python_order(self):
        source='''d={}
for _ in range(int(input())):
 operation,key,value=map(int,input().split())
 if operation==0:d[key]=value
 elif operation==1:del d[key]
 elif operation==2:d[key]+=value
 else:d.clear()
 print(len(d),sum(d.values()),list(d.items()))
'''
        rng=random.Random(2026102941);state={};operations=[]
        for _ in range(400):
            action=rng.randrange(10)
            if action<5 or not state:
                key=rng.randrange(12);value=rng.randrange(-100,101);state[key]=value;operation=0
            elif action<8:
                key=rng.choice(tuple(state));value=0;del state[key];operation=1
            elif action==8:
                key=rng.choice(tuple(state));value=rng.randrange(-20,21);state[key]+=value;operation=2
            else:key=value=0;state.clear();operation=3
            operations.append(f'{operation} {key} {value}\n')
        self.compare(source,(f'{len(operations)}\n'+''.join(operations),))

    def test_integer_wraps_after_each_augmented_result_and_key_expression(self):
        self.compare('''width=int(input())
d={1:(1<<(width-1))-1}
d[1]+=1
print(d)
d[1]**=2
d[1]-=1
d[1]<<=width+1
print(d)
del d[1]
d[(1<<width)+1]=-(1<<(width-1))
print(d)
''',('64\n','128\n'),integer_policy=True)

    def test_deleted_and_reinserted_values_use_the_solved_finite_value_type(self):
        self.compare('''d={1:2,2:3}
del d[1]
d[1]='word'
d[3]=None
print(d,list(d.items()))
del d[2]
d[2]='last'
print(d)
''')

    def test_without_pruning_both_storage_profiles_compile(self):
        self.compare('d={1:2,3:4}\nprint(d)\n',optimize=False)
        self.compare('d={1:2,3:4}\ndel d[1]\nprint(d)\n',optimize=False)

    def test_function_local_deletion_selects_ordered_storage_across_calls(self):
        source='''def erase(n):
 d={}
 for i in range(n):d[i]=i
 for i in range(n):del d[i]
 return len(d)
print(erase(int(input())))
'''
        self.compare(source,('0\n','1\n','50\n','2000\n'))
        for mode in('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(integer=mode))
            self.assertTrue(result.success,result.diagnostics)
            self.assertIn('struct NativeOrderedEntries',result.rust_source)
            self.assertNotIn('index.values_mut()',result.rust_source)

    def test_deletion_storage_reuses_slots_and_drops_removed_payloads(self):
        from py2fastrust.native_ordered_entries import ORDERED_HELPERS
        rust=ORDERED_HELPERS+'''
use std::rc::Rc;
use std::cell::Cell;
struct Item(Rc<Cell<usize>>);
impl Drop for Item{fn drop(&mut self){self.0.set(self.0.get()+1);}}
fn main(){
 let count=Rc::new(Cell::new(0));let mut entries=NativeOrderedEntries::new();
 let a=entries.insert(Item(count.clone())).unwrap();
 let b=entries.insert(Item(count.clone())).unwrap();
 let c=entries.insert(Item(count.clone())).unwrap();
 drop(entries.remove(b));assert_eq!(count.get(),1);
 for _ in 0..100000{let slot=entries.insert(Item(count.clone())).unwrap();drop(entries.remove(slot));}
 assert!(entries.slots.len()<=4);assert_eq!(entries.len(),2);
 let mut iter=entries.iter();assert!(iter.next_back().is_some());assert!(iter.next().is_some());assert!(iter.next().is_none());
 assert!(entries.slots[a].value.is_some());assert!(entries.slots[c].value.is_some());
 entries.clear();assert_eq!(count.get(),100003);assert!(entries.is_empty());
 let mut integers=NativeOrderedEntries::new();integers.insert(1).unwrap();integers.insert(2).unwrap();integers.insert(3).unwrap();
 let mut owned=integers.into_iter();assert_eq!(owned.next_back(),Some(3));assert_eq!(owned.next(),Some(1));assert_eq!(owned.next_back(),Some(2));assert_eq!(owned.next(),None);
}
'''
        with tempfile.TemporaryDirectory(prefix='pytors-order-slots-')as directory:
            path=Path(directory)/'main.rs';path.write_text(rust)
            for optimized in(False,True):
                binary=path.with_name('main'+str(optimized))
                build=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(path),'-o',str(binary)],capture_output=True,text=True)
                self.assertEqual(build.returncode,0,build.stderr)
                run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
                self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
