# Standard-library API support

This is the inventory of API implementations retained in the internal runtime.
It is not the current public direct-Rust support list. The CLI and `transpile()`
never select that runtime after direct lowering fails. A listed API without
direct Rust lowering produces a positioned `E006` diagnostic.

Restoring the required module APIs through direct generation remains unfinished
work. The implementations and their acceptance tests are retained; this
inventory and strict diagnostics do not establish completed compatibility or a
green full suite. See [COMPATIBILITY.md](COMPATIBILITY.md) for the public boundary.

Current direct module coverage includes proved immutable scalar and tuple
elements in `collections.deque` in all integer modes, with bounded queues and
the named methods described in
[COMPATIBILITY.md](COMPATIBILITY.md), plus
`sys.stdin`/`sys.stdin.buffer` `read`/`readline`, including statically captured
reader aliases and local imports. This does not establish direct coverage of
the other `sys` APIs listed in the retained inventory below.
Linked module references also adapt `sys.setrecursionlimit` and
`sys.getrecursionlimit`, including saved references. Replacing the standard
stream objects requires an unimplemented stream-object protocol and is rejected.

The direct linker bundles fixed-name user modules, packages and automatically
resolved `atcoder` source modules while retaining each original AST and scope.
An imported API compiles only when its own operations have direct lowering.
The original bundled `atcoder.fenwicktree.FenwickTree` constructor, `add` and
`sum`, `atcoder.scc.SCCGraph` construction/edge insertion/components, and
`atcoder.twosat.TwoSAT` construction/clauses/satisfiability/answers have standalone
differential execution coverage in all integer modes.
The unchanged bundled `atcoder.math` caller for `pow_mod`, `inv_mod`, `crt`, and
`floor_sum` also has standalone smoke coverage in all integer modes. This does
not establish exhaustive numerical coverage of those APIs.
Unchanged callers using `atcoder.dsu.DSU`, `atcoder.segtree.SegTree`, and
`atcoder.lazysegtree.LazySegTree` now also pass standalone differential smoke
checks in every integer mode, including callbacks and indexed operations.
These callers are not exhaustive coverage of each API's inputs or callbacks.
Other ACL APIs still encounter required core-language and builtin gaps; bundled
source availability is not evidence that those APIs are implemented.

F-strings and canonical builtin `format`, `repr`, and `ascii` calls have direct
frame lowering for supported native values, including captured aliases.
Integer, binary64, and string fields support alignment, width, grouping,
precision, and the supported standard presentation codes. Dynamic format specs,
debug fields, `!s`/`!r`/`!a`, and field/spec evaluation order use the original
Python AST. Plain fields emit only the needed display helpers. Source-defined
format/display methods, complex values, and string `format`/`format_map` methods
still require their own direct protocols.

Canonical `ord`, `bin`, `oct`, and `hex` calls have direct native lowering,
including saved aliases, callback arguments and class fields. `ord` accepts
single-character strings and single-byte bytes. Radix calls accept integers and
booleans, including signed minima and BigInt magnitudes. Custom `__index__`
objects and `chr` still require their native protocols.

Explicit-base `int(text, base)` and `int(text, base=...)` calls have direct
lowering for builtin strings and bytes, including saved aliases, class fields
and multi-source `map` callbacks. Bases 0 and 2 through 36 support signs,
prefixes and underscores; invalid bases and literals retain Python errors.
Fixed-width results wrap at the selected width. ASCII parsing scans bytes;
Unicode mode uses the pinned decimal-digit and whitespace tables. Custom base
`__index__` objects, bytearray/buffer storage and CPython conversion
digit limits remain unfinished.

Builtin `divmod` supports captured integral/boolean calls in every integer mode,
binary64 pairs in every mode, and mixed integer/binary64 calls in fixed-width
modes. It shares quotient/remainder kernels with the arithmetic operators.
Mixed BigInt/binary64 and custom operand special methods remain unfinished.

Builtin `pow` has direct captured/frame lowering for integral three-argument
calls, including modular inverses, signed moduli and keyword binding. Supported
two-argument integral calls require a proved nonnegative literal exponent.
Dynamic/negative two-argument and floating/complex power protocols remain
unfinished; see [COMPATIBILITY.md](COMPATIBILITY.md).

