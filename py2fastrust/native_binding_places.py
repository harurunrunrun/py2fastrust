"""Source binding access demands, independent of their stored payload ABI."""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class BindingPlace:
    name: str
    slot: int
    definition: int
    definition_event: tuple
    owner_scope: int


@dataclass(frozen=True)
class InvocationAccessPlan:
    place: BindingPlace
    mode: str = 'check_presence'

    @property
    def key(self):
        return self.mode, self.place.slot, self.place.definition

    @property
    def function(self):
        return f'class_binding_present_{self.place.slot}_{self.place.definition}'


@dataclass(frozen=True)
class CapturedBinding:
    """Private unit transport; this is never a general function Expression."""
    code: str
    plan: InvocationAccessPlan


def access_plan(emitter, node, request):
    if request is None or not isinstance(node, ast.Call) or request.node is not node.func:
        return None
    model = emitter.model
    from .native_call_context_effects import source_plan
    from .native_class_binding_contexts import same_function_entry, owner
    from .native_function_instances import instanced
    target = source_plan(model.callable_cells.plans[request.layout.definition])
    if (not isinstance(target.node, ast.FunctionDef) or target.node.decorator_list
            or target.node.type_params or model.lexical.parent_scope(target) is not None
            or instanced(model.lexical, target) or request.layout.environment_type is not None
            or target.signature.variadic_positional or target.signature.variadic_keyword
            or set(target.defaults) - set(target.default_literals)):
        return None
    if not same_function_entry(model, emitter.plan, node, target):
        return None
    # The existing entry certificate carries the actual defining generation,
    # not a class/source ordinal.  Its retained class anchor spans arguments
    # and invocation even when the source body needs the caller's module view.
    if owner(model, target) is None:
        return None
    demand = getattr(model, 'callable_field_demand', None)
    if demand is None or demand.barrier is not None:
        return None
    unit = model.unit
    rows = [row for row in model.iter_bindings()
            if row.name == request.name and model.module_owner(row.owner)
            and row.role != 'load']
    if (len(rows) != 1 or rows[0].role != 'definition'
            or rows[0].node != unit.ordinal(target.node)
            or rows[0].scope != rows[0].owner):
        return None
    event = getattr(target, 'definition_key', None)
    if event is None:
        return None
    place = BindingPlace(request.name, request.slot, request.layout.definition,
                         event, rows[0].owner)
    return InvocationAccessPlan(place)


def capture(emitter, node, request):
    plan = access_plan(emitter, node, request)
    if plan is None:
        return None
    accessors = getattr(emitter.model, 'binding_place_accessors', None)
    if accessors is None:
        accessors = {}
        emitter.model.binding_place_accessors = accessors
    accessors[plan.key] = plan
    temporary = emitter.fresh()
    code = emitter.at(plan.function + '(&class_scope)', request.node)
    request.used = True
    return f'let {temporary}={code};', CapturedBinding(temporary, plan)


def runtime(model):
    from .native import _string
    result = []
    for key, plan in sorted(getattr(model, 'binding_place_accessors', {}).items()):
        assert key == plan.key and model.namespace.index(plan.place.name) == plan.place.slot
        message = _string("NameError: name '" + model.display_name(plan.place.name) + "' is not defined")
        result.append(f'fn {plan.function}(scope:&ClassScope)->Result<(),String>{{'
                      f'let class_binding_globals=scope.globals.borrow();'
                      f'class_binding_globals.value_{plan.place.slot}.as_ref().ok_or_else(||{message}.to_owned())?;'
                      'Ok(())}')
    return '\n'.join(result)
