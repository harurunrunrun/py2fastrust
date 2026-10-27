"""Buffer leases remain reachable through public closure cell side maps."""

import shutil
import textwrap
import unittest
import test_runtime


@unittest.skipUnless(shutil.which('rustc'), 'rustc is required')
class BufferClosureCellTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_bytearray_repetition_retains_native_sequence_protocol_fallback(self):
        source = textwrap.dedent('''
            import gc
            events=[]
            class Index:
                def __index__(self):events.append('index');gc.collect();return 2
            class Reflected:
                def __rmul__(self,other):events.append('reflected');return ('right',other)
            class B(bytearray):pass
            for value in (bytearray(b'ab'),B(b'cd')):
                print(value*Index(),Index()*value)
                print(value*Reflected())
                alias=value;value*=Index();print(value,alias is value)
            print(events)
        ''')
        self.run_source(source+'\nexec('+repr(source)+', {})\n')

    def test_buffer_owners_in_shared_cells_and_replaced_function_closures(self):
        source = textwrap.dedent('''
            import gc
            import types
            def maker(value):
                captured = memoryview(value)
                def load():return captured
                return load
            a=bytearray(b'ab');f=maker(a);gc.collect()
            print(f().tobytes(),f.__closure__[0].cell_contents.obj is a)
            try:a.append(33)
            except Exception as error:print(type(error).__name__)
            cell=f.__closure__[0]
            g=types.FunctionType(f.__code__,globals(),'copy',None,(cell,))
            del f;gc.collect();print(g().tobytes())
            b=bytearray(b'cd');cell.cell_contents=memoryview(b);gc.collect()
            a.append(33);print(a,g().tobytes(),g.__closure__[0] is cell)
            del cell.cell_contents;gc.collect();b.append(34);print(b)
            try:g()
            except Exception as error:print(type(error).__name__)
            del g,cell;gc.collect()
            gc.disable()
            c=bytearray(b'xy');h=maker(c);gc.collect();print(h().tobytes())
            h.__closure__[0].cell_contents.release();c.append(35);print(c)
            gc.enable()
        ''')
        self.run_source(source+'\nexec('+repr(source)+', {})\n')


if __name__ == '__main__':
    unittest.main()
