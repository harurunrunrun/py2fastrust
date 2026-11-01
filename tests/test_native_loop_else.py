"""Native loop exhaustion preserves transfer, namespace and cleanup semantics."""
from pathlib import Path
import os,re,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions

CASES = [('for_exhaustion_0', 'for i in range(3):print(i,end="|")\nelse:print("else")\nprint(i)\n', ''),
 ('for_empty_0', 'x=9\nfor x in []:print("body")\nelse:print("empty",x)\n', ''),
 ('for_break_0',
  'for i in range(4):\n print(i,end="|")\n if i==1:break\nelse:print("else")\nprint("done",i)\n',
  ''),
 ('for_continue_0', 'for i in range(4):\n if i%2==0:continue\n print(i,end="|")\nelse:print("else",i)\n', ''),
 ('while_exhaustion_0', 'i=0\nwhile i<3:\n print(i,end="|")\n i+=1\nelse:print("else",i)\n', ''),
 ('while_break_0', 'i=0\nwhile i<3:\n i+=1\n if i==2:break\nelse:print("else")\nprint(i)\n', ''),
 ('while_continue_0',
  'i=0\nwhile i<4:\n i+=1\n if i%2:continue\n print(i,end="|")\nelse:print("else",i)\n',
  ''),
 ('while_false_0', 'i=7\nwhile False:print("body")\nelse:print("else",i)\n', ''),
 ('while_true_break_0', 'i=0\nwhile True:\n i+=1\n if i==3:break\nelse:print("impossible")\nprint(i)\n', ''),
 ('nested_break_0',
  'for i in range(3):\n'
  ' for j in range(4):\n'
  '  if j==1:break\n'
  ' else:print("inner else")\n'
  ' print(i,j)\n'
  'else:print("outer else")\n',
  ''),
 ('break_in_inner_else_targets_outer_0',
  'for i in range(3):\n'
  ' for j in []:print(j)\n'
  ' else:\n'
  '  print("inner else")\n'
  '  break\n'
  'else:print("outer else")\n'
  'print("done",i)\n',
  ''),
 ('continue_in_inner_else_targets_outer_0',
  'for i in range(3):\n'
  ' for j in []:print(j)\n'
  ' else:\n'
  '  print(i,end="|")\n'
  '  continue\n'
  ' print("after")\n'
  'else:print("outer else")\n',
  ''),
 ('return_skips_else_0',
  'def find(a):\n for x in a:\n  if x==3:return x\n else:return 9\nprint(find([1,3,4]),find([]))\n',
  ''),
 ('break_and_else_bind_different_types_0',
  'for x in range(int(input())):\n y="break"\n break\nelse:y=7\nprint(y)\n',
  '0\n'),
 ('break_and_else_bind_different_types_1',
  'for x in range(int(input())):\n y="break"\n break\nelse:y=7\nprint(y)\n',
  '3\n'),
 ('else_assignment_follows_continue_0',
  'x=2\nfor i in range(3):\n x+=i\n continue\nelse:x*=3\nprint(x)\n',
  ''),
 ('loop_else_reads_unbound_target_0', 'for x in range(int(input())):pass\nelse:print(x)\n', '0\n'),
 ('loop_else_reads_unbound_target_1', 'for x in range(int(input())):pass\nelse:print(x)\n', '3\n'),
 ('class_while_else_0',
  'class Box:\n'
  ' def __init__(self):self.n=0\n'
  ' def f(self):\n'
  '  while self.n<3:\n'
  '   self.n+=1\n'
  '   if self.n==2:break\n'
  '  else:return 99\n'
  '  return self.n\n'
  'print(Box().f())\n',
  ''),
 ('break_runs_with_cleanup_0',
  'class Manager:\n'
  ' def __enter__(self):print("enter")\n'
  ' def __exit__(self,t,e,b):print("exit");return False\n'
  'for i in range(2):\n'
  ' with Manager():break\n'
  'else:print("else")\n'
  'print("done")\n',
  ''),
 ('continue_runs_with_cleanup_0',
  'class Manager:\n'
  ' def __enter__(self):print("enter")\n'
  ' def __exit__(self,t,e,b):print("exit");return False\n'
  'for i in range(2):\n'
  ' with Manager():continue\n'
  'else:print("else")\n',
  ''),
 ('cleanup_error_cancels_break_0',
  'class Outer:\n'
  ' def __enter__(self):return None\n'
  ' def __exit__(self,t,e,b):return True\n'
  'class Inner:\n'
  ' def __enter__(self):return None\n'
  ' def __exit__(self,t,e,b):return 1//0\n'
  'for i in range(2):\n'
  ' with Outer():\n'
  '  with Inner():break\n'
  ' print("continued",i)\n'
  'else:print("else")\n',
  ''),
 ('cleanup_error_cancels_continue_0',
  'class Outer:\n'
  ' def __enter__(self):return None\n'
  ' def __exit__(self,t,e,b):return True\n'
  'class Inner:\n'
  ' def __enter__(self):return None\n'
  ' def __exit__(self,t,e,b):return 1//0\n'
  'for i in range(2):\n'
  ' with Outer():\n'
  '  with Inner():continue\n'
  ' print("continued",i)\n'
  'else:print("else")\n',
  ''),
 ('outer_with_inner_loop_break_0',
  'class Manager:\n'
  ' def __enter__(self):return None\n'
  ' def __exit__(self,t,e,b):return False\n'
  'with Manager():\n'
  ' for i in range(3):\n'
  '  if i==1:break\n'
  ' else:print("inner else")\n'
  ' print(i)\n',
  ''),
 ('body_error_skips_else_0', 'for i in range(3):\n print(i,end="|")\n x=1//0\nelse:print("else")\n', ''),
 ('else_error_has_original_frame_0', 'def f():\n for i in []:pass\n else:return 1//0\nprint(f())\n', ''),
 ('saved_iterator_break_position',
  'it=iter([1,2,3])\nfor x in it:\n print(x)\n break\nelse:print("else")\nprint(next(it),next(it))\n',
  ''),
 ('strict_zip_error_skips_else',
  'for x,y in zip([1,2],[3],strict=True):print(x,y)\nelse:print("else")\n',
  ''),
 ('recursive_loop_else',
  'def f(n):\n'
  ' if n<=0:return 0\n'
  ' for i in range(n):\n'
  '  if i==n-1:break\n'
  ' else:return -1\n'
  ' return 1+f(n-1)\n'
  'print(f(6))\n',
  ''),
 ('last_condition_effects_before_else',
  'seen=[]\n'
  'def condition(i):\n'
  ' seen.append(i)\n'
  ' return i<2\n'
  'i=0\n'
  'while condition(i):i+=1\n'
  'else:print(seen,i)\n',
  ''),
 ('false_loop_omits_unreached_body', 'while False:\n missing()\nelse:print("else")\n', ''),
 ('true_loop_omits_unreached_else', 'while True:break\nelse:missing()\nprint("after")\n', '')]


