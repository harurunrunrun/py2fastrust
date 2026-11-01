"""Linked module fields must not silently bypass standard stream semantics."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile


class LinkedStreamMutationTests(unittest.TestCase):
    def test_replacement_streams_are_rejected_through_each_module_receiver(self):
        with tempfile.TemporaryDirectory(prefix="pytors-stream-module-") as directory:
            root=Path(directory)
            (root/"helper.py").write_text("value=1\n")
            for stream in ("stdin","stdout","stderr"):
                for receiver,prefix in (("sys",""),("saved","saved=sys\n"),
                                        ("selected()","def selected():return sys\n")):
                    source="import helper\nimport sys\n"+prefix+receiver+"."+stream+"=None\nprint(2)\n"
                    for mode in ("i64","i128","bigint"):
                        with self.subTest(stream=stream,receiver=receiver,integer=mode):
                            result=transpile(source,TranspileOptions(filename=str(root/"main.py"),
                                module_paths=(root,),integer=mode))
                            self.assertFalse(result.success)
                            self.assertIsNone(result.rust_source)
                            self.assertEqual(len(result.diagnostics),1)
                            diagnostic=result.diagnostics[0]
                            self.assertEqual(diagnostic.code,"E006")
                            self.assertIn("sys."+stream,diagnostic.message)
                            self.assertIn("stream",diagnostic.message)
                            self.assertIn("dispatch",diagnostic.message)
                            self.assertEqual(diagnostic.line,len(prefix.splitlines())+3)

    @unittest.skipUnless(shutil.which("rustc"),"rustc is required")
    def test_an_ordinary_module_can_store_a_field_named_stdout(self):
        source="import helper\nhelper.stdout=None\nprint(helper.stdout)\n"
        with tempfile.TemporaryDirectory(prefix="pytors-user-stdout-field-") as directory:
            root=Path(directory);(root/"helper.py").write_text("stdout=42\n")
            script=root/"main.py";script.write_text(source)
            reference=subprocess.run([sys.executable,str(script)],capture_output=True,text=True,timeout=10)
            self.assertEqual((reference.returncode,reference.stdout),(0,"None\n"))
            for mode in ("i64","i128","bigint"):
                result=transpile(source,TranspileOptions(filename=str(script),module_paths=(root,),integer=mode))
                self.assertTrue(result.success,result.diagnostics)
                rust=root/(mode+".rs");rust.write_text(result.rust_source)
                for release in (False,True):
                    binary=root/mode
                    build=subprocess.run(["rustc","--edition=2021",*(["-O"]if release else[]),
                        str(rust),"-o",str(binary)],capture_output=True,text=True,timeout=90)
                    self.assertEqual(build.returncode,0,build.stderr)
                    actual=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,
                        env={"PATH":"/unavailable","PYTHONPATH":"/unavailable"})
                    self.assertEqual((actual.returncode,actual.stdout,actual.stderr),
                        (reference.returncode,reference.stdout,reference.stderr))
