# Compatibility

The language target remains Python 3.14. The public CLI and API now require
direct typed Rust generation. If that implementation is missing, they return a
source-positioned `E006` diagnostic and no Rust file. They never select the
retained general backend. `--no-optimize` disables optional helper pruning and
keeps the same direct generation path.

## Current public direct path

Proved integer/boolean and String/f64 scalars, BigInt scalar arithmetic and
functions, integer containers, compatible branches/loops, scalar functions and
selected competitive-programming input/BFS patterns are implemented. This is
an incomplete subset of the required Python language. Recursion, closures,
exceptions, classes/metaclasses, generators, dynamic execution, general imports
and many mixed-type/alias cases still require direct lowering. An `E006`
diagnostic makes that gap explicit; it does not satisfy the missing feature.

## Retained internal runtime implementation

The following inventory describes code and regression coverage retained for
the rewrite. These tables are not a claim that the strict public converter
currently accepts every listed feature. Existing acceptance tests remain in
place, and full-suite/CI success must be restored through direct implementation.

### Language and runtime features

| Category | Retained internal implementation |
|---|---|
| Values | `None`, `bool`, integers in the selected mode, `float`, `complex`, `str`, `bytes`, `bytearray`, `memoryview`, `list`, `tuple`, `dict`, `set`, `frozenset`, `slice`, `range`, live dictionary views and `mappingproxy`, GenericAlias, union types, Template, Interpolation |
| Variables | Type changes, shared references, chained and unpacking assignments, `global`/`nonlocal`, unbound-name errors |
| Control flow | `if`, `while`, `for`, `break`/`continue`, loop `else`, short-circuit operators, chained comparisons |
| Functions | Defaults, positional-only and keyword-only arguments, variadic arguments, recursion, lambdas, closures with shared writable `cell_contents`, read-only `__closure__`, type parameters with lazy bounds and defaults |
| Container expressions | Comprehensions, generator expressions, unpacking, negative indices, slicing |
| Exceptions | `raise`, `except`, `except*`, exception-group splitting and merging, `else`, `finally`, `assert`, original `args`, cause/context/notes, exception-target cleanup, source information in tracebacks |
| Classes | Inheritance, C3 MRO, descriptors, `property`, `staticmethod`/`classmethod`, `super`, metaclasses, `__slots__`, subclasses of `list`/`tuple`/`dict`/`set`/`frozenset`/`str`/`bytes`/`bytearray`/`int`/`float`/`complex` |
| Comprehensions | List/set/dict expressions execute in the enclosing frame with isolated iteration bindings and fresh local snapshots; generators and class-visible annotation comprehensions retain separate frames |
| Namespaces | `__prepare__` returning custom mappings, private names, Unicode NFKC identifiers, ordinary module/builtin dictionaries with arbitrary hashable keys and string-subclass lookup protocols, dictionary insertion order, separate internal temporaries, Python 3.14 function-local snapshots including free variables |
| Other constructs | `with`, generator `send`/`throw`/`close` and `yield from`, f-strings, t-strings, `match`/`case` |
| Dynamic execution | `compile`/`eval`/`exec`, `compile(optimize=0/1/2)`, calls between static and dynamic code, lazy annotations and `type` statements, all known `__future__` features and flag inheritance |
| Memory | Object identity, cyclic references, mark-and-sweep GC rooted in frames and temporary values, `__del__` and resurrection |

Ordinary function recursion, including calls through `cache` and `lru_cache`, uses heap-allocated frames.
Direct value protocols, `print`, iteration, `map`/`filter`/`zip`, itertools consumers,
container construction and lookup, sorting, `min`/`max`, `functools.reduce`, and Python class
creation callbacks use caller-owned
heap continuations, together with selected descriptor binding, subscription, attribute access,
unary/binary operators, and rich comparisons.
Return validation runs after the Python callback has returned, in its caller's exception scope.
Some internal built-in callback paths still reenter through Rust calls and need further continuation adapters.

Functions retain shared cells for their free variables without retaining unrelated enclosing locals.
Acyclic captured buffer exports can be released with automatic cyclic GC disabled;
recursive cell cycles remain exported until collection. Class annotation dictionary
and conditional annotation cells share the public closure-cell storage.

Heap classes retain stable `__mro__` and `__bases__` tuple identities, including
their MRO ownership cycles. Custom metaclass MRO binding and result iteration,
class bodies and cells, namespace copies, slot iterables, generic parameter
collection, `__set_name__`, `__init_subclass__`, and Python `__new__`/`__init__`
callbacks use caller-owned continuations. Class callbacks follow the configured
Python frame limit; native callback count at an error can differ from CPython.
MRO callbacks observe the previous cached tuple (or `None` during creation).

