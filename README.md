# py2fastrust

The `pytors` command transpiles Python 3.14 programs into a single Rust source file that needs no external crates.
Type hints and changes to the input program are not required.

This is an incomplete alpha release undergoing a direct-code-generation rewrite.
The public CLI and API either generate typed Rust or return a source-positioned
`E006` diagnostic. A failed lowering never selects another execution backend.
Required language and library coverage remains unfinished; rejecting an
unimplemented program is not completion of that requirement.
See [COMPATIBILITY.md](COMPATIBILITY.md) for the current public boundary and
[API_SUPPORT.md](API_SUPPORT.md) for the retained internal library inventory.

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

The integer mode applies to the entire directly generated program:

```bash
pytors main.py -o main.rs                 # i64 (default)
pytors main.py -o main.rs --int i128
pytors main.py -o main.rs --int bigint
```

In `i64` and `i128` modes, integer literals, conversions, and arithmetic results wrap to the selected signed width.
Use `--int bigint` when you need Python's arbitrary-precision integer behavior.
The generated file includes the BigInt runtime, so Cargo and additional crates are unnecessary.
Range termination, indices, and allocation sizes use separate checked calculations.

Strings default to ASCII mode for competitive-programming inputs. Their length,
indices, slices, and `count` bounds use bytes without scanning the string to
detect ASCII on each access. Use Unicode mode for non-ASCII text and Python's
code-point indexing:

```bash
pytors main.py -o main.rs --string-mode unicode
```

The API setting is `TranspileOptions(string_mode="unicode")`; the browser
provides the same selection. ASCII mode assumes that strings contain ASCII.
It does not automatically switch models when non-ASCII input is encountered.
The ASCII profile also selects ASCII numeric-text parsing and omits Unicode
property tables and code-point indexing caches. Buffered text input rejects
non-ASCII bytes; binary streams remain byte streams. Unicode mode enables
non-ASCII digits, whitespace, and code-point operations where supported.

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

Allowed options are `--int`, `--string-mode`, `--license`, `--module-path`, `--include-module`,
`--no-optimize`, `--optimize`, `-o`/`--output`, and `--check`.
Input filenames, help, and version options are not accepted in directives.
If a scalar option appears more than once, the last value wins.
Source declarations of repeated options, such as `--module-path` and `--include-module`,
replace the corresponding CLI or API list; repeated source declarations accumulate within that list.
Relative paths in directives are resolved from the input file's directory.

Output paths and `--check` affect the CLI only. The Python API returns a result and never writes files,
even when those options appear in the source.

## Modules

The direct path recognizes proved `collections.deque` imports using the
compiler's actual module resolution. A user module with the same name is not
silently replaced by that specialization.
Resolved `heapq` min/max heap operations and `bisect` searches/insertions use
typed list helpers. Their current payload and callable-key boundaries are
listed in [COMPATIBILITY.md](COMPATIBILITY.md).
It also recognizes trusted `sys.stdin` and `sys.stdin.buffer` readers, including
captured `read`/`readline` aliases and local imports inside ordinary functions.
Text and byte reads retain their different newline, EOF, whitespace, and
integer-parsing rules. Both use the same buffered input stream.

General fixed-name imports, pure-Python packages, and `--include-module` remain
required work for direct Rust generation. Their existing internal runtime code
is retained, but the public API does not select it. `--module-path` and
`--include-module` remain recognized options; an unimplemented direct import or
explicit module bundle produces a diagnostic instead of being ignored.
The input file's directory remains the default module search path.

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

The shared frontend parses each source once with the official `ast` and
`symtable` APIs, validates contextual syntax, and resolves fixed-name imports
before native lowering. All direct emitters consume the same read-only source
unit and lexical metadata. No VM instruction compilation is needed for public
conversion. Only requested modules are resolved; `__future__` is not implicitly
loaded.
A shared semantic graph solves allocation field constraints and loop-header
binding shapes before ordinary Rust lowering, including empty collections and
possibly unbound names. It contains compile-time facts and typed control-flow
edges; the generated program executes its Rust statements directly. Nested lists
with proved immutable payloads retain typed shared row identities across aliases,
ordinary function calls, parent replacement/clearing, and live iteration in all
integer modes. Flat uniquely owned arrays keep their existing vector storage.

`source_map` retains original file, line and column. Its `code` field identifies
a lexical scope; `instruction` is a stable AST ordinal within that scope, rather
than a generated Rust instruction offset. These positions remain identical
with optional Rust helper pruning enabled or disabled.
A successful public result has `backend="native"`. An unimplemented direct
lowering returns `rust_source=None` and an `E006` diagnostic at the relevant
source operation. Official Python syntax, scope and module-resolution errors
keep their existing diagnostic categories.

`TranspileOptions(optimize=False)` and the CLI's `--no-optimize` option disable
optional Rust helper pruning. Direct typed generation and its correctness
proofs still run. Neither setting enables another execution path. `--check`
checks conversion without writing a Rust file.

## Direct generation and remaining work

The converter uses Python's official `ast` and `symtable` APIs. Supported
bindings, operators and control flow become Rust values, expressions, loops
and functions. The current implementation covers proved integer and boolean
operations, shared immutable strings and `f64` scalars, owned BigInt scalar operations, integer
lists and shared nested rows, dictionaries, sets and integer deques, including bounded queues. It supports
ordinary scalar functions with proved argument and return kinds, constant
defaults, positional and keyword binding, and calls between those functions.
Statically known function aliases retain their original definitions across
rebinding, with separate specializations for the actual argument kinds and
callable globals. Integer-list slices and `sorted` create independent lists.
Python names can change type through distinct typed Rust slots. Compatible
branches and loops merge proved kinds; finite boolean/integer unions use a
small stack enum. ASCII string indexing accesses bytes directly. Opt-in Unicode
indexing caches character lengths and lazily builds shared byte offsets for
repeated reads. String snapshots share immutable storage, and proved fixed-width
ASCII loops can use guarded byte spans. Integer modes preserve their documented
wrapping policy.

