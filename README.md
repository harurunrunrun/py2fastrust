# py2fastrust

The `pytors` command transpiles Python 3.14 programs into a single Rust source file that needs no external crates.
Type hints and changes to the input program are not required.

This is an alpha release. See [COMPATIBILITY.md](COMPATIBILITY.md) for supported features and known limitations,
and [API_SUPPORT.md](API_SUPPORT.md) for individual standard-library APIs.

## Usage

Transpilation requires Python 3.14 or later. Compiling the generated code requires Rust 1.85 or later.
The compiled executable needs neither Python nor additional source files.

```bash
python3 -m pip install -e .
pytors examples/sum.py -o /tmp/main.rs
rustc --edition=2021 -O /tmp/main.rs -o /tmp/main
printf '4\n1 2 3 4\n' | /tmp/main
```

You can also run the transpiler from the repository root without installing it:

```bash
python3 -m py2fastrust examples/sum.py -o /tmp/main.rs
```

The [browser converter](web/README.md) provides a black-and-white, two-panel
interface for the same compiler using Python 3.14 in a Pyodide module worker.
It accepts a single source file and keeps translation in the browser after the
runtime assets load. See its documentation for local verification and GitHub
Pages deployment.

The integer mode applies to the entire generated program, including `eval` and `exec`:

```bash
pytors main.py -o main.rs                 # i64 (default)
pytors main.py -o main.rs --int i128
pytors main.py -o main.rs --int bigint
```

In `i64` and `i128` modes, integer literals, conversions, and arithmetic results wrap to the selected signed width.
Use `--int bigint` when you need Python's arbitrary-precision integer behavior.
The generated file includes the BigInt runtime, so Cargo and additional crates are unnecessary.
Range termination, indices, and allocation sizes use separate checked calculations.

## Options in source comments

Conversion options can be recorded in the initial comment block:

```python
# pytors: --int i128 --license Unlicense
n = int(input())
print(n * n)
```

Source options take precedence over command-line and Python API settings.
The parser reads blank lines and comments, including shebang and encoding comments,
and stops at the first Python statement. Later directives have no effect.

Allowed options are `--int`, `--license`, `--module-path`, `--include-module`,
`--no-optimize`, `--optimize`, `-o`/`--output`, and `--check`.
Input filenames, help, and version options are not accepted in directives.
If a scalar option appears more than once, the last value wins.
Source declarations of repeated options, such as `--module-path` and `--include-module`,
replace the corresponding CLI or API list; repeated source declarations accumulate within that list.
Relative paths in directives are resolved from the input file's directory.

Output paths and `--check` affect the CLI only. The Python API returns a result and never writes files,
even when those options appear in the source.

## Modules

Fixed-name imports and bundled pure-Python modules and packages are supported.
The input file's directory is the default module search path.

```bash
pytors main.py --module-path ./lib -o main.rs
pytors main.py --include-module helpers -o main.rs
```

Use `--include-module` to bundle modules that the ordinary source does not reference, such as imports inside `eval` or `exec`.
The generated executable uses bundled code and the supported standard modules.

## Python API

```python
from py2fastrust import TranspileOptions, transpile

result = transpile(
    'n = int(input())\nprint(n * n)\n',
    TranspileOptions(integer="i128", filename="solution.py", license="Unlicense"),
)
if result.success:
    print(result.rust_source)
else:
    for diagnostic in result.diagnostics:
        print(diagnostic)
```

`source_map` maps code units and instruction positions to the original file, line, and column.
`backend` is either `native` or `vm`. Select the general runtime with
`TranspileOptions(optimize=False)` or the CLI's `--no-optimize` option.
`--check` checks whether conversion succeeds without writing a Rust file.

## Execution and performance

Ordinary input is parsed with Python's official `ast` and `symtable` APIs to analyze scopes and evaluation order.
When types and bindings can be established, `i64`/`i128` integers, integer arrays and independent rows,
integer dictionaries, sets, deques, and loops become native Rust integers, `Vec<T>`, `HashMap`, `HashSet`, `VecDeque`, and control flow.
Supported patterns include `list(map(int, input().split()))`, unpacked integer input,
integer-list `append`, `extend`, and `sort`, dictionary aggregation, and dictionary iteration in insertion order.
Native integer sets support construction, insertion, deletion, membership, and `sum`.
Programs that observe set iteration order or sharing use the general runtime.
Owned adjacency lists and unbounded integer deques support native BFS loops.
Deque specialization uses the compiler's resolved bundled `collections` module; a user module of the same name is respected.
Shared rows, container aliases, and mutation during active iteration use the general runtime.
Programs that cannot be specialized also use the shared dynamic runtime.
The optimizer follows proved type changes and combines compatible branch and loop states.
Finite unions of `bool` and integer values also stay native across branches and loop back edges.
A stack value preserves their distinct result types and formatting without object allocation.
Unproved combinations use the general runtime.
Ordinary user functions get separate Rust versions for proved integer, boolean, and read-only integer-list arguments.
Scalar results retain their integer or boolean type; positional and keyword arguments, constant defaults, and calls between functions are supported.
Integer lists are borrowed without copying; functions that mutate or expose those argument lists use the general runtime.
Recursion and functions with dynamic global or closure state use the general runtime.
Within a general-runtime program, selected pure arithmetic function bodies can also use native code.
Entry guards check the actual code object and bound integer arguments before any body operation;
other argument types execute the original instructions. `--no-optimize` disables these entry paths.
For simple module-level code, the optimizer also proves whether dynamic compilation is unreachable.
The proof checks both the AST and the lowered control flow, including reaching assignments,
possible types, call targets, and unknown effects. Uncertain paths retain the runtime parser.
When that proof succeeds, the general backend omits the runtime parser and its Unicode name tables.
Imports, reflection, indirect calls, user-defined functions or classes, and unknown syntax retain the full runtime.
`--no-optimize` retains all runtime components.

