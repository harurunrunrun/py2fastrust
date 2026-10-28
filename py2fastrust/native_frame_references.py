"""Compile-time-only source function references proved by shared call facts.

Only bound Name assignments whose uses are proved calls/other such assignments
are erased. Escaping function objects still need a runtime callable carrier.
"""
import ast
from dataclasses import dataclass
from types import MappingProxyType

from .native_constraints import FunctionValue


@dataclass(frozen=True)
class References:
    assignments: frozenset[tuple[int|None,int]]
    blocked_assignments: object
    lifetime_assignments: object
    mutable_bindings: frozenset


def _definitions(identity):
    if identity is None or identity.unknown or identity.unbound or not identity.alternatives:return frozenset()
    if not all(isinstance(value,FunctionValue)for value in identity.alternatives):return frozenset()
    return frozenset(value.definition for value in identity.alternatives)


def prove(unit,analysis,targets):
    parents={id(child):parent for parent in ast.walk(unit.tree)for child in ast.iter_child_nodes(parent)}
    bindings={item.node:item for item in unit.bindings}
    # CallFacts summarize a function with its incoming globals. They do not
    # establish post-call callable versions after a global/nonlocal write.
    # Erasure is valid only for bindings confined to their lexical owner.
    cross_scope_writes={(item.name,item.owner)for item in unit.bindings
        if item.role not in {'load','parameter'}and item.scope!=item.owner}
    values={}
    for (caller,_),facts in analysis.scopes.items():
        for site,value in facts.values.items():
            key=(caller,site)
            values[key]=value if key not in values else values[key].join(value)
    candidates={};by_node={};blocked={};lifetime={}
    for node in ast.walk(unit.tree):
        if not(isinstance(node,ast.Assign)and isinstance(node.value,ast.Name)and all(isinstance(target,ast.Name)for target in node.targets)):continue
        source=unit.ordinal(node.value);site=unit.ordinal(node)
        names=tuple((bindings[unit.ordinal(target)].name,bindings[unit.ordinal(target)].owner)for target in node.targets)
        for (caller,term),identity in values.items():
            if term==source and len(_definitions(identity))==1:
                key=(caller,site)
                if any(name in cross_scope_writes for name in names):
                    blocked[key]=tuple(sorted(name for name,owner in names if(name,owner)in cross_scope_writes))
                else:candidates[key]=names;by_node[id(node)]=key
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    while True:
        removed=set()
        allowed_writes={unit.ordinal(target)for caller,site in candidates for target in nodes[site].targets}
        for key,names in candidates.items():
            # Erasing only a function assignment would leave a later del or a
            # previous parameter/data binding with the wrong lifetime/state.
            unsupported={binding.name for binding in unit.bindings
                if(binding.name,binding.owner)in names and binding.role!='load'
                and binding.node not in allowed_writes}
            if unsupported:
                lifetime[key]=tuple(sorted(unsupported));removed.add(key);continue
            for binding in unit.bindings:
                if binding.role!='load'or (binding.name,binding.owner)not in names:continue
                node=nodes[binding.node];parent=parents.get(id(node))
                if isinstance(parent,ast.Assign)and parent.value is node and by_node.get(id(parent))in candidates:continue
                if isinstance(parent,ast.Call)and parent.func is node:
                    site=unit.ordinal(parent)
                    options=[target for (caller,term),target in targets.items()if term==site]
                    if options and all(len(option)==1 for option in options):continue
                removed.add(key);break
        if not removed:break
        for key in removed:del candidates[key]
    mutable=cross_scope_writes|{(binding.name,binding.owner)for binding in unit.bindings if binding.role=='delete'}
    return References(frozenset(candidates),MappingProxyType(blocked),MappingProxyType(lifetime),frozenset(mutable))


def _selection(model):return getattr(model,'frame_selection',None)


def alias_assignment(model,plan,node):
    selection=_selection(model)
    if selection is None or selection.references is None or model.unit is None:return False
    provider=getattr(model,'callable_cells',None)
    if provider is not None and getattr(provider,'enabled',True):return False
    caller=None if plan is model.module else model.unit.ordinal(plan.node)
    key=(caller,model.unit.ordinal(node))
    names=selection.references.blocked_assignments.get(key)
    if names:
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'source-function alias '+', '.join(repr(name)for name in names)+' is written from another lexical scope; shared call facts do not establish its current callable after those writes, and versioned callable namespace cells/dispatch are not implemented',proof='callable binding versions across global/nonlocal writes')
    names=selection.references.lifetime_assignments.get(key)
    if names:
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'source-function alias '+', '.join(repr(name)for name in names)+' also has deletion, parameter or non-reference writes; erasing only its function assignment would change binding existence/lifetime, and a runtime callable binding cell is not implemented',proof='callable binding existence and lifetime across writes')
    return key in selection.references.assignments


def call_target(model,plan,node):
    selection=_selection(model)
    if selection is None or selection.analysis is None or model.unit is None:return None
    provider=getattr(model,'callable_cells',None)
    if provider is not None and getattr(provider,'enabled',True):return None
    if isinstance(node.func,ast.Name)and selection.references is not None:
        site=model.unit.ordinal(node.func)
        binding=next((item for item in model.unit.bindings if item.node==site),None)
        if binding is not None and(binding.name,binding.owner)in selection.references.mutable_bindings:return None
    caller=None if plan is model.module else model.unit.ordinal(plan.node)
    definitions=selection.call_targets.get((caller,model.unit.ordinal(node)),())
    if len(definitions)!=1:return None
    definition=next(iter(definitions))
    return next((function for function in model.functions.values()if model.unit.ordinal(function.node)==definition),None)
