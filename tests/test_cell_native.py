"""CellType metadata, native descriptors, and suspended rich comparisons."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions, transpile


WRAPPER = "import sys\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class CellNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="pytors-cell-native-")
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        source = Path(cls.tmp.name) / "main.rs"
        source.write_text(result.rust_source)
        cls.binary = source.with_suffix("")
        built = subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source,
                                  capture_output=True, text=True, timeout=30)
        actual = subprocess.run([str(self.binary)], input=source,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_class_metadata_and_owned_descriptors(self):
        self.compare('''
            import types,gc
            C=types.CellType;c=C()
            print(C,type(C),C.__class__,c.__class__ is C,type(c) is C)
            print(isinstance(C,type),isinstance(c,C),issubclass(C,object))
            print(C.__name__,C.__qualname__,C.__module__,C.__base__)
            print(C.__bases__,C.__mro__,C.mro())
            print(C.__bases__ is C.__bases__,C.__mro__ is C.__mro__)
            print(C.__basicsize__,C.__itemsize__,C.__flags__,C.__dictoffset__,C.__weakrefoffset__)
            print(C.__text_signature__,C.__type_params__,C.__hash__)
            print(list(C.__dict__),dir(C),dir(c))
            for name in ['__new__','__repr__','__eq__','__ne__','__lt__','__le__','__gt__','__ge__','cell_contents']:
                d=getattr(C,name)
                print(name,d is C.__dict__[name],type(d),type(d).__name__,d.__name__,d.__qualname__)
                print(d.__name__ is d.__name__,d.__qualname__ is d.__qualname__)
                print(d.__doc__)
                if name!='__new__':print(d.__objclass__ is C,d.__get__(None,C) is d)
                if name!='cell_contents':print(d.__text_signature__)
            print(C.__new__.__self__ is C,C.__new__.__module__ is None)
            print(C.__init__ is object.__init__,C.__sizeof__ is object.__sizeof__)
            print(C.__call__(7).cell_contents,C.__subclasses__(),C.__instancecheck__(c),C.__subclasscheck__(C))
            print(C.__doc__==c.__doc__,C.__sizeof__(c),c.__sizeof__())
            print(type(c.__eq__).__name__,c.__eq__.__self__ is c,c.__eq__.__objclass__ is C)
            print(c.__eq__.__doc__,c.__eq__.__text_signature__)
            print(c.__eq__.__name__ is c.__eq__.__name__,c.__eq__.__qualname__ is c.__eq__.__qualname__)
            bases=C.__bases__;mro=C.__mro__;doc=C.__doc__;del c;gc.collect()
            print(bases is C.__bases__,mro is C.__mro__,doc is C.__doc__)
        ''')

    def test_implicit_class_string_uses_metaclass_slot(self):
        self.compare('''
            import types
            C=types.CellType
            import itertools
            for value in (C,type,object,int,str,list,dict,bytearray,memoryview,itertools.count,ValueError):
                print(str(value)==repr(value))
            print(str(C),repr(C),format(C),f"{C}")
            print(C.__str__(C),type(C).__str__(C))
            class Text(str):pass
            print(Text(C))
            try:C.__str__()
            except TypeError as error:print(type(error).__name__)
        ''')

    def test_constructor_and_final_class(self):
        self.compare('''
            from types import CellType as C
            c=C.__new__(C,12);print(c.cell_contents,C.__init__(c,1,2,a=3),c.cell_contents)
            print(C.__init__(1,1,2,a=3))
            for action in [lambda:C.__new__(),lambda:C.__new__(1),lambda:C.__new__(object),
                           lambda:C.__new__(C,1,2),lambda:C.__new__(C,contents=1),
                           lambda:C(1,2),lambda:C(contents=1),lambda:object.__new__(C),
                           lambda:type('Child',(C,),{}),lambda:setattr(C,'x',1),
                           lambda:delattr(C,'__eq__'),lambda:setattr(c,'x',1),
                           lambda:hash(c),lambda:getattr(C,'__annotations__'),lambda:getattr(C,'__annotate__')]:
                try:action()
                except Exception as e:print(type(e).__name__)
            for action in [lambda:C.__new__(),lambda:C.__new__(1),lambda:C.__new__(object),
                           lambda:C.__new__(C,1,2),lambda:C.__new__(C,contents=1),lambda:C(1,2),lambda:C(contents=1)]:
                try:action()
                except Exception as e:print(str(e))
        ''')

    def test_writable_getset_binding_and_errors(self):
        self.compare('''
            from types import CellType as C
            d=C.cell_contents;c=C()
            print(type(d).__name__,d.__objclass__ is C,d.__doc__)
            print(callable(d))
            print(d.__get__(None,C) is d,d.__get__(None,1) is d)
            print(d.__set__(c,3),d.__get__(c),d.__get__(c,int))
            print(d.__delete__(c),d.__delete__(c))
            for action in [lambda:d(c),lambda:d.__get__(c),lambda:d.__get__(),lambda:d.__get__(None),
                           lambda:d.__get__(None,None),lambda:d.__get__(1),lambda:d.__get__(c,C,1),
                           lambda:d.__get__(c,x=1),lambda:d.__set__(1,2),lambda:d.__set__(c),
                           lambda:d.__set__(c,1,2),lambda:d.__set__(c,2,x=1),
                           lambda:d.__delete__(1),lambda:d.__delete__(),lambda:d.__delete__(c,1),
                           lambda:d.__delete__(c,x=1)]:
                try:action()
                except Exception as e:print(type(e).__name__,str(e))
            d.__set__(c,c);print(c.cell_contents is c);del c.cell_contents
            c.cell_contents=9;print(d.__get__(c));d.__delete__(c)
        ''')

    def test_rich_descriptors_preserve_result_and_validate_receiver(self):
        self.compare('''
            from types import CellType as C
            marker=object()
            class Contents:
                def __eq__(self,other):print('eq');return marker
                def __ne__(self,other):print('ne');return marker
                def __lt__(self,other):print('lt');return marker
                def __le__(self,other):print('le');return marker
                def __gt__(self,other):print('gt');return marker
                def __ge__(self,other):print('ge');return marker
            value=Contents();a=C(value);b=C(value)
            for name in ['__eq__','__ne__','__lt__','__le__','__gt__','__ge__']:
                d=getattr(C,name)
                print(d(a,b) is marker,d(a,a) is marker,getattr(a,name)(b) is marker)
                print(d(a,1) is NotImplemented)
                for action in [lambda:d(),lambda:d(1,a),lambda:d(a),lambda:d(a,b,b),
                               lambda:d(a,b,x=1),lambda:d.__get__(1,C)]:
                    try:action()
                    except Exception as e:print(type(e).__name__,str(e))
            print((a==b) is marker,(a!=b) is marker,(a<b) is marker,
                  (a<=b) is marker,(a>b) is marker,(a>=b) is marker)
            print([value is marker for value in map(C.__eq__,[a,a],[b,b])])
        ''')

    def test_empty_cells_and_notimplemented(self):
        self.compare('''
            from types import CellType as C
            for a,b in [(C(),C()),(C(),C(1)),(C(1),C())]:
                print(a==b,a!=b,a<b,a<=b,a>b,a>=b)
                print([getattr(C,name)(a,b) for name in ['__eq__','__ne__','__lt__','__le__','__gt__','__ge__']])
            class Refuse:
                def __eq__(self,other):print('eq');return NotImplemented
                def __ne__(self,other):print('ne');return NotImplemented
                def __lt__(self,other):print('lt');return NotImplemented
                def __gt__(self,other):print('gt');return NotImplemented
            a=C(Refuse());b=C(Refuse())
            print(a==b,a!=b)
            for action in [lambda:a<b,lambda:C.__lt__(a,b)]:
                try:action()
                except Exception as e:print(type(e).__name__,str(e))
            print(C.__eq__(C(),1) is NotImplemented,C.__lt__(C(),1) is NotImplemented)
        ''')

    def test_repr_does_not_call_contents(self):
        self.compare('''
            from types import CellType as C
            from functools import partial
            from itertools import count
            def clean(s):
                parts=s.split('0x');result=parts[0]
                for part in parts[1:]:
                    index=0
                    while index<len(part) and part[index] in '0123456789abcdef':index+=1
                    result+='0xADDR'+part[index:]
                return result
            class Contents:
                def __repr__(self):raise RuntimeError('repr callback')
            for c in [C(),C(None),C(2),C('x'),C(Contents()),C(partial(int)),C(count()),C(list[int]),C(int|str),C((lambda:0).__code__)]:
                print(clean(repr(c)),clean(str(c)),clean(C.__repr__(c)),clean(c.__repr__()))
            c=C();c.cell_contents=c;print(clean(repr(c)))
            print(clean(repr(c.__eq__)),repr(C.__eq__),repr(C.cell_contents))
            for action in [lambda:C.__repr__(),lambda:C.__repr__(1),lambda:C.__repr__(c,1)]:
                try:action()
                except Exception as e:print(type(e).__name__,str(e))
        ''')

    def test_queued_direct_callbacks_recursion_and_collection(self):
        self.compare('''
            from types import CellType as C
            import gc
            class Contents:
                def __init__(self,n):self.n=n
                def __eq__(self,other):
                    if self.n==0:return 'done'
                    return C.__eq__(C(Contents(self.n-1)),C(Contents(other.n-1)))
            print(C.__eq__(C(Contents(300)),C(Contents(300))))
            a=C();b=C();a.cell_contents=a;b.cell_contents=b
            for action in [lambda:a==b,lambda:C.__eq__(a,b),lambda:a.__eq__(b)]:
                try:action()
                except Exception as e:print(type(e).__name__)
            class Recursive:
                def __eq__(self,other):return C.__eq__(C(self),C(other))
            try:C.__eq__(C(Recursive()),C(Recursive()))
            except Exception as e:print(type(e).__name__)
            events=[]
            class Collected:
                def __init__(self,name):self.name=name
                def __del__(self):events.append(self.name)
                def __eq__(self,other):
                    del left.cell_contents;del right.cell_contents
                    gc.collect();print('alive',events)
                    return self.name+other.name
            left=C(Collected('L'));right=C(Collected('R'))
            print(C.__eq__(left,right));gc.collect();print(sorted(events))
        ''')

    def test_stream_consumers_preserve_heap_cell_descriptor_recursion(self):
        self.compare('from types import CellType as C\n\n\nclass Contents:\n    def __init__(self, depth):\n        self.depth = depth\n\n    def __eq__(self, other):\n        if self.depth == 0:\n            return "done"\n        return next(map(C.__eq__, [C(Contents(self.depth - 1))],\n                        [C(Contents(other.depth - 1))]))\n\n\nprint(C.__eq__(C(Contents(300)), C(Contents(300))))\n\n\nclass Recursive:\n    def __eq__(self, other):\n        return next(map(C.__eq__, [C(self)], [C(other)]))\n\n\ntry:\n    C.__eq__(C(Recursive()), C(Recursive()))\nexcept Exception as error:\n    print(type(error).__name__)\n')

    def test_standalone_pruned_runtime_all_integer_modes(self):
        source = '''\
from types import CellType as C
import gc
class Contents:
    def __eq__(self,other):return 'rich result'
def outer():
    value=5
    def read():return value
    return read
read=outer();cell=read.__closure__[0]
print(type(C),type(cell) is C,C.__mro__,C.__mro__ is C.__mro__)
C.cell_contents.__set__(cell,8);print(read())
print(C.__eq__(C(Contents()),C(Contents())))
print(C.__new__(C,4).cell_contents,C.__init__(cell,1,2,x=3))
del cell.cell_contents;gc.collect();print(C.__eq__(cell,C()))
'''
        expected = subprocess.run([sys.executable, "-I", "-c", source], capture_output=True,
                                  text=True, check=True).stdout
        for integer in ("i64", "i128", "bigint"):
            with self.subTest(integer=integer):
                result = transpile(source, TranspileOptions(integer=integer, optimize=True))
                self.assertTrue(result.success, str(result.diagnostics))
                path = Path(self.tmp.name) / f"static-{integer}.rs"
                path.write_text(result.rust_source)
                binary = path.with_suffix("")
                built = subprocess.run(["rustc", "--edition=2021", str(path), "-o", str(binary)],
                                       capture_output=True, text=True, timeout=120)
                self.assertEqual(built.returncode, 0, built.stderr)
                actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20,
                                        env={**os.environ, "PATH": "/nonexistent"})
                self.assertEqual(actual.returncode, 0, actual.stderr)
                self.assertEqual(actual.stdout, expected)


if __name__ == "__main__":
    unittest.main()
