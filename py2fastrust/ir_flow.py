"""Conservative control/data flow for the common executable IR.

The analysis never executes Python expressions. Definitions are static instruction
identities; joins retain every reaching definition and possible type. Unknown
operations and user calls keep an explicit top value rather than inventing a
native type or a direct call target. Exception/finally edges overapproximate the
runtime's transfers. The analysis supplies proofs for Rust code generation.
"""

from collections import deque
from dataclasses import dataclass, field, replace
import builtins
from types import BuiltinFunctionType

from .ir import SourceLocation
from .typeflow import TypeSet

UNKNOWN = TypeSet(unknown=True)
UNBOUND = TypeSet(maybe_unbound=True)

# Closed built-in calls shared with the existing AST reachability proof. Their
# arguments still have to originate from closed built-in values to rule out
# descriptor/conversion/hash callbacks changing bindings.
LEAF_BUILTINS = frozenset({
    'abs', 'ascii', 'bin', 'bool', 'bytes', 'chr', 'complex', 'dict', 'divmod',
    'float', 'format', 'frozenset', 'hash', 'hex', 'id', 'input', 'int',
    'isinstance', 'issubclass', 'len', 'list', 'oct', 'ord', 'pow', 'print',
    'range', 'repr', 'reversed', 'round', 'set', 'slice', 'str', 'sum', 'tuple',
})
# Exclude site-installed Python objects such as help/quit: their protocols
# are not closed built-in operations, and availability is not a core guarantee.
_BUILTINS = frozenset(name for name,value in vars(builtins).items()
                      if isinstance(value,(type,BuiltinFunctionType)))
_BUILTIN_VALUES = {'None':'none','True':'bool','False':'bool','__debug__':'bool',
                   'Ellipsis':'ellipsis','NotImplemented':'notimplemented'}
_CALL_TYPES = {
    'ascii':'str', 'bin':'str', 'bool':'bool', 'bytes':'bytes', 'chr':'str',
    'complex':'complex', 'dict':'dict', 'divmod':'tuple', 'float':'float',
    'format':'str', 'frozenset':'frozenset', 'hash':'int', 'hex':'str', 'id':'int',
    'input':'str', 'int':'int', 'isinstance':'bool', 'issubclass':'bool', 'len':'int',
    'list':'list', 'oct':'str', 'ord':'int', 'print':'none', 'range':'range',
    'repr':'str', 'reversed':'iterator', 'set':'set', 'slice':'slice', 'str':'str',
    'tuple':'tuple',
}


@dataclass(frozen=True, order=True)
class BindingVersion:
    code: int
    pc: int
    name: str
    kind: str = 'store'


@dataclass(frozen=True)
class ValueFact:
    types: TypeSet = UNKNOWN
    definitions: frozenset[BindingVersion] = frozenset()
    targets: frozenset[str] = frozenset()
    unknown_target: bool = True
    unknown_definition: bool = False
    loaded_names: frozenset[str] = frozenset()
    # Closed built-in values cannot run arbitrary Python through their protocols.
    trusted: bool = False
    item_types: TypeSet = UNKNOWN

    def join(self, other):
        return ValueFact(self.types.join(other.types),
                         self.definitions | other.definitions,
                         self.targets | other.targets,
                         self.unknown_target or other.unknown_target,
                         self.unknown_definition or other.unknown_definition,
                         self.loaded_names | other.loaded_names,
                         self.trusted and other.trusted,
                         self.item_types.join(other.item_types))


TOP = ValueFact()


def _value(kind, *, trusted=True, items=UNKNOWN):
    return ValueFact(TypeSet.from_kind(kind), trusted=trusted, item_types=items)


@dataclass(frozen=True)
class FlowState:
    bindings: dict[str, ValueFact]
    stack: tuple[ValueFact, ...] | None = ()
    unknown_effects: bool = False

    def join(self, other):
        names = self.bindings.keys() | other.bindings.keys()
        bindings = {name:self.bindings.get(name, TOP).join(other.bindings.get(name, TOP))
                    for name in names}
        stack = None
        if self.stack is not None and other.stack is not None and len(self.stack) == len(other.stack):
            stack = tuple(a.join(b) for a,b in zip(self.stack, other.stack))
        return FlowState(bindings, stack, self.unknown_effects or other.unknown_effects)


@dataclass(frozen=True, order=True)
class Edge:
    target: int
    kind: str = 'normal'
    handler: int = -1


