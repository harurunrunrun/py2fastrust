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

Immediate integer-map consumers of canonical zero-argument text/binary
`readline()` reuse the buffered line through parsing and preserve raw-byte,
newline, EOF and error order. Proved reader aliases share this path. Stored
maps and callbacks keep their owned input snapshots; sized reads keep their
existing adapters. No input view escapes, and `readline()` still does not flush
pending output implicitly.

Source functions using statement `yield` can supply typed native iterators to
ordinary consumers. Creation defers the body, arguments/defaults are captured
once, globals remain live at pulls, and aliases share the suspended cursor.
Builtin-container/numeric frame storage and structured native loops are
supported. Delegation, injected resumption/cleanup, lexical captures, opaque
retained payloads and recursive resume regions remain explicit diagnostics;
this is not full generator-protocol coverage.

Direct source `__iter__` methods returning registered native cursors serve
builtin consumers, comprehensions, unpacking and supported collection/iterator
constructors. Their cursor identity, sharing and evaluation order are retained.
Owned source-instance generator captures are supported with lifetime checks;
manual `__next__`, alternate descriptors and unsafe captures remain diagnostics.
Fixed-target unpacking of finite builtin list/tuple alternatives uses an exact
length check and Rust local snapshots, releasing temporary list leases before
target stores and retaining shared mutable elements without iterator allocation.

Proved bounded primitive remainders in i128 mode can use i64 remainder
instructions while retaining the selected integer policy and both operand
evaluations. Exact pre-modulo bounds are required; guards invalidated by
assignments/callbacks and unproved or wider values retain native i128 arithmetic.

Source `__str__`/`__repr__` methods and plain same-class aliases have native
callback paths for printing, string/repr conversion and supported formatting.
Argument evaluation, partial output, mutation and errors keep Python ordering;
list/dynamic-tuple display releases borrows around callbacks and guards repr
recursion. Unsupported publication/descriptor cases, custom mapping/deque repr
callbacks and recursive tuples lacking stable identity remain diagnostics.

Direct source `__contains__` methods support `in`/`not in`, including builtin
truth-valued returns, callback effects and chained comparisons. Nonfunction or
replaced slots, implicit iteration fallback and unconnected instance-result
truth protocols produce positioned diagnostics. `NotImplemented` results retain
Python 3.14's truth-conversion `TypeError`.


Ordinary source `__getitem__` and `__setitem__` methods support indexed reads,
stores and augmented assignments through direct typed callbacks. Receivers and
keys are evaluated once; augmented assignment captures the original getter
value before the right operand, then stores through the original receiver and
key. Shared returned rows retain alias identity. Unsupported descriptors,
replaced slots, custom slice keys and deletion retain positioned diagnostics.


Canonical `bytes()` and `bytes(count)` use checked native allocation; a bytes
source retains its immutable value. Constructor aliases use the same binding
proof. All arguments run before count/type errors, and counts are checked
against the target index width before negative-count rejection. Text encodings,
keyword arguments, iterable sources and custom conversion protocols remain
specific diagnostics.

Typed source frames support captured canonical stdin readers at deferred
callable sites, optional positional sizes and `from sys import stdin` aliases.
Size checks precede blocking reads. Binary reads retain raw bytes, and default
or closed literal UTF-8 `bytes.decode` calls can produce native text. Reader
keyword/invalid-arity call errors, custom size `__index__`, other codecs/error
handlers and some exception-only frame-selection cases remain positioned
diagnostics.

