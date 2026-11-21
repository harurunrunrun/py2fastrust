"""x in deque compares items in order like deque_contains."""
import unittest

from test_native_exception_handlers import compare


class NativeDequeMembershipTests(unittest.TestCase):
    def test_membership(self):
        compare(self, 'from collections import deque\nd = deque(map(int, input().split()))\nprint(3 in d, 9 not in d, 1 in deque())\n'
                'd.rotate(1)\nd.appendleft(9)\nprint(9 in d, d.pop() in d)\nq = deque([(0, 0)], maxlen=2)\nq.append((1, 2))\nq.append((3, 4))\nprint((0, 0) in q, (1, 2) in q, [x in q for x in [(3, 4), (5, 6)]])\n'
                'words = deque(["a", "b"])\nprint("b" in words, "c" in words)\n', '1 2 3 4\n')


if __name__ == '__main__':
    unittest.main()
