"""Live view cursors, tuple materialization and mapping ownership interaction."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from py2fastrust import transpile,TranspileOptions


class MappingViewDiagnostics(unittest.TestCase):
    def test_floating_query_is_not_misclassified_as_an_unhashable_key(self):
        result=transpile("class Marker:pass\nd={1:7}\nprint(d[1.0])\n")
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertIn('floating/custom hash',result.diagnostics[0].message)
        self.assertIn('key=float',result.diagnostics[0].message)

    def test_heterogeneous_key_schema_is_a_positioned_diagnostic(self):
        result=transpile("class Marker:pass\nd={(1,2):7,():9}\nprint(d)\n")
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertEqual(result.diagnostics[0].line,2)
        self.assertIn('heterogeneous',result.diagnostics[0].message)

    def test_live_view_ownership_cycle_is_rejected(self):
        result=transpile("class Marker:pass\nd={}\nd['self']=d.items()\n")
        self.assertFalse(result.success)
        self.assertEqual(result.diagnostics[0].code,'E006')
        self.assertRegex(result.diagnostics[0].message,'cycle|recursive')


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MappingViewExecutionTests(unittest.TestCase):
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


    def test_items_unpack(self):
        self.compare("""class Marker:pass
d={(1,2):7,(3,4):9}
for (a,b),value in d.items():print(a,b,value)
print([key[0]+value for key,value in d.items()])
""")

    def test_saved_views_are_live(self):
        self.compare("""class Marker:pass
d={'a':1}
keys=d.keys()
values=d.values()
items=d.items()
d['a']=5
d['b']=9
print(list(keys),list(values),list(items),len(keys),bool(values))
""")

    def test_size_change_error(self):
        self.compare("""class Marker:pass
d={'a':1,'b':2}
for key in d:
 print(key)
 d['c']=3
""")

    def test_break_after_size_change(self):
        self.compare("""class Marker:pass
d={'a':1,'b':2}
for key in d:
 print(key)
 d['c']=3
 break
print(d)
""")

    def test_cursor_creation_before_later_argument(self):
        self.compare("""class Marker:pass
d={'a':1}
def change():
 d['b']=2
 return 9
print(next(iter(d),change()))
""")

    def test_finite_mapping_view_union(self):
        self.compare("""class Marker:pass
def choose(flag):
 if flag:return {'a':3,'b':4}
 return {'x':8}
for flag in [False,True]:
 d=choose(flag)
 print(list(d.items()),list(d),list(d.values()))
""")

    def test_empty_views(self):
        self.compare("""class Marker:pass
d={}
print(list(d.keys()),list(d.values()),list(d.items()),len(d.items()),bool(d.keys()))
""")

    def test_frequency_counts(self):
        self.compare("""class Marker:pass
counts={}
for word in ['cat','dog','cat','owl','dog','cat']:
 counts[word]=counts.get(word,0)+1
for word,count in sorted(counts.items()):print(word,count)
""")

    def test_runtime_tuple_identity(self):
        self.compare("""class Marker:pass
a=tuple([2,3])
b=tuple(a)
c=tuple([2,3])
print(a,b,a is b,a is c,a==c)
print(tuple([]) is tuple([]),tuple()==tuple([]))
""")

    def test_fixed_key_runtime_query_separate_families(self):
        self.compare("""class Marker:pass
d={(1,2):7}
e={():9}
print(d[tuple([1,2])],e[tuple([])],d.get(tuple([1]),-1),tuple([1,2]) in d)
""")

    def test_nested_query_key_layouts(self):
        self.compare("""class Marker:pass
d={((1,2),(3,4)):8}
key=tuple([tuple([1,2]),tuple([3,4])])
print(d[key],key in d,d.get(tuple([tuple([1,2])]),-1))
""")

    def test_mutable_tuple_materialization(self):
        self.compare("""class Marker:pass
a=[3]
t=tuple([a,a])
t[0].append(4)
print(t,a,t[0] is t[1])
""")

    def test_iterator_tuple(self):
        self.compare("""class Marker:pass
def doubled(x):return x*2
it=map(doubled,[2,3,4])
print(tuple(it),tuple(it))
""")

    def test_varargs_and_mapping_runtime(self):
        self.compare("""class Marker:pass
def f(*xs):return len(xs)
d={1:2}
print(f(4,5),d[1])
""")

    def test_key_tuple_nested_unhashable(self):
        self.compare("""class Marker:pass
d={(1,2):3}
print(d[(1,[])])
""")

    def test_returned_alias(self):
        self.compare("""def same(value):return value
d={1:2}
e=same(d)
e[1]=9
print(d,e,d is e)
""")

    def test_mutable_mapping_parameter(self):
        self.compare("""def add(counts,word):
 counts[word]=counts.get(word,0)+1
counts={}
for word in ['a','b','a']:add(counts,word)
print(counts)
""")

    def test_set_parameter_alias(self):
        self.compare("""def same(values):return values
values={2,4}
other=same(values)
other.add(8)
print(sorted(values),other is values)
""")

    def test_mapping_as_closure_argument(self):
        self.compare("""def outer(counts):
 def add(key):counts[key]=counts.get(key,0)+1
 return add
counts={}
f=outer(counts)
f('a')
f('a')
print(counts)
""")

    def test_plain_mutable_tuple_materialization_and_view_identity(self):
        self.compare("""a=[3]
t=tuple([a,a])
t[0].append(4)
print(t,a,t[0] is t[1])
d={'a':1}
view=d.keys()
alias=view
print(view is alias,view is d.keys())
""")
