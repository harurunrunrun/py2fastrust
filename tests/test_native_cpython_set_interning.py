"""Raw CP-first interning boundaries, recursion exemptions and order erasure."""
import os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path

WORDS="{'apple','banana','cherry','damson','elderberry','fig','grape'}"
REVERSED="{'grape','fig','elderberry','damson','cherry','banana','apple'}"
BOUNDARIES={
 'reused_comparator':'class Probe:\n def __contains__(self,values):\n  print(list(values))\n  return True\nprint("apple"in '+WORDS+'in Probe())\n',
 'observed':'print(list('+WORDS+'))\n',
 'identifiers':'apple=banana=cherry=damson=elderberry=fig=grape=0\nprint(list('+WORDS+'))\n',
 'published_alias':'s='+WORDS+'\na=list(s)\na.sort()\nprint(a,list(s))\n',
 'callback':'def key(value):\n print(value)\n return 0\nprint(sorted('+WORDS+',key=key))\n',
 'shadowed_sorted':'def sorted(values):\n print(list(values))\n return 0\nprint(sorted('+WORDS+'))\n',
 'original_seed_fixture':'print("source")\ns={"a","bb","ccc","dddd"}\niterator=iter(s)\nprint(sorted(s))\n',
 'original_ascii_fixture':'s={"a","bb","ccc"}\nprint(list(s))\n',
}
CASES={
 'dynamic':'apple=banana=cherry=0\nprint(list(set(["apple","banana","cherry","damson","fig"])))\n',
 'singleton_strings':'a=b=c=0\nprint(list({"","a","b","c","0","1","_"}))\n',
 'nonword_strings':'print(list({"apple-tree","banana fruit","cherry!","damson:plum","fig/jam"}))\n',
 'unicode_strings':'print(list({"éé","ĀĀ","😀😀","ÿ","a\\x00é"}))\n',
 'tuple_strings':'apple=banana=cherry=damson=0\nprint(list({("apple",0),("banana",8),("cherry",16),("damson",24)}))\n',
 'bytes':'apple=banana=cherry=damson=0\nprint(list({b"apple",b"banana",b"cherry",b"damson"}))\n',
 'numeric':'print(list({0,8,16,24,32}))\nprint(list({None}),list({()}))\n',
 'sorted_temporary':'class Marker:pass\nprint(sorted('+WORDS+'))\n',
 'sorted_list':'class Marker:pass\na=list('+WORDS+')\na.sort()\nprint(a)\n',
 'sorted_alias':'class Marker:pass\ncollect=list\na=collect('+WORDS+')\na.sort()\nprint(a)\n',
 'sorted_local':'class Marker:pass\ndef run():\n s='+WORDS+'\n return sorted(s)\nprint(run())\n',
 'sorted_forwarding':'class Marker:pass\ndef erase(items):\n items.sort()\ndef run():\n a=list('+WORDS+')\n erase(a)\n return a\nprint(run())\n',
 'sorted_mixed':'class Marker:pass\nprint(sorted('+WORDS+'),sorted('+REVERSED+'))\n',
 'closed_membership':'class Marker:pass\nword="apple"\nprint(word in '+WORDS+',"pear"not in '+WORDS+')\n',
}


@unittest.skipUnless(shutil.which('rustc')and sys.implementation.name=='cpython'and sys.version_info[:3]==(3,14,4),'CPython3.14.4 and rustc are required')
class StringConstantHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-set-interning-');cls.root=Path(cls.directory.name)
        cls.oracles={(name,seed):subprocess.run([sys.executable,'-B','-c',source],env={**os.environ,'PYTHONHASHSEED':str(seed),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=10)
                     for name,source in {**BOUNDARIES,**CASES}.items()for seed in (0,1,42,4294967295)}
        assert all(item.returncode==0 for item in cls.oracles.values())

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def test_observable_unproved_string_histories_are_positioned_boundaries(self):
        from py2fastrust import transpile,TranspileOptions
        for name,source in BOUNDARIES.items():
            for mode in ('i64','i128','bigint'):
                for optimize in (False,True):
                    with self.subTest(name=name,mode=mode,optimize=optimize):
                        result=transpile(source,TranspileOptions(filename='interning.py',integer=mode,optimize=optimize,license='none'))
                        self.assertFalse(result.success);self.assertIsNone(result.rust_source)
                        self.assertTrue(all(item.code=='E006'and item.line>0 for item in result.diagnostics))
                        self.assertIn('CodeType string interning',result.diagnostics[0].message)

    def exercise(self,name):
        from py2fastrust import transpile,TranspileOptions
        source=CASES[name]
        for mode in ('i64','i128','bigint'):
            result=transpile(source,TranspileOptions(filename='interning.py',integer=mode,license='none',string_mode='unicode'if name=='unicode_strings'else'ascii'))
            self.assertTrue(result.success,str(result.diagnostics));rust=self.root/(name+'_'+mode+'.rs');rust.write_text(result.rust_source)
            for optimized in (False,True):
                binary=rust.with_suffix('.O'if optimized else'.debug')
                built=subprocess.run(['rustc','--edition=2021',*(['-O']if optimized else[]),str(rust),'-o',str(binary)],capture_output=True,text=True,timeout=90)
                self.assertEqual(built.returncode,0,built.stderr[:12000])
                for seed in (0,1,42,4294967295):
                    ran=subprocess.run([str(binary)],env={**os.environ,'PYTHONHASHSEED':str(seed),'PATH':'/no-python-runtime'},capture_output=True,text=True,timeout=10);expected=self.oracles[name,seed]
                    self.assertEqual((ran.returncode,ran.stdout,ran.stderr),(expected.returncode,expected.stdout,expected.stderr),(name,mode,optimized,seed))


for _name in CASES:setattr(StringConstantHistory,'test_'+_name,lambda self,name=_name:self.exercise(name))
