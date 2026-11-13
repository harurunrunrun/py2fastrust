"""CP-first programs for canonical normal-termination callback semantics."""

CASES={
 'lifo_capture_and_register_return':'''import atexit
def show(a,b=0,*,label='default'):
 print(label,a,b)
print(atexit.register(show,1,b=2,label='first') is show)
atexit.register(show,3,4,label='second')
print('body')
''',
 'module_alias_and_late_global':'''import atexit as endings
value=1
def show():print('value',value)
register=endings.register
register(show)
value=9
print('body')
''',
 'callee_rebinding_keeps_original':'''import atexit
def show():print('old')
atexit.register(show)
def show():print('new')
print('body')
''',
 'mutable_arguments_remain_original_objects':'''import atexit
def show(values,*,prefix):print(prefix,values)
values=[1]
atexit.register(show,values,prefix='saved')
values.append(2)
values=[9]
print('body',values)
''',
 'bound_method_receiver_retained':'''import atexit
class Buffer:
 def __init__(self,name):self.name=name;self.values=[]
 def flush(self):print(self.name,self.values)
def make(name):
 owner=Buffer(name)
 owner.values.append(1)
 atexit.register(owner.flush)
 owner.values.append(2)
make('first')
make('second')
print('body')
''',
 'decorator_returns_same_callable':'''import atexit
@atexit.register
def finish():print('decorated')
print(type(finish).__name__,'body')
''',
 'function_return_then_shutdown':'''import atexit
def finish(value):print('end',value)
def main():
 atexit.register(finish,7)
 print('inside')
 return
main()
print('outside')
''',
 'main_sys_exit_preserves_status':'''import atexit,sys
def finish():print('finished')
atexit.register(finish)
print('body')
sys.exit(3)
print('unreachable')
''',
 'unhandled_main_error_still_runs_callbacks':'''import atexit
def finish():print('finished')
atexit.register(finish)
print('body')
print(1//0)
''',
 'callback_error_continues_in_lifo_order':'''import atexit
def fail():
 print('failure-body')
 raise ValueError('shutdown failed')
def finish(label):print(label)
atexit.register(finish,'oldest')
atexit.register(fail)
atexit.register(finish,'newest')
print('body')
''',
 'callback_system_exit_is_unraisable':'''import atexit,sys
def finish(label):print(label)
def fail():sys.exit(8)
atexit.register(finish,'oldest')
atexit.register(fail)
print('body')
sys.exit(3)
''',
 'main_error_report_precedes_callback_error':'''import atexit
def fail():raise ValueError('callback')
atexit.register(fail)
print('body')
raise RuntimeError('main')
''',
 'callback_binding_errors_are_deferred':'''import atexit
def needs(value):print('called',value)
atexit.register(needs)
print('registered')
''',
 'noncallable_error_after_argument_effects':'''import atexit
def mark(value):print('argument',value);return value
def finish():print('previous')
atexit.register(finish)
atexit.register(mark(7),mark(9),key=mark(11))
print('unreachable')
''',
 'empty_positional_register_error_after_keyword_effects':'''import atexit
def mark():print('argument');return 7
atexit.register(func=mark())
''',
 'snapshot_does_not_run_new_registrations':'''import atexit
def finish(label):print(label)
def add():
 print('adding')
 atexit.register(finish,'newly registered')
atexit.register(finish,'oldest')
atexit.register(add)
print('body')
''',
 'clear_during_callback_keeps_snapshot':'''import atexit
def finish(label):print(label)
def clear():
 print('clearing')
 atexit._clear()
atexit.register(finish,'oldest')
atexit.register(clear)
atexit.register(finish,'newest')
print('body',atexit._ncallbacks())
''',
 'clear_before_termination':'''import atexit
def finish():print('unreachable')
atexit.register(finish)
print(atexit._ncallbacks())
print(atexit._clear(),atexit._ncallbacks())
print('body')
''',
 'nested_local_capture_retained':'''import atexit
def make(start):
 value=start
 def finish():print('captured',value)
 atexit.register(finish)
 value+=3
make(5)
make(20)
print('body')
''',
}

