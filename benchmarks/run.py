"""Correctness-gated CPython/generated Rust/handwritten Rust measurements.

python benchmarks/run.py --all --output /tmp/bench.json
--size 17 --batch 1 --repeats 1 --warmup 0 makes a small smoke run.
Batched work amortizes startup. Calibration has time/input/batch limits; JSON
records when a limit leaves startup significant. Measurements are workload and
machine specific, and source scans are facts rather than performance proofs.
"""
import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from py2fastrust import TranspileOptions, transpile

CASES = {
    "arithmetic": "n=int(input())\ns=0\nfor i in range(n):\n s += (i*17+3)%1000000007\nprint(s)\n",
    "input": "n=int(input())\ns=0\nfor i in range(n):\n s += int(input())\nprint(s)\n",
    "list": "n=int(input())\na=[i%100 for i in range(n)]\ns=0\nfor x in a:\n s += x*x\nprint(s)\n",
    "sort": "n=int(input())\na=[(i*19237)%100003 for i in range(n)]\na.sort()\nprint(a[0],a[-1],sum(a))\n",
    "dict": "n=int(input())\nd={}\nfor i in range(n):\n k=i%101\n d[k]=d.get(k,0)+1\nprint(sum(d.values()))\n",
    "set": "n=int(input())\ns=set()\nfor i in range(n):\n s.add((i*19237)%101)\nfound=0\nfor i in range(n):\n if (i*31)%101 in s:\n  found+=1\nprint(len(s),found)\n",
    "bfs": (REPO / "examples" / "bfs.py").read_text(encoding="utf-8"),
    "dp": "n=int(input())\na=[0]*(n+2)\na[0]=1\nfor i in range(n):\n a[i+1]=(a[i+1]+a[i])%1000000007\n a[i+2]=(a[i+2]+a[i])%1000000007\nprint(a[n])\n",
    "bigint": "n=int(input())\na=1\nfor i in range(n):\n a=a*2+1\nprint(a.bit_length())\n",
}
DEFAULT_SIZES = {"arithmetic": 20_000_000, "input": 500_000, "list": 2_000_000,
                 "sort": 500_000, "dict": 500_000, "set": 2_000,
                 "bfs": 2_000, "dp": 2_000_000, "bigint": 5_000}
ALGORITHMS = {
    "arithmetic": "counted-loop sum of (i*17+3)%1000000007",
    "input": "parse/sum n decimal integers: buffered Rust tokens versus Python lines",
    "list": "materialize n i%100 values, then sum squares",
    "sort": "ascending integer sort, first/last/sum; both Rust paths use sort_unstable",
    "dict": "101 possible integer keys: explicit get then insert; sum counts",
    "set": "101 possible integer keys: insert then n membership queries",
    "bfs": "chain adjacency list, queue BFS, emit all distances",
    "dp": "n+2 cells, two modulo updates each iteration",
    "bigint": "all a=a*2+1 iterations; handwritten u32 limbs implement multiply/add/bit_length without a closed form",
}

def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()

def execute(command, stdin, timeout):
    timer = Path("/usr/bin/time")
    measured = [str(timer), "-f", "\nPY2FASTRUST_RSS=%M", *command] if timer.is_file() else command
    start = time.perf_counter()
    result = subprocess.run(measured, input=stdin, text=True, capture_output=True, timeout=timeout)
    elapsed = time.perf_counter() - start
    stderr, marker, rss = result.stderr.rpartition("PY2FASTRUST_RSS=")
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {command!r}\n{stderr if marker else result.stderr}")
    return {"stdout": result.stdout, "seconds": elapsed,
            "max_rss_kib": int(rss.strip()) if marker else None}

def input_text(case, size, batch):
    item = f"{size}\n"
    if case == "input":
        item += "".join(f"{i}\n" for i in range(size))
    elif case == "bfs":
        item = f"{size} {size-1}\n" + "".join(f"{i} {i+1}\n" for i in range(size-1))
    return f"{batch}\n" + item * batch

