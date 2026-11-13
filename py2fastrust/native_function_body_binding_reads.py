"""Published module binding presence in native functions and source methods.

Presence is separate from the binding's current value. Runtime namespace
loads retain actual callable instances, defaults, receiver and module context.
"""
import ast



def _targets(model):
    cached=getattr(model,'initialized_module_targets',None)
    if cached is None:
        cached=frozenset(row.name for row in model.unit.bindings
            if model.module_owner(row.owner)and row.role not in {'load','parameter'}
            and model.display_name(row.name)in model.namespace.builtin_names)
        model.initialized_module_targets=cached
    return cached


def _entry(model,plan):
    contexts=getattr(model,'initialized_module_calls',{}).get(plan.index,{})
    if not contexts or any(value is None for value in contexts.values()):return None
    return frozenset.intersection(*contexts.values())


def begin(model,plan):
    """Forget derived source callsites before their original body is revisited."""
    if model.unit is None or not _targets(model):return
    for contexts in getattr(model,'initialized_module_calls',{}).values():
        for key in tuple(contexts):
            if key[0]==plan.index:del contexts[key]


def activate(model,caller,node,callee,environment):
    if model.unit is None:return
    targets=_targets(model)
    if not targets:return
    if model.is_module_plan(caller):
        incoming=frozenset(name for name in getattr(environment,'definite',())if name in targets)
    else:incoming=_entry(model,caller)
    table=getattr(model,'initialized_module_calls',None)
    if table is None:table={};model.initialized_module_calls=table
    table.setdefault(callee.index,{})[(caller.index,id(node))]=incoming


def snapshot(model):
    return tuple((plan,tuple((key,None if value is None else tuple(sorted(value)))
                for key,value in sorted(contexts.items())))
                for plan,contexts in sorted(getattr(model,'initialized_module_calls',{}).items()))


def _origin(model,node):
    unit=model.unit
    return unit.original_unit(node)if hasattr(unit,'original_unit')else unit


def _enclosing_publication(model,plan,origin):
    for statement in origin.tree.body:
        if any(child is plan.node for child in ast.walk(statement)):
            return statement
    return None


def _direct_events(model,origin,writes):
    definitions={row.node for row in writes if row.role=='definition'}
    stores={row.node for row in writes if row.role=='store'}
    for statement in origin.tree.body:
        if isinstance(statement,ast.FunctionDef)and model.unit.ordinal(statement)in definitions:
            yield statement
        elif isinstance(statement,ast.Assign)and any(
                isinstance(target,ast.Name)and model.unit.ordinal(target)in stores
                for target in statement.targets):
            yield statement
        elif isinstance(statement,ast.AnnAssign)and statement.value is not None and isinstance(statement.target,ast.Name):
            if model.unit.ordinal(statement.target)in stores:yield statement


def _shared_publication(model,plan,node):
    """Only a publication clue; mutable identity and effects stay independent."""
    from .native_constraints import FunctionValue
    selection=getattr(model,'frame_selection',None)
    analysis=getattr(selection,'analysis',None)
    if analysis is None or analysis.graph.unit is not model.unit:return False
    unit=model.unit
    site=unit.ordinal(node)
    definition=unit.ordinal(plan.node)
    values=[facts.values[site]for key,facts in analysis.scopes.items()
            if key[0]==definition and site in facts.values]
    return bool(values)and all(not value.unknown and not value.unbound and value.alternatives
        and all(isinstance(part,FunctionValue)for part in value.alternatives)for value in values)


def read(provider,plan,node):
    model=provider.model
    if (model.unit is None or plan.class_body is not None or model.is_module_plan(plan)
            or not isinstance(node,ast.Name)):
        return None
    name=model.resolved_name(plan,node)
    if provider.spelling(name)not in model.namespace.builtin_names:return None
    binding=model.namespace.owners.get(model.unit.ordinal(node))
    if binding is None or not model.module_owner(binding.owner):return None
    writes=[row for row in model.unit.bindings if row.owner==binding.owner and row.name==name
            and row.role not in {'load','parameter'}]
    if not writes:return None
    actual=[cell for key,cell in model.namespace.incoming.get(name,{}).items()
            if key!=('builtin',name)]
    if not actual:return None
    from .native_class_body_function_reads import _effects_closed,_is_unbinding,_unbinding_can_execute
    if not _effects_closed(model,provider,name):return None
    nodes={model.unit.ordinal(child):child for child in model.iter_nodes()}
    if any(_is_unbinding(row,nodes)and _unbinding_can_execute(model,row)for row in writes):return None
    origin=_origin(model,node)
    enclosure=_enclosing_publication(model,plan,origin)
    events=tuple(_direct_events(model,origin,writes))
    structural=(enclosure is not None and any(origin.tree.body.index(event)<origin.tree.body.index(enclosure)
                                             for event in events))
    incoming=_entry(model,plan)
    initialized=incoming is not None and name in incoming
    if not structural and not initialized and not _shared_publication(model,plan,node):return None
    from .native_classes import Cell,shape
    from .native_class_globals import complete
    from .native_aot_callables import AotFunctionType
    # Keep a pending producer pending. A synthetic builtin must not become the
    # sole known payload before a returned closure's constraints have settled.
    if len(actual)==1:value=actual[0]
    elif any(not complete(shape(cell))for cell in actual):
        value=Cell()
    else:
        from .native_constraints import Variable
        kind=model.namespace.value_kind(Variable(('native_function_initialized',plan.index,name),'value'),actual)
        if kind is None:return None
        value=model.namespace.representation(kind,actual,node)
    provider.require_binding(name,node)
    from .native_types import alternatives
    for kind in alternatives(shape(value)):
        if isinstance(kind,AotFunctionType):provider.used.update(kind.definitions)
    provider.builtin_sites.pop((plan.index,id(node)),None)
    linked=getattr(provider,'linked_builtins',None)
    if linked is not None:linked.sites.pop((plan.index,id(node)),None)
    return model.flow_copy(value)
