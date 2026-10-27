"""Bytearray and memoryview share rooted mutable storage and buffer leases."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import test_runtime
from py2fastrust import TranspileOptions, transpile


@unittest.skipUnless(shutil.which('rustc'),'rustc is required')
class MutableBufferTests(unittest.TestCase):
    run_source=test_runtime.RuntimeTests.run_source

    def compare(self,source,**kwargs):
        source=textwrap.dedent(source)
        return self.run_source(source+'\nexec('+repr(source)+', {})\n',**kwargs)

    def test_bytearray_public_ascii_transform_search_translation_and_constructors(self):
        self.compare(r'''
            values=[bytearray(),bytearray(b'Ab cD!'),bytearray(b'a\xffb'),bytearray(b'\t A\r\nB\n')]
            for value in values:
                for name in ('lower','upper','swapcase','capitalize','title','isascii','isalpha','isalnum','isdigit','isspace','islower','isupper','istitle'):
                    print(name,getattr(value,name)())
                print(value.center(13,b'-'),value.ljust(13,b'.'),value.rjust(13,b'+'),value.zfill(13))
                print(value.expandtabs(),value.expandtabs(tabsize=3),value.splitlines(),value.splitlines(keepends=True))
            value=bytearray(b'abc def abc')
            for needle in (b'abc',bytearray(b'abc'),memoryview(b'abc'),97):
                print(value.count(needle),value.find(needle),value.rfind(needle),value.index(needle),value.rindex(needle))
            print(value.startswith(bytearray(b'abc')),value.endswith(memoryview(b'abc')),value.startswith((b'Z',bytearray(b'ab'))))
            print(value.partition(bytearray(b' ')),value.rpartition(memoryview(b' ')))
            print(value.removeprefix(b'abc'),value.removesuffix(b'abc'),value.removesuffix(b''))
            print(value.replace(b'abc',b'X',1),value.split(),value.rsplit(b' ',1),value.strip(b'ac'),bytearray(b',').join([b'a',bytearray(b'b'),memoryview(b'c')]))
            table=bytearray.maketrans(b'ac',b'AC');print(type(table) is bytes,value.translate(table),value.translate(None,delete=b' '))
            print(bytearray.fromhex('41 42\t43'),bytearray.fromhex(b'44 45'),bytearray.fromhex(memoryview(b'46')))
            events=[]
            class B(bytearray):
                def __init__(self,*args,**kwargs):events.append(args);super().__init__(*args,**kwargs)
            print(B.fromhex('41 42'),events)
            for action in (lambda:bytearray.fromhex('A B'),lambda:bytearray.fromhex('GG'),lambda:bytearray.maketrans(b'a',b''),lambda:value.translate(b'short')):
                try:action()
                except Exception as error:print(type(error).__name__)
        ''')

    def test_comparison_hash_count_index_and_subclass_overrides(self):
        self.compare(r'''
            a=bytearray([1,0,0,0]);typed=memoryview(bytes(a)).cast('I')
            print(a==typed,typed==a,a<typed,a==bytes(a),bytes(a)==a)
            print(memoryview(b'\x01').cast('b')==memoryview(b'\x01'),memoryview(b'\x01').cast('c')==memoryview(b'\x01'))
            v=memoryview(b'abacad');print(v.count(97),v.index(97),v.index(97,1),v.index(97,-3))
            print(hash(v)==hash(b'abacad'));v.release();print(hash(v)==hash(b'abacad'),v==v)
            try:memoryview(b'x').index(99)
            except Exception as error:print(type(error).__name__)
            for value in (memoryview(bytearray(b'ab')),memoryview(bytearray(b'ab')).toreadonly(),memoryview(b'abcd').cast('I')):
                try:hash(value)
                except Exception as error:print(type(error).__name__)
            events=[]
            class Override(bytearray):
                __slots__=('note',)
                def __len__(self):events.append('len');return 9
                def __getitem__(self,key):events.append('get');return 77
                def __iter__(self):return iter([5,6])
                def __contains__(self,item):return True
                def __repr__(self):return 'custom repr'
            value=Override(b'ab');value.note=3
            print(value,value.note,len(value),value[0],list(value),999 in value)
            print(bytearray.__len__(value),bytearray.__getitem__(value,0),bytearray.__repr__(value),memoryview(value).tobytes(),events)
            try:
                class Invalid(memoryview):pass
            except Exception as error:print(type(error).__name__)
        ''')

    def test_shared_views_slices_readonly_context_and_release(self):
        self.compare('''
            a=bytearray([65,66,67,68]);alias=a
            print(a,len(a),list(a),a[1],a[::2],a is alias)
            v=memoryview(a);s=v[1:3];r=s.toreadonly()
            print(v.obj is a,s.obj is a,r.obj is a,v.format,v.itemsize,v.ndim,v.shape,v.strides,v.suboffsets,v.readonly,v.nbytes)
            v[0]=90;s[:]=b'xy';print(a,v.tobytes(),bytes(a),int.from_bytes(v),str(v,'ascii'))
            print(r.tolist(),r.tobytes(),r.readonly)
            try:r[0]=1
            except Exception as error:print(type(error).__name__)
            for action in (lambda:a.append(70),lambda:a.clear(),lambda:a.__setitem__(slice(None),b'ab')):
                try:action()
                except Exception as error:print(type(error).__name__)
            a[:]=b'1234';a.reverse();print(v.tobytes())
            v.release();s.release()
            try:a.append(70)
            except Exception as error:print(type(error).__name__)
            r.release();a.append(70);print(a)
            with memoryview(a) as view:view[-1]=71
            print(a)
            for name in ('obj','shape','format','readonly','nbytes','tolist','tobytes','hex'):
                try:
                    value=getattr(view,name)
                    if callable(value):value()
                except Exception as error:print(name,type(error).__name__)
            print(view.release())
        ''')

    def test_bytearray_mutation_alias_iteration_and_atomic_bad_input(self):
        self.compare('''
            a=bytearray(b'abc');alias=a
            a.append(100);a.extend([101,102]);a.insert(-2,90);print(a,alias)
            print(a.pop(),a.pop(0));a.remove(90);print(a)
            a[1:2]=[70,71,72];a[::2]=bytes([1]*len(a[::2]));print(a)
            del a[::-3];print(a)
            try:a+=a
            except BufferError:print('self concat export')
            a.extend(a);a*=2;print(a is alias,a);a*=0;print(a)
            a.extend(b'ab');iterator=iter(a);print(next(iterator));a.append(99);print(list(iterator))
            a.extend(a);print(a)
            def invalid():yield 77;yield 999
            for action in (lambda:a.extend(invalid()),lambda:a.__setitem__(slice(None),invalid())):
                try:action()
                except Exception as error:print(type(error).__name__,a)
            a.resize(3);print(a);a.resize(6);print(a);print(a.copy() is a)
            a.clear();print(a)
            for action in (lambda:bytearray(-1),lambda:bytearray([256]),lambda:bytearray('x'),lambda:bytearray(unknown=1),lambda:hash(a)):
                try:action()
                except Exception as error:print(type(error).__name__)
        ''')

    def test_native_scalar_casts_shapes_strides_and_orders(self):
        self.compare('''
            for format,value in [('B',250),('b',-12),('c',b'x'),('?',True),('h',-123),('H',123),('i',-123456),('I',123456),('l',-12345),('L',12345),('q',-12345),('Q',12345),('n',-12345),('N',12345),('P',12345),('f',1.25),('d',-.25),('e',1.75),('@I',99)]:
                a=bytearray(16);view=memoryview(a).cast(format);view[0]=value
                print(format,view.format,view.itemsize,view.shape,view.strides,view[0],view.tolist(),view.tobytes())
            a=bytearray(range(12));v=memoryview(a).cast('B',shape=[3,4])
            print(v.shape,v.strides,v.ndim,v.nbytes,v[1,2],v.tolist(),v.tobytes(),v.tobytes('F'))
            v[1,2]=77;print(a)
            s=v[::-1];print(s.shape,s.strides,s.tolist(),s.c_contiguous,s.f_contiguous,s.contiguous,s.tobytes())
            for action in (lambda:s.cast('B'),lambda:v.cast('I').cast('H'),lambda:v.cast('>I'),lambda:v.cast('B',shape=[2,2]),lambda:v[0]):
                try:action()
                except Exception as error:print(type(error).__name__)
            z=memoryview(b'X').cast('B',shape=[]);print(z.ndim,z.shape,z[()],z.tolist(),z.tobytes())
            try:len(z)
            except Exception as error:print(type(error).__name__)
        ''')

    def test_gc_acyclic_release_cycle_retention_and_resurrection(self):
        self.compare('''
            import gc
            gc.disable();a=bytearray(b'ab')
            view=memoryview(a);del view;a.append(99);print(a)
            cycle=[memoryview(a)];cycle.append(cycle);del cycle
            try:a.append(100)
            except BufferError:print('cycle export retained')
            gc.collect();a.append(100);print(a)
            kept=[];events=[]
            class Holder:
                def __del__(self):events.append('finalize');kept.append(self.view)
            def make(cyclic):
                holder=Holder();holder.view=memoryview(a)
                if cyclic:holder.me=holder
            make(False)
            try:a.append(101)
            except BufferError:print('resurrected',events,kept[-1].tobytes())
            kept.pop().release();a.append(101);print(a)
            make(True);gc.collect()
            try:a.append(102)
            except BufferError:print('cycle resurrected',events,kept[-1].tobytes())
            kept.pop().release();a.append(102);print(a)
            gc.enable()
        ''')

    def test_python_exporter_flags_pins_callbacks_and_returned_view_identity(self):
        self.compare('''
            events=[]
            class Exporter:
                def __init__(self):self.data=bytearray(b'abcd');self.returned=None
                def __buffer__(self,flags):events.append(('acquire',flags));self.returned=memoryview(self.data);return self.returned
                def __release_buffer__(self,view):events.append(('release',view is self.returned,view.tobytes()));view.release()
            e=Exporter();v=memoryview(e);s=v[1:]
            print(type(v.obj).__name__,s.obj is v.obj,v.tobytes(),events)
            try:e.returned.release()
            except Exception as error:print(type(error).__name__)
            v.release();print(events);s.release();print(events)
            print(bytes(e),bytearray(e),int.from_bytes(e),str(e,'ascii'));print(events)
            class Retain:
                def __init__(self):self.view=memoryview(bytearray(b'xyz'))
                def __buffer__(self,flags):return self.view
                def __release_buffer__(self,view):events.append('retain release')
            e=Retain();v=memoryview(e);del v;e.view.release();print(events[-1])
            class Bad:
                def __buffer__(self,flags):return b'bad'
            try:memoryview(Bad())
            except Exception as error:print(type(error).__name__)
            import gc
            class Collect:
                def __buffer__(self,flags):gc.collect();return memoryview(b'WXYZ')
                def __release_buffer__(self,view):gc.collect();view.release()
            data=bytearray(b'abcd');view=memoryview(data)
            view[:]=Collect();print(data);view.release();data.append(33);print(data)
            class Fail:
                def __buffer__(self,flags):gc.collect();raise ValueError('acquire')
            view=memoryview(data)
            try:view[:]=Fail()
            except Exception as error:print(type(error).__name__)
            view.release();data.append(34);print(data)
        ''')

    def test_buffer_interop_conversions_protocol_priority_and_noncontiguous_errors(self):
        self.compare(r'''
            data=bytearray(b'1234');v=memoryview(data);s=v[::2]
            print(bytes(v),bytes(s),bytearray(v),bytearray(s),int(data),int(v),int(data,16),float(data),float(v))
            print(str(v,'ascii'),data.decode(),b'1' in v,b'13' in data)
            print(b'1234'.find(data),b'1234'.startswith(data),bytearray(b'1234').startswith(v))
            for action in (lambda:str(s,'ascii'),lambda:b'1234'.find(s),lambda:int(s,10)):
                try:action()
                except Exception as error:print(type(error).__name__)
            print(bytearray('日本','utf8'),bytes(bytearray('日本','utf8')).decode())
            events=[]
            class B(bytearray):
                def __bytes__(self):events.append('bytes');return b'custom'
                def __index__(self):events.append('index');return 2
            value=B(b'1234')
            print(bytes(value),bytearray(value),int(value),int(value,10),float(value),events)
            class E:
                def __buffer__(self,flags):events.append(('buffer',flags));return memoryview(b'25')
                def __release_buffer__(self,view):events.append('release');view.release()
            print(int(E()),float(E()),bytes(E()),bytearray(E()),events[-8:])
            class Different(bytearray):
                def __buffer__(self,flags):events.append(flags);return memoryview(b'changed')
            print(str(Different(b'original'),'ascii'),events[-1])
            for kind in (BufferError,ValueError,RuntimeError):
                class Bad:
                    def __buffer__(self,flags):raise kind('sentinel')
                try:str(Bad(),'ascii')
                except Exception as error:print(type(error).__name__)
        ''')

    def test_overlap_random_slices_callback_mutation_and_cast_boundaries(self):
        self.compare('''
            state=12345
            for case in range(100):
                state=(state*37+17)%65521
                a=bytearray(range(state%15));v=memoryview(a)
                start=(state%25)-12;stop=((state//19)%25)-12;step=[-5,-2,-1,1,2,4][case%6]
                view=v[start:stop:step]
                print(case,a[start:stop:step],view.tolist(),view.shape,view.strides,view.tobytes())
                replacement=bytes((x+11)%256 for x in view)
                view[:]=replacement;print(a)
                view.release();v.release()
            a=bytearray(b'abcdef');v=memoryview(a)
            v[1:]=v[:-1];print(a);v[::-1]=v;print(a);v.release()
            class Index:
                def __index__(self):a.clear();return 1
            for operation in ('set','get','pop'):
                a[:]=b'abcd'
                try:
                    if operation=='set':a[Index()]=65
                    elif operation=='get':print(a[Index()])
                    else:print(a.pop(Index()))
                except Exception as error:print(operation,type(error).__name__,a)
            a[:]=b'abcd'
            class Value:
                def __index__(self):a.clear();return 65
            try:a[1]=Value()
            except Exception as error:print('value',type(error).__name__,a)
            a[:]=b'abcd';v=memoryview(a)
            class Release:
                def __index__(self):v.release();return 66
            try:v[0]=Release()
            except Exception as error:print('release',type(error).__name__,a)
            for format,value in [('b',128),('B',-1),('h',32768),('H',-1),('f',1e300),('e',65520.)]:
                v=memoryview(bytearray(8)).cast(format)
                try:v[0]=value
                except Exception as error:print(format,type(error).__name__)
            for value in [0.,-0.,1.,-2.,0.000000059604644775390625,65504.,1.00048828125]:
                v=memoryview(bytearray(2)).cast('e');v[0]=value;print(v[0],v.tobytes())
        ''')

    def test_native_buffer_flag_negotiation_owner_identity_and_pinning(self):
        self.compare('''
            values=[b'abcdef',bytearray(b'abcdef'),memoryview(b'abcdef'),memoryview(b'abcdef')[::2],memoryview(bytearray(range(8))).cast('I'),memoryview(bytearray(range(8))).cast('I',[1,2])]
            for value in values:
                for flags in [0,1,4,8,12,16,24,28,32,56,64,88,128,152,256,284,512,-1,2147483648]:
                    try:
                        view=value.__buffer__(flags)
                        print(type(value).__name__,flags,view.obj is value,view.format,view.itemsize,view.ndim,view.shape,view.strides,view.tobytes(),view.tolist())
                        view.release()
                    except Exception as error:print(type(value).__name__,flags,type(error).__name__)
            a=bytearray(b'ab');v=memoryview(a);export=v.__buffer__(284);part=export[:]
            print(export.obj is v,part.obj is v)
            try:v.release()
            except Exception as error:print(type(error).__name__)
            v.__release_buffer__(export)
            try:v.release()
            except Exception as error:print(type(error).__name__)
            v.__release_buffer__(part);v.release();a.append(99);print(a)
            a=bytearray(b'ab');b=bytearray(b'cd');av=memoryview(a);bv=memoryview(b)
            for owner,view in [(a,bv),(a,av),(a,av),(a,1)]:
                try:print(owner.__release_buffer__(view))
                except Exception as error:print(type(error).__name__)
            bv.release()
            class B(bytearray):pass
            value=B(b'xy');view=value.__buffer__(284);print(view.obj is value);value.__release_buffer__(view);value.append(122);print(value)
            v=memoryview(value);export=v.__buffer__(284);del export;v.release();value.append(33);print(value)
            a=bytearray(range(8));v=memoryview(a).cast('I');export=v.__buffer__(0)
            export[0]=7;print(a,export.tolist(),export.cast('B').tolist(),export==memoryview(bytes([7,4])))
            try:export[:]=b'ab'
            except Exception as error:print(type(error).__name__)
            export[:]=export[::-1];print(a);v.__release_buffer__(export);v.release()
        ''')

    def test_cast_shape_exact_integers_and_released_argument_boundaries(self):
        self.compare('''
            events=[]
            class Index:
                def __index__(self):events.append('index');return 2
            class Integer(int):
                def __index__(self):events.append('override');return 99
            v=memoryview(bytearray(8))
            for shape in [[Index(),4],[2.,4],[Integer(2),Integer(4)],[True,8],None,[0,8],[],[2,-4]]:
                try:print(v.cast('B',shape).shape)
                except Exception as error:print(type(error).__name__)
            print(events)
            for name,args in [('tolist',(1,)),('toreadonly',(1,)),('cast',()),('cast',(3,)),('tobytes',(3,)),('tobytes',('C','C')),('hex',('x',1,2)),('count',()),('index',(1,2,3,4))]:
                released=memoryview(b'abc');released.release()
                try:getattr(released,name)(*args)
                except Exception as error:print(name,type(error).__name__)
            a=bytearray(b'abcd');view=memoryview(a)
            class Equal:
                def __eq__(self,other):view.release();return False
            for name in ['count','index']:
                view=memoryview(a)
                try:print(getattr(view,name)(Equal()))
                except Exception as error:print(name,type(error).__name__)
        ''')

    def test_all_modes_debug_release_standalone(self):
        source=textwrap.dedent('''
            import gc
            a=bytearray(b'abcd');alias=a;v=memoryview(a);s=v[::2]
            s[:]=b'XY';print(a,alias is a,s.tobytes(),bytes(v),int.from_bytes(v))
            try:a.append(1)
            except BufferError:print('exported')
            v.release();s.release();a.extend(a);a.resize(10);print(a)
            class B(bytearray):__slots__=('note',)
            b=B(b'12');b.note='slot';print(b,b.note,int(b),float(b),b+b'3')
            class Exporter:
                def __init__(self):self.data=bytearray(b'25')
                def __buffer__(self,flags):return memoryview(self.data)
                def __release_buffer__(self,view):print('released',view.tobytes());view.release()
            e=Exporter();print(bytes(e),str(e,'ascii'))
            gc.disable();v=memoryview(a);del v;a.append(33);print(a)
            cycle=[memoryview(a)];cycle.append(cycle);del cycle
            try:a.append(34)
            except BufferError:print('cycle')
            gc.collect();a.append(34);print(a);gc.enable()
            exec("a=bytearray(b'xyz');v=memoryview(a);v[1]=65;print(a,v.hex(),v.tolist());v.release()")
        ''')
        expected=subprocess.run([sys.executable,'-I','-c',source],capture_output=True,text=True,check=True).stdout
        with tempfile.TemporaryDirectory(prefix='mutable-buffer-standalone-') as directory:
            path=Path(directory)
            for integer in ('i64','i128','bigint'):
                result=transpile(source,TranspileOptions(integer=integer,filename='buffers.py',optimize=False))
                self.assertTrue(result.success,result.diagnostics)
                target=path/(integer+'.rs');target.write_text(result.rust_source,encoding='utf-8')
                for optimized in (False,True):
                    with self.subTest(integer=integer,release=optimized):
                        binary=path/(integer+('-release' if optimized else '-debug'))
                        command=['rustc','--edition=2021',str(target),'-o',str(binary)]
                        if optimized:command.append('-O')
                        compiled=subprocess.run(command,capture_output=True,text=True,timeout=180)
                        self.assertEqual(compiled.returncode,0,compiled.stderr)
                        environment=dict(os.environ,PATH=str(path/'no-tools'))
                        environment.pop('PYTHONPATH',None);environment.pop('PYTHONHOME',None)
                        actual=subprocess.run([str(binary)],env=environment,cwd=path,capture_output=True,text=True,timeout=20)
                        self.assertEqual(actual.returncode,0,actual.stderr)
                        self.assertEqual(actual.stdout,expected)


if __name__=='__main__':unittest.main()