@dataclass(frozen=True)
class CallSite:
    location: SourceLocation
    callee: ValueFact
    arguments: tuple[ValueFact, ...]
    implicit: bool = False

    @property
    def direct_unmodified_leaf(self):
        return (not self.implicit and not self.callee.unknown_target
                and not self.callee.unknown_definition
                and not self.callee.types.maybe_unbound
                and not self.callee.types.unknown
                and len(self.callee.targets) == 1
                and self.callee.targets <= LEAF_BUILTINS
                and self.callee.loaded_names == self.callee.targets
                and not self.callee.definitions)


@dataclass
class InstructionFlow:
    location: SourceLocation
    entry: FlowState | None = None
    exit: FlowState | None = None
    exits: dict[Edge, FlowState] = field(default_factory=dict)
    successors: tuple[Edge, ...] = ()
    definition: BindingVersion | None = None
    uses: dict[str, frozenset[BindingVersion]] = field(default_factory=dict)
    unknown_uses: frozenset[str] = frozenset()
    call: CallSite | None = None


@dataclass
class CodeFlow:
    code: int
    instructions: dict[int, InstructionFlow]
    definitions: dict[BindingVersion, SourceLocation]
    entry_definitions: frozenset[BindingVersion] = frozenset()
    complete: bool = True
    reasons: set[str] = field(default_factory=set)

    @property
    def calls(self):
        return {pc:flow.call for pc,flow in self.instructions.items()
                if flow.entry is not None and flow.call is not None}

    @property
    def proves_leaf_calls(self):
        return (self.complete and all(
            flow.entry.stack is not None and flow.exit.stack is not None
            and not flow.entry.unknown_effects and not flow.exit.unknown_effects
            and (flow.call is None or flow.call.direct_unmodified_leaf)
            for flow in self.instructions.values() if flow.entry is not None))


@dataclass
class ProgramFlow:
    codes: dict[int, CodeFlow]
    signature: tuple


@dataclass(frozen=True)
class _Handler:
    setup: int
    target: int
    end: int
    finally_: bool


def _signature(program):
    return tuple((code.filename, code.kind, tuple(code.locals), tuple(code.globals),
                  tuple(code.nonlocals), tuple(code.frees), tuple(code.comp_locals), repr(code.params),
                  tuple((op.op, repr(op.args), op.line, op.column) for op in code.ops))
                 for code in program.codes)


def analyze_program(program):
    """Analyze a standalone Program; code zero has fresh default builtins.

    Imported/function scopes start with unknown ambient bindings. Use
    analyze_code(fresh_module=False) for externally supplied eval/exec scopes.
    The cache refreshes after any change to executable instructions or scopes.
    """
    signature = _signature(program)
    cached = getattr(program, 'flow', None)
    if cached is not None and cached.signature == signature:
        return cached
    analysis = ProgramFlow({i:analyze_code(code, i, fresh_module=i == 0)
                            for i,code in enumerate(program.codes)}, signature)
    program.flow = analysis
    return analysis


def _initial(code, code_id, fresh_module):
    names = set(code.locals) | set(code.globals) | set(code.frees) | set(code.nonlocals)
    names |= {op.args[0] for op in code.ops
              if op.op in {'Load','Store','Delete','LoadCell','StoreCell'} and op.args}
    parameters = (code.params.positional + code.params.kwonly
                  + ([code.params.vararg] if code.params.vararg else [])
                  + ([code.params.kwarg] if code.params.kwarg else []))
    bindings = {}
    for name in names:
        if name in parameters:
            bindings[name] = ValueFact(UNKNOWN, frozenset({BindingVersion(code_id,-1,name,'parameter')}))
        elif fresh_module and code.kind == 'Module' and name == '__name__':
            bindings[name] = _value('str')
        elif fresh_module and code.kind == 'Module' and name in _BUILTIN_VALUES:
            bindings[name] = _value(_BUILTIN_VALUES[name])
        elif fresh_module and code.kind == 'Module' and name in _BUILTINS:
            bindings[name] = ValueFact(TypeSet.from_kind('builtin'), targets=frozenset({name}),
                                       unknown_target=False, trusted=True)
        elif name in code.locals and (fresh_module and code.kind == 'Module' or
                code.kind in {'Function','Comprehension'} and name not in code.globals and name not in code.nonlocals):
            bindings[name] = ValueFact(UNBOUND,trusted=True)
        else:
            bindings[name] = ValueFact(UNKNOWN.join(UNBOUND),unknown_definition=True)
    return FlowState(bindings)


