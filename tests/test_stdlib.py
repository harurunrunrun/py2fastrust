import shutil
import unittest

import test_runtime


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class StandardLibraryTests(unittest.TestCase):
    run_source = test_runtime.RuntimeTests.run_source

    def test_bisect_public_api_and_custom_key(self):
        self.run_source('''
            import bisect
            a = [1, 2, 2, 4]
            print(bisect.bisect_left(a, 2), bisect.bisect_right(a, 2), bisect.bisect(a, 3))
            bisect.insort_left(a, 2)
            bisect.insort_right(a, 3)
            bisect.insort(a, 5)
            print(a)
            records = [(1, "a"), (3, "b")]
            bisect.insort(records, (2, "c"), key=lambda x: x[0])
            print(records, bisect.bisect_left(records, 3, key=lambda x: x[0]))
            try:
                bisect.bisect_left(a, 2, -1)
            except ValueError:
                print("negative lo")
        ''')

    def test_heapq_public_api_and_max_heaps(self):
        self.run_source('''
            import heapq
            heap = [4, 1, 7, 3]
            heapq.heapify(heap)
            heapq.heappush(heap, 2)
            print(heapq.heappop(heap), heapq.heappushpop(heap, 5), heapq.heapreplace(heap, 0))
            print([heapq.heappop(heap) for _ in range(len(heap))])
            heap = [4, 1, 7, 3]
            heapq.heapify_max(heap)
            heapq.heappush_max(heap, 6)
            print(heapq.heappop_max(heap), heapq.heappushpop_max(heap, 2), heapq.heapreplace_max(heap, 8))
            print([heapq.heappop_max(heap) for _ in range(len(heap))])
            print(heapq.nsmallest(3, [5, 2, 9, 1, 6]))
            print(heapq.nlargest(2, ["aa", "b", "cccc", "ddd"], key=len))
            print(list(heapq.merge([1, 4], [2, 3, 5])))
            print(list(heapq.merge([5, 2], [4, 1], reverse=True)))
        ''')

    def test_collections(self):
        self.run_source('''
            from collections import deque, defaultdict, Counter, namedtuple, OrderedDict
            queue = deque([1, 2], maxlen=3)
            queue.appendleft(0)
            queue.append(3)
            queue.rotate(1)
            print(list(queue), queue.popleft(), queue.pop(), queue.maxlen)
            mapping = defaultdict(list)
            mapping["x"].append(4)
            print(dict(mapping), mapping.default_factory is list)
            counts = Counter("banana")
            counts.update("a")
            print(counts["missing"], counts.most_common(), sorted(counts.elements()))
            Point = namedtuple("Point", "x y", defaults=[0])
            point = Point(3)
            print(point, point.x, point.y, point._asdict(), point._replace(y=4))
            ordered = OrderedDict([("a", 1), ("b", 2)])
            ordered.move_to_end("a")
            print(list(ordered), ordered.popitem(last=False))
        ''')

    def test_function_tools_cache_and_partial(self):
        self.run_source('''
            from functools import cache, lru_cache, partial, reduce
            calls = []
            @lru_cache(maxsize=2)
            def f(x):
                calls.append(x)
                return x * 2
            print(f(1), f(1), f(2), f(3), f(1), calls)
            info = f.cache_info()
            print(info.hits, info.misses, info.maxsize, info.currsize)
            f.cache_clear()
            print(f.cache_info().currsize)
            @cache
            def fib(n):
                return n if n < 2 else fib(n-1) + fib(n-2)
            print(fib(15), fib.cache_info().currsize)
            def combine(a, b, *, scale=1):
                return (a+b)*scale
            twice = partial(combine, 3, scale=2)
            print(twice(4), reduce(lambda a,b: a+b, [1,2,3], 4))
        ''')

    def test_deep_recursion_uses_heap_frames(self):
        self.run_source('''
            import sys
            sys.setrecursionlimit(10000)
            def descend(n):
                return 0 if n == 0 else descend(n-1) + 1
            print(descend(5000))
        ''')


if __name__ == "__main__":
    unittest.main()
