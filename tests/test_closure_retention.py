"""Function closures retain cells without manufacturing namespace cycles."""

import shutil
import textwrap
import unittest
import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class ClosureRetentionTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare(self, source):
        source = textwrap.dedent(source)
        self.run_source(source+'\nexec('+repr(source)+', {})\n')

    def test_acyclic_captured_view_releases_with_gc_disabled(self):
        self.compare('''
            import gc
            gc.disable()
            def maker(value):
                view=memoryview(value)
                def load():return view
                return load
            a=bytearray(b'ab');f=maker(a);print(f().tobytes());del f
            a.append(33);print(a)
            b=bytearray(b'cd');f=maker(b);cell=f.__closure__[0];del f
            try:b.append(33)
            except Exception as error:print(type(error).__name__)
            del cell;b.append(34);print(b)
            gc.enable()
        ''')

    def test_unrelated_local_exports_are_not_captured_by_returned_functions(self):
        self.compare('''
            import gc
            gc.disable()
            def maker(value):
                unrelated=memoryview(value)
                captured=7
                def load():return captured
                return load
            a=bytearray(b'ab');f=maker(a);a.append(33);print(a,f())
            def no_frees(value):
                unrelated=memoryview(value)
                def load():return 9
                return load
            b=bytearray(b'cd');g=no_frees(b);b.append(34);print(b,g(),g.__closure__)
            gc.enable()
        ''')

    def test_real_recursive_cell_cycles_remain_pinned_until_collection(self):
        self.compare('''
            import gc
            gc.disable()
            def maker(value):
                view=memoryview(value)
                def load():return view,load
                return load
            a=bytearray(b'ab');f=maker(a);print(f()[0].tobytes());del f
            try:a.append(33)
            except Exception as error:print(type(error).__name__)
            gc.collect();a.append(34);print(a)
            gc.enable()
        ''')

    def test_conditional_annotation_private_cells_remain_shared_and_hidden(self):
        self.compare('''
            events=[]
            class Space(dict):
                def __getitem__(self,key):
                    if key=='__conditional_annotations__':events.append('private read')
                    return super().__getitem__(key)
            class Meta(type):
                @classmethod
                def __prepare__(m,name,bases):return Space()
            class C(metaclass=Meta):
                __conditional_annotations__='ordinary entry'
                always:str
                if True:x:int
                if False:y:float
            annotate=C.__annotate__;names=annotate.__code__.co_freevars
            print(names,events,C.__conditional_annotations__)
            cell=annotate.__closure__[names.index('__conditional_annotations__')]
            print(type(cell.cell_contents).__name__,annotate(1))
            cell.cell_contents=set();print(annotate(1))
            cell.cell_contents={1};print(annotate(1))
            del cell.cell_contents
            try:annotate(1)
            except Exception as error:print(type(error).__name__)
            print(C.__conditional_annotations__,events)
        ''')


if __name__ == '__main__':
    unittest.main()