Resolved integer calls to `math.gcd`, `lcm`, `isqrt`, `factorial`, `comb`, and
`perm` also have direct helpers. The following list APIs have direct typed
lowering with the payload, storage and evaluation-order limits documented in
[COMPATIBILITY.md](COMPATIBILITY.md):

| Module | Direct APIs | Remaining requirements |
|---|---|---|
| `heapq` | `heapify`, `heappush`, `heappop`, `heappushpop`, `heapreplace`, and all five `_max` counterparts | `merge`, `nlargest`, `nsmallest`, custom/fallible comparisons, floating tuple identity |
| `bisect` | `bisect`, `bisect_left`, `bisect_right`, `insort`, `insort_left`, `insort_right` with checked bounds and `key=None` | Callable keys, arbitrary sequence protocols, custom/fallible comparisons |

Canonical heap/bisection imports also work in typed class, closure and linked
module frames, including saved member aliases and shared list fields. Ordinary
vector-only programs keep their direct path. Bare float heaps work in all integer
modes; mixed BigInt/float ordering still requires implementation. Frame bisection
retains keyword evaluation order, checked bounds and per-visited-element builtin
ordering errors. Custom index/key/sequence/ordering protocols and native-member
starred calls remain positioned diagnostics.

The frame path also stores typed `iter`, `filter`, multi-source `map` and `zip`
objects, including the `strict` keyword, captured callbacks, shared cursor
aliases, and list/reduction consumers. Builtin list, fixed tuple, range, text
and byte sources have adapters. Custom iteration protocols and cyclic ownership
still require implementation; this does not establish complete builtin object
compatibility.

Frame `str.split`/`rsplit` and `bytes.split`/`rsplit` accept optional `sep` and
`maxsplit`, including keywords, `None` whitespace splitting and checked signed
index-size bounds. Borrowed cursors preserve receiver/argument evaluation order
and materialize one shared typed list. ASCII uses byte whitespace scans; Unicode
uses character boundaries, while bytes retain their separate whitespace set.
Custom `__index__` and bytes-buffer objects still require protocol adapters.

Frame `str`/`bytes` `strip`, `lstrip` and `rstrip` accept optional character sets
or `None`, including ordinary `readline().rstrip("\n")` and binary line readers.
They preserve receiver/argument order, Unicode versus bytes whitespace, and
positioned argument errors. Custom bytes-buffer objects need their own adapter.

Frame `str.replace` and `bytes.replace` support old/new values and optional
counts, including empty patterns, Unicode character boundaries, exact argument
errors and captured evaluation order. Text accepts the `count` keyword; bytes
keeps its positional-only signature. Byte matching uses a linear prefix-table
algorithm, with checked output sizes and no intermediate match-position list.

Frame text/bytes `find`, `rfind`, `index` and `rindex` support optional clipped
start/end bounds, empty patterns and integer byte needles. Unicode results use
code-point indices through the existing cached boundary table; ASCII uses byte
offsets. Byte searches use linear forward/reverse prefix matching and stop at
the first match in the requested direction.

Frame `str.count` and `bytes.count` support nonoverlapping occurrences, optional
clipped start/end bounds, empty patterns and integer byte needles. Counts reuse
cached Unicode windows or ASCII byte scans; multi-byte patterns use a linear
prefix matcher. Existing simple text-count and input-parsing paths remain static.

Typed frame `for` loops accept raw text and bytes through shared source cursors,
including finite source alternatives and `enumerate`. Text yields characters
in the configured ASCII/Unicode mode; bytes yield integers. Captured immutable
owners survive local or field rebinding during the loop. Ordinary static text
loops retain their existing path.

Typed frame dictionaries and sets have shared native storage, including
ordinary mutable aliases, dictionary values and class fields. Direct adapters
cover literals/comprehensions, `dict`/`set` constructors, dictionary subscripts,
`get`, `setdefault`, shallow `copy`, set `add`, length/truth/membership and
order-insensitive `sorted` set consumption. Live dictionary `keys`/`items`/
`values` views and checked shared cursors support iteration and the same
materialization/reduction consumers, including `tuple(iterable)`. Key families
and the remaining deletion, view-operation and custom-protocol limits are documented in
[COMPATIBILITY.md](COMPATIBILITY.md).