def _handlers(code):
    regions = []
    for pc,op in enumerate(code.ops):
        if op.op not in {'SetupExcept','SetupFinally'} or not op.args:
            continue
        target = op.args[0]
        if not isinstance(target,int) or not 0 <= target < len(code.ops):
            continue
        end = target
        if op.op == 'SetupFinally':
            depth = 0
            for end in range(target, len(code.ops)):
                name = code.ops[end].op
                if name == 'SetupFinally':depth += 1
                elif name == 'EndFinally':
                    if not depth:break
                    depth -= 1
        regions.append(_Handler(pc,target,end,op.op == 'SetupFinally'))
    return regions


_NO_RAISE = frozenset({'Const','Keyword','Pop','Dup','Swap','Rotate','Jump',
    'SetupExcept','SetupFinally','PopHandler','ClearException','Nop'})


def _edges(code, regions):
    result = {}
    size = len(code.ops)
    for pc,op in enumerate(code.ops):
        edges = set()
        following = pc + 1
        if op.op in {'Jump','Break','Continue'}:
            if op.args:edges.add(Edge(op.args[0], 'jump'))
        elif op.op in {'JumpFalse','JumpTrue','ForIter'}:
            if following < size:edges.add(Edge(following, 'iterate' if op.op == 'ForIter' else 'fallthrough'))
            if op.args:edges.add(Edge(op.args[0], 'exhausted' if op.op == 'ForIter' else 'branch'))
        elif op.op not in {'Return','Raise'} and following < size:
            edges.add(Edge(following))
        if op.op == 'Return':edges.add(Edge(-1,'return'))
        if op.op == 'Raise':edges.add(Edge(-2,'raise'))
        if op.op not in _NO_RAISE:edges.add(Edge(-2,'exception_exit'))
        if op.op in {'Return','Break','Continue'}:
            for region in regions:
                if region.finally_ and region.setup < pc < region.target:
                    edges.add(Edge(region.target, 'finally', region.setup))
        if op.op == 'EndFinally':
            for region in regions:
                if region.finally_ and region.end == pc:
                    for transfer in code.ops[region.setup+1:region.target]:
                        if transfer.op in {'Break','Continue'} and transfer.args:
                            edges.add(Edge(transfer.args[0], 'resume'))
                    # An error entering an inner finally can leave through an
                    # enclosing except/finally, even without an explicit Raise.
                    for outer in regions:
                        if outer.setup < region.setup < outer.target:
                            edges.add(Edge(outer.target,'exception',outer.setup))
        if op.op not in _NO_RAISE:
            for region in regions:
                if region.setup < pc < region.target:
                    edges.add(Edge(region.target,'exception',region.setup))
        if op.op == 'YieldFrom':edges.add(Edge(pc,'resume'))
        result[pc] = tuple(sorted(edges))
    return result


def _invalidate(state, code_id, pc):
    bindings = {}
    for name,value in state.bindings.items():
        changed = ValueFact(UNKNOWN.join(UNBOUND), frozenset({BindingVersion(code_id,pc,name,'effect')}),
                            unknown_definition=True)
        bindings[name] = value.join(changed)
    stack = None if state.stack is None else tuple(value.join(TOP) for value in state.stack)
    return FlowState(bindings, stack, True)


def _binary(operator, left, right):
    kinds = left.types.kinds | right.types.kinds
    if left.types.unknown or right.types.unknown:return UNKNOWN
    numeric = kinds <= {'int','bool','float','complex'}
    if operator in {'&','|','^'} and kinds == {'bool'}:return TypeSet.from_kind('bool')
    if numeric:
        if 'complex' in kinds:return TypeSet.from_kind('complex')
        if operator == '**':return TypeSet(frozenset({'float','complex'}) if 'float' in kinds else frozenset({'int','float'}))
        if 'float' in kinds or operator == '/':return TypeSet.from_kind('float')
        return TypeSet.from_kind('int')
    if left.types.kinds == right.types.kinds and len(kinds) == 1 and operator == '+':
        if kinds <= {'str','bytes','list','tuple'}:return TypeSet(kinds)
    return UNKNOWN


