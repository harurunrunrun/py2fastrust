"""Construct proved immutable class callable bindings from their actual owner."""
import ast


def definition(model,member,stored):
    from .native_aot_callables import AotFunctionType
    from .native_function_instances import instanced
    from .native_value_classes import selected
    owner,plan=member.owner,member.plan
    if plan is None or not selected(model,owner):return None
    if getattr(model,'module_linker',None)is None:return None
    unit=model.unit
    if owner.node not in unit.original_unit(owner.node).tree.body:return None
    if not isinstance(plan.node,ast.FunctionDef)or plan.node not in owner.node.body:return None
    if member.descriptor not in {'function','classmethod'}:return None
    if member.descriptor=='function'and plan.node.decorator_list:return None
    if model.lexical.parent_scope(plan)is not None or instanced(model.lexical,plan):return None
    if any(symbol.has('free')or symbol.has('nonlocal')for symbol in unit.scope_for(plan.node).symbols):return None
    number=model.callable_cells.definition(plan)
    if stored!=AotFunctionType((number,)):return None
    scope=unit.scope_for(owner.node).ordinal
    writes=[binding for binding in unit.bindings
            if binding.owner==scope and binding.name==member.name and binding.role!='load']
    if len(writes)!=1 or writes[0].role!='definition'or writes[0].node!=unit.ordinal(plan.node):return None
    # Function metadata remains an ordinary object capability. Do not replace
    # an observed function namespace/default/annotation object with a fresh
    # carrier when a source attribute could observe or modify that metadata.
    for reached in model.plans:
        if not reached.reachable:continue
        for node in ast.walk(reached.node):
            if not isinstance(node,ast.Attribute):continue
            cell=model.records.get((reached.index,id(node.value)))
            if cell is None:continue
            from .native_classes import shape
            kind=shape(cell)
            if isinstance(kind,AotFunctionType)and number in kind.definitions:return None
    return number


def prepared_definition(registry,member,stored):
    model=registry.model
    cache=getattr(registry,'immutable_function_bindings',None)
    if cache is None:
        cache={};registry.immutable_function_bindings=cache
    key=(member.owner.index,member.name)
    if key not in cache:cache[key]=definition(model,member,stored)
    return cache[key]


def emit(registry,emitter,node,reference,member,stored):
    number=prepared_definition(registry,member,stored)
    if number is None:return None
    from .native_classes import Expression
    # The captured class carries the module of this actual successful class
    # execution, including saved class aliases and failed-import retries.
    return Expression(f'ClassFunctionRef::F{number}(({reference.code}).module.clone())',stored)
