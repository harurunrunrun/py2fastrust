"""Measure correctness first, then median execution time and peak RSS.

Run from a checkout: python benchmarks/run.py --case arithmetic --size 1000000
Results go to stdout; compilation time is measured separately.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from py2fastrust import TranspileOptions, transpile


CASES = {
    "arithmetic": "n=int(input())\ns=0\nfor i in range(n):\n s += (i*17+3)%1000000007\nprint(s)\n",
    "input": "n=int(input())\ns=0\nfor i in range(n):\n s += int(input())\nprint(s)\n",
    "list": "n=int(input())\na=[i%100 for i in range(n)]\ns=0\nfor x in a:\n s += x*x\nprint(s)\n",
    "sort": "n=int(input())\na=[(i*19237)%100003 for i in range(n)]\na.sort()\nprint(a[0],a[-1],sum(a))\n",
    "dict": "n=int(input())\nd={}\nfor i in range(n):\n k=i%101\n d[k]=d.get(k,0)+1\nprint(sum(d.values()))\n",
    "dp": "n=int(input())\na=[0]*(n+2)\na[0]=1\nfor i in range(n):\n a[i+1]=(a[i+1]+a[i])%1000000007\n a[i+2]=(a[i+2]+a[i])%1000000007\nprint(a[n])\n",
    "bigint": "n=int(input())\na=1\nfor i in range(n):\n a=a*2+1\nprint(a.bit_length())\n",
}
CASES["bfs"] = (Path(__file__).resolve().parents[1] / "examples" / "bfs.py").read_text()
HANDWRITTEN = r'''use std::io::{self, Read};fn main(){let mut s=String::new();io::stdin().read_to_string(&mut s).unwrap();let n:i64=s.trim().parse().unwrap();let mut sum=0_i64;for i in 0..n {sum=sum.wrapping_add((i.wrapping_mul(17).wrapping_add(3))%1000000007);}println!("{}",sum);}'''


def execute(command, stdin):
    timer = Path("/usr/bin/time")
    measured = [str(timer), "-f", "\nPY2FASTRUST_RSS=%M", *command] if timer.is_file() else command
    start = time.perf_counter()
    result = subprocess.run(measured, input=stdin, text=True, capture_output=True, timeout=120)
    elapsed = time.perf_counter() - start
    stderr, marker, rss = result.stderr.rpartition("PY2FASTRUST_RSS=")
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout, elapsed, int(rss.strip()) if marker else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, default="arithmetic")
    parser.add_argument("--size", type=int, default=2000)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmup", type=int, default=2)
    args = parser.parse_args()
    if args.size < 1 or args.repeats < 1 or args.warmup < 0:
        parser.error("size/repeats must be positive and warmup must be nonnegative")
    source = CASES[args.case]
    mode = "bigint" if args.case == "bigint" else "i64"
    stdin = str(args.size) + "\n"
    if args.case == "input":
        stdin += "\n".join(str(i) for i in range(args.size)) + "\n"
    if args.case == "bfs":
        stdin = f"{args.size} {args.size-1}\n" + "".join(f"{i} {i+1}\n" for i in range(args.size-1))
    with tempfile.TemporaryDirectory(prefix="py2fastrust-bench-") as directory:
        root = Path(directory)
        script = root / "source.py"
        script.write_text(source)
        start = time.perf_counter()
        result = transpile(source, TranspileOptions(integer=mode, filename=str(script)))
        transpile_seconds = time.perf_counter() - start
        if not result.success:
            raise RuntimeError("\n".join(map(str, result.diagnostics)))
        rust = root / "main.rs"
        rust.write_text(result.rust_source)
        start = time.perf_counter()
        subprocess.run(["rustc", "--edition=2021", "-O", str(rust), "-o", str(root / "main")], check=True)
        compile_seconds = time.perf_counter() - start
        commands = {"cpython": [sys.executable, str(script)], "generated_rust": [str(root / "main")]}
        pypy = shutil.which("pypy3")
        if pypy:
            commands["pypy"] = [pypy, str(script)]
        if args.case == "arithmetic":
            handwritten = root / "handwritten.rs"
            handwritten.write_text(HANDWRITTEN)
            subprocess.run(["rustc", "--edition=2021", "-O", str(handwritten), "-o", str(root / "handwritten")], check=True)
            commands["handwritten_rust"] = [str(root / "handwritten")]
        expected = execute(commands["cpython"], stdin)[0]
        results = {}
        for name, command in commands.items():
            durations, memory = [], []
            for trial in range(args.warmup + args.repeats):
                stdout, seconds, rss = execute(command, stdin)
                if stdout != expected:
                    raise RuntimeError(f"output mismatch: {name}")
                if trial >= args.warmup:
                    durations.append(seconds)
                    if rss is not None:
                        memory.append(rss)
            results[name] = {"median_seconds": statistics.median(durations),
                             "max_rss_kib": max(memory) if memory else None}
        print(json.dumps({"case": args.case, "size": args.size, "int": mode,
                          "python": sys.version, "platform": sys.platform, "cpu_count": os.cpu_count(),
                          "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
                          "transpile_seconds": transpile_seconds, "compile_seconds": compile_seconds,
                          "generated_source_bytes": rust.stat().st_size, "binary_bytes": (root / "main").stat().st_size,
                          "results": results}, indent=2))


if __name__ == "__main__":
    main()
