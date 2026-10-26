"""Object identity survives transport without replacing ordinary equality."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class IdentityTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_alias_transport_and_disjoint_identity_numbers(self):
        self.run_source('''
            import gc
            values = [int("1000"), float("2.5"), "".join(["long", " string"]),
                      bytes([65, 66, 67]), None, True, False, [], int, ValueError]
            def relay(value):
                return value
            def closure(value):
                def inner():
                    return value
                return inner
            def generator(value):
                yield value
                return value
            for value in values:
                alias = value
                box = [value]
                mapping = {"value": value}
                iterator = generator(value)
                print(value is alias, id(value) == id(alias), relay(value) is value,
                      closure(value)() is value, box[0] is value,
                      mapping["value"] is value, next(iter(box)) is value,
                      next(iterator) is value)
                try:
                    next(iterator)
                except StopIteration as error:
                    print(error.value is value)
            print(len(set(id(value) for value in values)) == len(values))
            for unused in range(11000):
                garbage = [unused]
            gc.collect()
            print(all(value is relay(value) for value in values))
        ''')

    def test_exact_constructors_and_conversion_callback_identity(self):
        self.run_source('''
            integer = int("1000")
            floating = float("1.25")
            string = "".join(["a long", " string"])
            binary = bytes([65, 66, 67])
            sequence = (integer, floating)
            print(int(integer) is integer, float(floating) is floating,
                  str(string) is string, bytes(binary) is binary,
                  tuple(sequence) is sequence, tuple.__new__(tuple, sequence) is sequence)
            class Conversions:
                def __int__(self):
                    return integer
                def __float__(self):
                    return floating
                def __str__(self):
                    return string
                def __bytes__(self):
                    return binary
            class Index:
                def __index__(self):
                    return integer
            value = Conversions()
            print(int(value) is integer, int(Index()) is integer,
                  float(value) is floating, str(value) is string, bytes(value) is binary)
            print((+integer) is integer, abs(integer) is integer,
                  round(integer) is integer, round(integer, 2) is integer,
                  (+floating) is floating)
            import math
            print(math.floor(integer) is integer, math.ceil(integer) is integer,
                  math.trunc(integer) is integer)
            def named():
                "doc string"
                pass
            class Named:
                pass
            named.__name__ = string
            named.__qualname__ = string
            Named.__name__ = string
            print(named.__name__ is string, named.__qualname__ is string,
                  Named.__name__ is string, named.__doc__ is named.__doc__)
        ''')

    def test_computation_freshness_and_subtype_to_base_conversion(self):
        self.run_source('''
            first = int("1000")
            second = int("1000")
            float_first = float("2.5")
            float_second = float("2.5")
            string_first = "".join(["some", " text"])
            string_second = "".join(["some", " text"])
            bytes_first = bytes([65, 66])
            bytes_second = bytes([65, 66])
            print(first == second, first is second, float_first == float_second,
                  float_first is float_second, string_first == string_second,
                  string_first is string_second, bytes_first == bytes_second,
                  bytes_first is bytes_second)
            print((first + second) is (first + second),
                  (float_first + float_second) is (float_first + float_second))
            class Integer(int):
                pass
            class String(str):
                pass
            for value, convert in [(Integer(1000), int), (String("long string"), str)]:
                left = convert(value)
                right = convert(value)
                print(type(left) is convert, left == right, left is value, left is right)
            value = Integer(1000)
            print((+value) is (+value), abs(value) is abs(value),
                  round(value) is round(value))
        ''')

    def test_nan_and_custom_container_identity_shortcuts(self):
        self.run_source('''
            import functools
            import itertools
            nan = float("nan")
            other = float("nan")
            print(nan is nan, nan == nan, nan != nan)
            print(nan in [nan], other in [nan], [nan] == [nan], [nan] == [other])
            print((nan,) == (nan,), {nan: nan} == {nan: nan})
            print([nan].count(nan), [nan].index(nan))
            values = [nan]
            values.remove(nan)
            print(values)
            mapping = {nan: "value"}
            print(mapping[nan], nan in mapping, other in mapping)
            unique = {nan, nan, other}
            print(len(unique))
            print([nan] <= [nan], [nan] <= [other], [nan] >= [other], [nan] < [other])
            @functools.cache
            def cached(value):
                print("miss")
                return []
            print(cached(nan) is cached(nan), cached(other) is cached(other))
            print([len(list(group)) for key, group in itertools.groupby([nan, nan, other])])
            print(list(iter(lambda: nan, nan)))
            class Unequal:
                def __eq__(self, other):
                    print("eq")
                    return False
            value = Unequal()
            print(value == value, value in [value], [value] == [value])
        ''')

    def test_stored_range_coordinates_and_namespace_keys(self):
        self.run_source('''
            coordinate = int("1000")
            class Index:
                def __index__(self):
                    return coordinate
            direct = range(coordinate, coordinate + 10, coordinate)
            converted = range(Index(), coordinate + 10, Index())
            print(direct.start is coordinate, direct.step is coordinate,
                  direct.stop is direct.stop, converted.start is coordinate,
                  converted.step is coordinate)
            key = "".join(["runtime", "_key"])
            globals()[key] = coordinate
            found = [name for name in globals() if name == key][0]
            again = [name for name in globals().keys() if name == key][0]
            print(found is key, again is key, globals()[found] is coordinate)
            replacement = "".join(["runtime", "_key"])
            globals()[replacement] = coordinate + 1
            found = [name for name in globals().copy() if name == key][0]
            print(found is key, found is replacement)
            del globals()[key]
            globals()[replacement] = coordinate
            found = [name for name in globals() if name == key][0]
            print(found is replacement)
        ''')

    def test_small_integer_and_per_code_literal_pools(self):
        source = '''
            for number in [-5, 0, 1, 256]:
                print(int(str(number)) is int(str(number)))
            def literal():
                return 1000, 1.25, "literal text", b"literal bytes"
            first = literal()
            second = literal()
            print([left is right for left, right in zip(first, second)])
            import math
            print(math.nan is math.nan, math.inf is math.inf,
                  math.nan == math.nan, id(math.nan) == id(math.nan))
        '''
        for integer in ("i64", "i128", "bigint"):
            with self.subTest(integer=integer):
                self.run_source(source, integer=integer)

    def test_aot_dynamic_value_transport_and_code_reexecution(self):
        self.run_source('''
            value = int("1000")
            def identity(arg=value):
                return arg
            namespace = {"identity": identity, "value": value}
            exec("alias = identity(value)\\ndef dynamic(arg=alias):\\n    return arg", namespace)
            print(namespace["alias"] is value, namespace["dynamic"]() is value,
                  eval("identity(value)", namespace) is value)
            code = compile("1000", "identity.py", "eval")
            print(eval(code) is eval(code))
            code = compile("'literal text'", "identity.py", "eval")
            print(eval(code) is eval(code))
        ''')


if __name__ == "__main__":
    unittest.main()
