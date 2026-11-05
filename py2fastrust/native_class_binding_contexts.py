"""Carry actual defining-class contexts through certified native entries.

Binding identity is separate from a semantic class number: a failed import can
execute the same ClassDef again. Only entries whose defining function and
receiver generations are proved equal may derive this context from a receiver.
"""
import ast
from dataclasses import dataclass


class Unproved(Exception):
    pass


@dataclass(frozen=True)
class Binding:
    owner: object
    name: str
    scope: int
    definition: int


class Registry:
    def __init__(self, model):
        self.model = model
        self.bindings = {}
        self.methods = {}
        self.functions = {}
        self.function_entries = set()
        self.reasons = {}
        self.entries = {}
        self.loads = {}
        self.barrier = None
        if model.unit is None or getattr(model, 'module_linker', None) is None:
            self.barrier = 'this native unit has no retained linked class contexts'
            return
        self.unit = model.unit
        self.values = model.value_classes
        self.rows = tuple(model.iter_bindings())
        self.parents = self.values.parents
        self.plans = {plan.index: plan for plan in model.plans if plan.reachable}
        self.nodes = {id(node): node for node in model.iter_nodes()}
        try:
            from .native_finite_depth_calls import _model_proof, Unproved as GraphUnproved
            _model_proof(model)
        except GraphUnproved as error:
            self.barrier = str(error)
            return
        from .native_single_execution_metadata import _identities
        from .native_classes import shape
        from .native_module_calls import BuiltinRef
        identities = set(model.callable_cells.builtin_used) | set(model.callable_cells.member_used)
        for cell in model.records.values():
            identities.update(_identities(shape(cell)))
        if any(isinstance(identity, BuiltinRef) and (
                identity.module in {'gc', 'weakref'}
                or identity.module == 'sys' and identity.name in {'getrefcount', '_getframe', '_current_frames'})
                for identity in identities):
            self.barrier = 'a heap/frame/reference observer requires original capture ownership'
            return
        if model.namespace.globals_observed or any(
                getattr(shape(cell), '_native_namespace_view', False)
                for cell in model.records.values()):
            self.barrier = 'a live namespace mapping has no immutable class-store certificate'
            return
        if any(isinstance(node, ast.Attribute) and node.attr in {
                '__dict__', '__globals__', 'f_globals', 'f_locals', 'tb_frame'}
                for node in self.nodes.values()):
            self.barrier = 'an exposed namespace/frame can change class publication state'
            return
        from .native_module_linking import ModuleType
        from .native_types import alternatives
        if any(self.model.display_name(row.name) == '__builtins__'
               and self.model.module_owner(row.owner) for row in self.rows):
            self.barrier = 'an exposed builtin namespace has no immutable fallback certificate'
            return
        for plan in self.plans.values():
            for node in self.values.own_nodes(plan):
                if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, (ast.Store, ast.Del)):
                    continue
                for kind in alternatives(self.kind(plan, node.value)):
                    module = self.model.module_linker.by_number.get(kind.number) if isinstance(kind, ModuleType) else None
                    if module is not None and module.name == 'builtins' and module.native_adapter:
                        self.barrier = 'a mutated builtin namespace can supply another generation through fallback'
                        return
        from .native_value_classes import selected
        for owner in model.classes.values():
            if not owner.used or not selected(model, owner):
                continue
            try:
                binding = self.binding(owner)
            except Unproved as error:
                self.reasons[owner.index] = str(error)
                continue
            self.bindings[owner.index] = binding
        implicit = self.implicit_entries()
        for owner in model.classes.values():
            if owner.index not in self.bindings:
                continue
            for name, method in owner.methods.items():
                if name == '__init__':
                    continue
                try:
                    entries = self.method(owner, name, method, implicit)
                except Unproved as error:
                    self.reasons[owner.index, name] = str(error)
                    continue
                self.methods[self.source(method).index] = owner.index
                self.entries[self.source(method).index] = entries
        self.forward_functions()
        from .native_module_linking import ClassReferenceType
        for plan in self.plans.values():
            owner = self.method_owner(plan)
            if owner is None:
                continue
            binding = self.bindings[owner.index]
            for node in self.values.own_nodes(plan):
                if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
                    continue
                row = model.namespace.owners.get(self.unit.ordinal(node))
                if (row is not None and row.owner == binding.scope
                        and model.resolved_name(plan, node) == binding.name
                        and self.kind(plan, node) == ClassReferenceType(owner.index)):
                    self.loads[plan.index, id(node)] = owner.index

    def source(self, plan):
        from .native_call_context_effects import source_plan
        return source_plan(plan)

    def kind(self, plan, node):
        return self.values.kind(plan, node)

    def binding(self, owner):
        from .native_module_linking import ClassReferenceType, ModuleType
        original = self.unit.original_unit(owner.node)
        if owner.node not in original.tree.body:
            raise Unproved('class binding is not one direct original module definition')
        if owner.node.bases or owner.node.keywords or owner.node.decorator_list or owner.node.type_params:
            raise Unproved('class publication is not plain')
        name = self.model.class_key(owner)
        writes = [row for row in self.rows if row.name == name
                  and self.model.module_owner(row.owner) and row.role != 'load']
        ordinal = self.unit.ordinal(owner.node)
        if (len(writes) != 1 or writes[0].role != 'definition'
                or writes[0].node != ordinal or writes[0].scope != writes[0].owner):
            raise Unproved('the class global has another official binding producer')
        binding = writes[0]
        module = self.model.module_linker.modules.get(owner.module_name)
        if module is None:
            raise Unproved('the original class module has no exact linked identity')
        for plan in self.plans.values():
            for node in self.values.own_nodes(plan):
                if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, (ast.Store, ast.Del)):
                    continue
                from .native_types import alternatives
                for receiver in alternatives(self.kind(plan, node.value)):
                    attributes = {node.attr, self.model.display_name(self.model.resolved_name(plan, node))}
                    if (isinstance(receiver, ModuleType) and receiver.number == module.number
                            and owner.node.name in attributes):
                        raise Unproved('a module alias changes the class binding')
                    if isinstance(receiver, ClassReferenceType) and receiver.definition == owner.index:
                        raise Unproved('the published class namespace changes')
        return Binding(owner, name, binding.owner, ordinal)

    def implicit_entries(self):
        result = {}
        for attribute in ('sites', 'unary_sites', 'comparison_sites'):
            for key, site in getattr(self.model.operators, attribute).items():
                for branch in site.branches.values():
                    for phase in branch.phases:
                        method = phase.member.plan
                        if method is not None and phase.member.descriptor == 'function':
                            result.setdefault((key[0], key[1], self.source(method).index), set()).add('operator receiver definition')
        return result

    def method(self, owner, name, method, implicit):
        from .native_aot_callables import AotFunctionType
        from .native_classes import InstanceType, shape
        from .native_immutable_class_functions import definition
        from .native_class_calls import synchronous
        from .native_module_linking import ClassReferenceType
        model = self.model
        member = model.class_namespaces.members.get((owner.index, name))
        if member is None or definition(model, member, shape(member.function_cell)) != model.callable_cells.definition(method):
            raise Unproved('the method has no immutable original function binding')
        if not synchronous(model, method) or not method.runtime_parameters:
            raise Unproved('the receiver entry is not synchronous')
        if shape(method.arguments[method.runtime_parameters[0]]) != InstanceType(model.class_key(owner)):
            raise Unproved('the first argument is not the exact ordinary instance receiver')
        # A class member read as a function can be invoked with an unrelated
        # generation of self. A retained bound method has a separate adapter;
        # both must keep that adapter until it supplies an explicit class ctx.
        for plan in self.plans.values():
            for node in self.values.own_nodes(plan):
                if isinstance(node, ast.Name):
                    row = model.namespace.owners.get(self.unit.ordinal(node))
                    if (row is not None and row.role == 'load'
                            and row.owner == self.unit.scope_for(owner.node).ordinal
                            and row.name == name):
                        raise Unproved('a method function is exposed during class publication')
                if not isinstance(node, ast.Attribute) or model.resolved_name(plan, node) != name:
                    continue
                from .native_types import alternatives
                choices = alternatives(self.kind(plan, node.value))
                if any(isinstance(kind, ClassReferenceType) and kind.definition == owner.index for kind in choices):
                    raise Unproved('an unbound class member needs an explicit defining-class adapter')
                if InstanceType(model.class_key(owner)) not in choices:
                    continue
                call = self.parents.get(id(node))
                if (not isinstance(call, ast.Call) or call.func is not node
                        or any(isinstance(arg, ast.Starred) for arg in call.args)
                        or any(keyword.arg is None for keyword in call.keywords)
                        or (plan.index, id(call)) in model.callable_cells.sites):
                    raise Unproved('a retained/expanded method needs its captured-context adapter')
        source = self.source(method)
        entries = []
        for (caller, node_id), targets in model.call_edges_by_site.items():
            reached = [self.plans[index] for index in targets if index in self.plans
                       and self.source(self.plans[index]) is source]
            if not reached:
                continue
            if (caller, node_id, source.index) in implicit:
                entries.append((caller, node_id, 'operator receiver definition'))
                continue
            plan = self.plans.get(caller)
            node = self.nodes.get(node_id)
            if (plan is not None and isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and self.kind(plan, node.func.value) == InstanceType(model.class_key(owner))
                    and model.resolved_name(plan, node.func) == name
                    and (caller, node_id) not in model.callable_cells.sites
                    and all(index in self.plans and self.source(self.plans[index]) is source for index in targets)):
                entries.append((caller, node_id, 'direct bound receiver definition'))
                continue
            raise Unproved('an incoming call lacks an exact defining-generation origin')
        if not entries:
            raise Unproved('the method has no reached certified entry')
        binding = self.bindings[owner.index]
        has_read = any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                       and model.resolved_name(method, node) == binding.name
                       for node in self.values.own_nodes(method))
        if not has_read:
            raise Unproved('the method does not read its own canonical class binding')
        return entries

    def method_owner(self, plan):
        number = self.methods.get(self.source(plan).index, self.functions.get(self.source(plan).index))
        return next((owner for owner in self.model.classes.values() if owner.index == number), None)

    def forward_functions(self):
        """A retained original function lookup establishes its real generation.

        The lookup is never hoisted or erased. Only a direct same-module,
        immutable definition called exclusively from certified contexts can
        forward that context after the ordinary argument/default binder.
        """
        from .native_classes import shape
        from .native_aot_callables import AotFunctionType
        from .native_module_linking import ClassReferenceType, ModuleType
        from .native_function_instances import instanced
        candidates = {self.source(plan).index: self.source(plan)
                      for plan in self.model.functions.definitions.values() if plan.reachable}
        for source in candidates.values():
            if (source.index in self.methods or not isinstance(source.node, ast.FunctionDef)
                    or source.node.decorator_list or source.node.type_params
                    or source.signature.variadic_positional or source.signature.variadic_keyword
                    or self.model.lexical.parent_scope(source) is not None
                    or instanced(self.model.lexical, source)
                    or source.node not in self.unit.original_unit(source.node).tree.body):
                continue
            definitions = [row for row in self.rows if row.node == self.unit.ordinal(source.node)
                           and row.role == 'definition' and self.model.module_owner(row.owner)]
            if len(definitions) != 1:
                continue
            definition = definitions[0]
            if (self.model.display_name(definition.name) in self.model.namespace.builtin_names
                    or definition.name in self.model.callable_cells.fallback_names):
                continue
            writes = [row for row in self.rows if row.owner == definition.owner
                      and row.name == definition.name and row.role != 'load']
            if writes != definitions:
                continue
            number = self.model.callable_cells.definition(source)
            invalid = False
            for plan in self.plans.values():
                for node in self.values.own_nodes(plan):
                    if not isinstance(node, ast.Attribute):
                        continue
                    kind = self.kind(plan, node.value)
                    if isinstance(kind, AotFunctionType) and number in kind.definitions:
                        invalid = True
                    if isinstance(node.ctx, (ast.Store, ast.Del)):
                        from .native_types import alternatives
                        for choice in alternatives(kind):
                            if isinstance(choice, ModuleType):
                                module = self.model.module_linker.by_number[choice.number]
                                attributes = {node.attr, self.model.display_name(self.model.resolved_name(plan, node))}
                                if any(self.unit.global_name(module.name, attribute) == definition.name for attribute in attributes):
                                    invalid = True
            if invalid:
                continue
            incoming = []
            for (caller, node_id), targets in self.model.call_edges_by_site.items():
                if not any(index in self.plans and self.source(self.plans[index]) is source for index in targets):
                    continue
                plan = self.plans.get(caller)
                node = self.nodes.get(node_id)
                context = None if plan is None else self.method_owner(plan)
                row = (self.model.namespace.owners.get(self.unit.ordinal(node.func))
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) else None)
                if (context is None or definition.owner != self.bindings[context.index].scope
                        or row is None or row.owner != definition.owner
                        or self.model.resolved_name(plan, node.func) != definition.name
                        or any(isinstance(arg, ast.Starred) for arg in node.args)
                        or any(keyword.arg is None for keyword in node.keywords)):
                    invalid = True
                    break
                incoming.append((self.source(plan).index, node_id, source.index, context.index))
            if invalid or not incoming or len({item[3] for item in incoming}) != 1:
                continue
            owner = next(owner for owner in self.model.classes.values() if owner.index == incoming[0][3])
            binding = self.bindings[owner.index]
            if not any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                       and self.model.resolved_name(source, node) == binding.name
                       and self.kind(source, node) == ClassReferenceType(owner.index)
                       for node in self.values.own_nodes(source)):
                continue
            self.functions[source.index] = owner.index
            self.function_entries.update(item[:3] for item in incoming)


