"""Programs that were positioned boundaries and now convert; outputs are compared with CPython."""
import unittest

from test_native_exception_handlers import compare

PROGRAMS = {
    'negative_power_map': 'print(list(map(lambda x:x**-1,[1,2])))\n',
    'walrus_boolean_capture': 'flag=True\nprint(flag is (flag:=False),flag)\nprint((flag:=True) is flag,flag)\n',
    'walrus_tagged_capture': 'for turn in (False,True):\n value=True if turn else 1\n print(value is (value:=True),value)\n',
    'float_sum_consumer': 'print(sum(map(lambda value:value/2,[1,2,3])))\n',
    'deferred_sum_binding': 'values=[3,1]\nprint(sum(values,(values:=[9])[0]))\n',
    'walrus_dictionary_comprehension': 'data={i:(last:=i) for i in range(3)}\nprint(last)\n',
}


class NativeConvertedBoundaryTests(unittest.TestCase):
    def test_programs(self):
        for name, source in PROGRAMS.items():
            with self.subTest(name=name):
                compare(self, source, '')


if __name__ == '__main__':
    unittest.main()
