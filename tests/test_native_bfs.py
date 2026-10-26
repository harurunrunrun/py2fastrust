"""Owned integer rows and provenance-checked unbounded deque native lowering."""

from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from py2fastrust import TranspileOptions, transpile
from py2fastrust.native import try_generate_native

BFS = (Path(__file__).resolve().parents[1] / "examples" / "bfs.py").read_text()


@unittest.skipUnless(shutil.which("rustc"), "rustc is required")
class NativeBfsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="py2fastrust-native-bfs-")
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile(self, source, integer="i64", optimized=False, backend="native", module_paths=(), filename="bfs.py"):
        result = transpile(source, TranspileOptions(integer=integer, filename=filename, module_paths=module_paths))
        self.assertTrue(result.success, str(result.diagnostics))
        self.assertEqual(result.backend, backend, source)
        if backend == "native":
            self.assertNotIn("enum Value", result.rust_source)
            self.assertNotIn("struct Runtime", result.rust_source)
        type(self).counter += 1
        path = Path(self.tmp.name) / f"bfs{self.counter}.rs"
        path.write_text(result.rust_source)
        compiled = subprocess.run(["rustc", "--edition=2021", *(["-O"] if optimized else []), str(path), "-o", str(path.with_suffix(""))],
                                  capture_output=True, text=True, timeout=90)
        self.assertEqual(compiled.returncode, 0, compiled.stderr + "\n" + source)
        return path.with_suffix(""), result.rust_source

    def differential(self, source, inputs=("",), modes=("i64", "i128"), optimizations=(False, True), expected=None):
        references = [subprocess.run([sys.executable, "-I", "-c", source], input=data, capture_output=True, text=True, timeout=5)
                      for data in inputs] if expected is None else None
        for integer in modes:
            for optimized in optimizations:
                with self.subTest(integer=integer, optimized=optimized):
                    binary, _ = self.compile(source, integer, optimized)
                    for index, data in enumerate(inputs):
                        actual = subprocess.run([str(binary)], input=data, capture_output=True, text=True, timeout=5)
                        if expected is not None:
                            self.assertEqual(actual.returncode, 0, actual.stderr)
                            self.assertEqual(actual.stdout, expected[integer])
                            continue
                        reference = references[index]
                        self.assertEqual(actual.stdout, reference.stdout, source + "\n" + data)
                        self.assertEqual(actual.returncode, reference.returncode, actual.stderr)
                        if reference.returncode:
                            self.assertEqual(actual.stderr.strip().splitlines()[-1].split(":")[0],
                                             reference.stderr.strip().splitlines()[-1].split(":")[0])

    def test_example_bfs_and_seeded_graphs_all_widths_and_build_modes(self):
        inputs = ["1 0\n", "0 0\n", "-2 0\n", "3 1\n-1 0\n", "2 1\n2 0\n", "2 1\n0 1 extra\n"]
        rng = random.Random(20261027)
        for n in (2, 9, 31):
            edges = [(rng.randrange(n), rng.randrange(n)) for _ in range(3*n)]
            inputs.append(f"{n} {len(edges)}\n" + "".join(f"{a} {b}\n" for a, b in edges))
        self.differential(BFS, inputs)

    def test_solve_function_and_constructor_alias(self):
        setup, body = BFS.split("\n", 1)
        source = setup.replace("deque", "deque as Queue") + "\ndef solve():\n" + "".join(" " + line + "\n" for line in body.replace("deque([0])", "Queue(iterable=(0,),maxlen=None)").splitlines())
        source += '\nif __name__ == "__main__":\n solve()\n'
        self.differential(source, ("4 3\n0 1\n1 2\n0 3\n", "1 0\n", "0 0\n"))

    def test_independent_rows_input_rows_replacement_and_rebinding(self):
        self.differential('''
n=int(input())
m=int(input())
grid=[[0]*m for _ in range(n)]
for i in range(n):
 grid[i].append(i+7)
 for j in range(m):
  grid[i][j]=i*10+j
  grid[i][j]+=2
for i in range(n):
 print(len(grid[i]),sum(grid[i]))
if n:
 grid[-1]=[91,92]
 print(*grid[-1])
grid=[[3],[5,7]]
grid.append([9])
print(len(grid),sum(grid[0]),sum(grid[-1]))
grid.clear()
print(len(grid))
grid=11
print(grid)
''', ("0\n3\n", "3\n2\n", "2\n-1\n"))
        self.differential('''
n=int(input())
rows=[list(map(int,input().split())) for _ in range(n)]
for i in range(n):
 print(len(rows[i]),sum(rows[i]))
''', ("0\n", "3\n1 2\n\n3 4 5\n"), modes=("i64",), optimizations=(True,))

    def test_queue_constructors_operations_and_argument_evaluation(self):
        self.differential('''
from collections import deque
q=deque()
q.append(3)
q.appendleft(7)
q.append(q.popleft()+1)
print(*q,q.pop(),len(q))
q=deque(iterable=(0,1,2,3),maxlen=None)
print(q[q.popleft()],sum(q,q.pop()),len(q))
r=deque(q)
q.clear()
print(len(q),sum(r))
q=deque([8,0,9])
print(deque([q.popleft()])[q.popleft()],q.popleft())
q=deque(range(-3,4,2))
while q:
 print(q.popleft(),end=",")
print()
q=deque((0,1,2))
rows=[[] for _ in range(3)]
x=19
for x in q:
 rows[x].append(x+7)
print(x,sum(rows[0]),sum(rows[-1]),sum(q))
q=[13]
print(sum(q))
''')

    def test_row_receiver_checks_and_assignment_order(self):
        self.differential('''
from collections import deque
rows=[[1,2]]
q=deque([0,1,7])
rows[q.popleft()].append(q.popleft())
rows[0][q.popleft()]=q.popleft()
''')
        self.differential('''
rows=[[1]]
def marker(value):
 print(value)
 return value
rows[marker(4)].append(marker(5))
''', modes=("i64",), optimizations=(True,))
        self.differential('''
rows=[[1]]
def marker(value):
 print(value)
 return value
rows[marker(4)][marker(3)]=marker(5)
''', modes=("i64",), optimizations=(False,))

    def test_zero_loops_row_iteration_and_queue_empty_errors(self):
        self.differential('''
from collections import deque
n=int(input())
graph=[[] for _ in range(n)]
x=19
for x in range(n):
 graph[x].append(x)
for i in range(n):
 for x in graph[i]:
  print(x)
print(x)
q=deque([7])
print(q.popleft())
print(q.popleft())
''', ("0\n", "3\n"))

    def test_fixed_width_keys_and_elements_normalize_before_bfs_branch(self):
        source = '''
from collections import deque
huge=2**127
rows=[[0]*2 for _ in range(2)]
rows[0][1]=huge+huge+9
q=deque([huge+huge+1])
v=q.popleft()
if v==1:
 rows[1].append(rows[0][v]+huge)
print(rows[0][1],sum(rows[1]))
'''
        expected = {}
        for bits in (64, 128):
            wrap = lambda x: (x + (1 << (bits-1))) % (1 << bits) - (1 << (bits-1))
            value = wrap(wrap(2**127)+wrap(2**127)+9)
            expected[f"i{bits}"] = f"{value} {wrap(value+wrap(2**127))}\n"
        self.differential(source, expected=expected)

    def test_queue_and_matrix_phi_moves_and_integer_argument_function(self):
        self.differential('''
from collections import deque
def measure(n):
 if n:
  rows=[[1]]
  q=deque([3])
 else:
  rows=[[2,3]]
  q=deque()
 for i in range(n):
  rows[0].append(i)
  q.append(i+7)
 total=sum(rows[0])
 while q:
  total+=q.popleft()
 q=False
 q=deque((11,13))
 rows=17
 rows=[[5],[7]]
 return total+sum(q)+sum(rows[-1])
flag=int(input())
print(measure(flag),measure(0),measure(2))
''', ("0\n", "3\n"))

    def test_row_repetition_checks_only_execute_for_actual_rows(self):
        self.differential('''
n=int(input())
m=int(input())
print(17)
rows=[[0]*m for _ in range(n)]
print(len(rows))
''', ("0\n18446744073709551616\n", "1\n18446744073709551616\n"),
                          modes=("i128",))

    def test_input_unpack_stack_array_and_large_heap_fallback_preserve_lazy_errors(self):
        names = [f"value{index}" for index in range(40)]
        source = ",".join(names) + "=map(int,input().split())\nprint(value0,value39)\n"
        base = " ".join(str(value) for value in range(40))
        self.differential(source, (base+"\n", base+" 41 invalid\n", "1 2\n"),
                          modes=("i64",), optimizations=(True,))

    def test_unproved_alias_iterator_and_bounded_queues_fall_back(self):
        programs = [
            "rows=[[0]*2]*3\nrows[0][0]=8\nprint(rows)\n",
            "row=[1]\nrows=[row]\nrow.append(2)\nprint(rows)\n",
            "rows=[[1],[2]]\nrow=rows[0]\nrow.append(3)\nprint(rows)\n",
            "rows=[[1],[2]]\nfor x in rows[0]:\n rows[1].append(x)\nprint(rows)\n",
            "from collections import deque\nq=deque([1])\nr=q\nr.append(2)\nprint(q)\n",
            "from collections import deque\nq=deque([1])\nfor x in q:\n q.append(2)\n",
            "from collections import deque\nq=deque([1,2],maxlen=0)\nprint(q)\n",
            "from collections import deque\nq=deque(maxlen=-1)\n",
            "from collections import deque\nq=deque([1],1)\nprint(q)\n",
            "from collections import deque\nq=deque(unknown=1)\n",
            "from collections import deque as __name__\ndef solve():\n print(1)\nif __name__ == '__main__':\n solve()\n",
            "from collections import deque\ndef f():\n q=deque()\n print(len(q))\ndeque=3\nf()\n",
            "def f():\n q=deque()\n print(len(q))\nf()\nfrom collections import deque\n",
        ]
        for source in programs:
            with self.subTest(source=source):
                result = transpile(source)
                self.assertTrue(result.success, result.diagnostics)
                self.assertEqual(result.backend, "vm")
        # Direct native entry without actual module-resolution evidence cannot
        # silently assume that this import denotes our standard implementation.
        self.assertIsNone(try_generate_native(BFS, "bfs.py", "i64"))
        self.assertIsNone(try_generate_native(BFS, "bfs.py", "bigint", trusted_imports={"collections"}))

    def test_local_collections_and_module_path_shadowing_use_vm(self):
        root = Path(self.tmp.name) / "shadow"
        root.mkdir()
        (root / "collections.py").write_text('def deque(value):\n print("custom module", value)\n return [99]\n')
        source = "from collections import deque\nq=deque([7])\nprint(q)\n"
        for paths, filename in (((), str(root / "main.py")), ((root,), "somewhere/main.py")):
            binary, _ = self.compile(source, backend="vm", module_paths=paths, filename=filename)
            actual = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(actual.stdout, "custom module [7]\n[99]\n")

    def test_generated_bfs_has_native_rows_queue_and_no_runtime_dispatch(self):
        result = transpile(BFS)
        self.assertEqual(result.backend, "native")
        rust = result.rust_source
        self.assertRegex(rust, r"let mut native_var_\d+: Vec<Vec<NativeInt>>;")
        self.assertRegex(rust, r"let mut native_var_\d+: std::collections::VecDeque<NativeInt>;")
        main = rust[rust.rfind("fn main()") :]
        self.assertNotRegex(main, r"\b(?:Value|Runtime)\b|obj_value|Box::|Rc::")
        self.assertIn(".iter().copied()", main)
        self.assertNotIn("clone()", main)


if __name__ == "__main__":
    unittest.main()
