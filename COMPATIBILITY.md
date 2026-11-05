# Compatibility

The language target remains Python 3.14. The public CLI and API now require
direct typed Rust generation. If that implementation is missing, they return a
source-positioned `E006` diagnostic and no Rust file. They never select the
retained general backend. `--no-optimize` disables optional helper pruning and
keeps the same direct generation path.

## Current public direct path

Proved integer/boolean, string, and f64 scalars, BigInt scalar arithmetic and
functions, integer containers, compatible branches/loops, scalar functions and
selected competitive-programming input/BFS patterns are implemented. This is
an incomplete subset of the required Python language. Remaining closure lifetime
cases, exception handlers, general object models, user-defined generators,
dynamic execution, import reflection/reloading and many mixed-type/alias cases
still require direct lowering. An `E006`
diagnostic makes that gap explicit; it does not satisfy the missing feature.

F-strings lower their original `JoinedStr` and `FormattedValue` nodes to native
string construction. Fields, conversions, and dynamic specs run in Python 3.14
order: an explicit `!s`/`!r`/`!a` conversion runs before spec expressions, while
default formatting observes the captured object's state after those expressions.
Debug fields, nested f-strings, canonical `format`/`repr`/`ascii` aliases,
integer/boolean/string/binary64 formatting, and supported container display work
in all integer modes. Nonempty specs for containers raise `TypeError`.
Source-defined `__format__`, `__str__`, and `__repr__` methods, complex formatting,
and `str.format`/`str.format_map` remain positioned diagnostics. Unicode format
widths and fills follow the selected string mode; Unicode data is included and
attributed only when its helpers remain reachable.

Canonical `ord` calls accept strings containing one Unicode scalar value and
bytes of length one; invalid lengths raise the corresponding Python `TypeError`.
`bin`, `oct`, and `hex` accept integral and boolean values in every integer mode,
with Python signs and prefixes. Saved aliases, callbacks and class fields use
the same captured-call contract. These operations need no Unicode data tables.
Custom integer-index protocols, unpaired surrogate string storage, and `chr`
remain unfinished. Fixed-width input normalization still follows the chosen
integer mode.

Explicit-base `int(text, base)` and `int(text, base=...)` calls have direct
lowering for builtin strings and bytes, including saved aliases, class fields
and multi-source `map` callbacks. Bases 0 and 2 through 36 support signs,
prefixes and underscores; invalid bases and literals retain Python errors.
Fixed-width results wrap at the selected width. ASCII parsing scans bytes;
Unicode mode uses the pinned decimal-digit and whitespace tables. Custom base
`__index__` objects, bytearray/buffer storage and CPython conversion
digit limits remain unfinished.

Fixed-name imports now compile supported user modules, pure-Python packages and
bundled module sources to separate typed namespaces in the same Rust file.
Original AST, symbol-table, scope and source positions remain attached to each
source unit. Initialization runs once at the original import statement, with
partial namespace caching for circular imports. Module references, supported
attribute values and exported callables preserve identity and defining globals
through aliases, function arguments, returned values and captured defaults.
Relative imports and parent-package attributes use the same namespace objects.
The implementation does not load Python files at runtime. Arbitrary namespace
keys, import-spec objects, lazy annotation descriptors, runtime imports and
`--include-module` dynamic bundles still require implementation. Replacing
`sys.stdin`, `sys.stdout` or `sys.stderr` requires stored stream-object dispatch;
such assignments are rejected instead of silently continuing to use the native
standard streams.

Immediate `for`, reduction, `list`, `set`, `sorted`, `next`, unpacking, and string
`join` consumers use the same normalized producer plans. Core builtin aliases
are resolved from definite lexical bindings; a spelling alone does not prove
builtin identity. An alias absent on a branch or loop edge is not treated as a
definitely bound callable. Splitting text or bytes uses a common source adapter,
and proved integer projections share a parser for `map`, generators, and eager
comprehensions. Lazy unpacking converts exactly the first excess item before
raising a cardinality error, while eager comprehensions finish before unpacking.
Producer conversion errors and consumer cardinality errors retain their own
source frames. Exact builtin list/tuple unpacking reports the complete sequence
length in Python 3.14's excess-value error. Lazy producers inspect only the
first excess item and retain the error without a full-length claim.
General dynamic callable values and conflicting core-name
rebinding still require direct implementation.
Dynamic builtin-list row unpacking is selected from reached allocation facts before
Rust lowering. Input-built rows support assignment, `for` and comprehension
unpacking, including `enumerate` nesting. The native iterator adapter checks each
level before its target stores, reports exact list cardinality errors and retains
shared row mutations and ordered partial effects in nested targets.


`set(iterable)` and set comprehensions consume the same typed streams in every
integer mode. Exact-set sorting with `key=None` permits traversal whose order
cannot affect the result; this permission crosses a transparent `iter` adapter,
but does not cross callbacks, generators, `enumerate`, or `zip`.
Container name lookups, including unbound-name checks, occur before later call
arguments. Their Rust borrows begin after those arguments, so mutations such as
`sum(values, values.pop())` retain Python's evaluation order. The same rule
applies to borrowed list arguments of native functions. Callbacks that replace
bindings through unsupported namespace writes remain rejected.

Positional `min` and `max` calls consume canonical call plans in every integer
mode. Supported values include integers/bools, strings, bytes, and immutable
tuples with supported comparable fields; fixed-width modes also support scalar
floats. Every argument runs before comparisons, ties retain the first value,
and tuples compare lexicographically with short-circuited field comparisons.
`key=None` is supported. Captured builtin identities can replace `min`/`max`
bindings without dispatching by their old spelling. Typed frames also support
`key` callbacks and the single-iterable `default` argument. Keys run once per
candidate in source order; equal keys retain the first original candidate and
mutable aliases are preserved. Empty input returns its captured default without
calling the key. Generator inputs use direct loop sinks, keeping construction,
keyword evaluation and body execution in their original order. Source callbacks
invalidate loop field caches through a shared semantic-effect registry. Bare
binary64 comparisons retain native partial ordering in every integer mode;
exact mixed BigInt/float ordering and identity-sensitive floating containers
still require their own protocols.

Canonical builtin and registered native-member references have stable display
metadata, including builtin class names. Display of source functions and bound
methods still requires their name/address object protocol. Default user objects
raise ordering `TypeError` only when a comparison is actually needed; defining
custom special methods remains an explicit unsupported class protocol.

Generator expressions consumed by `sum`, `any`, `all`, `min`, or `max` lower to
typed Rust loops, including proved nested clauses, filters, and
`map`/`filter`/`enumerate`/`zip` adapters. Construction and iteration keep their
different evaluation times, and short-circuit consumers stop without evaluating
later elements. On typed frames, `list` and `next` also consume nonescaping
generator expressions. Positional `*generator` arguments fill the call's typed
argument buffer directly, including nested clauses and filters, without an
intermediate list. The first iterator is constructed at generator creation;
body evaluation follows the consumer's actual timing. Body `StopIteration`
becomes `RuntimeError`; a `map`/`filter` callback `StopIteration` ends one pull
without permanently exhausting a resumable source. Escaping generators and
unproved mutation still need direct implementation. Floating-point compensated
`sum` is not implemented here.
Ordinary `for` loops share these typed adapters, including string character
iteration, `reversed`, destructuring `enumerate`/`zip`, and generator producers.
They preserve `break`, `continue`, `return`, and loop `else`. A possibly unset
scalar target uses `Option<T>` with a positioned Python unbound-name error on
read, including zero-iteration and filtered-generator paths.

Fixed-shape list literals can retain per-position types for constant
indexing, record unpacking and iteration over records. Their physical element
carrier remains a typed finite union, so aliases and mutable list identity are
preserved. Unknown allocation origins, resizing, reordering and unproved
callback effects conservatively widen positional facts to ordinary list facts.

All integer modes support uniquely owned flat integer lists, indexed reads and
updates, copied lists, ordinary list operations, `sorted` with supported immutable key results,
and slicing with positive or negative steps. Slices make independent lists.
Nested lists with proved integer/boolean, text/bytes, None, or recursively
immutable tuple payloads use typed shared handles in every integer mode. Named
row aliases, shallow `copy`, repetition/concatenation, item mutation, ordinary
function parameters/results, live list iteration, and printing retain object
identity. Captured row handles survive replacement or clearing of the parent.
Shared-list indexing through stable local names and scalar, non-reentrant
indices borrows the existing handles directly. Nested paths retain parent
borrow guards instead of acquiring a new reference-counted handle for each row.
Scalar stores and scalar augmented assignments use the same path when its
evaluation-order and storage-effect proofs apply. Effectful indices retain
owned handles and short borrows so mutations still observe Python semantics.
List `for` loops can retain one immutable contents borrow when solved allocation
and call-effect facts prove that the body cannot mutate any possible source
object. Mutations of other proved disjoint lists remain allowed. Cached source
function effects retain their actual receiver origins; delayed or unknown calls
prevent the optimization. Repeated executions of one allocation site are never
assumed to identify distinct objects. Direct list loops and one-source `iter`
and `enumerate` adapters share this proof. Eager adapter arguments finish before
the borrow starts, and the captured owner and borrow leave scope before loop
`else`, subsequent statements, or a function return. Other cases keep native
live cursors so alias mutation and suspended producer effects remain observable.
Source-function summaries refresh when their global binding dependencies change,
including a formerly absent builtin override. Content-type epochs created by
`clear()` keep their original object identity for alias proofs. Reference-field
proofs include updates made through every such epoch, including caller-owned
containers cleared and refilled inside another function. Symbolic writes to
reference fields reach a finite weak-update fixed point separately from type
layouts; protocol preconditions are checked again against those final fields.
Builtin method reference results and stored iterators preserve symbolic input
paths, and function-summary cache keys retain argument paths as well as origins.
Iterator rewrapping keeps finite root sets rather than growing nested histories.
Unmodeled calls or implicit protocols conservatively invalidate heap-alias
proofs across the program, including before a loop or through reentry into an
earlier function. Canonical standard input and closed primitive mappers retain
their sealed non-reentrant paths; delayed producers with unproved effects do
not retain loop borrows.
Subscript receivers and indices execute once; assignment evaluates its RHS first,
and numeric item augmented assignment reads the old item before its RHS and checks
the stored index again after a length-changing RHS. Shared-list `+=` and `*=` retain that same list object, including self-extension,
zero/negative repetition and shallow nested row handles. Both name and indexed
list targets capture their original reference before evaluating the RHS. Standalone flat arrays retain owned-vector storage when their unique ownership
is proved. Shared name aliases, returned argument references and caller-owned
list mutation through ordinary functions select the same typed handle storage. Shared nested-list slicing, element-layout changes
through `clear`, float/custom element identity, and recursive object graphs remain
explicit unsupported operations. In all integer modes, strings default to ASCII:
lengths, indices, slices, and `count` bounds use bytes without per-access ASCII
detection. `--string-mode unicode` selects Python code-point semantics. The
source-comment directive overrides CLI/API settings. Non-ASCII strings require
Unicode mode; ASCII mode does not detect and switch automatically.
ASCII selection also applies to numeric-text parsing and buffered text input.
Text input rejects non-ASCII bytes, while binary streams retain arbitrary bytes.
Unicode mode is required for non-ASCII digits and whitespace. ASCII output
omits Unicode property tables and code-point cache implementations.
Unicode mode selects semantics, rather than including every Unicode table.
Only operations that need bundled Unicode data retain it and its notice,
including with `--no-optimize`. Integer-only classes, recursion and BigInt
literals do not require those tables. Numeric text conversion can require
Unicode digit and whitespace data even when the result is an integer.
Integer conversion from bytes always uses ASCII numeric rules and does not
require Unicode tables, regardless of the selected string profile.

