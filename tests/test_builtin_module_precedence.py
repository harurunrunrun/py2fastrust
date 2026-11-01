"""BuiltinImporter priority follows the actual conversion-runtime build."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions
from py2fastrust.frontend import build_program
from py2fastrust.module_catalog import BUILTIN_MODULES,TARGET_BUILTIN_MODULES


def compare_native_files(test,files,input_text=''):
    if not shutil.which('rustc'):test.skipTest('rustc is required')
    with tempfile.TemporaryDirectory(prefix='pytors-builtin-priority-')as directory:
        root=Path(directory)
        for name,source in files.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source)
        main=root/'main.py'
        expected=subprocess.run([sys.executable,'-S',str(main)],input=input_text,text=True,capture_output=True,timeout=15,
                                cwd=root,env={**os.environ,'PYTHONPATH':''})
        test.assertEqual(expected.returncode,0,expected.stderr)
        for mode in ('i64','i128','bigint'):
            result=transpile(main.read_text(),TranspileOptions(filename=str(main),module_paths=(root,),integer=mode))
            test.assertTrue(result.success,result.diagnostics)
            test.assertEqual(result.backend,'native')
            rust=root/(mode+'.rs');rust.write_text(result.rust_source)
            for optimized in (False,True):
                with test.subTest(integer=mode,optimized=optimized):
                    binary=root/(mode+('_release'if optimized else'_debug'))
                    build=subprocess.run(['rustc','--edition=2021','--crate-name','builtin_precedence',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],text=True,capture_output=True,timeout=180)
                    test.assertEqual(build.returncode,0,build.stderr)
                    actual=subprocess.run([str(binary)],input=input_text,text=True,capture_output=True,timeout=15,
                                          env={**os.environ,'PATH':'/pytors-no-python','PYTHONPATH':'/pytors-no-python'})
                    test.assertEqual((actual.returncode,actual.stdout,actual.stderr),(expected.returncode,expected.stdout,expected.stderr))


class BuiltinModulePrecedenceTests(unittest.TestCase):
    def test_target_catalog_is_the_supported_intersection_of_real_builtins(self):
        self.assertEqual(TARGET_BUILTIN_MODULES,frozenset(sys.builtin_module_names)&BUILTIN_MODULES)

    def test_real_builtin_imports_precede_poisoned_source_candidates(self):
        with tempfile.TemporaryDirectory(prefix='pytors-builtin-resolution-')as directory:
            root=Path(directory)
            for name in sorted(TARGET_BUILTIN_MODULES):
                (root/(name+'.py')).write_text('raise RuntimeError("must not read or execute this candidate")\n')
                with self.subTest(module=name):
                    program=build_program('import '+name+'\n',str(root/'main.py'))
                    self.assertEqual(program.module(name).origin,'builtin')
                    self.assertIn(name,program.native_imports)
                    self.assertNotIn(name,{unit.name for unit in program.units})

    def test_ordinary_stdlib_files_and_regular_packages_remain_path_first(self):
        with tempfile.TemporaryDirectory(prefix='pytors-ordinary-resolution-')as directory:
            root=Path(directory)
            (root/'heapq.py').write_text('value=7\n')
            package=root/'collections';package.mkdir();(package/'__init__.py').write_text('')
            (package/'child.py').write_text('value=8\n')
            program=build_program('import heapq\nimport collections.child\n',str(root/'main.py'))
            for name in ('heapq','collections','collections.child'):
                self.assertEqual(program.module(name).origin,'user')
                self.assertNotIn(name,program.native_imports)

    def test_builtin_policy_is_not_tied_to_standard_module_spellings(self):
        with tempfile.TemporaryDirectory(prefix='pytors-catalog-resolution-')as directory:
            root=Path(directory);(root/'ordinary.py').write_text('value=7\n')
            with patch('py2fastrust.frontend.TARGET_BUILTIN_MODULES',frozenset({'ordinary'})):
                program=build_program('import ordinary\n',str(root/'main.py'))
            self.assertEqual(program.module('ordinary').origin,'builtin')

    @unittest.skipUnless('math'in TARGET_BUILTIN_MODULES and shutil.which('rustc'),'requires a target build with builtin math and rustc')
    def test_reported_math_source_preserves_the_actual_builtin_precedence(self):
        compare_native_files(self,{'main.py':'from math import gcd\nprint(gcd(8,3))\n','math.py':'def gcd(a,b):return a+b\n'})


if __name__=='__main__':unittest.main()