Changing `__bases__` validates physical layouts and updates descendants in
registration and depth-first order. Pending descendant snapshots stay alive
through callbacks and GC. Errors or discarded work restore owned updates while
preserving a later reentrant change and callback writes to instance slots.
Class allocation slots remain distinct from visible `__new__` attributes.
Native payloads omitted by a custom MRO remain owned without exposing removed
methods. Some native primitive conversion and buffer callbacks still require
additional continuation adapters.

`types.CellType` exposes its native class metadata, rich-comparison wrappers, and
writable `cell_contents` descriptor. Empty cells sort before filled cells; filled
cells delegate comparisons to their contents and preserve arbitrary rich results.
Cell descriptor callbacks use the same heap continuation queue as other code.

Sorting retains stable equal-key order, keeps the list temporarily empty during
callbacks, and restores it on errors. Mutations during sorting raise `ValueError`,
including an empty extension that reserves storage through a positive length hint.

`sys.setrecursionlimit` controls Python frame depth. Finite native list/tuple comparison nesting does not
consume that budget. Pending native protocol actions have a separate 64 MiB storage bound, counting
inline action records and boxed native operation records; exhaustion raises `RecursionError` in the caller.
Callback-free native comparison cycles can be detected earlier. Stateful callbacks retain their effects
and may terminate a cycle normally. The exact callback count at a recursion error need not match
CPython's adaptive opcode specialization or platform-specific C-stack guard.

The retained general backend generates Rust code bodies with shared value and
object helpers. It also contains instruction execution for runtime-compiled
source. The public converter does not call this backend on proof failure,
regardless of optimization settings. These retained mechanisms are not a
fallback option for unfinished direct lowering.

`frozenset` supports construction, hashing, iteration, membership, comparisons, read-only set methods,
mixed operations with `set`, subclasses, and GenericAlias.
Member hashes and the final frozenset hash are retained; operations that copy a set's contents reuse stored member hashes.

Standard input is read on demand. `input()` captures the current `sys.stdin`,
`sys.stdout`, and `sys.stderr` before callbacks; redirected prompt, flush, and
readline operations run through the caller's heap continuation. It preserves
nonterminal string/bytes results and strips one trailing LF. Terminal input
uses the native reader with encoding metadata and trailing CR/LF handling.
`print(..., flush=True)` and explicit standard-stream flushes are observable before input EOF.
Text and binary input share a buffered raw reader, with decoded look-ahead retained for text reads.
Standard input uses the existing strict UTF-8 policy and preserves CR bytes in LF-terminated lines.

`bytearray` provides mutable binary storage and its public construction, search,
ASCII transformation, translation, and mutation methods. `memoryview` retains
shared storage through slices, native scalar casts, shapes, strides, read-only
views, context managers, and explicit release. Active exports prevent resizing;
Python `__buffer__` and `__release_buffer__` methods participate in the same GC
roots and lease lifecycle. Cyclic exporters remain pinned until collected.

Native file I/O supports `open`, `io.FileIO`, `io.BufferedReader`,
`io.BufferedWriter`, `io.BufferedRandom`, and `io.TextIOWrapper` with stable
`raw`/`buffer` identities, context managers, iteration, close/detach, checked
seek/truncate, and directional buffering. Files accept path-like objects;
64-bit Unix descriptors support `closefd` and checked alias closure. Binary
`write`, `readinto`, and `readinto1` use contiguous buffer exports, including
Python exporters, typed views, and writable multidimensional views. Export
leases remain live through the I/O operation and release callbacks. Text
files support UTF-8, ASCII, Latin-1, newline translation, `reconfigure`, and
opaque seek cookies that restore pending decoder and newline state.
Descriptor/opener behavior is currently verified on 64-bit Linux.

Unicode `str` `%` formatting supports mapping keys, flags, dynamic width and
precision, numeric conversions, `s`/`r`/`a`, and Unicode characters. String
precision and width count Unicode characters. Python conversion and mapping
callbacks use caller-owned heap continuations. Displaying a float with `%d`
uses exact internal truncation, independently of the selected user integer width.
Unpaired surrogate character results remain explicitly unsupported.

Binary `%` formatting supports bytes, bytearray, mapping keys, flags, dynamic
width and precision, integer and float conversions, and bytes/repr protocols.
Formatting keeps a bytearray format exported while callbacks run; equal-length
changes affect later directives, and an attempted resize raises `BufferError`.

Set iteration order is not guaranteed to match CPython's internal hash-table order.

Python 3.14 patch releases differ in a few observable metadata details. Fixed,
trusted probes select the converter host's t-string expression whitespace,
annotation-function qualified names, and ExceptionGroup representation behavior.
The generated runtime embeds that profile and uses it for dynamic compilation
as well as ordinary source. Input programs are not executed by these probes.

Non-raw string literals, f-strings, and t-strings support Unicode 16.0 character names
and all 477 formal name aliases in `\N{name}` escapes, including Hangul and algorithmic names.
Named character sequences are not accepted in literal escapes, matching Python.
Raw strings and bytes literals retain their normal escape behavior.

