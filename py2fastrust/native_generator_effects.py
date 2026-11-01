"""Select the generator error boundary from solved canonical call effects."""
import ast


def may_stop(unit,analysis):
    from .native_constraints import FunctionValue,MethodValue,TupleValue
    from .native_types import ListType,DequeType,alternatives
    from .native_key_types import DictType,SetType
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    generators={unit.scope_for(node).ordinal:unit.ordinal(node)for node in nodes.values()if isinstance(node,ast.GeneratorExp)}
    definitions={unit.ordinal(node):unit.scope_for(node).ordinal for node in nodes.values()
                 if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda))}
    edges={};direct=set()
    def owner(ordinal):
        scope=unit.nodes[ordinal].scope
        while scope is not None and scope not in generators and unit.scopes[scope].kind=='comprehension':scope=unit.scopes[scope].parent
        return scope
    for facts in analysis.scopes.values():
        for ordinal,call in facts.calls.items():
            if ordinal not in nodes:continue
            scope=owner(ordinal)
            identities=call.identity.alternatives
            if call.identity.unknown:direct.add(scope)
            for identity in identities:
                if not isinstance(identity,MethodValue):continue
                safe=bool(identity.receiver.alternatives)and identity.receiver.alternatives<={'str','bytes'}
                original=nodes[ordinal]
                if isinstance(original,ast.Call)and isinstance(original.func,ast.Attribute)and identity.site==unit.ordinal(original.func):
                    kind=facts.expressions.get(unit.ordinal(original.func.value))
                    choices=alternatives(kind)if kind is not None else()
                    if choices and all(part in {'str','bytes'}for part in choices):safe=True
                    elif choices and all(isinstance(part,(ListType,DequeType))for part in choices):
                        safe=identity.name in {'append','appendleft','pop','popleft','insert','clear','reverse','copy'}
                    elif choices and all(isinstance(part,DictType)for part in choices):
                        safe=identity.name in {'clear','copy','popitem','keys','values','items'}
                    elif choices and all(isinstance(part,SetType)for part in choices):
                        safe=identity.name in {'clear','copy','pop'}
                if not safe:direct.add(scope)
            if identities&{BuiltinIdentity('next'),BuiltinRef('builtins','next')} and len(call.positional)==1 and not call.keywords:
                direct.add(scope)
            targets={value.definition for value in identities if isinstance(value,FunctionValue)}
            # Key callbacks propagate their exceptions through these builtin
            # consumers; map/filter instead convert callback StopIteration to
            # normal iterator exhaustion and do not introduce this edge.
            if any(BuiltinIdentity(name)in identities for name in ('sorted','min','max')):
                for name,value in call.keywords:
                    if name=='key':targets.update(part.definition for part in value.alternatives if isinstance(part,FunctionValue))
            edges.setdefault(scope,set()).update(definitions[target]for target in targets if target in definitions)
        # The fixed-arity solver retains each expanded call's evaluated callee
        # and operand values without inventing a flattened CallFact. Read that
        # metadata directly; an immutable tuple pack proves its actual arity.
        recorded=set(facts.values)|set(facts.expressions)
        for ordinal,node in nodes.items():
            if not isinstance(node,ast.Call)or not any(isinstance(arg,ast.Starred)for arg in node.args):continue
            function=unit.ordinal(node.func)
            if ordinal not in recorded and function not in recorded:continue
            scope=owner(ordinal);callee=facts.values.get(function)
            if callee is None or callee.unknown:direct.add(scope);continue
            targets={part.definition for part in callee.alternatives if isinstance(part,FunctionValue)}
            edges.setdefault(scope,set()).update(definitions[target]for target in targets if target in definitions)
            if not callee.alternatives&{BuiltinIdentity('next'),BuiltinRef('builtins','next')}or node.keywords:continue
            count=0
            for arg in node.args:
                if not isinstance(arg,ast.Starred):count+=1;continue
                pack=facts.values.get(unit.ordinal(arg.value))
                lengths={len(part.fields)for part in pack.alternatives if isinstance(part,TupleValue)}if pack is not None else set()
                if(pack is None or pack.unknown or pack.unbound or len(lengths)!=1
                        or any(not isinstance(part,TupleValue)for part in pack.alternatives)):
                    count=None;break
                count+=next(iter(lengths))
            if count is None or count==1:direct.add(scope)
    marked=set(direct)
    while True:
        updated=marked|{scope for scope,targets in edges.items()if targets&marked}
        if updated==marked:break
        marked=updated
    return frozenset(ordinal for scope,ordinal in generators.items()if scope in marked)


