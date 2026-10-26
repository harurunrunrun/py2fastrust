"""Runtime type arguments are substituted through real Python type parameters."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class GenericSubstitutionTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_ordered_parameters_nested_containers_and_lazy_cache(self):
        self.run_source('''
            from types import GenericAlias
            from typing import TypeVar
            T = TypeVar("T")
            U = TypeVar("U")
            other = TypeVar("T")
            for alias in [dict[T, list[U]], tuple[T, T, U],
                          GenericAlias(list, [T, (U, T)]), tuple[T, other]]:
                print(alias.__parameters__,
                      alias.__parameters__ is alias.__parameters__)
            print(dict[T, list[U]][int, str])
            print(GenericAlias(list, [T, (U, T)])[int, str])
            events = []
            class Foreign:
                @property
                def __parameters__(self):
                    events.append("parameters")
                    return (T,)
                def __getitem__(self, key):
                    return "foreign", key
            alias = GenericAlias(list, Foreign())
            print(events)
            parameters = alias.__parameters__
            print(parameters, events,
                  alias.__parameters__ is parameters)
            print(alias[str], events)
            class Bare:
                __parameters__ = (T,)
            print(list[Bare].__parameters__)
            values = [T]
            alias = GenericAlias(list, values)
            values.append(U)
            parameters = alias.__parameters__
            values.append(other)
            print(parameters, alias.__parameters__ is parameters)
            class Renamed:
                __parameters__ = (T,)
                def __getitem__(self, key):
                    return key
            Renamed.__name__ = "type"
            alias = GenericAlias(list, Renamed())
            print(alias.__parameters__, alias[int])
        ''')

    def test_typevar_replacement_partial_substitution_defaults_and_arity(self):
        self.run_source('''
            from typing import TypeVar
            T = TypeVar("T")
            U = TypeVar("U")
            D = TypeVar("D", default=str)
            R = TypeVar("R", default=T)
            alias = dict[T, list[U]]
            partial = alias[U, int]
            print(partial, partial.__parameters__, partial[str])
            print(dict[T, D][int], tuple[T, R][str])
            print(list[T][None], list[T][None].__args__[0] is type(None))
            print(list[T]["Missing"], list[T][[int, str]], list[T][...])
            bounded = TypeVar("bounded", bound=int)
            print(list[bounded][str])
            for key in [(), (int, str), (int, str, bytes)]:
                try:
                    list[T][key]
                except TypeError as error:
                    print(type(error).__name__, str(error))
            try:
                list[T][((int, str),)]
            except TypeError as error:
                print(type(error).__name__)
        ''')

    def test_paramspec_parameter_lists_defaults_and_markers(self):
        self.run_source('''
            from typing import ParamSpec, TypeVar
            P = ParamSpec("P")
            Q = ParamSpec("Q")
            T = TypeVar("T")
            for key in [int, (int, str), [int, str], [], ..., Q]:
                alias = list[P][key]
                print(alias, alias.__parameters__)
            print(tuple[P, T][[int, str], bytes])
            D = ParamSpec("D", default=[int, str])
            print(list[D][()])
            print(list[P.args].__parameters__, list[P.kwargs].__parameters__)
            for key in [(), None]:
                try:
                    list[P][key]
                except TypeError as error:
                    print(type(error).__name__)
        ''')

    def test_typevartuple_packs_nested_aliases_defaults_and_errors(self):
        self.run_source('''
            from typing import TypeVar, TypeVarTuple, Unpack
            T = TypeVar("T")
            U = TypeVar("U")
            Ts = TypeVarTuple("Ts")
            Us = TypeVarTuple("Us")
            alias = tuple[Unpack[Ts]]
            print(alias.__parameters__)
            for key in [(), int, (int, str), [int, str], ...]:
                result = alias[key]
                print(result, result.__parameters__)
            print(tuple[T, Unpack[Ts], U][int, str],
                  tuple[T, Unpack[Ts], U][int, str, bytes])
            print(dict[str, tuple[Unpack[Ts]]][int, bytes])
            partial = alias[Unpack[Us]]
            print(partial.__parameters__ == (Us,), partial[int, str])
            print(alias[Unpack[tuple[int, str]]])
            result = tuple[T, Unpack[Ts], U][Unpack[tuple[int, ...]]]
            print(len(result.__args__), result.__args__[0] is int,
                  result.__args__[-1] is int,
                  result.__args__[1].__typing_unpacked_tuple_args__ == (int, ...))
            Ds = TypeVarTuple("Ds", default=Unpack[tuple[int, str]])
            print(tuple[Unpack[Ds]][()])
            for template, key in [(tuple[Unpack[Ts], Unpack[Us]], int),
                                  (list[Ts], int),
                                  (tuple[T, Unpack[Ts], U], int)]:
                try:
                    template[key]
                except TypeError as error:
                    print(type(error).__name__, str(error))
        ''')

    def test_type_alias_and_union_parameter_substitution(self):
        self.run_source('''
            from typing import TypeAliasType, TypeVar
            T = TypeVar("T")
            U = TypeVar("U")
            A = TypeAliasType("A", list[T], type_params=(T,))
            print(A.__parameters__, list[A].__parameters__)
            print(list[A][int], list[A[T]][str], A[()].__args__, A[int, str].__args__)
            D = TypeVar("D", default=int)
            B = TypeAliasType("B", list[D], type_params=(D,))
            print(list[B][()])
            union = T | list[U]
            print(union.__parameters__)
            concrete = union[int, str]
            print(concrete == (int | list[str]), concrete.__parameters__)
            alias = list[union]
            print(alias.__parameters__, alias[int, str] == list[int | list[str]])
        ''')

    def test_pep695_parameters_and_lazy_defaults(self):
        self.run_source('''
            events = []
            def resolve():
                events.append("default")
                return str
            def function[T, U=resolve()]():
                pass
            T, U = function.__type_params__
            alias = dict[T, list[U]]
            print(events, alias.__parameters__ == (T, U))
            print(alias[int], events)
            print(alias[bytes], events)
            type A[T=int] = list[T]
            print(list[A][()], list[A][str])
            def variadic[*Ts, **P]():
                pass
            Ts, P = variadic.__type_params__
            print(tuple[*Ts].__parameters__ == (Ts,), list[P].__parameters__ == (P,))
            def defaults[*Ds = *tuple[int, str]]():
                pass
            Ds = defaults.__type_params__[0]
            print(Ds.__default__, tuple[*Ds][()])
        ''')