def canonical_error(stderr):
    return [line for line in stderr.splitlines()if line.startswith(('Traceback (most recent call last):','  File ','During handling of the above exception, another exception occurred:'))or re.match(r'^[A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception|Iteration)(?::|$)',line)]


class LoopElseSelectionTests(unittest.TestCase):
    def test_reached_else_selects_frames_before_codegen(self):
        # The public transpile entry is exercised with the legacy emitter disabled.
        with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy emitter entered')):
            result=transpile('for i in range(2):pass\nelse:print(i)\n')
        self.assertTrue(result.success,result.diagnostics)
        self.assertEqual(result.backend,'native')

    def test_no_else_has_no_exhaustion_flag(self):
        result=transpile('class Box:\n def f(self):\n  for i in range(3):\n   if i==1:break\n  return i\nprint(Box().f())\n')
        self.assertTrue(result.success,result.diagnostics)
        self.assertNotIn('=true;',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class LoopElseExecutionTests(unittest.TestCase):
    def exercise(self,source,stdin):
        with tempfile.TemporaryDirectory(prefix='pytors-loop-else-')as directory:
            root=Path(directory);main=root/'main.py';main.write_text(source)
            expected=subprocess.run([sys.executable,'-S',str(main)],input=stdin,capture_output=True,text=True,timeout=15)
            for mode in ('i64','i128','bigint'):
                with self.subTest(integer=mode):
                    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy emitter entered')):
                        result=transpile(source,TranspileOptions(filename=str(main),integer=mode))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.backend,'native')
                    self.assertLess(len(result.rust_source.encode()),512*1024)
                    for marker in ('enum Value','enum Op','struct Runtime','struct PegParser','UNICODE LICENSE V3'):
                        self.assertNotIn(marker,result.rust_source)
                    rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        with self.subTest(optimized=optimized):
                            binary=root/(mode+('_release'if optimized else'_debug'))
                            build=subprocess.run(['rustc','--edition=2021','--crate-name','native_loop_else_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                            self.assertEqual(build.returncode,0,build.stderr)
                            actual=subprocess.run([str(binary)],input=stdin,capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                            self.assertEqual(actual.stdout,expected.stdout)
                            self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                            self.assertEqual(canonical_error(actual.stderr),canonical_error(expected.stderr))


def _execution(source,stdin):
    def test(self):self.exercise(source,stdin)
    return test


for _name,_source,_stdin in CASES:
    setattr(LoopElseExecutionTests,'test_'+_name,_execution(_source,_stdin))