The runtime handles shared objects, GC, function frames, exceptions, classes, and closures.
List, set, and dict comprehensions run in their enclosing frame with isolated iteration bindings
and Python 3.14 local snapshots. Generators and class-visible annotation comprehensions retain their own frames.
Module and builtin namespaces are ordinary dictionaries. Functions and frames retain the builtin mapping captured at creation; replacing a module's `__builtins__` affects later captures, while mutations to an already captured mapping remain visible.
Calls retain original expanded keyword key objects and their stored hashes across functions, partials, caches, and metaclasses.
Ordinary cached-function recursion uses explicit execution frames, including cache misses and exceptional returns.
Exception groups and `except*` support subgroup handling, reraising, and merging unhandled exceptions.
Runtime `eval` and `exec` use a Rust tokenizer and PEG rules generated from CPython 3.14.4's official grammar,
then lower the resulting syntax tree directly to the shared instructions.
Syntax without runtime support produces a diagnostic.
The runtime also supports `__future__` declarations and flag inheritance, Unicode NFKC identifiers,
type parameters, lazy type aliases, and GenericAlias parameter substitution in both static and dynamic code.
T-strings produce `Template` and `Interpolation` objects that retain expression values, conversions, and format specifications.
Complex literals, arithmetic, and conversions, as well as runtime `compile(optimize=1/2)`, are supported.
Dynamic execution accepts keyword `globals`/`locals` and preserves dictionary subclass identity.
`compile()` supports path-like filenames and source encoding declarations in bytes.
Unicode 16.0 character names and aliases in `\N{name}` escapes work in dynamically compiled strings,
f-strings, and t-strings.
Immutable `frozenset` values support mixed operations with `set`, cached hashing, subclasses, and generic aliases.
Standard input is buffered and read on demand in both backends. Interactive pipe programs can
show an `input()` prompt or `print(..., flush=True)` output before stdin reaches EOF.
Text reads keep decoded look-ahead while sharing the underlying input with `sys.stdin.buffer`.


The benchmarks check that CPython, generated Rust, and handwritten Rust produce the same results.
They cover arithmetic, I/O, arrays, sorting, dictionaries, sets, BFS, DP, and BigInt.
Pass `--pypy` to include PyPy in the comparison; this requires `pypy3` on PATH.

```bash
python3 benchmarks/run.py --all --output /tmp/bench.json --artifacts /tmp/bench-artifacts
python3 benchmarks/run.py --case arithmetic --case set --size 5000000 --output /tmp/selected.json
python3 benchmarks/run.py --all --size 17 --verify-only
```

Each implementation repeats the same input, adjusting the repetition count to reduce the effect of process startup.
The JSON report records median and raw execution times, peak RSS, transpilation and compilation times,
source and executable sizes and hashes, and environment details.
Checking the target of at most twice the runtime of handwritten Rust also requires checking startup overhead.
If measurement limits prevent a sufficiently long run, the report records that limitation.
Generated-source audit results are saved too, but text checks alone cannot prove the absence of unnecessary allocations
or guarantee the performance of other programs.

Programs using dynamic features have different performance characteristics from specialized programs.
The general runtime currently uses linear searches for `dict` and mutable `set`.
`frozenset` retains member hashes and uses hash buckets for membership.
Native integer dictionaries and sets use `HashMap` and `HashSet`.
Operations at either end of `deque` are amortized O(1); moving an `OrderedDict` entry to the front is O(n).

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 tests/test_native.py --benchmark-native
python3 tools/check_standalone.py
```

Tests cover execution differences against CPython 3.14, a reference model for fixed-width integers,
randomized BigInt arithmetic, GC, and calls between dynamic and AOT code.
CI targets Rust 1.85 and stable.
`check_standalone.py` builds and runs debug and optimized programs in every integer mode,
including with a PATH that cannot find Python.
Use `--wheel path/to/package.whl` to check a distribution and `--output directory` to save generated sources,
executables, and measurements.

## Licenses and generated headers

The transpiler and original runtime code use the [MIT license](LICENSE).
The license recorded for translated program logic defaults to `CC0-1.0`.
If the original Python source specifies a license, that license takes precedence.
The selected output license applies when the original source does not specify one.
Use `--license` or `TranspileOptions(license=...)` to select another bundled license.
List the available canonical identifiers with `pytors --list-licenses`:

```bash
pytors --list-licenses
```

For example:

```bash
pytors main.py -o main.rs --license CC0-1.0
pytors main.py -o main.rs --license Unlicense
pytors main.py -o main.rs --license MIT
```

License names are case-insensitive; `cc0` is also accepted for `CC0-1.0`.
A source comment can override this choice, as shown above.
This selection applies to translated program logic. Bundled runtime and third-party components
retain their existing license notices.

Each generated Rust file begins with line comments containing the selected `LICENSE`,
the project URL, the exact statement “Transpilation does not use generative AI.”,
the integer mode and backend, the original source's SHA-256 hash, and the full selected license text.
The original Python input, before import expansion, follows as line comments.
Transpilation uses the compiler and runtime described above and does not call a generative-AI service.

See [THIRD_PARTY.md](THIRD_PARTY.md) and the bundled PSF and Unicode licenses for
CPython-derived standard-library code, numerical algorithms, and Unicode data.
