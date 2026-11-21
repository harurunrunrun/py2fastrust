"""str += on framed variables appends in place without changing Python-visible values."""
import unittest

from test_native_exception_handlers import compare


class NativeTextAppendTests(unittest.TestCase):
    def test_building_and_aliases(self):
        compare(self, 'n = int(input())\nt = ""\nfor i in range(n):\n    t += chr(97 + i % 26)\nu = t\nt += "!"\nt += t\nprint(len(t), t[:5], u[-3:], u == t, len(u))\n'
                'words = [str(i) for i in range(5)]\ns = ""\nfor w in words:\n    s += w + ","\nprint(s, ord(s[0]))\n', '50000\n')

    def test_errors_keep_the_previous_text(self):
        compare(self, 't = "ab"\ndef bad(x):\n    if x > 1:\n        raise ValueError("no")\n    return chr(65 + x)\nfor i in range(3):\n    try:\n        t += bad(i)\n'
                '    except ValueError as error:\n        print("kept", t, error)\nprint(t)\nt += chr(int(input()))\nprint("unreachable")\n', '-1\n')

    def test_function_locals_globals_and_closures(self):
        compare(self, 'g = ""\ndef add(c):\n    global g\n    g += c\ndef build(n):\n    s = ""\n    for i in range(n):\n        s += hex(i)[-1]\n    return s\n'
                'def counter():\n    text = ""\n    def push(c):\n        nonlocal text\n        text += c\n        return text\n    return push\npush = counter()\n'
                'for c in "xyz":\n    add(c)\n    push(c)\nprint(g, build(20), push("!"), bin(5))\n', '')


if __name__ == '__main__':
    unittest.main()
