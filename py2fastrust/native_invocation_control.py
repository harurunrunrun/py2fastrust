"""Original-source invocation producers for typed continuation calls.

The ledger is compiler IR. Its owned receiver/argument nodes are consumed by
source-specific frame generation, never emitted as an instruction stream.
"""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class InvocationProducer:
    caller: object
    node: object
    role: str
    callee: object
    argument_nodes: tuple
    receiver: object=None
    physical_result: object=None
    logical_activation: str='source'


class InvocationLedger:
    def __init__(self,model,source):
        self.model=model;self.source=source;self.producers={};self.covered=set()
        self.plans={plan.index:plan for plan in model.plans if plan.reachable}
        self.classes={model.class_key(owner):owner for owner in model.classes.values()}

    def describe(self,plan,node,targets):
        from .native_classes import InstanceType,shape
        target=self.plans.get(next(iter(targets)))if len(targets)==1 else None
        if target is None:
            return InvocationProducer(plan,node,'finite_or_implicit',None,())
        callee=self.source(target)
        role='implicit';receiver=None;arguments=();result=shape(target.result);activation='source'
        if isinstance(node,ast.Call):
            site=self.model.callable_cells.sites.get((plan.index,id(node)))
            name=self.model.resolved_name(plan,node.func)if isinstance(node.func,ast.Name)else None
            function=self.model.functions.get(name)
            if (function is not None and name not in self.model.callable_cells.versioned_names
                    and self.source(function)is callee):
                # The caller separately proves this original binding immutable,
                # call-only and initialized. Captured ABI metadata does not
                # turn that exact source invocation into an opaque callback.
                role='direct_function';arguments=tuple(node.args)
            elif site is not None and(site.constructors or site.targets):
                role='captured_callable'
            elif isinstance(node.func,ast.Name):
                owner=self.model.classes.get(name)
                if owner is not None and self.source(owner.methods.get('__init__'))is callee:
                    # Constructor object result and initializer None result are
                    # separate physical roles, even though one depth is shared.
                    role='constructor';result=InstanceType(self.model.class_key(owner));activation='constructor'
            elif isinstance(node.func,ast.Attribute):
                cell=self.model.records.get((plan.index,id(node.func.value)))
                kind=None if cell is None else shape(cell)
                owner=self.classes.get(kind.name)if isinstance(kind,InstanceType)else None
                method=None if owner is None else owner.methods.get(self.model.resolved_name(plan,node.func))
                if method is not None and self.source(method)is callee:
                    role='direct_method';receiver=node.func.value;arguments=(receiver,*node.args)
        elif isinstance(node,ast.ClassDef)and getattr(target,'class_body',None)is not None:
            role='class_publication';activation='publication'
        elif isinstance(node,(ast.BinOp,ast.UnaryOp,ast.Compare,ast.AugAssign)):
            role='operator_phase'
        producer=InvocationProducer(plan,node,role,target,arguments,receiver,result,activation)
        self.producers[plan.index,id(node)]=producer
        self.covered.update((plan.index,id(node),index)for index in targets)
        return producer

    def bounded_constructor(self,plan,node,owner):
        from .native_classes import InstanceType,shape
        cell=self.model.records.get((plan.index,id(node)))
        result=InstanceType(self.model.class_key(owner))
        if cell is None or shape(cell)!=result:return None
        producer=InvocationProducer(plan,node,'constructor',None,(),physical_result=result,
                                    logical_activation='constructor')
        self.producers[plan.index,id(node)]=producer
        return producer

    def complete(self):
        if not all((caller,site,target)in self.covered
                   for(caller,site),targets in self.model.call_edges_by_site.items()
                   if caller in self.plans for target in targets):return False
        return all(set(self.model.call_edges.get(caller,()))<=
                   {target for owner,_,target in self.covered if owner==caller}
                   for caller in self.plans)


def flat_field(kind):
    from .native_types import alternatives,ListType,TupleType
    for part in alternatives(kind):
        if part in {'int','bool','int_bool','none','float','str','bytes'}:continue
        if isinstance(part,ListType):
            if all(child in {'int','bool','int_bool','none','float','str','bytes'}for child in alternatives(part.element)):continue
        if isinstance(part,TupleType)and all(flat_field(child)for child in part.fields):continue
        return False
    return True


def owned_kind(model,kind):
    from .native_classes import InstanceType,shape
    from .native_owned_object_places import selected as unique_owned
    if kind in {'int','bool','int_bool','none','float','str','bytes'}:return True
    if type(kind)is not InstanceType:return False
    owner=model.classes.get(kind.name)
    return(owner is not None and not unique_owned(model,owner)
           and all(flat_field(shape(field.cell))for field in owner.fields.values()))


def contains_instance(kind):
    from .native_class_identity_demand import nested
    from .native_classes import InstanceType
    return any(isinstance(part,InstanceType)for part in nested(kind))


def canonical_identities(kind):
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    from .native_types import alternatives
    result=set()
    for part in alternatives(kind):
        if isinstance(part,(BuiltinIdentity,BuiltinRef)):result.add(part)
        for family in ('targets','builtins','members'):
            result.update(getattr(part,family,()))
    return result


def method_slot_write_closed(classes,kind,attribute):
    """Every MAY receiver must preserve the published method dictionary."""
    from .native_classes import InstanceType
    from .native_module_linking import ClassReferenceType
    from .native_types import alternatives
    if not isinstance(attribute,str):return False
    for part in alternatives(kind):
        # Class dictionaries are immutable in this initial calling convention;
        # this also covers class aliases and newly installed protocol hooks.
        if isinstance(part,ClassReferenceType):return False
        if not isinstance(part,InstanceType):return False
        owner=classes.get(part.name)
        if owner is None or attribute in owner.methods:return False
        if attribute in {'__class__','__dict__','__weakref__'}:return False
    return True


def method_binding_write_closed(model,plan,node):
    from .native_classes import shape
    receiver=model.records.get((plan.index,id(node.value)))
    if receiver is None:return False
    return method_slot_write_closed(model.classes,shape(receiver),model.resolved_name(plan,node))
