"""Immutable iterator semantics shared by every direct Rust consumer.

Plans contain source expressions and proved callable identities. They contain
no VM instructions and execute no source expressions. The lowering adapter
captures their arguments once, in the order provided by call_semantics, before
selecting a parser or a loop implementation.
"""

import ast
from dataclasses import dataclass
from enum import Enum

from .call_semantics import CallArguments, CallBinding, CallBindingError, FunctionSignature, normalize_call
from .references import BuiltinIdentity, callable_reference


class ProducerKind(Enum):
    VALUE = "value"
    SEQUENCE = "sequence"
    GENERATOR = "generator"
    RANGE = "range"
    MAP = "map"
    FILTER = "filter"
    ENUMERATE = "enumerate"
    ZIP = "zip"
    REVERSED = "reversed"
    ITER = "iter"
    METHOD = "method"
    WORDS = "words"


class ConsumerKind(Enum):
    FOR = "for"
    SUM = "sum"
    ANY = "any"
    ALL = "all"
    MIN = "min"
    MAX = "max"
    MIN_ARGUMENTS = "min_arguments"
    MAX_ARGUMENTS = "max_arguments"
    LIST = "list"
    SORTED = "sorted"
    NEXT = "next"
    UNPACK = "unpack"
    JOIN = "join"


@dataclass(frozen=True)
class DefaultValue:
    name: str
    value: object


@dataclass(frozen=True)
class Operand:
    expression: ast.expr | None
    parameter: str
    default: DefaultValue | None = None
    captured: object = None


@dataclass(frozen=True)
class Invocation:
    node: ast.Call
    identity: object
    arguments: CallArguments


@dataclass(frozen=True)
class BoundInvocation:
    invocation: Invocation
    binding: CallBinding
    explicit_order: tuple[Operand, ...]


@dataclass(frozen=True)
class BuiltinMethodIdentity:
    owner: object
    name: str
    _native_reference = True


@dataclass(frozen=True)
class MethodPlan:
    identity: BuiltinMethodIdentity
    receiver: Operand
    invocation: BoundInvocation

@dataclass(frozen=True)
class DeferredProducer:
    expression: ast.expr


@dataclass(frozen=True)
class GeneratorClause:
    target: ast.expr
    source: "ProducerPlan | DeferredProducer"
    filters: tuple[ast.expr, ...]


@dataclass(frozen=True)
class ProducerPlan:
    kind: ProducerKind
    node: ast.expr
    invocation: Invocation | None = None
    binding: BoundInvocation | None = None
    sources: tuple["ProducerPlan", ...] = ()
    elements: tuple[ast.expr, ...] = ()
    callback: object = None
    clauses: tuple[GeneratorClause, ...] = ()
    element: ast.expr | None = None
    frame: str | None = None
    receiver: ast.expr | None = None
    member: str | None = None
    method: MethodPlan | None = None

    @property
    def is_iterator(self):
        return self.kind in {ProducerKind.GENERATOR, ProducerKind.MAP, ProducerKind.FILTER,
                             ProducerKind.ENUMERATE, ProducerKind.ZIP, ProducerKind.REVERSED,
                             ProducerKind.ITER}


@dataclass(frozen=True)
class ConsumerPlan:
    kind: ConsumerKind
    node: ast.AST
    source: ProducerPlan | None
    binding: BoundInvocation | None = None
    target: ast.expr | None = None
    body: tuple[ast.stmt, ...] = ()
    otherwise: tuple[ast.stmt, ...] = ()
    values: tuple[ast.expr, ...] = ()
    method: MethodPlan | None = None


_PRODUCERS = {kind.value: kind for kind in ProducerKind
              if kind not in {ProducerKind.VALUE, ProducerKind.SEQUENCE, ProducerKind.GENERATOR, ProducerKind.METHOD}}
_CONSUMERS = {kind.value: kind for kind in ConsumerKind
              if kind in {ConsumerKind.SUM, ConsumerKind.ANY, ConsumerKind.ALL, ConsumerKind.MIN,
                          ConsumerKind.MAX, ConsumerKind.LIST, ConsumerKind.SORTED, ConsumerKind.NEXT}}


def _signature(positional, *, positional_only=(), keywords=(), defaults=()):
    return FunctionSignature.declaration(positional, positional_only=positional_only,
                                         keyword_only=keywords, default_names=defaults)


