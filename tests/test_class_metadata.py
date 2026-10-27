"""Heap class metadata keeps stable identities and its real MRO cycle."""

import shutil
import textwrap
import unittest
import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ClassMetadataTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source):
        source = textwrap.dedent(source)
        self.run_source(source+'\nexec('+repr(source)+', {})\n')

    def test_identity_original_bases_and_creation_hook_visibility(self):
        self.compare('''
            import gc
            events=[]
            class Descriptor:
                def __set_name__(self,owner,name):
                    events.append((owner.__mro__ is owner.__mro__,owner.__bases__ is owner.__bases__,owner.__mro__[0] is owner))
            class Root:
                def __init_subclass__(cls):
                    events.append((cls.__mro__ is cls.__mro__,cls.__bases__ is cls.__bases__))
            class Child(Root):field=Descriptor()
            print(events,Child.__bases__==(Root,),Child.__mro__==(Child,Root,object))
            bases=(Root,);C=type('C',bases,{})
            print(C.__bases__ is bases,C.__mro__ is C.__mro__)
            mro=C.__mro__;own_bases=C.__bases__;gc.collect()
            print(C.__mro__ is mro,C.__bases__ is own_bases)
            class Tuple(tuple):
                def __iter__(self):raise LookupError('must bypass iteration')
            bases=Tuple((Root,));D=type('D',bases,{})
            print(D.__bases__ is bases,D.__mro__==(D,Root,object))
            for bases in [[],[Root],iter([Root]),1]:
                try:type('Invalid',bases,{})
                except Exception as error:print(type(error).__name__)
        ''')

    def test_empty_slots_class_mro_cycle_retains_exports_until_gc(self):
        self.compare('''
            import gc
            gc.disable()
            a=bytearray(b'ab')
            class C:
                __slots__=()
                view=memoryview(a)
            print(C.__mro__ is C.__mro__)
            del C
            try:a.append(33)
            except Exception as error:print(type(error).__name__)
            gc.collect();a.append(34);print(a)
            gc.enable()
        ''')

    def test_diamond_mro_and_surviving_metadata_owner(self):
        self.compare('''
            import gc
            class A:pass
            class B(A):pass
            class C(A):pass
            class D(B,C):pass
            print(D.__mro__==(D,B,C,A,object),D.__bases__==(B,C))
            mro=D.__mro__;bases=D.__bases__;del D;gc.collect()
            print(mro[0].__mro__ is mro,mro[0].__bases__ is bases)
            class X(B,C):pass
            class Y(C,B):pass
            try:
                class Invalid(X,Y):pass
            except Exception as error:print(type(error).__name__)
        ''')


if __name__ == '__main__':
    unittest.main()