Canonical `collections.deque` constructors have a shared typed frame carrier for
function arguments/results, class fields and mutable aliases. Constructor
iterables/bounds, append/appendleft, pop/popleft, clear/copy, len/bool, maxlen,
identity, integer-indexed reads/writes/deletion and display are supported.
Augmented indexed assignment captures its owner/index once, loads before the RHS,
and checks the original index against the current deque when storing. Mutable
child handles survive shallow copy. Live forward cursors support `iter`,
collection/reduction consumers, `map`/`filter`/`zip`, comprehensions and source
unions. `extend`/`extendleft` preserve argument effects and snapshot an actual
self-extension; a saved iterator over the receiver stays live. Structural mutation
raises `RuntimeError` during iteration; indexed replacement stays visible.
Reversed cursors, search/ordering, saved builtin method aliases and custom index
conversion still require adapters. Ordinary unique-owner paths remain available.

Canonical `collections.Counter` imports have a typed frame adapter, including
saved constructor aliases, integer-count iterable/mapping constructors, missing
zero reads, `get`, `copy`, `update`, `subtract`, `most_common`, `total`, and live
mapping views. `isinstance` recognizes the Counter class and its dict base.
`most_common(n)` uses a bounded native heap; it does not sort the whole mapping
for small or nonpositive limits. Counter arithmetic, `elements`, general count
objects remain unfinished. See
[COMPATIBILITY.md](COMPATIBILITY.md) for admitted keys and exact boundaries.

Canonical `collections.defaultdict` imports use the same typed mapping storage.
Factories can be builtin `int`/`list`/`set` identities or captured compiled
functions, lambdas and bound methods with a proved zero-argument call. Missing
indexing calls the current `default_factory`; `get` and `setdefault` keep their
ordinary dictionary behavior. Factory mutation, shallow copies, shared values,
live views, class fields, and typed initial mappings/pairs are supported.
Nonescaping generator expressions can supply initial pairs without an
intermediate list. General callable objects, subclass protocols and ownership
cycles remain diagnosed.

Module/function aliases use resolved identities. Positional `*` call expansion
supports compiled source functions and `print`, including nonescaping generator
expressions and shared dictionary views. Expansion into other native builtins,
module functions and constructors, and `**` mappings still need their adapters.
The tables below describe the retained runtime inventory, not additional direct
coverage.

## math

| API | Status |
|---|---|
| `acos` | Implemented |
| `acosh` | Implemented |
| `asin` | Implemented |
| `asinh` | Implemented |
| `atan` | Implemented |
| `atan2` | Implemented |
| `atanh` | Implemented |
| `cbrt` | Implemented |
| `ceil` | Implemented |
| `comb` | Implemented |
| `copysign` | Implemented |
| `cos` | Implemented |
| `cosh` | Implemented |
| `degrees` | Implemented |
| `dist` | Implemented |
| `e` | Implemented |
| `erf` | Implemented |
| `erfc` | Implemented |
| `exp` | Implemented |
| `exp2` | Implemented |
| `expm1` | Implemented |
| `fabs` | Implemented |
| `factorial` | Implemented |
| `floor` | Implemented |
| `fma` | Implemented |
| `fmod` | Implemented |
| `frexp` | Implemented |
| `fsum` | Implemented |
| `gamma` | Implemented |
| `gcd` | Implemented |
| `hypot` | Implemented |
| `inf` | Implemented |
| `isclose` | Implemented |
| `isfinite` | Implemented |
| `isinf` | Implemented |
| `isnan` | Implemented |
| `isqrt` | Implemented |
| `lcm` | Implemented |
| `ldexp` | Implemented |
| `lgamma` | Implemented |
| `log` | Implemented |
| `log10` | Implemented |
| `log1p` | Implemented |
| `log2` | Implemented |
| `modf` | Implemented |
| `nan` | Implemented |
| `nextafter` | Implemented |
| `perm` | Implemented |
| `pi` | Implemented |
| `pow` | Implemented |
| `prod` | Implemented |
| `radians` | Implemented |
| `remainder` | Implemented |
| `sin` | Implemented |
| `sinh` | Implemented |
| `sqrt` | Implemented |
| `sumprod` | Implemented |
| `tan` | Implemented |
| `tanh` | Implemented |
| `tau` | Implemented |
| `trunc` | Implemented |
| `ulp` | Implemented |

