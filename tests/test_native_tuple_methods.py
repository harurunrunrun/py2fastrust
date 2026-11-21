"""tuple.count and tuple.index compared with CPython."""
import unittest

from test_native_exception_handlers import compare


class NativeTupleMethodTests(unittest.TestCase):
    def test_fixed_and_runtime_tuples(self):
        compare(self, 't = (1, 2, 2, 3)\nprint(t.count(2), t.count(9), t.index(3), t.index(2))\npair = ("a", 1)\nprint(pair.count("a"), pair.index(1))\n'
                'r = tuple(map(int, input().split()))\nprint(r.count(2), r.index(2), r.count(7))\n'
                'try:\n    r.index(7)\nexcept ValueError as error:\n    print(error)\nprint(t.index(5))\n', '5 2 7 2\n')


if __name__ == '__main__':
    unittest.main()
