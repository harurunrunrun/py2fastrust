"""Source context managers keep cleanup, control flow and exception chains."""
from pathlib import Path
import os,re,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions

CASES = {'normal_value_and_shared_events': {'main.py': 'events=[]\n'
                                               'class Guard:\n'
                                               ' def '
                                               '__init__(self,name,suppress=False):self.name=name;self.suppress=suppress\n'
                                               ' def __enter__(self):\n'
                                               "  events.append('enter'+self.name)\n"
                                               '  return self.name\n'
                                               ' def __exit__(self,kind,value,traceback):\n'
                                               "  events.append('exit'+self.name)\n"
                                               '  return self.suppress\n'
                                               "with Guard('A')as value:events.append(value)\n"
                                               'print(value,events)\n'},
 'nested_return_break_continue': {'main.py': 'events=[]\n'
                                             'class Guard:\n'
                                             ' def '
                                             '__init__(self,name,suppress=False):self.name=name;self.suppress=suppress\n'
                                             ' def __enter__(self):\n'
                                             "  events.append('enter'+self.name)\n"
                                             '  return self.name\n'
                                             ' def __exit__(self,kind,value,traceback):\n'
                                             "  events.append('exit'+self.name)\n"
                                             '  return self.suppress\n'
                                             'def run():\n'
                                             ' for index in range(4):\n'
                                             "  with Guard('A'):\n"
                                             "   with Guard('B'):\n"
                                             '    if index==0:continue\n'
                                             '    if index==2:break\n'
                                             '    events.append(index)\n'
                                             " with Guard('R'):return events\n"
                                             'result=run()\n'
                                             'print(result is events,events)\n'},
 'body_error_suppression_without_metadata': {'main.py': 'events=[]\n'
                                                        'class Guard:\n'
                                                        ' def '
                                                        '__init__(self,name,suppress=False):self.name=name;self.suppress=suppress\n'
                                                        ' def __enter__(self):\n'
                                                        "  events.append('enter'+self.name)\n"
                                                        '  return self.name\n'
                                                        ' def __exit__(self,kind,value,traceback):\n'
                                                        "  events.append('exit'+self.name)\n"
                                                        '  return self.suppress\n'
                                                        "with Guard('A',True):\n"
                                                        " events.append('body')\n"
                                                        ' 1//0\n'
                                                        "events.append('after')\n"
                                                        'print(events)\n'},
 'body_error_propagation_runs_exit': {'main.py': 'events=[]\n'
                                                 'class Guard:\n'
                                                 ' def '
                                                 '__init__(self,name,suppress=False):self.name=name;self.suppress=suppress\n'
                                                 ' def __enter__(self):\n'
                                                 "  events.append('enter'+self.name)\n"
                                                 '  return self.name\n'
                                                 ' def __exit__(self,kind,value,traceback):\n'
                                                 "  events.append('exit'+self.name)\n"
                                                 '  return self.suppress\n'
                                                 'def body():\n'
                                                 " with Guard('A'):\n"
                                                 "  print('body')\n"
                                                 '  1//0\n'
                                                 'body()\n'},
 'exit_error_on_normal_body': {'main.py': 'class Guard:\n'
                                          " def __enter__(self):print('enter')\n"
                                          ' def __exit__(self,a,b,c):\n'
                                          "  print('exit')\n"
                                          '  1//0\n'
                                          "with Guard():print('body')\n"},
 'exit_error_chains_body_error': {'main.py': 'class Guard:\n'
                                             ' def __enter__(self):return self\n'
                                             ' def __exit__(self,a,b,c):\n'
                                             "  print('exit')\n"
                                             '  9//0\n'
                                             'def run():\n'
                                             ' with Guard():\n'
                                             "  print('body')\n"
                                             '  [0][4]\n'
                                             'run()\n'},
 'enter_error_does_not_call_exit': {'main.py': 'class Guard:\n'
                                               ' def __enter__(self):\n'
                                               "  print('enter')\n"
                                               '  return 1//0\n'
                                               " def __exit__(self,a,b,c):print('wrong exit')\n"
                                               "with Guard():print('wrong body')\n"},
 'target_unpack_error_can_be_suppressed': {'main.py': 'class Guard:\n'
                                                      ' def __enter__(self):return [1]\n'
                                                      ' def __exit__(self,a,b,c):\n'
                                                      "  print('exit')\n"
                                                      '  return True\n'
                                                      "with Guard()as(a,b):print('wrong body')\n"
                                                      "print('after')\n"},
 'multiple_items_second_enter_fails': {'main.py': 'class First:\n'
                                                  " def __enter__(self):print('first enter');return 3\n"
                                                  " def __exit__(self,a,b,c):print('first exit')\n"
                                                  'class Second:\n'
                                                  " def __enter__(self):print('second enter');return "
                                                  '1//0\n'
                                                  " def __exit__(self,a,b,c):print('wrong second "
                                                  "exit')\n"
                                                  "with First()as left,Second()as right:print('wrong "
                                                  "body')\n"},
 'loop_inside_outer_manager_breaks_locally': {'main.py': 'events=[]\n'
                                                         'class Guard:\n'
                                                         ' def '
                                                         '__init__(self,name,suppress=False):self.name=name;self.suppress=suppress\n'
                                                         ' def __enter__(self):\n'
                                                         "  events.append('enter'+self.name)\n"
                                                         '  return self.name\n'
                                                         ' def __exit__(self,kind,value,traceback):\n'
                                                         "  events.append('exit'+self.name)\n"
                                                         '  return self.suppress\n'
                                                         "with Guard('outer'):\n"
                                                         ' for i in range(3):\n'
                                                         "  with Guard('inner'):\n"
                                                         '   if i==1:break\n'
                                                         '   events.append(i)\n'
                                                         " events.append('after loop')\n"
                                                         'print(events)\n'},
 'return_expression_error_runs_exit': {'main.py': 'events=[]\n'
                                                  'class Guard:\n'
                                                  ' def '
                                                  '__init__(self,name,suppress=False):self.name=name;self.suppress=suppress\n'
                                                  ' def __enter__(self):\n'
                                                  "  events.append('enter'+self.name)\n"
                                                  '  return self.name\n'
                                                  ' def __exit__(self,kind,value,traceback):\n'
                                                  "  events.append('exit'+self.name)\n"
                                                  '  return self.suppress\n'
                                                  'def run():\n'
                                                  " with Guard('return'):\n"
                                                  '  return 7//0\n'
                                                  'run()\n'},
 'return_retains_mutable_payload': {'main.py': 'class Guard:\n'
                                               ' def __init__(self,items):self.items=items\n'
                                               ' def __enter__(self):return self.items\n'
                                               ' def __exit__(self,a,b,c):self.items.append(4)\n'
                                               'def run(items):\n'
                                               ' with Guard(items)as value:return value\n'
                                               'items=[1]\n'
                                               'print(run(items)is items,items)\n'},
 'variadic_exit_erases_only_unused_pack': {'main.py': 'class Guard:\n'
                                                      " def __enter__(self):print('enter')\n"
                                                      ' def '
                                                      "__exit__(self,*ignored):print('exit');return "
                                                      'True\n'
                                                      'with Guard():1//0\n'
                                                      "print('after')\n"},
 'exit_updates_global_binding': {'main.py': 'value=3\n'
                                            'class Guard:\n'
                                            ' def __enter__(self):return value\n'
                                            ' def __exit__(self,a,b,c):\n'
                                            '  global value\n'
                                            "  value='changed'\n"
                                            'def run():\n'
                                            ' with Guard()as old:print(old)\n'
                                            ' print(value)\n'
                                            'run()\n'},
 'direct_exit_call_still_evaluates_arguments': {'main.py': "def mark():print('argument');return [1]\n"
                                                           'class Guard:\n'
                                                           " def __enter__(self):print('enter')\n"
                                                           " def __exit__(self,a,b,c):print('exit')\n"
                                                           'g=Guard()\n'
                                                           'g.__exit__(mark(),False,None)\n'
                                                           'with g:pass\n'},
 'exit_binding_error_chains_body_error': {'main.py': 'class Guard:\n'
                                                     ' def __enter__(self):return 3\n'
                                                     " def __exit__(self,a):print('wrong exit body')\n"
                                                     'with Guard():1//0\n'},
 'while_continue_and_break': {'main.py': 'events=[]\n'
                                         'class Guard:\n'
                                         ' def '
                                         '__init__(self,name,suppress=False):self.name=name;self.suppress=suppress\n'
                                         ' def __enter__(self):\n'
                                         "  events.append('enter'+self.name)\n"
                                         '  return self.name\n'
                                         ' def __exit__(self,kind,value,traceback):\n'
                                         "  events.append('exit'+self.name)\n"
                                         '  return self.suppress\n'
                                         'i=0\n'
                                         'while i<5:\n'
                                         " with Guard('A'):\n"
                                         '  i+=1\n'
                                         '  if i==1:continue\n'
                                         '  if i==4:break\n'
                                         '  events.append(i)\n'
                                         'print(i,events)\n'},
 'exit_keyword_only_default_kept_live': {'main.py': 'class Guard:\n'
                                                    " def __enter__(self):print('enter')\n"
                                                    ' def __exit__(self,a,b,c,*,suppress=True):\n'
                                                    "  print('exit',suppress)\n"
                                                    '  return suppress\n'
                                                    'with Guard():1//0\n'
                                                    "print('after')\n"},
 'nested_exit_failures_chain': {'main.py': 'class Inner:\n'
                                           ' def __enter__(self):return self\n'
                                           ' def __exit__(self,a,b,c):[1][9]\n'
                                           'class Outer:\n'
                                           ' def __enter__(self):return self\n'
                                           ' def __exit__(self,a,b,c):1//0\n'
                                           'with Outer():\n'
                                           " with Inner():int('bad')\n"},
 'suppressed_assignment_keeps_unbound_local': {'main.py': 'class Guard:\n'
                                                          ' def __enter__(self):return self\n'
                                                          ' def __exit__(self,a,b,c):return True\n'
                                                          'def run():\n'
                                                          ' with Guard():value=1//0\n'
                                                          ' return value\n'
                                                          'run()\n'},
 'multiple_items_continue_and_return': {'main.py': 'events=[]\n'
                                                   'class Guard:\n'
                                                   ' def __init__(self,n):self.n=n\n'
                                                   ' def __enter__(self):events.append(self.n)\n'
                                                   ' def __exit__(self,a,b,c):events.append(-self.n)\n'
                                                   'def run():\n'
                                                   ' for i in range(3):\n'
                                                   '  with Guard(1),Guard(2):\n'
                                                   '   if i==0:continue\n'
                                                   '   if i==2:return events\n'
                                                   '   events.append(7)\n'
                                                   'print(run(),events)\n'},
 'suppressed_second_enter_leaves_target_unbound': {'main.py': 'class Outer:\n'
                                                              ' def __enter__(self):return 3\n'
                                                              " def __exit__(self,a,b,c):print('exit "
                                                              "outer');return True\n"
                                                              'class Inner:\n'
                                                              ' def __enter__(self):return 1//0\n'
                                                              " def __exit__(self,a,b,c):print('wrong "
                                                              "inner exit')\n"
                                                              'with Outer()as left,Inner()as '
                                                              "right:print('wrong body')\n"
                                                              'print(left)\n'
                                                              'print(right)\n'},
 'object_exit_result_uses_default_truth': {'main.py': 'class Guard:\n'
                                                      ' def __enter__(self):return 3\n'
                                                      ' def __exit__(self,a,b,c):return self\n'
                                                      'with Guard():1//0\n'
                                                      "print('after')\n"},
 'saved_exit_alias_and_expanded_call': {'main.py': 'events=[]\n'
                                                   'class Guard:\n'
                                                   " def __enter__(self):events.append('enter')\n"
                                                   " def __exit__(self,a,b,c):events.append('exit')\n"
                                                   'g=Guard()\n'
                                                   'saved=g.__exit__\n'
                                                   "with g:events.append('body')\n"
                                                   'saved(*[1,2,3])\n'
                                                   'print(events)\n'},
 'recursive_factorial_with_shared_counts': {'main.py': 'class Scope:\n'
                                                       ' def __init__(self,counts):self.counts=counts\n'
                                                       ' def __enter__(self):self.counts[0]+=1\n'
                                                       ' def __exit__(self,a,b,c):self.counts[1]+=1\n'
                                                       'def factorial(n,counts):\n'
                                                       ' with Scope(counts):\n'
                                                       '  if n<2:return 1\n'
                                                       '  return n*factorial(n-1,counts)\n'
                                                       'counts=[0,0]\n'
                                                       'print(factorial(12,counts),counts)\n'},
 'variadic_exit_alias_expansion': {'main.py': 'events=[]\n'
                                              'class Guard:\n'
                                              ' def __enter__(self):events.append(1)\n'
                                              ' def __exit__(self,*ignored):events.append(2)\n'
                                              'g=Guard()\n'
                                              'saved=g.__exit__\n'
                                              'saved(*[1,2,3])\n'
                                              'with g:events.append(3)\n'
                                              'print(events)\n'}}

