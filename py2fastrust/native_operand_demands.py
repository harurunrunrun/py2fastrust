"""Source value demands for private, witnessed native function entries.

Source binding and operand evaluation remain distinct from physical argument
transport. A code-less operand is a capability for one checked invocation;
it is never a Python value or a general native Expression.
"""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class PrivateProjection:
    plan: object
    mode: object
    erased_names: frozenset
    erased_ordinals: tuple
    covered_reads: tuple


@dataclass(frozen=True)
class ClassAccess:
    caller: object
    call: object
    mode: object
    definition: int
    kind: object
    name: str
    slot: int
    projections: tuple
    binding: object = None


@dataclass(frozen=True)
class ClassOperand:
    kind: object
    access: ClassAccess


class Registry:
    def __init__(self, model, state):
        self.model = model
        self.state = state
        self.projections = {}
        self.accesses = []
        self.reasons = {}
        if state is None or state.barrier is not None or not state.bridges:
            return
        from .native_call_context_effects import source_plan, incoming_module, unused_parent
        from .native_class_binding_contexts import parameter
        from .native_class_calls import entry_result
        from .native_function_instances import instanced
        for index, abi in state.abis.items():
            plan = abi.plan
            source = source_plan(plan)
            mode = state.modes.get(('function', index))
            if (source is None or mode is None or not isinstance(source.node, ast.FunctionDef)
                    or index in state.producers or incoming_module(model, plan)
                    or not unused_parent(model, plan) or parameter(model, plan)
                    or model.lexical.parent_scope(source) is not None
                    or model.lexical.scope(source) in model.lexical.environments
                    or instanced(model.lexical, source) or not entry_result(model, plan)
                    or tuple(plan.runtime_parameters) != tuple(source.signature.parameters)
                    or set(source.defaults) - set(source.default_literals)
                    or source.signature.variadic_positional or source.signature.variadic_keyword):
                self.reasons[index] = 'an incoming context, instance, default or frame still needs source values'
                continue
            if any(source_plan(owner.methods.get('__init__')) is source
                   for owner in model.classes.values() if owner.methods.get('__init__') is not None):
                self.reasons[index] = 'constructor receiver/value ABI is retained'
                continue
            erased = {}
            for position, name in enumerate(plan.runtime_parameters):
                reads = self.formal_reads(plan, mode, name)
                if reads:
                    erased[name] = reads
            if erased:
                self.projections[index] = PrivateProjection(
                    plan, mode, frozenset(erased),
                    tuple(i for i, name in enumerate(plan.runtime_parameters) if name in erased),
                    tuple((name, erased[name]) for name in plan.runtime_parameters if name in erased))

    def formal_reads(self, plan, mode, name):
        from .native_classes import shape
        from .native_module_linking import ClassReferenceType
        from .native_primitive_parameter_places import readonly_parameter
        from .native_call_context_effects import source_plan
        from .native_source_total_places import receiver_formal
        model, state = self.model, self.state
        value = plan.arguments.get(name)
        if value is None or type(shape(value)) is not ClassReferenceType:
            return None
        source = source_plan(plan)
        scope = model.lexical.scope(source)
        if not readonly_parameter(model.unit, state.rows, scope, name):
            return None
        raw = {model.unit.ordinal(node): node for node in state.raw_own[plan.index]
               if id(node) in model.unit.node_ordinals}
        owned = {id(node) for node in state.own[plan.index]}
        loads = []
        for row in state.rows:
            if row.owner != scope or row.name != name or row.role == 'parameter':
                continue
            node = raw.get(row.node)
            if (row.role != 'load' or node is None or not isinstance(node, ast.Name)
                    or model.lexical.execution_scope(row.scope) != scope):
                return None
            if id(node) in owned:
                loads.append(node)
        if not loads:
            return None
        parents = model.value_classes.parents
        covered = []
        for node in loads:
            attribute = parents.get(id(node))
            read = parents.get(id(attribute))
            slot = mode.reads.get(id(read))
            if (not isinstance(attribute, ast.Attribute) or attribute.value is not node
                    or not isinstance(read, ast.Subscript) or read.value is not attribute
                    or receiver_formal(model, plan, state, mode, read, slot) != name):
                return None
            covered.append(id(read))
        return tuple(covered)


def prepare(model):
    model.operand_demands = Registry(model, getattr(model, 'source_state', None))


def private_projection(emitter):
    registry = getattr(emitter.model, 'operand_demands', None)
    if (registry is None or not getattr(emitter, 'source_state_private', False)
            or getattr(emitter, 'source_state_producer', None) is not None):
        return None
    projection = registry.projections.get(emitter.plan.index)
    active = getattr(emitter, 'source_state_active', None)
    if (projection is None or projection.plan is not emitter.plan or active is None
            or active[0] is not projection.mode):
        return None
    abi = registry.state.abis[emitter.plan.index]
    if not all(slot.key in active[1] for slot in abi.slots):
        return None
    return projection


