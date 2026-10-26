# Compatibility

The language target is Python 3.14. The following tables describe implemented features;
they do not imply compatibility with all CPython internals or the entire standard library.

## Language and runtime features

| Category | Supported features |
|---|---|
| Values | `None`, `bool`, integers in the selected mode, `float`, `complex`, `str`, `bytes`, `list`, `tuple`, `dict`, `set`, `frozenset`, `slice`, `range`, live dictionary views and `mappingproxy`, GenericAlias, union types, Template, Interpolation |
| Variables | Type changes, shared references, chained and unpacking assignments, `global`/`nonlocal`, unbound-name errors |
| Control flow | `if`, `while`, `for`, `break`/`continue`, loop `else`, short-circuit operators, chained comparisons |
| Functions | Defaults, positional-only and keyword-only arguments, variadic arguments, recursion, lambdas, closures, type parameters with lazy bounds and defaults |
| Container expressions | Comprehensions, generator expressions, unpacking, negative indices, slicing |
| Exceptions | `raise`, `except`, `except*`, exception-group splitting and merging, `else`, `finally`, `assert`, original `args`, cause/context/notes, exception-target cleanup, source information in tracebacks |
| Classes | Inheritance, C3 MRO, descriptors, `property`, `staticmethod`/`classmethod`, `super`, metaclasses, `__slots__`, subclasses of `list`/`tuple`/`dict`/`set`/`frozenset`/`str`/`int`/`complex` |
| Namespaces | `__prepare__` returning custom mappings, private names, Unicode NFKC identifiers, dictionary insertion order, separate internal temporaries, Python 3.14 function-local snapshots including free variables |
| Other constructs | `with`, generator `send`/`throw`/`close` and `yield from`, f-strings, t-strings, `match`/`case` |
| Dynamic execution | `compile`/`eval`/`exec`, `compile(optimize=0/1/2)`, calls between static and dynamic code, lazy annotations and `type` statements, all known `__future__` features and flag inheritance |
| Memory | Object identity, cyclic references, mark-and-sweep GC rooted in frames and temporary values, `__del__` and resurrection |

Ordinary function recursion, including calls through `cache` and `lru_cache`, uses heap-allocated frames.
Some calls made through protocols and built-ins still reenter the runtime through Rust calls.

`frozenset` supports construction, hashing, iteration, membership, comparisons, read-only set methods,
mixed operations with `set`, subclasses, and GenericAlias.
Member hashes and the final frozenset hash are retained; operations that copy a set's contents reuse stored member hashes.
Set iteration order is not guaranteed to match CPython's internal hash-table order.

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
- `bytearray`, `memoryview`, and file I/O through `open` are unsupported. Standard streams provide text and binary I/O.
- Encoding conversion covers UTF-8, ASCII, and Latin-1, with limitations on supported `errors` modes. Constructing a `str` subclass with an encoding is unsupported.
- Runtime syntax validation and instruction generation use the syntax tree from a PEG generated from the official grammar. Execution of some syntax, including async constructs, remains unsupported.
- Not all `annotationlib` formats or `typing` APIs are implemented. TypeVar, ParamSpec, TypeVarTuple, type aliases, GenericAlias parameter substitution, and union types are provided.
- AST input/output for `compile()`, top-level await, and incomplete-input flags are unsupported.
- Executing existing code objects with explicit closure cells is unsupported. Closures created by ordinary and dynamically compiled source are supported.
- Module namespace dictionaries still have limitations for non-string keys and string-subclass key protocols during global name resolution.
- Imports whose names are determined at runtime, external C extensions, networking, threads, `asyncio`, and CPython-specific internal APIs are out of scope.
- Unlisted standard-module APIs, including `inspect`, `pickle`, and `weakref`, are not provided.
- Compatibility differences remain in `namedtuple` caller-module inference, the representation of empty function defaults, and base-descriptor operations on dictionary subclasses.
- Comprehensions run in separate frames, so `locals()` called within them may differ from Python 3.14's inlined comprehensions.
- A traceback's `tb_frame` is a snapshot containing source information. It does not expose live-frame manipulation or CPython bytecode offsets.
- Native specialization of code containing dynamic functions and classes is limited; such code may use the general runtime.
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
