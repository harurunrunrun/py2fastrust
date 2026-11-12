"""Bound compiler temporaries and dead local handles by original source flow.

Only a closed lifetime certificate permits earlier physical drops. Official
bindings, loop fixed points and captured-name pinning determine local liveness;
the source types, assignment order and shared object representation stay intact.
"""
import ast

from .native_join_liveness import Flow, UnsupportedFlow


class LocalFlow(Flow):
    def __init__(self, model, plan):
        self.model=model
        self.unit=model.unit
        self.owner=model.lexical.scope(plan)
        self.bindings={binding.node:binding for binding in model.iter_bindings()}
        self.pinned={binding.name for binding in self.bindings.values()
                     if binding.owner==self.owner and binding.scope!=self.owner
                     and binding.role=='load'}
        self.exits={}
        self.headers={}
        self.after={}
        if not isinstance(plan.node.body,list):raise UnsupportedFlow
        self.block(plan.node.body,set(),None,None)

    def statement(self,node,after,breaking,continuing):
        before=super().statement(node,after,breaking,continuing)
        self.after[id(node)]=frozenset(after)|self.pinned
        return before


def analysis(emitter):
    if hasattr(emitter,'statement_lifetime_flow'):
        return emitter.statement_lifetime_flow
    from .native_namespace_read_places import lifetime_closed
    emitter.statement_lifetime_closed=lifetime_closed(emitter.model)
    flow=None
    if emitter.statement_lifetime_closed and not emitter.model.is_module_plan(emitter.plan):
        try:flow=LocalFlow(emitter.model,emitter.plan)
        except UnsupportedFlow:pass
    emitter.statement_lifetime_flow=flow
    return flow


def scope(emitter,node,code):
    flow=analysis(emitter)
    if not code or not emitter.statement_lifetime_closed:
        return code
    # Every original statement owns its implementation-only operand captures.
    # Persistent Python bindings live in the function's separately declared
    # slots, not in these temporary Rust lets.
    result='{'+code+'}'
    if flow is None or isinstance(node,(ast.Return,ast.Raise,ast.Break,ast.Continue)):
        return result
    live=flow.after.get(id(node))
    if live is None:return result
    touched={flow.key(child)for child in ast.walk(node)if isinstance(child,ast.Name)}
    dead=touched-live-set(emitter.plan.runtime_parameters)-{None}
    from .native_classes import InstanceType
    from .native_copy_scalar_fields import selected as scalar_fields
    from .native_value_classes import selected as value_class
    from .native_class_identity_demand import Unproved
    owners=getattr(emitter.model,'statement_lifetime_owners',None)
    if owners is None:
        owners={}
        emitter.model.statement_lifetime_owners=owners
    for (name,kind),slot in emitter.slots.items():
        if name not in dead or not isinstance(kind,InstanceType):continue
        owner=emitter.model.classes[kind.name]
        if not scalar_fields(emitter.model,owner)or value_class(emitter.model,owner):continue
        if owner.index not in owners:
            # Default repr/str can expose an address even without an id()
            # call. Saved representations must not observe earlier reuse.
            try:emitter.model.class_identity_demand.prove(owner)
            except Unproved:owners[owner.index]=False
            else:owners[owner.index]=True
        if owners[owner.index]:result+=slot+'=None;'
    return result