def call_projection(emitter, node, target):
    registry = getattr(emitter.model, 'operand_demands', None)
    if (registry is None or registry.model is not emitter.model
            or getattr(emitter.model, 'source_state', None) is not registry.state
            or registry.state.barrier is not None or not registry.state.bridges):
        return None
    projection = registry.projections.get(target.index)
    if projection is None or projection.plan is not target:
        return None
    active = getattr(emitter, 'source_state_active', None)
    abi = registry.state.abis.get(target.index)
    if (active is None or not any(active[0] is mode for mode in registry.state.modes.values())
            or abi is None or abi.plan is not target
            or not all(slot.key in active[1] for slot in abi.slots)):
        return None
    from .native_source_state import call_arguments
    if call_arguments(emitter, node, target) is None:
        return None
    return projection


def bound_projection(emitter, node, source, target, binding):
    projection = call_projection(emitter, node, target)
    tokens = [(name, value) for name, value in zip(binding.parameters, binding.values)
              if isinstance(value, ClassOperand)]
    if projection is None:
        if tokens:
            raise AssertionError('a presence operand reached an ordinary source invocation')
        return None
    from .native_call_context_effects import source_plan
    from .native_classes import shape
    if (source_plan(source) is not source_plan(target)
            or tuple(binding.parameters) != tuple(target.runtime_parameters)):
        raise AssertionError('private argument projection changed its source signature')
    registry = emitter.model.operand_demands
    active = getattr(emitter, 'source_state_active', None)
    for name, value in tokens:
        access = value.access
        if (name not in projection.erased_names or access.caller is not emitter.plan
                or access.call is not node or active is None or access.mode is not active[0]
                or not any(access is approved for approved in registry.accesses)
                or not any(projection is approved for approved in access.projections)
                or access.definition != emitter.model.callable_cells.definition(source)
                or name != source.runtime_parameters[0]
                or value.kind != shape(target.arguments[name])):
            raise AssertionError('a presence operand has no matching source-entry capability')
    for name, value in zip(binding.parameters, binding.values):
        if name in projection.erased_names and value.kind != shape(target.arguments[name]):
            raise AssertionError('erased source formal still requires a value coercion')
    return projection


def capture_access(emitter, node, request, *, record=True):
    """Check the original global class Name before any explicit arguments."""
    registry = getattr(emitter.model, 'operand_demands', None)
    active = getattr(emitter, 'source_state_active', None)
    if registry is None or active is None or request is None:
        return None
    state, model = registry.state, emitter.model
    if (not isinstance(node, ast.Call) or request.node is not node.func
            or request.direct_definition is None or not isinstance(node.func, ast.Attribute)
            or not isinstance(node.func.value, ast.Name)):
        return None
    mode, values = active
    targets = mode.calls.get(id(node), ())
    if not targets:
        return None
    receiver = node.func.value
    from .native_module_linking import ClassReferenceType
    kind = emitter.kind(receiver)
    if type(kind) is not ClassReferenceType:
        return None
    owner = model.class_namespaces.owners.get(kind.definition)
    binding = model.lexical.binding(receiver)
    key = model.resolved_name(emitter.plan, receiver)
    if (owner is None or binding is None or not model.module_owner(binding.owner)
            or not model.namespace.owns(emitter.plan, receiver)
            or key != model.class_key(owner) or not state.class_root(owner)
            or emitter.plan.module_name != owner.module_name
            or dict(model.namespace.fields()).get(key) != kind):
        return None
    members = model.class_namespaces.attribute_reads.get((emitter.plan.index, id(node.func)), ())
    if (len(members) != 1 or members[0].owner is not owner
            or members[0].plan is None or members[0].descriptor != 'classmethod'
            or request.target.definition != request.direct_definition
            or request.target.class_definition != owner.index
            or request.target._native_receiver_kind != kind):
        return None
    from .native_immutable_class_functions import prepared_definition
    member = members[0]
    stored = dict(model.namespace.fields()).get(member.key)
    if prepared_definition(model.class_namespaces, member, stored) != request.direct_definition:
        return None
    projections = []
    for index in targets:
        plan = state.plans.get(index)
        projection = None if plan is None else call_projection(emitter, node, plan)
        if (projection is None or not plan.runtime_parameters
                or plan.runtime_parameters[0] not in projection.erased_names
                or model.callable_cells.definition(plan) != request.direct_definition):
            return None
        abi = state.abis[index]
        if not all(slot.key in values and slot.owner is owner for slot in abi.slots):
            return None
        projections.append(projection)
    from .native import _string
    slot = model.namespace.index(key)
    from .native_source_class_bindings import certify
    binding = None
    for projection in projections:
        for state_slot in state.abis[projection.plan.index].slots:
            binding = certify(state,state_slot,key)
            if binding is not None:break
        if binding is not None:break
    access = ClassAccess(emitter.plan, node, mode, request.direct_definition,
                         kind, key, slot, tuple(projections),binding)
    if record:
        registry.accesses.append(access)
    if binding is not None:
        return '',ClassOperand(kind,access)
    message = _string("NameError: name '" + model.display_name(key) + "' is not defined")
    check = ('{let class_operand_namespace=class_scope.globals.borrow();'
             + 'class_operand_namespace.value_' + str(slot)
             + '.as_ref().map(|_|()).ok_or_else(||' + message + '.to_owned())}')
    temporary = emitter.fresh()
    return ('let ' + temporary + '=' + emitter.at(check, receiver) + ';',
            ClassOperand(kind, access))