def _transfer(code, code_id, pc, state, flow, fresh_module):
    op = code.ops[pc]
    name,args = op.op,op.args
    stack = None if state.stack is None else list(state.stack)
    bindings = state.bindings.copy()
    opaque = False
    def pop():
        nonlocal stack
        if stack is None:return TOP
        if not stack:
            stack = None
            return TOP
        return stack.pop()
    def pops(count):return list(reversed([pop() for _ in range(count)]))
    def push(value):
        if stack is not None:stack.append(value)
    def joined_types(values):
        result = TypeSet()
        for value in values:result = result.join(value.types)
        return result
    if name == 'Const':
        value = args[0]
        kind = {type(None):'none', bool:'bool', int:'int', float:'float', complex:'complex', str:'str', bytes:'bytes'}.get(type(value))
        push(_value(kind) if kind else TOP)
        opaque = kind is None
    elif name == 'Keyword':push(_value('str'))
    elif name in {'Load','LoadCell'}:
        key = args[0]
        storage = '@cell:' + key if name == 'LoadCell' else key
        value = bindings.get(storage, TOP)
        if name == 'Load' and (code.kind == 'Class' or
                code.kind != 'Module' and (key not in code.locals or key in code.globals or key in code.nonlocals)):
            value = value.join(replace(TOP,unknown_definition=True))
        elif name == 'Load' and fresh_module and code.kind == 'Module' and value.types.maybe_unbound and not state.unknown_effects:
            # DELETE_NAME/conditional assignment can fall back to captured
            # builtins. Keep the binding's modification versions for the guard.
            if key in _BUILTINS:
                fallback = ValueFact(TypeSet.from_kind('builtin'),targets=frozenset({key}),unknown_target=False,trusted=True)
            elif key in _BUILTIN_VALUES:fallback = _value(_BUILTIN_VALUES[key])
            else:fallback = None
            if fallback is not None:
                value = value.join(fallback)
                value = replace(value,types=replace(value.types,maybe_unbound=False))
            elif key in vars(builtins):value = value.join(TOP)
        flow.uses = {key:value.definitions}
        flow.unknown_uses = frozenset({key}) if value.unknown_definition else frozenset()
        push(replace(value, loaded_names=frozenset({key})))
    elif name in {'Store','StoreCell','Delete'}:
        key = args[0]
        version = BindingVersion(code_id,pc,key,'delete' if name == 'Delete' else 'store_cell' if name == 'StoreCell' else 'store')
        value = ValueFact(UNBOUND,trusted=True) if name == 'Delete' else pop()
        if code.kind == 'Class' and name != 'StoreCell':value = value.join(replace(TOP,unknown_definition=True))
        storage = '@cell:' + key if name == 'StoreCell' else key
        bindings[storage] = replace(value, definitions=frozenset({version}), loaded_names=frozenset())
    elif name == 'Pop':pop()
    elif name == 'Dup':
        value = pop();push(value);push(value)
    elif name == 'Swap':
        right,left = pop(),pop();push(right);push(left)
    elif name == 'Rotate':
        count = args[0]
        values = pops(count)
        if values:values = values[-1:] + values[:-1]
        for value in values:push(value)
    elif name in {'BuildList','BuildTuple','BuildSet','BuildDict','BuildSlice','BuildString','BuildTemplate'}:
        values = pops(args[0] * (2 if name == 'BuildDict' else 1))
        kind = {'BuildList':'list','BuildTuple':'tuple','BuildSet':'set','BuildDict':'dict',
                'BuildSlice':'slice','BuildString':'str','BuildTemplate':'template'}[name]
        trusted = all(value.trusted for value in values)
        opaque = name in {'BuildSet','BuildDict','BuildSlice','BuildString'} and not trusted
        push(_value(kind,trusted=trusted,items=joined_types(values) if kind == 'tuple' else UNKNOWN))
    elif name == 'Binary':
        right,left = pop(),pop();trusted = left.trusted and right.trusted
        opaque = not trusted
        push(ValueFact(_binary(args[0],left,right),trusted=trusted))
    elif name == 'Unary':
        value = pop();opaque = not value.trusted
        kinds = value.types.kinds
        result = TypeSet.from_kind('bool') if args[0] == 'not' else (
            TypeSet.from_kind('int') if not value.types.unknown and kinds <= {'int','bool'} else value.types)
        push(ValueFact(result,trusted=value.trusted))
    elif name == 'Compare':
        right,left = pop(),pop();trusted = args[0] in {'is','is not'} or left.trusted and right.trusted
        opaque = not trusted
        push(_value('bool') if trusted else TOP)
    elif name in {'JumpFalse','JumpTrue'}:opaque = not pop().trusted
    elif name in {'GetIter','GetYieldFromIter'}:
        value = pop();opaque = not value.trusted
        items = (TypeSet.from_kind('int') if not value.types.unknown and value.types.kinds and value.types.kinds <= {'range','bytes'} else
                 TypeSet.from_kind('str') if value.types.kinds == {'str'} else value.item_types)
        push(_value('iterator',trusted=value.trusted,items=items))
    elif name == 'ForIter':pass  # Each edge has a different stack effect.
    elif name == 'GetItem':
        key,value = pop(),pop();trusted = key.trusted and value.trusted;opaque = not trusted
        slice_only = not key.types.unknown and key.types.kinds == {'slice'}
        maybe_slice = key.types.unknown or 'slice' in key.types.kinds
        if value.types.kinds == {'str'}:types = TypeSet.from_kind('str')
        elif value.types.kinds == {'bytes'}:
            types = TypeSet.from_kind('bytes') if slice_only else TypeSet.from_kind('int')
            if maybe_slice and not slice_only:types = types.join(TypeSet.from_kind('bytes'))
        elif value.types.kinds == {'tuple'}:
            types = TypeSet.from_kind('tuple') if slice_only else value.item_types
            if maybe_slice and not slice_only:types = types.join(TypeSet.from_kind('tuple'))
        elif value.types.kinds == {'list'} and slice_only:types = TypeSet.from_kind('list')
        else:types = UNKNOWN
        push(ValueFact(types,trusted=trusted,item_types=value.item_types if slice_only else UNKNOWN))
    elif name in {'SetItem','DelItem'}:
        values = pops(3 if name == 'SetItem' else 2);opaque = not all(value.trusted for value in values)
    elif name == 'Call':
        values = pops(args[0] + len(args[1]));callee = pop()
        flow.call = CallSite(flow.location,callee,tuple(values))
        safe = not callee.unknown_target and len(callee.targets) == 1 and callee.targets <= LEAF_BUILTINS and all(value.trusted for value in values)
        target = next(iter(callee.targets)) if safe else None
        opaque = not safe
        kind = _CALL_TYPES.get(target)
        types = TypeSet.from_kind(kind) if kind else UNKNOWN
        if target in {'abs','round','sum','pow'}:
            types = UNKNOWN  # Numeric promotion/iterable contents need more proof.
        items = TypeSet.from_kind('int') if target == 'range' else UNKNOWN
        push(ValueFact(types,trusted=safe,item_types=items))
    elif name == 'CallEx':
        values = pops(3 if args[0] else 2)
        flow.call = CallSite(flow.location,values[0] if values else TOP,tuple(values[1:]),True)
        push(TOP);opaque = True
    elif name == 'MakeFunction':
        values = pops(args[1] + len(args[2]))
        push(ValueFact(TypeSet.from_kind('function'),targets=frozenset({f'function:{args[0]}'}),unknown_target=False))
    elif name == 'PrepareClass':
        push(TOP);push(_value('function',trusted=False));opaque = True
        flow.call = CallSite(flow.location,TOP,(),True)
    elif name == 'GetAttr' or name == 'GetSpecialAttr':pop();push(TOP);opaque = True
    elif name in {'SetAttr','DelAttr'}:pops(2 if name == 'SetAttr' else 1);opaque = True
    elif name == 'Unpack' or name == 'UnpackEx':
        value = pop();opaque = not value.trusted
        count = args[0] if name == 'Unpack' else args[0]+args[1]+1
        for index in reversed(range(count)):
            if name == 'UnpackEx' and index == args[0]:push(_value('list',trusted=value.trusted))
            else:push(ValueFact(value.item_types,trusted=value.trusted))
    elif name == 'FormatValue':
        values = pops(2 if args[1] else 1);trusted = all(value.trusted for value in values)
        opaque = not trusted;push(_value('str',trusted=trusted))
    elif name == 'MakeInterpolation':
        values = pops(2 if args[2] else 1);push(_value('interpolation',trusted=all(value.trusted for value in values)))
    elif name in {'LoadException','LoadExceptionType','LoadExceptionTraceback'}:push(TOP)
    elif name == 'ExceptionMatch':pops(2);push(_value('bool'))
    elif name == 'Return':pop()
    elif name == 'Raise':pops(args[0])
    elif name == 'Yield':pop();push(TOP);opaque = True
    elif name == 'YieldFrom':pop();push(TOP);opaque = True
    elif name in {'Jump','Break','Continue','SetupExcept','SetupFinally','PopHandler','ClearException','EndFinally','Nop'}:pass
    else:
        stack = None;opaque = True
        return _invalidate(FlowState(bindings,None,state.unknown_effects),code_id,pc),False
    result = FlowState(bindings,None if stack is None else tuple(stack),state.unknown_effects)
    return (_invalidate(result,code_id,pc) if opaque else result),True


