"""Empty tuple packs and typed mapping helpers share one runtime definition."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from py2fastrust import transpile,TranspileOptions

SOURCE='''class Marker:pass
def count(*values):return len(values)
d={1:2}
print(count(),d[1])
'''


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MappingRuntimeHelperTests(unittest.TestCase):
    def test_empty_argument_pack_with_mapping_in_each_output_mode(self):
        expected=subprocess.run([sys.executable,'-I','-c',SOURCE],capture_output=True,text=True,timeout=10)
        self.assertEqual(expected.returncode,0,expected.stderr)
        with tempfile.TemporaryDirectory(prefix='pytors-mapping-empty-')as directory:
            for integer in ('i64','i128','bigint'):
                for optimize in (False,True):
                    result=transpile(SOURCE,TranspileOptions(integer=integer,optimize=optimize))
                    self.assertTrue(result.success,result.diagnostics)
                    self.assertEqual(result.rust_source.count('enum NativeEmpty'),1)
                    path=Path(directory)/(integer+str(optimize)+'.rs');path.write_text(result.rust_source)
                    for release in (False,True):
                        with self.subTest(integer=integer,optimize=optimize,release=release):
                            binary=path.with_name(path.stem+str(release))
                            build=subprocess.run(['rustc','--edition=2021',*(['-O']if release else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                            self.assertEqual(build.returncode,0,build.stderr)
                            actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,
                                env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                            self.assertEqual(actual.returncode,0,actual.stderr)
                            self.assertEqual(actual.stdout,expected.stdout)