UNSUPPORTED = {'observed_exception_in_nested_closure_guard': 'class Guard:\n'
                                               ' def __enter__(self):return self\n'
                                               ' def __exit__(self,kind,value,traceback):\n'
                                               '  def observe():return kind\n'
                                               '  print(observe())\n'
                                               'with Guard():pass\n',
 'observed_exception_in_nested_default_guard': 'class Guard:\n'
                                               ' def __enter__(self):return self\n'
                                               ' def __exit__(self,kind,value,traceback):\n'
                                               '  def observe(saved=kind):return saved\n'
                                               '  print(observe())\n'
                                               'with Guard():pass\n',
 'frame_reflection_guard': 'class Guard:\n'
                           ' def __enter__(self):return self\n'
                           ' def __exit__(self,kind,value,traceback):print(locals())\n'
                           'with Guard():pass\n',
 'lazy_child_annotation_capture_guard': 'class Guard:\n'
                                        ' def __enter__(self):return self\n'
                                        ' def __exit__(self,kind,value,traceback):\n'
                                        '  def child(saved:kind):return 3\n'
                                        '  print(child.__annotations__)\n'
                                        'with Guard():pass\n'}


def canonical_error(stderr):
    return [line for line in stderr.splitlines()if line.startswith(('Traceback (most recent call last):','  File ','During handling of the above exception, another exception occurred:'))or re.match(r'^[A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception|Iteration)(?::|$)',line)]


