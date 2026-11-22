"""Compile and run a standalone submission in every integer/build mode.

The fixture exercises input parsing, containers, collections, heapq, cached
recursion, classes, exceptions, generators and formatting; its output must
equal CPython's in every mode, so it stays within 64-bit integer results.

Use --wheel to check the packaged compiler from an isolated directory.  The
generated executables run with PATH pointing to a nonexistent directory.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


SOURCE = r'''# pytors: --license Unlicense
import sys
import heapq
from collections import deque, Counter, defaultdict
from functools import cache

n = int(input())
values = list(map(int, input().split()))
shared = [values]
other = shared
other[0].append(n)
print(sum(values), shared is other, values[-1])

graph = defaultdict(list)
for a, b in zip(values, values[1:]):
    graph[a].append(b)
    graph[b].append(a)
seen = {values[0]}
queue = deque([values[0]])
order = []
while queue:
    node = queue.popleft()
    order.append(node)
    for nxt in sorted(graph[node]):
        if nxt not in seen:
            seen.add(nxt)
            queue.append(nxt)
print(order, len(seen))

heap = []
for index, value in enumerate(values):
    heapq.heappush(heap, (-value, index))
print([heapq.heappop(heap) for _ in range(3)])
print(Counter("mississippi").most_common(2))

@cache
def cached_count(k):
    if not k:
        return 0
    return cached_count(k - 1) + 1

sys.setrecursionlimit(10000)
print(cached_count(1500))

class Shape:
    def __init__(self, sides, size):
        self.sides = sides
        self.size = size
    def area(self):
        return self.size * self.size if self.sides == 4 else 0
    def describe(self):
        return f"{self.sides} sides, area {self.area():.1f}"
for shape in [Shape(0, 1), Shape(4, 3)]:
    print(shape.describe())

def checked(text):
    if not text.strip():
        raise ValueError("blank line")
    return int(text)
try:
    checked(sys.stdin.readline())
except ValueError as error:
    print("rejected:", error)

def squares(limit):
    for i in range(limit):
        yield i * i
print(sum(squares(10**3)), list(squares(5)), 2**40, -7 // 2, -7 % 3)
words = sorted(["pear", "fig", "apple", "kiwi"], key=lambda w: (len(w), w))
print(" ".join(words), {w: len(w) for w in words}, f"{3.14159:>8.3f}|")
sys.stdout.write("standalone\n")
sys.stdout.flush()
'''
STDIN = "4\n1 2 3 4\n\n"


def run(command, *, cwd, **kwargs):
    result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=240, **kwargs)
    if result.returncode:
        error = result.stderr
        if isinstance(error, bytes):
            error = error.decode("utf-8", errors="replace")
        raise RuntimeError(f"{command[0]} failed ({result.returncode}):\n{error}")
    return result


def check(root, wheel):
    repository = Path(__file__).resolve().parents[1]
    package_root = repository
    if wheel:
        package_root = root / "installed"
        package_root.mkdir()
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                (package_root / name).resolve().relative_to(package_root.resolve())
            archive.extractall(package_root)
    rustc = shutil.which("rustc")
    if not rustc:
        raise RuntimeError("rustc is required")
    expected = run([sys.executable, "-I", "-c", SOURCE], cwd=root,
                   input=STDIN.encode()).stdout
    results = []
    for integer in ("i64", "i128", "bigint"):
        target = root / f"main_{integer}.rs"
        builder = ("import sys\nfrom pathlib import Path\n"
                   f"sys.path.insert(0, {str(package_root)!r})\n"
                   "from py2fastrust import TranspileOptions, transpile\n"
                   f"result = transpile({SOURCE!r}, TranspileOptions(integer={integer!r}, "
                   "filename='standalone.py', optimize=False, license='MIT'))\n"
                   "assert result.success, '\\n'.join(map(str, result.diagnostics))\n"
                   "assert result.rust_source.startswith('// LICENSE: Unlicense\\n')\n"
                   "assert 'If the original Python source specifies a license, that license takes precedence.' in result.rust_source\n"
                   "assert '// import sys\\n' in result.rust_source\n"
                   f"Path({str(target)!r}).write_text(result.rust_source, encoding='utf-8')\n")
        started = time.perf_counter()
        run([sys.executable, "-I", "-c", builder], cwd=root)
        conversion_seconds = time.perf_counter() - started
        for optimized in (False, True):
            build = "release" if optimized else "debug"
            executable = root / f"main_{integer}_{build}"
            command = [rustc, "--edition=2021", str(target), "-o", str(executable)]
            if optimized:
                command.insert(1, "-O")
            started = time.perf_counter()
            run(command, cwd=root)
            compilation_seconds = time.perf_counter() - started
            environment = dict(os.environ)
            environment["PATH"] = str(root / "no-executables")
            actual = run([str(executable)], cwd=root, env=environment,
                         input=STDIN.encode()).stdout
            if actual != expected:
                raise AssertionError(f"{integer}/{build}: {actual!r} != {expected!r}")
            results.append({"integer": integer, "build": build,
                            "conversion_seconds": conversion_seconds,
                            "compilation_seconds": compilation_seconds,
                            "source_bytes": target.stat().st_size,
                            "executable_bytes": executable.stat().st_size,
                            "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                            "stdout_sha256": hashlib.sha256(actual).hexdigest()})
            print(f"{integer}/{build}: PASS", flush=True)
    report = {"wheel": str(wheel) if wheel else None,
              "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest() if wheel else None,
              "python_source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
              "rustc": run([rustc, "--version"], cwd=root, text=True).stdout.strip(),
              "checks": results}
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, help="check an extracted wheel instead of this checkout")
    parser.add_argument("--output", type=Path, help="retain generated sources, binaries and report here")
    arguments = parser.parse_args()
    wheel = arguments.wheel.resolve() if arguments.wheel else None
    if arguments.output:
        root = arguments.output.resolve()
        root.mkdir(parents=True, exist_ok=False)
        check(root, wheel)
        print(f"report: {root / 'report.json'}")
    else:
        with tempfile.TemporaryDirectory(prefix="py2fastrust-standalone-") as directory:
            check(Path(directory), wheel)


if __name__ == "__main__":
    main()
