"""Container formatting keeps callbacks, cursors, cycle guards and GC on heap."""
from pathlib import Path
import shutil,subprocess,sys,tempfile,textwrap,unittest
from py2fastrust import TranspileOptions,transpile
WRAPPER='import sys,gc,types\nexec(sys.stdin.read())\n'
@unittest.skipUnless(shutil.which('rustc'),'rustc required')
class ProtocolRepresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='pytors-repr-protocol-');root=Path(cls.directory.name)
        result=transpile(WRAPPER,TranspileOptions(optimize=False))
        if not result.success:raise AssertionError(result.diagnostics)
        source=root/'main.rs';source.write_text(result.rust_source);cls.binary=root/'main'
        build=subprocess.run(['rustc','--edition=2021',str(source),'-o',str(cls.binary)],capture_output=True,text=True,timeout=120)
        if build.returncode:raise AssertionError(build.stderr)
    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()
    def compare(self,source):
        source=textwrap.dedent(source);expected=subprocess.run([sys.executable,'-I','-c',WRAPPER],input=source,capture_output=True,text=True,timeout=40);actual=subprocess.run([str(self.binary)],input=source,capture_output=True,text=True,timeout=40)
        self.assertEqual(expected.returncode,0,expected.stderr);self.assertEqual(actual.returncode,0,actual.stderr);self.assertEqual(actual.stdout,expected.stdout,actual.stderr)
    def test_recursive_repr_container_wrappers_and_fstrings(self):
        self.compare('''
            class Recursive:
                def __init__(self,mode):self.mode=mode
                def __repr__(self):
                    if self.mode=='list':return repr([self])
                    if self.mode=='dict':return repr({1:self})
                    if self.mode=='tuple':return repr((self,))
                    if self.mode=='set':return repr({self})
                    if self.mode=='fstring':return f'{[self]!r}'
                    if self.mode=='proxy':return repr({'x':self}.keys().mapping)
                    if self.mode=='exception':return repr(ValueError(self))
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for mode in ['list','dict','tuple','set','fstring','proxy','exception']:
                    try:repr(Recursive(mode))
                    except RecursionError:print(limit,mode,'caught')
        ''')
    def test_live_list_dictionary_and_snapshot_set(self):
        self.compare('''
            for kind in ['list','dict','set']:
                class Item:
                    def __repr__(self):
                        if kind=='list':container.append(3)
                        elif kind=='dict':container[3]=4
                        else:container.add(3)
                        return 'item'
                item=Item();container=[item] if kind=='list' else ({item:2} if kind=='dict' else {item})
                print(kind,repr(container))
            d={}
            class Key:
                def __hash__(self):return 1
                def __repr__(self):d.clear();d['new']=2;return 'key'
            key=Key();d[key]='old';print(repr(d))
        ''')
    def test_shared_cycles_and_callbacks_keep_original_values_alive(self):
        self.compare('''
            values=[];values.append(values);d={};d['self']=d
            print(repr(values),str(values),repr(d));print(repr((values,)))
            class Value:
                def __repr__(self):gc.collect();return 'value'
            value=Value();print(repr([value,value]),repr({1:value}),repr({value}),ascii([value]))
            print(repr(ValueError(value)),str(ValueError(value)),str(ValueError(value,value)))
        ''')
    def test_format_and_explicit_native_methods(self):
        self.compare('''
            class Recursive:
                def __format__(self,spec):return format(self,spec)
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                try:format(Recursive(),'x')
                except RecursionError:print(limit,'format caught')
            class Value:
                def __repr__(self):return '雪'
            value=Value();print(f'{[value]!a:>10}',list.__repr__([value]),tuple.__repr__((value,)))
        ''')
