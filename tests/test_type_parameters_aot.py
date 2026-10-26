"""PEP 695/696 AOT scopes and their lazy runtime objects against Python 3.14."""

import shutil
import unittest

from py2fastrust.compiler import Compiler
import test_runtime


class TypeParameterFrontendTests(unittest.TestCase):
    def test_official_type_parameter_and_evaluator_scopes_are_retained(self):
        program = Compiler().compile("def f[T: Bound=Default](value:T)->T:\n return value,T\n")
        wrapper = next(code for code in program.codes if code.kind == "TypeParameters")
        function = next(code for code in program.codes if code.kind == "Function" and code.name == "f")
        evaluators = [code for code in program.codes if code.kind == "Annotation"]
        self.assertIn("T", wrapper.locals)
        self.assertIn("T", function.frees)
        self.assertEqual([op.args for op in wrapper.ops if op.op == "MakeTypeParam"], [("T", "typevar")])
        self.assertEqual(len(evaluators), 3)
        for evaluator in evaluators:
            self.assertEqual(evaluator.params.positional, [".format"])
            self.assertEqual(evaluator.params.posonly, 1)


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class TypeParameterAotTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_function_parameters_scope_closure_and_annotations(self):
        self.run_source('''
            def identity[T](value:T)->T:
                return value, T
            T = identity.__type_params__[0]
            print(T, type(T).__name__, T.__name__, T.__module__)
            print(T.__infer_variance__, T.__covariant__, T.__contravariant__)
            print(identity(7)[0], identity(7)[1] is T)
            print(identity.__annotations__["value"] is T, identity.__annotations__["return"] is T)
            def outer(value):
                def inner[U]():
                    return value, U
                return inner
            first = outer(11)
            second = outer(13)
            print(first()[0], second()[0], first.__type_params__[0] is second.__type_params__[0])
            print("U" in globals())
        ''')

    def test_lazy_bound_constraints_default_cache_and_evaluators(self):
        self.run_source('''
            seen = []
            Bound = int
            Default = str
            def resolve(label, value):
                seen.append(label)
                return value
            def f[U:(resolve("a", int), resolve("b", str)), T:resolve("bound", Bound)=resolve("default", Default)](): pass
            U, T = f.__type_params__
            print(seen, U.has_default(), T.has_default())
            Bound = bytes
            Default = float
            print(T.__bound__ is bytes, T.__bound__ is bytes, seen)
            Bound = int
            print(T.evaluate_bound() is int, T.__bound__ is bytes, seen)
            print(U.__constraints__, U.__constraints__, seen)
            print(T.__default__ is float, T.__default__ is float, seen)
            Default = str
            print(T.evaluate_default() is str, T.__default__ is float, seen)
            try:
                T.evaluate_bound(3)
            except NotImplementedError:
                print("unsupported format")
        ''')

    def test_alias_forward_resolution_cache_and_recursive_values(self):
        self.run_source('''
            seen = []
            def resolve(value):
                seen.append(1)
                return value
            type Alias[T=int] = resolve(tuple[T, Other])
            print(Alias, type(Alias).__name__, Alias.__name__, Alias.__module__, seen)
            T = Alias.__type_params__[0]
            Other = str
            value = Alias.__value__
            print(value.__origin__ is tuple, value.__args__[0] is T, value.__args__[1] is str, seen)
            Other = bytes
            print(Alias.__value__ is value, Alias.evaluate_value().__args__[1] is bytes, seen)
            type Recursive = list[Recursive]
            print(Recursive.__value__.__args__[0] is Recursive)
            print(Alias[str].__origin__ is Alias, Alias[str].__args__)
        ''')

    def test_param_specs_variadic_defaults_and_unpack_validation(self):
        self.run_source('''
            import typing
            def f[T, *Ts=*tuple[int,...], **P=[str,int]](): pass
            T, Ts, P = f.__type_params__
            print(T.__default__ is typing.NoDefault, T.has_default())
            print(type(Ts).__name__, Ts.__default__, Ts.__default__.__unpacked__)
            print(type(P).__name__, P.__default__, P.args, P.kwargs)
            def one[*Ts=*[17]](): pass
            print(one.__type_params__[0].__default__)
            def many[*Ts=*[1,2]](): pass
            def empty[*Ts=*[]](): pass
            for function in [many, empty]:
                try:
                    function.__type_params__[0].__default__
                except ValueError:
                    print("unpack error")
        ''')

    def test_class_type_parameters_bases_namespace_and_field_annotations(self):
        self.run_source('''
            import typing
            class Meta(type):
                def __new__(meta, name, bases, namespace):
                    print(list(namespace)[:5])
                    print(namespace["__type_params__"])
                    return super().__new__(meta, name, bases, namespace)
            class Box[T](metaclass=Meta):
                field:T
                def __init__(self, value): self.field=value
                def parameter(self): return T
            T = Box.__type_params__[0]
            print(Box.__bases__ == (typing.Generic,), Box.__parameters__ == (T,))
            print(Box.__orig_bases__[0].__origin__ is typing.Generic)
            print(Box(19).parameter() is T, Box.__annotations__["field"] is T)
            class Items[U](list[U]): pass
            print(Items.__bases__ == (list,typing.Generic), Items.__orig_bases__[0].__origin__ is list)
            print(Items[int].__origin__ is Items, Items[int].__args__)
        ''')

    def test_class_namespace_lazy_lookup_and_private_type_names(self):
        self.run_source('''
            class Example[__T]:
                selected = int
                type __Alias[__U=selected] = tuple[__T,__U,selected]
                def f[__V:selected=selected](self): return __T,__V
            T = Example.__type_params__[0]
            alias = Example._Example__Alias
            U = alias.__type_params__[0]
            V = Example.f.__type_params__[0]
            print(T.__name__, U.__name__, V.__name__)
            Example.selected = str
            print(U.__default__ is str, V.__bound__ is str, V.__default__ is str)
            print(alias.__value__.__args__[0] is T, alias.__value__.__args__[1] is U, alias.__value__.__args__[2] is str)
            print(Example().f()[0] is T, Example().f()[1] is V)
        ''')

    def test_decorator_and_default_outer_scope_order(self):
        self.run_source('''
            seen = []
            T = "outer"
            def record(value):
                seen.append(value)
                return value
            def decorate(label):
                seen.append(label)
                def apply(function):
                    seen.append(function.__name__)
                    return function
                return apply
            @decorate("decorator")
            def f[T](value=record(T), *, key=record("keyword")):
                return value,key,T
            print(seen, f()[0:2], f()[2] is f.__type_params__[0])
            captured = []
            def replace(cls):
                captured.append(cls)
                return str
            @replace
            class Replaced[T:Replaced]: pass
            print(Replaced is str, captured[0].__type_params__[0].__bound__ is str)
        ''')

    def test_lazy_class_annotations_conditional_cells_and_mutation(self):
        self.run_source('''
            seen=[]
            def resolve(label,value):
                seen.append(label)
                return value
            class C[T]:
                selected=int
                always:resolve("always",T)
                if True:
                    chosen:resolve("chosen",selected)
                if False:
                    never:Missing
                for item in [1]:
                    repeated:resolve("loop",str)
            print(seen, "__conditional_annotations__" in C.__dict__)
            C.selected=bytes
            annotations=C.__annotations__
            print(list(annotations), annotations["always"] is C.__type_params__[0], annotations["chosen"] is bytes, seen)
            print(C.__annotations__ is annotations, seen)
            print(C.__annotate__(1)["chosen"] is bytes, seen)
        ''')

    def test_future_annotations_keep_generic_parameter_strings(self):
        self.run_source('''
            from __future__ import annotations
            def f[T:Bound=Default](value:T)->list[T]: return value,T
            print(f.__annotations__, f.__type_params__[0].__name__)
            class C[T]:
                field:T
                type Alias[U=T] = tuple[T,U]
            print(C.__annotations__, C.Alias.__type_params__[0].__default__ is C.__type_params__[0])
        ''')

    def test_lazy_module_annotations_conditions_and_late_names(self):
        self.run_source('''
            import sys
            seen=[]
            def resolve(label,value):
                seen.append(label)
                return value
            field:resolve("field",Later)
            if True:
                chosen:resolve("chosen",str)
            if False:
                absent:Missing
            Later=int
            module=sys.modules["__main__"]
            print(seen)
            annotations=module.__annotations__
            print(list(annotations),annotations["field"] is int,annotations["chosen"] is str,seen)
            Later=bytes
            print(module.__annotations__ is annotations,module.__annotations__["field"] is int,seen)
            print(module.__annotate__(1)["field"] is bytes,seen)
        ''')


if __name__ == "__main__":
    unittest.main()