EXTRA_CASES={'duplicate_alias_error_identity': "import atexit\ndef fail():raise ValueError('same')\nsaved=fail\natexit.register(fail)\natexit.register(saved)\ndef other():raise ValueError('different')\natexit.register(other)\nprint('body')\n", 'separate_closure_errors': "import atexit\ndef create(value):\n def fail():raise ValueError(value)\n return fail\nfirst=create('first')\nsecond=create('second')\natexit.register(first)\natexit.register(second)\natexit.register(first)\nprint('body')\n", 'bound_error_alias_identity': "import atexit\nclass Buffer:\n def __init__(self,value):self.value=value\n def fail(self):raise ValueError(self.value)\nfirst=Buffer('first');second=Buffer('second')\nsaved=first.fail\natexit.register(saved)\natexit.register(second.fail)\natexit.register(saved)\nprint('body')\n", 'primitive_builtin_callback': "import atexit\nprint(atexit.register(print,'last',sep=':') is print)\natexit.register(print,'before','last',sep=':')\nprint('body')\n", 'keyword_order_at_registration': "import atexit\ndef mark(label,value):print(label);return value\ndef finish(*values,**options):print(values,options)\natexit.register(finish,mark('first',1),mark('second',2),z=mark('z',3),a=mark('a',4))\nprint('body')\n", 'starred_registration': "import atexit\ndef arguments():print('arguments');return ('later',7)\ndef options():print('keywords');return {'sep':':'}\natexit.register(print,*arguments(),**options())\nprint('body')\n", 'callback_creation_defaults_once': "import atexit\ndef mark():print('default');return [1]\ndef finish(values=mark()):print(values)\natexit.register(finish)\nprint('body')\n", 'callback_changes_later_global': "import atexit\nvalue=1\ndef show():print('value',value)\ndef change():\n global value\n value+=7\n print('changed')\natexit.register(show)\natexit.register(change)\nprint('body')\n", 'callback_clear_register_count': "import atexit\ndef show():print('oldest')\ndef change():\n print('count',atexit._ncallbacks())\n atexit._clear()\n print('cleared',atexit._ncallbacks())\n atexit.register(show)\n print('added',atexit._ncallbacks())\natexit.register(show)\natexit.register(change)\nprint('body')\n", 'no_handlers': 'import atexit\nprint(atexit._ncallbacks())\nprint(atexit._clear())\n', 'empty_arity_effect': "import atexit\ndef mark():print('argument');return 1\natexit._clear(mark())\n", 'counter_keyword_effect': "import atexit\ndef mark():print('argument');return 1\natexit._ncallbacks(value=mark())\n", 'unsupported_unregister': "import atexit\ndef finish():print('end')\natexit.register(finish)\natexit.unregister(finish)\n", 'unsupported_custom_callable': "import atexit\nclass Action:\n def __call__(self):print('end')\natexit.register(Action())\n", 'unsupported_custom_receiver_repr': "import atexit\nclass Action:\n def __repr__(self):return 'custom'\n def finish(self):print('end')\natexit.register(Action().finish)\n", 'unsupported_iterator_payload': 'import atexit\ndef show(values):print(next(values))\nvalues=iter([1,2])\natexit.register(show,values)\n', 'unsupported_lexical_cycle': 'import atexit\ndef create():\n values=[]\n def finish():print(len(values))\n values.append(finish)\n atexit.register(finish)\ncreate()\n', 'unsupported_collected_payload': 'import atexit\nclass Node:\n def __init__(self):self.next=self\n def finish(self):print(self is self.next)\natexit.register(Node().finish)\n', 'unsupported_callback_id': "import atexit\ndef fail():raise ValueError('failed')\natexit.register(fail)\nprint(id(fail))\n", 'unsupported_callback_repr': "import atexit\ndef fail():raise ValueError('failed')\natexit.register(fail)\nprint(repr(fail))\n"}

import ast
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


