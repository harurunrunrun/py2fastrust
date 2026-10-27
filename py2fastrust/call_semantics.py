"""Shared Python call structure, independent of Rust types and ownership.

A call's explicit expressions retain Python's evaluation order. Binding maps
already evaluated values to parameters; it never evaluates default expressions.
Default slots belong to the definition and are captured by the definition's
lowering, allowing later mutable-default support without per-call reevaluation.
"""
from dataclasses import dataclass
import ast
from types import MappingProxyType


class CallBindingError(ValueError):
    """A structurally invalid or currently unproved call binding."""


@dataclass(frozen=True)
class Argument:
    expression: ast.expr
    name: str | None = None


@dataclass(frozen=True)
class CallArguments:
    positional: tuple[Argument, ...]
    keywords: tuple[Argument, ...]

    @property
    def evaluation_order(self):
        return self.positional + self.keywords


def normalize_call(node):
    """Normalize explicit arguments without executing their expressions.

    Expanding *args/**kwargs requires an emitted iterator/mapping operation and
    cannot be safely treated as a fixed signature. Keep it an explicit boundary
    until that general lowering is available.
    """
    if any(isinstance(value, ast.Starred) for value in node.args):
        raise CallBindingError("expanded positional arguments require dynamic call lowering")
    if any(value.arg is None for value in node.keywords):
        raise CallBindingError("expanded keyword arguments require dynamic call lowering")
    return CallArguments(tuple(Argument(value) for value in node.args),
                         tuple(Argument(value.value, value.arg) for value in node.keywords))


@dataclass(frozen=True)
class DefaultSlot:
    name: str
    expression: ast.expr | None
    ordinal: int | None
    definition_scope: int | None


@dataclass(frozen=True)
class CallBinding:
    parameters: tuple[str, ...]
    values: tuple[object, ...]
    explicit: frozenset[str]
    defaults: frozenset[str]

    @property
    def by_name(self):
        return MappingProxyType(dict(zip(self.parameters, self.values)))

    def __getitem__(self, name):
        return self.values[self.parameters.index(name)]


@dataclass(frozen=True)
class ValueSource:
    kind: str
    index: int | None = None
    name: str | None = None


@dataclass(frozen=True)
class CallPlan:
    """Parameter projections over one ordered evaluation of explicit arguments."""
    arguments: CallArguments
    parameters: tuple[str, ...]
    sources: tuple[ValueSource, ...]
    argument_parameters: tuple[str, ...]
    implicit_count: int
    explicit: frozenset[str]
    defaults: frozenset[str]

    def capture(self,evaluate,*,implicit=(),defaults=None):
        if len(implicit)!=self.implicit_count:
            raise CallBindingError("implicit receiver count does not match the call plan")
        values=tuple(evaluate(argument.expression,parameter)
                     for argument,parameter in zip(self.arguments.evaluation_order,self.argument_parameters))
        captured={}if defaults is None else defaults
        bound=[]
        for source in self.sources:
            if source.kind=="argument":value=values[source.index]
            elif source.kind=="implicit":value=implicit[source.index]
            else:
                if source.name not in captured:raise CallBindingError(f"default was not captured at definition: {source.name}")
                value=captured[source.name]
            bound.append(value)
        return CallBinding(self.parameters,tuple(bound),self.explicit,self.defaults)


