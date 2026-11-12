"""Canonical integer str maps join without per-element text allocations."""
import unittest
from unittest.mock import patch
from py2fastrust import transpile,TranspileOptions
import test_native_source_state as state_tests


SOURCES={
    'integer_join_cursor':'''convert = str
values = list(map(int, input().split()))
mapped = map(convert, values, strict=True)
print(next(mapped, "empty"))
values.append(-17)
print(" :: ".join(mapped))
print(list(mapped))
print("".join(map(str, [])))
''',
    'integer_join_order':'''events = []
def separator():
    events.append(1)
    return ":"
def values():
    events.append(2)
    return [3, -5, 0]
print(separator().join(map(str, values())))
print(events)
''',
    'integer_join_custom':'''values = [2, 3]
def convert(value):
    print("convert", value)
    if value == 2:
        values.append(5)
    return str(value + 1)
print(" ".join(map(convert, values)))
print(values)
''',
    'integer_join_bytes':'''mapped = map(str, [2, 3])
print(b" ".join(mapped))
''',
    'integer_join_keyword':'''mapped = map(str, [2, 3])
print(" ".join(mapped, ignored=True))
''',
    'integer_join_float':'''print(" ".join(map(str, [1.25, -0.0, 2.0])))
''',
    'integer_join_parse_error':'''mapped = map(int, ["3", "wrong", "7"])
print("before")
print(" ".join(map(str, mapped)))
''',
}


class NativeIntegerJoinTests(unittest.TestCase):
    def test_only_the_canonical_integer_formatter_is_fused(self):
        direct=transpile(SOURCES['integer_join_order'],TranspileOptions(license='none'))
        self.assertTrue(direct.success,direct.diagnostics)
        self.assertIn('struct NativeIntegerJoin',direct.rust_source)
        for name in ('integer_join_custom','integer_join_bytes','integer_join_keyword','integer_join_float'):
            result=transpile(SOURCES[name],TranspileOptions(license='none'))
            self.assertTrue(result.success,result.diagnostics)
            self.assertNotIn('struct NativeIntegerJoin',result.rust_source)

    def test_original_cursor_effects_errors_and_all_integer_modes(self):
        with patch.dict(state_tests.SOURCES,SOURCES):
            for name in SOURCES:
                with self.subTest(name=name):
                    inputs=('\n','0 -2 9000000000000000000\n')if name=='integer_join_cursor'else('',)
                    state_tests.NativeSourceStateExecutionTests.exercise(self,name,inputs)


if __name__=='__main__':unittest.main()