def prepare(model):
    model.class_binding_contexts = Registry(model)


def owner(model, plan):
    if plan is None:
        return None
    registry = getattr(model, 'class_binding_contexts', None)
    return None if registry is None else registry.method_owner(plan)


def parameter(model, plan):
    return ',class_defining_class:&ClassClassRef' if owner(model, plan) is not None else ''


def invocation(model, plan, receiver, *, caller=None, node=None):
    context_owner = owner(model, plan)
    if context_owner is None:
        return ''
    registry = model.class_binding_contexts
    if registry.source(plan).index in registry.functions:
        if not same_function_entry(model, caller, node, plan):
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node or plan.node, 'a native class context has no certified forwarding entry', proof='actual defining-class context provenance')
        return ',class_defining_class'
    from .native_classes import shape
    from .native_value_classes import borrowed_self
    name = plan.runtime_parameters[0]
    if borrowed_self(model, plan, name, shape(plan.arguments[name])):
        return ',&('+receiver+').borrow().class_definition'
    # The ordinary receiver ABI can move the instance (for example when self
    # is unused). Snapshot only its metadata with the actual metadata Clone
    # trait; a borrowed pointer into that moved value would be invalid.
    # The successful once-only carrier copies its pinned reference; a retry
    # carrier retains its own actual Rc generation until this call returns.
    return ',&<ClassValueMetadata_'+str(context_owner.index)+' as Clone>::clone(&('+receiver+').borrow().class_definition)'