Uniquely owned flat lists of supported immutable values share direct
`index`, `count`, and `pop` lowering. Search bounds use Python slice-style
normalization, numeric bool/int equality is preserved, and arguments finish
before the receiver's current contents are searched or mutated. Pop checks
index-size overflow and keeps unbound-name errors distinct from empty-list
errors. Element comparisons that require unsupported identity or object
protocols, including floating-point element identity, remain `E006`.

Concatenation and repetition of proved flat lists share one operation plan in
fixed-width and BigInt modes, including immutable bool/string/tuple elements.
Operands are evaluated in source order; results have independent list storage.
Repetition counts use checked index-sized conversion even for empty lists, and
allocation sizes use checked structural arithmetic.

String methods include `strip`/`lstrip`/`rstrip` with an optional
character set, `count` with bounds in the selected string model, and `join` over a proved
string iterable. Joining exhausts generator inputs before constructing its
result. Unicode whitespace includes Python's additional U+001C–U+001F range.
All integer modes use the immutable `NativeText` interface in scalar
bindings, function signatures, classes, and containers, with storage selected
for the configured string model. Cloning a string shares
its storage, and literal sites retain static storage. Unicode lengths are
cached; indexed reads lazily build and reuse code-point offsets. ASCII reads
retain byte-based borrowed views and carry no Unicode cache fields.
Mutable formatting and output builders remain
ordinary Rust `String` values. String identity and the remaining general object
protocols still need direct implementation.

Builtin `str` predicates support `isupper`, `islower`, `isalpha`, `isalnum`,
`isascii`, `isdecimal`, `isdigit`, `isnumeric`, `isspace`, `istitle`, and
`isidentifier`. Builtin `bytes` supports its corresponding ASCII predicates
(`isupper`, `islower`, `isalpha`, `isalnum`, `isascii`, `isdigit`, `isspace`, and
`istitle`). Methods use the shared receiver-first call plan and reject arguments.
The ASCII string profile uses direct byte classification; opt-in Unicode uses
pinned CPython Unicode 16.0 properties, including titlecase and identifier data.
Byte whitespace retains its distinct ASCII rules. Single-codepoint projections
can be classified without creating a string. Whole `isascii` reads cached
immutable-owner metadata: the default profile assumes ASCII, while Unicode mode
verifies the classification once. Generated output includes only the selected
predicates/property tables and retains their Unicode notice after pruning.
Class overrides remain ordinary user methods; builtin string subclasses and
remaining class protocol integration are still required work.

Structural type descriptors are shared by binding joins, declarations,
function signatures, and tuple operations. Fixed tuples of immutable scalar
values use ordinary Rust tuples and support aliases, unpacking, indexing,
comparisons, Python-style printing, and typed function arguments/results.
Possibly unbound tuple bindings use `Option<TupleType>` storage. Homogeneous variable-length tuples use immutable shared handles, including
`tuple(map(int, input().split()))`; their length is checked when unpacked rather
than inferred from later target counts. Indexing, iteration, printing, supported
comparisons and immutable keys share the same element types as fixed tuples.
Mutable tuple elements and unproved comparison protocols still require lowering.

Truth-only expressions in `if`, `while`, `not`, `bool`, conditional tests and
supported comprehension filters use short-circuit Rust boolean operations.
Lists and other supported containers can participate without constructing a
mutable list/scalar value union. Receiver effects and skipped operands retain
their source order, and loop-exit facts remain conservative after mutations.
Value-returning `and`/`or` and conditional expressions use typed result carriers.
An owned container can move into its selected result; a proved shared list keeps
the same reference through nullable values, finite alternatives, function
returns and control-flow joins. Different shared element layouts retain separate
typed alternatives rather than copying or widening an existing object. Borrowed
mutable dictionaries and sets still need shared storage before they can use
these result paths. Custom class truth protocols remain unfinished.

Non-escaping lambdas support immediate calls and `sort`/`sorted` key callbacks.
Definition-time immutable defaults run once, parameters retain their own lexical
scope, and free bindings are read at invocation. Keys are computed once per item
before stable sorting, including with `reverse=True`. Mutable arguments/defaults
on this eager path, variadic packing and callbacks observing the list currently
being sorted remain unfinished and produce a specific diagnostic.

Proved finite value alternatives share canonical types across ordinary binding
joins, function arguments/results, and immutable container fields. Each shape
uses its own typed Rust enum; nullable values use `Option<T>`. An unbound name
has a separate outer binding state, so bound `None`, an empty tuple, and an
unbound name remain distinct. Joined return types come from typed return records,
including a reachable implicit `None` return. Truth, Python-style output, equality,
and identity checks against `None` dispatch over the actual alternatives.
Uniquely owned mutable alternatives can move across proved branches and returns;
creating shared mutable aliases still requires implementation. Arithmetic on
general finite alternatives, ordering on mutable alternatives, and the class
adapter to this representation remain unfinished.

Ordering of proved immutable alternatives uses a common comparison lowering in
all integer modes: integers/bools, `None`, strings, bytes, and supported tuples
dispatch to native operations or a positioned Python `TypeError` for the actual
incompatible pair. Operands are captured once; chained comparisons evaluate the
next operand only if the preceding relation succeeds. Tuple comparisons retain
lexicographic short-circuiting and the original error operator. Fixed-width modes
also share exact integer/float ordering and partial binary64 ordering, including
NaN. BigInt/float interoperation, float tuple identity, mutable alternatives,
and general custom comparison protocols remain unfinished.

Ordinary comparison frontends consume one common set of captured operand
values before dispatching to finite, tuple, bytes, numeric, or keyed membership
operations. Nullable bytes equality therefore compares the actual payload, and
mutating operands cannot be emitted again while selecting another frontend.
The first two comparison operands always run; each later operand runs only when
the previous relation succeeds. Boolean operators and conditional expressions
also join mutation facts across paths that may be skipped. Pure allocation
analysis forks and joins those same conditional effects, including clear epochs;
accepted builtin list/deque/set/dict clear expressions return `None` without
leaving stale container cardinality proofs. Mutable equality, non-`None` object
identity, general operations on nullable values, and remaining class integration
are still unfinished.

`collections.deque` values use one native `VecDeque<T>` storage adapter in i64,
i128, and BigInt modes. The element representation is solved from ordinary
producers and mutations, including integers, booleans, text, bytes, None,
immutable finite alternatives, and fixed or homogeneous tuples. Trusted imports, module members, aliases,
and function-local imports resolve through the same callable identities. The
constructor accepts supported typed iterable producers and optional `maxlen`, including
proved nullable bounds. Append/pop operations at both ends, extend/extendleft,
clear, copy, count, index, insert, remove, reverse, rotate, readonly maxlen,
integer-indexed item reads/writes/deletion, content comparisons, membership, printing,
and existing stream consumers share typed native lowering. Bounded queues evict
from the opposite end; a zero bound still consumes source iterator effects.
Exact self-extension snapshots the original contents, while copy produces an
independent deque with the same bound. Plain print arguments retain mutable
identity until later arguments finish; starred arguments capture their expanded
values at their own evaluation point.

Ordinary unique-owner programs keep their direct deque path. Typed frames also
store shared deque handles across function arguments/results, object fields and
aliases. This frame adapter supports constructor iterables and nullable maxlen,
append/appendleft, pop/popleft, clear, shallow copy, len/bool, readonly maxlen,
identity, integer-indexed reads/writes/deletion and display. Indexed augmented
assignment loads before the RHS and retains the captured owner/raw index for
the store, including a length change or global rebinding during the RHS. Bounds
and index conversion errors retain their Python ordering. Shallow copies preserve
mutable child handles. Later argument effects cannot replace the already captured receiver. Zero maxlen still
consumes constructor source effects, and invalid bounds are checked before pulling
the source. Live forward frame cursors retain their deque owner and check structural version
stamps, including after exhaustion. Indexed replacement remains visible without
invalidation. List/tuple/reduction/extrema/sort consumers, map/filter/zip, normal
loops and comprehensions share this pull protocol, including finite source unions.
Extend/extendleft snapshot only an actual self-extension, identified by native
object identity. Iterator/generator arguments remain live, with partial effects
before a mutation error. At maxlen=0 extension consumes the source without
changing iterator state, while append still invalidates existing cursors.
Reversed cursors, custom index conversion, stored builtin method aliases, search/ordering protocols,
deque subclasses and arithmetic remain separate requirements. Floating/custom
search protocols and general aliases outside this admitted frame slice still
need their respective adapters. Shared deque ownership uses the same acyclic
lifetime proof as native closures and mappings. Unsupported cases remain positioned diagnostics; no VM or
implicit Python execution supplies these operations.

Proved immutable tuple keys use structurally typed Rust sets and dictionaries
in every integer mode. Numeric keys preserve Python's bool/int equality while
retaining the original key, and dictionaries retain insertion order. BigInt
integer keys use the same typed containers. The frame adapter also stores
shared dictionaries and sets in typed reference-counted handles, including
mutable dictionary values, class fields, captured arguments and returned
aliases. Dictionary/set literals, comprehensions and constructors preserve
source evaluation order. Frame keys may be integer/bool, text, bytes, `None`,
or compatible immutable tuple shapes; custom hash/equality protocols and
heterogeneous key representations remain unfinished.

Frame dictionary indexing, assignment, numeric augmented entries, membership,
`get`, `setdefault`, and shallow `copy` preserve shared payload identity. They
retain the original key on equal-key overwrites. Set membership, `add`, `copy`,
length, truth and `sorted(..., key=None)` use the same typed key adapter.
Observable set traversal/display and callable sorting keys that expose set tie
order remain diagnosed. Frame dictionaries provide live `keys`, `items` and `values` views, preserving
captured owner identity, insertion order, current values and mutable payload
aliases. Dictionary/view cursors check size changes at each pull, release all
borrows before callbacks, and stay exhausted after completion. Traversal uses
linked storage with O(1) cursor progress, without eager key snapshots or
repeated scans. Frame deletion/mapping expansion, view membership/set-like
operations, recursive ownership cycles and arbitrary mapping subclasses still
need their own protocols. The existing unique-owner path retains its
separate deletion support described below.

`collections.Counter` is a registered native mapping subclass with shared
handles. Canonical imports and saved constructor aliases preserve their class
identity; `isinstance(counter, Counter)` and `isinstance(counter, dict)` use the
registered class metadata. User modules named `collections` retain their own
exports and are never replaced by this adapter.

Counter constructors accept typed iterables, dictionaries, other Counters,
`None`, and compatible named counts. Missing indexing returns zero without
inserting a key; `get` keeps its ordinary dictionary default behavior. Copy,
mutation, class fields and returned aliases retain the same count/key storage
rules. `update` and `subtract` accept supported iterable/mapping/optional sources
and keywords. Counts must be builtin integers or booleans. Integral/boolean
key equivalence retains the original key, including during updates.

`most_common` preserves insertion-order ties. A requested finite positive limit
uses O(m log(min(n,m)+1)) counting/selection work and O(min(n,m)) auxiliary storage;
a nonpositive limit avoids traversal. Unbounded selection and Counter display
sort by count. `total` adds in the selected integer mode. Live keys/items/values
views use the same checked dictionary cursors. Counter `elements`, arithmetic
and set-like comparison, arbitrary count objects, subclassing/custom protocol
methods remain unfinished. Nonescaping generator-expression sources have direct
loop sinks for Counter construction, `update` and `subtract`.

