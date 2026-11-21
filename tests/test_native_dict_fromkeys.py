"""dict.fromkeys: keys in iteration order sharing one value object."""
import unittest

from test_native_exception_handlers import compare


class NativeDictFromkeysTests(unittest.TestCase):
    def test_fromkeys(self):
        compare(self, 'd = dict.fromkeys("abca", 0)\nd["a"] += 1\nprint(d, len(d))\nprint(dict.fromkeys(range(3)), dict.fromkeys([]))\n'
                'shared = dict.fromkeys([1, 2], [])\nshared[1].append(5)\nprint(shared, shared[1] is shared[2])\n'
                'words = input().split()\nseen = dict.fromkeys(words)\nprint(list(seen))\nfor k, v in seen.items():\n    print(k, v)\n', 'b a b c a\n')


if __name__ == '__main__':
    unittest.main()