def batched_source(case):
    original = CASES[case]
    imports_end = 0
    for statement in ast.parse(original).body:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            break
        imports_end = statement.end_lineno
    lines = original.splitlines(keepends=True)
    setup = "".join(lines[:imports_end])
    body = "".join(lines[imports_end:])
    return setup + "batch=int(input())\nfor benchmark_batch in range(batch):\n" + textwrap.indent(body, " ")

def inspect_source(rust, backend):
    main = rust[rust.rfind("fn main()"):]
    lines = main.splitlines()
    allocations = re.compile(r"\b(?:Vec|Box|Rc|String)::|\bvec!|\.collect\b|with_capacity|obj_value")
    dynamic = re.compile(r"\b(?:Value|Runtime)\b|obj_value")
    loops = []
    if backend == "native":
        for index, line in enumerate(lines):
            if not re.search(r"\b(?:for|while)\b", line) or "{" not in line:
                continue
            body, depth = [], 0
            for following in lines[index:]:
                body.append(following)
                depth += following.count("{") - following.count("}")
                if depth == 0:
                    break
            loops.append({"main_line": index+1, "header": line.strip()[:240],
                          "dynamic_reference_lines": [text.strip()[:240] for text in body if dynamic.search(text)],
                          "allocation_marker_lines": [text.strip()[:240] for text in body if allocations.search(text)]})
    return {"method": "lexical main/brace scan, not a semantic or allocation proof",
            "contains_value_enum": "enum Value" in rust, "contains_runtime_struct": "struct Runtime" in rust,
            "dynamic_reference_lines_in_main": sum(bool(dynamic.search(line)) for line in lines),
            "native_loop_regions": loops,
            "aot_note": None if backend == "native" else "General AOT bodies use Value and runtime helpers; this main-only scan does not inspect their basic blocks"}

def environment(args):
    cpu = {}
    path = Path("/proc/cpuinfo")
    if path.is_file():
        for line in path.read_text().split("\n\n", 1)[0].splitlines():
            key, _, value = line.partition(":")
            if key.strip() in {"model name", "vendor_id", "cpu family", "model", "flags"}:
                cpu[key.strip()] = value.strip()
    def git_output(*arguments):
        try:
            result = subprocess.run(["git", *arguments], cwd=REPO, capture_output=True, text=True)
        except OSError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None
    git_status = git_output("status", "--short")
    return {"utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
            "python_executable": sys.executable, "platform": platform.platform(), "cpu_count": os.cpu_count(),
            "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "cpu": cpu, "rustc": subprocess.check_output(["rustc", "-vV"], text=True).strip(),
            "git_commit": git_output("rev-parse", "HEAD"),
            "git_status": git_status.splitlines() if git_status is not None else None,
            "benchmark_source_sha256": {name: digest((REPO / "benchmarks" / name).read_bytes())
                                        for name in ("run.py", "handwritten.rs")},
            "rust_flags": ["--edition=2021", "-O", *shlex.split(args.rust_flags)],
            "rss_method": "/usr/bin/time %M (KiB on Linux)" if Path("/usr/bin/time").is_file() else "unavailable",
            "wall_method": "parent perf_counter around process launch/wait; startup measured separately",
            "measurement_isolation": "shared host; affinity is recorded but other agents or OS workloads may run",
            "load_average_at_start": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            "command_line": sys.argv, "input_generator": "deterministic integers / chain; no RNG"}