Typed source-class namespaces support ordinary nested classes and scalar/list
class data, including aliases, rebinding, deletion and instance-field precedence.
They retain the original scope owners and captured defining-module references.
Method descriptor replacement, arbitrary class metadata and metaclass protocols
remain explicit boundaries; see [COMPATIBILITY.md](COMPATIBILITY.md).

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
All 15 executable [upstream examples](https://github.com/not522/ac-library-python/tree/27fdbb71cd0d566bdeb12746db59c9d908c6b5d5/example)
also have standalone Rust execution coverage in every integer mode, including
both convolution examples, Modint, maximum flow, minimum-cost flow and suffix
arrays. Their original sources are imported without edits. This establishes
example coverage; other API inputs and callbacks can still need additional
core-language protocols. The integer convolution example uses CRT intermediates
wider than i64: i64 follows per-operation wrapping, while i128 and BigInt retain
the Python result for the tested inputs.

F-strings and canonical builtin `format`, `repr`, and `ascii` calls have direct
frame lowering for supported native values, including captured aliases.
Integer, binary64, and string fields support alignment, width, grouping,
precision, and the supported standard presentation codes. Dynamic format specs,
debug fields, `!s`/`!r`/`!a`, and field/spec evaluation order use the original
Python AST. Plain fields emit only the needed display helpers. Source-defined
format/display methods, complex values, dynamic string format templates and
`str.format_map` still require their own direct protocols.

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
two-argument integral calls accept dynamic and negative exponents. Nonnegative
exponents return integers; negative exponents return binary64 values, including
zero-to-negative and integer-to-float overflow errors. Binary64 bases with
integral exponents return binary64 and preserve overflow and signed-zero behavior.
Floating exponents accept builtin int/bool/float bases and return a finite
binary64/complex alternative. Print, string/repr conversion, truth testing and
int/float conversion errors observe the actual result. Complex arithmetic,
comparison and nonempty numeric formatting remain positioned boundaries; see
[COMPATIBILITY.md](COMPATIBILITY.md).

Resolved integer calls to `math.gcd`, `lcm`, `isqrt`, `factorial`, `comb`, and
`perm` also have direct helpers. The following list APIs have direct typed
lowering with the payload, storage and evaluation-order limits documented in
[COMPATIBILITY.md](COMPATIBILITY.md):

Builtin `list.insert` and `list.remove` also share the owned/shared sequence
lowering. Both preserve receiver and argument order; insertion checks signed
indices and allocation size, while removal uses existing equality adapters and
reports the missing-element `ValueError`. Custom equality/index protocols,
floating-object identity and cyclic ownership remain explicit boundaries.

| Module | Direct APIs | Remaining requirements |
|---|---|---|
| `heapq` | `heapify`, `heappush`, `heappop`, `heappushpop`, `heapreplace`, and all five `_max` counterparts; `nlargest`/`nsmallest` with captured keys | `merge`, custom rich comparisons, floating decorated tuple identity |
| `bisect` | `bisect`, `bisect_left`, `bisect_right`, `insort`, `insort_left`, `insort_right` with checked bounds and captured `key` callbacks | Arbitrary sequence protocols, custom/fallible comparisons |

Canonical heap/bisection imports also work in typed class, closure and linked
module frames, including saved member aliases and shared list fields. Ordinary
vector-only programs keep their direct path. Bare float heaps work in all integer
modes; mixed BigInt/float ordering still requires implementation. Frame bisection
retains keyword evaluation order, checked bounds and per-visited-element builtin
ordering errors. Keys may be captured source functions, closures, lambdas, builtin adapters or
bound source methods. Search transforms only visited existing elements; insertion
computes the new item key once, then retains the original inserted object.
Callbacks run without a list borrow and preserve live element mutations.
Custom index/sequence/ordering protocols and native-member
starred calls remain positioned diagnostics.

`nlargest` and `nsmallest` retain O(k) scored entries for bounded selection and
use O(n log k) work, followed by ordering at most k retained entries. Count one
uses a live source; a count at least a proved builtin length snapshots input
before calling keys. Source functions, closures, lambdas, builtin references and
bound methods preserve callback order and original mutable payload identities.
Counts currently require builtin integers/bools; floating/custom count and
identity-aware floating key comparisons remain positioned diagnostics.

The frame path also stores typed `iter`, `filter`, multi-source `map` and `zip`
objects, including the `strict` keyword, captured callbacks, shared cursor
aliases, and list/reduction consumers. Builtin list, fixed tuple, range, text
and byte sources have adapters. Custom iteration protocols and cyclic ownership
still require implementation; this does not establish complete builtin object
compatibility.

After type/call analysis proves canonical `int`, a direct `map` source from
builtin text/bytes `split` or `rsplit` retains the immutable input and an eager
word-position snapshot. Pulls parse borrowed word slices, avoiding per-word
string allocations while preserving delayed conversion errors and shared map
cursors. Captured callback aliases, separator/maxsplit effects and Unicode
character boundaries retain their ordinary semantics. Saved mutable word lists
use their live list cursor. Ordinary integer-word collectors report the original
invalid literal with its base and Python representation through a cold error
path.

Immediate frame `list(map(int, ...))`, captured canonical `list` aliases and
checked unpacking share the borrowed word collector. Final lists receive parsed
integers directly. Unpacking converts the extra item before reporting excess
values and completes all checks before storing targets. Invalid literal displays
use Python's 200-character representation limit, and errors from multiline
consumers retain the consumer's original source location.

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

Frame `str`/`bytes` `startswith` and `endswith` support clipped positional
bounds, individual patterns and fixed or runtime tuples of patterns. Tuple
matching stops at the first match, including lazy errors for later invalid
members. Queries borrow the selected native window without copying its text.

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

Canonical `reduce` calls have direct native folds with captured callbacks,
positional/keyword `initial`, empty/single input behavior, mutable accumulator
identity, shared iterator sources, and direct eager generator sinks. Missing
initial values remain distinct from an explicit `None`. Callback errors and
source exhaustion retain their separate Python meanings. Other entries below
remain the retained runtime inventory unless documented on the direct path.

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

Canonical `sum` accepts positional or keyword `start` through direct calls,
captured aliases and source-function arguments. Signature errors preserve the
evaluation of every explicit argument, including eager generator construction,
and do not consume a rejected iterable. This binding uses the same supported
numeric and iteration protocols as positional calls.

## sys

Native `sys.exit(status=None)` and site-provided `exit(code=None)` / `quit(code=None)`
support direct calls, captured aliases and source-function arguments. Termination
unwinds native frames and context managers before returning the process status.
Suppression by `__exit__` resumes execution. Site exit helpers close the shared
standard input; `sys.exit` leaves it open. Builtin scalar and container payloads
retain their shared values until final display. Deferred user-defined payload
display and observation of context-manager exception objects remain unsupported.
Integer statuses use Python's signed-64 conversion before platform status truncation;
values outside that range produce status 255 on POSIX. Source arithmetic still
uses the selected i64, i128 or BigInt policy.

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

Typed frame sorting supports `sorted(iterable, *, key=None, reverse=False)` and exact builtin `list.sort(*, key=None, reverse=False)` with captured source functions, closures, lambdas, builtin adapters and bound source methods as keys. Keys run once per input element before ordering; reverse sorting remains stable. Integer/boolean, text/bytes, and finite tuple/list key shapes use native comparisons while retaining element references. Direct source ordering objects use registered rich comparisons and the fallible stable Powersort kernel, including reflected methods, actual homogeneous-class `NotImplemented` retry order, callback effects and in-place mutation errors. Floating NaN ordering and nested container keys with custom rich comparisons remain unfinished.

Canonical `sorted` and captured aliases consume nonescaping generator expressions
directly into their final sorting buffer. The outer iterator is captured before
later arguments, all elements are collected before key callbacks, and element
references remain shared. Generator-body stopping uses PEP 479; key callback
exceptions propagate from the collector.
Canonical standard-stream aliases can be retained in lexical cells; their
distinct static identities need no runtime payload, while cell presence still
tracks initialization. Rebinding a captured reader to a different standard
stream operation remains an explicit callable-protocol diagnostic.

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


Canonical `operator` callables `add`, `sub`, `mul`, `and_`, `or_`, `xor`, `lshift`,
`rshift`, `floordiv`, `mod`, and `truediv` share the corresponding typed binary
operation planners. Captured aliases work as fold callbacks. This does not
implement in-place operator protocols, user special methods, or the remaining
`operator` exports. Integral BigInt true division uses exact rational rounding
to binary64; other missing floating interoperations retain diagnostics.

BigInt numeric expressions support direct binary64 addition, subtraction,
multiplication, true/floor division and remainder when a float operand is
present. Integral operands convert once through the exact `Int.ratio` helper,
with overflow errors instead of silent infinity. Pure integral true division
retains its existing exact-ratio path.

Builtin scalar integer/binary64 comparisons (`==`, `!=`, `<`, `<=`, `>`, `>=`)
are exact in every integer mode, including BigInt and finite numeric alternatives.
They preserve signed zero, infinities, NaN, operand order, and comparison-chain
short-circuiting. BigInt comparisons inspect existing limbs and float bits without
converting the integer to binary64 or allocating an intermediate integer.
Identity-sensitive floating container comparisons remain separate requirements.

Canonical `math.sqrt`, `floor`, `ceil` and `trunc` have direct numeric adapters
for int/bool/float values and captured aliases. Integer rounding retains exact
integers; square root converts integers once to binary64 with overflow checks.
NaN, infinities, signed zero and positioned argument errors follow Python 3.14.
User numeric conversion protocols remain explicit unsupported diagnostics.


Canonical `math.log`, `log2` and `log10` support builtin real arguments,
including huge positive BigInt values without converting them to infinity.
`log` accepts an optional positional base. Domain errors distinguish integral
and floating inputs; argument capture and base conversion retain Python order.

Canonical `typing` annotation aliases may be imported without using annotations
for inference. Their initialized binding presence is retained; runtime alias
object operations remain positioned diagnostics. Linked compiler-feature
exports retain the same unobserved-symbol behavior. `typing.cast` evaluates
its arguments normally and returns the original value, without conversion or
copying mutable payloads. Import binding presence is updated after each actual
linked import, including `globals()` membership observations.

Unobserved type metadata passed to the captured canonical `typing.cast` `typ`
parameter supports nested subscriptions of canonical `typing` aliases and
builtin generic classes. Builtin type objects, ordinary source class objects,
fixed type-parameter tuples, closed literal parameters and callable parameter
lists use dedicated compiler-symbol carriers. Assignments, source-function
argument/return transport and aliases retain their actual evaluation order;
`cast` returns its `val` without deriving or changing its type from `typ`.
Constructor arity, type-argument validation and closed forward-reference syntax
errors follow the host Python 3.14 `typing` implementation after evaluating the
original receiver and index expressions. No source expression is executed by
the converter. Dynamic scalar parameters, arbitrary mutable parameter packs,
custom metadata hashing/equality, metadata warnings, and general observation
of metadata objects remain positioned diagnostics. Printing, truth tests,
comparison, exposed metadata attributes and calling these compiler symbols do
not silently produce Python `None` or runtime metadata objects.

`typing.NamedTuple` supports canonical class syntax, including nested source
classes and captured factory aliases. Constructors support positional and
keyword fields, shared trailing defaults and Python binding errors. Records
retain their nominal type for `isinstance`, field reads, `_fields` and repr,
while equality, ordering, compatible native hash keys, unpacking and iteration
follow tuple behavior. Tuple conversion and constant fixed-layout slices return
plain tuples. Annotations do not request or perform runtime value coercion.
Functional factories, record identity, source methods, effectful annotation
metadata, descriptor replacement, expanded constructors and heterogeneous
named/plain tuple key storage remain explicit unsupported protocols.

Builtin `float()` supports zero/default construction, builtin int/bool/binary64,
text and bytes in every integer mode, including captured constructor aliases
and typed frames. BigInt integral conversion uses exact rational rounding and
raises `OverflowError` beyond binary64 range. ASCII mode parses numeric bytes
without Unicode digit tables; Unicode text mode also accepts Unicode decimal
digits and whitespace. Bytes retain ASCII-only numeric rules in either mode.
Invalid input preserves the original text/bytes repr in the error message.
Custom `__float__` and `__index__` protocols remain positioned diagnostics.

Linked native instances support `isinstance(value, source_class)` through their
captured class-definition references. Saved class/builtin aliases, finite class
arguments and nested classinfo tuples preserve short-circuit behavior, including
invalid later members. Matching uses actual class-object identity, including
same-named classes from different modules. Source inheritance and metaclass
instance-check protocols still require their own registered adapters. This does
not implement finite class-constructor unions or new class-object admission.

Canonical `functools.cmp_to_key` factories are accepted as `sorted` and
`list.sort` keys. Captured comparators, aliases, closures and bound methods use
the normal typed callback ABI. Sorting is stable and follows Python 3.14's
less-than comparison sequence, including reverse order, non-total results,
callback side effects and failures. Comparators may return builtin int/bool or
float values. Unorderable results retain Python's runtime error. Standalone
KeyWrapper calls, attributes and rich comparisons, other key consumers and
custom comparison-result protocols remain positioned unsupported diagnostics.

Typed frame sequences support list, text, bytes and homogeneous runtime-tuple
slices, including negative strides, omitted bounds and arbitrary BigInt bounds.
The owner and bound expressions are evaluated once in Python order; builtin
bound conversion and errors follow that evaluation. List slicing allocates a
new outer list while retaining referenced mutable elements. Finite sequence and
bound alternatives use concrete Rust projections. ASCII text slices use byte
indices, Unicode text slices use cached codepoint offsets, and unused slice
helpers are omitted. User `__index__` and `__getitem__` slice protocols and fixed
heterogeneous-tuple slicing remain positioned capability diagnostics. Pending
index types are deferred until the type-analysis fixed point is reached.

Canonical `@staticmethod` decorators retain the original source function:
class and instance reads supply no implicit receiver and preserve function
identity, defaults, arguments and exception frames. Decorator aliases/calls are
admitted only when their captured value proves the canonical builtin identity.
Descriptor resolution participates in the type-analysis fixed point before any
receiver is seeded. Plain zero-argument class-body functions can also execute
without an invented receiver. Ambiguous decorator identities, raw descriptor
values and descriptor replacement remain explicit capability diagnostics.

Canonical `@classmethod` decorators use the shared typed class namespace. The
decorator can be captured through a builtin alias or a source call only when its
resolved value is exactly the canonical builtin. Decorator expressions execute
before default expressions. Class and instance attribute reads create fresh
bound method objects retaining the actual class reference and the stored source
function; saved methods preserve that class after name rebinding. Fixed,
positional-only, keyword-only and variadic positional signatures, callback
passing and positional expansion use the shared native call binder. Bound method
identity and equality follow the retained function and class identities.

Arbitrary decorator replacement, stacked descriptor composition, raw class-body
`classmethod` descriptor values, classmethod constructor overrides and mutable
method-slot replacement remain positioned conversion errors. Inheritance,
metaclass and descriptor metadata support is not implied by this subset.

Source context managers with ordinary `__enter__` and `__exit__` methods use
retained type-level method lookup and typed cleanup regions. Normal exits,
exceptions, `return`, `break` and `continue` run cleanup once; nested managers
unwind in reverse order. A truthy cleanup result suppresses body errors, and
cleanup errors preserve the preceding exception chain and original source
frames. `as` target binding occurs inside the protected region, after entry.

The initial exception-argument adapter requires each received `__exit__`
exception parameter to be unobserved. Official binding ownership checks include
child closures, default expressions and lazy annotation captures. Frame
introspection is rejected. These arguments are erased compiler values, not
fabricated Python `None` metadata. Actual exception type/value/traceback objects,
nonfunction special-method descriptors, finite manager-type alternatives and
arbitrary builtin context managers remain explicit conversion boundaries.

The richer error context layout and rendering helpers are selected only for a
reached native `with` region. Programs without such a region retain their
ordinary error layout and generated source bytes.

Extended assignment targets support `first, *rest, last = source`, including
heterogeneous tuples, shared lazy iterators and nested targets. The remainder
is a fresh typed list retaining element handles. Each unpack level finishes
iteration and checks arity before storing any of its targets. Scalar/default
noniterable inputs retain the runtime unpacking TypeError, and map/zip callback
errors retain their original source frames. Custom iterator protocols remain
explicit unsupported diagnostics.

Canonical `isinstance` guards refine finite local alternatives for builtin
types and plain source-class identities. Saved canonical predicates/types and
literal tuples of type names are supported; same-spelling user functions do
not receive builtin assumptions. Guard argument/callee evaluation remains in
source order. Analysis waits for unresolved producers before entering guarded
arms, and unreachable arms do not contribute false call/return/storage types.
Read-only captured bindings retain point types in their owning function while
their closure storage keeps the complete shared ABI. Descendant rebinding,
arbitrary classinfo expressions and global subjects retain conservative facts.
Loop joins still retain a possible zero-trip entry, so some post-loop operations
remain explicit capability diagnostics. Builtin `bytes` is also available as a
type-predicate object; its constructor protocol is a separate capability.

The same extended target planner is used in ordinary `for` loops, list/set/
dictionary comprehensions and consumed generator expressions. Comprehension
targets retain their lexical scope and do not overwrite enclosing bindings.

Repeated execution of a nested `def` now creates a distinct native function
identity with its own captured default values. Saved aliases and returned
functions retain that instance's defaults, including mutable defaults and
keyword-only parameters, while body free variables keep their shared lexical
cells. A default-expression failure leaves the previous successful binding
intact. Default payload ownership participates in cycle checks. Multiple
distinct definitions of one lexical name and ordinary writes/deletes of that
name remain separate capabilities.

Plain instance data attributes support finite owner alternatives, including
`None`, and distinct source-class instances can share a finite return/binding
representation. Each Rust branch uses the actual class layout and retains its
shared payloads. Missing builtin attributes produce their Python read/store
errors; an existing builtin attribute needs its registered descriptor adapter
and is diagnosed explicitly. Attribute assignment evaluates its RHS before
looking up the target owner. Augmented assignment retains its owner and reads
the old value before evaluating its RHS. Method/descriptor alternatives and
cycle-aware object lifetimes remain independent capabilities.

The canonical builtin `NotImplemented` has a distinct native singleton type.
Unmodified builtin reads, saved aliases, parameter/return values, mixed shared
containers, identity and display preserve that value separately from `None` and
function objects. Truth testing raises Python3.14's `TypeError` at the original
demand location, including deferred filter/any/all consumers and map strictness.
Fallible `print(flush=...)` conversion precedes output and separator validation;
cleanup-result truth errors retain the active body exception context.

Mutable builtin-singleton namespace fallback and `builtins.NotImplemented`
exports remain positioned conversion boundaries. This value carrier is a
prerequisite for source numeric/reflected operator dispatch; it does not by
itself enable user-defined numeric special methods. Programs without singleton
values omit its runtime declaration.


Native frame `for` and `while` loops support exhaustion `else` suites. Normal
exhaustion and `continue` enter the suite; a completed `break`, `return`, or an
unsuppressed exception skips it. Break edges join after the suite, preserving
zero-trip bindings and values assigned only by the suite. Inner loop suites
can transfer to the enclosing loop. Context-manager cleanup runs before a
pending transfer takes effect, including suppression of an error that replaced
a pending break. Literal true/false while conditions omit unreachable suites
without resolving their contents. These loops compile to typed Rust control
flow, without a bytecode interpreter or generic execution loop.

Plain source-class cycles with scalar/`None`/direct-instance fields and their
finite alternatives have a native trial-deletion collector. Weak registration,
external alias counts and direct-edge tracing preserve live identities; borrowed
objects are conservative roots. Collection clears unreachable field storage
without source callbacks. Programs with acyclic class ownership types do not
include the collector.
Container/callable/closure-mediated cycles, `__del__`, weak-reference protocols
and resurrection remain unsupported. This does not implement general arena or
container collection.


Shared runtime tuples on typed frames support lexicographic `<`, `<=`, `>` and
`>=`, tuple membership, and stable sorting with proved identity-safe builtin
immutable elements. `min`/`max`, stored callbacks and tuple-producing sort keys
use the same captured-value protocols. Fixed/runtime tuple alternatives keep
their actual length, element comparison errors and first-candidate identity;
comparison does not re-evaluate operands or later chained-comparison values.
Floating NaN, custom element comparison and mutable element ordering still need
their own identity-aware adapters and retain positioned diagnostics.


Exact assignment unpacking of finite fixed-tuple alternatives on typed frames
retains each field's position and representation, including optional tuple
sources. Non-iterable and wrong-arity alternatives raise before storing any
target at that level; valid alternatives capture all members before ordered
target stores. Shared payloads keep their original handles. A temporary bottom
value from an as-yet-unsolved producer defers attribute analysis until the
shared fixed point; final protocol validation still applies. Mixed iterator
alternatives and extended starred targets retain their separate pull protocols.

Builtin `str.join` and `bytes.join` accept the registered typed sequence and
iterator families, including stored map/filter cursors, linked dictionary
views, and immediate generator expressions. Receiver and arguments are
captured before iteration. Generic sources collect concrete typed items before
validating their element types, preserving later iterator/callback errors and
shared cursor positions. The existing ordinary string collectors and the
class-frame string-list fast path remain available. Positional/keyword binding
errors, noniterable inputs and the first invalid element's index/type produce
Python errors at the original call.

Generator body `StopIteration` becomes `RuntimeError` with its complete
original direct-cause traceback. Canonical builtin exception classes and
stored exception instances use the shared typed exception protocol. No type
error or unsupported operation is hidden by a runtime interpreter fallback.


Captured source class references can be used by typed eager/lazy consumers,
including map callbacks. Their real __init__ signatures bind the already
captured positional, keyword and default values. Allocation retains the
captured class object and defining module; aliases and finite class/function
alternatives dispatch to the appropriate concrete constructor. Zero-length
sources never call the initializer. Invalid bindings raise Python TypeError
when the callable is actually invoked. Nominal NamedTuple factories and
non-None initializer returns require separate constructor protocols and receive
positioned diagnostics on this captured-callback path.


Typed C-iterator pulls preserve exception kind, payload and traceback until
the actual consumer decides whether `StopIteration` means exhaustion. A
`next` without a default forwards the original exception; a supplied default,
`for` and eager collectors clear it. Map/filter callbacks can resume on later
pulls. Strict map/zip clear source stops before validating lengths and retain
the callback's own exception. Chain advances past a stopped source; islice and
pairwise release their exhausted/error state; accumulate preserves its old
total and source after callback failure. Deferred Python caller frames follow
the clearing boundary, including recursive callbacks, rather than being
identified by line/name equality. Builtin C callbacks do not invent Python
frames. General iterator-object and source-function-object display remain
separate positioned capability boundaries.


Lambdas defined in immediately consumed generator expressions retain their
official lexical scope, target cells and fresh function identity. Escaping
lambdas share the generator's late-bound cells, while defaults are captured
at each original lambda evaluation. Nested generators and enclosing source
functions keep their own typed parent environments. Generator scopes are
selected from original AST/symbol identities, without synthesized callable
ASTs or an instruction stream. Runtime binding errors use the original
`<genexpr>` qualification. Stored generator suspension and unsupported function
object introspection remain separate capabilities.

Builtin list traversal retains the original object while observing later
append/extend, element stores/deletion, clear, reversal and sorting. Alias,
source-binding replacement, nested loops and comprehension effects use the
same solved allocation facts. Lists requiring live mutation use typed shared
handles; read-only lists keep ordinary owned-vector loops. Canonical iterator
adapters retain source allocation provenance without wrapping values in a VM.
Ordinary lexical value bindings support `del`, including conditional and
loop-carried unbound states. Imported/callable static-reference bindings still
need their own unbinding representation.

Owned typed vectors support indexed augmented assignment through the shared
stable-owner sequence capability. The receiver and index are captured before
reading the old element; the right-hand side runs before the final checked
store. Negative indices are normalized again after right-hand-side mutation.
Unaliased homogeneous arrays retain ordinary `Vec<T>` storage. Aliased builtin
lists containing floats or immutable float tuple fields use shared native list
handles without requiring an element-comparison protocol merely to store them.
Float tuple construction and display retain Python formatting; identity-sensitive
floating element equality, membership and ordering remain explicit missing
protocols rather than silently using Rust's value comparisons.

An indexed update reuses its checked offset when shared semantic effect facts
prove that the right-hand side contains only closed builtin value operations
and reads. Potential callbacks, binding writes and mutations retain a separate
checked store, including negative-index normalization after a resize.
BigInt list indices are checked against the structural length directly, without
constructing a BigInt length or running arbitrary-precision addition/comparison.
Values outside signed i128 cannot index an in-memory Rust sequence.

Arbitrary-precision integer add/subtract/multiply/negate and ordering have
inlined checked operations for canonical signed-i128 values. Results that exceed
that interval retain exact limb arithmetic. Comparing a wide value with a small
value uses the canonical representation bounds, without allocating a temporary
small magnitude. Fixed-width modes retain explicit wrapping at every operation.

Fresh, nonescaping numeric matrix rows can use owned nested vectors, including
row literals and per-iteration repeated rows such as `[[False] * w for _ in
range(h)]`. Direct cell reads, assignments and augmented assignments share the
stable sequence-storage capability. Repeated outer rows, escaped row aliases,
shallow copies, reentrant operations and mutations observed by a row iterator
retain identity-preserving storage. Assignment and augmented assignment keep
their separate Python operand and error order.

Unpacking consumes proved fixed tuple fields directly even when normalization
classifies the producer as a method or another iterable-producing operation.
The source expression runs once, arity is checked before binding, and the
captured tuple's owned fields are moved into the targets without constructing
an intermediate integer vector.
Builtin `dict.popitem()` removes the last inserted live slot without scanning
other entries, retains the original key representation, and raises `KeyError`
on an empty dictionary. Reinserted keys use their new insertion position.

Canonical direct constructors and constructor callbacks consumed by `map` have
separate source call and heap-effect certificates. Registered numeric in-place
methods propagate their real source writes instead of invalidating every
independent namespace fact. List slices register fresh outer allocations while
preserving references to their elements. These facts can transport a proved
context value through a native numeric loop; constructors and operators that
modify that context still invalidate it.

Plain classes with mutable instance fields can retain fixed original method
bindings and shared metadata from their proved single class publication.
Mutable objects keep their shared identity and field updates. Replaced methods,
observable metadata, ambiguous publication and unproved callbacks retain the
corresponding checked native operations.

Native `typing.TypeVar` construction supports closed arguments at proved
single-execution module sites, including constructor errors and distinct
same-name type-variable identities in unobserved metadata. Repeated factories,
retriable initializer imports, expanded/implicit factory calls, and runtime
metadata-object observation retain explicit diagnostics. This native slice does
not establish the broader historical typing/runtime API claims above.

Literal `str.format` templates lower through Python's official field parser to
direct typed Rust string construction. Positional, named and automatic root
fields, escaped braces, `!s`/`!r`/`!a`, and nested specifications preserve argument
and formatting-stage error order. Attribute/subscript field traversal, dynamic
templates and expanded argument calls retain precise unsupported diagnostics.

Immediate canonical `map(int, input().split())` unpack/list consumers can borrow
the input reader's reused line buffer until integer collection finishes. Stored
maps, aliased input bindings, callbacks and later argument effects retain owned
snapshots. Prompts, implicit input flushing, explicit print flushing and
interactive pipe behavior are preserved. This removes per-line text allocation;
it does not remove Python input's per-read output-flush cost.

Concrete `None` conditions preserve evaluation of the original test while
omitting the unreachable branch from native type execution. Official local
bindings remain local: an unbound read still raises `UnboundLocalError` rather
than falling back to a global value. Unknown conditions never establish this
proof, and a later type widening invalidates an earlier branch mask.

Closed TypeVar construction also permits function/control-flow imports when
every resolved module prefix and imported child is a canonical native adapter
without a Python source initializer. Source-module retry boundaries remain
explicit diagnostics. Empty primitive `str.format` specifications retain only
the required string conversion helpers.
