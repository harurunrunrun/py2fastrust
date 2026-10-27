"""Public lazy constructor classes and numeric count protocol contracts."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys,itertools,functools,gc\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class StandardIteratorTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="py2fastrust-iterator-types-")
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError("\n".join(map(str, result.diagnostics)))
        source = root / "main.rs"
        source.write_text(result.rust_source, encoding="utf-8")
        cls.binary = root / "main"
        compiled = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)], capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source, capture_output=True, text=True, timeout=30)
        actual = subprocess.run([str(self.binary)], input=source, capture_output=True, text=True, timeout=30)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_all_public_constructor_classes_and_lazy_instances(self):
        self.compare('''
            cases = [
                (itertools.accumulate,([1,2],)), (itertools.batched,([1,2],1)),
                (itertools.chain,([1,2],)), (itertools.combinations,([1,2],1)),
                (itertools.combinations_with_replacement,([1,2],1)),
                (itertools.compress,([1,2],[True,True])), (itertools.count,()),
                (itertools.cycle,([1,2],)), (itertools.dropwhile,(lambda x:False,[1,2])),
                (itertools.filterfalse,(lambda x:False,[1,2])), (itertools.groupby,([1,2],)),
                (itertools.islice,([1,2],2)), (itertools.pairwise,([1,2],)),
                (itertools.permutations,([1,2],1)), (itertools.product,([1,2],)),
                (itertools.repeat,(1,)), (itertools.starmap,(abs,[(-1,),(-2,)])),
                (itertools.takewhile,(lambda x:True,[1,2])), (itertools.zip_longest,([1,2],)),
            ]
            for cls,args in cases:
                value=cls(*args)
                print(cls.__name__,type(cls) is type,type(value) is cls,
                      isinstance(value,cls),issubclass(cls,object),cls.__module__,
                      cls.__qualname__,cls.__base__ is object,cls.__bases__==(object,))
                print(iter(value) is value,hasattr(value,'__dict__'))
                if cls is itertools.groupby:
                    key,group=next(value)
                    print(key,type(group).__name__,type(group).__module__,list(group))
                else: print(next(value))
            a,b=itertools.tee([1,2])
            print(type(itertools.tee).__name__,type(a).__name__,type(a).__module__,iter(a)is a)
            try:isinstance(a,itertools.tee)
            except TypeError:print('tee is a function')
            print(list(a),list(b))
        ''')

    def test_each_iterator_class_can_be_subclassed(self):
        self.compare('''
            cases=[(itertools.accumulate,([1],)),(itertools.batched,([1],1)),
              (itertools.chain,([1],)),(itertools.combinations,([1],1)),
              (itertools.combinations_with_replacement,([1],1)),
              (itertools.compress,([1],[True])),(itertools.count,()),(itertools.cycle,([1],)),
              (itertools.dropwhile,(lambda x:False,[1])),(itertools.filterfalse,(None,[0])),
              (itertools.groupby,([1],)),(itertools.islice,([1],1)),
              (itertools.pairwise,([1,2],)),(itertools.permutations,([1],1)),
              (itertools.product,([1],)),(itertools.repeat,(1,1)),
              (itertools.starmap,(abs,[(-1,)])),(itertools.takewhile,(bool,[1])),
              (itertools.zip_longest,([1],))]
            for base,args in cases:
                cls=type('Child',(base,),{})
                value=cls(*args)
                value.saved=base.__name__
                print(value.saved,type(value)is cls,isinstance(value,base),iter(value)is value)
                if base is itertools.groupby:
                    key,group=next(value);print(key,list(group))
                else:print(next(value))
            class Restricted(itertools.count):__slots__=()
            print(hasattr(Restricted(),'__dict__'))
            class Override(itertools.count):
                def __next__(self):return 91
                def __iter__(self):return iter([3,4])
            value=Override(7)
            print(next(value),list(value),super(Override,value).__next__())
        ''')

    def test_chain_and_partial_generic_aliases(self):
        self.compare('''
            for cls,args in [(itertools.chain,([1,2],)),(functools.partial,(list,))]:
                alias=cls[int]
                print(alias,alias.__origin__ is cls,alias.__args__,alias.__parameters__,type(alias(*args))is cls)
                print(cls.__class_getitem__(str))
            for cls in [itertools.count,itertools.repeat,itertools.accumulate]:
                try:cls[int]
                except TypeError:print(cls.__name__,'not generic')
            class Chain(itertools.chain):pass
            value=Chain.from_iterable([[1],[2,3]])
            print(type(value)is Chain,iter(value)is value,list(value),Chain[str])
            class Partial(functools.partial):pass
            value=Partial[int](list)
            print(type(value)is Partial,value(),value.__orig_class__)
            class Custom(itertools.chain):
                @classmethod
                def __class_getitem__(cls,key):return ('custom',key)
            print(Custom[int])
        ''')

    def test_count_complex_and_integer_subclass_paths(self):
        self.compare('''
            print(list(itertools.islice(itertools.count(1+2j,3j),3)))
            class Integer(int):
                def __int__(self):raise ValueError('conversion must not run')
                def __eq__(self,other):raise ValueError('comparison must not run')
                def __add__(self,other):print('add',other);return 20
            for step in [1,True,2,1.0,Integer(1),0]:
                values=itertools.count(Integer(5),step)
                for i in range(3):
                    value=next(values)
                    print(type(value).__name__,value)
            values=itertools.count(True,2)
            first=next(values)
            print(first is True,next(values),next(values))
        ''')

    def test_count_user_number_acceptance_and_first_next_effect(self):
        self.compare('''
            seen=[]
            class Number:
                def __repr__(self):return 'Number'
                def __int__(self):raise ValueError('not called')
                def __add__(self,other):seen.append(('add',other));gc.collect();return self
                def __radd__(self,other):seen.append(('radd',other));gc.collect();return self
            value=Number()
            first=itertools.count(value)
            second=itertools.count(4,value)
            print('constructed',seen)
            print(next(first)is value,seen)
            print(next(second),seen)
            print(next(second)is value,seen)
            for method in ['__int__','__index__','__float__']:
                cls=type('Number',(),{method:None,'__add__':lambda self,other:self})
                value=cls();print(next(itertools.count(value))is value)
            for namespace in [{'__add__':lambda self,other:self},
                              {'__complex__':lambda self:1j},
                              {'__bool__':lambda self:True}]:
                cls=type('Other',(),namespace)
                try:itertools.count(cls())
                except TypeError:print('not a number')
            class Fails:
                def __index__(self):return 1
                def __add__(self,other):print('add fails');raise LookupError
            values=itertools.count(Fails())
            for i in range(2):
                try:next(values)
                except LookupError:print('error')
        ''')

    def test_partial_public_class_subclass_call_and_readonly_members(self):
        self.compare('''
            cls=functools.partial
            print(cls,type(cls)is type,cls.__name__,cls.__qualname__,cls.__module__,cls.__bases__)
            value=cls(pow,2)
            print(type(value)is cls,isinstance(value,cls),callable(value),value(3),value.func is pow,value.args,value.keywords)
            class Partial(cls):
                def __init__(self,*args,tag=0,**kwargs):self.tag=tag
                def __call__(self,*args,**kwargs):return ('override',args)
            def calculate(a,b,*,tag=0):return a**b+tag
            value=Partial(calculate,2,tag=3)
            print(type(value)is Partial,isinstance(value,cls),value.tag,value(4))
            print(super(Partial,value).__call__(3))
            print(cls.__call__(value,3),cls.func.__get__(value,Partial)is calculate)
            for name in ['func','args','keywords']:
                for action in [lambda:setattr(value,name,3),lambda:delattr(value,name)]:
                    try:action()
                    except AttributeError:print(name,'readonly')
            class Slots(cls):__slots__=()
            value=Slots(int);value.saved=8
            print(value.saved,value.__dict__)
            try:cls(3)
            except TypeError:print('not callable')
            for base in [itertools.count,itertools.chain,cls]:
                try:object.__new__(base)
                except TypeError:print(base.__name__,'unsafe allocation')
                try:base.__new__(object)
                except TypeError:print(base.__name__,'requires subtype')
        ''')

    def test_partial_subclass_flattening_and_descriptor_binding(self):
        self.compare('''
            class Partial(functools.partial):
                def __call__(self,*args,**kwargs):return 'override'
            value=Partial(pow,2)
            flattened=functools.partial(value,3)
            print(flattened.func is pow,flattened.args,flattened())
            value.saved=True
            wrapped=functools.partial(value,3)
            print(wrapped.func is value,wrapped.args,wrapped())
            def calculate(base,owner,power):return base+owner.value+power
            class Holder:
                value=4
                action=functools.partial(calculate,2)
            holder=Holder()
            print(holder.action is Holder.action,holder.action(3),holder.action.__self__ is holder,holder.action.__func__ is Holder.action)
            print(Holder.action.__get__(None,Holder)is Holder.action)
            class Descriptor(functools.partial):
                def __get__(self,obj,owner):return ('override',obj is None,owner.__name__)
            class Holder:action=Descriptor(pow,2)
            print(Holder.action,Holder().action)
            value=functools.partial(pow,2,mod=5)
            value.keywords['mod']=7
            print(value(4),value.args is value.args,value.keywords is value.keywords)
        ''')

    def test_subclass_hooks_and_payloads_remain_gc_roots(self):
        self.compare('''
            released=[]
            class Token:
                def __init__(self,label):self.label=label
                def __del__(self):released.append(self.label)
            class Chain(itertools.chain):
                def __init__(self,*args):gc.collect();self.token=Token('chain')
            class Partial(functools.partial):
                def __init__(self,*args):gc.collect();self.token=Token('partial')
            value=Chain([Token('item')])
            bound=itertools.chain.__next__.__get__(value,Chain)
            del value;gc.collect()
            print(released)
            item=bound();print(item.label)
            del bound;gc.collect();print(sorted(released))
            value=Partial(lambda x:(gc.collect(),x.label)[1],Token('argument'))
            call=functools.partial.__call__.__get__(value,Partial)
            del value;gc.collect()
            print(call(),sorted(released))
            del call,item;gc.collect();print(sorted(released))
        ''')

    def test_public_classes_as_pattern_targets(self):
        self.compare('''
            for value in [itertools.count(),itertools.chain([1]),functools.partial(pow,2),0]:
                match value:
                    case itertools.count():print('count')
                    case itertools.chain():print('chain')
                    case functools.partial(func=function,args=stored,keywords=keywords):
                        print('partial',function is pow,stored,keywords)
                    case _:print('other')
            try:
                match itertools.count():
                    case itertools.count(value):pass
            except TypeError:print('no positional match args')
            try:
                match itertools.tee([]):
                    case itertools.tee():pass
            except TypeError:print('tee is not a class pattern')
        ''')

    def test_aot_standalone_all_integer_modes_and_count_wrapping(self):
        for mode in ["i64", "i128", "bigint"]:
            with self.subTest(mode=mode):
                bits = {"i64": 64, "i128": 128}.get(mode)
                start = 2 ** (bits - 1) - 1 if bits else 2 ** 200
                after = -(2 ** (bits - 1)) if bits else start + 1
                source = textwrap.dedent(f'''
                    from itertools import count, chain
                    from functools import partial
                    class Count(count): pass
                    class Partial(partial): pass
                    value=Count({start})
                    print(next(value),next(value),iter(value)is value,isinstance(value,count))
                    print(list(chain[int]([1],[2])))
                    value=Partial[int](int)
                    print(value(),type(value)is Partial,value.__orig_class__.__origin__ is Partial)
                    values=count(1+2j,3j)
                    print(next(values),next(values),next(values))
                ''')
                result = transpile(source, TranspileOptions(integer=mode, optimize=False))
                self.assertTrue(result.success, result.diagnostics)
                root = Path(self.directory.name)
                rust = root / (mode + ".rs")
                binary = root / mode
                rust.write_text(result.rust_source, encoding="utf-8")
                compiled = subprocess.run(["rustc", "--edition=2021", str(rust), "-o", str(binary)], capture_output=True, text=True, timeout=120)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                self.assertEqual(actual.returncode, 0, actual.stderr)
                self.assertEqual(actual.stdout, f"{start} {after} True True\n[1, 2]\n0 True True\n(1+2j) (1+5j) (1+8j)\n")


if __name__ == "__main__":
    unittest.main()
