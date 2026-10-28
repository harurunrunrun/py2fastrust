"""Lazy loop-invariant field reads for proved concrete native objects.

Only loops without user calls, attribute stores or inner lexical scopes qualify.
No getter is moved before its first evaluation: optional typed cache slots retain
the original zero-trip behavior and the first read's exception source position.
"""
import ast
from contextlib import contextmanager


def key(emitter,node):
    from .native_classes import domain
    if not isinstance(node,ast.Attribute)or not isinstance(node.value,ast.Name):return None
    owner=emitter.kind(node.value)
    if domain(owner)!="object":return None
    plan=emitter.model.classes[owner.name]
    field=emitter.model.resolved_name(emitter.plan,node)
    if field not in plan.fields:return None
    return emitter.model.resolved_name(emitter.plan,node.value),plan.index,field


def candidates(emitter,node):
    from .native_classes import domain
    roots=[node.test,*node.body]if isinstance(node,ast.While)else[node.target,*node.body]
    nodes=[child for root in roots for child in ast.walk(root)]
    if any(isinstance(child,(ast.Lambda,ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp,ast.FunctionDef,ast.ClassDef))for child in nodes):return {}
    if any(isinstance(child,ast.Attribute)and isinstance(child.ctx,(ast.Store,ast.Del))for child in nodes):return {}
    for child in nodes:
        if not isinstance(child,ast.Call):continue
        function=child.func
        if isinstance(function,ast.Name):
            if function.id in emitter.model.functions or function.id in emitter.model.classes:return {}
        elif isinstance(function,ast.Attribute):
            if domain(emitter.kind(function.value))=="object":return {}
        else:return {}
    stores={emitter.model.resolved_name(emitter.plan,child)for child in nodes
            if isinstance(child,ast.Name)and isinstance(child.ctx,(ast.Store,ast.Del))}
    result={}
    for child in nodes:
        if isinstance(child,ast.Attribute)and isinstance(child.ctx,ast.Load):
            identity=key(emitter,child)
            if identity is not None and identity[0]not in stores:result[identity]=emitter.kind(child)
    return result


@contextmanager
def scope(emitter,node):
    cache={}
    lines=[]
    for identity,kind in candidates(emitter,node).items():
        if any(identity in parent for parent in emitter.loop_field_caches):continue
        name=emitter.fresh();cache[identity]=(name,kind)
        lines.append(f"let mut {name}:Option<{emitter.rust_type(kind)}>=None;")
    emitter.loop_field_caches.append(cache)
    try:yield "".join(lines)
    finally:emitter.loop_field_caches.pop()


def read(emitter,node,code,kind):
    identity=key(emitter,node)
    if identity is None:return code
    for cache in reversed(emitter.loop_field_caches):
        if identity in cache:
            name,_=cache[identity]
            return (f'{{if {name}.is_none(){{{name}=Some({code});}}'
                    f'{name}.as_ref().expect("initialized loop field").clone()}}')
    return code