`collections.defaultdict` has canonical class identities, constructor aliases,
`isinstance` support and the dict base class. Factories can be `None`, builtin
callable identities such as `int`, `list` and `set`, and captured compiled
functions, lambdas or bound methods with compatible zero-argument calls.
Missing `d[key]` reads invoke the current factory once, release storage borrows
before calling it, then insert only if the factory did not already insert the
key. A reentrant insertion preserves the existing key/value, matching CPython
3.14. Existing reads, `get`, `setdefault`, membership and views do not call it.

`default_factory` is a mutable shared attribute; assignment need not be callable,
and a later missing read reports the resulting Python error. Constructors
accept an optional typed dictionary or iterable of two-element pairs and named
values; nonescaping generator pairs use direct loops and preserve first-iterable
evaluation before later arguments. Copies retain the factory and mutable value
aliases with independent mapping/factory fields. A live cursor owns the whole
mapping, including its captured factory. Missing factory calls invalidate loop
field caches through the same semantic callback effect registry as sorting and
extrema callbacks. Custom callable-object/class factory protocols, explicit
`__missing__` calls, factory deletion, subclassing and recursive ownership remain
positioned conversion diagnostics. Typed key-family restrictions still apply.
The separate deque adapter has not yet been connected to this linked frame
path, so programs combining these factories with canonical `collections.deque`
currently report a positioned missing-member conversion diagnostic.

On typed frames, builtin text and bytes `split`/`rsplit` bind `sep` and `maxsplit`
through the shared call signature. Captured receiver, positional arguments and
keywords retain Python evaluation order, including keyword order and later
receiver rebinding. `None` separators use Python whitespace rules, with distinct
bytes whitespace. Zero/negative/boolean limits, empty fields, overlapping
separators, right splitting and empty-separator errors are supported. Maximum
limits are checked against the target signed index width after selected integer
normalization. The original source error location, exception type and full final
message are retained for supported binding/argument failures.

Word cursors borrow their source and produce the final typed list directly;
right splitting reverses the collected vector once. ASCII whitespace paths use
byte cursors without repeated ASCII detection; Unicode whitespace paths scan
valid character boundaries. Finite text/bytes receiver and optional separator
alternatives use the same native kernels. Saved builtin bound methods, custom
`__index__`, bytes-buffer protocols and arbitrary string subclasses still need
separate adapters. Canonical text-method selection also resolves symbolic
container/tuple field receivers from their exact solved source-expression facts,
without replacing or rewriting the original allocation path.

Frame `str`/`bytes` `strip`, `lstrip` and `rstrip` bind one optional positional
`chars` argument. `None` selects the type's whitespace rules; other builtin
text/bytes arguments are character sets, with empty sets preserving content.
Receivers are captured before argument callbacks, including field rebinding.
Finite builtin receiver/character alternatives retain their concrete native
return types. The existing text kernel supports ASCII and Unicode; bytes use a
separate slice kernel and whitespace set. Wrong closed argument types, extra
arguments and forbidden keywords retain Python error messages and source
frames. Plain text calls that the static path already supports stay there; bytes
and optional/error bindings use semantic frame capability selection. Saved
builtin bound methods, custom bytes-buffer objects and arbitrary string
subclasses still require separate protocols.

Frame `str.replace`/`bytes.replace` use captured receiver, old/new and count
values with shared call binding. Both support empty/nonoverlapping patterns,
zero/negative/boolean counts and checked signed index-width limits after selected
integer normalization. Text count may be a keyword; bytes arguments remain
positional. Binding, old/new type checks and count conversion retain Python
validation order, source frames and full final error messages. Unicode empty
text patterns insert at code-point boundaries; bytes retain arbitrary values.

Text uses standard native pattern matching. Bytes build a prefix table once,
scan in O(n+m) work per pass and store no match-position list. Output lengths
use checked structural arithmetic and fallible capacity reservation before
copying. Finite builtin receiver/argument alternatives use the same typed
kernels. Saved builtin method values, custom bytes-buffer/`__index__` objects
and arbitrary builtin text subclasses still need their own protocols.

Frame text/bytes `find`, `rfind`, `index` and `rindex` bind one required pattern
and optional positional start/end values. Bounds accept builtin integers,
booleans and `None`, clip large/negative values after selected-width arithmetic,
and preserve empty-pattern/out-of-range behavior. Bytes also accept integer
needles from 0 through 255. Text validates its pattern before bounds; bytes
validate bounds before their integer/buffer pattern. Missing raising searches,
wrong closed arguments and invalid bindings retain Python error text and frames.

Text reuses cached native windows and standard string matching. Unicode byte
results map to code-point indices by binary search through cached boundaries;
ASCII avoids Unicode scans. Bytes reuse the forward prefix matcher and use a
reverse prefix scan for rightmost matches, including overlaps, without copying
or reversing input. Single-byte and empty-pattern cases have direct paths.
Native user methods named find/index remain ordinary source calls. Custom
`__index__`/buffer objects, saved builtin methods and arbitrary text subclasses
still require their own protocols.

Frame `str.count` and `bytes.count` share the search binding and clipped-bound
protocol, with nonoverlapping matches and Python empty-pattern behavior. Text
counts use the selected character model; bytes accept integer needles from 0
through 255. Text validates its pattern before bounds, while bytes validate
bounds first. Shared byte-pattern cursors scan without a match-position list.
Canonical simple text calls retain the existing static adapter; bytes, nullable
bounds and argument errors select typed frames. User methods named `count`
retain their source identity. Custom `__index__` and buffer objects remain
positioned unsupported protocol diagnostics.

Direct frame `for` loops admit builtin `str` and `bytes` through the shared
source/pull registry, including text/bytes or text/list/range alternatives,
`enumerate`, nested loops, zero iterations, break/continue and retained owners
when source names or fields are rebound. Text yields configured characters;
byte sources yield integers. The existing inline one-character text carrier
avoids a heap allocation for each yielded character. This capability does not
force otherwise static text loops onto frames.

Frame `str`/`bytes` `startswith` and `endswith` use cached native windows and
borrowed prefix/suffix comparisons. They support positional int/bool/None
start/end bounds, selected-width clipping, empty patterns/windows, finite
receiver alternatives, and fixed or runtime tuples of candidate patterns.
Bounds are validated before patterns. Tuple members are checked in order and
matching stops on the first success, so a later invalid member raises only
when reached. Integer byte needles are rejected for these methods. Original
receiver and argument evaluation order and exact tested Python binding/type
errors are retained. Custom index/buffer objects and saved builtin methods
remain separate protocols; source user methods keep their own identities.

`tuple(iterable)` shares the typed source/pull adapter on frames. It materializes
immutable tuples with alias-preserving mutable elements, retains an existing
tuple's identity, and shares the empty tuple. Fixed and runtime tuple query
keys are converted to the stored canonical hash representation in O(key size),
including nested tuple lengths. This retains hash lookup complexity and avoids
scanning dictionary entries. Floating/custom key queries remain precise
conversion diagnostics rather than spurious missing/unhashable-key results.

Builtin dictionaries support `del d[key]`, including sequential deletion
targets, checked missing-key errors and numeric augmented entry updates.
Receiver lookup and key evaluation run once; augmented assignment fetches the
old value before its right operand and stores after that operand's effects.
Deletion/reinsertion preserves Python insertion order and the original key on
an overwrite. Admitted keys are immutable integer/bool, text and tuple shapes;
general hash/equality protocols remain unfinished.

Numeric augmented entries reuse one existing hash slot when the right operand
is proved scalar and cannot call Python code or access container storage. The
same scalar effect proof serves class-owned list updates. Missing-key checks
still precede right-operand errors, and a failed calculation does not commit a
value. Effectful right operands keep the separate lookup/evaluate/store order.

Programs with proved key deletion use hash indices and reusable linked slots:
lookup, insertion and deletion take expected amortized O(1), traversal is O(n)
in the live entry count, and slot storage grows with peak live occupancy.
Function specializations propagate this storage requirement to their caller.
Programs without deletion retain dense entry storage. Index and entry reserves
are checked. Mutation during active dictionary iteration, shared mutable
mapping arguments/aliases and custom `__delitem__` protocols still require
their corresponding direct storage/protocol adapters.

A shared semantic constraint graph supplies ordinary function allocation shapes
and loop-header binding types to the fixed-width and BigInt emitters. Empty
list/set/dict fields start as type variables; proven insertions, indexing,
iteration, copies, and function results constrain them before Rust generation.
Branch joins and loop back edges, including continue paths, reach a fixed point;
break-only values join at the exit. Unconstrained empty fields use an uninhabited
Rust type, rather than guessing an integer element. Cleared uniquely owned
containers receive a separate content epoch, preserving the former shape of
existing copies. Maybe-unbound carriers remain distinct from a bound `None`.
The solver never emits or executes source expressions. Edge transfers preserve
zero-iteration values and move mutable payloads once. Mutable shape-changing
loop exits without a proven shared carrier, recursive mutable object graphs,
and the class allocation/field adapter still require implementation and produce
`E006`; no alternate execution backend is selected.

Symbolic container fields preserve their allocation provenance through nested
indexing, tuple projections, iteration, and ordinary function parameters.
Mutating a selected row therefore constrains that row's elements. All three
integer modes support adjacency-list construction from initially empty rows,
including the unchanged `examples/bfs.py`. Semantic shape constraints are separate
from allocation identities: they select physical shared storage without inventing
objects or assigning an arbitrary integer payload to unconstrained rows. Shared
sequence cardinality remains unknown so mutation through aliases cannot leave a
stale empty/nonempty proof. Sorting callbacks that observe the shared target via
an alias or parent remain rejected until temporary-empty sorting visibility is
implemented. This guard conservatively rejects observing another shared-list
binding in the enclosing scope as well; scalar parameters with the same spelling
keep their lexical owner.

Stable, definitely bound string owners can be borrowed once at a loop or
generator entry. Indexed characters carry a code-point projection for direct
comparison, while escaping characters retain the configured string semantics.
The proof excludes owner rebinding and unknown attribute/callback effects and
preserves the indexed read's checks and evaluation order. In fixed-width ASCII
mode, proved unit-stride affine reads can use guarded byte spans and ordinary
Rust iterator loops. Guards use captured range arguments, actual owner lengths,
and checked arithmetic for every intermediate index expression. If a guard does
not hold, the original checked Rust loop preserves Python error and side-effect
order. This does not select an interpreter or a different execution backend.
BigInt and Unicode reads retain their selected checked operations.

Immutable string/tuple list elements share `ListType(element)` metadata with
literal, comprehension, stream materialization, indexing, append, copies,
slices, and Python-style output. Proved owned list results can cross function
boundaries. Typed sorting is stable and computes a supported key once per
element. `next` immediately consumes a typed iterator with construction/default
evaluation before its first pull and a positioned `StopIteration` on exhaustion.
Nullable `next` defaults retain the distinction between exhaustion and a yielded
`None`. Escaping iterators, unproved aliases and remaining sequence
methods are still required work. Producer/consumer normalization is being
unified further; these operations do not establish full Python compatibility.

