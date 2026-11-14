"""Canonical sys.argv is lazy, shared native module data with actual OS arguments."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from py2fastrust import TranspileOptions, transpile


CASES = {'ordered_arguments': ('import sys\nprint(sys.argv)\nprint(len(sys.argv),sys.argv[0],sys.argv[-1])\nprint([len(value) for value in sys.argv[1:]])\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'from_import_shared_identity': ('import sys\nfrom sys import argv\nsaved=sys.argv\nargv.append("tail")\nsaved[1]="changed"\nprint(sys.argv,argv,saved)\nprint(sys.argv is argv,argv is saved)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'heterogeneous_elements': ('import sys\nfrom sys import argv\nargv.append(7)\nargv.append(None)\nprint(argv)\nprint(sys.argv is argv)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'rebound_module_member': ('import sys\nfrom sys import argv\noriginal=argv\nsys.argv=["new"]\nprint(argv,sys.argv,argv is sys.argv)\nargv.append("old-tail")\nsys.argv.append("new-tail")\nprint(original,sys.argv)\nsys.argv=9\nprint(argv,sys.argv)\nsys.argv=None\nprint(argv,sys.argv)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'function_rebind_and_return': ('import sys\nsaved=sys.argv\ndef replace():\n sys.argv=("tuple",3)\n return sys.argv\ndef read():return sys.argv\nprint(replace(),read(),saved)\nsys.argv=["again"]\nprint(read(),saved)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'callback_rebind_preserves_receiver': ('import sys\noriginal=sys.argv\ndef right():\n sys.argv=["new"]\n return "appended-old"\noriginal.append(right())\nprint(original,sys.argv)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'module_lookup_after_callback': ('import sys\nsaved=sys.argv\ndef replace():\n sys.argv=["new"]\n return None\nprint(replace(),sys.argv,saved)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'clear_live_alias': ('import sys\nfrom sys import argv\nsaved=sys.argv\nargv.clear()\nprint(sys.argv,saved,argv is saved)\nsys.argv.append("restored")\nprint(argv)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'slice_and_per_argument': ('import sys\nfrom sys import argv\ncopy=argv[:]\nfor i,value in enumerate(argv):print(i,value)\nargv.reverse()\nprint(argv,copy)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'unicode_observers': ('import sys\nfor value in sys.argv[1:]:\n print(value,len(value),value[:1],value[-1:])\n', [(['e697a5e69cace8aa9e', 'c3a9', 'f09f9982', ''], '')], ('unicode',)), 'entry_name_and_file': ('import sys\nprint(__file__)\nprint(sys.argv[0])\nprint(sys.argv[1:])\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'shadowed_local_module': ('import sys\nactual=sys.argv\nclass Substitute:\n def __init__(self):self.argv=["local"]\ndef inspect(sys):\n sys.argv.append("tail")\n return sys.argv\nprint(inspect(Substitute()),actual)\n', [([], ''), (['', '6f6e65', '74776f20776f726473', '2d2d6c69746572616c', '2d33'], '')], ('ascii',)), 'untaken_runtime_read': ('import sys\ndef observe(flag):\n if flag:return sys.argv\n return ["unused"]\nprint(observe(int(input())!=0))\n', [(['726177ff80'], '0\n')], ('ascii',)), 'assignment_before_read': ('import sys\nsys.argv=["replacement"]\nprint(sys.argv)\n', [(['726177ff80'], '0\n')], ('ascii',)), 'scalar_assignment_before_import_alias': ('import sys\nsys.argv=7\nfrom sys import argv\nprint(argv,sys.argv)\n', [(['726177ff80'], '0\n')], ('ascii',)), 'unicode_plain_print_both_modes': ('import sys\nprint(sys.argv[1])\n', [(['e697a5e69cace8aa9ec3a9f09f9982'], '')], ('ascii', 'unicode')), 'saved_module_alias': ('import sys as system\nsaved_module=system\nfrom sys import argv as saved\nsaved_module.argv.append("tail")\nprint(saved_module.argv,saved,saved_module.argv is saved)\n', [(['', '6f6e65', '74776f20776f726473'], '')], ('ascii',)), 'supported_unrelated_api': ('import sys\nsys.set_int_max_str_digits(0)\nprint(sys.get_int_max_str_digits())\n', [(['726177ff80'], '')], ('ascii',)), 'callback_before_alias': ('import sys\ndef change():sys.argv=7\nchange()\nfrom sys import argv\nprint(argv+1,sys.argv)\n', [(['', '7461696c'], '')], ('ascii',)), 'same_call_earlier_argument': ('import sys\nsys.argv=["new"]\ndef change():\n sys.argv=8\n return "changed"\nprint(change(),sys.argv)\n', [(['', '7461696c'], '')], ('ascii',)), 'loop_revisits_module_value': ('import sys\nfor i in range(2):\n print(sys.argv)\n sys.argv=i\n', [(['', '7461696c'], '')], ('ascii',)), 'initial_alias_before_callback': ('import sys\nfrom sys import argv\nsaved=argv\ndef change():sys.argv=13\nchange()\nargv.append("still-list")\nprint(saved,sys.argv,saved is argv)\n', [(['', '7461696c'], '')], ('ascii',)), 'prior_reassignment_before_alias': ('import sys\nsys.argv=["new"]\nfrom sys import argv\nargv.append("tail")\nprint(argv,sys.argv,argv is sys.argv)\n', [(['', '7461696c'], '')], ('ascii',)), 'conditional_callback_write': ('import sys\nsys.argv=["new"]\ndef change():\n sys.argv=4\n return True\nif change():print(sys.argv+1)\n', [(['', '7461696c'], '')], ('ascii',)), 'multiple_target_store': ('import sys\nsys.argv=other=7\nprint(sys.argv+1,other)\n', [(['726177ff80'], '')], ('ascii',)), 'append_argument_callback': ('import sys\nsys.argv=["new"]\nsaved=sys.argv\ndef change():\n sys.argv=4\n return "old-tail"\nsaved.append(change())\nprint(sys.argv+1,saved)\n', [(['726177ff80'], '')], ('ascii',)), 'display_callback_rebind': ('import sys\nsys.argv=["new"]\nclass Token:\n def __str__(self):\n  sys.argv=4\n  return "token"\nprint(Token())\nprint(sys.argv+1)\n', [(['726177ff80'], '')], ('ascii',)), 'completed_store_from_function': ('import sys\ndef choose(flag):\n return ["a"] if flag else ["b"]\nsys.argv=choose(int(input())!=0)\nfrom sys import argv\nargv.append("tail")\nprint(argv,argv is sys.argv)\n', [(['726177ff80'], '0\n'), (['726177ff80'], '1\n')], ('ascii',)), 'branch_stores_before_read': ('import sys\nif int(input()):sys.argv=["a"]\nelse:sys.argv=4\nprint(sys.argv)\n', [(['726177ff80'], '0\n'), (['726177ff80'], '1\n')], ('ascii',)), 'failed_store_keeps_initial_data': ('import atexit\nimport sys\ndef finish():print("initial",sys.argv)\natexit.register(finish)\ndef fail():\n raise ValueError("failed RHS")\nsys.argv=fail()\n', [(['', '7461696c'], '')], ('ascii',)), 'unobserved_argv_in_dormant_function': ('import sys\ndef unused():return sys.argv\nprint("unused")\n', [(['726177ff80'], '')], ('ascii',)), 'actual_list_class': ('import sys\nfrom sys import argv\nprint(type(argv) is list,type(sys.argv) is list)\nargv.append(3)\nprint(type(argv) is list,argv is sys.argv)\n', [(['', '7461696c'], '')], ('ascii',))}

BOUNDARIES = {'alias_after_delete': 'import sys\nfrom sys import argv\nsaved=argv\ndel sys.argv\nsaved.append("alive")\nprint(saved,argv is saved)\n', 'deleted_member_error': 'import sys\ndel sys.argv\nprint(sys.argv)\n', 'deleted_import_error': 'import sys\ndel sys.argv\nfrom sys import argv\n', 'getattr_observer_boundary': 'import sys\nprint(getattr(sys,"argv"))\n', 'vars_observer_boundary': 'import sys\nprint(vars(sys)["argv"])\n', 'dict_observer_boundary': 'import sys\nprint(sys.__dict__["argv"])\n', 'getattr_replacement_guard': 'import sys\ndef replace():sys.argv=3\nprint(getattr(sys,"argv",None))\n', 'stdout_rebind_changes_argv': 'import sys\noriginal=sys.stdout\nsys.argv=["new"]\nclass Sink:\n def write(self,text):\n  sys.argv=7\n  return original.write(text)\n def flush(self):return original.flush()\nsys.stdout=Sink()\nprint("trigger")\nsaved=sys.argv\nsys.stdout=original\nprint(saved+1)\n', 'stdout_rebind_without_argv_control': 'import sys\noriginal=sys.stdout\nclass Sink:\n def write(self,text):return original.write(text)\n def flush(self):return original.flush()\nsys.stdout=Sink()\nprint("trigger")\nsys.stdout=original\nprint("restored")\n', 'stdout_method_rebind_changes_argv': 'import sys\noriginal_write=sys.stdout.write\nsys.argv=["new"]\ndef write(text):\n sys.argv=9\n return original_write(text)\nsys.stdout.write=write\nprint("trigger")\nsaved=sys.argv\nsys.stdout.write=original_write\nprint(saved+1)\n', 'dir_only': 'import sys\nprint("argv" in dir(sys))\n', 'hasattr_only': 'import sys\nprint(hasattr(sys,"argv"))\n', 'hasattr_with_dormant_value_read': 'import sys\ndef unused():return sys.argv\nprint(hasattr(sys,"argv"))\n', 'getattr_only': 'import sys\nprint(getattr(sys,"argv"))\n', 'vars_only': 'import sys\nprint(vars(sys)["argv"])\n', 'module_dictionary_only': 'import sys\nprint(sys.__dict__["argv"])\n'}

INVALID_BYTES_SOURCE = 'import sys\nprint(repr(sys.argv[-1]))\nprint([ord(character) for character in sys.argv[-1]])\n'

PROJECT_FILES = {'main.py': 'import sys\nfrom args_reader import initial,current\nfrom args_writer import replace\ninitial.append("old-tail")\nprint(initial,current(),sys.argv,initial is sys.argv)\nreplace()\nprint(initial,current(),sys.argv,initial is sys.argv)\n', 'args_reader.py': 'import sys\nfrom sys import argv as initial\ndef current():return sys.argv\n', 'args_writer.py': 'import sys\ndef replace():\n sys.argv=["new"]\n sys.argv.append("new-tail")\n'}


def observed(process):
    stderr = process.stderr.decode('utf8', errors='backslashreplace')
    frames = re.findall(r'File "[^\n]*", line (\d+), in ([^\n]+)', stderr)
    final = stderr.strip().splitlines()[-1] if stderr.strip() else ''
    return process.returncode, process.stdout, frames, final


@unittest.skipUnless(shutil.which('rustc') and os.name == 'posix', 'Rust and POSIX OS arguments required')
class SysArgvExecutionTests(unittest.TestCase):
    def compare(self, source, inputs, string_modes=('ascii',), files=None):
        with tempfile.TemporaryDirectory(prefix='pytors-argv-') as directory:
            directory = Path(directory)
            script = directory / 'argv_program.py'
            script.write_text(source)
            for name, body in (files or {}).items():
                (directory / name).write_text(body)
            expected = []
            for encoded, data in inputs:
                args = [bytes.fromhex(value) for value in encoded]
                command = [os.fsencode(sys.executable), b'-S', b'-B', os.fsencode(script), *args]
                process = subprocess.run(command, input=data.encode(), capture_output=True,
                                         timeout=20, env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
                expected.append(observed(process))
            for integer in ('i64', 'i128', 'bigint'):
                for string_mode in string_modes:
                    with patch('py2fastrust.codegen.generate', side_effect=AssertionError('VM fallback')):
                        result = transpile(source, TranspileOptions(integer=integer,
                            filename=str(script), module_paths=(directory,),
                            string_mode=string_mode, license='none'))
                    self.assertTrue(result.success, result.diagnostics)
                    self.assertEqual(result.backend, 'native')
                    self.assertLess(len(result.rust_source.encode()), 512*1024)
                    for marker in ('enum Value', 'enum Op', 'struct Runtime', 'struct PegParser'):
                        self.assertNotIn(marker, result.rust_source)
                    rust = directory / (integer + '_' + string_mode + '.rs')
                    rust.write_text(result.rust_source)
                    for optimized in (False, True):
                        binary = rust.with_suffix('.opt' if optimized else '.debug')
                        build = subprocess.run(['rustc', '--edition=2021',
                            *(['-O'] if optimized else []), str(rust), '-o', str(binary)],
                            capture_output=True, text=True, timeout=120)
                        self.assertEqual(build.returncode, 0, build.stderr)
                        for (encoded, data), reference in zip(inputs, expected):
                            # This changes OS invocation data, not the source or
                            # sys.argv. Both programs receive the same argv0.
                            command = [os.fsencode(script), *(bytes.fromhex(value) for value in encoded)]
                            actual = subprocess.run(command, executable=os.fsencode(binary),
                                input=data.encode(), capture_output=True, timeout=20,
                                env={**os.environ, 'PATH':'/no-python-runtime'})
                            with self.subTest(integer=integer, string_mode=string_mode,
                                              optimized=optimized, arguments=encoded, input=data):
                                self.assertEqual(observed(actual), reference, actual.stderr)

    def test_actual_argv0_is_independent_of_source_metadata(self):
        source = CASES['entry_name_and_file'][0]
        with tempfile.TemporaryDirectory(prefix='pytors-argv0-') as directory:
            directory = Path(directory)
            for integer in ('i64', 'i128', 'bigint'):
                result = transpile(source, TranspileOptions(integer=integer,
                    filename='virtual/source.py', license='none'))
                self.assertTrue(result.success, result.diagnostics)
                rust = directory / (integer + '.rs')
                rust.write_text(result.rust_source)
                for optimized in (False, True):
                    binary = rust.with_suffix('.opt' if optimized else '.debug')
                    built = subprocess.run(['rustc', '--edition=2021',
                        *(['-O'] if optimized else []), str(rust), '-o', str(binary)],
                        capture_output=True, text=True, timeout=120)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    for invocation in ('', './independent-name', '日本-launch'):
                        # POSIX execve admits an empty argv0; CP's posix_spawn
                        # wrapper rejects it before exec, so use fork/exec here.
                        # This is the standalone launch contract, not a CP
                        # script invocation comparison or a sys.argv rewrite.
                        run = subprocess.run([invocation.encode(), b'', b'tail'],
                            executable=os.fsencode(binary), capture_output=True, timeout=20,
                            preexec_fn=lambda: None,
                            env={**os.environ, 'PATH':'/no-python-runtime'})
                        self.assertEqual(run.returncode, 0, run.stderr)
                        self.assertEqual(run.stdout.decode(),
                            "virtual/source.py\n" + invocation + "\n['', 'tail']\n")

    def test_shared_module_data_across_source_imports(self):
        self.compare(PROJECT_FILES['main.py'], [([], ''), (['', '7461696c'], '')],
                     files={name:body for name,body in PROJECT_FILES.items() if name!='main.py'})


def _case(spec):
    def test(self):
        self.compare(*spec)
    return test


for _name, _spec in CASES.items():
    setattr(SysArgvExecutionTests, 'test_' + _name, _case(_spec))


class SysArgvBoundaryTests(unittest.TestCase):
    def test_existing_namespace_observer_and_deletion_gaps_are_positioned(self):
        for name, source in BOUNDARIES.items():
            for integer in ('i64', 'i128', 'bigint'):
                with self.subTest(name=name, integer=integer):
                    result = transpile(source, TranspileOptions(integer=integer, license='none'))
                    self.assertFalse(result.success)
                    self.assertTrue(result.diagnostics)
                    self.assertTrue(all(value.code=='E006' and value.line>0 and value.column>0
                                        for value in result.diagnostics))
                    self.assertTrue(all('Source:' in str(value) for value in result.diagnostics))

    @unittest.skipUnless(shutil.which('rustc') and os.name=='posix', 'raw OS bytes need POSIX and Rust')
    def test_invalid_os_bytes_have_an_explicit_lossless_diagnostic(self):
        with tempfile.TemporaryDirectory(prefix='pytors-argv-bytes-') as directory:
            directory=Path(directory);script=directory/'invalid_argv.py';script.write_text(INVALID_BYTES_SOURCE)
            original=subprocess.run([os.fsencode(sys.executable),b'-S',b'-B',os.fsencode(script),b'raw\xff\x80'],capture_output=True,timeout=20)
            self.assertEqual(original.returncode,0)
            self.assertIn(b'56575',original.stdout)
            for integer in ('i64','i128','bigint'):
                result=transpile(INVALID_BYTES_SOURCE,TranspileOptions(integer=integer,filename=str(script),license='none'))
                self.assertTrue(result.success,result.diagnostics)
                rust=directory/(integer+'.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=rust.with_suffix('.opt' if optimized else '.debug')
                    build=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    run=subprocess.run([os.fsencode(script),b'raw\xff\x80'],executable=os.fsencode(binary),capture_output=True,timeout=20,env={**os.environ,'PATH':'/no-python-runtime'})
                    self.assertEqual(run.returncode,1)
                    self.assertIn(b'726177ff80',run.stderr)
                    self.assertIn(b'surrogateescape string representation is not implemented',run.stderr)
                    self.assertNotIn(b'panicked',run.stderr)
