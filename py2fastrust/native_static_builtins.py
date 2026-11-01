"""Prove compile-time builtin captures supported by the ordinary emitter.

Builtin assignment capture already keeps each lexical value in the ordinary
emitter environment. Unlike erased source-function aliases, that value need not
be the last value ever assigned to its Python name. Every reachable use still
needs a singleton static identity and an existing canonical adapter.
"""
import ast
from .references import BuiltinIdentity, CORE_BUILTINS


from .native_builtin_values import UNARY_BUILTINS,unary_capability


def capture_assignments(unit, analysis, references):
    if references is None:return frozenset()
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    parents={id(child):parent for parent in nodes.values()for child in ast.iter_child_nodes(parent)}
    bindings={binding.node:binding for binding in unit.bindings}
    values={};calls={};kinds={}
    for (caller,_),facts in analysis.scopes.items():
        for site,kind in facts.expressions.items():kinds.setdefault((caller,site),[]).append(kind)
        for site,fact in facts.calls.items():
            key=caller,site
            calls[key]=fact.identity if key not in calls else calls[key].join(fact.identity)
        for site,value in facts.values.items():
            key=caller,site
            values[key]=value if key not in values else values[key].join(value)
    by_site={}
    for key,value in values.items():by_site.setdefault(key[1],[]).append((key,value))
    writes={(binding.name,binding.owner)for binding in unit.bindings
            if binding.role not in {"load","parameter"}and binding.scope!=binding.owner}
    deletes={(binding.name,binding.owner)for binding in unit.bindings if binding.role=="delete"}
    unsupported_writes=set()
    for binding in unit.bindings:
        if binding.role in {"load","parameter"}:continue
        node=nodes[binding.node];parent=parents.get(id(node))
        if not(isinstance(node,ast.Name)and isinstance(parent,ast.Assign)
               and node in parent.targets and all(isinstance(target,ast.Name)for target in parent.targets)):
            unsupported_writes.add((binding.name,binding.owner))
    def immediate_generator(read,node):
        current=node
        while id(current)in parents:
            current=parents[id(current)]
            if isinstance(current,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda)):break
            if not isinstance(current,ast.GeneratorExp):continue
            consumer=parents.get(id(current))
            if not(isinstance(consumer,ast.Call)and consumer.args and consumer.args[0]is current):return False
            identity=calls.get((read[0],unit.ordinal(consumer)))
            if identity is None or identity.unknown or identity.unbound or len(identity.alternatives)!=1:return False
            target=next(iter(identity.alternatives))
            from .native_frame_references import _static_builtin_call
            return(isinstance(target,BuiltinIdentity)and target.name in
                   {"sum","min","max","list","tuple","set","sorted","any","all"}
                   and _static_builtin_call(target,consumer))
        return True
    def operand_capability(read,node,identity):
        parent=parents.get(id(node))
        if isinstance(parent,ast.Call)and parent.func is node and len(parent.args)==1:
            operands=kinds.get((read[0],unit.ordinal(parent.args[0])),())
        else:
            call=parent if isinstance(parent,ast.Call)else parents.get(id(parent))if isinstance(parent,ast.keyword)else None
            if not isinstance(call,ast.Call):return False
            if isinstance(parent,ast.Call):
                if len(call.args)!=2 or call.args[0]is not node:return False
                source=call.args[1]
            elif call.args:source=call.args[0]
            elif isinstance(call.func,ast.Attribute):source=call.func.value
            else:return False
            from .native_types import ListType,TupleType,TupleSequenceType,DequeType
            from .native_key_types import SetType,DictType
            operands=[]
            for kind in kinds.get((read[0],unit.ordinal(source)),()):
                if isinstance(kind,(ListType,TupleSequenceType,DequeType)):operands.append(kind.element)
                elif isinstance(kind,TupleType):operands.extend(kind.fields)
                elif isinstance(kind,(SetType,DictType)):operands.append(kind.key)
                elif kind=="str":operands.append("str")
                elif kind=="bytes":operands.append("int")
                else:return False
        return bool(operands)and all(unary_capability(identity,kind)for kind in operands)
    candidates={}
    for node in nodes.values():
        if not(isinstance(node,ast.Assign)and isinstance(node.value,ast.Name)
               and all(isinstance(target,ast.Name)for target in node.targets)):continue
        names=tuple((bindings[unit.ordinal(target)].name,bindings[unit.ordinal(target)].owner)
                    for target in node.targets)
        # Ordinary builtin capture is a lexical name binding. Replacing a
        # builtin namespace entry or a cross-frame cell needs runtime storage.
        if any(name in CORE_BUILTINS or(name,owner)in writes|deletes|unsupported_writes for name,owner in names):continue
        for (caller,_),value in by_site.get(unit.ordinal(node.value),()):
            if(not value.unknown and not value.unbound and len(value.alternatives)==1
               and isinstance(next(iter(value.alternatives)),BuiltinIdentity)
               and next(iter(value.alternatives)).name in UNARY_BUILTINS):
                candidates[(caller,unit.ordinal(node))]=names
    while True:
        removed=set()
        for key,names in candidates.items():
            for binding in unit.bindings:
                if binding.role!="load"or(binding.name,binding.owner)not in names:continue
                node=nodes[binding.node];parent=parents.get(id(node))
                for read,value in by_site.get(binding.node,()):
                    if value.unknown or value.unbound:
                        removed.add(key);break
                    identities=[part for part in value.alternatives if isinstance(part,BuiltinIdentity)]
                    if not identities:continue
                    if len(value.alternatives)!=1:
                        removed.add(key);break
                    if(read in references.static_uses and immediate_generator(read,node)
                       and operand_capability(read,node,identities[0])):continue
                    if(isinstance(parent,ast.Assign)and parent.value is node
                       and(read[0],unit.ordinal(parent))in candidates):continue
                    removed.add(key);break
                if key in removed:break
        if not removed:return frozenset(candidates)
        for key in removed:del candidates[key]