Trusted `sys.stdin`/`.buffer` imports and their `read`/`readline` aliases generate
direct reads through the same buffered input object. Ordinary entry functions
and function-local imports retain scope analysis. Text readers retain newlines
and return an empty string at EOF; binary readers return immutable `Vec<u8>`
values and use ASCII rules for integer splitting/parsing. Builtin `input()`
keeps its distinct EOF and newline behavior. Text input follows the selected
ASCII profile or opt-in strict UTF-8 Unicode profile. Custom/reconfigured
streams and surrogate escapes need further
direct implementation.

Builtin `print` also has its normal `None` result in assignment, nested call,
tuple and short-circuit expression contexts. These calls share the statement
printer's argument capture, formatting and explicit flush behavior. Replacing a
builtin with a function definition still requires callable binding versioning.

Fixed-width decimal `int(text)` and `int(bytes)` conversions use a shared
selected-width accumulator, including captured builtin aliases, lazy/eager word
streams and proved character projections. Signs, underscores, whitespace and
each integer mode's wrapping rules are preserved without an arbitrary-precision
temporary. Conversion-helper selection does not itself construct a standard-input reader. The
Unicode profile uses pinned Unicode 16.0 decimal and numeric-whitespace data;
retained data carries its Unicode notice. BigInt conversions keep exact parsing.


Static module and callable references support integer `math.gcd`, `lcm`,
`isqrt`, `factorial`, `comb`, and `perm`. Internal combinatorial arithmetic is
exact, and the returned result follows the selected integer mode.
Fixed-width results are computed with native integer operations without BigInt
temporaries. Combinations separate powers of two and use an odd modular inverse;
variadic LCM retains bounded factors so intermediate wrapping cannot corrupt
later gcd reductions. Mathematical argument expressions run before binding and
integer-index validation, preserving their effects and Python errors. These
six APIs also support captured references through linked module namespaces;
other mathematical object and function protocols still require direct lowering.

Float literals, variables, ordinary arguments/results, unary signs, truth and
display retain their binary64 representation in every integer mode. Typed
frames can also store and return these values. `int(float_value)` uses the
selected integer representation, including nonfinite conversion errors. General
BigInt/f64 arithmetic and identity-sensitive floating containers remain required
work.

Typed `isinstance` calls retain canonical primitive and container class
identities through aliases and captured arguments. Supported builtin classes
are `int`, `bool`, `float`, `str`, `list`, `tuple`, `dict`, `set`, `range`, `map`,
`zip`, `filter` and `enumerate`; checking an iterator's class does not execute
its callback. Boolean values match `int`. Class-info tuples short-circuit in
order, including invalid later members, and runtime variadic tuples use the
same protocol. This does not add source-class inheritance, metaclass
`__instancecheck__`, or arbitrary union-type objects.

Typed frames dispatch finite list/scalar alternatives for list repetition and
concatenation, including nullable counts and Python operand errors. Supported
list `+=` and `*=` branches mutate the captured list handle; numeric branches
retain ordinary value arithmetic. Child layouts and mutable element identities
are shared with the original containers. Indexed reads dispatch list, fixed or
runtime tuple, text and bytes alternatives, preserving runtime index/type errors
and evaluation order. Sealed incompatible ordering alternatives produce Python
`TypeError` paths. These operations do not narrow globals or captured locals
across calls. Indexed writes through alternative owner layouts, list `+=` from
non-list iterables, user index/subscription special methods and remaining
container protocols still require their native adapters.

Immutable range values can cross typed function returns, locals, closures and
object fields, including finite list/range alternatives. Their existing range
cursor remains independent for each iteration. `list(...)` materialization uses
the shared pull protocol for text/bytes and finite raw-source alternatives,
preserves saved iterator cursors, and raises Python `TypeError` for proved
noniterables. Direct list/range/tuple copy paths remain available and preserve
mutable element handles. Range object identity, display, checked `len(range)`
and escaped generator suspension still need their respective native adapters.

The ten `heapq` operations `heapify`, `heappush`, `heappop`, `heappushpop`,
`heapreplace`, and their `_max` counterparts operate directly on the original
typed list. Supported payloads include immutable integer/bool, text/bytes and
tuple values. Bare floats use Python's strict `<` comparison in every integer mode,
including NaNs. Shared list handles preserve caller/row aliases and capture
the receiver before later arguments run. Floating tuple identity, custom or
fallible comparisons and `merge` remain unfinished.

`heapq.nlargest` and `nsmallest` use the shared typed iterable and callback
adapters, including immediate generator expressions, saved cursors, class fields
and captured keys. Stable ties retain the original input order and object
identity. Count one skips the length shortcut and consumes live input. Otherwise
a count at least a known builtin length snapshots all elements before evaluating
keys. The bounded route retains O(k) entries, evaluates the first k keys before
heap construction, then interleaves each source pull with its key and a checked
heap update. Only retained entries are sorted at the end. Nonpositive counts
construct/validate iteration without pulling values; a checked overflowing range
length still raises before this route, matching Python. User callbacks execute
without source/heap borrows. Errors retain exact original-program/callback
frames and messages; CPython standard-library implementation frames are not
fabricated. Integer/bool counts and supported structural builtin ordering are
implemented. Custom count/index/ordering protocols and floating decorated key
identity/NaN ordering remain precise conversion diagnostics.

The six `bisect`/`insort` names use the same list storage adapter, including
read-only function parameters, shared rows, empty lists, and immutable scalar
or tuple comparisons. Explicit argument expressions run before checked `lo`/`hi`
conversion and before borrowing the captured list. Captured source functions,
closures, lambdas, builtin adapters and bound methods can serve as `key`, as can
`None`. Search applies the key only to visited existing elements; the probe is
already a key. Insertion computes the inserted item key once before checking
negative bounds or taking the default length, then inserts the original item.
Each visited element is retained while its temporary list borrow is released
before the callback, preserving source mutations, aliasing and callback errors.
Binary search uses O(log n) visits without copying the source list.
Arbitrary sequence protocols and custom/fallible comparisons remain unfinished. Module/member aliases and local imports retain their
resolved identities. These adapters support all integer modes; BigInt/float
comparison is still a separate unfinished requirement. Canonical heap/bisection
imports also work inside typed class, closure and linked-module frames. Captured
callee and argument values retain evaluation order, source-list identity and
argument effects before binding/bounds errors. Frame bisection dispatches finite
scalar/list alternatives and raises builtin ordering errors only for elements
actually visited. Custom index/sequence/ordering protocols,
heap stream selection and native-member starred expansion remain explicit
positioned diagnostics. Ordinary vector-only programs retain their direct path.

Module members and standard-input references share a lexical identity resolver.
Function specializations preserve the presence of global names even when their
values are not static callable references. This common reference context is
also used when validating cached specializations and calls between functions.

The frontend owns shared fixed-call signatures used by ordinary functions,
class constructors/methods, and supported module calls. Explicit argument
expressions retain source evaluation order before their values are projected
onto positional-only, ordinary and keyword-only parameters. The binder consumes
captured defaults without reevaluating their Python expressions. Class input
aliases retain a bound flag, so reading an unset alias reports its Python
name error before performing input or copying another alias.

Canonical builtin `divmod(a, b)` uses the shared quotient/remainder kernel on
frames, including saved builtin aliases, passed callables and class fields.
Integral and boolean inputs return an integer pair in every integer mode;
fixed-width normalization follows the same rules as `//` and `%`. Negative
operands retain floor division and divisor-signed remainders. Binary64 pairs
work in every integer mode, including signed zero, and fixed-width modes also
accept mixed integral/binary64 inputs. Explicit argument effects precede binding
and operand errors. Mixed BigInt/binary64 conversion, raw fixed-tuple identity
and user `__divmod__`/`__rdivmod__` dispatch remain positioned boundaries.

Captured builtin `pow(base, exp, mod)` calls on typed frames support integral
arguments in every integer mode, including negative exponents with modular
inverses, signed moduli, keyword binding and Python arithmetic/binding errors.
They share the ordinary integer arithmetic implementation. Saved aliases and
the canonical `builtins.pow` binding preserve callee-before-argument evaluation.
Two-argument integral calls currently require a literal exponent whose value
after selected-width normalization is nonnegative. Dynamic or negative
two-argument exponents, floating/complex power results and user operand special
methods remain required unfinished protocols with positioned `E006` diagnostics.

Definition-time defaults on the typed frame path run once in their original
execution scope, including mutable defaults and calls with effects. Optional
typed module cells distinguish an unset name from `None`, preserve shared list
identity and let functions read the latest assigned global value. Local and
parameter bindings keep their own representations. Finite source-function
values use typed references in module/local bindings, arguments, results,
conditionals, supported containers and object fields. Rebinding or deleting a
module function name updates its optional cell; saved references retain their
original identity and defaults. Calls capture the current callee before their
arguments and dispatch directly to the selected compiled Rust function. Valid
call-only aliases retain their ordinary static path. Supported captured builtins
share the canonical binding and typed captured-argument adapters; mutations of
the `builtins` namespace also affect subsequent builtin fallback reads, while
previously saved aliases keep their value. Repeated definition instances,
callable objects, function
metadata, variadic keyword packs and general
dynamic namespaces still require implementation.

Reading a supported ordinary instance method as a value captures its receiver
in a fresh typed method object. Saved, returned and container-held methods use
the same original function signature and defining module as direct calls.
Repeated reads of the same function/receiver compare equal but have distinct
identity; copying a saved method preserves its identity. Immediate method calls
keep their direct call path. Unbound class methods, descriptor overrides,
`staticmethod`/`classmethod`, method metadata and cyclic receiver ownership still
require implementation.

Positional variadic functions and lambdas capture `*args` in shared immutable
runtime tuples. The common signature binder handles positional-only, defaults,
keyword-only parameters and captured bound receivers before entering compiled
Rust functions. Empty packs use the canonical empty tuple; nonempty calls create
fresh tuple objects and preserve mutable element aliases. Stored/returned packs,
ordinary iteration, indexing, unpacking, display, equality and identity use the
same typed representation. Runtime tuple slicing/ordering and variadic keyword
packs remain required work.

Call-site `*iterable` expansion supports typed lists, fixed/runtime tuples,
ranges, strings, bytes and registered lazy iterators for compiled source
functions, lambdas, captured closures and bound methods, plus builtin `print`.
Several positional segments share the normal signature, default and
keyword-only parameter binder. The captured callee and argument expressions run
in Python order; a sole starred positional source is materialized after keyword
expressions, while mixed/multiple positional segments expand eagerly. Iteration
finishes before binding errors, and expanded mutable elements retain their
identities. Proved ordinary typed sequence print calls retain their existing
direct adapter. Other builtin/member/constructor expansion adapters and
`**mapping` keyword expansion remain unfinished, with specific positioned
diagnostics.

Explicit `raise` supports canonical `ValueError`, `TypeError`, `RuntimeError`
and `StopIteration` classes, captured class aliases and stored instances. Each
constructor keeps its actual typed builtin arguments; mutable list/tuple
payloads retain sharing. Evaluation order, class identity, instance identity,
truth, `str`, `repr` and exact predicates for these builtin types use native
exception carriers. Custom argument display, recursive exception arguments,
subclass construction and exception metadata attributes remain diagnostics.

Stored exceptions retain logical traceback locations across suppression and
later raises. Cleanup records implicit context separately from the direct cause
created by the generator `StopIteration` rule. Current context states are used
for cycle cuts and display; trace states participate in the existing native
cycle collector. This does not implement Python frame objects. Combining a
raised stored exception with `id()` remains a positioned capability boundary
until complete frame-local lifetime roots are represented. Bare re-raise,
`raise ... from ...`, `try`/`except` and custom exception inheritance are separate
capabilities. Generator consumers require their proved exception protocol before
using the direct-cause conversion.

