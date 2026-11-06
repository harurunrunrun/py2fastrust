"""Omit a witnessed list receiver only for its defined readonly class formal.

This certificate consumes an existing source-order StateSlot witness. It does
not infer presence from a type, a class ordinal, or a synchronous result ABI.
All other receiver expressions keep the original checked evaluation path.
"""
import ast


def receiver_formal(model, plan, state, mode, node, slot, *, kind=None):
    """Read the original total-place certificate without creating an emitter.

    Emission may supply its existing point-kind query; preparation uses the
    solved source facts. Neither path grants a call or creates a witness.
    """
    if (state is None or slot is None or state.model is not model or state.barrier is not None
            or not state.bridges or getattr(model, 'source_state', None) is not state
            or not any(mode is known for known in state.modes.values())
            or mode.reads.get(id(node)) is not slot
            or state.slots.get(slot.key) is not slot or not state.copy_kind(slot.kind)):
        return None
    if kind is None:
        kind = lambda value: state.kind(plan, value)
    kind_for = kind
    if not (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Attribute) and isinstance(node.value.ctx, ast.Load)
            and isinstance(node.value.value, ast.Name) and isinstance(node.value.value.ctx, ast.Load)):
        return None
    if not (isinstance(node.slice, ast.UnaryOp) and isinstance(node.slice.op, ast.USub)
            and isinstance(node.slice.operand, ast.Constant)
            and type(node.slice.operand.value) is int and node.slice.operand.value == 1):
        return None
    attribute = node.value
    receiver = attribute.value
    from .native_module_linking import ClassReferenceType
    kind = kind_for(receiver)
    if type(kind) is not ClassReferenceType or kind_for(node) != slot.kind:
        return None
    namespaces = getattr(model, 'class_namespaces', None)
    if namespaces is None:
        return None
    owner = namespaces.owners.get(kind.definition)
    if owner is None or slot.owner is not owner:
        return None
    point = plan.index, id(attribute)
    members = namespaces.attribute_reads.get(point, ())
    if (namespaces.instance_reads.get(point, False) or len(members) != 1):
        return None
    member = members[0]
    if (member.owner is not owner or member.key != slot.key or member.plan is not None
            or member.function_cell is not None
            or member.name != model.resolved_name(plan, attribute)):
        return None
    from .native_types import ListType
    stored = dict(model.namespace.fields()).get(slot.key)
    if (not isinstance(stored, ListType) or stored.element != slot.kind
            or kind_for(attribute) != stored):
        return None
    unit = model.unit
    if unit is None or id(receiver) not in unit.node_ordinals:
        return None
    from .native_call_context_effects import source_plan
    original = source_plan(plan)
    if not isinstance(getattr(original, 'node', None), ast.FunctionDef):
        return None
    lexical = model.lexical
    scope = lexical.scope(original)
    binding = lexical.binding(receiver)
    if (binding is None or binding.role != 'load' or binding.owner != scope
            or lexical.execution_scope(binding.scope) != scope
            or binding.name not in original.runtime_parameters
            or binding.name not in plan.runtime_parameters):
        return None
    from .native_primitive_parameter_places import readonly_parameter
    if not readonly_parameter(unit, state.rows, scope, binding.name):
        return None
    captures = lexical.environments.get(scope)
    if ((captures is not None and binding.name in captures.fields)
            or lexical.field_for(receiver) is not None
            or model.namespace.owns(plan, receiver)):
        return None
    from .native_classes import shape
    argument = plan.arguments.get(binding.name)
    if argument is None or shape(argument) != kind:
        return None
    # State preparation already proved generation/lifetime closure. The same
    # successful append plus complete intervening NoWrite keeps this namespace
    # slot present on the same unique actual class generation. A formal's
    # original binder has run and the independent all-producer seal keeps its
    # value defined; no receiver lookup, callback or destructor is omitted.
    return binding.name if state.class_root(owner) else None


def receiver_elidable(emitter, node, slot):
    state = getattr(emitter.model, 'source_state', None)
    active = getattr(emitter, 'source_state_active', None)
    if active is None:
        return False
    mode, values = active
    if slot.key not in values:
        return False
    return receiver_formal(emitter.model, emitter.plan, state, mode, node, slot,
                           kind=emitter.kind) is not None
