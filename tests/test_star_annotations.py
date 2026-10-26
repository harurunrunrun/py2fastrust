"""PEP 646 variadic annotations unpack exactly one value when evaluated."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class StarAnnotationTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_type_var_tuple_and_generic_alias_annotations_static_and_dynamic(self):
        self.run_source('''
            from typing import TypeVarTuple
            Ts=TypeVarTuple("Ts")
            def collect(*values:*Ts):return values
            def fixed(*values:*tuple[int,str]):return values
            def generic[*Us](*values:*Us):return values
            print(collect.__annotations__,fixed.__annotations__,generic.__annotations__)
            print(collect(1,"a"),fixed(2,"b"),generic(3,"c"))
            namespace={}
            exec('from typing import TypeVarTuple\\nTs=TypeVarTuple("Ts")\\ndef collect(*values:*Ts):return values\\ndef fixed(*values:*tuple[int,str]):return values\\ndef generic[*Us](*values:*Us):return values',namespace)
            for name in ["collect","fixed","generic"]:
                print(namespace[name].__annotations__,namespace[name](4,"d"))
        ''')

    def test_unpack_is_lazy_retries_after_errors_and_then_caches(self):
        self.run_source('''
            events=[]
            def provide():
                events.append("evaluated")
                return items
            def f(*args:*provide()):pass
            print(events)
            for items in [[],[int,str],None,[str]]:
                try:print(f.__annotations__)
                except (ValueError,TypeError) as error:print(type(error).__name__)
                print(events)
            items=[int]
            first=f.__annotations__
            print(first,first is f.__annotations__,events)
            namespace={"events":events,"provide":provide}
            exec('def dynamic(*args:*provide()):pass',namespace)
            print(namespace["dynamic"].__annotations__,events)
        ''')

    def test_iterator_and_first_value_stay_rooted_during_second_next(self):
        self.run_source('''
            import gc
            events=[]
            class Step:
                def __init__(self):self.index=0
                def __iter__(self):return self
                def __next__(self):
                    self.index+=1
                    events.append(self.index)
                    if self.index==1:return [77]
                    gc.collect()
                    raise StopIteration
            class Pack:
                def __iter__(self):return Step()
            def f(*args:*Pack()):pass
            print(f.__annotations__,events)
            namespace={"Pack":Pack}
            exec('def dynamic(*args:*Pack()):pass',namespace)
            print(namespace["dynamic"].__annotations__,events)
            type Alias[*Ts=*Pack()] = tuple[*Ts]
            print(Alias.__type_params__[0].__default__,events)
        ''')

    def test_class_private_names_and_generic_parameter_closures(self):
        self.run_source('''
            class Scope:
                __items=(int,)
                def f(*__args:*__items):pass
            Scope._Scope__items=(str,)
            print(Scope.f.__annotations__)
            def outer[*Ts]():
                def inner(*args:*Ts):pass
                return inner
            print(outer().__annotations__)
            namespace={}
            exec('class Scope:\\n __items=(int,)\\n def f(*__args:*__items):pass\\nScope._Scope__items=(str,)\\nprint(Scope.f.__annotations__)',namespace)
        ''')

    def test_future_stringization_uses_official_star_precedence(self):
        self.run_source('''
            from __future__ import annotations
            def simple(*args:*Ts):pass
            def compound(*args:*(left | right)):pass
            def tuple_value(*args:*(int,str)):pass
            def nested(*args:*tuple[call(x for x in source)]):pass
            print(simple.__annotations__,compound.__annotations__,tuple_value.__annotations__,nested.__annotations__)
            namespace={}
            exec('from __future__ import annotations\\ndef simple(*args:*Ts):pass\\ndef compound(*args:*(left | right)):pass\\ndef tuple_value(*args:*(int,str)):pass\\ndef nested(*args:*tuple[call(x for x in source)]):pass',namespace)
            for name in ["simple","compound","tuple_value","nested"]:
                print(namespace[name].__annotations__)
        ''')

    def test_runtime_optimized_annotations_preserve_debug_constant(self):
        self.run_source('''
            for level in [0,1,2]:
                namespace={}
                exec(compile('def f(*args:*([__debug__],)):pass',"star.py","exec",optimize=level),namespace)
                print(level,namespace["f"].__annotations__)
        ''')


if __name__ == "__main__":
    unittest.main()
