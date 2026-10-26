"""Observable runtime behavior of type parameters, aliases and union values."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class TypeParameterRuntimeTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_manual_parameters_metadata_and_validation(self):
        self.run_source('''
            import typing
            for constructor in [typing.TypeVar, typing.ParamSpec, typing.TypeVarTuple]:
                parameter = constructor("T")
                print(type(parameter).__name__, parameter.__name__, repr(parameter),
                      parameter.__module__, parameter.has_default(),
                      parameter.__default__ is typing.NoDefault)
                parameter.note = "metadata"
                parameter.__module__ = "sample"
                print(parameter.note, parameter.__module__)
                for name in ["__name__", "__default__"]:
                    try:
                        setattr(parameter, name, "other")
                    except AttributeError:
                        print("readonly", name)
            for parameter in [typing.TypeVar("C", covariant=True),
                              typing.TypeVar("D", contravariant=True),
                              typing.TypeVar("I", infer_variance=True),
                              typing.ParamSpec("P", default=[int, str])]:
                print(repr(parameter), parameter.__covariant__,
                      parameter.__contravariant__, parameter.__infer_variance__,
                      parameter.has_default())
            print(typing.TypeVar("T", int, str).__constraints__)
            print(typing.TypeVar("T", int, str, bound=None).__constraints__)
            for create in [lambda: typing.TypeVar("T", int),
                           lambda: typing.TypeVar("T", int, str, bound=int),
                           lambda: typing.TypeVar("T", covariant=True, contravariant=True),
                           lambda: typing.TypeVar("T", infer_variance=True, covariant=True),
                           lambda: typing.ParamSpec("P", int),
                           lambda: typing.TypeVarTuple("Ts", int)]:
                try:
                    create()
                except (TypeError, ValueError) as error:
                    print(type(error).__name__)
        ''')

    def test_parameter_substitution_markers_and_forward_references(self):
        self.run_source('''
            from typing import TypeVar, ParamSpec, TypeVarTuple, Unpack, ForwardRef
            T, P, Ts = TypeVar("T"), ParamSpec("P"), TypeVarTuple("Ts")
            print(P.args, P.kwargs, type(P.args).__name__, type(P.kwargs).__name__)
            print(P.args.__origin__ is P, P.kwargs.__origin__ is P,
                  P.args == P.args, P.args == P.kwargs)
            print(tuple(Ts), Unpack[Ts], Unpack[Ts].__args__,
                  Unpack[Ts].__parameters__, next(iter(Ts)) == Unpack[Ts])
            for value in [None, int, [int], 1, "Forward"]:
                replacement = T.__typing_subst__(value)
                print(repr(replacement))
            print(T.__typing_subst__("Forward") == ForwardRef("Forward"))
            print(hash(ForwardRef("Forward")) == hash(ForwardRef("Forward")))
            for value in [(), (int, str), [int], P, ...]:
                print(P.__typing_subst__(value))
            for value in [None, int, (), Unpack[Ts]]:
                try:
                    Ts.__typing_subst__(value)
                except TypeError as error:
                    print(type(error).__name__)
        ''')

    def test_lazy_alias_evaluators_cache_retry_and_gc(self):
        self.run_source('''
            import gc
            calls = []
            def value():
                calls.append(len(calls))
                return list[int]
            type A = value()
            print(A, A.__name__, A.__module__, A.__type_params__,
                  type(A).__name__, calls)
            print(A.evaluate_value(), A.evaluate_value(), calls)
            print(A.__value__, A.__value__, calls)
            print(A.evaluate_value(), calls)
            type Retry = missing
            for i in range(2):
                try:
                    Retry.__value__
                except NameError as error:
                    print(type(error).__name__)
            missing = str
            print(Retry.__value__)
            missing = int
            print(Retry.__value__ is str)
            type Recursive = list[Recursive]
            print(Recursive.__value__.__args__[0] is Recursive)
            def build():
                captured = [1, 2]
                type Held = captured
                captured.append(3)
                return Held
            held = build()
            gc.collect()
            print(held.__value__)
        ''')

    def test_lazy_parameter_attributes_evaluator_and_default_presence(self):
        self.run_source('''
            from typing import NoDefault
            calls = []
            def mark(name):
                calls.append(name)
                return int
            def f[T: mark("bound") = mark("default"), U: (int, str) = str]():
                return T, U
            T, U = f.__type_params__
            print(T.__module__, repr(T), T.__infer_variance__,
                  T.has_default(), U.has_default(), calls)
            print(T.evaluate_bound(), T.evaluate_bound(), calls)
            print(T.__bound__, T.__bound__, calls)
            print(T.evaluate_default(), T.__default__, T.__default__, calls)
            print(U.__constraints__, U.__default__, U.evaluate_constraints())
            print(f() == (T, U), T.__default__ is NoDefault)
        ''')

    def test_union_flattening_substitution_and_hashing(self):
        self.run_source('''
            from typing import TypeVar, Union, get_args, get_origin
            T = TypeVar("T")
            for value in [int | str, Union[int, str], int | None,
                          list[T] | dict[str, T], T | int]:
                print(value, value.__args__, get_args(value),
                      value.__origin__ is Union, get_origin(value) is Union,
                      value.__parameters__)
            print(int | int is int, (int | str) | int == str | int)
            print(hash(int | str) == hash(str | int))
            print((list[T] | int)[str] == list[str] | int)
            print(isinstance(1, int | str), isinstance([], int | str),
                  issubclass(bool, int | str))
            type Alias = int
            for invalid in [T, Alias]:
                for check in [lambda: isinstance(1, invalid),
                              lambda: issubclass(int, invalid)]:
                    try:
                        check()
                    except TypeError as error:
                        print(type(error).__name__)
        ''')

    def test_manual_alias_constructor_and_arbitrary_subscription(self):
        self.run_source('''
            from typing import TypeAliasType, TypeVar, get_origin, get_args
            from types import GenericAlias
            T = TypeVar("T")
            Alias = TypeAliasType("Alias", list[T], type_params=(T,))
            print(Alias, type(Alias).__name__, Alias.__value__, Alias.__module__,
                  Alias.__parameters__, Alias.__type_params__)
            for key in [(), int, (int, str)]:
                alias = Alias[key]
                print(alias, type(alias) is GenericAlias, get_origin(alias) is Alias,
                      get_args(alias), alias.__parameters__)
            try:
                Alias.extra = 1
            except AttributeError as error:
                print(type(error).__name__)
        ''')


if __name__ == "__main__":
    unittest.main()
