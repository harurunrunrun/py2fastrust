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
an incomplete subset of the required Python language. Recursion outside the
class path, closures, exceptions, general object models, user-defined generators,
dynamic execution, general imports
and many mixed-type/alias cases still require direct lowering. An `E006`
diagnostic makes that gap explicit; it does not satisfy the missing feature.

Immediate `for`, reduction, `list`, `set`, `sorted`, `next`, unpacking, and string
`join` consumers use the same normalized producer plans. Core builtin aliases
are resolved from definite lexical bindings; a spelling alone does not prove
builtin identity. An alias absent on a branch or loop edge is not treated as a
definitely bound callable. Splitting text or bytes uses a common source adapter,
and proved integer projections share a parser for `map`, generators, and eager
comprehensions. Lazy unpacking converts exactly the first excess item before
raising a cardinality error, while eager comprehensions finish before unpacking.
Producer conversion errors and consumer cardinality errors retain their own
source frames. General dynamic callable values and conflicting core-name
rebinding still require direct implementation.

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
bindings without dispatching by their old spelling. User key callbacks, general
mutable candidates, and tuple float identity rules require further lowering.

Generator expressions consumed by `sum`, `any`, `all`, `min`, or `max` lower to
typed Rust loops, including proved nested clauses, filters, and
`map`/`filter`/`enumerate`/`zip` adapters. Construction and iteration keep their
different evaluation times, and short-circuit consumers stop without evaluating
later elements. Escaping generators and unproved mutation still need direct
implementation. Floating-point compensated `sum` is not implemented here.
Ordinary `for` loops share these typed adapters, including string character
iteration, `reversed`, destructuring `enumerate`/`zip`, and generator producers.
They preserve `break`, `continue`, `return`, and loop `else`. A possibly unset
scalar target uses `Option<T>` with a positioned Python unbound-name error on
read, including zero-iteration and filtered-generator paths.

All integer modes support uniquely owned flat integer lists, indexed reads and
updates, copied lists, ordinary list operations, `sorted` with supported immutable key results,
and slicing with positive or negative steps. Slices make independent lists.
Nested lists with proved integer/boolean, text/bytes, None, or recursively
immutable tuple payloads use typed shared handles in every integer mode. Named
row aliases, shallow `copy`, repetition/concatenation, item mutation, ordinary
function parameters/results, live list iteration, and printing retain object
identity. Captured row handles survive replacement or clearing of the parent.
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
before stable sorting, including with `reverse=True`. Mutable arguments/defaults,
variadic packing, escaping closures and callbacks observing the list currently
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

This adapter currently requires a proved unique deque owner and identity-safe
immutable elements. General mutable aliases, mutation during active iteration,
deque function arguments, mutable element storage, floating/custom search
protocols, deque
subclasses, arithmetic operators, and the remaining general object protocols are
still required work. Unsupported cases remain positioned diagnostics; no VM or
implicit Python execution supplies these operations.

Proved immutable tuple keys use structurally typed Rust sets and dictionaries
in every integer mode. Numeric keys preserve Python's bool/int equality while
retaining the original key, and dictionaries retain insertion order. BigInt
integer keys use the same typed containers. Mutable values, observable set
iteration, and general container aliases remain unfinished.

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

The ten `heapq` operations `heapify`, `heappush`, `heappop`, `heappushpop`,
`heapreplace`, and their `_max` counterparts operate directly on the original
typed list. Supported payloads include immutable integer/bool, text/bytes and
tuple values. Bare fixed-width floats use Python's strict `<` comparison,
including NaNs. Shared list handles preserve caller/row aliases and capture
the receiver before later arguments run. Floating tuple identity, custom or
fallible comparisons, `merge`, `nlargest`, and `nsmallest` remain unfinished.

The six `bisect`/`insort` names use the same list storage adapter, including
read-only function parameters, shared rows, empty lists, and immutable scalar
or tuple comparisons. Explicit argument expressions run before checked `lo`/`hi`
conversion and before borrowing the captured list. `key=None` is supported;
callable keys, arbitrary sequence protocols, and custom/fallible comparisons
remain unfinished. Module/member aliases and local imports retain their
resolved identities. These adapters support all integer modes; BigInt/float
comparison is still a separate unfinished requirement.

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
call-only aliases retain their ordinary static path. Captured builtins,
repeated definition instances, bound methods, callable objects, function
metadata, dynamic argument expansion, emitted variadic functions and general
dynamic namespaces still require implementation.

Class values, method signatures, fields, and list elements use the shared
scalar, `TupleType`, `ListType`, `MaybeType`, `NullableType`, and `UnionType`
descriptors. A storage renderer preserves shared instance/list handles. Immutable
values entering allocation members use the common directional value constraints;
a container join does not widen the value inserted into it. The class scope and
control-flow planner still needs migration to the shared semantic graph. Nullable
mutable handles and identity-sensitive floating-point container comparisons remain
outside this direct proof.

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
callback or compiled function call. Class-path set/dict comprehensions, escaping
generators, async clauses, walrus assignment and arbitrary iterator protocols
remain unfinished.

Nested class-path lists retain shared handles at each mutable level. Fresh list
expressions allocate distinct containers; copy, concatenation, repetition,
extension and in-place repetition preserve inner identity. Existing canonical
list methods operate on these handles, including recursive built-in equality,
search and supported lexicographic list/tuple sorting. Instance equality uses
default object identity rather than structural field equality. Recursive storage
layouts and possible instance/list ownership cycles are conservatively rejected
until allocation-cycle proofs or cycle-aware collection exist. Mixed mutable
alternative carriers, custom comparison protocols and floating element identity
rules remain explicit boundaries.

The shared frontend supplements Python 3.14's inlined list/set/dict tables with
logical comprehension scopes. Official table objects and existing scope IDs are
retained. Targets belong to the appended scopes, while free reads, walrus writes,
class namespaces and nested lambda/generator scopes retain their lexical owners.
This metadata does not itself implement an otherwise unsupported language feature.

Exact builtin list methods share typed signatures and operation lowering across
owned vectors and shared class-scope handles: `append`, list-to-list `extend`,
`clear`, `reverse`, `copy`, `sort`, `index`, `count`, and `pop`. Receiver names,
fields, and checked row indices are captured before explicit arguments; contents
are borrowed afterward. A callback replacing a class field therefore does not
change the already selected list. Owned row projections retain conservative
parent mutation checks. Class sorting currently requires `key=None`; ordinary
sorting retains its proved callable-key path. General iterables for `extend`,
class key callbacks, and identity-sensitive float search remain required work.

Ordinary class lowering currently supports concrete typed instance fields,
constructors, fixed method lookup, tuple results, instance/list aliases, and
recursive methods. Missing fields use typed optional storage. Compiled Rust
futures run on an iterative executor; both successful deep calls and exception
unwinding avoid dependence on the native stack. This separate class proof
still needs integration with common semantic lowering. Inheritance,
descriptors, metaclasses, escaped methods, cyclic field layouts and incompatible
field/result types remain explicit implementation gaps.

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
