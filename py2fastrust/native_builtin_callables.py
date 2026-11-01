"""Typed builtin descriptor calls over already evaluated explicit arguments."""
from dataclasses import dataclass


@dataclass
class BuiltinSite:
    result: object
    error: str|None=None


def binding_error(identity,arguments):
    """Errors established solely by the actual builtin's fixed call shape."""
    name=identity.name
    count=len(arguments.positional)
    keywords=arguments.keywords
    if name=='isinstance':
        if keywords:return 'TypeError: isinstance() takes no keyword arguments'
        if count!=2:return f'TypeError: isinstance expected 2 arguments, got {count}'
    if name=="globals"and(count or keywords):return f"TypeError: globals() takes no arguments ({count+len(keywords)} given)"
    if name=="print":
        unknown=next((item.name for item in keywords if item.name not in {"sep","end","file","flush"}),None)
        return f"TypeError: print() got an unexpected keyword argument {unknown!r}"if unknown else None
    if name=="map":
        if count<2:return "TypeError: map() must have at least two arguments."
        unknown=next((item.name for item in keywords if item.name!="strict"),None)
        if unknown is not None:return f"TypeError: map() got an unexpected keyword argument {unknown!r}"
    if name=="zip":
        unknown=next((item.name for item in keywords if item.name!="strict"),None)
        if unknown is not None:return f"TypeError: zip() got an unexpected keyword argument {unknown!r}"
    if name in {"filter","iter","next","any","all"}:
        if keywords:return f"TypeError: {name}() takes no keyword arguments"
        if name=="filter"and count!=2:return f"TypeError: filter expected 2 arguments, got {count}"
        if name in {"any","all"}and count!=1:return f"TypeError: {name}() takes exactly one argument ({count} given)"
        if name in {"iter","next"}and not 1<=count<=2:
            if not count:return f"TypeError: {name} expected at least 1 argument, got 0"
            return f"TypeError: {name} expected at most 2 arguments, got {count}"
    if keywords:
        return f"TypeError: {name}() takes no keyword arguments"if name in {"len","abs","id","input","list","bool","float","range"}else None
    if name in {"len","abs","id"}and count!=1:
        return f"TypeError: {name}() takes exactly one argument ({count} given)"
    if name in {"input","list","bool","float"}and count>1:
        return f"TypeError: {name} expected at most 1 argument, got {count}"
    if name=="range"and not 1<=count<=3:
        return f"TypeError: range expected {'at least 1'if not count else'at most 3'} argument{'s'if count else''}, got {count}"
    if name in {"min","max"}and not count:return f"TypeError: {name} expected at least 1 argument, got 0"
    return None


def analyze(provider,plan,node,identity,arguments,positional,keywords,environment,site):
    from .native_classes import ClassUnsupported
    from .native_class_builtins import analyze as analyze_operation
    factory=lambda tag=None,args=():provider.model.cell(plan,node,tag,args,identity=identity)
    failure=binding_error(identity,arguments)
    if failure:result=factory("none")
    else:
        result=analyze_operation(provider.model,plan,node,identity,positional,keywords,environment,factory=factory,call_arguments=arguments)
        if result is None:
            raise ClassUnsupported(node,f"captured builtin {identity.name!r} has a valid call form whose argument/result protocol is not implemented by the shared typed builtin adapter",proof="builtin signature and typed result/iteration protocol")
    site.builtins[identity]=BuiltinSite(result,failure)
    return result


def emit(emitter,node,identity,builtin,arguments,keywords):
    from .native_classes import Expression,shape
    from .native import _string
    kind=shape(builtin.result)
    if builtin.error:
        return Expression(emitter.at(f"Err::<{emitter.rust_type(kind)},String>({_string(builtin.error)}.to_owned())",node),kind)
    from .native_class_builtins import emit as emit_operation
    return emit_operation(emitter,node,identity,arguments,dict(keywords),kind,kind)
