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

Resolved integer calls to `math.gcd`, `lcm`, `isqrt`, `factorial`, `comb`, and
`perm` also have direct helpers. The following list APIs have direct typed
lowering with the payload, storage and evaluation-order limits documented in
[COMPATIBILITY.md](COMPATIBILITY.md):

| Module | Direct APIs | Remaining requirements |
|---|---|---|
| `heapq` | `heapify`, `heappush`, `heappop`, `heappushpop`, `heapreplace`, and all five `_max` counterparts | `merge`, `nlargest`, `nsmallest`, custom/fallible comparisons, floating tuple identity |
| `bisect` | `bisect`, `bisect_left`, `bisect_right`, `insort`, `insort_left`, `insort_right` with checked bounds and `key=None` | Callable keys, arbitrary sequence protocols, custom/fallible comparisons |

Module/function aliases use resolved identities. General starred calls and
the remaining module APIs still need implementation. The tables below describe
the retained runtime inventory, not additional direct coverage.

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
