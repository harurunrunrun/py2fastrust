"""Pure allocation constraints and structured CFG fixed points for native code.

The semantic graph contains types, allocation sites and control-flow edges. It
does not contain source values, invoke an emitter, or execute Python code.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import dataclass,field
from types import MappingProxyType

from .call_semantics import FunctionSignature,normalize_call,CallBindingError
from .literal_semantics import Literal
from .native_types import (TupleType,TupleSequenceType,ListType,SharedListType,DequeType,deque_type,EmptyType,EMPTY,NullableType,UnionType,
                          join_types,union_type,alternatives,unmaybe,is_maybe,kind_tag,shared_payload)
from .native_key_types import SetType,DictType
from .references import BuiltinIdentity,DequeConstructor,CORE_BUILTINS


@dataclass(frozen=True)
class Value:
    alternatives: frozenset[object]=frozenset()
    unbound: bool=False
    unknown: bool=False

    def join(self,other):
        return Value(self.alternatives|other.alternatives,self.unbound or other.unbound,
                     self.unknown or other.unknown)


BOTTOM=Value()
MISSING=Value(unbound=True)
UNKNOWN=Value(unknown=True)


def value(kind):return Value(frozenset({kind}))


@dataclass(frozen=True)
class Variable:
    allocation: tuple
    field: str


@dataclass(frozen=True)
class ShapeConstraint:
    """A lower-bound layout fact, never a runtime object identity."""
    kind: object


@dataclass(frozen=True)
class Allocation:
    """A MAY-alias heap-site summary, never proof of one runtime object.

    Repeated executions of one lexical allocation can denote distinct Python
    objects. Consumers must preserve runtime identity and incoming references.
    """
    site: tuple
    category: str


@dataclass(frozen=True)
class TupleValue:
    fields: tuple[Value,...]


@dataclass(frozen=True)
class IteratorValue:
    item: Value
    sources: frozenset[Allocation]=frozenset()
    may_call:bool=False
    source_inputs:frozenset[Value]=frozenset()


@dataclass(frozen=True)
class Computed:
    operation: str
    operands: tuple[Value,...]


@dataclass(frozen=True)
class Projection:
    receiver: Value
    role: str
    index: int|None=None


@dataclass(frozen=True)
class FunctionValue:
    definition: int
    defaults: tuple[tuple[str,Value],...]


@dataclass(frozen=True)
class MethodValue:
    receiver: Value
    name: str
    site: int


@dataclass(frozen=True)
class CallFact:
    """Evaluated abstract identities/arguments; source values are never stored."""
    identity: Value
    positional: tuple[Value,...]
    keywords: tuple[tuple[str,Value],...]

    def join(self,other):
        return CallFact(self.identity.join(other.identity),
                        tuple(left.join(right) for left,right in zip(self.positional,other.positional)),
                        tuple((name,left.join(right)) for (name,left),(_,right) in zip(self.keywords,other.keywords)))


@dataclass(frozen=True)
class Expression:
    site: int
    operation: str
    operands: tuple=()
    data: object=None


@dataclass(frozen=True)
class Operation:
    site: int
    operation: str
    operands: tuple=()
    blocks: tuple=()
    data: object=None


@dataclass(frozen=True)
class Function:
    site: int
    name: str
    signature: FunctionSignature
    body: tuple[Operation,...]
    defaults: tuple[tuple[str,Expression],...]


@dataclass
class Flow:
    normal: dict|None
    breaks: list=field(default_factory=list)
    continues: list=field(default_factory=list)
    returns: Value=BOTTOM


def target_names(target):
    if target[0]=="name":return {target[1]}
    if target[0]=="unpack":return set().union(*(target_names(child) for child in target[1]))
    if target[0]=='starred':return target_names(target[1])
    return set()


def merge(states):
    states=[state for state in states if state is not None]
    if not states:return None
    result={}
    for name in set().union(*(state.keys() for state in states)):
        item=BOTTOM
        for state in states:item=item.join(state.get(name,MISSING))
        result[name]=item
    return result


class ConstraintFailure(Exception):
    def __init__(self,node):
        super().__init__("native type constraints did not reach a finite fixed point")
        self.node=node


class SemanticGraph:
    """Normalize syntax once. Solving uses only these semantic operations."""
    def __init__(self,unit):
        self.unit=unit
        self.functions={}
        self.nodes={}
        self.expressions={}
        self.loops={}
        self.literals={}
        self.body=self.block(unit.tree.body)
        for name in ("nodes","expressions","loops","literals","functions"):
            setattr(self,name,MappingProxyType(getattr(self,name)))

    def site(self,node):
        site=self.unit.ordinal(node)
        self.nodes[site]=node
        return site

    def name(self,node):
        try:return self.unit.name_for(node)
        except KeyError:return node.id if isinstance(node,ast.Name) else node.attr

    def target(self,node):
        if isinstance(node,ast.Name):return ("name",self.name(node))
        if isinstance(node,ast.Starred):return ('starred',self.target(node.value),self.site(node))
        if isinstance(node,(ast.Tuple,ast.List)):
            return ("unpack",tuple(self.target(item) for item in node.elts))
        if isinstance(node,ast.Subscript):return ("index",self.expression(node.value),self.expression(node.slice))
        if isinstance(node,ast.Attribute):return ("attribute",self.expression(node.value),self.name(node))
        return ("unknown",)

    def expression(self,node):
        site=self.site(node)
        if site in self.expressions:return self.expressions[site]
        op="unknown";args=();data=None
        if isinstance(node,ast.Constant):
            literal=Literal.from_ast(node)
            if literal is not None:
                op="constant";data=literal.kind;self.literals[site]=literal
        elif isinstance(node,ast.Name):op="name";data=self.name(node)
        elif isinstance(node,ast.Attribute):op="attribute";args=(self.expression(node.value),);data=self.name(node)
        elif isinstance(node,(ast.List,ast.Set,ast.Tuple)):
            op={ast.List:"list",ast.Set:"set",ast.Tuple:"tuple"}[next(kind for kind in (ast.List,ast.Set,ast.Tuple) if isinstance(node,kind))]
            args=tuple(self.expression(item) for item in node.elts)
        elif isinstance(node,ast.Dict) and all(key is not None for key in node.keys):
            op="dict";args=tuple((self.expression(key),self.expression(item)) for key,item in zip(node.keys,node.values))
        elif isinstance(node,ast.Call):
            try:
                arguments=normalize_call(node,allow_starred=True)
                op="expanded_call"if arguments.expanded else"call"
                args=(self.expression(node.func),tuple(self.expression(item.expression) for item in arguments.positional),
                                 tuple((item.name,self.expression(item.expression)) for item in arguments.keywords))
            except CallBindingError:pass
        elif isinstance(node,ast.Subscript):
            op="slice" if isinstance(node.slice,ast.Slice) else "index"
            args=(self.expression(node.value),tuple(self.expression(bound) for bound in (node.slice.lower,node.slice.upper,node.slice.step) if bound is not None)) if op=="slice" else (self.expression(node.value),self.expression(node.slice))
        elif isinstance(node,ast.BinOp):op="binary";args=(self.expression(node.left),self.expression(node.right));data=type(node.op).__name__
        elif isinstance(node,ast.UnaryOp):op="unary";args=(self.expression(node.operand),);data=type(node.op).__name__
        elif isinstance(node,ast.Compare):op="compare";args=tuple(self.expression(item) for item in (node.left,*node.comparators));data=tuple(type(operator).__name__ for operator in node.ops)
        elif isinstance(node,ast.BoolOp):op="join";args=tuple(self.expression(item) for item in node.values)
        elif isinstance(node,ast.IfExp):op="conditional";args=tuple(self.expression(item) for item in (node.test,node.body,node.orelse))
        elif isinstance(node,(ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp)):
            op="comprehension";data="list" if isinstance(node,ast.ListComp) else "set" if isinstance(node,ast.SetComp) else "dict" if isinstance(node,ast.DictComp) else "iterator"
            clauses=tuple((self.target(clause.target),self.expression(clause.iter),tuple(self.expression(test) for test in clause.ifs)) for clause in node.generators)
            item=(self.expression(node.key),self.expression(node.value)) if data=="dict" else (self.expression(node.elt),)
            args=(clauses,item)
        result=Expression(site,op,args,data);self.expressions[site]=result
        return result

    def statement(self,node):
        site=self.site(node)
        if isinstance(node,ast.Assign):return Operation(site,"assign",(self.expression(node.value),),data=tuple(self.target(target) for target in node.targets))
        if isinstance(node,ast.AnnAssign):
            if node.value is not None:return Operation(site,"assign",(self.expression(node.value),),data=(self.target(node.target),))
            from .native_annotations import target_inputs
            return Operation(site,"expression_group",tuple(self.expression(expression)for expression in target_inputs(node.target)))
        if isinstance(node,ast.Assert):
            terms=(self.expression(node.test),)
            if node.msg is not None:terms+=(self.expression(node.msg),)
            return Operation(site,"assert",terms)
        if isinstance(node,ast.AugAssign):return Operation(site,"augment",(self.expression(node.target),self.expression(node.value)),data=(self.target(node.target),type(node.op).__name__))
        if isinstance(node,ast.Delete):return Operation(site,"delete",data=tuple(self.target(target)for target in node.targets))
        if isinstance(node,ast.Expr):return Operation(site,"expression",(self.expression(node.value),))
        if isinstance(node,ast.If):return Operation(site,"branch",(self.expression(node.test),),(self.block(node.body),self.block(node.orelse)))
        if isinstance(node,(ast.For,ast.While)):
            op="for" if isinstance(node,ast.For) else "while"
            term=self.expression(node.iter if op=="for" else node.test)
            result=Operation(site,op,(term,),(self.block(node.body),self.block(node.orelse)),self.target(node.target) if op=="for" else None)
            self.loops[site]=result
            return result
        if isinstance(node,ast.Return):return Operation(site,"return",(self.expression(node.value),) if node.value is not None else ())
        if isinstance(node,(ast.Break,ast.Continue)):return Operation(site,"break" if isinstance(node,ast.Break) else "continue")
        if isinstance(node,ast.FunctionDef):
            signature=self.unit.signature_for(node)
            defaults=tuple((slot.name,self.expression(slot.expression)) for slot in signature.defaults)
            self.functions[site]=Function(site,self.name(node) if hasattr(node,"id") else node.name,signature,self.block(node.body),defaults)
            return Operation(site,"definition",data=site)
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            data=(None,tuple((item.name,item.asname) for item in node.names)) if isinstance(node,ast.Import) else (node.module,tuple((item.name,item.asname) for item in node.names))
            return Operation(site,"import",data=data)
        if isinstance(node,(ast.Pass,ast.Global,ast.Nonlocal)):return Operation(site,"pass",data=type(node).__name__)
        return Operation(site,"unknown")

    def block(self,statements):return tuple(self.statement(node) for node in statements)


@dataclass(frozen=True)
class BindingFact:
    kind: object|None
    maybe_unbound: bool


@dataclass(frozen=True)
class ScopeFacts:
    allocations: object
    headers: object
    expressions: object
    constructors: frozenset=frozenset()
    resets: object=field(default_factory=dict)
    calls: object=field(default_factory=dict)
    values: object=field(default_factory=dict)
    storage: object=field(default_factory=dict)
    header_storage: object=field(default_factory=dict)
    iteration_access:object=field(default_factory=dict)


@dataclass(frozen=True)
class Analysis:
    graph: SemanticGraph
    scopes: object
    iterations: int
    heap: object=field(default_factory=dict)

    def scope(self,function=None,kinds=()):
        key=(None,()) if function is None else (self.graph.unit.ordinal(function),tuple(canonical_kind(kind) for kind in kinds))
        return self.scopes.get(key,ScopeFacts({}, {}, {}))


def canonical_kind(kind):
    kind=unmaybe(kind)
    if isinstance(kind,SharedListType):return ListType(canonical_kind(kind.element))
    if isinstance(kind,DequeType):return DequeType(canonical_kind(kind.element))
    if kind=="deque_int":return DequeType("int")
    if isinstance(kind,ListType):return ListType(canonical_kind(kind.element))
    if kind=="list_int":return ListType("int")
    if kind=="set_int":return SetType("int")
    if kind=="dict_int":return DictType("int","int")
    if kind=="matrix_int":return ListType(ListType("int"))
    return kind


def native_kind(kind,bits):
    if isinstance(kind,SharedListType):return kind
    if isinstance(kind,DequeType)and kind.element=="int":return "deque_int"
    if isinstance(kind,ListType) and kind.element=="int":return "list_int"
    if isinstance(kind,ListType) and kind.element==ListType("int"):return "matrix_int"
    if bits and isinstance(kind,SetType) and kind.key=="int":return "set_int"
    if bits and isinstance(kind,DictType) and kind.key==kind.value=="int":return "dict_int"
    return kind


class Solver:
    def __init__(self,graph):
        self.graph=graph
        self.variables={}
        self.allocations={}
        self.records={}
        self.headers={}
        self.contexts={}
        self.cache={}
        self.active=set()
        self.constructors=set()
        self.resets={}
        self.calls={}
        self.shared_references=set()
        self.allocation_contexts={}
        self.incoming_sources={}
        self.active_iterations=[]
        from .native_iteration_effects import Recorder
        self.iteration_access=Recorder(self)

    def constrain(self,variable,item):
        self.variables[variable]=self.variables.get(variable,BOTTOM).join(item)

    def allocation_context(self,context):
        return self.allocation_contexts.get(context,context)

    def allocation(self,site,category,context):
        key=(self.allocation_context(context),site)
        result=Allocation(key,category)
        self.allocations[key]=result
        return result

    def field(self,allocation,name):return value(Variable(allocation.site,name))

    def provenance(self,item,active=frozenset()):
        """Follow symbolic fields without replacing object identities by types.

        A mutation of rows[i] constrains the row allocation, rather than the
        outer list's element type. Variables and projections retain that path
        through tuples, iteration and function arguments. Recursive symbolic
        paths contribute no new lower bound until another edge supplies one.
        """
        result=Value(unbound=item.unbound,unknown=item.unknown)
        for part in item.alternatives:
            if isinstance(part,ShapeConstraint):continue
            if isinstance(part,(Variable,Projection)):
                if part in active:continue
                if isinstance(part,Variable):
                    incoming=self.variables.get(part,BOTTOM)
                else:
                    owner=self.provenance(part.receiver,active|{part})
                    incoming=self.field_values(owner,part.role,part.index)
                result=result.join(self.provenance(incoming,active|{part}))
            else:result=result.join(value(part))
        return result

    def lookup(self,name,state,globals,locals):
        if name in state:return state[name]
        if name in locals:return MISSING
        if name in globals:
            self.iteration_access.global_read(name,globals[name])
            return globals[name]
        self.iteration_access.global_read(name,MISSING)
        if name in CORE_BUILTINS:return value(BuiltinIdentity(name))
        if name=="__name__":return value("str")
        return MISSING

    def field_values(self,item,role,index=None):
        result=BOTTOM
        for part in item.alternatives:
            if isinstance(part,Allocation):
                name="element" if part.category in {"list","tuple_sequence","deque"} else "key" if role=="iteration" else role
                result=result.join(self.field(part,name))
            elif isinstance(part,(ListType,TupleSequenceType,DequeType)):result=result.join(value(part.element))
            elif isinstance(part,SetType):result=result.join(value(part.key))
            elif isinstance(part,DictType):result=result.join(value(part.key if role=="iteration" else part.value))
            elif isinstance(part,IteratorValue):result=result.join(part.item)
            elif isinstance(part,TupleValue):
                if index is not None:
                    if -len(part.fields)<=index<len(part.fields):result=result.join(part.fields[index])
                else:
                    for field in part.fields:result=result.join(field)
            elif isinstance(part,TupleType):
                if index is not None:
                    if -len(part.fields)<=index<len(part.fields):result=result.join(value(part.fields[index]))
                else:
                    for field in part.fields:result=result.join(value(field))
            elif part=="deque_int":result=result.join(value("int"))
            elif part=="str":result=result.join(value("str"))
            elif part=="bytes":result=result.join(value("int"))
            elif isinstance(part,(Variable,Computed,Projection)):result=result.join(value(Projection(value(part),role,index)))
            else:result=result.join(UNKNOWN)
        return Value(result.alternatives,result.unbound or item.unbound,result.unknown or item.unknown)

    def insert(self,receiver,role,item):
        self.iteration_access.store(receiver,role,item)
        for part in self.provenance(receiver).alternatives:
            if isinstance(part,Allocation):self.constrain(Variable(part.site,role),item)

    def augmented(self,first,second,operator):
        # Builtin list in-place operators retain the receiver allocation.
        # Constrain inserted payloads, not a fresh list or a copied shape.
        if isinstance(self.kind(first),ListType)and operator in {"Add","Mult"}:
            if operator=="Add"and self.kind(second)not in {"int","bool","int_bool","float","none"}:
                payload=self.field_values(second,"iteration")
                self.iteration_access.store(first,"element",payload)
                self.insert(first,"element",self.provenance(payload))
            return first
        result=self.compute("binary:"+operator,(first,second))
        if result.unknown:self.iteration_access.unknown()
        return result

    def incoming_allocations(self,context):
        """Reachable caller storage, including children inserted during a call."""
        pending=list(self.incoming_sources.get(context,()))
        seen=set();allocations=set()
        while pending:
            item=pending.pop()
            for part in self.provenance(item).alternatives:
                if id(part)in seen:continue
                seen.add(id(part))
                if isinstance(part,Allocation):
                    allocations.add(part)
                    fields=("element",)if part.category in {"list","tuple_sequence","deque"}else("key",)if part.category=="set"else("key","value")
                    pending.extend(self.field(part,name)for name in fields)
                elif isinstance(part,TupleValue):pending.extend(part.fields)
                elif isinstance(part,IteratorValue):
                    pending.append(part.item)
                    pending.extend(value(source)for source in part.sources)
                elif isinstance(part,FunctionValue):pending.extend(item for _,item in part.defaults)
                elif isinstance(part,MethodValue):pending.append(part.receiver)
        return allocations

    def iteration_allocations(self,item):
        """Bounded MAY-alias roots retained by an actual iterator, not its items."""
        result=set()
        for part in self.provenance(item).alternatives:
            if isinstance(part,Allocation)and part.category=='list':result.add(part)
            elif isinstance(part,IteratorValue):result.update(part.sources)
        return frozenset(result)

    def retain_iteration(self,item):
        active=set().union(*self.active_iterations)if self.active_iterations else set()
        self.shared_references.update(active&self.iteration_allocations(item))

    @contextmanager
    def iterating(self,item):
        self.active_iterations.append(self.iteration_allocations(item))
        try:yield
        finally:self.active_iterations.pop()

    def record_mutation(self,receiver,context):
        """Preserve caller-owned list identity across a proved mutable call."""
        self.iteration_access.mutation(receiver)
        self.retain_iteration(receiver)
        if context is None or context[0]is None:return
        incoming=self.incoming_allocations(context)
        for part in self.provenance(receiver).alternatives:
            if isinstance(part,Allocation)and part.category=="list"and(part in incoming or part.site[0]!=self.allocation_context(context)):
                self.shared_references.add(part)

    def store_index(self,receiver,index,item,context=None):
        self.iteration_access.implicit(receiver,index)
        self.record_mutation(receiver,context)
        original=receiver
        receiver=self.provenance(receiver)
        categories={part.category for part in receiver.alternatives if isinstance(part,Allocation)}
        if "dict"in categories:
            self.iteration_access.store(original,"key",index);self.iteration_access.store(original,"value",item)
        if categories&{"list","deque"}:self.iteration_access.store(original,"element",item)
        if "dict" in categories:
            self.insert(receiver,"key",index);self.insert(receiver,"value",item)
        if categories&{"list","deque"}:self.insert(receiver,"element",item)

    def assign(self,target,item,state,context=None):
        if target[0]=="name":
            self.retain_iteration(state.get(target[1],BOTTOM))
            incoming={part for part in self.provenance(item).alternatives if isinstance(part,Allocation)and part.category=="list"}
            if incoming:
                for name,other in state.items():
                    if name!=target[1]:self.shared_references.update(incoming&self.provenance(other).alternatives)
            state[target[1]]=item
        elif target[0]=="unpack":
            fields=None
            if len(item.alternatives)==1:
                part=next(iter(item.alternatives))
                if isinstance(part,TupleValue):fields=part.fields
                elif isinstance(part,TupleType):fields=tuple(value(kind) for kind in part.fields)
            star=next((index for index,child in enumerate(target[1])if child[0]=='starred'),None)
            for index,child in enumerate(target[1]):
                if index==star:
                    source=value(self.allocation(child[2],'list',context))
                    if fields is None:self.insert(source,'element',self.field_values(item,'iteration'))
                    else:
                        tail=len(target[1])-star-1
                        for member in fields[star:len(fields)-tail]:self.insert(source,'element',member)
                    self.assign(child[1],source,state,context)
                else:
                    offset=index if star is None or index<star else len(fields)-len(target[1])+index if fields is not None else None
                    source=fields[offset]if fields is not None and offset is not None and 0<=offset<len(fields)else self.field_values(item,'iteration',offset)
                    self.assign(child,source,state,context)

        else:self.iteration_access.unknown()

    def compute(self,operation,operands):
        # Resolve type dependencies, never source values. Keeping a nested
        # expression tree for already-solved x += item would grow at every
        # back edge instead of reaching a finite type fixed point.
        kinds=tuple(self.kind(operand) for operand in operands)
        if None in kinds:return UNKNOWN
        kind=self.computed(operation,kinds)
        if EMPTY not in kinds:return UNKNOWN if kind is None else value(kind)
        return value(Computed(operation,operands))

    def expression(self,term,state,globals,locals,context):
        from .native_constraint_calls import Request,run
        return run(Request(self._expression,(term,state,globals,locals,context,)))

    def _expression(self,term,state,globals,locals,context):
        from .native_constraint_calls import Request
        evaluate=lambda child:Request(self._expression,(child,state,globals,locals,context))
        op,args=term.operation,term.operands
        result=UNKNOWN
        if op=="constant":result=value(term.data)
        elif op=="name":result=self.lookup(term.data,state,globals,locals)
        elif op=="tuple":
            fields=[]
            for child in args:fields.append((yield evaluate(child)))
            result=value(TupleValue(tuple(fields)))
        elif op in {"list","set","dict"}:
            allocation=self.allocation(term.site,op,context);result=value(allocation)
            if op=="dict":
                for key,item in args:
                    self.insert(result,"key",(yield evaluate(key)))
                    self.insert(result,"value",(yield evaluate(item)))
            else:
                for child in args:self.insert(result,"element" if op=="list" else "key",(yield evaluate(child)))
        elif op=="attribute":
            receiver=(yield evaluate(args[0]));result=value(MethodValue(receiver,term.data,term.site))
            # Trusted modules and streams resolve using the same pure member
            # table as calls; ordinary object attributes remain unproved.
            from .references import _member
            members=BOTTOM
            for owner in receiver.alternatives:
                member=_member(owner,term.data)
                if member is not None:members=members.join(value(member))
            if members.alternatives:result=members
            elif term.data=="maxlen"and deque_type(self.kind(receiver)):result=value(NullableType("int"))
            elif not self.iteration_access.closed(receiver):self.iteration_access.unknown()
        elif op=="call":
            callee=(yield evaluate(args[0]));positional=[];keywords=[]
            for child in args[1]:positional.append((yield evaluate(child)))
            for name,child in args[2]:keywords.append((name,(yield evaluate(child))))
            positional,keywords=tuple(positional),tuple(keywords)
            self.calls[(context,term.site)]=CallFact(callee,positional,keywords)
            self.iteration_access.call(callee,positional,keywords)
            result=BOTTOM
            for identity in callee.alternatives:
                result=result.join((yield Request(self._call,(identity,positional,keywords,term,state,globals,locals,context))))
            if callee.unknown or callee.unbound or not callee.alternatives:result=result.join(UNKNOWN)
        elif op=="expanded_call":
            self.iteration_access.unknown()
            # Observe real expression order without pretending one iterable
            # supplies one positional argument to the fixed-arity solver.
            callee=(yield evaluate(args[0]))
            for child in args[1]:(yield evaluate(child))
            for name,child in args[2]:(yield evaluate(child))
            if not callee.unknown and not callee.unbound and callee.alternatives==frozenset({BuiltinIdentity("print")}):
                result=value("none")
        elif op=="index":
            receiver=(yield evaluate(args[0]));index_value=(yield evaluate(args[1]))
            self.iteration_access.implicit(receiver,index_value)
            literal=self.graph.literals.get(args[1].site)
            index=literal.value if literal is not None and literal.kind=="int" and -(1<<63)<=literal.value<(1<<63) else None
            result=self.field_values(receiver,"value",index)
        elif op=="slice":
            receiver=(yield evaluate(args[0]))
            bounds=[]
            for bound in args[1]:bounds.append((yield evaluate(bound)))
            bounds=tuple(bounds)
            self.iteration_access.implicit(receiver,*bounds)
            item=self.field_values(receiver,"iteration")
            allocation=self.allocation(term.site,"list",context);result=value(allocation);self.insert(result,"element",item)
            if self.kind(receiver)=="str":result=value("str")
            elif self.kind(receiver)=="bytes":result=value("bytes")
        elif op=="compare":
            for child in args[:2]:self.iteration_access.implicit((yield evaluate(child)))
            for child in args[2:]:
                possible=state.copy()
                self.iteration_access.implicit((yield Request(self._expression,(child,possible,globals,locals,context))))
                joined=merge([state,possible])
                state.clear();state.update(joined)
            result=value("bool")
        elif op=="unary":
            operand=(yield evaluate(args[0]));self.iteration_access.implicit(operand)
            result=value("bool") if term.data=="Not" else self.compute("unary:"+term.data,(operand,))
        elif op=="binary":
            first=(yield evaluate(args[0]));second=(yield evaluate(args[1]))
            self.iteration_access.implicit(first,second)
            if term.data in {"Add","Mult"} and any(isinstance(part,(Allocation,ListType)) and (not isinstance(part,Allocation) or part.category=="list") for part in first.alternatives|second.alternatives):
                result=value(self.allocation(term.site,"list",context))
                sources=(first,second) if term.data=="Add" else tuple(item for item in (first,second) if any(isinstance(part,(Allocation,ListType)) for part in item.alternatives))
                for source in sources:self.insert(result,"element",self.field_values(source,"iteration"))
            else:
                operation="binary:"+term.data
                if term.data=='Pow':
                    from .native_integral_powers import semantic_kind
                    kind=semantic_kind(self.graph.nodes[term.site])
                    if kind=='int':operation+=':integral'
                    elif kind=='float':operation+=':negative'
                    else:
                        from .native_float_powers import real_node
                        if self.kind(second)=='float'and real_node(self.graph.nodes[term.site]):operation+=':real_float'
                result=self.compute(operation,(first,second))
        elif op in {"join","conditional"}:
            result=BOTTOM
            if op=="conditional":
                self.iteration_access.implicit((yield evaluate(args[0])));branches=[]
                for child in args[1:]:
                    possible=state.copy()
                    result=result.join((yield Request(self._expression,(child,possible,globals,locals,context))))
                    branches.append(possible)
                joined=merge(branches)
                state.clear();state.update(joined)
            elif args:
                result=(yield evaluate(args[0]))
                self.iteration_access.implicit(result)
                for child in args[1:]:
                    possible=state.copy()
                    next_value=(yield Request(self._expression,(child,possible,globals,locals,context)))
                    self.iteration_access.implicit(next_value)
                    result=result.join(next_value)
                    joined=merge([state,possible])
                    state.clear();state.update(joined)
        elif op=="comprehension":
            inside=state.copy()
            depth=len(self.active_iterations);sources=set()
            try:
                for target,source,filters in args[0]:
                    iterable=(yield Request(self._expression,(source,inside,globals,locals,context)))
                    owners=self.iteration_allocations(iterable);sources.update(owners)
                    self.active_iterations.append(owners)
                    self.assign(target,self.field_values(iterable,"iteration"),inside,context)
                    for condition in filters:(yield Request(self._expression,(condition,inside,globals,locals,context)))
                items=[]
                for child in args[1]:items.append((yield Request(self._expression,(child,inside,globals,locals,context))))
                items=tuple(items)
            finally:del self.active_iterations[depth:]
            if term.data=="iterator":result=value(IteratorValue(items[0],frozenset(sources),True))
            else:
                result=value(self.allocation(term.site,term.data,context))
                if term.data=="dict":self.insert(result,"key",items[0]);self.insert(result,"value",items[1])
                else:self.insert(result,"element" if term.data=="list" else "key",items[0])
        else:self.iteration_access.unknown()
        self.records[(context,term.site)]=result
        return result

    def call(self,identity,args,keywords,term,state,globals,locals,context):
        from .native_constraint_calls import Request,run
        return run(Request(self._call,(identity,args,keywords,term,state,globals,locals,context,)))

    def _call(self,identity,args,keywords,term,state,globals,locals,context):
        from .native_constraint_calls import Request
        if isinstance(identity,FunctionValue):return (yield Request(self._function,(identity,args,keywords,state if context[0] is None else globals,context,term.site)))
        if isinstance(identity,DequeConstructor):
            result=value(self.allocation(term.site,"deque",context))
            if args:self.insert(result,"element",self.field_values(args[0],"iteration"))
            elif any(name=="iterable"for name,_ in keywords):
                self.insert(result,"element",self.field_values(next(item for name,item in keywords if name=="iterable"),"iteration"))
            return result
        if isinstance(identity,MethodValue):
            receiver=self.provenance(identity.receiver);name=identity.name
            category={part.category for part in receiver.alternatives if isinstance(part,Allocation)}
            if category=={"list"}and name in {"insert","remove"}:
                from .native_sequence_plans import LIST_METHODS,bind_error
                if bind_error(LIST_METHODS[name],len(args),keywords).error:return value("none")
            if name in {"append","extend","clear","reverse","sort","pop","insert","remove"}:
                self.record_mutation(receiver,context)
            elif category&{'set','dict','deque'}and name in{'add','discard','update','setdefault','popitem','popleft','appendleft','extendleft','rotate','difference_update','intersection_update','symmetric_difference_update'}:
                self.record_mutation(receiver,context)
            category={part.category for part in receiver.alternatives if isinstance(part,Allocation)}
            kinds={part for part in receiver.alternatives if isinstance(part,(str,ListType,DictType,SetType))}
            if name in {"append","appendleft","add"} and args and (category&{"list","deque","set"}):
                self.insert(receiver,"key" if name=="add" else "element",args[0]);return value("none")
            if name=="insert"and len(args)>1 and category&{"list","deque"}:
                self.insert(receiver,"element",args[1]);return value("none")
            if name=="remove"and "list"in category:return value("none")
            if name in {"extend","extendleft","update"} and args and (category&{"list","deque","set"}):
                self.insert(receiver,"key" if name=="update" else "element",self.field_values(args[0],"iteration"));return value("none")
            if name in {"clear","reverse","rotate"}and "deque"in category:return value("none")
            if (name=="clear" and not args and not keywords and len(category)==1
                    and any(isinstance(part,Allocation) for part in identity.receiver.alternatives)):
                # Clearing a uniquely owned object creates a new content epoch,
                # not a new Python identity. All abstract aliases share it; the
                # emitter must prove unique ownership before changing storage.
                fresh=value(self.allocation(term.site,next(iter(category)),context))
                self.iteration_access.alias_epoch(fresh,identity.receiver)
                old={part for part in receiver.alternatives if isinstance(part,Allocation)}
                for binding,item in tuple(state.items()):
                    if old&item.alternatives:
                        state[binding]=Value((item.alternatives-old)|fresh.alternatives,item.unbound,item.unknown)
                self.resets[(context,term.site)]=fresh
                return value("none")
            if name in {"clear","reverse","sort"} and (category or any(isinstance(kind,ListType) for kind in kinds)):return value("none")
            if name=="copy" and len(category)==1:
                category=next(iter(category));result=value(self.allocation(term.site,category,context))
                for role in ("element",) if category in {"list","deque"} else ("key",) if category=="set" else ("key","value"):
                    self.insert(result,role,self.field_values(identity.receiver,"iteration" if role in {"key","element"} else "value"))
                return result
            if name in {"keys","values","items"} and ("dict" in category or any(isinstance(kind,DictType) for kind in kinds)):
                key=self.field_values(identity.receiver,"iteration");item=self.field_values(identity.receiver,"value")
                return value(IteratorValue(value(TupleValue((key,item))) if name=="items" else key if name=="keys" else item))
            if name=='popitem'and('dict'in category or any(isinstance(kind,DictType)for kind in kinds)):
                return value(TupleValue((self.field_values(identity.receiver,'iteration'),self.field_values(identity.receiver,'value'))))
            if name=="get" and args:
                fallback=args[1] if len(args)>1 else value("none")
                return self.field_values(identity.receiver,"value").join(fallback)
            if name=="split" and kinds&{"str","bytes"}:
                result=value(self.allocation(term.site,"list",context));self.insert(result,"element",value("bytes" if "bytes" in kinds else "str"));return result
            if name=='decode'and receiver.alternatives=={'bytes'}and not receiver.unknown and not receiver.unbound:return value('str')
            if name in {"strip","lstrip","rstrip","join","upper","lower"} and kinds&{"str","bytes"}:return value("bytes" if "bytes" in kinds else "str")
            if name in {"pop","popleft"} and "deque"in category:return self.field_values(identity.receiver,"iteration")
            if name in {"pop","popleft"} and "deque_int" in kinds:return value("int")
            if name=="copy"and "deque_int"in kinds:return value("deque_int")
            if name=="pop" and ("list" in category or any(isinstance(kind,ListType) for kind in kinds)):
                return self.field_values(identity.receiver,"iteration")
            if name in {"append","appendleft","extend","extendleft","clear","reverse","rotate"} and "deque_int" in kinds:return value("none")
            from .native_text_predicates import STR_PREDICATES,supports
            if name in STR_PREDICATES and not args and not keywords:
                kind=self.kind(receiver)
                if kind is not None and supports(kind,name):return value("bool")
            if name in {"count","index","bit_length","bit_count"}:return value("int")
            return UNKNOWN
        if not isinstance(identity,BuiltinIdentity):
            # Stream and standard-module identity records are shared with the
            # ordinary call resolver. Their result facts need no source spelling.
            if getattr(identity,"name",None)=="reader" and hasattr(identity,"binary"):return value("bytes" if identity.binary else "str")
            if getattr(identity,"module",None)=="heapq":
                name=identity.name.removesuffix("_max")
                if name in {"heapify","heappush","heappop","heappushpop","heapreplace"}and args:
                    receiver=args[0]
                    self.record_mutation(receiver,context)
                    if name in {"heappush","heappushpop","heapreplace"}and len(args)>1:self.insert(receiver,"element",args[1])
                    if name in {"heapify","heappush"}:return value("none")
                    result=self.field_values(receiver,"iteration")
                    return result.join(args[1])if name=="heappushpop"and len(args)>1 else result
            if getattr(identity,"module",None)=="bisect":
                if identity.name.startswith("insort"):
                    by_name=dict(keywords);receiver=args[0]if args else by_name.get("a",UNKNOWN)
                    item=args[1]if len(args)>1 else by_name.get("x",UNKNOWN)
                    self.record_mutation(receiver,context);self.insert(receiver,"element",item)
                    return value("none")
                return value("int")
            if getattr(identity,"module",None)=="math":
                from .native_math_calls import result_kind
                return value(result_kind(identity))
            return UNKNOWN
        name=identity.name
        if name in {"int","float","str","bool","bytes"}:return value(name)
        if name in {"bin","oct","hex"}:return value("str")
        if name=="abs" and args:return self.compute("unary:UAdd",(args[0],))
        if name=='pow':
            from .native_class_numeric_calls import _bind
            binding,error=_bind(args,keywords,value('none'))
            if error:return value('none')
            modulus=binding['mod']
            if modulus.alternatives=={'none'}and not modulus.unknown and not modulus.unbound:
                return self.compute('binary:Pow',(binding['base'],binding['exp']))
            return value('int')
        if name in {"len","ord","hash","sum"}:
            if name=="sum":return value(Computed("sum",(self.field_values(args[0],"iteration"),args[1] if len(args)>1 else dict(keywords).get("start",value("int"))))) if args else UNKNOWN
            return value("int")
        if name in {"any","all","isinstance","issubclass"}:return value("bool")
        if name=="input":return value("str")
        if name in {"print"}:return value("none")
        if name in {"list","set","dict"}:
            result=value(self.allocation(term.site,name,context))
            if not args and not keywords:self.constructors.add((context,term.site))
            if args:
                if name=="dict":return UNKNOWN
                self.insert(result,"element" if name=="list" else "key",self.field_values(args[0],"iteration"))
            return result
        if name in {"range","iter","reversed","filter","map","enumerate","zip","sorted"}:
            if name=="range":item=value("int")
            elif name in {"iter","reversed","filter","sorted"}:item=self.field_values(args[-1] if name=="filter" else args[0],"iteration") if args else UNKNOWN
            elif name=="enumerate":item=value(TupleValue((value("int"),self.field_values(args[0],"iteration")))) if args else UNKNOWN
            elif name=="zip":item=value(TupleValue(tuple(self.field_values(arg,"iteration") for arg in args)))
            elif len(args)>=2:
                item=BOTTOM
                for callback in args[0].alternatives:
                    item=item.join((yield Request(self._call,(callback,tuple(self.field_values(arg,"iteration") for arg in args[1:]),(),term,state,globals,locals,context))))
            else:item=UNKNOWN
            if name=="sorted":
                result=value(self.allocation(term.site,"list",context));self.insert(result,"element",item);return result
            inputs=(args[1:]if name in {'map','filter'}else args if name=='zip'else args[:1]if name in {'iter','reversed','enumerate'}else())
            sources=frozenset().union(*(self.iteration_access.iteration_allocations(item)for item in inputs))
            deferred=(name in {'map','filter'}and(not args or not self.iteration_access.sealed_mapper(args[0],inputs,filtering=name=='filter')))
            may_call=(deferred or name=='iter'and len(args)!=1
                      or any(self.iteration_access.iteration_may_call(item)for item in inputs))
            return value(IteratorValue(item,sources,may_call,self.iteration_access.iterator_inputs(inputs)))
        if name=="next" and args:
            item=self.field_values(args[0],"iteration")
            return item.join(args[1]) if len(args)>1 else item
        if name in {"min","max"} and args:
            result=self.field_values(args[0],"iteration") if len(args)==1 else args[0]
            for arg in args[1:]:result=result.join(arg)
            if "default" in dict(keywords):result=result.join(dict(keywords)["default"])
            return result
        if name=="tuple" and not args:return value(TupleValue(()))
        if name=="tuple"and len(args)==1 and not keywords:
            if all(isinstance(part,(TupleValue,TupleType,TupleSequenceType))or isinstance(part,Allocation)and part.category=="tuple_sequence"for part in args[0].alternatives):return args[0]
            result=value(self.allocation(term.site,"tuple_sequence",context))
            self.insert(result,"element",self.field_values(args[0],"iteration"))
            return result
        return UNKNOWN

    def function(self,identity,args,keywords,globals,caller_context=None,call_site=None):
        from .native_constraint_calls import Request,run
        return run(Request(self._function,(identity,args,keywords,globals,caller_context,call_site,)))

    def _function(self,identity,args,keywords,globals,caller_context=None,call_site=None):
        from .native_constraint_calls import Request
        definition=self.graph.functions[identity.definition]
        try:bound=definition.signature.bind(args,keywords,dict(identity.defaults))
        except CallBindingError:return UNKNOWN
        kinds=tuple(self.kind(item) for item in bound.values)
        global_key=tuple(sorted((name,tuple(sorted((part.definition for part in item.alternatives if isinstance(part,FunctionValue))))) for name,item in globals.items() if any(isinstance(part,FunctionValue) for part in item.alternatives)))
        # Semantic kinds select generated function signatures. Analysis also
        # needs object provenance: same-typed calls may read/write distinct
        # allocations and may return a reference to their particular argument.
        identities=tuple((self.provenance(item),item)for item in bound.values)
        # Heap sites use the lexical invocation path, never the argument
        # allocation graph. A loop can feed a fresh result into the same call
        # without recursively embedding all earlier arguments in new heap IDs.
        parent=self.allocation_context(caller_context)
        path=parent[2]if parent is not None and len(parent)==3 else()
        allocation_context=(definition.site,kinds,path+((definition.site,call_site),))
        # Provenance still distinguishes summaries that return/mutate actual
        # caller references; site abstraction denotes MAY alias, not identity.
        context=(definition.site,kinds,global_key,identities,allocation_context)
        if context in self.cache:
            if self.iteration_access.matches_globals(context,globals):
                self.iteration_access.replay(context,globals)
                return self.cache[context]
            del self.cache[context]
        if definition.site in self.active:
            self.iteration_access.unknown()
            return UNKNOWN
        self.allocation_contexts[context]=allocation_context
        self.incoming_sources[context]=tuple(bound.values)+tuple(globals.values())
        self.active.add(definition.site);self.contexts[context]=(definition.site,kinds)
        try:
            state=dict(zip(bound.parameters,bound.values))
            with self.iteration_access.function(context):
                flow=(yield Request(self._block,(definition.body,state,globals,definition.signature.local_names,context)))
            result=flow.returns.join(value("none")) if flow.normal is not None else flow.returns
            # A returned caller reference outlives this function frame. New local
            # allocations can still move out as uniquely owned vectors.
            incoming=self.incoming_allocations(context)
            self.shared_references.update(part for part in self.provenance(result).alternatives
                if isinstance(part,Allocation)and part.category=="list"and(part in incoming or part.site[0]!=self.allocation_context(context)))
            self.cache[context]=result
            return result
        finally:
            self.active.remove(definition.site)

    def block(self,operations,incoming,globals,locals,context):
        from .native_constraint_calls import Request,run
        return run(Request(self._block,(operations,incoming,globals,locals,context,)))

    def _block(self,operations,incoming,globals,locals,context):
        from .native_constraint_calls import Request
        flow=Flow(incoming.copy())
        for operation in operations:
            if flow.normal is None:break
            state=flow.normal
            evaluate=lambda term:Request(self._expression,(term,state,globals,locals,context))
            op,args=operation.operation,operation.operands
            if op=="assign":
                item=(yield evaluate(args[0]))
                for target in operation.data:
                    if target[0]=="index":
                        receiver=(yield evaluate(target[1]));index=(yield evaluate(target[2]))
                        self.store_index(receiver,index,item,context)
                    elif target[0]=="attribute":
                        (yield evaluate(target[1]));self.iteration_access.unknown()
                    else:self.assign(target,item,state,context)
            elif op=="augment":
                target,operator=operation.data
                if target[0]=="index":
                    receiver=(yield evaluate(target[1]));index=(yield evaluate(target[2]))
                    literal=self.graph.literals.get(target[2].site)
                    offset=(literal.value if literal is not None and literal.kind=="int"
                            and -(1<<63)<=literal.value<(1<<63)else None)
                    first=self.field_values(receiver,"value",offset)
                    second=(yield evaluate(args[1]))
                    self.iteration_access.implicit(first,second)
                    self.record_mutation(first,context)
                    self.store_index(receiver,index,self.augmented(first,second,operator),context)
                else:
                    first=(yield evaluate(args[0]));second=(yield evaluate(args[1]))
                    self.iteration_access.implicit(first,second)
                    self.record_mutation(first,context)
                    self.assign(target,self.augmented(first,second,operator),state,context)
            elif op=="expression":(yield evaluate(args[0]))
            elif op=="expression_group":
                for term in args:(yield evaluate(term))
            elif op=="assert":
                self.iteration_access.implicit((yield evaluate(args[0])))
                from .native_assertions import literal_truth
                if len(args)>1 and literal_truth(self.graph.nodes[operation.site].test)is not True:
                    (yield Request(self._expression,(args[1],state.copy(),globals,locals,context)))
            elif op=="delete":
                def delete(target):
                    if target[0]=='name':self.assign(target,MISSING,state,context)
                    elif target[0]=='unpack':
                        for child in target[1]:(yield Request(delete,(child,)))
                    elif target[0]=='index':
                        receiver=(yield evaluate(target[1]));index=(yield evaluate(target[2]))
                        self.iteration_access.implicit(receiver,index)
                        self.record_mutation(receiver,context)
                    elif target[0]=='attribute':
                        (yield evaluate(target[1]));self.iteration_access.unknown()
                for target in operation.data:(yield Request(delete,(target,)))
            elif op=="branch":
                self.iteration_access.implicit((yield evaluate(args[0])));yes=(yield Request(self._block,(operation.blocks[0],state,globals,locals,context)));no=(yield Request(self._block,(operation.blocks[1],state,globals,locals,context)))
                flow.normal=merge([yes.normal,no.normal]);flow.breaks+=yes.breaks+no.breaks;flow.continues+=yes.continues+no.continues;flow.returns=flow.returns.join(yes.returns).join(no.returns)
            elif op in {"for","while"}:
                if op=="for":source=(yield evaluate(args[0]))
                header=state.copy()
                with self.iterating(source if op=='for'else BOTTOM),self.iteration_access.loop(source if op=='for'else BOTTOM,context,operation.site if op=='for'else None):
                    for iteration in range(128):
                        inside=header.copy()
                        if op=="for":self.assign(operation.data,self.field_values(source,"iteration"),inside,context)
                        else:self.iteration_access.implicit((yield Request(self._expression,(args[0],inside,globals,locals,context))))
                        body=(yield Request(self._block,(operation.blocks[0],inside,globals,locals,context)))
                        joined=merge([state,body.normal,*body.continues])
                        if joined==header:break
                        header=joined
                    else:
                        self.iteration_access.incomplete()
                        header={name:UNKNOWN for name in header}
                self.headers[(context,operation.site)]=header
                otherwise=(yield Request(self._block,(operation.blocks[1],header,globals,locals,context)))
                flow.normal=merge([otherwise.normal,*body.breaks]);flow.breaks+=otherwise.breaks;flow.continues+=otherwise.continues
                flow.returns=flow.returns.join(body.returns).join(otherwise.returns)
            elif op=="return":flow.returns=flow.returns.join((yield evaluate(args[0])) if args else value("none"));flow.normal=None
            elif op=="break":flow.breaks.append(state.copy());flow.normal=None
            elif op=="continue":flow.continues.append(state.copy());flow.normal=None
            elif op=="definition":
                if getattr(self.graph.nodes[operation.site],"decorator_list",()):self.iteration_access.unknown()
                definition=self.graph.functions[operation.data]
                defaults=[]
                for name,term in definition.defaults:defaults.append((name,(yield evaluate(term))))
                defaults=tuple(defaults)
                state[definition.name]=value(FunctionValue(definition.site,defaults))
            elif op=="pass":
                if operation.data!="Pass":self.iteration_access.unknown()
            elif op=="import":
                from .native_module_calls import ModuleRef,MEMBERS
                module,names=operation.data
                if not(module in self.graph.unit.native_imports or module is None and all(name in self.graph.unit.native_imports for name,_ in names)):
                    self.iteration_access.unknown()
                for name,alias in names:
                    if module is None and name in self.graph.unit.native_imports:state[alias or name]=value(ModuleRef(name))
                    elif module in self.graph.unit.native_imports:
                        member=DequeConstructor(alias or name) if module=="collections" and name=="deque" else MEMBERS.get(module,{}).get(name)
                        if member is None and module=="sys" and name=="stdin":
                            from .native_stdio import TEXT
                            member=TEXT
                        state[alias or name]=value(member) if member is not None else UNKNOWN
            else:self.iteration_access.unknown()
            # Unknown operations are retained in the graph. The ordinary
            # emitter diagnoses their missing semantics; they are never run here.
        return flow

    def kind(self,item,active=frozenset()):
        if item.unknown:return None
        result=EMPTY
        for part in item.alternatives:
            if isinstance(part,Variable):
                current=EMPTY if part in active else self.kind(self.variables.get(part,BOTTOM),active|{part})
            elif isinstance(part,Allocation):
                if part in active:return None
                fields=("element",) if part.category in {"list","tuple_sequence","deque"} else ("key",) if part.category=="set" else ("key","value")
                kinds=tuple(self.kind(self.field(part,name),active|{part}) for name in fields)
                current=None if None in kinds else TupleSequenceType(kinds[0]) if part.category=="tuple_sequence" else ListType(kinds[0]) if part.category=="list" else DequeType(kinds[0]) if part.category=="deque" else SetType(kinds[0]) if part.category=="set" else DictType(*kinds)
            elif isinstance(part,TupleValue):
                fields=tuple(self.kind(field,active) for field in part.fields);current=None if None in fields else TupleType(fields)
            elif isinstance(part,Computed):
                operands=tuple(self.kind(operand,active) for operand in part.operands)
                current=self.computed(part.operation,operands)
            elif isinstance(part,Projection):
                owner=self.kind(part.receiver,active)
                current=EMPTY
                if owner is None:return None
                for shape in alternatives(owner):
                    if isinstance(shape,(ListType,TupleSequenceType,DequeType)):item=shape.element
                    elif isinstance(shape,SetType):item=shape.key
                    elif isinstance(shape,DictType):item=shape.key if part.role=="iteration" else shape.value
                    elif isinstance(shape,TupleType):
                        if part.index is not None:item=shape.fields[part.index] if -len(shape.fields)<=part.index<len(shape.fields) else EMPTY
                        else:
                            item=EMPTY
                            for field in shape.fields:item=join_types(item,field)
                    elif shape=="str":item="str"
                    elif shape=="bytes":item="int"
                    elif isinstance(shape,EmptyType):item=EMPTY
                    else:return None
                    current=join_types(current,item)
            elif isinstance(part,ShapeConstraint):current=part.kind
            elif isinstance(part,(str,TupleType,TupleSequenceType,ListType,DequeType,SetType,DictType,UnionType,NullableType,EmptyType)):current=part
            elif getattr(part,"_native_kind_tag",None) is not None:current=part
            else:return None
            if current is None:return None
            result=join_types(result,current)
        return result

    @staticmethod
    def computed(operation,kinds):
        if None in kinds:return None
        if any(isinstance(kind,UnionType)for kind in kinds):
            from itertools import product
            results=[Solver.computed(operation,choices)for choices in product(*(alternatives(kind)for kind in kinds))]
            return None if None in results else union_type(*results)
        if operation=="sum" and kinds[0]==EMPTY:return kinds[1]
        if EMPTY in kinds:return EMPTY
        numeric={"int","bool","int_bool","float"}
        if operation.startswith("unary:"):return "float" if kinds[0]=="float" else "int" if kinds[0] in numeric else None
        if operation=="sum":return "float" if "float" in kinds else "int" if set(kinds)<=numeric else None
        if len(kinds)!=2:return None
        first,second=kinds
        operator=operation.removeprefix("binary:")
        if first==second=="str" and operator=="Add":return "str"
        if "str" in kinds and operator=="Mult" and (second if first=="str" else first) in numeric-{"float"}:return "str"
        if set(kinds)<=numeric:
            if operator in{'Pow','Pow:real_float'}and second=='float':
                from .native_float_powers import RESULT
                return 'float'if operator=='Pow:real_float'else RESULT
            if "float" in kinds or operator=="Div":return "float"
            if operator=='Pow':return union_type('int','float')
            if operator=='Pow:negative':return 'float'
            if operator in {"BitAnd","BitOr","BitXor"} and first==second=="bool":return "bool"
            if operator in {"BitAnd","BitOr","BitXor"} and "int_bool" in kinds and set(kinds)<={"bool","int_bool"}:return "int_bool"
            return "int"
        return None

    def equalize(self,item,expected):
        """Propagate homogeneous structural field constraints to their sources."""
        if expected is None or isinstance(expected,EmptyType):return
        for part in item.alternatives:
            if isinstance(part,Allocation):
                if part.category=="list" and isinstance(expected,ListType):fields=(("element",expected.element),)
                elif part.category=="deque" and isinstance(expected,DequeType):fields=(("element",expected.element),)
                elif part.category=="set" and isinstance(expected,SetType):fields=(("key",expected.key),)
                elif part.category=="dict" and isinstance(expected,DictType):fields=(("key",expected.key),("value",expected.value))
                else:continue
                for name,kind in fields:
                    if not isinstance(kind,EmptyType):self.constrain(Variable(part.site,name),value(ShapeConstraint(kind) if isinstance(kind,(ListType,DequeType,SetType,DictType,TupleType,TupleSequenceType)) else kind))
            elif isinstance(part,Variable):self.constrain(part,value(ShapeConstraint(expected) if isinstance(expected,(ListType,DequeType,SetType,DictType,TupleType,TupleSequenceType)) else expected))
            elif isinstance(part,TupleValue) and isinstance(expected,TupleType) and len(part.fields)==len(expected.fields):
                for field,kind in zip(part.fields,expected.fields):self.equalize(field,kind)

    def propagate(self):
        # A nested empty row participates in the same homogeneous element
        # constraint as its peers. This transfers type facts, never objects.
        for variable,item in tuple(self.variables.items()):
            self.equalize(item,self.kind(item))

    def solve(self):
        root=(None,())
        for iteration in range(128):
            self.iteration_access.reset()
            before=self.variables.copy();self.cache={};self.records={};self.headers={};self.constructors=set();self.resets={};self.calls={};self.contexts={root:root}
            self.block(self.graph.body,{}, {},frozenset(),root)
            self.propagate()
            if self.variables==before:break
        else:raise ConstraintFailure(self.graph.unit.tree.body[0] if self.graph.unit.tree.body else self.graph.unit.tree)
        # Nested mutable list fields carry allocation identities. Select shared
        # physical storage from these solved edges, never from source spelling.
        from .native_types import shared_storage_payload
        def shared_lists(kind):
            return shared_storage_payload(kind)or isinstance(kind,ListType)and shared_lists(kind.element)
        shared={part for part in self.shared_references if shared_lists(self.kind(value(part)))}
        from .native_unique_nested_lists import allocations as unique_nested_allocations
        unique_nested=unique_nested_allocations(self)
        for allocation in self.allocations.values():
            if allocation.category!="list" or not shared_lists(self.kind(value(allocation))):continue
            children=self.provenance(self.field(allocation,"element"))
            nested={part for part in children.alternatives if isinstance(part,Allocation) and part.category=="list"}
            if nested and allocation not in unique_nested:shared.add(allocation);shared.update(nested)
        # A same-shape binding merge must retain one physical reference
        # representation on every incoming path once any alternative is shared.
        groups=[self.provenance(item).alternatives for item in self.records.values()]
        groups.extend(self.provenance(item).alternatives for state in self.headers.values()for item in state.values())
        while True:
            before=len(shared)
            for group in groups:
                lists={part for part in group if isinstance(part,Allocation)and part.category=="list"and shared_lists(self.kind(value(part)))}
                if lists&shared:shared.update(lists)
            if len(shared)==before:break
        def physical(item,active=frozenset()):
            resolved=self.provenance(item)
            members=resolved.alternatives
            if members and all(isinstance(part,Allocation) and part in shared for part in members):
                element=BOTTOM
                for part in members:element=element.join(self.field(part,"element"))
                if any(part in active for part in members):return None
                child=physical(element,active|members)
                return None if child is None else SharedListType(child)
            # Finite alternatives must retain the physical reference selected
            # for each allocation even when None/scalar values can also flow.
            handles={part for part in members if isinstance(part,Allocation) and part in shared}
            if handles and handles!=members and not resolved.unknown:
                others=members-handles
                # Same-shape list groups are closed above. A remaining raw
                # allocation needs an explicit layout proof rather than a copy.
                if not any(isinstance(part,Allocation)and part.category=="list"for part in others):
                    handle_kind=physical(Value(frozenset(handles)),active)
                    other_kind=self.kind(Value(frozenset(others)))
                    if handle_kind is not None and other_kind is not None:
                        return union_type(handle_kind,other_kind)
            return self.kind(item)
        allocations={};headers={};expressions={};values={};storage={};header_storage={}
        def key(context):return self.contexts.get(context,root)
        for (context,site),item in self.records.items():
            abstract=values.setdefault(key(context),{})
            abstract[site]=abstract[site].join(item) if site in abstract else item
            target=expressions.setdefault(key(context),{})
            kind=self.kind(item)
            layout=physical(item)
            if layout!=kind:storage.setdefault(key(context),{})[site]=layout
            if site not in target:target[site]=kind
            elif target[site] is not None:target[site]=None if kind is None else join_types(target[site],kind)
            if any(isinstance(part,Allocation) and part.site==(self.allocation_context(context),site) for part in item.alternatives):
                allocations.setdefault(key(context),{})[site]=target[site]
        for (context,site),state in self.headers.items():
            target=headers.setdefault(key(context),{}).setdefault(site,{})
            for name,item in state.items():
                layout=physical(item)
                if layout!=self.kind(item):header_storage.setdefault(key(context),{}).setdefault(site,{})[name]=layout
                fact=BindingFact(self.kind(item),item.unbound)
                if name in target:
                    old=target[name];fact=BindingFact(None if old.kind is None or fact.kind is None else join_types(old.kind,fact.kind),old.maybe_unbound or fact.maybe_unbound)
                target[name]=fact
        resets={}
        for (context,site),item in self.resets.items():
            target=resets.setdefault(key(context),{})
            current=self.kind(item)
            if site not in target:target[site]=current
            elif target[site] is not None:target[site]=None if current is None else join_types(target[site],current)
        calls={}
        for (context,site),fact in self.calls.items():
            target=calls.setdefault(key(context),{})
            target[site]=target[site].join(fact) if site in target else fact
        iteration_access=self.iteration_access.export(key)
        keys=set(allocations)|set(headers)|set(expressions)|set(resets)|set(calls)
        scopes={scope:ScopeFacts(MappingProxyType(allocations.get(scope,{})),MappingProxyType({site:MappingProxyType(state) for site,state in headers.get(scope,{}).items()}),MappingProxyType(expressions.get(scope,{})),frozenset(site for context,site in self.constructors if key(context)==scope),MappingProxyType(resets.get(scope,{})),MappingProxyType(calls.get(scope,{})),MappingProxyType(values.get(scope,{})),MappingProxyType(storage.get(scope,{})),MappingProxyType({site:MappingProxyType(state)for site,state in header_storage.get(scope,{}).items()}),MappingProxyType(iteration_access.get(scope,{}))) for scope in keys}
        return Analysis(self.graph,MappingProxyType(scopes),iteration+1,MappingProxyType(self.variables.copy()))


def analyze(unit):return Solver(SemanticGraph(unit)).solve()
