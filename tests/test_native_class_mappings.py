"""Shared typed mappings: original source scopes, aliases and hash-key semantics."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions


class MappingSelectionTests(unittest.TestCase):
    def test_ordinary_aliases_select_shared_storage_before_lowering(self):
        sources=["d={1:2}\na=d\na[1]=3\nprint(d)\n",
                 "v=[1]\nd={'x':v}\nd['x'].append(2)\nprint(v)\n",
                 "d={1:2}\nt=(d,)\nt[0][1]=3\nprint(d)\n"]
        for source in sources:
            with self.subTest(source=source),patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback entered')):
                result=transpile(source)
                self.assertTrue(result.success,result.diagnostics)
                self.assertIn('ClassMapping_',result.rust_source)

    def test_cycles_keep_a_positioned_lifetime_diagnostic(self):
        for source in ["class Marker:pass\nd={}\nd['x']=d\n", "class Marker:pass\nd={}\na=[d]\nd['x']=a\n"]:
            result=transpile(source)
            self.assertFalse(result.success)
            diagnostic=result.diagnostics[0]
            self.assertEqual(diagnostic.code,'E006')
            self.assertGreater(diagnostic.line,0)
            self.assertRegex(diagnostic.message,'cycl|recursive')

    def test_observable_set_traversal_keeps_a_specific_diagnostic(self):
        for body in ["print({1,2})", "print(sorted({1,2},key=lambda value:0))"]:
            result=transpile('class Marker:pass\n'+body+'\n')
            self.assertFalse(result.success)
            self.assertEqual(result.diagnostics[0].code,'E006')
            self.assertIn('set',result.diagnostics[0].message)
            self.assertRegex(result.diagnostics[0].message,'order|traversal')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MappingExecutionTests(unittest.TestCase):
    def compare(self,source):
        expected=subprocess.run([sys.executable,'-I','-c',source],text=True,capture_output=True,timeout=10)
        with tempfile.TemporaryDirectory(prefix='pytors-shared-mapping-')as directory:
            for integer in ('i64','i128','bigint'):
                with patch('py2fastrust.codegen.generate',side_effect=AssertionError('VM fallback entered')):
                    result=transpile(source,TranspileOptions(integer=integer,filename='mappings.py'))
                self.assertTrue(result.success,result.diagnostics)
                self.assertEqual(result.backend,'native')
                self.assertLess(len(result.rust_source.encode()),512*1024)
                for marker in ('enum Value','enum Op','struct Runtime','struct PegParser'):
                    self.assertNotIn(marker,result.rust_source)
                path=Path(directory)/(integer+'.rs');path.write_text(result.rust_source)
                for optimized in (False,True):
                    with self.subTest(integer=integer,optimized=optimized):
                        binary=path.with_name(integer+str(optimized))
                        built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(path),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                        self.assertEqual(built.returncode,0,built.stderr)
                        actual=subprocess.run([str(binary)],text=True,capture_output=True,timeout=10,
                            env={**os.environ,'PATH':'/pytors-no-runtime-dependencies','PYTHONPATH':'/pytors-no-runtime-dependencies'})
                        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
                        self.assertEqual(actual.returncode,expected.returncode,actual.stderr+expected.stderr)
                        if expected.returncode:
                            self.assertEqual(actual.stderr.splitlines()[-1],expected.stderr.splitlines()[-1])

    def test_dict_key_value_order(self):
        self.compare("""class Box:pass
def key(i):
 print('key',i)
 return i%2
def value(i):
 print('value',i)
 return i*10
d={key(i):value(i)for i in range(4)}
print(d)
""")

    def test_numeric_key_identity(self):
        self.compare("""class Box:pass
d={True:'first',1:'second',False:'zero',0:'last'}
print(d,len(d),d[1],d[False],2 in d)
""")

    def test_bytes_keys(self):
        self.compare("""class Box:pass
d={b'a':1,b'b':2}
print(d,d[b'a'],b'b' in d,b'c' not in d)
""")

    def test_none_key(self):
        self.compare("""class Box:pass
d={None:3}
print(d,d[None],None in d)
""")

    def test_missing_key(self):
        self.compare("""class Box:pass
d={'a':1}
print('before')
print(d['missing'])
""")

    def test_unhashable_lookup(self):
        self.compare("""class Box:pass
d={'a':1}
print('before')
print(d[[1]])
""")

    def test_augmented_rhs_rebind(self):
        self.compare("""class Box:pass
d={'a':10}
old=d
def replace():
 global d
 d={'a':99}
 return 7
d['a']+=replace()
print(old,d)
""")

    def test_dict_setdefault_aliases(self):
        self.compare("""class Box:pass
d={}
a=d.setdefault('x',[])
a.append(3)
b=d.setdefault('x',[9])
print(d,a,b,a is b)
""")

    def test_dict_copy(self):
        self.compare("""class Box:pass
a=[1]
d={'x':a}
e=d.copy()
e['y']=[2]
a.append(3)
print(d,e,d is e,d['x'] is e['x'])
""")

    def test_dict_constructor_pairs(self):
        self.compare("""class Box:pass
d=dict([(2,7),(1,3),(2,8)])
print(d)
""")

    def test_dict_acyclic_instance(self):
        self.compare("""class Child:
 def __init__(self,value):self.value=value
class Parent:
 def __init__(self,child):self.data={'x':child}
child=Child(7)
p=Parent(child)
p.data['x'].value=9
print(child.value,p.data['x'] is child)
""")

    def test_set_sorted(self):
        self.compare("""class Box:pass
values=[3,1,3,2]
s=set(values)
print(sorted(s),len(s),bool(s),1 in s,4 not in s)
""")

    def test_set_comprehension(self):
        self.compare("""class Box:pass
s={i%3 for i in range(8) if i%2}
print(sorted(s))
""")

    def test_empty_collections(self):
        self.compare("""class Box:pass
d={}
s=set()
print(d,len(d),bool(d),len(s),bool(s),sorted(s),d.get('x',7),'x' in d)
""")