Named nested functions have canonical lexical definition identities and typed
per-invocation environments. Returned and sibling functions preserve captured
list aliases, late writes, `nonlocal` updates/deletion and per-instance mutable
defaults. Nested recursive calls share their enclosing environment while each
factory invocation creates a distinct one. Unset captured names retain their
Python `UnboundLocalError` or free-variable `NameError`, including source frames;
binding errors retain nested qualified function names. Unentered lexical scopes
do not force frame selection or evaluate dormant defaults. Reexecuting a nested
definition in one enclosing invocation, non-definition writes to that callable
binding, and closure/object graphs requiring cycle collection remain required
work and produce specific diagnostics.

Escaping lambdas use their original AST and official signature/body scopes.
Each expression evaluation creates a fresh typed function instance with its own
captured default values. Lexical captures and list-comprehension targets use
shared cells, preserving late binding, nested comprehension lifetimes and
first-iterable evaluation order. Official free-symbol information selects the
environment actually retained by a lambda. Named functions and lambdas share
the same finite callable carrier and direct Rust dispatch. Imported lambda
lifetimes, reflection and cycle collection remain
required work.

Stored `iter`, `filter`, `map` and `zip` values on the frame path have concrete Rust
cursor and callback payloads. Aliases share their cursor and exhaustion state;
callbacks run only when a consumer requests an element. Builtin list, fixed
tuple, range, text and byte sources use typed adapters, including finite source
alternatives. Unicode text advances a byte cursor by each character's UTF-8
length. Source borrows finish before callbacks, so source mutation and recursive
pulls retain Python's evaluation order. These adapters do not interpret Python
instructions.

`map` accepts multiple sources and the Python 3.14 `strict` keyword. It pulls
sources from left to right and stops at the shortest; later calls retain any
consumption that occurred before the shorter source ended. Strict length
mismatches and deferred callback/signature errors retain the original source
frames. The callback uses the same captured-value calling convention as a
normal compiled call. The ordinary immediate integer-word parsing path remains
available when no cursor is saved.

`zip` shares the ordered multi-source cursor kernel, including zero/one/many
sources, the `strict` keyword, aliased inputs and partial consumption before
shorter-source termination. Its results preserve the shared handles of mutable
elements. Finite iterator alternatives propagate deferred element requirements
to each possible source; callbacks retain their original defining scope and
arguments. Existing immediate sorting, set construction and unpacking consumers
retain their ordinary direct path when no stored cursor is needed. General
tuple-object identity and arbitrary iterator protocols remain separate work.

Class values, method signatures, fields, and list elements use the shared
scalar, `TupleType`, `ListType`, `MaybeType`, `NullableType`, and `UnionType`
descriptors. A storage renderer preserves shared instance/list handles. Immutable
values entering allocation members use the common directional value constraints;
a container join does not widen the value inserted into it. The class scope and
control-flow planner still needs migration to the shared semantic graph. Proved
shared mutable handles retain identity through nullable method/function results.
Identity-sensitive floating-point container comparisons remain outside this proof.

A resolved call graph selects ordinary Rust functions for small acyclic class
call paths. Recursive components, their callers and longer chains retain the
typed compiled-future stack. The same typed frames support classless recursive
functions, module writes and definition-time default captures. Selection uses
canonical lexical bindings and reached callable identities before lowering;
lowering failures never select a different backend. Pure call-only aliases can
retain their proved definition identity, while unproved rebinding/deletion is
diagnosed. Both representations share logical recursion depth checks and error
frames. Constructor initialization retains its single Python call frame. These
are compiled Rust function bodies, with no generic source instruction dispatch.

Concrete field reads may be reused inside a loop only when its receiver binding
is stable and the loop has no attribute stores, user calls or inner lexical
scopes. Cache values are initialized at the first actual getter, then dropped at
loop exit. Mutable field contents retain their shared handles. Zero-trip paths,
missing attributes and argument effects keep their original order. This proof
uses the currently closed object/protocol surface; additional dynamic protocols
must extend its effect analysis before using this optimization.

Synchronous class-path list comprehensions use the common producer and generator
plans to emit typed loops. Their first iterable is captured in the enclosing
namespace; targets, later iterables, filters and elements use an isolated logical
scope. Reused target names have separate typed versions, zero-iteration targets
do not escape, and calls retain the callee's lexical namespace. List iteration
loads one shared element handle at a time and releases its borrow before a
callback or compiled function call. Frame set/dict comprehensions use these same
logical plans and scopes, with dictionary keys evaluated before their values.
Escaping generators, async clauses, walrus assignment and arbitrary iterator
protocols remain unfinished.

Nested class-path lists retain shared handles at each mutable level. Fresh list
expressions allocate distinct containers; copy, concatenation, repetition,
extension and in-place repetition preserve inner identity. Existing canonical
list methods operate on these handles, including recursive built-in equality,
search and supported lexicographic list/tuple sorting. Instance equality uses
default object identity rather than structural field equality. Acyclic instance
fields retain shared child handles; deleting a field clears its presence state
without changing surviving aliases. Missing fields remain distinct from fields
containing `None`, including after deletion. Descriptor deletion and finalizers
remain required protocols. Recursive container storage layouts and possible
instance/list ownership cycles remain conservatively rejected. Direct plain-class
cycles use the restricted collector described below. Mixed mutable
alternative carriers, custom comparison protocols and floating element identity
rules remain explicit boundaries.

The shared frontend supplements Python 3.14's inlined list/set/dict tables with
logical comprehension scopes. Official table objects and existing scope IDs are
retained. Targets belong to the appended scopes, while free reads, walrus writes,
class namespaces and nested lambda/generator scopes retain their lexical owners.
This metadata does not itself implement an otherwise unsupported language feature.

Exact builtin list methods share typed signatures and operation lowering across
owned vectors and shared class-scope handles: `append`, `insert`, `remove`, list-to-list `extend`,
`clear`, `reverse`, `copy`, `sort`, `index`, `count`, and `pop`. Receiver names,
fields, and checked row indices are captured before explicit arguments; contents
are borrowed afterward. A callback replacing a class field therefore does not
change the already selected list. Owned row projections retain conservative
parent mutation checks. Class sorting supports proved captured callable keys
through the same compiled-call ABI, including saved bound methods. General
iterables for `extend`, custom ordering, and identity-sensitive float search
remain required work.

`list.insert(index, value)` clips an accepted signed index to the current list
length, checks structural growth, and reports an index outside the platform's
signed size range before borrowing the list. `list.remove(value)` deletes the
first Python-equal element or raises `ValueError`; integer/boolean, text/bytes,
proved tuples, nested shared lists, and default instance identity use their
existing equality adapters. Receiver and argument evaluation retain shared
object identities even when an argument rebinds the receiver field. Removal
captures only the visited shared payload, releases its read borrow before
comparison, and takes a new mutable borrow after comparison. Custom `__index__`
or `__eq__`, floating-object identity (including NaN), and cyclic ownership
remain explicit diagnostics. The live-list storage proof also allows insertion
or removal during ordinary list iteration without borrowing the whole sequence.

On typed compiled frames, `sorted` materializes its input before converting
`reverse` or diagnosing unsupported keywords, then evaluates a captured key
once per element. `list.sort` exposes the temporary empty receiver during key
calls, restores its detached storage on errors, and reports mutations after
key/comparison success. Shared element handles preserve object identity. Stable
native sorting supports integer/boolean, text/bytes and proved structural keys;
floating NaN comparison schedules and custom ordering still need lowering.

Ordinary class lowering currently supports concrete typed instance fields,
constructors, fixed method lookup, tuple results, instance/list aliases, and
recursive methods. Missing fields use typed optional storage. Compiled Rust
futures run on an iterative executor; both successful deep calls and exception
unwinding avoid dependence on the native stack. This separate class proof
still needs integration with common semantic lowering. Inheritance,
descriptors, metaclasses, cyclic field layouts and incompatible
field/result types remain explicit implementation gaps.

Class data namespaces and nested plain classes use the existing linked class
reference carrier. Definitions and private names retain their official source
scope owners; identically named nested classes remain distinct. Class-local
name reads use their initialized namespace before module fallback, while method
globals do not capture the surrounding class namespace. Class scalar/list data
supports aliases, rebinding, deletion, and instance lookup with instance-field
precedence. Hidden namespace storage is excluded from `globals()`. Method
attribute reads retain the actual function reference created after default
capture. Rebinding/deleting method descriptors, class metadata dictionaries,
arbitrary metaclasses and finite alternatives in class constructor dispatch
remain explicit diagnostics. Class-local reads that need a builtin fallback
also require a further lookup adapter. Compiler-created class metadata
references/assignments remain explicit diagnostics. The native traceback formatter does not currently
add CPython's optional spelling suggestions to `NameError` messages.

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

Canonical `itertools.repeat`, `chain`, `islice`, and `pairwise` now use typed
shared cursor states in every integer mode. Construction/evaluation order,
partial consumption, source mutations and callback exhaustion are preserved.
These adapters compose with `map`, `filter`, `zip`, list/comprehension collectors
and ordinary loops without materializing intermediate lists. Custom iterator
protocols and the remaining itertools APIs still need direct adapters.

`itertools.accumulate` also supports ordinary prefix addition and captured binary
callbacks, optional initial values, partial consumption and shared payloads.
Default addition uses the common value-operator planner, including boolean
first-value identity, strings and shared lists. Transient source/callback
`StopIteration` ends one pull without permanently exhausting its source.


`itertools.combinations`, `permutations`, and `combinations_with_replacement`
share the concrete eager pool collector with `product`. Their outputs remain
lazy, retaining input item references and independent iterator progress through
aliases. Explicit small literal ranks use native Rust tuple fields; dynamic
ranks use typed immutable tuple storage, including checked loop unpacking.
Positional/keyword binding, nullable permutation rank, boolean ranks, negative
ranks, checked allocation sizes, source exhaustion and original error frames
follow each API's Python ordering. Ordinary generator expressions can fill
proved eager iterable parameters, including canonical keyword calls, without
an intermediate list. General stored generators and user `__index__` protocols
remain unfinished.

Typed frame loops can consume heterogeneous immutable tuples through the same
registered source cursor used by other containers. Their element families can
contain captured callables or concrete iterators; `next` dispatches finite
iterator alternatives while retaining source callback effects. Invalid
noniterator alternatives raise their runtime `TypeError` at the call site.

Shared deque handles support `rotate`, `reverse`, and registered reverse cursors.
The same reverse-source registry accepts native list/tuple/string/bytes/range
values and finite alternatives of those families; it does not use a VM or create
a temporary list for reversal. Forward and reverse deque cursor exhaustion rules
are intentionally distinct. Ordinary immediate reverse streams retain their
existing direct lowering. Custom reverse/index protocols require additional
native adapters and produce positioned diagnostics.


`functools.reduce` uses typed source cursors and direct callback invocations.
It supports captured functions, lambdas, bound methods and registered builtin
members, optional positional or Python 3.14 keyword `initial`, shared mutable
accumulators, direct generator sinks, source mutation and partial consumption.
Source `StopIteration` finishes collection; a callback's `StopIteration`
propagates, while a generator body's `StopIteration` becomes `RuntimeError`.
Fresh literal source cardinalities can prove that no callback runs, or that
only the initial seed reaches a single callback, without changing evaluation
order. Generic closed accumulator families retain subsequent type changes.