def normalized_stderr(value):
    """Keep error/header/frame order, elide only CP's source-line decorations.

    Pointer values vary between processes. Their equivalence classes are
    retained, so two aliases must print the same address and independent live
    callables/receivers must still have different addresses.
    """
    identities={}
    result=[]
    for line in value.splitlines():
        if line.startswith(('    ','      ')):continue
        if line.startswith('Exception ignored in atexit callback '):
            def identity(match):
                return identities.setdefault(match.group(),'<address-'+str(len(identities))+'>')
            line=re.sub(r'0x[0-9a-fA-F]+',identity,line)
        result.append(line)
    return '\n'.join(result)


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class AtexitExecutionTests(unittest.TestCase):
    def compare(self,source,*,merged=False):
        with tempfile.TemporaryDirectory(prefix='pytors-atexit-')as directory:
            script=Path(directory)/'atexit_program.py';script.write_text(source)
            expected=subprocess.run([sys.executable,'-I','-S',str(script)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT if merged else subprocess.PIPE,text=True,timeout=10)
            for integer in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback')):
                    result=transpile(source,TranspileOptions(integer=integer,filename=str(script),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                rust=Path(directory)/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt'if optimized else'.debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    actual=subprocess.run([str(binary)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT if merged else subprocess.PIPE,text=True,timeout=10,env={**os.environ,'PATH':'/no-python-runtime'})
                    with self.subTest(integer=integer,optimized=optimized):
                        if merged:
                            self.assertEqual(actual.returncode,expected.returncode,actual.stdout)
                            self.assertEqual(normalized_stderr(actual.stdout),normalized_stderr(expected.stdout))
                        else:
                            self.assertEqual((actual.returncode,actual.stdout),(expected.returncode,expected.stdout),actual.stderr)
                            self.assertEqual(normalized_stderr(actual.stderr),normalized_stderr(expected.stderr))


class AtexitDeferralTests(unittest.TestCase):
    def test_callback_effects_are_deferred(self):
        AtexitExecutionTests.compare(self,"import atexit\nvalues=[1]\ndef finish():\n values.append(2)\n print('end',values)\natexit.register(finish)\nprint('body',values)\n")


class AtexitBoundaryTests(unittest.TestCase):
    def test_unsupported_shutdown_protocols_are_positioned(self):
        boundaries={
            'unsupported_unregister':'unregister',
            'unsupported_custom_callable':'__call__',
            'unsupported_custom_receiver_repr':'receiver __repr__',
            'unsupported_iterator_payload':'shutdown ownership facet',
            'unsupported_lexical_cycle':'reference cycle',
            'unsupported_collected_payload':'collected source instance',
            'unsupported_callback_id':'id',
            'unsupported_callback_repr':'function-object',
            'keyword_order_at_registration':'variadic keyword',
            'starred_registration':'expanded keyword',
        }
        for name,reason in boundaries.items():
            for integer in ('i64','i128','bigint'):
                with self.subTest(name=name,integer=integer):
                    result=transpile(EXTRA_CASES[name],TranspileOptions(integer=integer,filename='boundary.py'))
                    self.assertFalse(result.success)
                    self.assertTrue(any(row.code=='E006'and row.line>0 and reason in row.message for row in result.diagnostics),result.diagnostics)

    def test_registration_decorator_keeps_existing_function_decorator_boundary(self):
        result=transpile(CASES['decorator_returns_same_callable'],TranspileOptions(filename='decorator.py'))
        self.assertFalse(result.success)
        self.assertTrue(any(row.code=='E006'and row.line==2 and'decorator'in row.message for row in result.diagnostics),result.diagnostics)

    def test_original_source_ast_and_official_symbol_tables_are_retained(self):
        from py2fastrust.frontend import build_program
        from py2fastrust.native_linked_frames import LinkedModel,LinkedProgram
        from py2fastrust.native_atexit import ShutdownPlan
        source=CASES['nested_local_capture_retained']
        program=build_program(source,'original.py')
        unit=program.main;original=ast.dump(unit.tree,include_attributes=True);table=unit.table
        linked=LinkedProgram.from_program(program)
        model=LinkedModel(linked,'original.py','i64','ascii').run()
        self.assertTrue(model.atexit_callbacks.records)
        original_nodes={id(node)for node in ast.walk(unit.tree)}
        for record in model.atexit_callbacks.records:
            self.assertIn(id(record.node),original_nodes)
            self.assertIsInstance(record.plan,ShutdownPlan)
            self.assertIs(record.plan.node,unit.tree)
            self.assertIs(linked.unit.original_unit(record.node),unit)
            self.assertNotIn(record.plan,list(model.lexical.plans.values()))
        unit.check_identity(source,'original.py')
        self.assertIs(unit.table,table)
        self.assertEqual(ast.dump(unit.tree,include_attributes=True),original)


def _case(source):
    def test(self):self.compare(source)
    return test

for _name,_source in CASES.items():
    if _name!='decorator_returns_same_callable':
        setattr(AtexitExecutionTests,'test_'+_name,_case(_source))
for _name,_source in EXTRA_CASES.items():
    if not _name.startswith('unsupported_')and _name not in {'keyword_order_at_registration','starred_registration'}:
        setattr(AtexitExecutionTests,'test_'+_name,_case(_source))


MERGED_CASES={'callback_error_continues_in_lifo_order': "import atexit\ndef fail():\n print('failure-body')\n raise ValueError('shutdown failed')\ndef finish(label):print(label)\natexit.register(finish,'oldest')\natexit.register(fail)\natexit.register(finish,'newest')\nprint('body')\n", 'main_error_report_precedes_callback_error': "import atexit\ndef fail():raise ValueError('callback')\natexit.register(fail)\nprint('body')\nraise RuntimeError('main')\n", 'callback_system_exit_is_unraisable': "import atexit,sys\ndef finish(label):print(label)\ndef fail():sys.exit(8)\natexit.register(finish,'oldest')\natexit.register(fail)\nprint('body')\nsys.exit(3)\n", 'unhandled_main_error_still_runs_callbacks': "import atexit\ndef finish():print('finished')\natexit.register(finish)\nprint('body')\nprint(1//0)\n", 'normal_callback_explicit_flush': "import atexit\ndef fail():\n print('failed callback')\n raise ValueError('callback failure')\ndef flush():print('explicit flush',flush=True)\natexit.register(fail)\natexit.register(flush)\nprint('body')\n", 'system_exit_text_before_callback_failure': "import atexit,sys\ndef fail():\n print('failed callback')\n raise ValueError('callback failure')\natexit.register(fail)\nprint('body')\nsys.exit('main payload')\n", 'main_error_before_callback_flush': "import atexit\ndef fail():\n print('failed callback')\n raise ValueError('callback failure')\ndef flush():print('explicit flush',flush=True)\natexit.register(fail)\natexit.register(flush)\nprint('body')\nraise RuntimeError('main failure')\n", 'system_exit_before_callback_flush': "import atexit,sys\ndef fail():\n print('failed callback')\n raise ValueError('callback failure')\ndef flush():print('explicit flush',flush=True)\natexit.register(fail)\natexit.register(flush)\nprint('body')\nsys.exit(3)\n", 'multiple_printing_callback_errors': "import atexit\ndef fail(name):\n print('callback',name)\n raise ValueError(name)\natexit.register(fail,'first')\natexit.register(fail,'second')\nprint('body')\n", 'callback_print_and_explicit_flush_before_raise': "import atexit,sys\ndef fail():\n print('callback')\n sys.stdout.flush()\n raise ValueError('callback')\natexit.register(fail)\nprint('body')\n"}

class AtexitMergedOutputTests(unittest.TestCase):
    pass


def _merged_case(source):
    def test(self):AtexitExecutionTests.compare(self,source,merged=True)
    return test


for _name,_source in MERGED_CASES.items():
    setattr(AtexitMergedOutputTests,'test_'+_name,_merged_case(_source))


class AtexitStderrBoundaryTests(unittest.TestCase):
    def test_direct_stderr_writes_remain_a_named_separate_protocol(self):
        sources=["import atexit,sys\ndef fail():\n print('callback')\n sys.stderr.write('stderr marker\\n')\n raise ValueError('callback')\natexit.register(fail)\nprint('body')\n", "import atexit,sys\ndef finish():print('callback')\natexit.register(finish)\nprint('body')\nsys.stderr.write('stderr marker\\n')\nraise RuntimeError('main')\n"]
        for source in sources:
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,filename='stderr_boundary.py'))
                self.assertFalse(result.success)
                self.assertTrue(any(row.code=='E006'and row.line>0 and 'stderr'in row.message for row in result.diagnostics),result.diagnostics)

if __name__=='__main__':unittest.main()
