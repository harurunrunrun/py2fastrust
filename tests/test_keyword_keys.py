"""Keyword calls retain original string keys and Python comparison effects."""

import shutil
import textwrap
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class KeywordKeyTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def compare_both(self, source):
        source = textwrap.dedent(source)
        self.run_source(source + "\nprint('dynamic')\nexec(" + repr(source) + ")\n")

    def test_argument_name_matching_and_original_keyword_objects(self):
        self.compare_both('''
            events = []
            class Key(str):
                def __hash__(self): events.append(('hash', str.__str__(self))); return str.__hash__(self)
                def __eq__(self, other): events.append(('eq', str.__str__(self), other)); return str.__eq__(self, other)
                def __str__(self): raise RuntimeError('must not stringify keys')
            key = Key('c')
            mapping = {key: 9}
            def named(a=1,b=2,c=3): return a,b,c
            events.clear()
            print(named(**mapping), events)
            def collect(**kwargs): return kwargs
            events.clear()
            result = collect(**mapping)
            print(next(iter(result)) is key, type(next(iter(result))).__name__, events)
            events.clear()
            second = collect(**result)
            print(next(iter(second)) is key, events)
            class Spoof(str):
                def __eq__(self, other): events.append(('spoof',other)); return other == 'wanted'
                __hash__=str.__hash__
            def target(wanted): return wanted
            mapping = {Spoof('different'): 77}
            events.clear()
            print(target(**mapping),events)
        ''')

    def test_mapping_hashes_reused_but_collector_hashes_again(self):
        self.compare_both('''
            events=[]
            class Key(str):
                broken=False
                def __hash__(self):
                    events.append('hash')
                    if self.broken: raise RuntimeError('broken hash')
                    return str.__hash__(self)
            key=Key('wanted')
            mapping={key:3}
            key.broken=True
            events.clear()
            def named(wanted): return wanted
            def collect(**kwargs): return kwargs
            print(named(**mapping),events)
            try: collect(**mapping)
            except RuntimeError: print('collector raises',events)
            key.broken=False
            events.clear()
            print(dict(mapping),events)
            print(mapping.copy(),events)
        ''')

    def test_keyword_evaluation_blocks_and_mapping_duplicates(self):
        self.compare_both('''
            events=[]
            def mark(name): events.append(name); return 1
            def target(**kwargs): return kwargs
            try: target(**{'x':0},x=mark('x'),later=mark('later'))
            except TypeError: print(events)
            events.clear()
            try:
                class C(*[],**{'x':0},x=mark('x'),later=mark('later')): pass
            except TypeError: print(events)
            events.clear()
            class Mapping:
                def keys(self): events.append('keys'); return ['a','a','later']
                def __getitem__(self,key): events.append(('get',key)); return 1
            try: target(**Mapping())
            except TypeError: print(events)
        ''')

    def test_custom_mapping_hash_effects_and_transient_dictionary_copies(self):
        self.compare_both('''
            events=[]
            class Key(str):
                def __hash__(self): events.append(('hash',str.__str__(self))); return str.__hash__(self)
            class Mapping:
                def keys(self): events.append('keys'); return [Key('a'),Key('b')]
                def __getitem__(self,key): events.append(('get',str.__str__(key))); return 1
            def collect(**kwargs): return kwargs
            def named(a,b): return a,b
            print(collect(**Mapping()),events)
            events.clear()
            print({**Mapping()},events)
            events.clear()
            source={Key('a'):1,Key('b'):2}
            events.clear()
            print(named(**{**source}),events)
            events.clear()
            print(named(**(source | {})),events)
            events.clear()
            print(named(**(source.copy())),events)
            events.clear()
            print(named(**dict(source)),events)
        ''')

    def test_stored_hashes_survive_key_hash_changes_and_dictionary_mutation(self):
        self.compare_both('''
            class Key(str):
                salt=0
                def __hash__(self): return str.__hash__(self)+self.salt
            key=Key('value')
            source={key:1}
            key.salt=1
            def named(value): return value
            def collect(**kwargs): return kwargs
            print(named(**source))
            result=collect(**source)
            print(result[key],next(iter(result)) is key)
            for copied in [source,source.copy(),dict(source),{**source},source | {}]:
                try: print(copied[key])
                except KeyError: print('old hash')
            source.clear()
            source[key]=2
            print(source[key],named(**source))
            del source[key]
            source[key]=3
            print(source[key])
        ''')

    def test_one_key_object_can_retain_different_hashes_in_two_entries(self):
        self.compare_both('''
            from functools import partial
            class Key(str):
                salt=0
                def __hash__(self): return 17+self.salt
            key=Key('value')
            source={key:10}
            key.salt=1
            source[key]=20
            keys=list(source)
            print(len(source),keys[0] is keys[1],source[key],list(source.values()),list(reversed(source.items())))
            def collect(**kwargs): return kwargs
            def named(value): return value
            print(collect(**source))
            try: named(**source)
            except TypeError: print('duplicate named')
            p=partial(collect,**source)
            print(len(p.keywords),p())
            copied=source.copy()
            print(len(copied),copied[key])
            iterator=iter(source.items())
            print(next(iterator))
            del source[key]
            source['other']=30
            print(list(iterator),list(source.items()))
            del source['other']
            try: print(source[key])
            except KeyError: print('old entry remains')
            key.salt=0
            print(source[key],source.popitem(),len(source))
        ''')

    def test_partial_keyword_forwarding_and_replacement_key_identity(self):
        self.compare_both('''
            from functools import partial
            class Key(str): pass
            key=Key('name')
            other=Key('name')
            def collect(**kwargs): return kwargs
            p=partial(collect,**{key:1})
            print(next(iter(p.keywords)) is key)
            r=p(**{other:2})
            print(r,next(iter(r)) is key)
            p2=partial(p,**{other:3})
            print(next(iter(p2.keywords)) is key,p2())
            p.keywords.clear()
            p.keywords[key]=4
            print(next(iter(p())) is key)
        ''')

    def test_partial_and_dictionary_copy_preserve_known_entry_hashes(self):
        self.compare_both('''
            from functools import partial
            events=[]
            class Key(str):
                def __hash__(self): events.append(('hash',str.__str__(self))); return str.__hash__(self)
                def __eq__(self,other): events.append(('eq',str.__str__(self),other)); return str.__eq__(self,other)
            key=Key('x')
            source={key:1}
            def collect(**kwargs): return kwargs
            events.clear()
            p=partial(collect,**source)
            print('new',events)
            events.clear()
            print(next(iter(p())) is key,events)
            events.clear()
            q=partial(p,**source)
            print('nested',events)
            events.clear()
            print(next(iter(p(**source))) is key,events)
            events.clear()
            copied={}
            copied.update(**source)
            print(next(iter(copied)) is key,events)
        ''')

    def test_metaclass_keyword_pop_and_original_forwarding(self):
        self.compare_both('''
            events=[]
            class Meta(type):
                @classmethod
                def __prepare__(mcls,name,bases,**kwargs):
                    events.append(('prepare',[(type(key).__name__,key is flag) for key in kwargs]))
                    return {}
                def __new__(mcls,name,bases,namespace,**kwargs):
                    events.append(('new',[(type(key).__name__,key is flag) for key in kwargs]))
                    return super().__new__(mcls,name,bases,namespace)
            class Key(str):
                def __hash__(self): return str.__hash__(self)
                def __str__(self): raise RuntimeError('no stringify')
            flag=Key('flag')
            class C(**{Key('metaclass'):Meta,flag:1}): pass
            print(type(C).__name__,events)
            class Spoof(str):
                def __hash__(self): return hash('metaclass')
                def __eq__(self,other): return other=='metaclass'
            class D(**{Spoof('other'):Meta}): pass
            print(type(D).__name__)
            class NotMeta(str):
                def __hash__(self): return str.__hash__(self)
                def __eq__(self,other): return False
            try:
                class E(**{NotMeta('metaclass'):Meta}): pass
            except TypeError: print('not metaclass')
        ''')

    def test_cached_calls_hash_keys_and_keep_distinct_keyword_order(self):
        self.compare_both('''
            from functools import lru_cache
            events=[]
            class Key(str):
                def __hash__(self): events.append(('hash',str.__str__(self))); return str.__hash__(self)
                def __eq__(self,other): events.append(('eq',str.__str__(self),other)); return str.__eq__(self,other)
            key=Key('extra')
            mapping={key:3}
            @lru_cache(maxsize=None)
            def collect(**kwargs):
                events.append('body')
                return kwargs
            events.clear()
            result=collect(**mapping)
            print(next(iter(result)) is key,events)
            events.clear()
            print(collect(**mapping) is result,events)
            other=Key('extra')
            second={other:3}
            events.clear()
            print(collect(**second) is result,events)
            print(collect.cache_info().hits,collect.cache_info().misses)
        ''')

    def test_binding_order_duplicate_positional_only_and_cross_execution(self):
        self.compare_both('''
            events=[]
            class Key(str):
                def __hash__(self): return str.__hash__(self)
                def __eq__(self,other): events.append((str.__str__(self),other)); return str.__eq__(self,other)
            def f(a,/,b=2,*,c=3,**kwargs): return a,b,c,kwargs
            key=Key('a')
            events.clear()
            result=f(1,**{key:4,Key('b'):5,Key('c'):6})
            print(result,next(iter(result[-1])) is key,events)
            events.clear()
            try: f(1,7,**{Key('b'):9,Key('c'):10})
            except TypeError: print('duplicate',events)
            def restricted(a,/,b): return a,b
            events.clear()
            try: restricted(**{Key('a'):1})
            except TypeError: print('posonly',events)
            namespace={}
            exec('def dynamic(**kwargs): return kwargs',namespace)
            source={Key('token'):8}
            result=namespace['dynamic'](**source)
            print(next(iter(result)) is next(iter(source)))
            exec('print(f(11, **source))',globals(),{'source':source})
            print(eval("namespace['dynamic'](**source)")==source)
        ''')

    def test_colliding_keyword_keys_preserve_comparison_effects(self):
        self.compare_both('''
            from functools import partial
            events=[]
            class Key(str):
                def __hash__(self): events.append(('hash',str.__str__(self))); return 17
                def __eq__(self,other): events.append(('eq',str.__str__(self),str.__str__(other))); return str.__eq__(self,other)
            a,b=Key('a'),Key('b')
            left,right={a:1},{b:2}
            def collect(**kwargs): return kwargs
            events.clear()
            result=collect(**left,**right)
            print(result,events)
            events.clear()
            p=partial(collect,**result)
            print('partial',events)
            events.clear()
            print(p(),events)
            events.clear()
            print(dict(result),events)
            class DescriptorKey(str):
                __eq__=str.__eq__
                __hash__=str.__hash__
            def named(a): return a
            print(named(**{DescriptorKey('a'):8}))
        ''')

    def test_keyword_keys_in_new_init_and_builtin_dictionary_receivers(self):
        self.compare_both('''
            events=[]
            class Key(str):
                def __hash__(self): events.append('hash'); return str.__hash__(self)
                def __str__(self): raise RuntimeError('no str')
            key=Key('option')
            source={key:9}
            class C:
                def __new__(cls,**kwargs):
                    events.append(('new',next(iter(kwargs)) is key))
                    return super().__new__(cls)
                def __init__(self,**kwargs): events.append(('init',next(iter(kwargs)) is key))
            events.clear()
            C(**source)
            print(events)
            class D(dict): pass
            events.clear()
            result=D(**source)
            print(next(iter(result)) is key,events)
            events.clear()
            result=D(source)
            print(next(iter(result)) is key,events)
            events.clear()
            dict.__init__(result,**source)
            print(next(iter(result)) is key,events)
        ''')

    def test_cache_entries_keep_keyword_key_objects_as_gc_roots(self):
        self.compare_both('''
            from functools import lru_cache
            import gc
            events=[]
            class Key(str):
                def __del__(self): events.append(str.__str__(self))
            @lru_cache(maxsize=None)
            def f(x): return x
            print(f(**{Key('x'):123}))
            gc.collect()
            print(events)
            f.cache_clear()
            gc.collect()
            print(events)
        ''')

    def test_dirty_dictionary_copy_and_empty_merge_comparison_effects(self):
        self.compare_both('''
            from functools import partial
            events=[]
            class Key(str):
                def __hash__(self): events.append(('hash',str.__str__(self))); return 17
                def __eq__(self,other): events.append(('eq',str.__str__(self),str.__str__(other))); return str.__eq__(self,other)
            def collect(**kwargs): return kwargs
            for size in [2,5,9,17]:
                for remaining in [1,2]:
                    source={Key(str(index)):index for index in range(size)}
                    for key in list(source)[:size-remaining]: del source[key]
                    for operation in [lambda:source.copy(),lambda:dict(source),lambda:{**source},lambda:collect(**source),lambda:partial(collect,**source)]:
                        events.clear()
                        result=operation()
                        print(size,remaining,events)
                        if isinstance(result,dict): print(list(result))
        ''')

    def test_keyword_abi_compiles_and_runs_in_wide_integer_modes(self):
        source='''
            from functools import partial
            class Key(str): pass
            key=Key('value')
            def named(value): return value+1
            def collect(**kwargs): return kwargs
            result=partial(collect,**{key:9})()
            print(named(**result),next(iter(result)) is key)
            exec("print(named(**result),next(iter(collect(**result))) is key)")
        '''
        for integer in ('i128','bigint'):
            with self.subTest(integer=integer):
                self.run_source(source,integer=integer)

    def test_saved_dictionary_hashes_do_not_depend_on_callable_display_names(self):
        self.compare_both('''
            from functools import lru_cache,partial
            class C: pass
            def f(): return 1
            cached=lru_cache(None)(f)
            p=partial(f)
            objects=[C,f,cached,p]
            values={value:index for index,value in enumerate(objects)}
            hashes=[hash(value) for value in objects]
            C.__name__='Renamed'
            f.__name__='renamed'
            cached.__name__='cached renamed'
            p.label='changed'
            print([hash(value)==old for value,old in zip(objects,hashes)])
            print([values[value] for value in objects])
        ''')

    def test_static_keyword_identifiers_are_interned_across_code_and_compilation(self):
        self.compare_both('''
            def key(**kwargs): return next(iter(kwargs))
            def first(): return key(abc=1)
            def second(): return key(abc=2)
            def expanded(): return key(**{},abc=3)
            print(first() is second(),first() is expanded(),first() is 'abc')
            def japanese_first(): return key(日本=1)
            def japanese_second(): return key(**{},日本=2)
            print(japanese_first() is japanese_second())
            namespace={'key':key}
            exec('x=key(abc=4)',namespace)
            exec('y=key(**{},abc=5)',namespace)
            print(namespace['x'] is namespace['y'],first() is namespace['x'])
            code=compile('z=key(abc=6)','interned.py','exec')
            exec(code,namespace)
            print(first() is namespace['z'])
            original=''.join(['ab','c'])
            print(key(**{original:7}) is original,key(**{original:7}) is first())
            class Key(str): pass
            subclass=Key('abc')
            print(key(**{subclass:8}) is subclass)
        ''')

    def test_static_keyword_identity_crosses_cache_partial_and_class_headers(self):
        self.compare_both('''
            from functools import lru_cache,partial
            def key(**kwargs): return next(iter(kwargs))
            def plain(): return key(abc=1)
            def make_partial(): return partial(key,abc=2)
            @lru_cache(None)
            def cached(**kwargs): return next(iter(kwargs))
            def cache_first(): return cached(abc=3)
            def cache_second(): return cached(**{},abc=4)
            p=make_partial()
            print(plain() is next(iter(p.keywords)),plain() is p())
            print(plain() is cache_first(),cache_first() is cache_second())
            def metaclass(name,bases,namespace,**kwargs): return next(iter(kwargs))
            def make_first():
                class Result(metaclass=metaclass,abc=5): pass
                return Result
            def make_second():
                class Result(*[],**{'metaclass':metaclass},abc=6): pass
                return Result
            print(make_first() is make_second(),make_first() is plain())
        ''')

    def test_bounded_cache_key_collision_and_disabled_hashing_effects(self):
        self.compare_both('''
            from functools import lru_cache
            events=[]
            class Key(str):
                def __hash__(self): events.append(('hash',str.__str__(self))); return 17
                def __eq__(self,other): events.append(('eq',str.__str__(self),str.__str__(other))); return str.__eq__(self,other)
            a,b,c=Key('a'),Key('b'),Key('c')
            first,second,third={a:1},{b:1},{c:1}
            for capacity in [None,2]:
                @lru_cache(capacity)
                def cached(**kwargs): events.append('body'); return next(iter(kwargs))
                events.clear()
                cached(**first);cached(**second)
                comparisons=[event for event in events if isinstance(event,tuple) and event[0]=='eq']
                print(capacity,[event for event in events if event not in comparisons],bool(comparisons),all(event==('eq','a','b') for event in comparisons))
                cached(**third)
                print(cached.cache_info().currsize)
            @lru_cache(0)
            def uncached(value): return len(value)
            print(uncached([1,2]),uncached.cache_info().hits,uncached.cache_info().misses)
        ''')

    def test_cache_hash_callback_clear_preserves_fresh_statistics_and_keys(self):
        self.compare_both('''
            from functools import lru_cache
            import gc
            events=[]
            class Key(str):
                armed=False
                def __hash__(self):
                    if self.armed:
                        self.armed=False
                        cached.cache_clear()
                        gc.collect()
                        events.append('cleared')
                    return str.__hash__(self)
            @lru_cache(None)
            def cached(**kwargs): events.append('body'); return kwargs
            key=Key('value')
            mapping={key:1}
            cached(**mapping)
            key.armed=True
            result=cached(**mapping)
            print(events,next(iter(result)) is key,cached.cache_info().hits,cached.cache_info().misses,cached.cache_info().currsize)
        ''')

    def test_keyword_objects_remain_gc_roots_during_binding(self):
        self.compare_both('''
            import gc
            class Key(str):
                def __eq__(self,other): gc.collect(); return str.__eq__(self,other)
                def __hash__(self): gc.collect(); return str.__hash__(self)
            def named(first,second,**kwargs):
                gc.collect()
                return first,second,[(type(key).__name__,value) for key,value in kwargs.items()]
            print(named(**{Key('first'):1,Key('second'):2,Key('extra'):3}))
            class Args:
                def __iter__(self): gc.collect(); return iter(())
            print(named(*Args(),**{Key('first'):10,Key('second'):11,Key('extra'):12}))
            class Dictionary(dict): pass
            wrapped=Dictionary({Key('first'):13,Key('second'):14,Key('extra'):15})
            gc.collect()
            print(named(**wrapped))
            def outer(**kwargs): return named(**kwargs)
            print(outer(**{Key('first'):4,Key('second'):5,Key('extra'):6}))
            exec("print(named(**{Key('first'):7,Key('second'):8,Key('extra'):9}))")
        ''')


if __name__ == '__main__':
    unittest.main()