class ContextManagerBoundaries(unittest.TestCase):
    def test_observed_exception_payloads_are_positioned(self):
        for name,source in UNSUPPORTED.items():
            for mode in ('i64','i128','bigint'):
                with self.subTest(case=name,integer=mode):
                    result=transpile(source,TranspileOptions(filename='main.py',integer=mode))
                    self.assertFalse(result.success)
                    self.assertEqual(result.diagnostics[0].code,'E006')
                    self.assertIn('exception',result.diagnostics[0].message)
                    self.assertGreater(result.diagnostics[0].line,0)

    def test_no_with_program_retains_small_error_layout(self):
        result=transpile('class Box:\n def get(self):return 3\nprint(Box().get())\n')
        self.assertTrue(result.success,result.diagnostics)
        self.assertNotIn('ClassWithFlow',result.rust_source)
        self.assertNotIn('context:Option<Box<NativeError>>',result.rust_source)
        self.assertNotIn('class_with_render_error',result.rust_source)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class ContextManagerExecutionTests(unittest.TestCase):
    def exercise(self,files):
        with tempfile.TemporaryDirectory(prefix='pytors-with-')as directory:
            root=Path(directory)
            for name,source in files.items():(root/name).write_text(source)
            main=root/'main.py'
            expected=subprocess.run([sys.executable,'-S',str(main)],capture_output=True,text=True,timeout=15)
            for mode in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy code generation entered')):
                    result=transpile(main.read_text(),TranspileOptions(filename=str(main),integer=mode))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser','UNICODE LICENSE V3'):self.assertNotIn(marker,result.rust_source)
                rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    with self.subTest(integer=mode,optimized=optimized):
                        binary=root/(mode+('_release'if optimized else'_debug'))
                        build=subprocess.run(['rustc','--edition=2021','--crate-name','native_context_manager_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                        self.assertEqual(build.returncode,0,build.stderr)
                        actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                        self.assertEqual(actual.stdout,expected.stdout)
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                        self.assertEqual(canonical_error(actual.stderr),canonical_error(expected.stderr))


def _execution(files):
    def test(self):self.exercise(files)
    return test


CASES.update({'multiline_enter_failure': {'main.py': 'class Guard:\n'
                                        ' def __enter__(self):return 1//0\n'
                                        " def __exit__(self,a,b,c):print('wrong exit')\n"
                                        'with (\n'
                                        ' Guard()\n'
                                        ' as value\n'
                                        '):\n'
                                        ' pass\n'},
 'multiline_exit_failure': {'main.py': 'class Guard:\n'
                                       ' def __enter__(self):return 3\n'
                                       ' def __exit__(self,a,b,c):return 1//0\n'
                                       'with (\n'
                                       ' Guard()\n'
                                       ' as value\n'
                                       '):\n'
                                       ' print(value)\n'},
 'multiline_unpack_failure': {'main.py': 'class Guard:\n'
                                         ' def __enter__(self):return [1]\n'
                                         " def __exit__(self,a,b,c):print('exit')\n"
                                         'with (\n'
                                         ' Guard()\n'
                                         ' as (left,right)\n'
                                         '):\n'
                                         ' pass\n'}})

for _name,_files in CASES.items():setattr(ContextManagerExecutionTests,'test_'+_name,_execution(_files))
