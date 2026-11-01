"""Termination unwinds native frames and retains Python exit payload semantics."""
from pathlib import Path
import os,re,shutil,subprocess,sys,tempfile,unittest
from py2fastrust import transpile,TranspileOptions


CASES={
    'site_exit':"print('before')\nexit(0)\nprint('after')\n",
    'quit_keyword':"print('before')\nquit(code=7)\nprint('after')\n",
    'saved_nested_exit':"from sys import exit as stop\ndef run(fn):\n print('before')\n fn(513)\n print('after')\nrun(stop)\n",
    'text_status':"import sys\nprint('before')\nsys.exit('finished')\n",
    'tuple_status':"import sys\nsys.exit((7,))\n",
    'mutable_cleanup':"import sys\nvalues=[1]\nclass Guard:\n def __enter__(self):return None\n def __exit__(self,a,b,c):values.append(2)\nwith Guard():sys.exit(values)\n",
    'suppressed_sys':"import sys\nclass Guard:\n def __enter__(self):return None\n def __exit__(self,a,b,c):return True\nwith Guard():sys.exit(7)\nprint(input())\n",
    'suppressed_site':"import sys\nclass Guard:\n def __enter__(self):return None\n def __exit__(self,a,b,c):return True\nreader=sys.stdin.buffer.readline\nwith Guard():exit(0)\nprint(reader())\n",
    'cleanup_context':"import sys\nclass Guard:\n def __enter__(self):return None\n def __exit__(self,a,b,c):return 1//0\nwith Guard():sys.exit(None)\n",
    'invalid_binding_effects':"def mark():print('argument');return 0\nexit(mark(),code=mark())\n",
    'shadowed_exit':"def exit(n):return n+3\nprint(exit(4))\n",
}


def observable_error(text):
    frames=re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)',text)
    chain=[line for line in text.splitlines()if re.match(r'^(?:[A-Za-z_]+Error|SystemExit|During handling|The above exception)',line)]
    return frames,chain


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class NativeExitTests(unittest.TestCase):
    def exercise(self,source):
        with tempfile.TemporaryDirectory()as temporary:
            directory=Path(temporary);main=directory/'main.py';main.write_text(source)
            # exit/quit are supplied by site, so -S would change the reference.
            expected=subprocess.run([sys.executable,'-I','-B',str(main)],input='ready\n',capture_output=True,text=True,timeout=15)
            for mode in ('i64','i128','bigint'):
                with self.subTest(integer=mode):
                    result=transpile(source,TranspileOptions(filename=str(main),integer=mode,license='none'))
                    self.assertTrue(result.success,str(result.diagnostics))
                    self.assertEqual(result.backend,'native')
                    self.assertLess(len(result.rust_source.encode()),512*1024)
                    for marker in ('enum Value','enum Op','struct Runtime','fn step('):self.assertNotIn(marker,result.rust_source)
                    rust=directory/'main.rs';rust.write_text(result.rust_source)
                    for optimized in (False,True):
                        with self.subTest(optimized=optimized):
                            binary=directory/'program'
                            build=subprocess.run(['rustc','--edition=2021','--crate-name','native_exit_tests',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=180)
                            self.assertEqual(build.returncode,0,build.stderr)
                            actual=subprocess.run([str(binary)],input='ready\n',capture_output=True,text=True,timeout=15,env={**os.environ,'PATH':'/no-python','PYTHONPATH':'/no-python'})
                            self.assertEqual(actual.returncode,expected.returncode)
                            self.assertEqual(actual.stdout,expected.stdout)
                            self.assertEqual(observable_error(actual.stderr),observable_error(expected.stderr))
                            if not observable_error(expected.stderr)[0]:self.assertEqual(actual.stderr,expected.stderr)


def _case(source):
    def test(self):self.exercise(source)
    return test


for _name,_source in CASES.items():setattr(NativeExitTests,'test_'+_name,_case(_source))


class ExitBoundaryTests(unittest.TestCase):
    def test_custom_payload_display_has_specific_diagnostic(self):
        result=transpile("class Status:pass\nexit(Status())\n",TranspileOptions(filename='main.py'))
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertIn('deferred',result.diagnostics[0].message)
        self.assertIn('__str__',result.diagnostics[0].message)
