"""Imports must balance operand stacks and preserve live iterator roots."""

import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class ImportRootsTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_from_import_inside_nested_loops(self):
        self.run_source('''
            for outer in range(3):
                from collections import deque, Counter as Count
                for inner in range(2):
                    from math import sqrt, ceil
                    print(outer, inner, list(deque([outer, inner])),
                          Count("ababa")["a"], ceil(sqrt(outer + inner)))
                else:
                    print("inner complete", outer)
            else:
                print("outer complete", outer, inner)
        ''')

    def test_batched_bfs_with_import_inside_outer_loop(self):
        self.run_source('''
            batch = int(input())
            for benchmark_batch in range(batch):
                from collections import deque
                n, m = map(int, input().split())
                graph = [[] for _ in range(n)]
                for _ in range(m):
                    a, b = map(int, input().split())
                    graph[a].append(b)
                    graph[b].append(a)
                distance = [-1] * n
                distance[0] = 0
                queue = deque([0])
                while queue:
                    vertex = queue.popleft()
                    for neighbor in graph[vertex]:
                        if distance[neighbor] == -1:
                            distance[neighbor] = distance[vertex] + 1
                            queue.append(neighbor)
                print(*distance)
        ''', stdin="2\n5 4\n0 1\n1 2\n0 3\n3 2\n3 1\n0 1\n")

if __name__ == "__main__":
    unittest.main()
