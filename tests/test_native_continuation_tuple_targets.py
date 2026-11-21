"""Recursive frames iterating a tuple literal with a destructuring target."""
import unittest

from test_native_exception_handlers import compare


class NativeContinuationTupleTargetTests(unittest.TestCase):
    def test_grid_dfs(self):
        compare(self, 'import sys\nsys.setrecursionlimit(10**6)\nH, W = map(int, input().split())\ng = [input() for _ in range(H)]\n'
                'seen = [[False] * W for _ in range(H)]\ndef dfs(y, x):\n    seen[y][x] = True\n'
                '    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):\n        ny, nx = y + dy, x + dx\n'
                '        if 0 <= ny < H and 0 <= nx < W and g[ny][nx] == "." and not seen[ny][nx]:\n            dfs(ny, nx)\n'
                'dfs(0, 0)\nprint(sum(map(sum, seen)))\nfor row in seen:\n    print("".join("o" if v else "x" for v in row))\n',
                '3 4\n..#.\n.#..\n....\n')

    def test_mixed_field_kinds(self):
        compare(self, 'def walk(depth):\n    for name, step in (("a", 1), ("b", 2)):\n        print(depth, name, step)\n        if depth < 1:\n            walk(depth + step)\nwalk(0)\n', '')


if __name__ == '__main__':
    unittest.main()
