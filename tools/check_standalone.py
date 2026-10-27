"""Compile and run standalone submissions in every integer/build mode.

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


SOURCE = '''# pytors: --license Unlicense
from __future__ import annotations
import gc
import sys
from typing import TypeVar, NoDefault
from string.templatelib import Template, Interpolation, convert

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
template = t"sum={sum(values)!r:>3}"
print(template.strings, template.values,
      [(i.expression, i.conversion, i.format_spec) for i in template.interpolations])
print(isinstance(template, Template),
      isinstance(template.interpolations[0], Interpolation),
      convert(template.values[0], "s"))
def template_factory():
    parts = [8, 9]
    return t"{parts}"
held_template = template_factory()
gc.collect()
print(held_template.values)
exec("template = t'{sum([1, 2, 3])}'", space)
print(space["template"].values)

def active_exception():
    return sys.exception()

group = ExceptionGroup("standalone", [ValueError("value"), TypeError("type")])
group.add_note("retained")
gc.collect()
try:
    try:
        raise group
    except* ValueError as matched:
        print(matched.message, matched.__notes__, active_exception() is matched,
              sys.exc_info()[0] is ExceptionGroup)
except ExceptionGroup as remaining:
    print([type(error).__name__ for error in remaining.exceptions])
exec("try: raise ValueError('dynamic')\\nexcept* ValueError as caught: print(caught.message, str(caught.exceptions[0]))", space)
print(sys.exception())
number = 3+4j
print(number.real, number.imag, abs(number), number*number, complex("1-2j"))
match number:
    case 3+4j:
        print("complex pattern")
optimized = {}
exec(compile('def function():\\n "removed"\\n assert False\\n return __debug__',
             "optimized.py", "exec", optimize=2), optimized)
print(optimized["function"](), optimized["function"].__doc__)
frozen = frozenset([1, 2, 2])
print(sorted(frozen | {3}), frozen == frozenset([2, 1]),
      hash(frozen) == hash(frozenset([2, 1])))
class Parent:
    def __init_subclass__(cls, *, flag, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.flag = flag
class Expanded(*[Parent], **{"flag": 17}):
    pass
print(Expanded.flag)
exec("class DynamicExpanded(*[Parent], **{'flag': 19}): pass", globals())
print(DynamicExpanded.flag)
print(sys.stdin.readline() == "\\n")
sys.stdout.flush()
sys.stdout.buffer.write(b"standalone\\n")
sys.stdout.flush()
'''
SOURCE += r'''
from functools import cache

@cache
def cached_count(n):
    if not n:
        return 0
    return cached_count(n - 1) + 1

sys.setrecursionlimit(4000)
print(cached_count(1500), cached_count.cache_info().currsize)

class Key(str):
    pass
key = Key("value")
def receive(**kwargs):
    return next(iter(kwargs))
def named_a():
    return receive(value=1)
def named_b():
    return receive(value=2)
print(receive(**{key: 1}) is key, named_a() is named_b())
exec("def dynamic_named(): return receive(value=3)", globals())
print(named_a() is dynamic_named())
gc.collect()
print(receive(**{key: 4}) is key)

class NativeList(list):
    pass
owned = NativeList([{"retained": 31}])
gc.collect()
print(owned[0]["retained"])

print(eval(r"'\N{LATIN SMALL LETTER A}\N{NUL}\N{HANGUL SYLLABLE GAG}'") == "a\0\uac01")
exec(r"named_template = t'\N{EM DASH}{5}'", space)
print(space["named_template"].strings, space["named_template"].values)
print(eval(b"# coding: latin-1\n'caf\xe9'"))
print(eval("left + right", globals={"left": 7}, locals={"right": 8}))

class Filename:
    def __fspath__(self):
        return b"standalone_dynamic.py"
exec(compile("path_result = 29", Filename(), "exec"), space)
print(space["path_result"])
'''
SOURCE += r'''
import builtins

module_space = globals()
module_space["inserted_from_mapping"] = 37
print(module_space is globals(), inserted_from_mapping)
del module_space["inserted_from_mapping"]
try:
    inserted_from_mapping
except NameError:
    print("deleted global")

def comprehension_owner():
    marker = 73
    items = [marker for marker in range(3)]
    [last := item for item in items]
    callbacks = [lambda: step for step in range(3)]
    return marker, last, [callback() for callback in callbacks], "step" in locals()

print(comprehension_owner())

old_builtins = {"marker": "old"}
new_builtins = {"marker": "new"}
captured_space = {"__builtins__": old_builtins, "new": new_builtins}
exec("def first(): return marker\n__builtins__ = new\ndef second(): return marker",
     captured_space)
first = captured_space["first"]
second = captured_space["second"]
del captured_space["__builtins__"]
gc.collect()
print(first(), second(), first.__builtins__ is old_builtins,
      second.__builtins__ is new_builtins)
old_builtins["marker"] = "mutated"
print(first())

hook_events = []
hook_builtins = dict(vars(builtins))
hook_space = {"__builtins__": hook_builtins, "__name__": "standalone_hooks"}
original_builder = builtins.__build_class__

def build_hook(body, name, *bases, **kwargs):
    hook_events.append((name, body.__code__.co_qualname))
    return original_builder(body, name, *bases, **kwargs)

def import_hook(name, global_space=None, local_space=None, fromlist=(), level=0):
    hook_events.append((name, global_space is hook_space,
                        local_space is hook_space, fromlist, level))
    return sys

hook_builtins["__build_class__"] = build_hook
hook_builtins["__import__"] = import_hook
exec("class Hooked:\n value = 41\nimport sys as imported", hook_space)
print(hook_space["Hooked"].value, hook_space["imported"] is sys, hook_events)

def stable_code():
    def child():
        return 43
    return child

saved_code = stable_code().__code__
gc.collect()
print(stable_code().__code__ is saved_code, saved_code.co_qualname)

def named_generator():
    yield 47

named_iterator = named_generator()
generator_code = named_iterator.gi_code
named_generator.__name__ = "ChangedFunction"
named_iterator.__name__ = "PausedGenerator"
gc.collect()
print(named_iterator.__name__, named_iterator.gi_code is generator_code,
      generator_code.co_qualname, next(named_iterator))

operand_events = []

class NativeInteger(int):
    pass

class ReflectedInteger(int):
    def __radd__(self, other):
        operand_events.append("reflected")
        return 99
    def __eq__(self, other):
        operand_events.append("equality")
        return False

print(NativeInteger(3) + ReflectedInteger(4),
      NativeInteger(3) == ReflectedInteger(3), operand_events)

class InPlaceList(list):
    def __iadd__(self, other):
        return NotImplemented
    def __add__(self, other):
        return list.__add__(self, other)

inplace = InPlaceList([1])
original = inplace
inplace += [2]
print(inplace, original, inplace is original, type(inplace).__name__)
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
