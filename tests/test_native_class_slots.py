"""Literal __slots__ on base-less classes; other slot behaviors stay positioned diagnostics."""
import unittest

from py2fastrust import TranspileOptions, transpile
from test_native_exception_handlers import compare


class NativeClassSlotsTests(unittest.TestCase):
    def test_linked_nodes_and_points(self):
        compare(self, 'class Node:\n    __slots__ = ("v", "nxt")\n    def __init__(self, v):\n        self.v = v\n        self.nxt = None\n'
                'class P:\n    __slots__ = ["x", "y"]\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y\n    def norm(self):\n        return self.x * self.x + self.y * self.y\n'
                'head = None\nfor i in range(int(input())):\n    n = Node(i)\n    n.nxt = head\n    head = n\ns = []\nwhile head is not None:\n    s.append(head.v)\n    head = head.nxt\n'
                'print(s, P(3, 4).norm(), sorted([P(2, 0), P(1, 1)], key=P.norm)[0].x)\n', '6\n')

    def test_unassigned_slot_reads_raise_attribute_error(self):
        compare(self, 'class Q:\n    __slots__ = "a"\nq = Q()\ntry:\n    print(q.a)\nexcept AttributeError as error:\n    print("AttributeError", error)\nq.a = 5\nprint(q.a)\nprint(Q().a)\n', '')

    def test_other_slot_protocols_are_positioned(self):
        cases = [('class A:\n    __slots__ = ("x",)\n    def __init__(self):\n        self.y = 1\nA()\n', 4),
                 ('class A:\n    __slots__ = ("x",)\n    x = 3\n', 2),
                 ('names = ("x",)\nclass A:\n    __slots__ = names\n', 3),
                 ('class A:\n    __slots__ = ("__x",)\n', 2),
                 ('class A:\n    __slots__ = ()\nprint(A.__slots__)\n', 3)]
        for source, line in cases:
            with self.subTest(source=source):
                result = transpile(source, TranspileOptions(filename='sl.py'))
                self.assertFalse(result.success)
                self.assertIn(f'sl.py:{line}:', '\n'.join(map(str, result.diagnostics)))


if __name__ == '__main__':
    unittest.main()
