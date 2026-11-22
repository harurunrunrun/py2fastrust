"""Run the unittest modules in tests/ in parallel, optionally as one shard of several.

Each test module runs in its own ``python -m unittest`` process, so modules
cannot share interpreter state. Modules are assigned to shards by a greedy
balance on file size (a stable proxy for runtime), and every module belongs to
exactly one shard. The exit status is nonzero if any module fails.

    python3 tools/run_tests.py                     # all modules, one process per CPU
    python3 tools/run_tests.py --shard 2 --shards 8 --jobs 4
    python3 tools/run_tests.py test_native_sets test_native_deques
"""
import argparse
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def modules():
    return sorted(path.stem for path in TESTS.glob("test*.py"))


def assign(names, shards):
    """Largest-first greedy assignment; deterministic for a given tree."""
    loads = [0] * shards
    owners = {}
    for name in sorted(names, key=lambda item: (-(TESTS / (item + ".py")).stat().st_size, item)):
        target = min(range(shards), key=lambda index: (loads[index], index))
        owners[name] = target
        loads[target] += (TESTS / (name + ".py")).stat().st_size
    return owners


def run(name, timeout):
    started = time.monotonic()
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        result = subprocess.run([sys.executable, "-m", "unittest", "-v", name], cwd=TESTS, env=environment,
                                capture_output=True, text=True, timeout=timeout)
        return name, result.returncode, result.stdout + result.stderr, time.monotonic() - started
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + (error.stderr or "")
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return name, -1, output + f"\nTIMEOUT after {timeout}s", time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--timeout", type=int, default=3600, help="seconds per module")
    parser.add_argument("--list", action="store_true", help="print this shard's modules and exit")
    parser.add_argument("names", nargs="*", help="run only these test modules (default: all)")
    options = parser.parse_args()
    if not 0 <= options.shard < options.shards:
        parser.error("--shard must be in [0, --shards)")
    known = modules()
    unknown = sorted(set(options.names) - set(known))
    if unknown:
        parser.error("unknown test modules: " + " ".join(unknown))
    owners = assign(options.names or known, options.shards)
    selected = sorted(name for name, shard in owners.items() if shard == options.shard)
    if options.list:
        print("\n".join(selected))
        return 0
    print(f"shard {options.shard}/{options.shards}: {len(selected)} modules, {options.jobs} parallel jobs", flush=True)
    failed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, options.jobs)) as pool:
        futures = [pool.submit(run, name, options.timeout) for name in selected]
        for future in concurrent.futures.as_completed(futures):
            name, code, output, seconds = future.result()
            status = "ok" if code == 0 else "FAILED"
            print(f"{status:6} {name} ({seconds:.0f}s)", flush=True)
            if code != 0:
                failed.append(name)
                print(output, flush=True)
    failed.sort()
    print(f"{len(selected) - len(failed)} passed, {len(failed)} failed" + (": " + " ".join(failed) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
