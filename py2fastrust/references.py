"""Static callable identity from lexical bindings and a proved namespace.

A source spelling is a builtin only after local and global shadowing have been
excluded. Existing function, module and stream references remain their original
identity records. This module resolves identities; it does not execute Python
objects or add runtime callable support.
"""
import ast
from dataclasses import dataclass


CORE_BUILTINS=frozenset({
    "abs","all","any","ascii","bin","bool","bytearray","bytes","callable","chr",
    "classmethod","compile","complex","delattr","dict","dir","divmod","enumerate",
    "eval","exec","filter","float","format","frozenset","getattr","globals","hasattr",
    "hash","hex","id","input","int","isinstance","issubclass","iter","len","list",
    "locals","map","max","memoryview","min","next","object","oct","open","ord",
    "pow","print","property","range","repr","reversed","round","set","setattr",
    "slice","sorted","staticmethod","str","sum","super","tuple","type","vars","zip",
    "__import__","__build_class__","BaseException","Exception","StopIteration","ValueError",
    "TypeError","RuntimeError","IndexError","KeyError","AttributeError","NameError",
    "UnboundLocalError","OverflowError","ZeroDivisionError","AssertionError","MemoryError",
    "NotImplementedError","RecursionError","EOFError","ImportError","ModuleNotFoundError","OSError",
})


@dataclass(frozen=True)
class BuiltinIdentity:
    name: str
    _native_reference=True


@dataclass(frozen=True)
class DequeConstructor:
    """A constructor resolved from the trusted collections module."""
    name: str
    _native_reference=True


@dataclass(frozen=True)
class UnboundReference:
    name: str
    local: bool


@dataclass(frozen=True)
class UnknownReference:
    name: str | None
    reason: str


_BUILTINS={name:BuiltinIdentity(name)for name in CORE_BUILTINS}

# These names have no spelling-based call implementation: their calls are
# lowered only through the canonical identity plans. Other legacy builtin
# spellings still require the conservative assignment boundary.
CANONICAL_REBINDABLES=frozenset({"min","max"})


def _known(value,name):
    return value if getattr(value,"_native_reference",False) else UnknownReference(name,"bound value is not a static callable reference")


def _member(owner,name):
    from .native_module_calls import ModuleRef,MEMBERS
    from .native_stdio import _IOReference,SYS,TEXT,BINARY,READERS
    if isinstance(owner,ModuleRef):
        if owner.name=="builtins":return _BUILTINS.get(name)
        if owner.name=="sys" and name=="stdin":return TEXT
        return MEMBERS.get(owner.name,{}).get(name)
    if isinstance(owner,_IOReference):
        if owner is SYS and name=="stdin":return TEXT
        if owner is TEXT and name=="buffer":return BINARY
        if owner in (TEXT,BINARY)and name in {"read","readline"}:
            return READERS[(owner.binary,name=="readline")]
    return None


def resolve_static_callable(node,environment,*,local_names=(),global_environment=None,
                            global_bound_names=None,name_for=None,private_owner=None,
                            function_scope=False,core_builtins=None):
    """Return a static identity, or an explicit unbound/unknown result.

    A function's global_bound_names is a complete presence mask, including
    non-static bindings omitted from its captured global_environment. Without
    that mask, absence of a name in a partial environment proves nothing about
    default builtin lookup. Definition-time captures pass their own namespace;
    already captured defaults never need to be resolved again at a call site.
    """
    allowed=CORE_BUILTINS if core_builtins is None else core_builtins
    globals_at_call={}if global_environment is None else global_environment
    def canonical(value):
        if name_for is not None:
            try:return name_for(value)
            except KeyError:pass
        name=value.id if isinstance(value,ast.Name)else value.attr
        if private_owner:
            from .frontend import private_name
            name=private_name(name,private_owner)
        return name
    def resolve(value):
        if isinstance(value,ast.Name):
            name=canonical(value)
            if name in environment:return _known(environment[name],name)
            if name in local_names:return UnboundReference(name,True)
            if name in globals_at_call:return _known(globals_at_call[name],name)
            if global_bound_names is not None and name in global_bound_names:
                return UnknownReference(name,"global name is shadowed by a non-static binding")
            if function_scope and global_bound_names is None:
                return UnknownReference(name,"global namespace presence is unproved")
            if name in allowed and name in _BUILTINS:return _BUILTINS[name]
            return UnboundReference(name,False)
        if isinstance(value,ast.Attribute):
            owner=resolve(value.value)
            if isinstance(owner,(UnboundReference,UnknownReference)):return owner
            name=canonical(value)
            member=_member(owner,name)
            return member if member is not None else UnknownReference(name,"attribute is not a proved static callable member")
        return UnknownReference(None,"expression is not a static reference")
    return resolve(node)


def callable_reference(generator,node,environment):
    """Resolve in the generator's actual lexical/call-time namespace context."""
    function=getattr(generator,"function",None)
    entry=getattr(generator,"entry_scope",None)
    function_scope=function is not None or entry is not None
    local_names=getattr(function,"local_names",())if function is not None else getattr(generator,"entry_local_names",())
    global_names=getattr(generator,"global_names",None)
    if global_names is None and function is not None:global_names=getattr(function,"global_names",None)
    unit=getattr(generator,"source_unit",None)
    owner=getattr(generator,"reference_private_owner",None)
    if owner is None and unit is not None and function is not None:
        try:
            scope=unit.scope_for(function.node)
            while scope.parent is not None:
                scope=unit.scopes[scope.parent]
                if scope.kind=="class":owner=scope.name;break
        except (KeyError,AttributeError):pass
    result=resolve_static_callable(node,environment,local_names=local_names,
        global_environment=getattr(generator,"global_environment",None),global_bound_names=global_names,
        name_for=unit.name_for if unit is not None else None,private_owner=owner,function_scope=function_scope)
    # Namespace validation remains part of each specialization's caller proof.
    base=node
    while isinstance(base,ast.Attribute):base=base.value
    if function is not None and isinstance(base,ast.Name)and getattr(result,"_native_reference",False):
        name=base.id
        if unit is not None:
            try:name=unit.name_for(base)
            except KeyError:pass
        if owner:
            from .frontend import private_name
            name=private_name(name,owner)
        if name not in local_names:
            globals_at_call=getattr(generator,"global_environment",None)or{}
            required=getattr(function,"required",None)
            if required is not None and (name in globals_at_call or global_names is not None and name in global_names):required.add(name)
            absent=getattr(function,"absent_globals",None)
            if (absent is not None and isinstance(result,BuiltinIdentity)and isinstance(node,ast.Name)
                    and name==result.name and name not in environment and name not in globals_at_call
                    and global_names is not None and name not in global_names):absent.add(name)
    return result


def capture_builtin_assignment(generator,node,environment):
    """Bind a proved identity; a source name alone never denotes a builtin."""
    if not (isinstance(node,ast.Assign) and isinstance(node.value,(ast.Name,ast.Attribute))):
        return None
    value=callable_reference(generator,node.value,environment)
    if not isinstance(value,BuiltinIdentity):
        return None
    from .native import _Unsupported
    if not all(isinstance(target,ast.Name) and (target.id not in CORE_BUILTINS or target.id in CANONICAL_REBINDABLES)
               and target.id not in generator.iterating_lists for target in node.targets):
        raise _Unsupported
    for target in node.targets:
        environment[target.id]=value
    return "",environment
