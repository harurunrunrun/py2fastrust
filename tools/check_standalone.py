"""Compile and run standalone submissions in every integer/build mode.

Use --wheel to check the packaged compiler from an isolated directory.  The
generated executables run with PATH pointing to a nonexistent directory.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


SOURCE = '''from __future__ import annotations
import gc
import sys
from typing import TypeVar, NoDefault

n = int(input())
values = list(map(int, input().split()))
shared = [values]
other = shared
other[0].append(n)
print(sum(values), shared is other, values[-1])

def factory():
    captured = [sum(values)]
    type Held[T=int] = tuple[T, captured]
    def read[U: int = str](value: U) -> U:
        return value, U
    return Held, read

held, read = factory()
gc.collect()
print(held.__value__.__args__[0] is held.__type_params__[0],
      held.__value__.__args__[1], read(7)[0], read.__annotations__)

class Box[T, U=str]:
    field: T
    def __init__(self, value):
        self.field = value

alias = Box[int]
instance = alias(9)
print(alias is Box[int], alias.__args__, instance.field,
      instance.__orig_class__ is alias)

parameter = TypeVar("Parameter", default=int)
print(list[parameter][()] == list[int], parameter.has_default(),
      parameter.__default__ is NoDefault)

space = {}
exec(compile("type Dynamic[T=str] = list[T]", "runtime.py", "exec"), space)
print(space["Dynamic"].__value__.__args__[0].__name__)

def generate():
    try:
        yield 1
        yield 2
    finally:
        print("closed")

iterator = generate()
print(next(iterator))
iterator.close()
print(sys.stdin.readline() == "\\n")
sys.stdout.flush()
sys.stdout.buffer.write(b"standalone\\n")
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
                   "filename='standalone.py', optimize=False))\n"
                   "assert result.success, '\\n'.join(map(str, result.diagnostics))\n"
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
                            "executable_bytes": executable.stat().st_size})
            print(f"{integer}/{build}: PASS", flush=True)
    report = {"wheel": str(wheel) if wheel else None,
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
