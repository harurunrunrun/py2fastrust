"""Machine modular power agrees with Python at signed and product boundaries."""
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from py2fastrust import transpile,TranspileOptions

PLAIN='''
for _ in range(int(input())):
    a, b, m = map(int, input().split())
    print(pow(a, b, m))
'''
CLASS='class Marker:pass\n'+PLAIN

class FixedModularPowerTests(unittest.TestCase):
    def check(self, source, include_errors):
        for mode,bits in (('i64',64),('i128',128)):
            low=-(1<<(bits-1));high=-(low+1);rng=random.Random(932+bits)
            rows=[(a,e,m)for a in (low,low+1,-7,-1,0,1,7,high)for e in (low,-19,-1,0,1,19,high)for m in (low,-97,-1,0,1,97,high)]
            rows += [(rng.randint(low,high),rng.randint(low,high),rng.randint(low,high))for _ in range(240)]
            valid=[];errors=[]
            for a,e,m in rows:
                try:pow(a,e,m)
                except ValueError as error:errors.append(((a,e,m),'ValueError: '+str(error)));continue
                valid.append((a,e,m))
            rows=valid
            data=str(len(rows))+'\n'+''.join(f'{a} {e} {m}\n'for a,e,m in rows)
            expected=subprocess.run([sys.executable,'-I','-S','-c',source],input=data,text=True,capture_output=True,timeout=30)
            self.assertEqual(expected.returncode,0,expected.stderr)
            result=transpile(source,TranspileOptions(integer=mode,license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertEqual(result.backend,'native')
            with tempfile.TemporaryDirectory(prefix='pytors-modpow-')as folder:
                rust=Path(folder,'main.rs');rust.write_text(result.rust_source)
                for optimized in (False,True):
                    binary=Path(folder,'opt'if optimized else'debug')
                    built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(built.returncode,0,built.stderr)
                    ran=subprocess.run([str(binary)],input=data,text=True,capture_output=True,timeout=30,env={**os.environ,'PATH':'/no-python-runtime'})
                    with self.subTest(mode=mode,optimized=optimized):
                        self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(0,expected.stdout,''))
                    if include_errors:
                        for (a,e,m),message in errors:
                            ran=subprocess.run([str(binary)],input=f'1\n{a} {e} {m}\n',text=True,capture_output=True,timeout=5,env={**os.environ,'PATH':'/no-python-runtime'})
                            self.assertEqual((ran.returncode,ran.stdout),(1,''))
                            self.assertEqual(ran.stderr.splitlines()[-1],message)
    def test_plain_loop(self):self.check(PLAIN,False)
    def test_inverses_and_errors(self):self.check(CLASS,True)

if __name__=='__main__':unittest.main()