Source-function return summaries use normalized control-flow returns and
official lexical owners. Proved formal/literal result dependencies retain
per-call families while the original function executes through its normal ABI.
Rebound, deleted or captured formals do not get an alias proof. Container fields
remain shared and reflect mutation through aliases, callbacks and defaults.
Other unresolved predicates retain conservative result unions; unsupported
member operations on those unions still produce positioned diagnostics.
Reached container formals with local binding changes select typed frames before
lowering; shadowed, copied, scalar-only and unreached bindings keep their
existing selection behavior.

BigInt integral true division now shares the existing exact integer-ratio
rounding kernel across direct scalar and frame operations, including overflow,
subnormal rounding, signed zero and zero denominators. This is not general
mixed BigInt/binary64 arithmetic support.

BigInt mode supports native binary64 arithmetic for builtin int/bool/float
operands, including finite alternatives, NaN, infinities, signed zero,
subnormals and Python division errors. Mixed integral operands are rounded
once through `Int.ratio(1)` and reject conversion overflow. Both operand
expressions evaluate before primitive numeric conversion begins. Integral
true division keeps its existing exact-ratio implementation, while otherwise
integral programs keep their static selection. Floating power/complex results
and custom numeric conversion protocols remain separate adapters.

Canonical `math.sqrt`, `floor`, `ceil` and `trunc` use shared typed numeric
adapters on ordinary and frame paths, including imported/captured aliases and
finite callable alternatives. Floor/ceil/trunc preserve builtin integral
values exactly and normalize float-to-integer results in the selected integer
mode. Sqrt converts integrals once, using fallible exact `Int.ratio(1)` for
BigInt, then applies native binary64 square root. Signed zero, NaN, infinities,
negative-input diagnostics, binding errors and closed nonnumeric type errors
retain Python 3.14 behavior and source frames. Simple fixed-width calls and
integral BigInt rounding retain static selection; BigInt float results use
typed frames selected before generation. Custom `__floor__`, `__ceil__`,
`__trunc__`, `__float__` and index protocols are not simulated. Ordinary module
support emits reached math kernels across function specializations, including
when unused-code pruning is disabled.

Admitted math namespaces preserve proved member rebinding through shared
module cells. Captured old callables retain their identity, functions read
the current member, and argument callbacks cannot replace the callee already
captured for the current call.

Canonical `math.log`, `log2` and `log10` return binary64 values for builtin
int/bool/float arguments and captured callable alternatives. Integral zero or
negative arguments keep the integer-domain diagnostic, while floating domain
errors include round-trip values such as negative zero. NaN, infinity, tiny
positive floats and log-base zero division retain Python behavior.

Positive BigInt values beyond binary64 range use an exact ratio against a
power of two to obtain a rounded mantissa and exponent, including carry at
the upper mantissa boundary. The logarithm identity combines native mantissa
and exponent terms; guaranteed-overflow direct conversion is skipped above
1024 bits. Both source arguments evaluate before conversion, then the value
logarithm precedes optional-base conversion and division. Custom numeric
conversion protocols remain positioned unsupported diagnostics.

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

Canonical class declarations based on `typing.NamedTuple` use typed tuple
payloads with nominal record metadata. Nested declarations, captured factory
aliases, positional/keyword construction, trailing defaults, field reads,
`_fields`, repr, tuple equality/order, unpacking and iteration are supported.
Field annotations do not coerce values. Mutable field/default payloads retain
their shared handles. Constant fixed-layout slices and `tuple(record)` produce
plain tuples. Constructors retain Python argument/default evaluation order and
argument-binding errors.

Functional `NamedTuple(...)` factories, user-defined record methods, observable
annotation evaluation, record identity, field descriptor mutation, dynamically
sized fixed-tuple slices and expanded record construction remain positioned
unsupported diagnostics. Heterogeneous named/plain tuple dictionary-key storage
also remains unsupported; ordinary compatible record keys use structural tuple
hashing and equality. This support does not replace imported Python algorithms
with prewritten implementations.

Canonical `float` construction shares one typed conversion adapter across
ordinary numeric code, saved builtin aliases, callbacks and linked frames.
Omitted arguments produce positive zero; existing binary64 values retain their
bits, including signed zero and nonfinite values. Fixed integers convert to
binary64 directly; BigInt uses the exact `Int.ratio(1)` rounding path and reports
`OverflowError: int too large to convert to float` instead of silent infinity.
The ASCII parser validates signs, decimal/exponent syntax, separators and
special values without a character vector or Unicode tables. Normal numeric
text needs no normalization allocation. Unicode text uses the existing pinned
decimal-digit parser; bytes always retain ASCII whitespace/digit rules.
Invalid conversion errors include the original repr, and builtin call binding
preserves argument effects before errors. Unimplemented custom numeric methods
remain explicit diagnostics. Other `math` APIs are independent capabilities.

Linked native instances support `isinstance(value, source_class)` through their
captured class-definition references. Saved class/builtin aliases, finite class
arguments and nested classinfo tuples preserve short-circuit behavior, including
invalid later members. Matching uses actual class-object identity, including
same-named classes from different modules. Source inheritance and metaclass
instance-check protocols still require their own registered adapters. This does
not implement finite class-constructor unions or new class-object admission.

`functools.cmp_to_key` retains its captured comparator for ordinary `sorted`
and `list.sort` keys. Each comparison enters the original compiled function
with the actual shared element handles and tests its result against zero.
The native fallible Powersort kernel follows CPython 3.14.4's run detection,
binary insertion, galloping and stable merge schedule. Reverse sorting keeps
tie stability. A failed in-place sort restores the same partial permutation
before propagating its original callback exception and user source frames;
callbacks observe the temporarily detached list just as in Python.

Factories preserve capture order, alias identity and closure ownership. Empty
or single-item inputs do not invoke the comparator. Recursive comparator
functions use the existing compiled future ABI, with no Python operation
interpreter. Exposed KeyWrapper object construction/attributes/comparisons,
other ordering consumers and custom rich-comparison results remain explicit
boundaries. The retained CPython-derived kernel carries its required PSF
notice only when generated output actually contains it.

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

Typed frame assignment supports extended starred unpacking with prefix,
remainder and trailing targets, using the original target AST. Canonical
`map(int, input().split())` creates the ordinary shared integer cursor for a
starred target; fixed-count eager unpacking remains available for fixed
targets. Existing iterator aliases share their consumed position. No stores
at one unpack level occur until that level has captured its items and passed
the size check. Nested targets then store in Python order. The fresh remainder
list uses its allocation's solved element representation, so later mutations
can widen its element kind without copying or retagging the source iterable.

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

Comprehension and generator target adapters invoke that same unpack plan with
their own lexical binding/store callbacks. They retain outer-iterable capture,
ordered nested clauses and filters, local target lifetimes, late-bound closure
cells and generator error frames. No synthetic target or rewritten source is
used. Ordinary `for` targets share the assignment path as well.

Loop-executed nested function definitions use per-execution default data and
identity. The enclosing lexical binding retains the current data without an
environment pointer; captured function references carry both that data and
their lexical environment. This preserves saved old functions, escaped getters
of the current binding, mutable defaults, positional-only/keyword-only binding,
variadic arguments, late-bound body cells and `nonlocal` state. All explicit
defaults evaluate before the current function binding changes.

Default values remain explicit lifetime graph edges: a callable default can
capture the same owning environment and create a real cycle. Such unproved
cycles retain the existing positioned cycle-collection diagnostic. This does
not implement arbitrary function-object attributes, multiple distinct `def`
nodes for one lexical binding, or rebinding/deleting that binding.

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
prerequisite for source numeric/reflected operator dispatch. Programs without
singleton values omit its runtime declaration.


Native frame `for` and `while` loops support exhaustion `else` suites. Normal
exhaustion and `continue` enter the suite; a completed `break`, `return`, or an
unsuppressed exception skips it. Break edges join after the suite, preserving
zero-trip bindings and values assigned only by the suite. Inner loop suites
can transfer to the enclosing loop. Context-manager cleanup runs before a
pending transfer takes effect, including suppression of an error that replaced
a pending break. Literal true/false while conditions omit unreachable suites
without resolving their contents. These loops compile to typed Rust control
flow, without a bytecode interpreter or generic execution loop.

Method acquisition on finite plain-instance alternatives, including optional
receivers and multiple source classes, uses the same native bound-method carrier
as a single receiver. Lookup captures the original receiver once before call
arguments. Missing attributes on `None` and other closed receiver types raise
`AttributeError` at the attribute expression, before any arguments execute.
Saved aliases retain method identity, receiver mutation and shared return values;
each new attribute read creates a fresh method object. Calls retain ordinary
signature/default binding and can pass these methods to existing typed iterator
consumers. Mixed data/method attributes, builtin descriptor families and
nonfunction descriptors across finite receivers remain positioned capability
diagnostics.

Direct cycles among plain source-class instances use a native trial-deletion
collector when every field of the cyclic classes contains builtin scalar values,
`None`, direct instance handles or finite alternatives of those kinds. Ordinary
source functions remain compiled Rust functions. Only eligible cyclic classes
register weak handles; programs with an acyclic class ownership type graph
receive no collector or changed scope storage. Collection counts each direct
field edge, treats external aliases and
borrowed nodes as roots, traces reachable nodes and clears unreachable optional
fields without invoking Python callbacks. Geometric collection thresholds avoid
repeated full scans while a live graph grows. Container-, callable- and
closure-mediated cycles, custom finalizers, weak references and resurrection
remain explicit unsupported protocols; this is not general arena/container GC.


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

Plain source classes support direct numeric special-method dispatch for binary,
reflected and augmented arithmetic, shifts, bitwise operations, unary `+`, `-`
and `~`, and the six rich comparisons. Calls retain the actual class namespace,
captured function defaults, original operands and shared mutable payloads.
`NotImplemented` advances to the next appropriate slot; equal arithmetic types
skip the reflected slot, while rich comparisons can try both receivers.
`__ne__` without its own method delegates to `__eq__` and negates its truth value.
Comparison expressions preserve nonboolean results and short-circuit chains.
Implicit source callbacks invalidate field caches across loops. Captured
`operator` binary callables and default `itertools.accumulate` addition use the
same direct dispatch plan.

Numeric special methods implemented by descriptors, subclass-priority rules,
custom three-argument `pow`, and container comparisons that invoke user rich
comparisons remain separate capabilities with positioned diagnostics. These
boundaries do not substitute pointer equality or a generic execution engine for
Python callbacks. The unchanged ACL lazy-segment-tree practice K example is
covered by standalone generated Rust in every integer mode.

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

Immediate canonical map/filter callbacks use captured original-node descriptors
when the shared solver proves their scalar/immutable item, default and result
representations and existing effect/ownership rules admit ordinary code. Lambda
defaults run once before iterable construction, including empty input; callback
bodies remain lazy. Source-function and canonical math callbacks use the same
captured-value invocation protocol. Unproved captures, mutable defaults, possible
StopIteration and float identity use typed callable storage selected before
emission. These ordinary callbacks emit Rust loops without function-object
allocation or fabricated Python Call/Name AST nodes. Float-valued map input to
sum remains a positioned unsupported consumer capability.

Live ordinary list loops retain source identity with per-pull borrows when
mutation or source binding changes require it. The allocation solver propagates
bounded source-owner sets through builtin lazy adapters and comprehensions;
it does not infer object identity from equal shapes or allocation sites.
Lexical value deletion drops the binding independently from references held by
iterators and aliases. Maybe-unbound cells retain positioned NameError and
UnboundLocalError behavior; the ordinary static callable/import identity ABI
does not yet expose generic deletion cells.

