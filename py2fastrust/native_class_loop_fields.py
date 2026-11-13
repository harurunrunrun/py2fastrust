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
    registry=getattr(emitter.model,"class_namespaces",None)
    if registry is not None and(emitter.plan.index,id(node))in registry.attribute_reads:return None
    owner=emitter.kind(node.value)
    if domain(owner)!="object":return None
    plan=emitter.model.classes[owner.name]
    field=emitter.model.resolved_name(emitter.plan,node)
    if field not in plan.fields:return None
    from .native_owned_class_lists import selected
    if selected(emitter.model,plan,list(plan.fields).index(field)):return None
    return emitter.model.resolved_name(emitter.plan,node.value),plan.index,field


def _may_call_source(emitter,node):
    """Resolve a call's effects through the same proof/carrier as emission."""
    from .native_callback_effects import may_call
    if may_call(emitter.model,emitter.plan,node):return True
    from .native_frame_references import call_target
    if call_target(emitter.model,emitter.plan,node)is not None:return True
    site=emitter.model.callable_cells.sites.get((emitter.plan.index,id(node)))
    if site is None:return False
    targets=getattr(site,"targets",None)
    builtins=getattr(site,"builtins",None)
    members=getattr(site,"members",None)
    # An unavailable callee vector is not a purity proof. Standard module
    # adapters can invoke callbacks; keep them outside invariant field caches.
    return (targets is None or bool(targets)or builtins is None
            or members is None or bool(members))


def candidates(emitter,node):
    from .native_classes import domain
    if isinstance(node,ast.For)and(emitter.model.iterators.may_call(emitter.kind(node.iter))or emitter.model.iterators.effects(emitter.plan,node)):return {}
    roots=[node.test,*node.body]if isinstance(node,ast.While)else[node.target,*node.body]
    reached=getattr(emitter.model,'reached_statements',None)
    def walk(current):
        if isinstance(current,ast.stmt)and reached is not None and(emitter.plan.index,id(current))not in reached:return
        yield current
        for child in ast.iter_child_nodes(current):yield from walk(child)
    nodes=[child for root in roots for child in walk(root)]
    if any(isinstance(child,(ast.Lambda,ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp,ast.FunctionDef,ast.ClassDef))for child in nodes):return {}
    if any(isinstance(child,ast.Attribute)and isinstance(child.ctx,(ast.Store,ast.Del))for child in nodes):return {}
    from .native_callback_effects import may_call
    if any(may_call(emitter.model,emitter.plan,child)for child in nodes):return {}
    for child in nodes:
        if not isinstance(child,ast.Call):continue
        if emitter.model.iterators.effects(emitter.plan,child):return {}
        if _may_call_source(emitter,child):return {}
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
