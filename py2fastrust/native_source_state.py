"""Source-order, generation-sealed Copy witnesses for successful list reads.

The records below are compiler IR, not Python values or a runtime proof
interpreter.  The original checked entries remain available.  A private entry
is selected only at a certified source callpoint after its arguments have run.
"""
import ast
from dataclasses import dataclass, field


class Unproved(Exception):
    pass


@dataclass(frozen=True)
class StateSlot:
    key: object
    kind: object
    origins: frozenset
    # This is a source namespace key under the unique-generation certificate;
    # allocation sites themselves never stand for one runtime object.
    owner: object = field(compare=False, hash=False, default=None)


@dataclass
class StateMode:
    reads: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Producer:
    plan: object
    node: object
    slot: StateSlot


@dataclass(frozen=True)
class StateAbi:
    plan: object
    slots: tuple


def source(plan):
    from .native_call_context_effects import source_plan
    return source_plan(plan)


class Registry:
    def __init__(self, model):
        self.model = model
        self.slots = {}
        self.producers = {}
        self.bridges = {}
        self.abis = {}
        self.modes = {}
        self.coverage = []
        self.reasons = {}
        self.barrier = None
        self.plans = {p.index: p for p in model.plans if p.reachable}
        self.nodes = {id(n): n for n in model.iter_nodes()}
        self.rows = tuple(model.iter_bindings())
        self.raw_own = {p.index: tuple(model.value_classes.own_nodes(p))
                        for p in self.plans.values()}
        from .native_source_execution_points import owned_points
        # Class publication proofs inspect the complete raw producer inventory
        # while execution-point certificates are built for every source plan.
        self.own = self.raw_own
        linked_class_root = (self.class_root
            if getattr(model, 'module_linker', None) is not None
            and callable(getattr(model.unit, 'original_unit', None)) else None)
        refined = {p.index: tuple(owned_points(model, p, self.raw_own[p.index], self.nodes,
                                             class_root=linked_class_root))
                    for p in self.plans.values()}
        self.own = refined
        self.excluded_owned = {
            p.index: frozenset(id(node) for node in self.raw_own[p.index])
                     - frozenset(id(node) for node in self.own[p.index])
            for p in self.plans.values()}
        try:
            self.prepare()
        except Unproved as error:
            self.barrier = str(error)
            self.producers.clear(); self.bridges.clear(); self.abis.clear()
            self.modes.clear()

    def kind(self, plan, node):
        from .native_classes import shape
        cell = self.model.records.get((plan.index, id(node)))
        return None if cell is None else shape(cell)

    def copy_kind(self, kind):
        return (kind in {'bool', 'float'}
                or kind == 'int' and self.model.integer in {'i64', 'i128'})

    def generation(self):
        """A real source-execution certificate, independent of TLS layout.

        The first increment deliberately requires unique source module
        execution.  It does not derive that fact from a module number, status,
        ClassDef, successful value fact or the late metadata representation.
        """
        from .native_namespace_read_places import lifetime_closed
        if not lifetime_closed(self.model):
            raise Unproved('capture/drop/observer or finite source proof is absent')
        from .native_single_execution_metadata import _identities, _module_name
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        model = self.model
        linker = getattr(model, 'module_linker', None)
        if linker is None:
            raise Unproved('actual linked namespace generation transport is absent')
        for (index, node_id), _ in linker.imports.items():
            plan = self.plans.get(index); node = self.nodes.get(node_id)
            if plan is None:
                continue
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                raise Unproved('an import has no original source execution point')
            original = model.unit.original_unit(node)
            if (not isinstance(node, (ast.Import, ast.ImportFrom))
                    or not model.is_module_plan(plan)
                    or plan.node is not original.tree
                    or not any(item is node for item in original.tree.body)):
                raise Unproved('a loader can execute another namespace generation')
        compiler = {'__import__', 'eval', 'exec', 'compile'}
        loaders = {'importlib', 'importlib.util', 'importlib.machinery',
                   'importlib._bootstrap', 'importlib._bootstrap_external',
                   '_frozen_importlib', '_frozen_importlib_external', '_imp', 'imp'}
        identities = set(model.callable_cells.builtin_used) | set(model.callable_cells.member_used)
        for cell in model.records.values():
            from .native_classes import shape
            identities.update(_identities(shape(cell)))
        for identity in identities:
            if (isinstance(identity, BuiltinIdentity) and identity.name in compiler
                    or isinstance(identity, BuiltinRef) and (
                        identity.module in loaders
                        or identity.module == 'builtins' and identity.name in compiler)):
                raise Unproved('a canonical loader/runtime compiler can create another generation')
        cache = {'modules', 'meta_path', 'path', 'path_hooks', 'path_importer_cache'}
        for plan in self.plans.values():
            for node in self.own[plan.index]:
                if not isinstance(node, ast.Attribute):
                    continue
                module = _module_name(model, plan, node.value)
                if (module == 'builtins' and node.attr in compiler | {'__dict__'}
                        or module == 'sys' and node.attr in cache
                        or module in loaders
                        or module is not None and node.attr in {'__loader__', '__spec__'}):
                    raise Unproved('an observed loader/cache has no single-generation proof')

    def class_root(self, owner):
        model = self.model
        unit = model.unit.original_unit(owner.node)
        if (not any(n is owner.node for n in unit.tree.body)
                or owner.node.bases or owner.node.keywords
                or owner.node.decorator_list or owner.node.type_params):
            return False
        key = model.class_key(owner)
        writes = [r for r in self.rows if r.name == key
                  and model.module_owner(r.owner) and r.role != 'load']
        if (len(writes) != 1 or writes[0].role != 'definition'
                or writes[0].node != model.unit.ordinal(owner.node)
                or writes[0].scope != writes[0].owner):
            return False
        from .native_module_linking import ModuleType
        from .native_types import alternatives
        module = model.module_linker.modules.get(owner.module_name)
        if module is None:
            return False
        for plan in self.plans.values():
            for node in self.own[plan.index]:
                if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    if (ModuleType(module.number) in alternatives(self.kind(plan, node.value))
                            and node.attr == owner.node.name):
                        return False
        return True

    def slot(self, plan, node):
        from .native_types import ListType
        from .native_classes import InstanceType
        from .native_module_linking import ClassReferenceType, ModuleType
        from .native_list_positions import allocation_origins, registry
        kind = self.kind(plan, node)
        if not isinstance(kind, ListType) or not self.copy_kind(kind.element):
            return None
        cell = self.model.records.get((plan.index, id(node)))
        if cell is None:
            return None
        origins = allocation_origins(cell)
        if not origins or not origins <= registry(self.model).keys():
            return None
        owner = None
        if isinstance(node, ast.Name):
            if not self.model.namespace.owns(plan, node):
                return None
            key = self.model.resolved_name(plan, node)
        elif isinstance(node, ast.Attribute):
            receiver = self.kind(plan, node.value)
            if isinstance(receiver, (ClassReferenceType, InstanceType)):
                namespaces = self.model.class_namespaces
                point = plan.index, id(node)
                members = namespaces.attribute_reads.get(point, ())
                if (len(members) != 1 or members[0].plan is not None
                        or namespaces.instance_reads.get(point, False)):
                    return None
                member = members[0]; owner = member.owner
                if not self.class_root(owner):
                    return None
                if isinstance(receiver, InstanceType) and any(
                        name in owner.methods for name in ('__getattr__', '__getattribute__')):
                    return None
                key = member.key
            elif isinstance(receiver, ModuleType):
                module = self.model.module_linker.by_number.get(receiver.number)
                if module is None or module.native_adapter:
                    return None
                if self.model.unit.global_name(module.name, '__getattr__') in self.model.namespace.incoming:
                    return None
                key = self.model.unit.global_name(module.name, node.attr)
            else:
                return None
        else:
            return None
        if dict(self.model.namespace.fields()).get(key) != kind:
            return None
        result = self.slots.setdefault(key, StateSlot(key, kind.element, origins, owner))
        if result.kind != kind.element or result.origins != origins:
            return None
        return result

    def reader(self, plan, node):
        if not (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
                and isinstance(node.slice, ast.UnaryOp) and isinstance(node.slice.op, ast.USub)
                and isinstance(node.slice.operand, ast.Constant)
                and type(node.slice.operand.value) is int and node.slice.operand.value == 1):
            return None
        slot = self.slot(plan, node.value)
        return slot if slot is not None and self.kind(plan, node) == slot.kind else None

    def pure_scalar(self, plan, node):
        """A scalar value expression can fail, but cannot change its receiver.

        Source Call/operator protocols are not inferred from a scalar result.
        The first producer accepts closed scalar loads only, not callbacks.
        """
        from .native_classes import InstanceType
        if not self.copy_kind(self.kind(plan, node)):
            return False
        if isinstance(node, (ast.Constant, ast.Name)):
            return True
        if isinstance(node, ast.Attribute) and isinstance(self.kind(plan, node.value), InstanceType):
            owner = self.model.classes[self.kind(plan, node.value).name]
            return (node.attr in owner.fields
                    and not any(name in owner.methods for name in ('__getattr__', '__getattribute__'))
                    and not self.model.call_edges_by_site.get((plan.index, id(node))))
        return False

    def producer(self, plan):
        from .native_class_calls import synchronous
        from .native_classes import shape
        if (not synchronous(self.model, plan) or not isinstance(plan.node, ast.FunctionDef)
                or plan.node.type_params
                or self.model.lexical.parent_scope(plan) is not None):
            return None
        result_kind = shape(plan.result)
        appends = []
        returned = False
        for statement in plan.node.body:
            if returned:
                return None
            if isinstance(statement, ast.Pass):
                continue
            if isinstance(statement, ast.Return):
                if not appends:
                    return None
                value = statement.value
                if (value is None or isinstance(value, ast.Constant) and value.value is None):
                    if result_kind != 'none':
                        return None
                else:
                    if not isinstance(value, ast.Name) or not isinstance(value.ctx, ast.Load):
                        return None
                    from .native_primitive_parameter_places import readonly_parameter
                    scope = self.model.lexical.scope(source(plan))
                    binding = self.model.lexical.binding(value)
                    name = self.model.resolved_name(plan, value)
                    argument = plan.arguments.get(name)
                    captured = self.model.lexical.environments.get(scope)
                    if (binding is None or binding.role != 'load' or binding.owner != scope
                            or binding.name != name
                            or self.model.lexical.execution_scope(binding.scope) != scope
                            or name not in plan.runtime_parameters or argument is None
                            or shape(argument) != result_kind or self.kind(plan, value) != result_kind
                            or not readonly_parameter(self.model.unit, self.rows, scope, name)
                            or self.model.namespace.owns(plan, value)
                            or self.model.lexical.field_for(value) is not None
                            or captured is not None and name in captured.fields):
                        return None
                returned = True
                continue
            call = statement.value if isinstance(statement, ast.Expr) else None
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == 'append' and len(call.args) == 1 and not call.keywords
                    and self.pure_scalar(plan, call.args[0])):
                return None
            slot = self.slot(plan, call.func.value)
            if slot is None or self.kind(plan, call.args[0]) != slot.kind:
                return None
            appends.append(Producer(plan, call, slot))
        return appends[0] if len(appends) == 1 and (returned or result_kind == 'none') else None

    def aliases_value(self, cell, seen=frozenset()):
        from .native_list_positions import allocation_origins
        from .native_types import ListType, UnionType, NullableType
        from .native_classes import shape
        if cell is None:
            return set(self.slots)
        cell = cell.root()
        if id(cell) in seen:
            return set(self.slots)
        kind = shape(cell)
        if kind is None:
            return set(self.slots)
        if isinstance(kind, (UnionType, NullableType)):
            if cell.tag != 'union':
                return set(self.slots)
            result = set()
            for child in cell.args:
                result.update(self.aliases_value(child, seen | {id(cell)}))
            return result
        if not isinstance(kind, ListType):
            return set()
        origins = allocation_origins(cell)
        if not origins:
            return set(self.slots)
        return {key for key, slot in self.slots.items() if slot.origins & origins}

    def aliases(self, plan, node):
        return self.aliases_value(self.model.records.get((plan.index, id(node))))

    def hash_closed(self, plan, node):
        from .native_types import TupleType
        def closed(kind):
            if kind in {'int', 'bool', 'int_bool', 'float', 'str', 'bytes', 'none'}:
                return True
            return isinstance(kind, TupleType) and all(closed(child) for child in kind.fields)
        return closed(self.kind(plan, node))

    def constructor_role_closed(self, owner, children):
        """Separate source initializer effects from native allocation roles.

        Allocation/metadata/binding remain checked. This is only a NoWrite
        certificate under generation()'s no-GC/finalizer/observer seal, not a
        claim that construction, defaults or source activation cannot fail.
        """
        if (not isinstance(owner.node, ast.ClassDef) or owner.node.bases
                or owner.node.keywords or owner.node.decorator_list
                or owner.node.type_params or any(name in owner.methods for name in
                    ('__new__', '__getattr__', '__getattribute__', '__setattr__', '__delattr__'))):
            return False
        initializer = owner.methods.get('__init__')
        if initializer is None:
            return True
        member = self.model.class_namespaces.members.get((owner.index, '__init__'))
        if member is not None and member.descriptor != 'function':
            return False
        original = source(initializer)
        return original is not None and original.index in children

    def source_roles_closed(self, plan, node, targets):
        """Every executable MAY role, not merely one source edge, is sealed."""
        children = set()
        for index in targets:
            child = self.plans.get(index)
            original = None if child is None else source(child)
            if original is None:
                return False
            children.add(original.index)
        provider = self.model.callable_cells
        site = provider.sites.get((plan.index, id(node)))
        if site is not None:
            # A native member/builtin may mutate the heap even when a source
            # alternative contributes an ordinary semantic call edge. Until
            # that complete native operation has a StateEffect, keep it opaque.
            if site.builtins or site.members or site.exception_constructors or site.errors:
                return False
            for target in site.targets:
                definition = getattr(target, 'definition', target)
                original = provider.plans.get(definition)
                original = None if original is None else source(original)
                if original is None or original.index not in children:
                    return False
            for record in site.constructors.values():
                if record.error or not self.constructor_role_closed(record.owner, children):
                    return False
            return bool(site.targets or site.constructors)
        # No stored callable site: prove the actual direct producer role.
        # Edges from native callbacks/formatting alone are not source calls.
        linker = getattr(self.model, 'module_linker', None)
        owner = None if linker is None else linker.class_calls.get((plan.index, id(node)))
        if owner is not None:
            return self.constructor_role_closed(owner, children)
        from .native_frame_references import call_target
        direct = call_target(self.model, plan, node)
        if direct is not None:
            original = source(direct)
            return original is not None and children == {original.index}
        if isinstance(node.func, ast.Attribute):
            from .native_classes import InstanceType
            receiver = self.kind(plan, node.func.value)
            if isinstance(receiver, InstanceType):
                owner = self.model.classes.get(receiver.name)
                method = None if owner is None else owner.methods.get(self.model.resolved_name(plan, node.func))
                original = None if method is None else source(method)
                return original is not None and children == {original.index}
        return False

    def local_effect(self, plan, node):
        """MAY writes, including same-length writes and reordered elements."""
        from .native_types import ListType, alternatives
        from .native_module_linking import ClassReferenceType, ModuleType
        if isinstance(node, ast.FunctionDef):
            from .native_source_definition_effects import binding_effect
            return binding_effect(self, plan, node)
        if isinstance(node, ast.For):
            from .native_source_iteration_effects import for_effects
            return set(for_effects(self, plan, node, include_source=False))
        if isinstance(node, ast.AugAssign):
            # The binding store is separate from the in-place heap effect.
            # In particular, a local parameter Name can retain the caller's
            # list even though namespace.owns(target) is false. Read the
            # original operand cell, not the post-store binding carrier.
            from .native_classes import shape
            previous = self.model.augmented.get((plan.index, id(node)))
            kind = None if previous is None else shape(previous)
            if isinstance(kind, ListType):
                return self.aliases_value(previous)
            if kind in {'int', 'bool', 'int_bool', 'float', 'str', 'bytes', 'none', 'range'}:
                return set()
            # Finite mixed lists, other mutable carriers, unregistered
            # protocol payloads and missing old-read facts are not NoWrite.
            return set(self.slots)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
            # Native phase writes are available before the source-effect
            # fixed point. Registered source children are propagated by that
            # fixed point separately, including conditional/zero-trip phases.
            from .native_source_iteration_effects import comprehension_effects
            return comprehension_effects(self, plan, node, include_source=False)
        if isinstance(node, ast.GeneratorExp):
            # Lazy frame/cursor transport has its own ownership/lifetime ABI.
            return set(self.slots)
        if isinstance(node, ast.Dict):
            if any(key is None or not self.hash_closed(plan, key) for key in node.keys):
                return set(self.slots)
        if isinstance(node, ast.Set):
            if any(not self.hash_closed(plan, item) for item in node.elts):
                return set(self.slots)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            member = self.model.class_namespaces.local_member(plan, node)
            if member is not None:
                return {member.key} & self.slots.keys()
            if self.model.namespace.owns(plan, node):
                key = self.model.resolved_name(plan, node)
                return {key} & self.slots.keys()
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            # Stores/deletes do not have attribute_reads entries. Resolve the
            # actual typed namespace target instead of treating absence of a
            # load record as absence of a write.
            affected = set()
            name = self.model.resolved_name(plan, node)
            for receiver in alternatives(self.kind(plan, node.value)):
                if isinstance(receiver, ClassReferenceType):
                    owner = self.model.class_namespaces.owners.get(receiver.definition)
                    if owner is None:
                        return set(self.slots)
                    affected.add(self.model.class_namespaces.member(owner, name).key)
                elif isinstance(receiver, ModuleType):
                    module = self.model.module_linker.by_number.get(receiver.number)
                    if module is None:
                        return set(self.slots)
                    affected.add(self.model.unit.global_name(module.name, node.attr))
            if affected:
                return affected & self.slots.keys()
            # A scalar element type is not an alias proof for its parent.
            return self.aliases(plan, node.value)
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, (ast.Store, ast.Del)):
            return self.aliases(plan, node.value)
        if isinstance(node, ast.Call):
            from .native_source_native_effects import operation
            native_writes = operation(self, plan, node)
            if native_writes is not None:
                return set(native_writes)
            targets = self.model.call_edges_by_site.get((plan.index, id(node)))
            if targets:
                return set() if self.source_roles_closed(plan, node, targets) else set(self.slots)
            if isinstance(node.func, ast.Attribute) and isinstance(self.kind(plan, node.func.value), ListType):
                if node.func.attr in {'copy', 'count', 'index'}:
                    # Only actual Copy scalar elements have sealed equality.
                    from .native_list_positions import closed
                    if (self.copy_kind(self.kind(plan, node.func.value).element)
                            and all(closed(self.kind(plan, value)) for value in
                                    (*node.args, *(item.value for item in node.keywords)))):
                        return set()
                    return set(self.slots)
                return self.aliases(plan, node.func.value)
            from .native_physical_list_builtins import static_builtin
            if isinstance(node.func, ast.Name):
                if any(static_builtin(self.model, plan, node.func, name) for name in
                       ('print', 'input', 'range', 'len', 'int', 'bool', 'float', 'str', 'abs')):
                    from .native_list_positions import closed
                    if all(closed(self.kind(plan, value)) for value in
                           (*node.args, *(item.value for item in node.keywords))):
                        return set()
            return set(self.slots)
        return set()

    def prepare(self):
        from .native_source_execution_points import excluded_binding
        if self.model.unit is None:
            raise Unproved('official source identities are absent')
        self.generation()
        for plan in self.plans.values():
            for node in self.own[plan.index]:
                if isinstance(node, ast.Subscript):
                    self.reader(plan, node)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.slot(plan, node.func.value)
        self.effects = {}
        self.requirements = {}
        self.binding_coverage = []
        for plan in self.plans.values():
            writes = set(); reads = set()
            owned = {}
            raw_owned = {self.model.unit.node_ordinals[id(node)]: node
                         for node in self.raw_own[plan.index]
                         if id(node) in self.model.unit.node_ordinals}
            for node in self.own[plan.index]:
                ordinal = self.model.unit.node_ordinals.get(id(node))
                if ordinal is not None:
                    owned[ordinal] = node
                writes.update(self.local_effect(plan, node))
                reader = self.reader(plan, node)
                if reader is not None:
                    reads.add(reader.key)
                if isinstance(node, (ast.Call, ast.NamedExpr, ast.AugAssign, ast.Delete)):
                    self.coverage.append((plan.index, self.model.unit.ordinal(node), type(node).__name__))
            scope = self.model.unit.scope_for(source(plan).node).ordinal
            for row in self.rows:
                if row.role == 'load' or row.scope != scope and row.node not in raw_owned:
                    continue
                node = owned.get(row.node)
                if row.role == 'parameter':
                    classification = 'already-bound source parameter'
                elif excluded_binding(row.node, raw_owned, owned):
                    classification = 'excluded by original native execution certificate'
                elif node is None:
                    # A newly introduced binding form cannot leave an earlier
                    # state fact alive just because this visitor missed it.
                    writes.update(self.slots)
                    classification = 'unmodeled binding kills all state'
                else:
                    writes.update(self.local_effect(plan, node))
                    classification = 'original binding operation and enclosing control transfer'
                self.binding_coverage.append((plan.index, row.owner, row.scope,
                                              row.node, row.role, classification))
            self.effects[plan.index] = writes
            self.requirements[plan.index] = reads
        changed = True
        while changed:
            changed = False
            for index in self.plans:
                for child in self.model.call_edges.get(index, ()):
                    if child not in self.plans:
                        writes = set(self.slots); reads = set()
                    else:
                        writes = self.effects[child]; reads = self.requirements[child]
                    previous = len(self.effects[index]), len(self.requirements[index])
                    self.effects[index].update(writes); self.requirements[index].update(reads)
                    changed |= previous != (len(self.effects[index]), len(self.requirements[index]))
        from .native_class_calls import synchronous
        from .native_source_definition_effects import argument_parent_closed
        for plan in self.plans.values():
            required = self.requirements[plan.index]
            if (required and not required & self.effects[plan.index]
                    and synchronous(self.model, plan) and isinstance(plan.node, ast.FunctionDef)
                    and argument_parent_closed(self.model, plan)
                    and not plan.signature.variadic_positional and not plan.signature.variadic_keyword):
                ordered = tuple(self.slots[key] for key in sorted(required, key=str))
                self.abis[plan.index] = StateAbi(plan, ordered)
        # Every solved entry must exist before any body asks for its callee's
        # ABI. Source definition or specialization order is not a call order.
        for index, abi in self.abis.items():
            mode = StateMode()
            self.block(abi.plan, abi.plan.node.body, set(self.requirements[index]), mode)
            self.modes['function', index] = mode
        for (index, node_id), records in self.model.context_managers.sites.items():
            plan = self.plans.get(index); node = self.nodes.get(node_id)
            if plan is None or not isinstance(node, ast.With) or len(records) != 1:
                continue
            record = records[0]
            producer = self.producer(record.enter_member.plan)
            if producer is None:
                continue
            definition = self.model.callable_cells.definition(producer.plan)
            if (set(record.enter_site.targets) != {definition}
                    or record.enter_site.errors or record.enter_site.builtins
                    or record.enter_site.members or record.enter_site.constructors):
                continue
            mode = StateMode()
            available = {producer.slot.key}
            if record.original.optional_vars is not None:
                available -= self.target_effect(plan, record.original.optional_vars)
            self.block(plan, node.body, available, mode)
            if not mode.reads and not mode.calls:
                continue
            self.producers[producer.plan.index] = producer
            self.bridges[index, node_id] = producer
            self.modes['with', index, node_id] = mode

    def target_effect(self, plan, target):
        result = set()
        for node in ast.walk(target):
            result.update(self.local_effect(plan, node))
            for child in self.model.call_edges_by_site.get((plan.index, id(node)), ()):
                result.update(self.effects.get(child, self.slots))
        return result

    def after_truth(self, plan, node, available):
        from .native_list_positions import closed
        if not closed(self.kind(plan, node)):
            return set()
        return available

    def annotate_invocation(self, plan, node, available, mode):
        """Grant source entries only after every preceding native phase.

        A native callback edge is not an immediate source call. For example,
        list.sort empties its receiver before invoking its key function.
        """
        mode.calls.pop(id(node), None)
        targets = self.model.call_edges_by_site.get((plan.index, id(node)), ())
        if not targets or not all(index in self.abis for index in targets):
            return
        required = set().union(*(self.requirements[index] for index in targets))
        if not required <= available:
            return
        # Different sequential phases may require different slots. Eligibility
        # of one entry seals only its own requirements, so additionally protect
        # the complete set transported across this original operation.
        if any(required & self.effects.get(index, set(self.slots)) for index in targets):
            return
        if isinstance(node, ast.Call):
            if not self.source_roles_closed(plan, node, targets):
                from .native_source_native_effects import operation
                native_writes = operation(self, plan, node)
                if native_writes is None or required & native_writes:
                    return
        else:
            # These original numeric plans describe all reflected/source
            # phases and preserve their native lookup/binding/allocation work.
            # Every source phase preserves the whole transported set by the
            # union-effect check above, including reflected fallback phases.
            operators = self.model.operators
            if isinstance(node, ast.BinOp):
                sites = [site for point, site in operators.sites.items()
                         if point[:2] == (plan.index, id(node))]
            elif isinstance(node, ast.UnaryOp):
                sites = [operators.unary_sites.get((plan.index, id(node)))]
            elif isinstance(node, ast.Compare) and len(node.ops) == 1:
                sites = [operators.comparison_sites.get((plan.index, id(node), 0))]
            else:
                return
            if not sites or any(site is None or not site.branches for site in sites):
                return
            for site in sites:
                for branch in site.branches.values():
                    if (not branch.complete or any(phase.member.descriptor != 'function'
                                                  for phase in branch.phases)):
                        return
        mode.calls[id(node)] = frozenset(targets)

    def expression(self, plan, node, available, mode):
        if node is None:
            return available
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return self.comprehension(plan, node, available, mode)
        if isinstance(node, ast.Lambda):
            # Defaults execute now; the body executes through its own source
            # plan later. Walking the body eagerly would attach a witness to
            # the wrong activation and miss a mutating eager default.
            for value in (*node.args.defaults, *node.args.kw_defaults):
                if value is not None:
                    available = self.expression(plan, value, available, mode)
            return available
        if isinstance(node, ast.NamedExpr):
            available = self.expression(plan, node.value, available, mode)
            return available - self.target_effect(plan, node.target)
        if isinstance(node, ast.Dict):
            # Python evaluates/inserts each key-value pair before the next
            # key. ast.iter_child_nodes instead groups all keys before values.
            for key, value in zip(node.keys, node.values):
                if key is not None:
                    available = self.expression(plan, key, available, mode)
                available = self.expression(plan, value, available, mode)
                if key is None or not self.hash_closed(plan, key):
                    available.clear()
            return available
        if isinstance(node, ast.Set):
            for value in node.elts:
                available = self.expression(plan, value, available, mode)
                if not self.hash_closed(plan, value):
                    available.clear()
            return available
        # Children are processed before their enclosing operation. A callee's
        # body requirements are tested after receiver/callee/argument effects.
        if isinstance(node, ast.Call):
            available = self.expression(plan, node.func, available, mode)
            from .call_semantics import normalize_call, CallBindingError
            try:
                arguments = normalize_call(node)
            except CallBindingError:
                return set()
            for item in arguments.evaluation_order:
                available = self.expression(plan, item.expression, available, mode)
            targets = self.model.call_edges_by_site.get((plan.index, id(node)), ())
            self.annotate_invocation(plan, node, available, mode)
            available -= self.local_effect(plan, node)
            for index in targets:
                available -= self.effects.get(index, set(self.slots))
            return available
        if isinstance(node, ast.Compare):
            available = self.expression(plan, node.left, available, mode)
            for operator, comparator in zip(node.ops, node.comparators):
                available = self.expression(plan, comparator, available, mode)
                if len(node.ops) == 1:
                    self.annotate_invocation(plan, node, available, mode)
                # A chained comparison can invoke a source rich comparison
                # and its truth protocol before the next operand is evaluated.
                for index in self.model.call_edges_by_site.get((plan.index, id(node)), ()):
                    available -= self.effects.get(index, set(self.slots))
                # Identity tests return a primitive bool without an equality
                # or truth callback. Operand effects have already occurred.
                if (not isinstance(operator, (ast.Is, ast.IsNot))
                        and not all(self.copy_kind(self.kind(plan, value)) for value in (node.left, comparator))):
                    available.clear()
            return available
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                available = self.expression(plan, value, available, mode)
                available = self.after_truth(plan, value, available)
            return available
        if isinstance(node, ast.IfExp):
            available = self.expression(plan, node.test, available, mode)
            available = self.after_truth(plan, node.test, available)
            yes = self.expression(plan, node.body, set(available), mode)
            no = self.expression(plan, node.orelse, set(available), mode)
            return yes & no
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                available = self.expression(plan, child, available, mode)
        self.annotate_invocation(plan, node, available, mode)
        reader = self.reader(plan, node)
        if reader is not None and reader.key in available:
            mode.reads[id(node)] = reader
        available -= self.local_effect(plan, node)
        for index in self.model.call_edges_by_site.get((plan.index, id(node)), ()):
            available -= self.effects.get(index, set(self.slots))
        return available

    def comprehension(self, plan, node, available, mode):
        """Meet all repeated explicit/implicit effects before body facts."""
        if not node.generators:
            return set()
        available = self.expression(plan, node.generators[0].iter, available, mode)
        if isinstance(node, ast.GeneratorExp):
            # Lazy bodies may run after this witness's source scope has ended.
            return set()
        from .native_source_iteration_effects import comprehension_phase, comprehension_item, annotate_pulls
        effect = comprehension_phase(self, plan, node)
        repeated = [generator.target for generator in node.generators]
        repeated += [generator.iter for generator in node.generators[1:]]
        repeated += [test for generator in node.generators for test in generator.ifs]
        repeated += [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        # The eager outer iterable is intentionally excluded from this purge.
        # No earlier one-shot body annotation survives the repeated MAY meet.
        self.discard_annotations(mode, repeated)
        invariant = available - effect.writes - self.repeated_effects(plan, repeated)
        conditional = set(invariant)
        for index, generator in enumerate(node.generators):
            if index:
                conditional = self.expression(plan, generator.iter, conditional, mode)
            conditional = self.assignment_target(plan, generator.target, conditional, mode,
                value=comprehension_item(self, plan, node, index))
            for test in generator.ifs:
                conditional = self.expression(plan, test, conditional, mode)
                conditional = self.after_truth(plan, test, conditional)
        if isinstance(node, ast.DictComp):
            conditional = self.expression(plan, node.key, conditional, mode)
            conditional = self.expression(plan, node.value, conditional, mode)
        else:
            conditional = self.expression(plan, node.elt, conditional, mode)
        # Expression/target visitors clear their own original-node call facts.
        # Attach pull roles last, using the precomputed whole-backedge meet,
        # never the state observed after just one successful iteration.
        annotate_pulls(self, effect, invariant, mode)
        return invariant & conditional

    def repeated_effects(self, plan, roots):
        """MAY effects over every repeated condition/body and implicit edge.

        This pass records no read/call annotations. In particular a while
        condition must not first acquire a one-shot incoming witness and only
        later discover that its backedge can invalidate that witness.
        """
        killed = set()
        owned = {id(node) for node in self.own[plan.index]}
        for root in roots:
            for node in ast.walk(root):
                if id(node) not in owned:
                    continue
                killed.update(self.local_effect(plan, node))
                for child in self.model.call_edges_by_site.get((plan.index, id(node)), ()):
                    killed.update(self.effects.get(child, self.slots))
        return killed

    @staticmethod
    def discard_annotations(mode, roots):
        for root in roots:
            for node in ast.walk(root):
                mode.reads.pop(id(node), None)
                mode.calls.pop(id(node), None)

    def assignment_target(self, plan, target, available, mode, *, value=None):
        effect = None
        if isinstance(target, (ast.Tuple, ast.List)):
            # Pull/arity phases finish before any target receiver is visited.
            # A native output kind alone cannot close their source callbacks.
            from .native_source_iteration_effects import unpack_phase, annotate_pulls
            effect = unpack_phase(self, plan, target, value)
            available -= effect.writes
            self.discard_annotations(mode, [target])
            # Nested pulls can follow an earlier sibling target's receiver or
            # index effects. Transport only facts preserved by every target
            # phase; do not assume all nested unpacks precede all stores.
            pull_available = available - self.target_effect(plan, target)
        available = self.expression(plan, target, available, mode)
        if effect is not None:
            annotate_pulls(self, effect, pull_available, mode)
        return available - self.target_effect(plan, target)

    def block(self, plan, statements, incoming, mode):
        available = set(incoming)
        for node in statements:
            if id(node) in self.excluded_owned.get(plan.index, ()):
                self.discard_annotations(mode, [node])
                continue
            if isinstance(node, ast.If):
                available = self.expression(plan, node.test, available, mode)
                available = self.after_truth(plan, node.test, available)
                yes = self.block(plan, node.body, available, mode)
                no = self.block(plan, node.orelse, available, mode)
                available = no if yes is None else yes if no is None else yes & no
                if available is None:
                    return None
            elif isinstance(node, (ast.For, ast.While)):
                if isinstance(node, ast.For):
                    # The source iterable expression is one-shot, unlike a
                    # while test. Its reads can use the genuine incoming state.
                    available = self.expression(plan, node.iter, available, mode)
                    from .native_source_iteration_effects import for_phase, annotate_pulls
                    effect = for_phase(self, plan, node)
                    repeated = [node.target, *node.body]
                    self.discard_annotations(mode, repeated)
                    mode.calls.pop(id(node), None)
                    # For obtains/pulls its iterator without bool(iterable).
                    # Meet every repeated pull/target/body phase first, then
                    # analyze target receivers under that loop invariant.
                    available -= effect.writes | self.repeated_effects(plan, repeated)
                    available = self.expression(plan, node.target, available, mode)
                    annotate_pulls(self, effect, available, mode)
                else:
                    repeated = [node.test, *node.body]
                    self.discard_annotations(mode, repeated)
                    available -= self.repeated_effects(plan, repeated)
                    available = self.expression(plan, node.test, available, mode)
                    available = self.after_truth(plan, node.test, available)
                self.block(plan, node.body, available, mode)
                finished = self.block(plan, node.orelse, available, mode)
                if finished is not None:
                    available &= finished
            elif isinstance(node, ast.With):
                # Nested effects/cleanup have their own independently checked
                # bridge. No lexical-exit shortcut restores an outer token.
                available.clear()
            elif isinstance(node, ast.Assign):
                available = self.expression(plan, node.value, available, mode)
                for target in node.targets:
                    available = self.assignment_target(plan, target, available, mode)
            elif isinstance(node, ast.AugAssign):
                # Evaluate target operands before the RHS. The original
                # emitter retains its read/in-place/store protocol; include
                # every native/source MAY effect before later uses of state.
                available = self.expression(plan, node.target, available, mode)
                available = self.expression(plan, node.value, available, mode)
                available -= self.target_effect(plan, node)
            elif isinstance(node, ast.AnnAssign):
                available = self.expression(plan, node.value, available, mode)
                available = self.assignment_target(plan, node.target, available, mode)
            elif isinstance(node, ast.FunctionDef):
                from .native_source_definition_effects import transfer
                available = transfer(self, plan, node, available, mode)
            elif isinstance(node, ast.Assert):
                from .native_source_definition_effects import assertion_transfer
                available = assertion_transfer(self, plan, node, available, mode)
            elif isinstance(node, (ast.Expr, ast.Return, ast.Raise)):
                available = self.expression(plan, getattr(node, 'value', None)
                                            if not isinstance(node, ast.Raise) else node.exc,
                                            available, mode)
                if isinstance(node, (ast.Return, ast.Raise)):
                    # No normal successor is distinct from a successor whose
                    # incoming source witnesses have all been invalidated.
                    return None
            elif isinstance(node, (ast.Pass, ast.Global, ast.Nonlocal)):
                pass
            else:
                # Unmodeled control, targets, imports, defaults or hidden
                # producers do not inherit a pre-statement witness.
                available.clear()
        return available


def prepare(model):
    model.source_state = Registry(model)
    from .native_operand_demands import prepare as prepare_operand_demands
    prepare_operand_demands(model)


def registry(emitter):
    return getattr(emitter.model, 'source_state', None)


def total_read(emitter, node):
    active = getattr(emitter, 'source_state_active', None)
    if active is None:
        return None
    mode, values = active
    slot = mode.reads.get(id(node))
    if slot is None or slot.key not in values:
        return None
    from .native_classes import Expression
    from .native_source_total_places import receiver_elidable
    if receiver_elidable(emitter, node, slot):
        return Expression(values[slot.key], slot.kind)
    # Otherwise a successful append/top witness alone does not license omitting evaluation of
    # the source list receiver. In particular its owner may be an effectful
    # call, an unbound class/module alias, or a checked namespace lookup. Keep
    # the complete existing list expression and its capture/drop scope; only
    # the pure constant -1 index/read is replaced by the Copy witness.
    before, receiver = emitter.capture(emitter.expression(node.value))
    return Expression('{' + before + values[slot.key] + '}', slot.kind)


def private_name(plan):
    return 'class_state_function_' + str(plan.index)


def function_name(emitter, plan):
    if getattr(emitter, 'source_state_private', False) and plan is emitter.plan:
        return ('class_state_enter_' if getattr(emitter, 'source_state_producer', None) is not None
                else 'class_state_function_') + str(plan.index)
    return None


def extra_parameters(emitter):
    state = registry(emitter)
    if state is None or not getattr(emitter, 'source_state_private', False):
        return ''
    abi = state.abis.get(emitter.plan.index)
    if abi is None or getattr(emitter, 'source_state_producer', None) is not None:
        return ''
    return ''.join(',class_state_value_' + str(index) + ':' + emitter.rust_type(slot.kind)
                   for index, slot in enumerate(abi.slots))


def producer_result(emitter, result, tail):
    producer = getattr(emitter, 'source_state_producer', None)
    if producer is None:
        return result, tail, ''
    kind = emitter.rust_type(producer.slot.kind)
    from .native_classes import Expression, shape
    from .native_types import alternatives
    result_kind = shape(emitter.plan.result)
    if 'none' in alternatives(result_kind):
        value = emitter.coerce(Expression('()', 'none'), result_kind, emitter.plan.node)
        tail = 'Ok((' + value + ',class_state_effect_value))'
    return '(' + result + ',' + kind + ')', tail, 'let class_state_effect_value:' + kind + ';'


def explicit_return(emitter, node):
    if getattr(emitter, 'source_state_producer', None) is None:
        return None
    if isinstance(node, ast.Return):
        from .native_classes import Expression, shape
        value = Expression('()', 'none') if node.value is None else emitter.expression(node.value)
        return 'return Ok((' + emitter.coerce(value, shape(emitter.plan.result), node) + ',class_state_effect_value));'
    return None


def append_export(emitter, node, method, bound):
    producer = getattr(emitter, 'source_state_producer', None)
    if producer is None or producer.node is not node or method.name != 'append':
        return ''
    value = bound['value']
    assert value.kind == producer.slot.kind
    return 'class_state_effect_value=' + value.code + ';'


def call_arguments(emitter, node, target):
    state = registry(emitter)
    active = getattr(emitter, 'source_state_active', None)
    if state is None or active is None:
        return None
    mode, values = active
    if target.index not in mode.calls.get(id(node), ()):
        return None
    abi = state.abis[target.index]
    return tuple(values[slot.key] for slot in abi.slots)


def bound_call(emitter, node, bound):
    request = getattr(emitter, 'source_state_enter_request', None)
    if request is not None and source(bound.target) is source(request[0].plan):
        producer, output = request
        invocation = ('class_state_enter_' + str(producer.plan.index) + '(class_scope.clone()'
                      + bound.extra_context + (',' + ','.join(bound.values) if bound.values else '') + ')')
        return invocation, output
    extra = call_arguments(emitter, node, bound.target)
    from .native_operand_demands import call_projection
    projection = call_projection(emitter, node, bound.target)
    if getattr(bound, 'projection', None) is not projection:
        raise AssertionError('private operand projection lost its exact call permission')
    if extra is None:
        return bound.call_code(emitter), None
    return (private_name(bound.target) + '(class_scope.clone()' + bound.extra_context
            + (',' + ','.join(bound.values) if bound.values else '')
            + ''.join(',' + value for value in extra) + ')'), None


def bodies(model):
    state = getattr(model, 'source_state', None)
    if state is None or not state.bridges:
        return []
    output = []
    for index, abi in state.abis.items():
        emitter = model.emitter(abi.plan)
        emitter.source_state_private = True
        values = {slot.key: 'class_state_value_' + str(i) for i, slot in enumerate(abi.slots)}
        emitter.source_state_active = state.modes['function', index], values
        output.append(emitter.generate())
    for producer in state.producers.values():
        emitter = model.emitter(producer.plan)
        emitter.source_state_private = True
        emitter.source_state_producer = producer
        output.append(emitter.generate())
    return output


def constructor(model, emitter, owner, signature, allocation, receiver, arguments):
    state = getattr(model, 'source_state', None)
    plan = owner.methods.get('__init__')
    abi = None if state is None or not state.bridges or plan is None else state.abis.get(plan.index)
    if abi is None:
        return ''
    parameters = ''.join(',class_state_value_' + str(i) + ':' + emitter.rust_type(slot.kind)
                         for i, slot in enumerate(abi.slots))
    call = private_name(plan) + '(class_scope.clone(),' + receiver
    call += ''.join(',' + value for value in arguments)
    call += ''.join(',class_state_value_' + str(i) for i in range(len(abi.slots))) + ')?;'
    return ('fn class_state_construct_' + str(owner.index) + '(' + signature + parameters
            + ')->ClassResult<ClassHandle_' + str(owner.index) + '>{' + allocation + call + 'Ok(object)}')
