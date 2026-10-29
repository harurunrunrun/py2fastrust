"""Field caches use resolved callable effects, including aliases and returns."""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from py2fastrust import TranspileOptions,transpile
from py2fastrust.native_class_loop_fields import _may_call_source

CASES={'exact_public_alias': ('class Box:\n def __init__(self):self.value=0\nbox=Box()\ndef advance():box.value+=1\ncall=advance\nfor index in range(3):\n print(box.value)\n call()\n print(box.value)\n', ('',)), 'returned_alias': ('class Box:\n def __init__(self):self.value=0\nbox=Box()\ndef advance():box.value+=1\ndef make():return advance\ncall=make()\nfor index in range(3):\n print(box.value)\n call()\n print(box.value)\n', ('',)), 'callable_argument_alias': ('class Box:\n def __init__(self):self.value=0\nbox=Box()\ndef advance():box.value+=1\ndef invoke(callback):callback()\ncall=invoke\nfor index in range(3):\n print(box.value)\n call(advance)\n print(box.value)\n', ('',)), 'conditional_alias': ('class Box:\n def __init__(self):self.value=0\nbox=Box()\ndef advance():box.value+=1\ndef twice():box.value+=2\ncall=advance if int(input()) else twice\nfor index in range(3):\n print(box.value)\n call()\n print(box.value)\n', ('0\n', '1\n'))}


class LoopFieldCallProofTests(unittest.TestCase):
    def test_missing_callable_effect_vectors_are_conservative(self):
        node=ast.parse("invoke()").body[0].value
        for targets,builtins,members in ((None,{},{}),({},None,{}),({},{},None)):
            site=SimpleNamespace(targets=targets,builtins=builtins,members=members)
            model=SimpleNamespace(frame_selection=None,callable_cells=SimpleNamespace(sites={(0,id(node)):site}))
            emitter=SimpleNamespace(model=model,plan=SimpleNamespace(index=0))
            self.assertTrue(_may_call_source(emitter,node))


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class LoopFieldAliasExecutionTests(unittest.TestCase):
    def compare(self,source,inputs):
        expected=[subprocess.run([sys.executable,'-I','-S','-c',source],input=data,capture_output=True,text=True,timeout=10)for data in inputs]
        self.assertTrue(all(not result.returncode for result in expected))
        with tempfile.TemporaryDirectory(prefix='pytors-loop-alias-')as directory:
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,filename='loop_alias.py'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                source_path=Path(directory)/(integer+'.rs');source_path.write_text(result.rust_source)
                for release in(False,True):
                    binary=source_path.with_suffix('.release'if release else'.debug')
                    build=subprocess.run(['rustc','--edition=2021',*(['-O']if release else[]),str(source_path),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(build.returncode,0,build.stderr)
                    for data,reference in zip(inputs,expected):
                        with self.subTest(integer=integer,release=release,input=data):
                            actual=subprocess.run([str(binary)],input=data,capture_output=True,text=True,timeout=10,env={'PATH':'/no-python-runtime'})
                            self.assertEqual((actual.returncode,actual.stdout,actual.stderr),(reference.returncode,reference.stdout,reference.stderr))


def case(name):
    def test(self):self.compare(*CASES[name])
    return test
for name in CASES:setattr(LoopFieldAliasExecutionTests,'test_'+name,case(name))

if __name__=='__main__':unittest.main()
