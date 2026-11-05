"""Dependency-directed body analysis with a fair semantic fixed-point barrier.

The complete existing snapshot and fair sweeps cover heap, namespace, alias and
registry dependencies that are not represented by function call interfaces.
"""
from collections import deque


def interfaces(model):
    from .native_classes import shape
    return {
        plan.index: (
            plan.reachable,
            None if plan.visible_definitions is None else tuple(sorted(plan.visible_definitions)),
            None if plan.global_names is None else tuple(sorted(plan.global_names)),
            shape(plan.result),
            tuple((name, shape(cell)) for name, cell in plan.arguments.items()),
        )
        for plan in model.plans
    }


def analyze(model, plan):
    from .native_guard_flow import AnalysisPending
    if plan is model.module:
        model.module.visible_definitions = set()
        try:
            model.block(model.module, model.tree.body, dict(model.global_symbols))
        except AnalysisPending:
            pass
        return
    environment = {name: value for name, value in model.global_symbols.items()
                   if name not in plan.declared}
    environment.update(plan.arguments)
    model.lexical.seed_arguments(plan)
    for name, value in plan.arguments.items():
        model.canonical_local(plan, name, value)
    try:
        remaining = model.analyze_body(plan, environment)
    except AnalysisPending:
        return
    if remaining is not None:
        from .native_classes import Cell, merge
        merge(plan.result, Cell('none'), plan.node)


def solve(model):
    from .native_class_allocation_facts import publish
    from .native_list_positions import refresh
    stats = dict(waves=0, body_analyses=0, interface_requeues=0, verification_sweeps=0)
    model.inference_runs = getattr(model, 'inference_runs', []) + [stats]
    pending = deque(plan.index for plan in model.plans if plan.reachable)
    queued = set(pending)

    def enqueue(index, *, priority=True):
        if index not in queued and index < len(model.plans) and model.plans[index].reachable:
            (pending.appendleft if priority else pending.append)(index)
            queued.add(index)
            stats['interface_requeues'] += 1

    def schedule_changes(before, after):
        changed = [key for key, value in after.items() if before.get(key) != value]
        if not changed:
            return
        parents = {}
        for caller, callees in model.call_edges.items():
            for callee in callees:
                parents.setdefault(callee, set()).add(caller)
        for target in changed:
            enqueue(target)
            for caller in sorted(parents.get(target, ())):
                enqueue(caller)

    while True:
        stats['waves'] += 1
        # This is a scheduling quantum, not a convergence limit. Preserve
        # dirty work for the next wave so a derived interface oscillation
        # cannot starve the mandatory original-order verification sweep.
        for _ in range(max(1, len(model.plans))):
            if not pending:
                break
            index = pending.popleft()
            queued.remove(index)
            before = interfaces(model)
            analyze(model, model.plans[index])
            stats['body_analyses'] += 1
            schedule_changes(before, interfaces(model))

        # Preserve the original transfer order as an explicit verification
        # barrier. Some registry shapes are derived, rather than monotone;
        # a checkpoint after an arbitrary queue order cannot replace this.
        while True:
            before_verification = checkpoint(model)
            before_interfaces = interfaces(model)
            analyze(model, model.module)
            stats['body_analyses'] += 1
            for plan in model.plans[1:]:
                if plan.reachable:
                    analyze(model, plan)
                    stats['body_analyses'] += 1
            publish(model)
            refresh(model)
            stats['verification_sweeps'] += 1
            if checkpoint(model) == before_verification:
                return
            after_interfaces = interfaces(model)
            schedule_changes(before_interfaces, after_interfaces)
            # A queued linked initializer can temporarily clear its derived
            # publication scope; callers in the original sweep restore it.
            # Stabilize those scope facts without another out-of-order pass
            # before deciding whether further type propagation is required.
            before_scopes = tuple((key, value[1:3]) for key, value in before_interfaces.items())
            after_scopes = tuple((key, value[1:3]) for key, value in after_interfaces.items())
            if before_scopes == after_scopes:
                break
        for plan in model.plans:
            if plan.reachable:
                enqueue(plan.index, priority=False)


def checkpoint(model):
    return (model.snapshot(),
            tuple((caller, tuple(sorted(targets)))
                  for caller, targets in sorted(model.call_edges.items())),
            tuple((site, tuple(sorted(targets)))
                  for site, targets in sorted(model.call_edges_by_site.items())))