Closed scalar loops on typed function frames borrow stable local lists once for the loop. Reads, writes, augmented assignments and `len` share that borrow; mutable regions require a single list binding. The proof includes nested control flow and exhaustion clauses, preserves zero-trip and first-read name errors, and excludes callbacks, rebinding, escaping containers and accesses through other possible aliases. Other loops retain their native identity-preserving accesses.

Proved builtin integer and boolean `bit_count()` and `bit_length()` calls inside
generator expressions do not require a StopIteration conversion boundary.
Their use alone therefore does not change the storage and loops of the enclosing
program. The proof uses resolved receiver types and callable identities;
source-defined methods with the same names and real `next()` effects retain
Python's PEP 479 exception chain. Unresolved callable effects remain conservative.

Ordinary loop transfers omit unused exit and feedback carriers when the original
binding cannot be read on those paths and its concrete storage has no Python
cleanup protocol. This preserves source assignments, mutations, exceptions,
zero-iteration behavior and live post-loop targets. Generator and comprehension
targets use their own official scopes. Captured cells, namespace observers and
unresolved calls retain conservative storage, including effects of reached
source callees and captured callbacks. An annotation without a value leaves the
existing binding intact.

Fixed builtin tuple projections from stable function-local bindings copy only
the selected field. A short immutable reference replaces cloning the whole
tuple, including chained fixed projections; the selected result is owned before
evaluating later arguments or callbacks. Original unbound-local errors remain.
Captured, module-owned, comprehension and generator bindings, widened local
storage and named tuple receivers keep their existing storage paths.

Canonical classmethods used directly as a call's attribute callee retain their
receiver and actual function in a stack payload, after attribute lookup and
before evaluating explicit arguments. This avoids allocating a temporary method
object for an identity that cannot escape that immediate call. Stored methods,
finite mixed targets, instance attribute overrides and expanded calls retain
their ordinary native method-object representation. Argument errors, captured
defaults, class namespace changes and source traceback frames keep their normal
evaluation rules.

Typed instances whose solved data fields are all fixed-width integers, booleans,
floats or None use independent `Cell<Option<T>>` slots inside the same stable Rc
object identity. Field access avoids a whole-object runtime borrow check.
Uninitialized and deleted fields remain distinct from Python None, and class
namespace fallback retains its original class-definition handle. BigInt integer
fields, reference payloads and cycle-collected objects keep their native shared
borrowed layout. This representation choice does not restrict accepted programs.


Plain classes with only proved fixed Copy scalar fields can use native value
storage when every reached write occurs in an implicit, nonescaping constructor
or a unique fresh local before publication. Constructor receivers borrow the
actual new value; factories update their real local slot. Aliases, captures,
postpublication mutations, explicit initializer calls, reflective namespaces,
identity/representation observations, custom attribute protocols, inheritance,
and unproved callable identities retain the normal native reference layout.
Definition-time positional and keyword-only defaults count as publication.
Indirect builtin observers in callback values and expanded arguments retain
reference storage as well.
Integer fields in BigInt mode retain reference storage. This optimization does
not specialize a class, module, library, or source name and does not remove
constructor, callback, namespace, or error effects.

An independent identity-demand certificate can omit private per-instance ID
storage and its TLS allocator for those value classes. It uses the original
reached source, solved contained types and canonical callable identities, with
a closed finite source/import/callback graph and no collector or finalizer.
Identity, display, hashing, container comparison and retained instance-method
consumers keep ordinary identity storage. Any retained canonical `id` capability,
or any unproved value owner, preserves every allocation in the shared logical
ID sequence, including allocations belonging to other owners. Unrecorded calls
are never assumed dead: their enclosing original statement must independently
be excluded by the same reached-statement filter used by native emission.
Unused default display implementations are omitted with the IDs; no fabricated
identity or representation is substituted. Actual class-definition metadata,
classmethod receiver identities, constructor/argument effects, missing-field
errors and exception frames remain unchanged. Unproved programs keep their
existing native representation. BigInt integer fields remain reference-backed;
other Copy fields can use the same identity-demand proof in every integer mode.

Compiled frames can also use scalar value facts that are separate from type
constraints. Original bindings, call parameters/results, instance fields and
registered list allocation origins contribute to one finite compile-time graph.
Every official producer and heap mutation must be modeled or widen the affected
fact to unknown, including imports, assignment expressions, with/loop targets,
deletion, comprehensions and in-place list extension. Missing inputs and unseeded
cycles are unknown; only an explicitly empty allocation can certify no elements.
Different constructor/context values and alias writes keep generic native code.
Integer literals and each supported operation normalize at the selected width;
expensive folds are bounded and remain native operations when unproved.

The initial consumer exposes a proved integer/boolean field value after the
original getter succeeds. It retains receiver evaluation, field-presence errors,
constructors, context operations, callbacks and source exception frames. A list
whose every possible inserted element agrees can supply a successful-read value
fact without assuming a nonempty stack or suppressing its runtime lookup.
Without a separate storage proof, class metadata and physical field slots remain
unchanged. Ordinary-path value
fact integration and proofs eliminating redundant lookups/calls remain unfinished;
this foundation does not claim their removal or a performance target.

A constant scalar field can omit its physical Copy slot only when independent
immutable-value, definite-initialization and observer certificates also hold.
Logical field names/indices and actual class metadata remain intact. Original
receiver/RHS expressions, constructor/default calls, callbacks and exceptions
still execute; the erased getter returns a normalized typed constant after its
actual receiver is captured. Missing or conditionally initialized fields,
class-member fallbacks, publication-time mutation, deletion, reflection,
unproved defaults/contexts and reference-backed integers keep their storage.
Canonical source/builtin identities come from solved callable payloads and
official bindings, including finite mixed callees; spelling alone never proves
an observation-safe builtin. This storage change does not establish removal of
the retained source/runtime calls or a performance target.

Ordinary scalar fields of a proved concrete local instance are read through its
existing local slot without cloning the receiver. This applies to fixed-width
integers, booleans, floats and None, while the existing getter retains missing
attribute errors and the existing lazy loop cache retains first-read timing.
Captured, module, comprehension and generator bindings, mixed receiver storage,
class namespace lookup and custom attribute protocols keep ordinary lowering.
Mutable and BigInt fields also retain their existing owned access paths.

Selected value classes declared directly in a source module can share their
class metadata after successful module initialization. Copies of those values
copy the shared metadata reference. Initializing or failed imports and distinct
runtime class generations retain owned metadata; reuse checks actual class
identity. At most one metadata record per eligible source definition is pinned
for the generated program's lifetime. Normal class lookup, classmethod binding
and explicit requests for an owned class reference retain the actual class and
module globals. Source classes with unproved value semantics keep their native
reference representation.


Synchronous source parameters of a proved value class can borrow their captured
actual value when every use of the official parameter binding is a plain Copy
scalar field load. Rebinding, captures, forwarding, identity observations and
escaping uses keep the owned native ABI. The physical call adaptation runs after
normal argument capture, so later arguments, exceptions and callback evaluation
retain their original order. Address-taken Rust functions, async/unsafe/const/extern headers, physical class
layouts with a custom destructor (including aliases), futures and unknown
physical call shapes keep their original ABI.


Native recursion-depth counters can be omitted for an entirely synchronous,
closed, acyclic source graph with a certified depth below 256 and a sealed
default limit of 1000. Import initializer edges are verified explicitly. A
physical graph bounds synthetic call spans between source activations; positive
counter cycles and opaque trait callbacks prevent this optimization. Recursion
limit setters (including captured adapters), runtime compilation/reflection,
generators, finalizers, unproved calls and changing control state retain the
ordinary native guard. Actual calls and exception-frame propagation remain.

Already-proved immutable value classes can use scalar field slots without an
additional missing-value tag. A canonical initializer must assign every field
on every normal exit, and every initializer read must follow its assignment.
The proof follows official parameter bindings and structured branches. Field
deletion, class member sharing, raw or reflective allocation, unproved receiver
escape, loops and structured cleanup retain the previous optional field layout.
Fresh factory updates preserve the same initialized slots. Missing fields and
first-read errors keep their existing behavior; this optimization adds no new
language capability and does not change integer normalization.


Exact synchronous class-reference parameters can borrow their captured class
when every use of the official parameter is an ordinary class data attribute
load and its owner has the closed value-class capability. Rebinding, aliases,
closures, forwarding, returns and method/descriptor attribute uses retain the
owned parameter ABI. Attribute values, including mutable list contents, are
still looked up and captured in their original order. Class identity and stored
bound methods remain the actual runtime objects. Unknown Rust ABI shapes,
address-taken functions, futures and observable destructors prevent borrowing.


Eligible value classes can retain a plain process-lifetime reference to their
class metadata when module execution is proved unique. This requires the full
closed finite-depth certificate and every reached fixed-name import to be an
original direct module-body statement. Runtime importer/reload/loader APIs and
import-hook/cache namespaces prevent this specialization. Failed-import retry,
callback imports, conditional/loop imports and unproved programs retain the
owned-capable metadata carrier. Constructors still evaluate their actual class
reference and arguments in the original order. Class aliases and pending module
initialization keep their nominal identity.


The synchronous context-borrow ABI also covers generated constructors. It uses
the same shared-field, nonescaping-use, synchronous-header and function-address
guards as ordinary source calls. Retained or returned contexts remain explicit
owned clones; futures, qualified/escaping functions and custom context drops
retain their original ABI. Constructor arguments and module context captures
keep their original evaluation order.

Immutable class callable lookup: for a proved Copy-field value class defined directly in its module, an unchanged direct method binding can use its compiled function identity and the captured class module without loading the namespace slot. Class-body rebinding, function metadata observations, lexical captures and unproved value layouts retain ordinary native namespace lookup. Definition-time defaults and descriptor binding keep their original order.

Ordinary native unpacking supports mixed name and builtin list-index targets, including character swaps, fixed nested tuple/list targets, dynamic tuple sources and generator consumers. Each unpack level captures its values before storing targets from left to right; a later index observes earlier assignments and an error preserves earlier stores. Shared list elements retain their handles. Unproved slice, mapping or attribute places report the missing ordered store adapter at the original target. Class-field and descriptor targets retain their existing class-emitter path.


Module context switches can borrow the existing execution context when the
actual globals Rc is identical. A different globals object retains the ordinary
owned context, including failed-import generations with the same module number.
This optimization requires the finite synchronous runtime certificate and a
shared context layout without custom destruction. Only compiler-private module
bindings in synchronous functions with borrow-only context uses qualify.
References must call an unqualified direct function with a concrete
`&ClassScope` parameter; unknown, generic, qualified or retained references keep
the original context. Module expressions keep their normal evaluation order,
and retained or returned context clones remain owned.

Builtin list reads with an exact integer literal `0` or `-1` use the first or last element directly, retaining the original positioned IndexError and mutable element identity. Other literals, computed indices, booleans, custom index protocols and other sequence types keep their existing native paths. This applies to ordinary, shared nested and typed class list storage without a runtime fallback.


A certified finite synchronous program can share the execution-context control,
input/output and module-cache roots as one common owned allocation. Each actual
root constructor creates its own common state. Module switches and retained
context clones share that state, while globals keep their original distinct Rc
identity. Existing inner root Rc types and explicit retained clones are
preserved. Exact private constructors/layouts and a global field-use seal are
required; aliases, custom destruction, alternate construction/destructuring,
root moves/replacement, layout/count/address observers and unproved runtime
forms retain the original native context. Source calls, stream cursors, module
initialization/failure, exceptions and frame propagation remain unchanged.

