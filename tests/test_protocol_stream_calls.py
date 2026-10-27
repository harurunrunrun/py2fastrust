"""Streaming protocol continuations preserve partial output and iteration scopes."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from py2fastrust import TranspileOptions,transpile


WRAPPER="import sys,gc,functools\nexec(sys.stdin.read())\n"


@unittest.skipUnless(shutil.which("rustc"),"rustc is required")
class ProtocolStreamCallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix="py2fastrust-stream-protocol-")
        root=Path(cls.directory.name)
        result=transpile(WRAPPER,TranspileOptions(optimize=False))
        if not result.success:raise AssertionError(result.diagnostics)
        source=root/"main.rs";source.write_text(result.rust_source,encoding="utf-8")
        cls.binary=root/"main"
        compiled=subprocess.run(["rustc","--edition=2021",str(source),"-o",str(cls.binary)],capture_output=True,text=True,timeout=120)
        if compiled.returncode:raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def compare(self,source):
        source=textwrap.dedent(source)
        expected=subprocess.run([sys.executable,"-I","-c",WRAPPER],input=source,capture_output=True,text=True,timeout=35)
        actual=subprocess.run([str(self.binary)],input=source,capture_output=True,text=True,timeout=35)
        self.assertEqual(expected.returncode,0,expected.stderr)
        self.assertEqual(actual.returncode,0,actual.stderr)
        self.assertEqual(actual.stdout,expected.stdout,actual.stderr)

    def test_recursive_print_string_and_file_callbacks(self):
        self.compare('''
            class Sink:
                def write(self,text):pass
            sink=Sink()
            class Text:
                def __str__(self):print(self,file=sink);return 'unreachable'
            class File:
                def write(self,text):print(text,file=self)
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('str',lambda:print(Text(),file=sink)),('write',lambda:print('text',file=File()))]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
        ''')

    def test_print_write_lookup_conversion_partial_output_and_flush(self):
        self.compare('''
            events=[]
            class File:
                def __getattribute__(self,name):
                    if name in ['write','flush']:events.append(('lookup',name))
                    return object.__getattribute__(self,name)
                def write(self,text):events.append(('write',type(text).__name__,text))
                def flush(self):events.append(('flush',))
            file=File()
            class Text(str):
                def __str__(self):events.append(('separator',));return 'converted'
            class Argument:
                def __str__(self):events.append(('argument',));return 'value'
            class Flush:
                def __bool__(self):events.append(('flush truth',));return True
            print(Argument(),2,sep=Text('|'),end=Text('!'),file=file,flush=Flush())
            print(events)
            for mode in ['lookup','str','write','flush']:
                events.clear()
                class Failure:
                    def __getattribute__(self,name):
                        if name=='write' and mode=='lookup':raise LookupError('lookup')
                        return object.__getattribute__(self,name)
                    def write(self,text):
                        events.append(('write',text))
                        if mode=='write':raise LookupError('write')
                    def flush(self):events.append(('flush',));raise LookupError('flush')
                class Bad:
                    def __str__(self):
                        events.append(('str',))
                        if mode=='str':raise LookupError('str')
                        return 'value'
                try:print('prefix',Bad(),'after',file=Failure(),flush=True)
                except LookupError as error:print(mode,str(error),events)
            events.clear()
            try:print(Argument(),sep=3,file=file,flush=Flush())
            except TypeError:print('bad separator',events)
        ''')

    def test_print_captures_stdout_after_flush_truth_before_stringification(self):
        self.compare('''
            events=[]
            original=sys.stdout
            class File:
                def __init__(self,name):self.name=name
                def write(self,text):events.append((self.name,'write',text))
                def flush(self):events.append((self.name,'flush'))
            first=File('first');second=File('second')
            class Argument:
                def __str__(self):events.append(('str',));sys.stdout=second;return 'arg'
            class Flush:
                def __bool__(self):events.append(('flush truth',));sys.stdout=second;return True
            try:
                sys.stdout=first
                print(Argument(),Argument())
                sys.stdout=first
                print(Argument(),flush=Flush())
                sys.stdout=None
                print(1,sep=3,end=4)
            finally:sys.stdout=original
            print(events)
            class Text(str):pass
            result=Text('text')
            class Argument:
                def __str__(self):return result
            class IdentityFile:
                def write(self,text):events.append(text is result)
            events.clear();print(Argument(),end='',file=IdentityFile())
            print(events)
            print(Argument())
        ''')

    def test_recursive_next_higher_order_callbacks_and_for(self):
        self.compare('''
            class Direct:
                def __iter__(self):return self
                def __next__(self):return next(self)
            def mapped(value):return next(map(mapped,[value]))
            def predicate(value):return next(filter(predicate,[value]))
            def called():return next(iter(called,object()))
            class Loop:
                def __iter__(self):return self
                def __next__(self):
                    for value in self:return value
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('next',lambda:next(Direct())),('map',lambda:next(map(mapped,[1]))),('filter',lambda:next(filter(predicate,[1]))),('callable',lambda:next(iter(called,object()))),('for',lambda:next(Loop()))]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
        ''')

    def test_stopiteration_payload_defaults_and_nested_boundaries(self):
        self.compare('''
            class Iterator:
                def __iter__(self):return self
                def __next__(self):raise StopIteration(12)
            for make in [lambda:Iterator(),lambda:map(abs,Iterator()),lambda:filter(None,Iterator()),lambda:enumerate(Iterator()),lambda:zip(Iterator())]:
                value=make()
                try:next(value)
                except StopIteration as error:print('payload',error.value)
                marker=object();print(next(value,marker)is marker)
            def stop(*args):raise StopIteration(14)
            for make in [lambda:map(stop,[1]),lambda:filter(stop,[1]),lambda:iter(stop,0),lambda:iter(functools.partial(next,Iterator()),0)]:
                value=make()
                for i in range(2):
                    try:next(value)
                    except StopIteration as error:print('callback',error.value)
            class Error(StopIteration):pass
            class Subclass:
                def __next__(self):raise Error(16)
            marker=object();print(next(Subclass(),marker)is marker)
            try:next(Subclass())
            except Error as error:print(type(error).__name__,error.value)
        ''')

    def test_map_filter_enumerate_zip_and_callable_evaluation_order(self):
        self.compare('''
            events=[]
            class Iterator:
                def __init__(self,name,values):self.name=name;self.values=iter(values)
                def __iter__(self):return self
                def __next__(self):events.append(self.name);return next(self.values)
            value=map(lambda a,b:(events.append('map'),a+b)[1],Iterator('a',[1,2]),Iterator('b',[10]))
            for i in range(3):
                try:print(next(value))
                except StopIteration:print('stop')
            print(events)
            events.clear()
            value=zip(Iterator('a',[1,2]),Iterator('b',[3]))
            for item in value:print(item)
            print(events)
            class Truth:
                def __init__(self,value):self.value=value
                def __bool__(self):events.append(('truth',self.value));return self.value%2==1
            for item in filter(None,map(Truth,range(4))):print(item.value)
            print(events)
            events.clear()
            class Sentinel:
                def __eq__(self,other):events.append('sentinel');return False
            class Value:
                def __eq__(self,other):events.append('value');return False
            item=Value();value=iter(lambda:item,Sentinel())
            print(next(value)is item,events)
            print(list(enumerate(Iterator('enumerate',[3,4]),7)))
        ''')

    def test_iterator_and_print_suspension_keeps_gc_roots(self):
        self.compare('''
            released=[]
            class Token:
                def __init__(self,name):self.name=name
                def __del__(self):released.append(self.name)
                def __str__(self):gc.collect();return self.name
            class File:
                def write(self,text):gc.collect()
            print(Token('first'),Token('second'),file=File())
            gc.collect();print(sorted(released));released.clear()
            def combine(a,b):gc.collect();return a.name+b.name
            value=map(combine,[Token('a')],[Token('b')])
            print(next(value));del value;gc.collect();print(sorted(released));released.clear()
            class Truth:
                def __init__(self,token):self.token=token
                def __bool__(self):gc.collect();return True
            value=filter(Truth,[Token('kept')]);item=next(value)
            del value;gc.collect();print(released,item.name)
            del item;gc.collect();print(released)
        ''')


    def test_sequence_iterators_reentry_cursor_and_recursive_getitem(self):
        self.compare('''
            class Sequence:
                def __init__(self):self.busy=False
                def __len__(self):return 3
                def __getitem__(self,index):
                    if index>=3:raise IndexError(index)
                    print('get',index)
                    if not self.busy:
                        self.busy=True
                        print('nested',next(self.iterator))
                    return index
            for reverse in [False,True]:
                value=Sequence();value.iterator=reversed(value)if reverse else iter(value)
                print('reverse',reverse,next(value.iterator),next(value.iterator))
            class Source:
                def __getitem__(self,index):raise StopIteration(42)
            value=iter(Source());marker=object()
            print(next(value,marker)is marker,next(value,marker)is marker)
            class Recursive:
                def __getitem__(self,index):return next(iter(self))
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                try:next(iter(Recursive()))
                except RecursionError:print(limit,'sequence caught')
        ''')

    def test_generator_next_and_yield_from_share_scheduler(self):
        self.compare('''
            def inner():
                yield 1
                return 42
            def outer():
                result=yield from inner()
                yield result
                return 99
            value=outer();print(next(value),next(value))
            try:next(value)
            except StopIteration as error:print('return',error.value)
            def invalid():
                raise StopIteration(12)
                yield
            try:next(invalid())
            except RuntimeError as error:print('pep479',type(error.__cause__).__name__,error.__cause__.value)
            def recursive():yield next(recursive())
            def delegate():yield from delegate()
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,make in [('next',recursive),('delegate',delegate)]:
                    try:next(make())
                    except RecursionError:print(limit,label,'caught')
            def collected():
                item=object();gc.collect();yield item
                gc.collect();yield item
            value=collected();item=next(value);print(next(value)is item)
        ''')

    def test_itertools_callbacks_queue_and_preserve_lazy_values(self):
        self.compare('''
            import itertools as tools
            print(list(tools.accumulate([1,2,3])),list(tools.accumulate([],initial=4)))
            print(list(tools.batched(range(5),2)))
            print(list(tools.chain([1,2],[],[3])),list(tools.chain.from_iterable([[1],[],[2]])))
            print(list(tools.compress(range(5),[0,1,False,True,1])))
            print(list(tools.islice(tools.cycle([1,2]),5)))
            print(list(tools.dropwhile(lambda x:x<3,range(6))))
            print(list(tools.filterfalse(lambda x:x%2,range(6))))
            print([(key,list(group))for key,group in tools.groupby([1,1,2,1,1])])
            print(list(tools.islice(range(12),2,9,3)),list(tools.pairwise(range(4))))
            class Args:
                def __iter__(self):yield 2;yield 3
            print(list(tools.starmap(lambda a,b:a+b,[Args(),(4,5)])))
            print(list(tools.takewhile(lambda x:x<3,range(6))))
            left,right=tools.tee(range(4));print(next(left),next(left),next(right));print(list(left),list(right))
            print(list(tools.zip_longest([1,2],[],[3],fillvalue=9)))
            class Stop:
                def __iter__(self):return self
                def __next__(self):raise StopIteration(12)
            factories=[lambda:tools.accumulate(Stop()),lambda:tools.batched(Stop(),2),lambda:tools.chain(Stop()),lambda:tools.compress(Stop(),[1]),lambda:tools.cycle(Stop()),lambda:tools.dropwhile(bool,Stop()),lambda:tools.filterfalse(bool,Stop()),lambda:tools.groupby(Stop()),lambda:tools.islice(Stop(),3),lambda:tools.pairwise(Stop()),lambda:tools.starmap(abs,Stop()),lambda:tools.takewhile(bool,Stop()),lambda:tools.tee(Stop())[0],lambda:tools.zip_longest(Stop())]
            for factory in factories:
                try:next(factory())
                except StopIteration as error:print('end',error.value)
            for strict in [False,True]:
                value=tools.batched([1],2,strict=strict)
                try:print('batch',next(value))
                except ValueError as error:print(type(error).__name__)
        ''')

    def test_itertools_recursive_python_callbacks_and_iterator_sources(self):
        self.compare('''
            import itertools as tools
            def accumulation(a,b):return next(tools.accumulate([1],accumulation,initial=0))
            def predicate(value):return next(tools.dropwhile(predicate,[value]))
            def falsepredicate(value):return next(tools.filterfalse(falsepredicate,[value]))
            def takepredicate(value):return next(tools.takewhile(takepredicate,[value]))
            def key(value):return next(tools.groupby([value],key))
            def star(value):return next(tools.starmap(star,[(value,)]))
            class Source:
                def __iter__(self):return self
                def __next__(self):return next(self.factory(self))
            factories=[('accumulate',lambda source:tools.accumulate(source)),('batched',lambda source:tools.batched(source,2)),('chain',lambda source:tools.chain(source)),('compress',lambda source:tools.compress(source,[1])),('cycle',lambda source:tools.cycle(source)),('islice',lambda source:tools.islice(source,3)),('pairwise',lambda source:tools.pairwise(source)),('tee',lambda source:tools.tee(source)[0]),('zip',lambda source:tools.zip_longest(source))]
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('accumulate',lambda:accumulation(0,0)),('drop',lambda:predicate(1)),('false',lambda:falsepredicate(1)),('take',lambda:takepredicate(1)),('key',lambda:key(1)),('star',lambda:star(1))]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
                for label,factory in factories:
                    source=Source();source.factory=factory
                    try:next(factory(source))
                    except RecursionError:print(limit,label,'source caught')
        ''')

    def test_tee_reentry_error_cleanup_and_tool_callback_gc(self):
        self.compare('''
            import itertools as tools
            class Source:
                def __init__(self):self.calls=0
                def __iter__(self):return self
                def __next__(self):
                    self.calls+=1
                    if self.calls==1:return next(self.other)
                    if self.calls==2:raise ValueError('retry')
                    if self.calls==3:return 7
                    raise StopIteration(12)
            source=Source();left,right=tools.tee(source);source.other=right
            for value in [left,right,left,left,right]:
                try:print('tee',next(value))
                except (RuntimeError,ValueError,StopIteration)as error:print(type(error).__name__,str(error))
            class Item:
                def __init__(self,value):self.value=value
                def __bool__(self):gc.collect();return bool(self.value)
            def predicate(value):gc.collect();return value
            def key(value):gc.collect();return value.value
            print([value.value for value in tools.filterfalse(predicate,[Item(0),Item(1)])])
            print([value.value for value in tools.compress([Item(2),Item(3)],[Item(0),Item(1)])])
            print([(value,[item.value for item in group])for value,group in tools.groupby([Item(1),Item(1),Item(2)],key)])
            print([value.value for value in tools.takewhile(predicate,[Item(1),Item(0)])])
        ''')

    def test_direct_next_methods_and_callback_error_retry(self):
        self.compare('''
            import itertools as tools
            def mapped(value):return map(mapped,[value]).__next__()
            def generator():yield generator().__next__()
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,operation in [('map method',lambda:mapped(1)),('generator method',lambda:generator().__next__())]:
                    try:operation()
                    except RecursionError:print(limit,label,'caught')
            def failing():
                yield [1]
                raise ValueError('outer')
            value=tools.chain.from_iterable(failing())
            print(value.__next__())
            for i in range(2):
                try:value.__next__()
                except (ValueError,StopIteration)as error:print(type(error).__name__,str(error))
            class Bad:
                def __iter__(self):raise LookupError('iter')
            value=tools.chain(Bad(),[7])
            for i in range(2):
                try:next(value)
                except (LookupError,StopIteration)as error:print(type(error).__name__,str(error))
            class Source:
                def __init__(self):self.calls=0
                def __iter__(self):return self
                def __next__(self):
                    self.calls+=1
                    if self.calls==1:raise ValueError('source')
                    return self.calls
            value=tools.zip_longest(Source(),[1,2])
            for i in range(2):
                try:next(value)
                except (ValueError,StopIteration)as error:print(type(error).__name__,str(error))
        ''')

    def test_constructor_coercions_and_send_none_do_not_reenter_host(self):
        self.compare('''
            factories=[('map',lambda value:map(abs,value)),('filter',lambda value:filter(None,value)),('zip',lambda value:zip(value)),('enumerate',lambda value:enumerate(value))]
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,factory in factories:
                    class Source:
                        def __iter__(self):return iter(factory(self))
                    try:iter(Source())
                    except RecursionError:print(limit,label,'constructor caught')
                class Reversible:
                    def __reversed__(self):return reversed(self)
                try:reversed(Reversible())
                except RecursionError:print(limit,'reversed caught')
                class Sequence:
                    def __getitem__(self,index):return index
                    def __len__(self):return len(reversed(self))
                try:reversed(Sequence())
                except RecursionError:print(limit,'reverse length caught')
                def generator():yield generator().send(None)
                try:generator().send(None)
                except RecursionError:print(limit,'send caught')
        ''')

    def test_constructor_evaluation_order_strict_lengths_and_gc(self):
        self.compare('''
            events=[]
            class Source:
                def __init__(self,name):self.name=name
                def __iter__(self):events.append(('iter',self.name));gc.collect();return iter([1,2])
            class Strict:
                def __bool__(self):events.append(('strict',));gc.collect();return True
            class Start:
                def __index__(self):events.append(('index',));gc.collect();return 3
            for label,make in [('zip',lambda:zip(Source('a'),Source('b'),strict=Strict())),('map',lambda:map(lambda a,b:a+b,Source('a'),Source('b'),strict=Strict())),('enumerate',lambda:enumerate(iterable=Source('a'),start=Start())),('filter',lambda:filter(None,Source('a')))]:
                events.clear();value=make();print(label,events,list(value))
            for label,make in [('zip',lambda*args:zip(*args,strict=True)),('map',lambda*args:map(lambda*values:values,*args,strict=True))]:
                for inputs in [([],[]),([],[1]),([1],[]),([1],[1],[]),([1],[1],[1,2])]:
                    value=make(*inputs)
                    try:print(label,list(value))
                    except ValueError as error:print(str(error))
            class Stop:
                def __iter__(self):return self
                def __next__(self):raise StopIteration(42)
            for value in [zip(Stop(),Stop(),strict=True),map(lambda*a:a,Stop(),Stop(),strict=True)]:
                try:next(value)
                except StopIteration as error:print('strict stop',error.value)
            for make in [lambda:enumerate([],start=1.5),lambda:map(abs,strict=Strict())]:
                try:make()
                except TypeError:print('type error')
            print(events)
            def generator():yield 1;return 42
            value=generator();print(value.send(None))
            try:value.send(None)
            except StopIteration as error:print('send stop',error.value)
        ''')

    def test_itertools_constructor_coercion_numeric_and_pool_recursion(self):
        self.compare('''
            import itertools as tools
            factories=[('chain',lambda value:tools.chain.from_iterable(value)),('accumulate',lambda value:tools.accumulate(value)),('batched',lambda value:tools.batched(value,2)),('compress',lambda value:tools.compress(value,[])),('cycle',lambda value:tools.cycle(value)),('dropwhile',lambda value:tools.dropwhile(bool,value)),('filterfalse',lambda value:tools.filterfalse(bool,value)),('groupby',lambda value:tools.groupby(value)),('islice',lambda value:tools.islice(value,3)),('pairwise',lambda value:tools.pairwise(value)),('starmap',lambda value:tools.starmap(abs,value)),('takewhile',lambda value:tools.takewhile(bool,value)),('tee',lambda value:tools.tee(value)),('zip_longest',lambda value:tools.zip_longest(value))]
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit)
                for label,factory in factories:
                    class Source:
                        def __iter__(self):factory(self);return iter([])
                    try:factory(Source())
                    except RecursionError:print(limit,label,'coercion caught')
                for label,factory in [('product',lambda value:tools.product(value)),('combinations',lambda value:tools.combinations(value,1)),('permutations',lambda value:tools.permutations(value))]:
                    class Source:
                        def __iter__(self):return self
                        def __next__(self):factory(self);raise StopIteration
                    try:factory(Source())
                    except RecursionError:print(limit,label,'pool caught')
                class Size:
                    def __index__(self):tools.repeat(0,self);return 1
                try:tools.repeat(0,Size())
                except RecursionError:print(limit,'numeric caught')
        ''')

    def test_itertools_constructor_order_validation_and_pool_gc(self):
        self.compare('''
            import itertools as tools
            events=[]
            class Source:
                def __init__(self,name):self.name=name
                def __iter__(self):events.append(('iter',self.name));gc.collect();return iter([1,2])
            class Size:
                def __init__(self,name,value):self.name=name;self.value=value
                def __index__(self):events.append(('index',self.name));gc.collect();return self.value
            class Strict:
                def __bool__(self):events.append(('strict',));gc.collect();return True
            for label,factory in [('batched',lambda:tools.batched(Source('a'),Size('n',2),strict=Strict())),('comb',lambda:tools.combinations(Source('a'),Size('r',1))),('product',lambda:tools.product(Source('a'),Source('b'),repeat=Size('repeat',1))),('tee0',lambda:tools.tee(Source('a'),0)),('tee',lambda:tools.tee(Source('a'),Size('n',2))),('islice',lambda:tools.islice(Source('a'),Size('start',0),Size('stop',2),Size('step',1)))]:
                events.clear();value=factory();print(label,events)
            for factory in [lambda:tools.batched(Source('a'),Size('n',-1),strict=Strict()),lambda:tools.combinations(Source('a'),Size('r',-1)),lambda:tools.permutations(Source('a'),Size('r',1)),lambda:tools.islice(Source('a'),Size('start',-1),Size('stop',2),Size('step',1))]:
                events.clear()
                try:factory()
                except (ValueError,TypeError)as error:print(type(error).__name__,str(error),events)
            class Bad:
                def __index__(self):events.append(('bad',));raise LookupError('bad')
            for args in [(Bad(),Size('stop',2),Size('step',1)),(Size('start',0),Bad(),Size('step',1))]:
                events.clear()
                try:tools.islice(Source('a'),*args)
                except ValueError as error:print(str(error),events)
            class Item:
                def __init__(self,n):self.n=n
            class Pool:
                def __iter__(self):
                    for n in range(2):gc.collect();yield Item(n)
            print([[item.n for item in values]for values in tools.product(Pool(),repeat=2)])
            print([[item.n for item in values]for values in tools.combinations(Pool(),1)])
            print([[item.n for item in values]for values in tools.permutations(Pool())])
        ''')

    def test_standalone_stream_paths_in_all_integer_modes(self):
        source=textwrap.dedent('''
            import itertools as tools
            class Source:
                def __iter__(self):gc.collect();yield 1;gc.collect();yield 2
            print(list(map(lambda x:x+1,Source(),strict=True)))
            print(list(zip(Source(),Source(),strict=True)))
            print(list(tools.product(Source(),repeat=2)))
            def inner():yield 3;return 4
            def outer():yield from inner();return 5
            value=outer();print(value.send(None))
            try:next(value)
            except StopIteration as error:print(error.value)
        ''')
        expected=subprocess.run([sys.executable,"-I","-c",WRAPPER],input=source,capture_output=True,text=True,timeout=15)
        self.assertEqual(expected.returncode,0,expected.stderr)
        for mode in ["i64","i128","bigint"]:
            with self.subTest(mode=mode):
                if mode=="i64":binary=self.binary
                else:
                    result=transpile(WRAPPER,TranspileOptions(integer=mode,optimize=False))
                    self.assertTrue(result.success,result.diagnostics)
                    rust=Path(self.directory.name)/f"{mode}.rs";rust.write_text(result.rust_source,encoding="utf-8")
                    binary=rust.with_suffix("")
                    compiled=subprocess.run(["rustc","--edition=2021",str(rust),"-o",str(binary)],capture_output=True,text=True,timeout=120)
                    self.assertEqual(compiled.returncode,0,compiled.stderr)
                actual=subprocess.run([str(binary)],input=source,capture_output=True,text=True,timeout=15)
                self.assertEqual(actual.returncode,0,actual.stderr)
                self.assertEqual(actual.stdout,expected.stdout,actual.stderr)

    def test_count_advances_before_return_and_keeps_numeric_fast_path(self):
        self.compare('''
            import itertools as tools
            events=[]
            class Number:
                def __init__(self,n):self.n=n
                def __int__(self):return self.n
                def __add__(self,other):
                    events.append((self.n,other.n));gc.collect()
                    return Number(self.n+other.n)
            value=tools.count(Number(1),Number(2))
            for i in range(3):
                item=next(value);print(item.n,events)
            class Integer(int):
                def __add__(self,other):raise AssertionError('count numeric fast path')
            value=tools.count(Integer(4),Integer(1));print([next(value)for i in range(3)])
            events=[]
            class Failing(Number):
                def __add__(self,other):events.append('add');raise LookupError('count addition')
            value=tools.count(Failing(1),Number(2))
            for i in range(2):
                try:next(value)
                except LookupError as error:print(str(error),events)
            class Recursive(Number):
                def __add__(self,other):return next(value)
            for limit in [50,1000,3000]:
                sys.setrecursionlimit(limit);value=tools.count(Recursive(1),Number(2))
                try:next(value)
                except RecursionError:print(limit,'count caught')
        ''')