class Normalizer:
    """Resolve identities and argument roles once in one lexical context."""

    def __init__(self, generator, environment, *, resolver=None):
        self.generator = generator
        self.environment = environment
        self.resolve = resolver or (lambda node: callable_reference(generator, node, environment))
        self._invocations = {}
        self._producers = {}
        self._methods = {}

    def invocation(self, node):
        if not isinstance(node, ast.Call):
            raise TypeError("an invocation requires an ast.Call")
        key = id(node)
        if key not in self._invocations:
            self._invocations[key] = Invocation(node, self.resolve(node.func), normalize_call(node))
        return self._invocations[key]

    def bind(self, invocation, signature, defaults=()):
        default_values = {name: Operand(None, name, DefaultValue(name, value)) for name, value in defaults}
        plan = signature.plan(invocation.arguments)
        explicit = []
        def capture(expression, parameter):
            operand = Operand(expression, parameter)
            explicit.append(operand)
            return operand
        binding = plan.capture(capture, defaults=default_values)
        return BoundInvocation(invocation, binding, tuple(explicit))

    def producer(self, node):
        key = id(node)
        if key not in self._producers:
            self._producers[key] = self._producer(node)
        return self._producers[key]

    def method(self,node):
        key=id(node)
        if key in self._methods:
            return self._methods[key]
        self._methods[key]=None
        if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                and node.func.attr in {"split","join"}):
            return None
        evaluate=getattr(self.generator,"expression",None)
        if evaluate is None:
            return None
        receiver=evaluate(node.func.value,self.environment)
        if receiver.kind not in {"str","bytes"} or receiver.kind=="bytes" and node.func.attr=="join":
            return None
        identity=BuiltinMethodIdentity(receiver.kind,node.func.attr)
        original=self.invocation(node)
        invocation=Invocation(node,identity,original.arguments)
        if identity.name=="split":
            signature=_signature(("self","sep","maxsplit"),positional_only=("self",),defaults=("sep","maxsplit"))
            defaults=(("sep",None),("maxsplit",-1))
        else:
            signature=_signature(("self","iterable"),positional_only=("self","iterable"))
            defaults=()
        default_values={name:Operand(None,name,DefaultValue(name,value))for name,value in defaults}
        implicit=Operand(node.func.value,"self",captured=receiver)
        explicit=[]
        def capture(expression,parameter):
            operand=Operand(expression,parameter)
            explicit.append(operand)
            return operand
        call=signature.plan(invocation.arguments,implicit_count=1)
        binding=call.capture(capture,implicit=(implicit,),defaults=default_values)
        bound=BoundInvocation(invocation,binding,tuple(explicit))
        result=MethodPlan(identity,implicit,bound)
        self._methods[key]=result
        return result

    def comprehension(self, node):
        if not node.generators or any(clause.is_async for clause in node.generators):
            raise CallBindingError("asynchronous comprehensions require asynchronous lowering")
        clauses = []
        for index, clause in enumerate(node.generators):
            source = self.producer(clause.iter) if index == 0 else DeferredProducer(clause.iter)
            clauses.append(GeneratorClause(clause.target, source, tuple(clause.ifs)))
        frame = "<genexpr>" if isinstance(node, ast.GeneratorExp) else None
        return ProducerPlan(ProducerKind.GENERATOR, node, clauses=tuple(clauses), element=node.elt, frame=frame)

    def _producer(self, node):
        if isinstance(node, ast.GeneratorExp):
            return self.comprehension(node)
        if isinstance(node, (ast.List, ast.Tuple)):
            return ProducerPlan(ProducerKind.SEQUENCE, node, elements=tuple(node.elts))
        if not isinstance(node, ast.Call):
            return ProducerPlan(ProducerKind.VALUE, node)
        invocation = self.invocation(node)
        identity = invocation.identity
        name = identity.name if isinstance(identity, BuiltinIdentity) else None
        kind = _PRODUCERS.get(name)
        if kind is None:
            if isinstance(node.func, ast.Attribute) and not getattr(identity, "_native_reference", False):
                method=self.method(node)
                if method is not None and method.identity.name=="split":
                    return ProducerPlan(ProducerKind.WORDS,node,invocation=invocation,method=method)
                # The type adapter proves the receiver before assigning a
                # builtin method identity. A spelling never proves str.split.
                return ProducerPlan(ProducerKind.METHOD, node, invocation=invocation,
                                    receiver=node.func.value, member=node.func.attr)
            return ProducerPlan(ProducerKind.VALUE, node, invocation=invocation)
        arguments = invocation.arguments
        if kind is ProducerKind.RANGE:
            count = len(arguments.positional)
            if arguments.keywords or count not in {1, 2, 3}:
                raise CallBindingError("range requires one to three positional arguments")
            parameters = ("stop",) if count == 1 else ("start", "stop") if count == 2 else ("start", "stop", "step")
            binding = self.bind(invocation, _signature(parameters, positional_only=parameters))
            return ProducerPlan(kind, node, invocation, binding)
        if kind in {ProducerKind.MAP, ProducerKind.FILTER}:
            if len(arguments.positional) != 2 or arguments.keywords:
                raise CallBindingError("this typed adapter requires a callback and one iterable")
            binding = self.bind(invocation, _signature(("function", "iterable"), positional_only=("function", "iterable")))
            callback_node = binding.binding["function"].expression
            callback = (None if isinstance(callback_node, ast.Constant) and callback_node.value is None else self.resolve(callback_node))
            source = self.producer(binding.binding["iterable"].expression)
            return ProducerPlan(kind, node, invocation, binding, (source,), callback=callback)
        if kind is ProducerKind.ENUMERATE:
            binding = self.bind(invocation, _signature(("iterable", "start"), positional_only=("iterable",), defaults=("start",)), (("start", 0),))
            source = self.producer(binding.binding["iterable"].expression)
            return ProducerPlan(kind, node, invocation, binding, (source,))
        if kind is ProducerKind.ZIP:
            if arguments.keywords:
                raise CallBindingError("strict zip lowering requires a typed pull protocol")
            return ProducerPlan(kind, node, invocation, sources=tuple(self.producer(argument.expression) for argument in arguments.positional))
        binding = self.bind(invocation, _signature(("iterable",), positional_only=("iterable",)))
        source = self.producer(binding.binding["iterable"].expression)
        return ProducerPlan(kind, node, invocation, binding, (source,))

    def consumer(self, node):
        if isinstance(node, ast.For):
            return ConsumerPlan(ConsumerKind.FOR, node, self.producer(node.iter), target=node.target,
                                body=tuple(node.body), otherwise=tuple(node.orelse))
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List)):
            return ConsumerPlan(ConsumerKind.UNPACK, node, self.producer(node.value), target=node.targets[0])
        if isinstance(node, ast.ListComp):
            return ConsumerPlan(ConsumerKind.LIST, node, self.comprehension(node))
        if not isinstance(node, ast.Call):
            return None
        invocation = self.invocation(node)
        identity = invocation.identity
        name = identity.name if isinstance(identity, BuiltinIdentity) else None
        kind = _CONSUMERS.get(name)
        if kind is None:
            method=self.method(node)
            if method is not None:
                if method.identity.name=="split":
                    source=ProducerPlan(ProducerKind.WORDS,node,invocation=invocation,method=method)
                    return ConsumerPlan(ConsumerKind.LIST,node,source,method=method)
                source=self.producer(method.invocation.binding["iterable"].expression)
                return ConsumerPlan(ConsumerKind.JOIN,node,source,method=method)
            return None
        if kind is ConsumerKind.LIST and not invocation.arguments.evaluation_order:
            return ConsumerPlan(kind,node,ProducerPlan(ProducerKind.SEQUENCE,node))
        if kind in {ConsumerKind.MIN, ConsumerKind.MAX} and len(invocation.arguments.positional) != 1:
            if len(invocation.arguments.positional) < 2 or invocation.arguments.keywords:
                raise CallBindingError("this variadic extremum form is not proved")
            variadic = ConsumerKind.MIN_ARGUMENTS if kind is ConsumerKind.MIN else ConsumerKind.MAX_ARGUMENTS
            return ConsumerPlan(variadic, node, None, values=tuple(argument.expression for argument in invocation.arguments.positional))
        if kind is ConsumerKind.SUM:
            signature = _signature(("iterable", "start"), positional_only=("iterable",), defaults=("start",))
            defaults = (("start", 0),)
        elif kind in {ConsumerKind.MIN, ConsumerKind.MAX}:
            signature = _signature(("iterable",), positional_only=("iterable",), keywords=("default", "key"), defaults=("default", "key"))
            defaults = (("default", DefaultValue("missing", None)), ("key", None))
        elif kind is ConsumerKind.SORTED:
            signature = _signature(("iterable",), positional_only=("iterable",), keywords=("key", "reverse"), defaults=("key", "reverse"))
            defaults = (("key", None), ("reverse", False))
        elif kind is ConsumerKind.NEXT:
            signature = _signature(("iterable", "default"), positional_only=("iterable", "default"), defaults=("default",))
            defaults = (("default", DefaultValue("missing", None)),)
        else:
            signature = _signature(("iterable",), positional_only=("iterable",))
            defaults = ()
        binding = self.bind(invocation, signature, defaults)
        source = self.producer(binding.binding["iterable"].expression)
        return ConsumerPlan(kind, node, source, binding)


def context(g,environment):
    """Reuse normalization only while the proved namespace/context is equal."""
    names=getattr(g,"global_names",None)
    globals_at_call=getattr(g,"global_environment",None)or{}
    key=(tuple(sorted((name,id(value))for name,value in environment.items())),
         None if names is None else frozenset(names),
         tuple(sorted((name,id(value))for name,value in globals_at_call.items())),
         id(getattr(g,"function",None)),g.scope_name(),getattr(g,"expression_trace_id",None))
    cache=getattr(g,"_normalized_stream_contexts",None)
    if cache is None:
        cache={}
        g._normalized_stream_contexts=cache
    if key not in cache:
        cache[key]=Normalizer(g,environment)
    return cache[key]


def consumer_plan(g,node,environment,kinds=None):
    from .native import _Unsupported
    try:
        plan=context(g,environment).consumer(node)
    except CallBindingError as error:
        raise _Unsupported from error
    return plan if plan is not None and (kinds is None or plan.kind in kinds) else None
