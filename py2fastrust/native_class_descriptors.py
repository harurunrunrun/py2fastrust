"""Canonical definition-time descriptors over retained source callables."""
from dataclasses import dataclass

from .native_bound_methods import BoundMethodTarget

DEFERRED_RECEIVER=object()


@dataclass(frozen=True)
class ClassMethodTarget(BoundMethodTarget):
    class_definition:int

    @property
    def _native_receiver_kind(self):
        from .native_module_linking import ClassReferenceType
        return ClassReferenceType(self.class_definition)

    @property
    def _native_owned_kinds(self):
        from .native_aot_callables import AotFunctionType
        return self._native_receiver_kind,AotFunctionType((self.definition,))


def receiver_kind(registry,owner,node):
    from .native_classes import InstanceType,ClassUnsupported
    if not node.decorator_list:return InstanceType(registry.model.class_key(owner))
    if len(node.decorator_list)!=1:
        raise ClassUnsupported(node,"stacked class method decorators need composed descriptor construction; only one canonical classmethod or staticmethod decorator is currently supported",proof="ordered class descriptor composition")
    if node.name=="__init__":
        raise ClassUnsupported(node,"decorated __init__ needs the constructor descriptor protocol; ordinary classmethod and staticmethod attribute binding are supported, but constructor receiver replacement is not implemented",proof="decorated constructor receiver and return protocol")
    # Resolve the original decorator at its definition event, before defaults.
    # Defer receiver seeding until then: staticmethod takes no implicit argument.
    registry.member(owner,registry.unit.name_for(node)).descriptor="pending"
    return DEFERRED_RECEIVER


def prepare_definition(registry,caller,node,member,environment):
    if not node.decorator_list:return
    from .native_classes import ClassUnsupported,shape
    from .native_aot_callables import function_kind
    from .references import BuiltinIdentity
    value=registry.model.expression(caller,node.decorator_list[0],environment)
    kind=shape(value)
    if kind is None and not registry.model.final:return
    choices={BuiltinIdentity('classmethod'):'classmethod',BuiltinIdentity('staticmethod'):'staticmethod'}
    descriptor=choices.get(kind.targets[0])if function_kind(kind)and len(kind.targets)==1 else None
    if descriptor is None:
        raise ClassUnsupported(node.decorator_list[0],"this method decorator is not proved to be the canonical classmethod or staticmethod object; arbitrary decorator calls and replacement descriptors are not implemented",types=(("decorator",kind),),proof="captured canonical class descriptor identity")
    member.descriptor=descriptor
    if descriptor=='classmethod'and member.plan.parameters:
        from .native_classes import Cell
        from .native_module_linking import ClassReferenceType
        registry.model.contribute(member.plan.arguments[member.plan.parameters[0]],Cell(ClassReferenceType(member.owner.index)),node)


def analyze_definition(registry,caller,node,member,environment):
    if node.decorator_list and member.descriptor not in {'classmethod','staticmethod','pending'}:
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,"this class method decorator needs its definition-time descriptor construction adapter",proof="registered class descriptor construction")


def emit_prepare_definition(registry,emitter,node,member):
    if member.descriptor not in {'classmethod','staticmethod'}:return ""
    # Evaluating a canonical decorator can still involve a user call. Its
    # effects and exceptions precede every default expression's evaluation.
    return "let _="+emitter.expression(node.decorator_list[0]).code+";"


def analyze_member(registry,plan,node,member,receiver,environment):
    if member.descriptor=='pending':
        if not registry.model.final:
            from .native_guard_flow import AnalysisPending
            raise AnalysisPending()
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'method descriptor identity remains unresolved at its original class definition',proof='resolved definition-time class descriptor')
    if member.descriptor=='staticmethod':return member.function_cell
    if member.descriptor!="classmethod":return None
    from .native_classes import Cell
    target=ClassMethodTarget(registry.model.callable_cells.definition(member.plan),registry.model.class_key(member.owner),member.owner.index)
    registry.model.callable_cells.bound_methods.used.add(target)
    return Cell('function',(target,))


def emit_member(registry,emitter,node,member,class_reference,function):
    if member.descriptor=='staticmethod':return function
    if member.descriptor!="classmethod":return None
    from .native_classes import Expression
    from .native_aot_callables import AotFunctionType
    target=ClassMethodTarget(registry.model.callable_cells.definition(member.plan),registry.model.class_key(member.owner),member.owner.index)
    fields='receiver:('+class_reference.code+').clone(),function:('+function.code+').clone()'
    from .native_immediate_classmethod import stack_payload
    code=stack_payload(emitter,node,target,fields)
    if code is None:
        from .native_callable_carriers import construct
        code=construct(registry.model.callable_cells,target,'std::rc::Rc::new(ClassBoundMethod'+str(target.definition)+'{'+fields+'})')
    return Expression(code,AotFunctionType.from_targets((target,)))


def emit_bound(provider,emitter,node,target,site,positional,keywords,wanted,error,*,source_call_location=None):
    from .native_classes import Expression
    from .native_aot_callables import AotFunctionType,CallSite,emit_values
    if target in site.errors:return error(site.errors[target])
    callee=Expression('class_selected_method.function.clone()',AotFunctionType((target.definition,)))
    receiver=Expression('class_selected_method.receiver.clone()',target._native_receiver_kind)
    nested=CallSite(provider.model.cell_for_kind(callee.kind),site.result)
    return emit_values(emitter,node,nested,callee,[receiver]+positional,keywords,wanted,source_call_location=source_call_location).code


def wrap_expanded(provider,emitter,target,code):
    method=provider.plans[target.definition]
    context=provider.call_context_setup(emitter,method)
    from .native_callable_carriers import bind_payload
    return '{'+bind_payload(provider,target.definition,'class_selected_method.function.clone()')+context+code+'}'