@dataclass(frozen=True)
class FunctionSignature:
    positional: tuple[str, ...]
    positional_only: frozenset[str]
    keyword_only: tuple[str, ...]
    defaults: tuple[DefaultSlot, ...] = ()
    local_names: frozenset[str] = frozenset()
    variadic_positional: str | None = None
    variadic_keyword: str | None = None

    @property
    def parameters(self):
        return self.positional + self.keyword_only

    @classmethod
    def from_ast(cls,node,*,name_for=None,local_names=(),ordinal=None,definition_scope=None):
        arguments=node.args
        name_for=(lambda value:value.arg)if name_for is None else name_for
        ordinal=(lambda value:None)if ordinal is None else ordinal
        positional=tuple(name_for(value)for value in arguments.posonlyargs+arguments.args)
        keyword_only=tuple(name_for(value)for value in arguments.kwonlyargs)
        defaults=[]
        for name,value in zip(positional[len(positional)-len(arguments.defaults):],arguments.defaults):
            defaults.append(DefaultSlot(name,value,ordinal(value),definition_scope))
        for name,value in zip(keyword_only,arguments.kw_defaults):
            if value is not None:defaults.append(DefaultSlot(name,value,ordinal(value),definition_scope))
        return cls(positional,frozenset(name_for(value)for value in arguments.posonlyargs),keyword_only,
                   tuple(defaults),frozenset(local_names),
                   name_for(arguments.vararg)if arguments.vararg else None,
                   name_for(arguments.kwarg)if arguments.kwarg else None)

    @classmethod
    def from_unit(cls,node,unit):
        scope=unit.scope_for(node)
        return cls.from_ast(node,name_for=unit.name_for,ordinal=unit.ordinal,
            definition_scope=unit.nodes[unit.ordinal(node)].scope,
            local_names=(symbol.name for symbol in scope.symbols if symbol.has("local")or symbol.has("parameter")))

    @classmethod
    def declaration(cls, positional=(), *, positional_only=(), keyword_only=(), default_names=()):
        parameters=tuple(positional)+tuple(keyword_only)
        if len(set(parameters))!=len(parameters):
            raise ValueError("duplicate signature parameter")
        if not set(positional_only)<=set(positional) or not set(default_names)<=set(parameters):
            raise ValueError("signature refers to an unknown parameter")
        return cls(tuple(positional),frozenset(positional_only),tuple(keyword_only),
                   tuple(DefaultSlot(name,None,None,None)for name in default_names))

    def without_receiver(self):
        if not self.positional:raise CallBindingError("method has no positional receiver")
        name=self.positional[0]
        return FunctionSignature(self.positional[1:],self.positional_only-{name},self.keyword_only,
                                 tuple(value for value in self.defaults if value.name!=name),self.local_names-{name},
                                 self.variadic_positional,self.variadic_keyword)

    def plan(self,arguments,*,implicit_count=0):
        """Resolve argument positions once, before backend-specific evaluation."""
        positional=tuple(ValueSource("implicit",index)for index in range(implicit_count))
        positional+=tuple(ValueSource("argument",index)for index in range(len(arguments.positional)))
        keywords=tuple((argument.name,ValueSource("argument",len(arguments.positional)+index))
                       for index,argument in enumerate(arguments.keywords))
        defaults={slot.name:ValueSource("default",name=slot.name)for slot in self.defaults}
        binding=self.bind(positional,keywords,defaults)
        parameters=[None]*len(arguments.evaluation_order)
        for name,source in zip(binding.parameters,binding.values):
            if source.kind=="argument":parameters[source.index]=name
        return CallPlan(arguments,binding.parameters,binding.values,tuple(parameters),implicit_count,
                        binding.explicit,binding.defaults)

    def bind(self, positional, keywords=(), defaults=None):
        """Bind opaque, already evaluated values; None is an ordinary value."""
        if self.variadic_positional or self.variadic_keyword:
            raise CallBindingError("variadic signatures require dynamic call lowering")
        if len(positional)>len(self.positional):
            raise CallBindingError("too many positional arguments")
        bound=dict(zip(self.positional,positional))
        for name,value in keywords:
            if name is None:raise CallBindingError("expanded keyword arguments require dynamic call lowering")
            if name in self.positional_only:raise CallBindingError(f"positional-only argument passed by keyword: {name}")
            if name not in self.parameters:raise CallBindingError(f"unexpected keyword argument: {name}")
            if name in bound:raise CallBindingError(f"multiple values for argument: {name}")
            bound[name]=value
        explicit=frozenset(bound)
        captured={}if defaults is None else defaults
        declared={value.name for value in self.defaults}
        used=set()
        for name in self.parameters:
            if name not in bound:
                if name not in declared or name not in captured:
                    raise CallBindingError(f"missing required argument: {name}")
                bound[name]=captured[name]
                used.add(name)
        return CallBinding(self.parameters,tuple(bound[name]for name in self.parameters),explicit,frozenset(used))