Supported competitive-programming patterns include unpacked integer input,
`list(map(int, input().split()))`, integer-list mutation and sorting, dictionary
aggregation and insertion-order iteration, and owned adjacency-list BFS.
Standard input is buffered and read on demand. Output flushes before a blocking
input operation, including inside supported ordinary functions.
Immediate iterator producers and consumers share immutable semantic plans.
`for`, reductions, `list`, `sorted`, `next`, unpacking, and string `join` consume
those plans, with callable identities and argument roles resolved before Rust
loop generation. Statically captured builtin aliases use the same producer and
consumer paths. Text and byte splitting share word-stream adapters; integer
parsing is selected from their proved element conversion, rather than from a
particular spelling of `input().split()`. Unpacking pulls at most one extra
converted item and assigns targets only after validating the item count.
In fixed-width modes, decimal text and byte conversions accumulate directly in
the selected Rust integer type. Scalar calls, captured builtin aliases, word
streams and proved character projections share this parser; they do not create
arbitrary-precision integer temporaries or acquire standard input solely to
convert an existing value. Unicode digit and whitespace data is included only
when the selected Unicode profile and retained operations require it.
Immediately consumed generator expressions use typed loops for reductions.
All integer modes also support character-based string slicing,
`strip`/`lstrip`/`rstrip`, `count`, and `join` over proved string streams.

Ordinary class instances can use concrete Rust structs, typed fields and
methods, and shared lists with proved scalar, tuple, instance or nested-list
elements. Shallow copies and repetition retain inner aliases. Synchronous list
comprehensions on this path generate typed loops with isolated target bindings.
Small acyclic call paths use ordinary Result-returning Rust functions.
Recursive methods and longer call chains use typed Rust futures with an
iterative call executor and a logical Python recursion limit. Both call forms
keep Python argument order and exception frames. Proved stable concrete fields
can be reused lazily within loops without changing first-read errors.
This initial class implementation has a separate proof boundary; integrating
it with common semantic lowering remains required work. Inheritance,
descriptors, metaclasses, escaped methods, cyclic ownership, heterogeneous
mutable alternatives and unproved container protocols are not yet implemented.

If the implementation cannot establish a supported direct representation, it
reports the missing construct or type combination. This currently includes
many mutable aliases and mixed-type joins, recursion outside the class path,
closures, exceptions, user-defined generators, general object models,
dynamic execution, and most standard-module calls.
These are implementation gaps that must be restored through direct generation;
they are not removed from the project's goals and do not require users to add
type hints or rewrite ordinary Python as a substitute.

The source tree retains earlier general-runtime, object-model, parser and
execution code and its compatibility tests for the continuing rewrite. The
public `transpile()` and `pytors` entry points never call that backend after a
direct lowering fails. There is no fallback mode or switch that enables it.

The benchmarks check that CPython, generated Rust, and handwritten Rust produce the same results.
They cover arithmetic, I/O, indexed ASCII strings, arrays, sorting, dictionaries,
sets, BFS, DP, and BigInt.
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

Direct integer dictionaries and sets use Rust `HashMap` and `HashSet`.
Operations at either end of a supported deque are amortized O(1).
Unimplemented benchmark patterns produce the same positioned diagnostic as
other input programs; they are not measured through another backend.

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 tests/test_native.py --benchmark-native
python3 tools/check_standalone.py
```

Tests include CPython differential checks, an independent fixed-width reference,
randomized BigInt arithmetic, and explicit no-fallback API/CLI checks. Existing
class, GC, closure, generator, dynamic execution and module acceptance tests are
retained. Many of those public acceptance cases currently expose missing direct
lowering; the strict boundary is not a claim that the full suite or CI is green.
CI targets Rust 1.85 and stable.

`check_standalone.py` retains the advanced all-integer-mode acceptance fixture,
including execution without Python on PATH. That fixture is currently blocked
by missing direct features and must be restored through implementation. Its
`--wheel` and `--output` options remain available for distribution verification.

## Licenses and generated headers

The transpiler uses the [MIT license](LICENSE). Its generated-output permission
allows original runtime helpers in generated programs to be distributed without
the project's copyright or MIT notice. Third-party code and data keep their own
required notices when included.
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
This selection applies to translated program logic. Original generated helpers
do not impose an additional project copyright notice. Third-party components
retain their required license notices when present.

Each generated Rust file begins with line comments containing the selected `LICENSE`,
the project URL, the exact statement “Transpilation does not use generative AI.”,
the integer and string modes, the original source's SHA-256 hash, and the full selected license text.
The original Python input, before import expansion, follows as line comments.
Generated implementation code omits explanatory and documentation comments.
Empty `else` blocks and unused scalar bindings are removed when their removal
preserves Rust type inference and Python execution order. Expressions that still
need evaluation keep their type context even when their result is discarded.
Objects with uncertain destructor or borrow lifetimes retain their bindings.
Required third-party attributions and license texts remain in a separate notice
block when their code or data is included.
Transpilation uses the compiler and runtime described above and does not call a generative-AI service.

See [THIRD_PARTY.md](THIRD_PARTY.md) and the bundled PSF and Unicode licenses for
CPython-derived standard-library code, numerical algorithms, and Unicode data.
