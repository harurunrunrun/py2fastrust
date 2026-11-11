"""Incoming module demands of private source entries with actual witnesses.

The defining class and lexical environment remain separate arguments. Only
the module view can be omitted, and only at an approved private call point.
"""
import ast


def calls_closed(model, state, index, admitted):
    from .native_call_context_effects import incoming_module
    mode = state.modes['function', index]
    covered = set()
    for (caller, point), targets in model.call_edges_by_site.items():
        if caller != index:
            continue
        covered.update(targets)
        private = mode.calls.get(point, ())
        for target in targets:
            if target in private and target in admitted:
                continue
            if target not in state.plans or incoming_module(model, state.plans[target]):
                return False
    return covered == set(model.call_edges.get(index, ()))


def prepare(model):
    model.private_module_demands = set()
    state = getattr(model, 'source_state', None)
    if state is None or state.barrier is not None or not state.bridges:
        return
    from .native_class_binding_contexts import own_read
    from .native_immediate_classmethod import candidate
    from .native_operand_demands import capture_access
    from .native_classes import shape
    from .native_module_linking import ClassReferenceType
    from .references import BuiltinIdentity
    candidates = set()
    for index, abi in state.abis.items():
        plan = abi.plan
        mode = state.modes.get(('function', index))
        if mode is None or set(plan.defaults) - set(plan.default_literals):
            continue
        emitter = model.emitter(plan)
        emitter.source_state_private = True
        emitter.source_state_active = mode, {slot.key: 'module_demand_witness' for slot in abi.slots}
        nodes = state.own.get(index)
        if nodes is None:
            continue
        erased = set()
        for node in nodes:
            if (not isinstance(node, ast.Call) or id(node) not in mode.calls
                    or not isinstance(node.func, ast.Attribute)
                    or not isinstance(node.func.value, ast.Name)):
                continue
            receiver = model.records.get((plan.index,id(node.func.value)))
            function = model.records.get((plan.index,id(node.func)))
            if (receiver is None or type(shape(receiver)) is not ClassReferenceType
                    or function is None or shape(function) is None):
                continue
            request = candidate(emitter, node.func)
            if request is None:
                continue
            access = capture_access(emitter, node, request, record=False)
            if access is not None and access[1].access.binding is not None:
                erased.add(id(node.func.value))
        allowed = (ast.Return, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.If,
            ast.For, ast.While, ast.Break, ast.Continue, ast.Pass, ast.Expr,
            ast.Name, ast.Constant, ast.Tuple, ast.List, ast.Subscript, ast.Slice,
            ast.Attribute, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
            ast.IfExp, ast.Call, ast.keyword, ast.Starred, ast.Load, ast.Store,
            ast.operator, ast.unaryop, ast.boolop, ast.cmpop)
        safe = True
        for node in nodes:
            if not isinstance(node, allowed):
                safe = False
                break
            if not isinstance(node, ast.Name):
                continue
            binding = model.lexical.binding(node)
            if binding is None:
                safe = False
                break
            if not model.module_owner(binding.owner):
                continue
            builtin = model.builtin_identity(plan, node, {}) if isinstance(node.ctx, ast.Load) else None
            if (isinstance(builtin, BuiltinIdentity) or own_read(emitter, node)
                    or id(node) in erased):
                continue
            safe = False
            break
        if safe:
            candidates.add(index)
    # Start conservatively. An entry is admitted only after every original
    # explicit/implicit source edge has an independent context certificate.
    admitted = model.private_module_demands
    changed = True
    while changed:
        changed = False
        for index in candidates - admitted:
            if calls_closed(model, state, index, admitted):
                admitted.add(index)
                changed = True


def module_unused(emitter, node, source):
    if not getattr(emitter.model, 'private_module_demands', ()):
        return False
    state = getattr(emitter.model, 'source_state', None)
    active = getattr(emitter, 'source_state_active', None)
    if state is None or active is None:
        return False
    mode, values = active
    targets = mode.calls.get(id(node), ())
    # A source callable can specialize by its already-bound argument types.
    # Every reachable private target for this source definition must agree.
    from .native_call_context_effects import source_plan
    source = source_plan(source)
    matching = [state.abis[index] for index in targets if index in state.abis
                and source_plan(state.abis[index].plan) is source]
    return bool(matching) and all(abi.plan.index in emitter.model.private_module_demands
        and all(slot.key in values for slot in abi.slots) for abi in matching)