## Standard modules

| Module | Scope |
|---|---|
| `math` | All Python 3.14 public functions and `pi`/`e`/`tau`/`inf`/`nan` |
| `heapq` | CPython's pure-Python implementation, including the public max-heap APIs |
| `bisect` | CPython's pure-Python implementation, including `key` and `lo`/`hi` |
| `itertools` | Public APIs with lazy execution, including infinite iterators, `tee`, and `groupby` |
| `functools` | Public APIs, including `cache`/`lru_cache`, `partial`, decorators, dispatch, and `cached_property` |
| `collections` | `deque`, `defaultdict`, `Counter`, `namedtuple`, `OrderedDict` |
| `sys` | Standard streams, `argv`, `exit`, recursion limits, `exception`/`exc_info` |
| `gc` | Runtime GC controls, including `collect` |

The floating-point special functions in `math` undergo accuracy tests,
but are not guaranteed to match the operating system's or CPython's `libm` results bit for bit.

Bundled pure-Python modules must themselves use supported syntax, built-ins, and modules.
See [API_SUPPORT.md](API_SUPPORT.md) for individual API names.

## Known limitations

- `async`/`await` are unsupported.
- Some basic-value behavior, including unpaired Unicode surrogates, remains unsupported.
- File I/O still lacks Python-defined raw/buffer adapters, in-memory `io` streams, nonblocking descriptor semantics, and complete native I/O subclass/descriptor APIs.
- Encoding conversion covers UTF-8, ASCII, and Latin-1, with limitations on supported `errors` modes. String subclasses use the same decoding and buffer rules as `str`, including explicit `str.__new__` calls.
- Runtime syntax validation and instruction generation use the syntax tree from a PEG generated from the official grammar. Execution of some syntax, including async constructs, remains unsupported.
- Not all `annotationlib` formats or `typing` APIs are implemented. TypeVar, ParamSpec, TypeVarTuple, type aliases, GenericAlias parameter substitution, and union types are provided.
- AST input/output for `compile()`, top-level await, and incomplete-input flags are unsupported.
- Imports whose names are determined at runtime, external C extensions, networking, threads, `asyncio`, and CPython-specific internal APIs are out of scope.
- Unlisted standard-module APIs, including `inspect`, `pickle`, and `weakref`, are not provided.
- In one CPython 3.14.4 bug case, a captured comprehension iteration variable shadows a free variable of the enclosing function and the interpreter retains the new cell. Generated code instead restores the original enclosing cell as [PEP 709](https://peps.python.org/pep-0709/) specifies. AST and dynamic compilation agree on that restoration.
- Invalid stale text-decoder snapshots raise `OSError` before changing the stream. CPython 3.14.4 can access beyond an empty snapshot after a seek/iteration/flush sequence; its unstable release-build results are not reproduced.
- A traceback's `tb_frame` is a snapshot containing source information. It does not expose live-frame manipulation or CPython bytecode offsets.
- Direct generation for dynamic functions and classes is unfinished. The public API reports `E006` instead of selecting the retained runtime.
- Superseded container storage in native code can remain until the enclosing Rust scope ends. Peak memory may exceed that of the equivalent Python program.

Unsupported syntax and modules produce transpilation diagnostics.
Unsupported dynamic operations produce runtime exceptions with original source locations.

## Integer modes

`i64` and `i128` normalize integer values and arithmetic results to the selected width.
For example, `2**63` is `-2**63` in `i64` mode.
This overflow behavior differs from CPython's arbitrary-precision integers.
BigInt mode uses arbitrary-precision integers.

Negative `//` and `%`, modular powers with negative exponents, negative bitwise operations,
large shifts, and comparisons between integers and floats have dedicated handling.
Lengths, indices, allocation sizes, and range progression are checked separately from user integer arithmetic.
Opaque text seek cookies preserve their complete structural decoder state in every integer mode.
Arithmetic or explicit integer conversion applied to a cookie still follows the selected integer normalization policy.

Integers provide `to_bytes`, `from_bytes`, `as_integer_ratio`, and `is_integer`.
Floating-point values provide `hex`, `fromhex`, `from_number`, `as_integer_ratio`, and `is_integer`.
Integer results from these methods follow the selected integer normalization policy;
internal calculations for binary64 conversion retain the precision needed for correct rounding.
Float floor division, remainder, and `divmod` share sign and quotient correction,
including signed zero and values close to an integral quotient.

Existing code objects can be executed with `exec(code, globals, locals, closure=cells)`.
The exact tuple of cells must match `co_freevars`; `eval` rejects code with free variables.
`types.CellType`, `types.FunctionType`, and `types.LambdaType` support constructing shared closures.
Replacing `function.__code__` checks the free-variable count and preserves closure cells by position.