## heapq

| API | Status |
|---|---|
| `heapify` | Implemented |
| `heapify_max` | Implemented |
| `heappop` | Implemented |
| `heappop_max` | Implemented |
| `heappush` | Implemented |
| `heappush_max` | Implemented |
| `heappushpop` | Implemented |
| `heappushpop_max` | Implemented |
| `heapreplace` | Implemented |
| `heapreplace_max` | Implemented |
| `merge` | Implemented |
| `nlargest` | Implemented |
| `nsmallest` | Implemented |

## bisect

| API | Status |
|---|---|
| `bisect` | Implemented |
| `bisect_left` | Implemented |
| `bisect_right` | Implemented |
| `insort` | Implemented |
| `insort_left` | Implemented |
| `insort_right` | Implemented |

## itertools

Direct typed frames currently adapt canonical `repeat`, `chain`, `islice`,
`pairwise`, `accumulate`, `product`, `combinations`, `permutations`, and
`combinations_with_replacement`, including saved aliases, lazy consumption, shared mutable values,
loop/comprehension consumers and their builtin class-info queries. `chain`
defers acquisition of each input iterator until it is reached; `chain.from_iterable`
and the other entries in the retained inventory below still need direct adapters.

| API | Status |
|---|---|
| `accumulate` | Implemented |
| `batched` | Implemented |
| `chain` | Implemented |
| `combinations` | Implemented |
| `combinations_with_replacement` | Implemented |
| `compress` | Implemented |
| `count` | Implemented |
| `cycle` | Implemented |
| `dropwhile` | Implemented |
| `filterfalse` | Implemented |
| `groupby` | Implemented |
| `islice` | Implemented |
| `pairwise` | Implemented |
| `permutations` | Implemented |
| `product` | Implemented |
| `repeat` | Implemented |
| `starmap` | Implemented |
| `takewhile` | Implemented |
| `tee` | Implemented |
| `zip_longest` | Implemented |

## functools

| API | Status |
|---|---|
| `Placeholder` | Implemented |
| `WRAPPER_ASSIGNMENTS` | Implemented |
| `WRAPPER_UPDATES` | Implemented |
| `cache` | Implemented |
| `cached_property` | Implemented |
| `cmp_to_key` | Implemented |
| `lru_cache` | Implemented |
| `partial` | Implemented |
| `partialmethod` | Implemented |
| `reduce` | Implemented |
| `singledispatch` | Implemented |
| `singledispatchmethod` | Implemented |
| `total_ordering` | Implemented |
| `update_wrapper` | Implemented |
| `wraps` | Implemented |

`functools.singledispatch` and `singledispatchmethod` support class and union-type registrations.
Integration with ABCs from unsupported modules is limited.
The special functions in `math` do not always match CPython's `libm` results bit for bit.

## collections

| Type or factory | Public APIs |
|---|---|
| `deque` | append, appendleft, clear, copy, count, extend, extendleft, index, insert, pop, popleft, remove, reverse, rotate, maxlen |
| `defaultdict` | Dictionary operations, `default_factory`, `copy`, `fromkeys` |
| `Counter` | Dictionary operations, `elements`, `most_common`, `subtract`, `total`, `update`, arithmetic, set operations, comparisons |
| `namedtuple` | defaults/module/rename, _fields, _field_defaults, _make, _asdict, _replace, __match_args__ |
| `OrderedDict` | Dictionary operations, `move_to_end`, `popitem(last=...)`, order-sensitive comparisons between OrderedDict instances |

`Counter.fromkeys` raises `NotImplementedError`, as it does in CPython.
`ChainMap`, `UserDict`, `UserList`, and `UserString` are not included.

## sys

| API | Status |
|---|---|
| `stdin`, `stdout`, `stderr` | Mutable standard streams; text/binary-buffer I/O, `fileno`, `isatty`, text `encoding`/`errors` |
| `argv` | Arguments passed to the executable |
| `exit` | Raises `SystemExit` |
| `setrecursionlimit`, `getrecursionlimit` | Set and retrieve the recursion limit |
| `exception`, `exc_info` | The active exception, including `except*` subgroups, inheritance across function calls, and generator suspension/resumption |

