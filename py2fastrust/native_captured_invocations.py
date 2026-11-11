"""Owned source invocation binding and closed typed continuation regions.

These records are compiler IR.  Source signatures/defaults remain owned by the
original callable; generated transfers carry concrete native frame fields.
"""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class BoundInvocation:
    source: object
    target: object
    values: tuple
    extra_context: str
    projection: object = None

    def call_code(self, emitter):
        if self.projection is not None:
            raise ValueError('a projected invocation needs its certified private entry')
        return (emitter.function_name(self.target) + '(class_scope.clone()'
                + self.extra_context
                + (',' + ','.join(self.values) if self.values else '') + ')')

    def frame_code(self):
        if self.projection is not None:
            raise ValueError('a projected invocation has no ordinary frame ABI')
        if self.extra_context:
            raise ValueError('this invocation needs additional owned frame ABI fields')
        return ('ClassNativeFrame_' + str(self.target.index)
                + '::new(class_scope.clone()'
                + (',' + ','.join(self.values) if self.values else '') + ')')


def bind_definition(emitter, node, definition, positional, keywords, *, captured_class_context=None):
    """Use the original default/signature binder before native target choice."""
    from .call_semantics import CallBindingError
    from .native_classes import ClassUnsupported, shape
    provider = emitter.model.callable_cells
    source = provider.plans[definition]
    default_emitter = emitter.model.emitter(source)
    parent = emitter.model.lexical.parent_scope(source)
    is_lambda = isinstance(source.node, ast.Lambda)
    from .native_function_instances import instanced
    has_instance = instanced(emitter.model.lexical, source)
    if is_lambda:
        default_emitter.lambda_instance_override = 'class_selected_environment'
    if has_instance:
        default_emitter.function_instance_override = 'class_selected_environment.data'
    if parent:
        default_emitter.lexical_environment_override = ('class_selected_environment.environment'
            if is_lambda or has_instance else 'class_selected_environment')
    try:
        from .native_variadic import pack_emission
        bound = source.signature.bind(positional, keywords,
            default_emitter.captured_defaults(source),
            pack_positional=lambda members: pack_emission(emitter, source, members, node))
    except CallBindingError as failure:
        raise ClassUnsupported(node, str(failure)) from None
    from .native_frame_specialization import native_target
    target = native_target(emitter.model, source, bound.by_name)
    from .native_operand_demands import ClassOperand, bound_projection
    projection = bound_projection(emitter, node, source, target, bound)
    erased = projection.erased_names if projection is not None else frozenset()
    values = []
    for name, value in zip(bound.parameters, bound.values):
        if name in erased:
            continue
        if isinstance(value, ClassOperand):
            raise ValueError('a code-less operand cannot enter a value parameter')
        values.append(emitter.coerce(value, shape(target.arguments[name]), node))
    from .native_call_context_effects import unused_parent
    from .native_class_binding_contexts import invocation as class_context_argument, parameter as class_context_parameter
    from .native_class_value_demands import private as private_class_context
    receiver = None
    if positional and class_context_parameter(emitter.model, target):
        if isinstance(positional[0], ClassOperand):
            raise ValueError('a code-less operand cannot supply class context')
        receiver = positional[0].code
    context = class_context_argument(emitter.model, target,
        receiver, caller=emitter.plan, node=node,
        captured_class_context=captured_class_context,
        private=private_class_context(emitter,node,target))
    lexical = ((',class_selected_environment.environment.clone()'
                if is_lambda or has_instance else ',class_selected_environment.clone()')
               if parent and not unused_parent(emitter.model, target) else '')
    return BoundInvocation(source, target, tuple(values), lexical + context, projection)


@dataclass(frozen=True)
class CapturedInvocation:
    definition: int
    target: object
    site: object


@dataclass(frozen=True)
class FrameAbi:
    plan: object
    # The actual ClassScope is owned by every frame. Its globals are taken
    # from the captured callable, never reconstructed from a module cache.
    actual_scope: bool = True
    lexical_environment: object = None
    constructor_role: bool = False
    retained_python_values: tuple = ()
    implicit_error_only: bool = True