def analyze_code(code, code_id=0, *, fresh_module=False, max_updates=100_000):
    """Compute a monotone fixed point, including zero-iteration/exception paths.

    Ambient globals/builtins are unknown unless the caller explicitly proves a
    fresh standalone module. Closed-container trust is stronger than an outer
    type tag and must not be reused as an alias/mutation summary.
    """
    flows = {pc:InstructionFlow(SourceLocation(code_id,pc,code.filename,op.line,op.column))
             for pc,op in enumerate(code.ops)}
    result = CodeFlow(code_id,flows,{})
    if not flows:return result
    if len(flows) > 20_000:
        result.complete = False;result.reasons.add('instruction limit');return result
    for pc,op in enumerate(code.ops):
        if op.op in {'Store','StoreCell','Delete'}:
            version = BindingVersion(code_id,pc,op.args[0],'delete' if op.op == 'Delete' else 'store_cell' if op.op == 'StoreCell' else 'store')
            flows[pc].definition = version;result.definitions[version] = flows[pc].location
    regions = _handlers(code)
    edges = _edges(code,regions)
    for pc,successors in edges.items():
        if any(not isinstance(edge.target,int) or edge.target not in flows and edge.target not in {-1,-2} for edge in successors):
            result.complete = False;result.reasons.add('invalid control-flow target')
        flows[pc].successors = tuple(edge for edge in successors if edge.target in flows or edge.target in {-1,-2})
    flows[0].entry = _initial(code,code_id,fresh_module)
    result.entry_definitions = frozenset(version for value in flows[0].entry.bindings.values()
                                         for version in value.definitions)
    pending,queued = deque([0]),{0}
    updates = 0
    while pending:
        pc = pending.popleft();queued.discard(pc)
        flow = flows[pc];entry = flow.entry
        exit,known = _transfer(code,code_id,pc,entry,flow,fresh_module)
        if not known:
            result.complete = False;result.reasons.add(f'unsupported operation: {code.ops[pc].op}')
        flow.exit = exit
        for value in exit.bindings.values():
            for version in value.definitions:
                if version.kind == 'effect':result.definitions[version] = flows[version.pc].location
        for edge in flow.successors:
            outgoing = exit
            if code.ops[pc].op == 'ForIter' and exit.stack is not None:
                stack = list(exit.stack)
                if edge.kind == 'iterate':
                    iterator = stack[-1] if stack else TOP
                    stack.append(ValueFact(iterator.item_types,trusted=iterator.trusted))
                elif edge.kind == 'exhausted' and stack:stack.pop()
                outgoing = replace(exit,stack=tuple(stack))
            if edge.handler >= 0:
                outgoing = entry.join(exit) if edge.kind == 'exception' else exit
                setup = flows[edge.handler].entry
                depth = len(setup.stack) if setup is not None and setup.stack is not None else None
                if depth == 0:
                    stack = ()
                elif edge.kind == 'exception' and depth is not None and entry.stack is not None and exit.stack is not None:
                    stack = tuple(a.join(b) for a,b in zip(entry.stack[:depth],exit.stack[:depth]))
                    if len(stack) != depth:stack = None
                else:
                    stack = outgoing.stack[:depth] if outgoing.stack is not None and depth is not None else None
                outgoing = replace(outgoing,stack=stack)
            flow.exits[edge] = outgoing
            if edge.target < 0:continue
            target = flows[edge.target]
            merged = outgoing if target.entry is None else target.entry.join(outgoing)
            if target.entry != merged:
                target.entry = merged
                if edge.target not in queued:pending.append(edge.target);queued.add(edge.target)
                updates += 1
                if updates > max_updates:
                    result.complete = False;result.reasons.add('fixed-point limit');return result
    return result