Unlisted `sys` APIs are unsupported.

## Additional modules

| Module | Supported features |
|---|---|
| `__future__` | All known features, `compiler_flag`, release metadata, validation of future-statement placement, inheritance in `compile`/`eval`/`exec` |
| `types.GenericAlias` | Origin/args/parameters metadata, comparisons, hashing, calls, `__class_getitem__`, MRO integration, TypeVar/ParamSpec/TypeVarTuple substitution and defaults |
| `types.UnionType` | The same type as `typing.Union` in Python 3.14 |
| `string.templatelib` | `Template`, `Interpolation`, `convert`; t-string values, expression text, conversion, and `format_spec` are retained for consumers to format |
| `typing` | `TypeVar`, `ParamSpec`, `TypeVarTuple`, `TypeAliasType`, `Generic`, `Unpack`, `Union`, `ForwardRef`, `NoDefault`, `ParamSpecArgs`/`ParamSpecKwargs`, `get_args`/`get_origin`; the whole module is not supported |

Typed frame sorting supports `sorted(iterable, *, key=None, reverse=False)` and exact builtin `list.sort(*, key=None, reverse=False)` with captured source functions, closures, lambdas, builtin adapters and bound source methods as keys. Keys run once per input element before ordering; reverse sorting remains stable. Integer/boolean, text/bytes, and finite tuple/list key shapes use native comparisons while retaining element references. Floating NaN ordering and custom rich-comparison protocols remain required unfinished work.

Canonical eager native-member capabilities also admit original generator
expressions to `Counter` construction and its sealed `update`/`subtract` methods.
The shared generator collector writes directly into count storage; it preserves
argument order, body frames, PEP 479 and dictionary mutation checks without an
intermediate list. Saved generators, lazy adapters and arbitrary user methods
still require general suspension state.

`itertools.product` captures its input pools at construction and emits results
from concrete pool/index state. Runtime `repeat`, zero dimensions, mutable
element aliases and eager generator inputs are supported. Small proved ranks
retain Rust tuple field types; other ranks use typed immutable tuple storage.
General stored generators still require suspension state.

`combinations`, `permutations`, and `combinations_with_replacement` also capture
one immutable input pool at construction and emit tuples lazily from native
indices/cycles. They support positional/keyword arguments, dynamic `r`, the
permutation default/None rank, mutable item identity, source errors, shared
partial consumption, generator pools, and runtime-rank tuple unpacking. Rank
conversion and pool consumption retain each API's Python ordering.
The eager-member capability registry also recognizes admitted keyword iterable
arguments; unrelated user/lazy calls do not gain eager generator admission.

Typed frame `enumerate` values now have shared concrete cursor state, including
source aliases, keyword starts, returned iterators, generic `zip`/sorting/extrema
consumers and class-info queries. Source pulls precede index advancement, so
reentrant pulls and transient source exhaustion retain Python ordering. Index
values use the selected integer policy; stored generator sources still require
general suspension state. Existing ordinary immediate for/comprehension forms
retain their direct lowering.

### Shared reverse iteration

`reversed()` uses registered native cursors for shared deques, lists, fixed tuples,
variadic tuples, strings, bytes, and ranges. Cursors share their position through
aliases. List cursors retain their original endpoint and observe replacement and
shrink operations; exhausted cursors stay exhausted. Unicode mode walks backward
by codepoint, while ASCII mode uses byte positions. Range reversal computes the
last element directly without materializing values or requiring a machine-sized
length. Fixed-width endpoint calculations preserve the selected integer policy.

Shared `deque.rotate()` and `deque.reverse()` keep object identity. Rotation of a
deque with at least two elements invalidates live cursors, including a rotation
by zero. Reversal changes the values seen by existing cursors without invalidating
them. A reverse deque cursor checks mutations while active and stays exhausted
after its last item, matching Python's distinct forward/reverse cursor rules.
Custom `__reversed__`, sequence fallback methods, and user `__index__` adapters
remain explicit conversion boundaries.
