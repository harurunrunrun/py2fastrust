"""Typed exception chains interoperate with unwound process-exit markers."""
from pathlib import Path
import hashlib,os,re,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions


def observable_error(stderr):
    rows=[];message=False
    for line in stderr.splitlines():
        if line=='Traceback (most recent call last):'or line.startswith('  File '):
            rows.append(line);message=False
        elif line in {'During handling of the above exception, another exception occurred:',
                      'The above exception was the direct cause of the following exception:'}:
            rows.append(line);message=False
        elif re.match(r'^[A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception|Iteration|Exit)(?::|$)',line):
            rows.append(line);message=True
        elif message:rows.append(line)
    return rows


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeExceptionExitIntegrationTests(unittest.TestCase):
    def exercise(self,source):
        with tempfile.TemporaryDirectory(prefix='pytors-exception-exit-')as temporary:
            root=Path(temporary);main=root/'main.py';main.write_text(source)
            expected=subprocess.run([sys.executable,'-I','-B',str(main)],capture_output=True,text=True,timeout=15)
            for mode in ('i64','i128','bigint'):
                with self.subTest(integer=mode):
                    with patch('py2fastrust.codegen.generate',side_effect=AssertionError('legacy emitter entered')):
                        result=transpile(source,TranspileOptions(filename=str(main),integer=mode,license='none'))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.backend,'native')
                    self.assertLess(len(result.rust_source.encode()),512*1024)
                    for marker in ('enum Value','enum Op','struct Runtime','fn step(','UNICODE LICENSE V3'):
                        self.assertNotIn(marker,result.rust_source)
                    rust=root/(mode+'.rs');rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        with self.subTest(optimized=optimized):
                            binary=root/(mode+('_optimized'if optimized else'_debug'))
                            build=subprocess.run(['rustc','--edition=2021','--crate-name','exception_exit_integration',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                            self.assertEqual(build.returncode,0,build.stderr)
                            actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/no-python-runtime','PYTHONPATH':'/no-python-runtime'})
                            self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
                            self.assertEqual(actual.stdout,expected.stdout)
                            self.assertEqual(observable_error(actual.stderr),observable_error(expected.stderr))
                            if not observable_error(expected.stderr):self.assertEqual(actual.stderr,expected.stderr)

CASES = [('stored_value_replaces_sys_zero',
  'import sys\n'
  'saved=ValueError("saved")\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise saved\n'
  'with Guard():sys.exit(0)\n',
  'b60adab0678e0f20d15382cbe6bc364a826e256ad2bf340b50b03dc558b5dc20'),
 ('stored_value_replaces_site_none',
  'saved=TypeError("cleanup")\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise saved\n'
  'with Guard():exit(None)\n',
  '5283b405773768e53436d1b1bbcd22d29dc6eb18d438e082a56c836e5786139c'),
 ('stored_value_replaces_sys_none',
  'import sys\n'
  'saved=RuntimeError("cleanup")\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):raise saved\n'
  'with Guard():sys.exit(None)\n',
  'ac44de6a6d7f63bc792cdd89d201becb1fc1b7692ecd13b6f0d4384690096dce'),
 ('shared_payload_context_late_display',
  'import sys\n'
  'payload=[1]\n'
  'saved=ValueError(payload)\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):payload.append(2);raise saved\n'
  'with Guard():sys.exit(payload)\n',
  'cc2f0509c6eb6d69c814c59bd0849654514b426d4c2a058b6e28e3876a5a8b63'),
 ('exit_replaces_saved_value',
  'import sys\n'
  'saved=ValueError("original")\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):print("cleanup");sys.exit(5)\n'
  'with Guard():raise saved\n',
  '5b6aca716441f4c2634a3026e448bfe258190573e68b0e0cc29b86f7e67fefdd'),
 ('suppressed_exit_then_reraise_original',
  'import sys\n'
  'saved=TypeError("original")\n'
  'class Leave:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):sys.exit(4)\n'
  'class Suppress:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):return True\n'
  'with Suppress():\n'
  ' with Leave():raise saved\n'
  'raise saved\n',
  '67450cf63667e8c3247ef88aa031cfcbae08d33df32da1ae783ab7984fb40a1c'),
 ('exit_replaces_generator_direct_cause',
  'import sys\n'
  'def stop(value):raise StopIteration(value)\n'
  'class Guard:\n'
  ' def __enter__(self):return self\n'
  ' def __exit__(self,a,b,c):sys.exit(6)\n'
  'with Guard():print(list(stop(value)for value in [1]))\n',
  '684a6325a7bbd90bf230978f411a355d38c134200be48b11e757294f5dd12d75')]


def _case(source,digest):
    def test(self):
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),digest)
        self.exercise(source)
    return test


for _name,_source,_digest in CASES:
    setattr(NativeExceptionExitIntegrationTests,"test_"+_name,_case(_source,_digest))