def same_function_entry(model, caller, node, target):
    registry = getattr(model, 'class_binding_contexts', None)
    return (registry is not None and caller is not None and node is not None
            and (registry.source(caller).index, id(node), registry.source(target).index)
            in registry.function_entries)


def borrowed_constructor(model, constructor):
    return constructor.index in getattr(getattr(model, 'class_binding_contexts', None), 'bindings', ())


def own_read(emitter, node):
    return (emitter.plan.index, id(node)) in getattr(getattr(emitter.model, 'class_binding_contexts', None), 'loads', ())


def read(emitter, node, wanted):
    if not own_read(emitter, node):
        return None
    from .native_classes import Expression
    return Expression('Rc::clone(class_defining_class)', wanted)


def direct_constructor(emitter, node, constructor):
    return borrowed_constructor(emitter.model, constructor) and own_read(emitter, node.func)


def captured_constructor(emitter, node, site):
    """A private callee place, never an owned Expression with a borrowed ABI."""
    from .native_classes import shape
    from .native_module_linking import ClassReferenceType
    if (not own_read(emitter, node.func) or len(site.constructors) != 1
            or any((site.targets, site.errors, site.builtins, site.members, site.exception_constructors))):
        return None
    number, record = next(iter(site.constructors.items()))
    if (shape(site.callee) != ClassReferenceType(number)
            or not borrowed_constructor(emitter.model, record.owner)):
        return None
    return record


