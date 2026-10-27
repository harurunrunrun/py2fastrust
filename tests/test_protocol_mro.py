"""Caller-owned MRO binding, iteration and base-transaction continuations."""

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
class ProtocolMroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="pytors-protocol-mro-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        result = transpile(WRAPPER, TranspileOptions(optimize=False))
        if not result.success:
            raise AssertionError(result.diagnostics)
        target = root / "main.rs"
        target.write_text(result.rust_source)
        cls.binary = target.with_suffix("")
        built = subprocess.run(["rustc", "--edition=2021", str(target), "-o", str(cls.binary)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise AssertionError(built.stderr)

    def compare(self, source):
        source = textwrap.dedent(source)
        expected = subprocess.run([sys.executable, "-I", "-c", WRAPPER], input=source,
                                  capture_output=True, text=True, timeout=45)
        actual = subprocess.run([str(self.binary)], input=source,
                                capture_output=True, text=True, timeout=45,
                                env={"PATH": "/nonexistent"})
        self.assertEqual(expected.returncode, 0, expected.stderr)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, expected.stdout, actual.stderr)

    def test_recursive_base_callbacks_use_python_frames_and_restore_on_error(self):
        self.compare('''
            import sys,gc
            sys.setrecursionlimit(3000)
            active=False
            remaining=300
            class A:pass
            class B:pass
            class M(type):
                def mro(cls):
                    global remaining
                    if active and remaining:
                        remaining-=1
                        if remaining in (299,0):gc.collect()
                        cls.__bases__=(A,) if cls.__bases__==(B,) else (B,)
                    return type.mro(cls)
            class C(A,metaclass=M):pass
            active=True
            C.__bases__=(B,)
            print(remaining,C.__bases__[0].__name__,C.__mro__[1].__name__)
            active=False
            C.__bases__=(A,)
            class Recursive(type):
                def mro(cls):
                    if active:cls.__bases__=(A,) if cls.__bases__==(B,) else (B,)
                    return type.mro(cls)
            class D(A,metaclass=Recursive):pass
            active=True
            try:D.__bases__=(B,)
            except Exception as error:print(type(error).__name__)
            print(D.__bases__==(A,),D.__mro__==(D,A,object))
        ''')

    def test_descriptor_binding_suspends_before_recursive_base_changes(self):
        self.compare('''
            import sys,gc
            sys.setrecursionlimit(3000)
            active=False
            remaining=300
            class A:pass
            class B:pass
            class Descriptor:
                def __get__(self,cls,owner):
                    global remaining
                    if active and remaining:
                        remaining-=1
                        if remaining==0:gc.collect()
                        type.__setattr__(cls,'__bases__',(A,) if cls.__bases__==(B,) else (B,))
                    return lambda:type.mro(cls)
            class M(type):mro=Descriptor()
            class C(A,metaclass=M):pass
            active=True
            type.__setattr__(C,'__bases__',(B,))
            print(remaining,C.__bases__[0].__name__,C.__mro__[1].__name__)
        ''')

    def test_result_iteration_suspends_and_never_requests_a_length_hint(self):
        self.compare('''
            import sys,gc
            sys.setrecursionlimit(3000)
            active=False
            remaining=300
            events=[]
            class A:pass
            class B:pass
            class Result:
                def __init__(self,cls):self.cls=cls;self.iterator=None
                def __iter__(self):
                    global remaining
                    if active and remaining:
                        remaining-=1
                        if remaining==0:gc.collect()
                        setattr(self.cls,'__bases__',(A,) if self.cls.__bases__==(B,) else (B,))
                    self.iterator=iter(type.mro(self.cls));return self
                def __len__(self):raise AssertionError('MRO conversion must not request length')
                def __length_hint__(self):raise AssertionError('MRO conversion must not request hint')
                def __next__(self):return next(self.iterator)
            class M(type):
                def mro(cls):return Result(cls)
            class C(A,metaclass=M):pass
            active=True
            setattr(C,'__bases__',(B,))
            print(remaining,C.__bases__[0].__name__,C.__mro__[1].__name__)
        ''')

    def test_pending_descendants_and_previous_mro_survive_callback_collection(self):
        self.compare('''
            import gc
            active=False
            keep=[]
            events=[]
            data=bytearray(b'ab')
            class A:pass
            class B:pass
            class Root(A):pass
            class M(type):
                def mro(cls):
                    if active and cls.__name__=='First':
                        keep.clear();gc.collect()
                        try:data.append(33)
                        except Exception as error:events.append(type(error).__name__)
                    return type.mro(cls)
            class First(Root,metaclass=M):pass
            class Last(Root,metaclass=M):view=memoryview(data)
            keep.append(Last);del Last
            active=True
            old=Root.__mro__
            Root.__bases__=(B,)
            print(events,old==(Root,A,object),Root.__mro__==(Root,B,object))
            gc.collect();data.append(34);print(data)
        ''')

    def test_caught_length_hint_error_discards_and_rolls_back_nested_transaction(self):
        self.compare('''
            active=False
            class A:pass
            class B:pass
            class M(type):
                def mro(cls):
                    if active:raise TypeError('nested hint callback')
                    return type.mro(cls)
            class C(A,metaclass=M):pass
            class Hint:
                def __iter__(self):return iter(())
                def __len__(self):C.__bases__=(B,);return 0
            active=True
            print(list(Hint()),C.__bases__==(A,),C.__mro__==(C,A,object))
        ''')

    def test_failed_result_iteration_rolls_back_all_completed_descendants(self):
        self.compare('''
            import gc
            active=False
            events=[]
            class A:pass
            class B:pass
            class M(type):
                def mro(cls):
                    if active:
                        events.append(cls.__name__)
                        if cls.__name__=='Late':
                            def values():
                                yield cls
                                gc.collect()
                                raise LookupError('late iteration')
                            return values()
                    return type.mro(cls)
            class Root(A,metaclass=M):pass
            class Early(Root):pass
            class Late(Root):pass
            originals=[value.__mro__ for value in (Root,Early,Late)]
            bases=Root.__bases__
            active=True
            try:setattr(Root,'__bases__',(B,))
            except Exception as error:print(type(error).__name__)
            print(events,Root.__bases__ is bases,[value.__mro__ is old for value,old in zip((Root,Early,Late),originals)])
            active=False
            Root.__bases__=(B,)
            print(Root.__mro__==(Root,B,object),issubclass(Early,B),issubclass(Late,B))
        ''')


if __name__ == "__main__":
    unittest.main()
