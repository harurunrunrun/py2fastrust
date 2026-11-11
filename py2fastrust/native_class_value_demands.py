"""Value demands of actual defining classes at certified private entries.

A source class is still published as an ordinary class object. Its private
entries may omit that object only when every use consumes static identity or
constructs a value carrying the already-published metadata marker.
"""
import ast


def marker_constructor(model, owner):
    return owner.index in getattr(model, 'marker_constructors', ())


def private(emitter, node, target):
    if target.index not in getattr(emitter.model, 'erased_class_contexts', ()):
        return False
    from .native_source_state import call_arguments
    return call_arguments(emitter, node, target) is not None


def _identity_operand(emitter, node):
    from .native_classes import InstanceType
    kind = emitter.kind(node)
    if isinstance(kind, InstanceType):
        from .native_sealed_class_identity import match
        return match(emitter.model, emitter.plan, emitter.model.classes.get(kind.name)) is not None
    return type(kind) is str and kind in {'int', 'bool', 'int_bool', 'float', 'str', 'bytes', 'none'}


def prepare(model):
    model.marker_constructors = set()
    model.erased_class_contexts = set()
    state = getattr(model, 'source_state', None)
    if state is None or state.barrier is not None or not state.bridges:
        return
    published = getattr(model, 'published_metadata', ())
    for owner in model.classes.values():
        initializer = owner.methods.get('__init__')
        if (owner.index in published and initializer is not None
                and initializer.index in state.abis
                and initializer.index in getattr(model, 'private_module_demands', ())):
            model.marker_constructors.add(owner.index)
    from .native_class_binding_contexts import owner as context_owner, own_read, same_function_entry
    from .native_module_linking import ClassReferenceType
    from .native_physical_list_builtins import static_builtin
    parents = model.value_classes.parents
    candidates = set()
    for index, abi in state.abis.items():
        owner = context_owner(model, abi.plan)
        if owner is None or owner.index not in published:
            continue
        mode = state.modes['function', index]
        emitter = model.emitter(abi.plan)
        emitter.source_state_private = True
        emitter.source_state_active = mode, {slot.key: 'class_value_witness' for slot in abi.slots}
        safe = True
        for node in state.own[index]:
            if not isinstance(node, ast.Name) or not own_read(emitter, node):
                continue
            parent = parents.get(id(node))
            if isinstance(parent, ast.Call) and parent.func is node:
                kind = emitter.kind(node)
                actual = next((c for c in model.classes.values()
                               if kind == ClassReferenceType(c.index)), None)
                initializer = None if actual is None else actual.methods.get('__init__')
                if (actual is not None and marker_constructor(model, actual)
                        and initializer is not None
                        and initializer.index in mode.calls.get(id(parent), ())):
                    continue
            if (isinstance(parent, ast.Call) and len(parent.args) == 2
                    and parent.args[1] is node and not parent.keywords
                    and not any(isinstance(arg, ast.Starred) for arg in parent.args)
                    and static_builtin(model, abi.plan, parent.func, 'isinstance')
                    and _identity_operand(emitter, parent.args[0])):
                continue
            if (isinstance(parent, ast.Compare) and len(parent.ops) == 1
                    and isinstance(parent.ops[0], (ast.Is, ast.IsNot))
                    and parent.comparators[0] is node):
                call = parent.left
                if (isinstance(call, ast.Call) and len(call.args) == 1
                        and not call.keywords and not isinstance(call.args[0], ast.Starred)
                        and static_builtin(model, abi.plan, call.func, 'type')
                        and _identity_operand(emitter, call.args[0])):
                    continue
            safe = False
            break
        if safe:
            candidates.add(index)
    # Forwarded free functions require the same exact private call point as
    # the eventual invocation. Another call of the same function is no proof.
    admitted = model.erased_class_contexts
    changed = True
    while changed:
        changed = False
        for index in candidates - admitted:
            plan = state.abis[index].plan
            mode = state.modes['function', index]
            forwarded = [(point, target) for (caller, point), targets in model.call_edges_by_site.items()
                         if caller == index for target in targets
                         if target in state.plans and same_function_entry(model, plan,
                             model.class_binding_contexts.nodes.get(point), state.plans[target])]
            if all(target in admitted and target in mode.calls.get(point, ())
                   for point, target in forwarded):
                admitted.add(index)
                changed = True


def direct_operator(emitter, node, phase, arguments, wanted):
    """Call an immutable original method without materializing its owner."""
    from .native_classes import Expression, shape
    from .native_immutable_class_functions import definition
    from .native_private_module_demands import module_unused
    number = definition(emitter.model, phase.member, shape(phase.member.function_cell))
    if (number is None or phase.member.owner.index not in getattr(emitter.model, 'published_metadata', ())
            or tuple(getattr(shape(phase.site.callee), 'definitions', ())) != (number,) or phase.site.errors):
        return None
    source = emitter.model.callable_cells.plans[number]
    state = emitter.model.source_state
    active = getattr(emitter, 'source_state_active', None)
    if active is None or not module_unused(emitter, node, source):
        return None
    from .native_captured_invocations import bind_definition
    bound = bind_definition(emitter, node, number, arguments, [])
    # The original binder selects a concrete specialization from these actual
    # captured operands. Other source signatures at this execution point are
    # not invoked, so their different value demands cannot block this entry.
    if not private(emitter, node, bound.target):
        return None
    from .native_aot_callables import emit_bound_definition_body
    return Expression(emit_bound_definition_body(emitter, node, bound, wanted), wanted)
