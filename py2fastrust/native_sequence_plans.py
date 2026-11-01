"""Typed builtin sequence operations, independent of their physical storage.

An exact builtin list type establishes method identity. User instance methods
never enter this registry, even when their names coincide with a list method.
The same declarations bind ordinary and shared class-scope sequence calls.
"""
from dataclasses import dataclass,replace
from types import MappingProxyType

from .call_semantics import FunctionSignature
from .native_types import list_type,deque_type


@dataclass(frozen=True)
class SequenceMethod:
    name: str
    signature: FunctionSignature
    defaults: tuple
    mutates: bool
    result: str
    error: str|None=None


def _method(name, positional=(), *, defaults=(), keywords=(), mutates=False, result="none"):
    names=("self",)+tuple(positional)
    return SequenceMethod(name,FunctionSignature.declaration(names,positional_only=names,
        keyword_only=keywords,default_names=tuple(key for key,_ in defaults)),defaults,mutates,result)


LIST_METHODS=MappingProxyType({method.name:method for method in (
    _method("append",("value",),mutates=True),
    _method("extend",("iterable",),mutates=True),
    _method("insert",("index","value"),mutates=True),
    _method("remove",("value",),mutates=True),
    _method("clear",mutates=True),
    _method("reverse",mutates=True),
    _method("copy",result="copy"),
    _method("pop",("index",),defaults=(("index",-1),),mutates=True,result="element"),
    _method("index",("value","start","stop"),defaults=(("start",0),("stop",None)),result="int"),
    _method("count",("value",),result="int"),
    _method("sort",keywords=("key","reverse"),defaults=(("key",None),("reverse",False)),mutates=True),
)})


DEQUE_METHODS=MappingProxyType({method.name:method for method in (
    _method("append",("value",),mutates=True),
    _method("appendleft",("value",),mutates=True),
    _method("extend",("iterable",),mutates=True),
    _method("extendleft",("iterable",),mutates=True),
    _method("pop",mutates=True,result="element"),
    _method("popleft",mutates=True,result="element"),
    _method("clear",mutates=True),
    _method("reverse",mutates=True),
    _method("rotate",("n",),defaults=(("n",1),),mutates=True),
    _method("copy",result="copy"),
    _method("count",("value",),result="int"),
    _method("index",("value","start","stop"),defaults=(("start",0),("stop",None)),result="int"),
    _method("insert",("index","value"),mutates=True),
    _method("remove",("value",),mutates=True),
)})
METHODS=MappingProxyType({**LIST_METHODS,**DEQUE_METHODS})


def sequence_method(kind,name):
    return DEQUE_METHODS.get(name)if deque_type(kind)else LIST_METHODS.get(name)if list_type(kind)else None


def bind_error(method,count,keywords):
    if method is None or method.name not in {"insert","remove"}:return method
    expected=2 if method.name=="insert"else 1
    error=(f"TypeError: list.{method.name}() takes no keyword arguments"if keywords else
           f"TypeError: insert expected 2 arguments, got {count}"if method.name=="insert"and count!=expected else
           f"TypeError: list.remove() takes exactly one argument ({count} given)"if count!=expected else None)
    return replace(method,error=error,mutates=False)if error else method


def element_type(kind):
    return "int" if kind in {"list_int","deque_int"} else kind.element
