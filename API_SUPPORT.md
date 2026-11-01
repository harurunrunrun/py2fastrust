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

The frame path also stores typed `iter`, `filter`, multi-source `map` and `zip`
objects, including the `strict` keyword, captured callbacks, shared cursor
aliases, and list/reduction consumers. Builtin list, fixed tuple, range, text
and byte sources have adapters. Custom iteration protocols and cyclic ownership
still require implementation; this does not establish complete builtin object
compatibility.

Typed frame dictionaries and sets have shared native storage, including
ordinary mutable aliases, dictionary values and class fields. Direct adapters
cover literals/comprehensions, `dict`/`set` constructors, dictionary subscripts,
`get`, `setdefault`, shallow `copy`, set `add`, length/truth/membership and
order-insensitive `sorted` set consumption. Live dictionary `keys`/`items`/
`values` views and checked shared cursors support iteration and the same
materialization/reduction consumers, including `tuple(iterable)`. Key families
and the remaining deletion, view-operation and custom-protocol limits are documented in
[COMPATIBILITY.md](COMPATIBILITY.md).

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

Direct typed frames currently adapt canonical `repeat`, `chain`, `islice`, and
`pairwise`, including saved aliases, lazy consumption, shared mutable values,
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