Function-local list bindings with fresh allocations and no escaping aliases can
use owned `Vec<T>` storage even on the class/frame path. Physical layout follows
the official binding separately from the Python element type: homogeneous lists
use their concrete element type, while heterogeneous lists use a finite enum of
the inferred alternatives. Repetition preserves shared child-object identities.
Direct indexing, indexed stores, `len`, `append` and `pop` access the vector
without cloning the outer list handle or taking a RefCell loan for each access.
Canonical list construction,
list literals, comprehensions and literal repetition construct vectors directly.
Direct `for` loops and immediate builtin `enumerate` loops also keep an owned
vector when the official binding has a single fresh definition and no escaping
uses. Each pull clones only the current element and releases its Rust reference
before executing the body, so element writes, `append` and `pop` affect later
pulls just as in Python. Nested loops retain independent cursors. Rebinding,
retained iterators and unproved enumeration arguments keep shared storage.
Captured, returned, aliased, reflectively observed or otherwise unproved list
bindings retain identity-preserving shared storage. Fixed heterogeneous records
use the separate positional and physical-tuple proofs described below.

Direct builtin `str.upper()` and `str.lower()` calls are supported in ASCII
mode. `bytes.upper()` and `bytes.lower()` preserve non-ASCII bytes in either
string mode. Receivers and explicit arguments retain their evaluation order,
including calls that raise a signature error. Classes with methods of the same
name retain ordinary method dispatch. Unicode string casing still reports the
missing Python-compatible case-mapping and conditional-casing implementation.
Zero-argument immediate calls can also project a finite builtin receiver domain
containing strings or bytes plus integers, booleans, floats or None. Only text
alternatives contribute a returned value; other alternatives raise AttributeError
with their actual builtin type name. The receiver is evaluated once. Mixed
receiver calls with explicit, keyword or expanded arguments, stored bound methods,
and user-class alternatives still need a pre-argument attribute lookup adapter.


A nonescaping builtin list field of a plain native class can reside directly as
an `Option<Vec<Element>>` in its existing identity-preserving object. Fresh
at-most-once constructor assignment, official self bindings, canonical implicit
initialization and every reached field use must be proved. Object aliases share
the same vector; escaping/replaced/shared-argument lists keep their ordinary
shared storage. Scalar, finite-union, heterogeneous tuple and shared-reference
elements retain their existing ABI and child identities.

Selected indexed places capture the owner and check field presence before index
effects. Element snapshots and stores use short owner borrows that end before
source callbacks. Assignment/AugAssign keep Python evaluation and error order;
old element destruction happens after releasing the owner borrow. Reflection,
custom allocation/attribute protocols, initializer reset, GC/finalizers and
owner address/representation observations prevent this initial optimization.
The generic list type is unchanged and no whole-vector cloning getter is emitted.


Ordinary modules and function wrappers can select fixed-list positional
constraints without declaring a class. The choice runs before either emitter
and uses reached shared AST/type facts plus solved allocation provenance for
unpack, constant slot, record iteration and keyed sort consumers. Merely
printing, measuring or leaving a heterogeneous literal unused does not force
that route; uniform ordinary scalar paths remain available. The immutable
analysis heap stores symbolic type/allocation constraints, never source values
or runtime object uniqueness. The positional emitter still validates slot
mutation and escape independently. Failed lowering never selects another
emitter, and no marker class or input-source rewrite is performed.

Reached heterogeneous list literals with closed per-element facts can select
positional analysis even when coarse aggregate mutation constraints are unresolved.
This is an upfront capability choice, not a type or ownership proof: the selected
model still validates indexed updates, aliases and every operation. Compatible
constant-slot stores and alias-preserving augmented updates use the existing
finite typed list storage. Ordinary print/length-only and homogeneous list code
keeps its existing selection. Correlated writes through a union of list and
non-list receiver kinds use the finite builtin indexed-store adapter where its
receiver and index protocols are proved.

Indexed assignment through finite builtin receiver alternatives supports actual
list storage and Python errors for immutable builtin arms. The receiver and
index are captured once after the assignment RHS; augmented assignment captures
the old element before its RHS. Each list arm uses its own inferred element
representation, retaining shallow aliases and child identity. Custom item/index
protocols remain separate capabilities. This adapter does not introduce a VM or
change list storage globally; ordinary homogeneous arrays keep their selection.

Immediate calls to a proved immutable, monomorphic synchronous classmethod can pass the captured class reference and its actual defining module directly to the original compiled body. Callee evaluation precedes explicit arguments; the existing argument binder, defaults, exception frames and recursion rules remain in effect. Retained methods and unproved mutable class/function layouts keep their ordinary native callable representation.

A private fixed-schema heterogeneous function-local list can use a separate
physical tuple place such as `Option<(NativeInt, NativeText)>`. The semantic
value remains a Python list. Selection requires original lexical bindings, one
fresh literal definition, converged position types equal to the literal fields,
and no whole-list alias, capture, return, identity observation, resize or slot
type change. Constant indices, builtin `len`, compatible stores and explicit
unpack access the physical fields directly. Unpack snapshots all source values
before target effects; binding and bounds failures retain their source positions.
Child values keep their existing shallow value/reference ABI. Unproved records,
dynamic indices and interprocedural list values retain the existing vector or
shared-handle storage.

A fixed-schema heterogeneous class list field can also use a physical tuple in
its existing object. It first satisfies the nonescaping owned-field proof, then
requires one original literal, stable concrete slot types and only constant
integer indices or builtin `len`. Each selected slot has its own typed getter
and setter, without a vector allocation or a uniform tagged-element accessor.
Literal elements are evaluated before the target owner, and short owner borrows
end before callbacks or old-value destruction. Missing fields and bounds errors
retain their original order. Owner aliases and shared child values preserve
identity. Whole-list aliases/unpack, runtime indices, field replacement, resize
or changing slot types retain the existing vector/shared-list representation.

An exact synchronous constructor call returned with the same nominal instance type can forward its compiled Result directly. Argument/callee captures, defaults, actual module context, source call guards and error frames remain in their original order. Non-tail expressions, result type conversions, recursive callers, context-manager control returns and unproved call forms retain their existing native return path.

Immediate global calls with one proved source-function definition capture the actual stored module and closure/function-instance payload before explicit arguments. Global initialization errors, shared defaults, captured cells and failed-import module generations retain their existing behavior. Callable storage in every scope uses the exact target-family representation described below.

Private list length shortcuts require the original callee to be an unshadowed official module lookup of builtin `len`. Inline-comprehension targets with that spelling retain their actual captured callable, argument evaluation, mutation and error behavior. The positional effect analysis separately recognizes an exact captured builtin `len` payload as read-only while retaining all lookup and argument code, so safe builtin aliases keep their existing slot precision. These rules apply to local vectors, fixed local records and private class list/record fields.

Private function-local matrices with structurally fresh rows use recursive `Vec<Vec<T>>` (and deeper vectors) when every use is a scalar index path or a length query. Scalar rows can be fresh literals, comprehensions, or literal repetitions; outer repetition, row aliases, row replacement/resizing, captures and whole-row escapes keep shared list storage. Intermediate indices are checked before later index expressions, and assignment/augmented-assignment retain Python evaluation order. The same pre-emission certificate enables eligible classless programs only when all reached argument contexts agree on the nested scalar kind; flat arrays and polymorphic matrix functions keep their existing selection. Global semantic list types and other function/field/parameter ABIs are unchanged.

Reached native class/frame functions can instantiate independent original-AST bodies for closed argument-type contexts instead of carrying a joined numeric or object union through every call. The original definition still owns callable identity, signature, defaults, module and capture state; instances share semantic object/container effects while keeping separate local/argument/result cells. The initial certificate excludes constructors, decorated/generic functions, variadics, lexical capture environments, nested callable/generator state and mutable container result carriers. Exact scalar, instance and tuple arguments are instantiated with a finite context budget; unproved or widened contexts use their already analyzed ordinary native body. This changes neither backend selection nor source binding/evaluation order and introduces no runtime interpreter.

Parameter-only synchronous frame calls can omit an unused invocation module view and lexical-parent argument after original-source effect analysis. Defaults, observed function identity, source operator calls and error frames retain their semantics; required module and environment captures use their actual source payloads. Bodies with captured/global names, nonliteral defaults, nested environments, explicit calls, augmented assignments, or unproved implicit truth/iteration/index protocols keep their ordinary native context.

Native callable storage uses the exact proved target family in globals, locals, arguments, fields, defaults and captured cells. A singleton source function, builtin or bound method has its own payload struct; a real finite join has an enum containing only its possible targets. Required source captures use the actual defining module, lexical/lambda environment and repeated-definition instance data. Bound method payloads retain their actual receiver and function. Capturing these values still precedes explicit arguments, so later binding replacement, shared defaults, errors and identity behave as before. Singleton calls unpack their payload and invoke the compiled target directly; static ordinary function aliases retain their existing direct native specializations.

A proved private non-Copy class instance can use an owned Rust struct with
borrowed method receivers instead of an `Rc<RefCell<...>>` object. Selection
requires every instance to originate in one fresh official function-local
constructor binding, with no whole-object alias, capture, return, parameter
escape, identity/representation observation or custom lifetime protocol.
Existing field proofs independently choose embedded vectors or shared child
handles; vectors are never cloned to simulate object sharing. Method lookup
and actual defining-module capture precede arguments, while mutable receiver
loans begin only after arguments have been evaluated. Reentrant method/index
calls, conditional field initialization, zero-trip unbound locals and source
errors retain their order. Shared, escaping and unproved objects keep their
existing native storage. This first placement certificate excludes class
record fields and explicit initializer reentry.

Private callable module and lexical-environment captures are omitted when the
original invocation/default summary proves them unused and every reached value
consumer has a closed transport/callback or nonobserving role. The certificate
covers exact native payloads in locals, formals, fields, globals and containers;
it does not replace source functions with reconstructed current-module values.
Original definition/default evaluation, binding-existence checks and receiver
lookup still occur in Python order. Same-target identity/equality, implicit
container comparisons, hashed keys, metadata, unproved native roles and heap or
address/lifetime observers retain the required original captures. A saved bound
method always retains its actual receiver and method-object identity. Recursive,
suspended or unclosed graphs retain the existing complete native payload.

A proved readonly primitive function or method parameter uses its existing
native argument directly, without a second `Option` local or repeated unbound
checks. The signature and Python argument/default evaluation remain unchanged.
This requires both the official symbol table and every original binding
producer to exclude rebinding, deletion, capture and namespace observation.
Inline comprehension targets retain their separate official ownership. The
initial certificate covers exact fixed-width integers, bool, float and None;
BigInt integers, unions, non-Copy values, captured or mutable parameters,
suspended/recursive functions and generator-expression bodies retain their
existing storage.

Immutable plain class bindings can supply an explicit borrowed defining-class
context to certified synchronous instance methods and their closed same-module
factories. The certificate uses original binding producers and every reached
entry, rather than a lexical class number: failed imports can execute the same
definition with different module globals. Eligible own-class construction and
immediate builtin type tests use that actual context without another module
global lookup. Callee lookup, arguments, defaults, constructor bodies and source
errors retain their original order. A by-value receiver gets an independent
metadata snapshot before its value is moved into the call. Mutable builtins or
class bindings, unbound or retained method entries, externally called factories
and unproved publication paths keep their existing native binding/context code.
This proof changes neither semantic class identity nor backend selection.
