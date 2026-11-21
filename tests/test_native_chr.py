"""chr() code points, error classes and character arithmetic."""
import unittest

from test_native_exception_handlers import compare


CASES = {
    'code_points_and_errors': ('print(chr(98),chr(ord("a")+2),[chr(97+i) for i in range(3)])\ns="abz"\nprint("".join(chr(ord(c)+1) for c in s))\nprint(chr(True),repr(chr(0)))\nfor v in [1114111+1,-1]:\n    try:\n        chr(v)\n    except ValueError:\n        print("range")\ntry:\n    chr(2**40)\nexcept ValueError:\n    print("big")\n', ''),
}


class NativeChrTests(unittest.TestCase):
    def test_code_points_and_errors(self):
        compare(self, *CASES['code_points_and_errors'])
