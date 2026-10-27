"""Collections share native dict data while retaining subtype-specific order."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile
import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class CollectionSemanticsTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source, **kwargs):
        source=textwrap.dedent(source)
        return self.run_source(source+"\nexec("+repr(source)+", {})\n",**kwargs)

    def test_namedtuple_unicode_identifiers_raw_fields_and_normalized_parameters(self):
        self.compare('''
            from collections import namedtuple
            for typename, fields in [('A', ['á']), ('Ａ', ['日本語','á']),
                                     ('P', ['𝒊𝒇']), ('P', ['＿x']), ('P', ['K']),
                                     ('P', ['x²']), ('P', ['K','K']), ('P', ['class'])]:
                try:
                    cls=namedtuple(typename,fields)
                    value=cls(*range(len(fields)))
                    print(cls.__name__,cls._fields,value,tuple(getattr(value,f) for f in fields))
                except Exception as error:print(type(error).__name__)
            cls=namedtuple('Renamed',['á','á','x²','class','_bad','ok'],rename=True)
            print(cls._fields,cls(1,2,3,4,5,6),cls._field_defaults)
            for defaults in [None,[],[7]]:
                cls=namedtuple('P','x',defaults=defaults)
                print(cls.__new__.__defaults__,cls._field_defaults,cls(3))
        ''')

    def test_namedtuple_caller_module_across_bundled_aot_and_dynamic_calls(self):
        module='''from collections import namedtuple
AtImport=namedtuple('AtImport','x')
def create(): return namedtuple('FromFunction','x')
class Factory:
 @staticmethod
 def create(): return namedtuple('FromMethod','x')
'''
        source='''from collections import namedtuple
import package_fixture
print(package_fixture.AtImport.__module__,package_fixture.create().__module__,package_fixture.Factory.create().__module__)
space={'__name__':'runtime_namespace','namedtuple':namedtuple}
exec("Dynamic=namedtuple('Dynamic','x')",space)
print(space['Dynamic'].__module__)
print(namedtuple('Explicit','x',module='chosen').__module__)
class ModuleName(str):pass
names=[ModuleName('subclass_name'),17,None,'',False]
for name in names:
 namespace={'__name__':name,'namedtuple':namedtuple}
 exec("Generated=namedtuple('Generated','x')",namespace)
 result=namespace['Generated'].__module__
 print(result,type(result).__name__,result is name)
'''
        with tempfile.TemporaryDirectory(prefix='collections-modules-') as tmp:
            root=Path(tmp);(root/'package_fixture.py').write_text(module)
            result=transpile(source,TranspileOptions(filename=str(root/'main.py'),module_paths=(root,),optimize=False))
            self.assertTrue(result.success,result.diagnostics)
            target=root/'main.rs';target.write_text(result.rust_source)
            built=subprocess.run(['rustc','--edition=2021',str(target),'-o',str(root/'main')],capture_output=True,text=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stderr)
            actual=subprocess.run([str(root/'main')],capture_output=True,text=True,timeout=15)
            expected=subprocess.run([sys.executable,'-I','-c',f'import sys;sys.path.insert(0,{str(root)!r});exec({source!r})'],capture_output=True,text=True,timeout=15)
            self.assertEqual(actual.returncode,expected.returncode,actual.stderr)
            self.assertEqual(actual.stdout,expected.stdout)

    def test_native_dict_base_descriptors_and_aliases_observe_same_data(self):
        self.compare('''
            from collections import defaultdict,Counter,OrderedDict
            for cls in [defaultdict,Counter,OrderedDict]:
                d=cls(None,a=1,b=2) if cls is defaultdict else cls(a=1,b=2)
                alias=d
                dict.__setitem__(d,'a',7)
                dict.__setitem__(d,'base',9)
                print(cls.__name__,alias is d,d['a'],dict.__getitem__(d,'a'),len(d),list(d))
                print(list(dict.keys(d)),list(dict.values(d)),list(dict.items(d)),dict.get(d,'base'),dict.copy(d))
                print(dict.setdefault(d,'new',11),list(dict.keys(d)),list(d))
                dict.update(d,{'a':13,'base2':17})
                print(d['a'],dict.get(d,'base2'),list(dict.keys(d)),list(d))
                print(dict.pop(d,'base2'),dict.get(d,'absent',19))
                for get in [lambda:d['absent'],lambda:dict.__getitem__(d,'absent'),lambda:dict.get(d,'absent')]:
                    try:print(get())
                    except Exception as error:print(type(error).__name__)
                d.clear()
                print(len(d),list(d),list(dict.keys(d)))
        ''')

    def test_defaultdict_mutable_factory_native_missing_and_subclass_protocols(self):
        self.compare('''
            from collections import defaultdict,Counter
            events=[]
            class D(defaultdict):
                def __setitem__(self,k,v):events.append(('set',k));super().__setitem__(k,v)
            d=D(list,a=[1]);d.update(b=[2])
            print(events,d['x'],events,dict.__getitem__(d,'y'),events)
            print(dict.get(d,'z'),list(d),d.default_factory is list)
            d.default_factory=lambda:23
            print(d['new'])
            del d.default_factory
            print(d.default_factory)
            try:d['last']
            except Exception as error:print(type(error).__name__)
            d.default_factory=int
            copied=d.copy()
            print(type(copied).__name__,copied.default_factory is int,copied['zero'],copied['a'] is d['a'])
            print(hasattr(defaultdict(None),'__dict__'),Counter().__dict__)
            events=[]
            class Attributes(defaultdict):
                def __setattr__(self,k,v):events.append(('set',k));super().__setattr__(k,v)
                def __getattribute__(self,k):
                    if k=='default_factory':events.append(('get',k))
                    return super().__getattribute__(k)
            value=Attributes(list)
            print('factory init',events)
            events.clear();print(value['x'],events)
            events.clear();del value.default_factory;print('factory del',events)
            class Property(defaultdict):
                @property
                def default_factory(self):return lambda:99
                @default_factory.setter
                def default_factory(self,v):events.append('property set')
                @default_factory.deleter
                def default_factory(self):events.append('property delete')
            events.clear();value=Property(list)
            print('factory property',events,value['x'],defaultdict.default_factory.__get__(value,Property) is list)
            events.clear();del value.default_factory
            print('factory property delete',events,defaultdict.default_factory.__get__(value,Property) is list)
            for value in [defaultdict(list),dict.__new__(defaultdict)]:
                defaultdict.default_factory.__delete__(value)
                print('factory descriptor delete',value.default_factory)
                defaultdict.default_factory.__delete__(value)
                print(value.default_factory)
            class C(Counter):
                def __missing__(self,k):return 37
            c=C(a=1)
            print(c['missing'],dict.__getitem__(c,'missing'),c.get('missing'),list(c))
            del c['absent']
            try:dict.__delitem__(c,'absent')
            except Exception as error:print(type(error).__name__)
        ''')

    def test_ordereddict_keeps_native_insertion_order_separate_from_node_order(self):
        self.compare('''
            from collections import OrderedDict
            d=OrderedDict(a=1,b=2,c=3)
            alias=d
            d.move_to_end('a')
            d.move_to_end('c',False)
            print(list(d),list(dict.keys(d)),list(d.items()),alias is d)
            print(list(d.copy()),list(dict.copy(d)))
            dict.__setitem__(d,'ghost',7)
            print(len(d),list(d),list(dict.keys(d)),d['ghost'])
            print(list(d.copy()),dict.copy(d))
            for action in [lambda:d.move_to_end('ghost'),lambda:d.pop('ghost')]:
                try:action()
                except Exception as error:print(type(error).__name__)
            del d['ghost']
            print(list(dict.keys(d)),list(d))
            print(d.popitem(False),d.popitem(),list(d),list(dict.keys(d)))
            d.clear();print(d,list(dict.keys(d)))
            class O(OrderedDict):
                def __setitem__(self,k,v):events.append(k);super().__setitem__(k,v)
            events=[]
            value=O(a=1);value.update(b=2);dict.update(value,c=3)
            print(events,list(value),list(dict.keys(value)),value.__dict__)
        ''')

    def test_base_mutation_invalidates_live_views_and_iterators(self):
        self.compare('''
            from collections import defaultdict,Counter,OrderedDict
            for cls in [defaultdict,Counter,OrderedDict]:
                d=cls(None,a=1,b=2) if cls is defaultdict else cls(a=1,b=2)
                keys,items=d.keys(),d.items()
                iterator=iter(keys)
                print(next(iterator))
                dict.__setitem__(d,'c',3)
                try:print(next(iterator))
                except Exception as error:print(type(error).__name__)
                print(len(keys),list(keys),list(dict.keys(d)))
                iterator=iter(items)
                dict.__setitem__(d,'a',9)
                print(next(iterator))
                dict.__delitem__(d,'b')
                try:print(next(iterator))
                except Exception as error:print(type(error).__name__)
                d.clear()
                print(len(keys))
        ''')

    def test_stored_key_identity_hashes_and_comparison_effects(self):
        self.compare('''
            from collections import defaultdict,Counter,OrderedDict
            for cls in [defaultdict,Counter,OrderedDict]:
                events=[]
                class Key:
                    def __init__(self,n):self.n=n
                    def __hash__(self):events.append(('hash',self.n));return 7
                    def __eq__(self,o):events.append(('eq',self.n,o.n));return self.n==o.n
                d=cls(None) if cls is defaultdict else cls()
                first=Key(1);same=Key(1);other=Key(2)
                for action in [lambda:d.__setitem__(first,3),lambda:d.__setitem__(same,4),
                               lambda:d.__setitem__(other,5),lambda:d[first],lambda:d.get(first),
                               lambda:first in d]:
                    events.clear();action();print(cls.__name__,events)
                events.clear();keys=list(d);print(events,keys[0] is first)
                events.clear();copied=dict.copy(d);print(events,next(iter(copied)) is first)
                events.clear();del d[same];print(events,len(d))
        ''')

    def test_hash_and_equality_errors_do_not_invoke_missing_or_mutate_data(self):
        self.compare('''
            from collections import defaultdict,Counter,OrderedDict
            events=[]
            class HashError:
                def __hash__(self):events.append('hash');raise KeyError('hash failed')
            class EqualityError:
                def __hash__(self):return 31
                def __eq__(self,other):events.append('eq');raise KeyError('comparison failed')
            def factory():events.append('factory');return []
            for cls in [defaultdict,Counter,OrderedDict]:
                d=cls(factory) if cls is defaultdict else cls()
                events.clear()
                try:d[HashError()]
                except Exception as error:print(cls.__name__,type(error).__name__,error.args,events,len(d))
                key=EqualityError();d[key]=7;events.clear()
                try:dict.__getitem__(d,EqualityError())
                except Exception as error:print(type(error).__name__,error.args,events,len(d),d[key])
        ''')

    def test_ordered_mutation_uses_stored_keys_and_hashes(self):
        self.compare('''
            from collections import OrderedDict
            events=[]
            class Key:
                def __init__(self,n):self.n=n
                def __hash__(self):events.append(('hash',self.n));return 7
                def __eq__(self,other):events.append(('eq',self.n,other.n));return self.n==other.n
            for operation in ['move','pop','popitem','setdefault','clear']:
                first,second=Key(1),Key(2)
                d=OrderedDict([(first,3),(second,5)]);events.clear()
                if operation=='move':d.move_to_end(Key(2),False);value=d[second]
                elif operation=='pop':value=d.pop(Key(2))
                elif operation=='popitem':
                    pair=d.popitem();value=pair[1];print(pair[0] is second)
                elif operation=='setdefault':value=d.setdefault(Key(2),11)
                else:value=d.clear()
                print(operation,value,events,len(d))
        ''')

    def test_base_views_keep_subclass_attributes_and_cycles_alive(self):
        self.compare('''
            import gc
            from collections import Counter
            events=[]
            class Held(Counter):
                def __del__(self):events.append('finalized')
            def create(kind):
                value=Held(a=1)
                value.cycle=value
                view=dict.keys(value)
                if kind==0:return view
                if kind==1:return iter(view)
                return view.mapping
            for kind in [0,1,2]:
                held=create(kind)
                gc.collect()
                print(events,list(held))
                del held
                gc.collect()
                print(events)
        ''')

    def test_base_view_mapping_proxy_preserves_original_subclass_protocols(self):
        self.compare('''
            from collections import defaultdict,Counter,OrderedDict
            for cls in [defaultdict,Counter,OrderedDict]:
                d=cls(None,a=1,b=2) if cls is defaultdict else cls(a=1,b=2)
                proxy=dict.keys(d).mapping
                print(str(proxy),repr(proxy),type(proxy.copy()).__name__,list(proxy))
                print(dict(proxy),proxy.get('missing',7),list(proxy.values()))
            class D(defaultdict):
                def __iter__(self):return iter(['other'])
                def __getitem__(self,k):return ('value',k)
                def keys(self):return ['custom']
                def get(self,k,default=None):return ('get',k)
                def __len__(self):return 9
                def __contains__(self,k):return k=='present'
                def __reversed__(self):return iter(['reverse'])
                def __repr__(self):return 'CUSTOM'
            d=D(None)
            proxy=dict.keys(d).mapping
            print(repr(proxy),str(proxy),len(proxy),bool(proxy),list(proxy),list(reversed(proxy)))
            print(proxy['x'],proxy.get('x'),list(proxy.keys()),'present' in proxy,'a' in proxy)
            for receiver in [[],(),set(),1]:
                for action in [lambda:dict.copy(receiver),lambda:dict.clear(receiver),lambda:dict.__setitem__(receiver,0,1)]:
                    try:action()
                    except Exception as error:print(type(error).__name__)
        ''')

    def test_dictionary_payload_key_value_and_order_nodes_are_gc_roots(self):
        self.compare('''
            import gc
            from collections import defaultdict,Counter,OrderedDict
            for cls in [defaultdict,Counter,OrderedDict]:
                class Key:
                    def __hash__(self):gc.collect();return 17
                    def __eq__(self,other):gc.collect();return self is other
                key=Key();d=cls(None) if cls is defaultdict else cls()
                d[key]=[d]
                alias=d
                gc.collect()
                print(alias[key][0] is d,next(iter(dict.keys(d))) is key)
                if cls is OrderedDict:
                    d.move_to_end(key)
                    print(d.popitem()[0] is key)
                d.clear()
        ''',integer='bigint')


if __name__=='__main__':unittest.main()