def components(graph):
    """SCCs over the complete explicit and implicit native activation graph."""
    order = []
    seen = set()
    for root in graph:
        if root in seen:
            continue
        stack = [(root, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend((child, False) for child in graph[node] if child not in seen)
    reverse = {node: set() for node in graph}
    for node, children in graph.items():
        for child in children:
            reverse[child].add(node)
    result = []
    seen = set()
    for root in reversed(order):
        if root in seen:
            continue
        group = set()
        stack = [root]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            group.add(node)
            stack.extend(reverse[node] - seen)
        result.append(frozenset(group))
    return tuple(result)


SCALARS = frozenset({'int', 'bool', 'int_bool', 'float', 'str', 'bytes', 'none'})


def closed_value(kind):
    from .native_types import ListType, SharedListType, TupleType
    if kind in SCALARS:
        return True
    if type(kind) in {ListType, SharedListType}:
        return kind.element in SCALARS
    if type(kind) is TupleType:
        return all(closed_value(part) for part in kind.fields)
    return kind == 'range'


class Regions:
    """A bounded first owned-ABI certificate, with per-SCC coverage closure."""
    def __init__(self, registry):
        self.registry = registry
        self.model = registry.model
        self.plans = {plan.index: plan for plan in self.model.plans if plan.reachable}
        edges = {index: set(self.model.call_edges.get(index, ())) for index in self.plans}
        self.missing_targets = {index: targets - self.plans.keys()
                                for index, targets in edges.items()}
        self.graph = {index: targets & self.plans.keys() for index, targets in edges.items()}
        self.reasons = {}
        self.captured = {}
        self.direct = {}
        self.abis = {}
        self.covered = {}
        self.covered_sites = {}
        self.groups = components(self.graph)
        self.original_nodes = {id(node): node for node in self.model.iter_nodes()}

    def source(self, plan):
        return self.registry.source(plan)

    def kind(self, plan, node):
        from .native_classes import shape
        value = self.model.records.get((plan.index, id(node)))
        return None if value is None else shape(value)

    def nodes(self, plan):
        return [node for node in self.model.value_classes.own_nodes(plan)
                if not self.registry.omitted(plan, node)]

    def proof(self, plan):
        from .native_classes import shape
        from .native_aot_callables import AotFunctionType
        from .native_module_linking import ModuleType
        from .native_invocation_control import canonical_identities
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        model = self.model
        source = self.source(plan)
        if self.missing_targets[plan.index]:
            return 'a native producer target has no reached plan/interface'
        if model.is_module_plan(plan) or getattr(source, 'class_body', None) is not None:
            return 'publication/import entries keep their existing convention'
        if not isinstance(source.node, ast.FunctionDef) or source.owner is not None:
            return 'this frame needs a different source invocation role'
        unit = model.unit.original_unit(source.node) if hasattr(model.unit, 'original_unit') else model.unit
        if unit is None or source.node not in unit.tree.body:
            return 'nested source definitions need an owned lexical FrameAbi'
        args = source.node.args
        if source.node.decorator_list or source.node.type_params or args.vararg or args.kwarg:
            return 'decorated/generic/variadic callable metadata needs another ABI role'
        if model.lexical.parent_scope(source) is not None or model.lexical.signature(plan):
            return 'the actual lexical environment needs an owned FrameAbi field'
        from .native_class_binding_contexts import parameter as class_context_parameter
        if class_context_parameter(model, plan) or getattr(plan, 'erased_context_parameters', ()):
            return 'the entry has another physical context formal not owned by this FrameAbi'
        own = model.lexical.environments.get(model.lexical.scope(plan))
        if own is not None:
            return 'published closure cells need an owned frame root'
        if any(shape(value) not in SCALARS for value in
               [*plan.arguments.values(), plan.result,
                *(cell for values in plan.locals.values() for cell in values)]):
            return 'a non-scalar source place needs its physical FrameAbi'
        if any(len({shape(cell) for cell in values}) > 1 for values in plan.locals.values()):
            return 'type-changing source places need their own frame rule'
        forbidden = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda,
            ast.GeneratorExp, ast.Yield, ast.YieldFrom, ast.Await, ast.Try, ast.TryStar,
            ast.With, ast.AsyncWith, ast.TypeAlias, ast.NamedExpr, ast.Delete,
            ast.Import, ast.ImportFrom)
        local_covered = set()
        local_sites = {}
        for node in self.nodes(plan):
            if isinstance(node, forbidden):
                return 'this source producer needs its own continuation/control role'
            if isinstance(node, ast.AnnAssign) and any(isinstance(part,
                    (ast.Call, ast.NamedExpr, ast.Lambda)) for part in ast.walk(node.annotation)):
                return 'an effectful deferred annotation has no typed activation role'
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                return 'a field store needs an owned place descriptor'
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                if model.namespace.owns(plan, node):
                    name = model.resolved_name(plan, node)
                    field = dict(model.namespace.fields()).get(name)
                    if field is not None and field not in SCALARS:
                        return 'a namespace replacement can release an unproved payload'
            if isinstance(node, ast.expr):
                kind = self.kind(plan, node)
                parent = self.registry.parents.get(id(node))
                # Callees and their module/stream receiver lookups retain the
                # original emitter's checked capture, not a Python scalar ABI.
                lookup = (isinstance(parent, ast.Call) and parent.func is node
                          or isinstance(parent, ast.Attribute) and parent.value is node)
                if kind is not None and not closed_value(kind) and not lookup:
                    return 'this expression has a callback/lifetime-bearing value'
            if not isinstance(node, ast.Call):
                continue
            identities = canonical_identities(self.kind(plan, node.func))
            site = model.callable_cells.sites.get((plan.index, id(node)))
            if site is not None:
                for family in ('builtins', 'members', 'errors'):
                    identities.update(getattr(site, family, {}))
            from .native_physical_list_builtins import static_builtin
            if isinstance(node.func, ast.Name):
                spelling = model.display_name(model.resolved_name(plan, node.func))
                if static_builtin(model, plan, node.func, spelling):
                    identities.add(BuiltinIdentity(spelling))
            if self.kind(plan, node.func) is None and not identities:
                return 'the callee has no checked point identity or canonical intrinsic proof'
            if any((isinstance(identity, BuiltinIdentity)
                    or isinstance(identity, BuiltinRef) and identity.module == 'builtins') and identity.name in {
                    'id', 'hash', 'vars', 'dir', 'locals', 'globals', 'eval', 'exec',
                    'compile', 'getattr', 'setattr', 'delattr', 'type', '__import__', 'exit', 'quit'}
                   or isinstance(identity, BuiltinRef) and identity.module not in {'builtins', 'sys'}
                   or isinstance(identity, BuiltinRef) and identity.module == 'sys'
                      and identity.name not in {'getrecursionlimit', 'setrecursionlimit'}
                   for identity in identities):
                return 'the service can observe or reenter an unproved frame'
            key = plan.index, id(node)
            targets = set(model.call_edges_by_site.get(key, ()))
            if not targets:
                continue
            if len(targets) != 1:
                return 'finite source alternatives need their typed transfer variants'
            if any(isinstance(arg, ast.Starred) for arg in node.args) or any(
                    keyword.arg is None for keyword in node.keywords):
                return 'expanded arguments need their own ordered capture producer'
            target = self.plans.get(next(iter(targets)))
            if target is None:
                return 'the actual source target has no reached native interface'
            kind = self.kind(plan, node.func)
            definition_plan = (model.callable_cells.plans.get(kind.targets[0])
                               if isinstance(kind, AotFunctionType) and len(kind.targets) == 1
                               and isinstance(kind.targets[0], int) else None)
            if (definition_plan is not None
                    and isinstance(kind.targets[0], int) and site is not None
                    and kind.targets[0] in site.targets and not site.errors
                    and self.source(target) is self.source(definition_plan)):
                self.captured[key] = CapturedInvocation(kind.targets[0], target, site)
            else:
                from .native_frame_references import call_target
                if (not isinstance(node.func, ast.Name)
                        or call_target(model, plan, node) is not self.source(target)):
                    return 'the actual source callee needs another capture/binding producer'
                if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
                    return 'this direct invocation needs the shared binder sink'
                if len(node.args) != len(target.runtime_parameters):
                    return 'binding-error source calls retain the existing adapter'
                self.direct[key] = target
            local_covered.update(targets)
            local_sites[key] = frozenset(targets)
        if local_covered != self.graph[plan.index]:
            return 'an implicit native/source activation has no typed transfer producer'
        for key, targets in model.call_edges_by_site.items():
            if key[0] == plan.index and frozenset(targets) != local_sites.get(key, frozenset()):
                return 'an implicit source site has no complete owned transfer producer'
        self.covered[plan.index] = local_covered
        self.covered_sites.update(local_sites)
        self.abis[plan.index] = FrameAbi(plan, retained_python_values=tuple(
            shape(value) for value in [*plan.arguments.values(), plan.result,
                *(cell for values in plan.locals.values() for cell in values)]))
        return None

    def incoming_closed(self, target):
        """Only existing explicit source entry adapters are certified here."""
        source = self.source(target)
        seen = set()
        for (caller, site_id), targets in self.model.call_edges_by_site.items():
            if target.index not in targets:
                continue
            seen.add(caller)
            plan = self.plans.get(caller)
            node = self.original_nodes.get(site_id)
            if plan is None or not isinstance(node, ast.Call):
                return False
            site = self.model.callable_cells.sites.get((caller, site_id))
            if site is not None and any(self.source(self.model.callable_cells.plans[definition]) is source
                    for definition in site.targets if definition in self.model.callable_cells.plans):
                continue
            function = (self.model.functions.get(self.model.resolved_name(plan, node.func))
                        if isinstance(node.func, ast.Name) else None)
            if function is None or self.source(function) is not source:
                return False
        return all(target.index not in targets or caller in seen
                   for caller, targets in self.graph.items())

    def transfer_points_closed(self, plan, targets, selected):
        def suspended(node):
            return any((plan.index, id(child)) in targets
                       and targets[plan.index, id(child)].index in selected
                       for child in ast.walk(node) if isinstance(child, ast.Call))
        for node in self.nodes(plan):
            if not isinstance(node, ast.expr) or not suspended(node):
                continue
            if self.kind(plan, node) is None:
                return False
            children = []
            if isinstance(node, ast.Call):
                if (plan.index, id(node.func)) in self.model.records:
                    children.append(node.func)
                children.extend(node.args)
                children.extend(keyword.value for keyword in node.keywords)
            elif isinstance(node, ast.BinOp):
                children = [node.left, node.right]
            elif isinstance(node, ast.UnaryOp):
                children = [node.operand]
            elif isinstance(node, ast.Subscript):
                children = [node.value, node.slice]
            elif isinstance(node, (ast.Tuple, ast.List)):
                children = node.elts
            if any(self.kind(plan, child) is None for child in children):
                return False
        return True

    def select(self):
        from .native_class_calls import synchronous
        from .native_typed_continuations import control_reason
        valid = set()
        for index, plan in self.plans.items():
            reason = self.proof(plan)
            if reason is None and not self.incoming_closed(plan):
                reason = 'an incoming implicit source entry has no certified Result adapter'
            if reason is None:
                valid.add(index)
            else:
                self.reasons[index] = reason
        # No component may straddle an unproved implicit/retained helper cycle.
        for group in self.groups:
            if not group <= valid:
                valid.difference_update(group)
        while True:
            before = set(valid)
            valid = {index for index in valid if self.graph[index] <= valid}
            selected = {index for index in valid if not synchronous(self.model, self.plans[index])}
            targets = {**self.direct, **{key: capture.target for key, capture in self.captured.items()}}
            for index in tuple(valid):
                reason = control_reason(self.registry, self.plans[index], targets, selected)
                if (reason is None and index in selected
                        and not self.transfer_points_closed(self.plans[index], targets, selected)):
                    reason = 'a transferred expression has no complete original point interface'
                if reason is not None:
                    self.reasons[index] = reason
                    valid.discard(index)
            for group in self.groups:
                if not group <= valid:
                    valid.difference_update(group)
            if valid == before:
                break
        return {index: self.plans[index] for index in valid
                if not synchronous(self.model, self.plans[index])}


def install_regions(registry):
    """Select before emission; an unproved region keeps the existing ABI."""
    from .native_invocation_control import InvocationLedger, InvocationProducer
    from .native_class_calls import synchronous
    proof = Regions(registry)
    registry.region_proof = proof
    selected = proof.select()
    if not selected:
        return False
    registry.plans = selected
    registry.targets = {}
    registry.captured = {}
    registry.invocations = InvocationLedger(registry.model, registry.source)
    for key, capture in proof.captured.items():
        if key[0] not in selected:
            continue
        node = next(node for node in proof.nodes(selected[key[0]]) if id(node) == key[1])
        producer = InvocationProducer(selected[key[0]], node, 'captured_function',
            capture.target, tuple(node.args))
        registry.invocations.producers[key] = producer
        registry.invocations.covered.add((*key, capture.target.index))
        registry.targets[key] = capture.target
        registry.captured[key] = capture
    for key, target in proof.direct.items():
        if key[0] not in selected:
            continue
        node = next(node for node in proof.nodes(selected[key[0]]) if id(node) == key[1])
        registry.invocations.describe(selected[key[0]], node, {target.index})
        registry.targets[key] = target
    # A root entry cannot be called by a source function. It may use its
    # existing Result body when every reached child already has that ABI;
    # this does not make it a NoSuspend/borrowable source activation.
    module = registry.model.module
    root_result = all(index in selected or synchronous(registry.model, proof.plans[index])
                      for index in proof.graph[module.index])
    root_sites = set().union(*(set(targets) for (caller, _), targets
                              in registry.model.call_edges_by_site.items()
                              if caller == module.index))
    root_result = (root_result and not proof.missing_targets[module.index]
                   and root_sites == proof.graph[module.index])
    root_result = root_result and not any(isinstance(node, (ast.With, ast.AsyncWith,
        ast.Try, ast.TryStar, ast.Yield, ast.YieldFrom, ast.GeneratorExp,
        ast.Await, ast.AsyncFunctionDef, ast.TypeAlias)) for node in proof.nodes(module))
    registry.result_entries = set(selected) | ({module.index} if root_result else set())
    registry.reason = None
    return True
