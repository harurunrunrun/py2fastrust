"""Prove a scalar cell is initialized before any relevant closure can exist.

Value equality comes from the independently audited scalar producer graph.
This certificate only removes a presence check: the single literal store must
precede the enclosing source statement that creates the reading closure.
"""
import ast


class Registry:
    def __init__(self, model, constants):
        self.model = model
        self.constants = constants
        self.stores = {}
        self.reads = set()
        from .native_namespace_read_places import lifetime_closed
        if constants.reason is not None or not lifetime_closed(model):
            return
        nodes = {model.unit.ordinal(node): node for node in model.iter_nodes()}
        producers = {}
        for binding in model.iter_bindings():
            if binding.role != 'load':
                producers.setdefault((binding.owner, binding.name), set()).add(
                    (binding.role, binding.node))
        parents = model.value_classes.parents
        for key, writes in producers.items():
            if len(writes) != 1:
                continue
            role, ordinal = next(iter(writes))
            target = nodes.get(ordinal)
            if role != 'store' or not isinstance(target, ast.Name):
                continue
            statement = parents.get(id(target))
            if not (isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1 and statement.targets[0] is target
                    and isinstance(statement.value, ast.Constant)
                    and type(statement.value.value) in {int, bool}):
                continue
            owner = model.lexical.scope_plans.get(key[0])
            if owner is None or not isinstance(owner.node, ast.FunctionDef):
                continue
            if statement not in owner.node.body:
                continue
            self.stores[key] = (owner.node, owner.node.body.index(statement))
        for plan in constants.plans.values():
            scope = model.lexical.scope(plan)
            for node in model.value_classes.own_nodes(plan):
                if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
                    continue
                binding = constants.bindings.get(model.unit.ordinal(node))
                if binding is None or binding.scope != scope or binding.owner == scope:
                    continue
                store = self.stores.get((binding.owner, binding.name))
                if store is None or model.lexical.field_for(node) is None:
                    continue
                owner, position = store
                anchor = plan.node
                while anchor is not None and parents.get(id(anchor)) is not owner:
                    anchor = parents.get(id(anchor))
                if anchor in owner.body and owner.body.index(anchor) > position:
                    self.reads.add((plan.index, id(node)))

    def refine_contexts(self):
        """Finalize body demands before constructing any physical carriers."""
        from .native_call_context_effects import Summary, source_plan
        model = self.model
        effects = getattr(model, 'call_context_effects', None)
        if effects is None:
            return
        groups = {}
        for plan in self.constants.plans.values():
            source = source_plan(plan)
            if source is not None:
                groups.setdefault(source.index, []).append(plan)
        for index, plans in groups.items():
            previous = effects.summaries.get(index)
            if previous is None or previous.incoming_module or not previous.lexical_parent:
                continue
            required = []
            for plan in plans:
                scope = model.lexical.scope(plan)
                for node in model.value_classes.own_nodes(plan):
                    if not isinstance(node, ast.Name):
                        continue
                    binding = self.constants.bindings.get(model.unit.ordinal(node))
                    if binding is not None and binding.owner != scope:
                        required.append((plan, node))
            if required and all(self.literal_read(plan, node) for plan, node in required):
                effects.summaries[index] = Summary(False, False,
                    'all lexical reads have complete singleton scalar producers and dominate closure creation')

    def literal_read(self, plan, node):
        if (plan.index, id(node)) not in self.reads:
            return False
        kind = self.constants.kind(plan, node)
        key = self.constants.binding(plan, node)
        fact = None if key is None else self.constants.graph.constant(key)
        return kind in {'int', 'bool'} and fact is not None and fact.kind == kind


def selected(emitter, node):
    registry = getattr(emitter.model, 'initialized_lexical_scalars', None)
    return registry is not None and (emitter.plan.index, id(node)) in registry.reads
