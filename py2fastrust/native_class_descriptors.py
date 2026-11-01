"""Canonical definition-time descriptors over retained source callables."""
from dataclasses import dataclass

from .native_bound_methods import BoundMethodTarget


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
        raise ClassUnsupported(node,"stacked class method decorators need composed descriptor construction; only a proved canonical classmethod decorator is currently supported",proof="ordered class descriptor composition")
    if node.name=="__init__":
        raise ClassUnsupported(node,"classmethod used as __init__ needs the constructor descriptor protocol; ordinary classmethod attribute binding is supported, but constructor receiver replacement is not implemented",proof="classmethod constructor receiver and return protocol")
    # The original decorator is solved at its definition event, before defaults.
    # This provisional receiver cannot reach emission unless that identity proof
    # succeeds; it does not infer a descriptor from the decorator's spelling.
    registry.member(owner,registry.unit.name_for(node)).descriptor="classmethod"
    from .native_module_linking import ClassReferenceType
    return ClassReferenceType(owner.index)


def prepare_definition(registry,caller,node,member,environment):
    if member.descriptor!="classmethod":return
    from .native_classes import ClassUnsupported,shape
    from .native_aot_callables import function_kind
    from .references import BuiltinIdentity
    value=registry.model.expression(caller,node.decorator_list[0],environment)
    kind=shape(value)
    if kind is None and not registry.model.final:return
    if not function_kind(kind)or kind.targets!=(BuiltinIdentity('classmethod'),):
        raise ClassUnsupported(node.decorator_list[0],"this method decorator is not proved to be the canonical classmethod object; arbitrary decorator calls and replacement descriptors are not implemented",types=(("decorator",kind),),proof="captured canonical classmethod identity")


def analyze_definition(registry,caller,node,member,environment):
    if node.decorator_list and member.descriptor!="classmethod":
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,"this class method decorator needs its definition-time descriptor construction adapter",proof="registered class descriptor construction")


def emit_prepare_definition(registry,emitter,node,member):
    if member.descriptor!="classmethod":return ""
    # Evaluating a canonical decorator can still involve a user call. Its
    # effects and exceptions precede every default expression's evaluation.
    return "let _="+emitter.expression(node.decorator_list[0]).code+";"


def analyze_member(registry,plan,node,member,receiver,environment):
    if member.descriptor!="classmethod":return None
    from .native_classes import Cell
    target=ClassMethodTarget(registry.model.callable_cells.definition(member.plan),registry.model.class_key(member.owner),member.owner.index)
    registry.model.callable_cells.bound_methods.used.add(target)
    return Cell('function',(target,))


def emit_member(registry,emitter,node,member,class_reference,function):
    if member.descriptor!="classmethod":return None
    from .native_classes import Expression
    from .native_aot_callables import AotFunctionType
    target=ClassMethodTarget(registry.model.callable_cells.definition(member.plan),registry.model.class_key(member.owner),member.owner.index)
    code='ClassFunctionRef::D'+str(target.definition)+'(std::rc::Rc::new(ClassBoundMethod'+str(target.definition)+'{receiver:('+class_reference.code+').clone(),function:('+function.code+').clone()}))'
    return Expression(code,AotFunctionType.from_targets((target,)))


def emit_bound(provider,emitter,node,target,site,positional,keywords,wanted,error):
    from .native_classes import Expression
    from .native_aot_callables import AotFunctionType,CallSite,emit_values
    if target in site.errors:return error(site.errors[target])
    callee=Expression('class_selected_method.function.clone()',AotFunctionType((target.definition,)))
    receiver=Expression('class_selected_method.receiver.clone()',target._native_receiver_kind)
    nested=CallSite(provider.model.cell_for_kind(callee.kind),site.result)
    return emit_values(emitter,node,nested,callee,[receiver]+positional,keywords,wanted).code


def runtime_bound(target):
    tag='D'+str(target.definition)
    declaration='struct ClassBoundMethod'+str(target.definition)+'{receiver:ClassClassRef,function:ClassFunctionRef}'
    variant=tag+'(std::rc::Rc<ClassBoundMethod'+str(target.definition)+'>)'
    equal='(Self::'+tag+'(left),Self::'+tag+'(right))=>std::rc::Rc::ptr_eq(&left.receiver,&right.receiver)&&left.function==right.function'
    identical='(Self::'+tag+'(left),Self::'+tag+'(right))=>std::rc::Rc::ptr_eq(left,right)'
    return declaration,variant,equal,identical


def wrap_expanded(provider,emitter,target,code):
    method=provider.plans[target.definition]
    context=provider.call_context_setup(emitter,method)
    return 'match class_selected_method.function.clone(){'+provider.call_pattern(target.definition)+'=>{'+context+code+'},_=>unreachable!("retained classmethod function identity")} '