def benchmark(case, args, root):
    root.mkdir(parents=True, exist_ok=True)
    size = args.size if args.size is not None else DEFAULT_SIZES[case]
    mode = "bigint" if case == "bigint" else "i64"
    source = batched_source(case)
    start = time.perf_counter()
    script = root / "source.py"
    script.write_text(source, encoding="utf-8")
    python_preparation = time.perf_counter() - start
    start = time.perf_counter()
    result = transpile(source, TranspileOptions(integer=mode, filename=str(script)))
    conversion = time.perf_counter() - start
    if not result.success:
        raise RuntimeError("\n".join(map(str, result.diagnostics)))
    generated = root / "generated.rs"
    generated.write_text(result.rust_source, encoding="utf-8")
    start = time.perf_counter()
    handwritten = root / "handwritten.rs"
    handwritten.write_text((REPO / "benchmarks" / "handwritten.rs").read_text(encoding="utf-8"), encoding="utf-8")
    hand_preparation = time.perf_counter() - start
    commands = {"cpython": [sys.executable, "-I", str(script)]}
    builds = {}
    for name, path, extra in [("generated_rust", generated, []),
                              ("handwritten_rust", handwritten, ["--cfg", f'benchmark="{case}"'])]:
        binary = root / name
        command = ["rustc", "--edition=2021", "-O", *shlex.split(args.rust_flags), *extra, str(path), "-o", str(binary)]
        compiled = execute(command, "", args.compile_timeout)
        commands[name] = [str(binary)]
        builds[name] = {"compile_seconds": compiled["seconds"], "compile_max_rss_kib": compiled["max_rss_kib"],
                        "compile_command": command, "source_bytes": path.stat().st_size,
                        "source_sha256": digest(path.read_bytes()), "binary_bytes": binary.stat().st_size,
                        "binary_sha256": digest(binary.read_bytes()),
                        "conversion_seconds": conversion if name == "generated_rust" else None,
                        "source_preparation_seconds": python_preparation if name == "generated_rust" else hand_preparation}
    if args.pypy:
        pypy = shutil.which("pypy3")
        if pypy is None:
            raise RuntimeError("--pypy requested, but pypy3 is unavailable")
        commands["pypy"] = [pypy, str(script)]
    def correct(data):
        expected = execute(commands["cpython"], data, args.timeout)["stdout"]
        for name, command in commands.items():
            if name != "cpython" and execute(command, data, args.timeout)["stdout"] != expected:
                raise RuntimeError(f"output mismatch: {case}/{name}")
        return expected
    small = input_text(case, args.verify_size, 1)
    small_output = correct(small)
    report = {"case": case, "algorithm": ALGORITHMS[case], "integer": mode, "backend": result.backend,
              "python_source": source, "python_source_bytes": len(source.encode()), "builds": builds,
              "source_inspection": inspect_source(result.rust_source, result.backend),
              "small_correctness": {"status": "passed", "size": args.verify_size,
                                    "input_sha256": digest(small), "output_sha256": digest(small_output)},
              "handwritten_note": "checked-in std-only source; cfg selects a case; conversion not applicable",
              "artifact_directory": str(root) if args.artifacts else None}
    if args.verify_only:
        return report
    startup = {name: statistics.median(execute(command, "0\n", args.timeout)["seconds"] for _ in range(3))
               for name, command in commands.items()}
    expected = correct(input_text(case, size, 1))
    batches, calibration, reasons = {}, {}, {}
    for name, command in commands.items():
        batch = args.batch or 1
        calibration[name] = []
        reasons[name] = "explicit batch" if args.batch else "minimum duration reached"
        if not args.batch and args.min_seconds:
            while True:
                data = input_text(case, size, batch)
                if len(data.encode()) > args.max_input_bytes:
                    raise RuntimeError("calibration input exceeds --max-input-bytes; choose a smaller --size")
                trial = execute(command, data, args.timeout)
                if trial["stdout"] != expected * batch:
                    raise RuntimeError(f"output mismatch during calibration: {case}/{name}")
                calibration[name].append({"batch": batch, "seconds": trial["seconds"]})
                # Target both useful work duration and <=20% startup overhead.
                if trial["seconds"] - startup[name] >= max(args.min_seconds, 4 * startup[name]):
                    break
                if batch >= args.max_batch or trial["seconds"] * 2 > args.max_generated_seconds:
                    reasons[name] = "batch/time cap; inspect startup fraction before interpreting ratios"
                    break
                batch = min(batch * 2, args.max_batch)
        batches[name] = batch
    inputs = {name: input_text(case, size, batch) for name, batch in batches.items()}
    samples = {name: [] for name in commands}
    names = list(commands)
    for trial in range(args.warmup + args.repeats):
        order = names[trial % len(names):] + names[:trial % len(names)]
        for name in order:
            measurement = execute(commands[name], inputs[name], args.timeout)
            if measurement.pop("stdout") != expected * batches[name]:
                raise RuntimeError(f"output mismatch during trial: {case}/{name}")
            if trial >= args.warmup:
                samples[name].append(measurement)
    results = {}
    for name, values in samples.items():
        durations = [value["seconds"] for value in values]
        rss = [value["max_rss_kib"] for value in values if value["max_rss_kib"] is not None]
        median = statistics.median(durations)
        results[name] = {"median_seconds": median, "min_seconds": min(durations), "max_seconds": max(durations),
                         "batch": batches[name], "median_seconds_per_instance": median / batches[name],
                         "input_bytes": len(inputs[name].encode()), "input_sha256": digest(inputs[name]),
                         "output_bytes": len(expected.encode()) * batches[name], "output_sha256": digest(expected * batches[name]),
                         "max_rss_kib": max(rss) if rss else None, "samples": values,
                         "startup_median_seconds": startup[name], "estimated_startup_fraction": min(1.0, startup[name] / median)}
    ratio = results["generated_rust"]["median_seconds_per_instance"] / results["handwritten_rust"]["median_seconds_per_instance"]
    guarded = all(results[name]["estimated_startup_fraction"] <= 0.2 for name in ("generated_rust", "handwritten_rust"))
    report.update({"size": size, "batches": batches, "work_items": {name: size*batch for name,batch in batches.items()},
                   "warmups": args.warmup, "repeats": args.repeats, "calibration": calibration, "calibration_stop_reason": reasons,
                   "single_instance_output_bytes": len(expected.encode()), "single_instance_output_sha256": digest(expected),
                   "batch_method": "independent engine batches, median process wall / batch; identical instance inputs/outputs",
                   "batch_lifetimes": "Python bindings persist until rebound; handwritten work locals drop each instance",
                   "results": results, "generated_vs_handwritten": {"median_per_instance_ratio": ratio,
                       "within_2x_observed_wall": ratio <= 2, "startup_guard_passed": guarded,
                       "within_2x_with_startup_guard": ratio <= 2 if guarded else None},
                   "generated_vs_cpython_speedup": results["cpython"]["median_seconds_per_instance"] / results["generated_rust"]["median_seconds_per_instance"]})
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--case", choices=CASES, nargs="+", action="append")
    group.add_argument("--all", action="store_true")
    for name, default in [("size", None), ("batch", None), ("repeats", 5), ("warmup", 2), ("verify-size", 17),
                          ("max-batch", 1024), ("max-input-bytes", 128*1024*1024)]:
        parser.add_argument("--"+name, type=int, default=default)
    for name, default in [("min-seconds", 0.02), ("max-generated-seconds", 5), ("timeout", 120), ("compile-timeout", 240)]:
        parser.add_argument("--"+name, type=float, default=default)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--rust-flags", default="", help="extra rustc flags, e.g. -Ctarget-cpu=native")
    parser.add_argument("--pypy", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifacts", type=Path, help="retain sources and binaries here")
    args = parser.parse_args()
    if any(value is not None and value < 1 for value in (args.size, args.batch, args.repeats, args.verify_size, args.max_batch, args.max_input_bytes)):
        parser.error("sizes/batches/repeats/limits must be positive")
    if args.warmup < 0 or args.min_seconds < 0 or min(args.timeout, args.compile_timeout, args.max_generated_seconds) <= 0:
        parser.error("warmup/min-seconds must be nonnegative; timeouts must be positive")
    cases = list(CASES) if args.all else list(dict.fromkeys(case for choices in (args.case or [["arithmetic"]]) for case in choices))
    report = {"schema_version": 3, "environment": environment(args), "scope": "selected deterministic workloads; wall time includes startup and IO",
              "configuration": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}, "cases": []}
    with tempfile.TemporaryDirectory(prefix="py2fastrust-bench-") as directory:
        root = args.artifacts.resolve() if args.artifacts else Path(directory)
        for case in cases:
            print(f"benchmark: {case}", file=sys.stderr, flush=True)
            try:
                report["cases"].append(benchmark(case, args, root/case))
            except (RuntimeError, subprocess.TimeoutExpired) as error:
                report["cases"].append({"case": case, "status": "error", "error": str(error)})
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text+"\n", encoding="utf-8")
    else:
        print(text)
    return int(any(case.get("status") == "error" for case in report["cases"]))

if __name__ == "__main__":
    raise SystemExit(main())