def requires_frames(unit,analysis):return bool(may_stop(unit,analysis))


def model_may_stop(model):
    """Retain actual reached frame calls, including class/imported methods."""
    from .native_classes import shape
    from .native_types import alternatives
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    unit=model.unit
    nodes={id(node):node for node in model.iter_nodes()}
    generators={unit.scope_for(node).ordinal:id(node)for node in nodes.values()if isinstance(node,ast.GeneratorExp)}
    def owner(node):
        scope=unit.nodes[unit.ordinal(node)].scope
        while scope is not None and scope not in generators and unit.scopes[scope].kind=='comprehension':scope=unit.scopes[scope].parent
        return scope
    def identities(plan,node):
        site=model.callable_cells.sites.get((plan.index,id(node)))
        value=site.callee if site is not None else model.records.get((plan.index,id(node.func)))
        if value is not None:
            return {identity for kind in alternatives(shape(value))for identity in getattr(kind,'targets',())}
        identity=model.builtin_identity(plan,node.func,{})if isinstance(node.func,(ast.Name,ast.Attribute))else None
        return {identity}if identity is not None else set()
    canonical={BuiltinIdentity('next'),BuiltinRef('builtins','next')}
    edges={};marked=set()
    for (index,identity),targets in model.call_edges_by_site.items():
        node=nodes.get(identity)
        if node is None:continue
        if isinstance(node,ast.Call)and len(node.args)==2 and not node.keywords and not any(isinstance(arg,ast.Starred)for arg in node.args):
            actual=identities(model.plans[index],node)
            if actual and actual<=canonical:continue
        edges.setdefault(owner(node),set()).update(unit.scope_for(model.plans[target].node).ordinal for target in targets)
    for (index,identity),value in model.records.items():
        node=nodes.get(identity)
        if not isinstance(node,ast.Call)or node.keywords:continue
        if len(node.args)==1 and not isinstance(node.args[0],ast.Starred)and identities(model.plans[index],node)&canonical:
            marked.add(owner(node))
    while True:
        updated=marked|{scope for scope,targets in edges.items()if targets&marked}
        if updated==marked:break
        marked=updated
    return frozenset(identity for scope,identity in generators.items()if scope in marked)


def ensure_protocol(model,node,*,analysis_only=False):
    """A generator error boundary must retain its original direct cause."""
    protocol=getattr(model,'generator_exception_protocol',None)
    if protocol is not None:
        protocol.require(node)
        return
    if analysis_only:return
    unit=model.unit.original_unit(node)if hasattr(model.unit,'original_unit')else model.unit
    cache=getattr(model,'generator_stop_facts',None)
    if cache is None:cache={};model.generator_stop_facts=cache
    key=id(unit)
    if key not in cache:
        selection=getattr(model,'frame_selection',None)
        analysis=getattr(selection,'analysis',None)
        if analysis is not None and analysis.graph.unit is not unit:analysis=None
        if analysis is None:
            from .native_constraints import analyze
            analysis=analyze(unit)
        cache[key]=may_stop(unit,analysis)
    if unit.ordinal(node)in cache[key]or id(node)in model_may_stop(model):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'this generator body can raise StopIteration and requires the PEP479 RuntimeError boundary with its original direct cause and exception-chain traceback; retaining that generator exception-chain support is not implemented on this native path',proof='generator StopIteration direct cause and exception-chain ownership')