def comparison(emitter, node, wanted):
    """Immediate builtin type identity consumes a borrowed defining class."""
    if (len(node.ops) != 1 or not isinstance(node.ops[0], (ast.Is, ast.IsNot))
            or not own_read(emitter, node.comparators[0])):
        return None
    call = node.left
    if (not isinstance(call, ast.Call) or len(call.args) != 1 or call.keywords
            or isinstance(call.args[0], ast.Starred)):
        return None
    from .native_physical_list_builtins import static_builtin
    if not static_builtin(emitter.model, emitter.plan, call.func, 'type'):
        return None
    from .native_classes import Expression, InstanceType
    kind = emitter.kind(call.args[0])
    if not isinstance(kind, InstanceType) and kind not in {'int', 'bool', 'int_bool', 'float', 'str', 'bytes', 'none'}:
        return None
    setup, argument = emitter.capture(emitter.expression(call.args[0]))
    test = ('Rc::ptr_eq(&('+argument.code+').borrow().class_definition,class_defining_class)'
            if isinstance(kind, InstanceType) else 'false')
    if isinstance(node.ops[0], ast.IsNot):
        test = '!('+test+')'
    return Expression('{'+setup+test+'}', wanted)


def instance_test(emitter, node):
    """Default plain-class isinstance uses the actual generation by borrow."""
    if (len(node.args) != 2 or node.keywords
            or any(isinstance(arg, ast.Starred) for arg in node.args)
            or not own_read(emitter, node.args[1])):
        return None
    from .native_physical_list_builtins import static_builtin
    if not static_builtin(emitter.model, emitter.plan, node.func, 'isinstance'):
        return None
    from .native_classes import Expression, InstanceType
    kind = emitter.kind(node.args[0])
    if isinstance(kind, InstanceType):
        actual = emitter.model.classes.get(kind.name)
        if actual is None or actual.node.bases:
            return None
    elif kind not in {'int', 'bool', 'int_bool', 'float', 'str', 'bytes', 'none'}:
        return None
    setup, argument = emitter.capture(emitter.expression(node.args[0]))
    test = ('Rc::ptr_eq(&('+argument.code+').borrow().class_definition,class_defining_class)'
            if isinstance(kind, InstanceType) else 'false')
    return Expression('{'+setup+test+'}', emitter.kind(node))

