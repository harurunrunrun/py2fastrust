"""Original source item slots use typed calls and captured assignment primaries."""
import ast
from dataclasses import dataclass

from .call_semantics import Argument,CallArguments


@dataclass
class ItemSite:
    member:object
    callback:object
    owner:object
    key:object


def source_owner(model,value):
    from .native_classes import InstanceType,shape
    kind=shape(value)
    return model.classes[kind.name]if isinstance(kind,InstanceType)else None


def sites(model):
    if not hasattr(model,'source_item_sites'):
        model.source_item_sites={}
        from .native_callback_effects import register
        register(model,lambda plan,node:any(key[:2]==(plan.index,id(node))for key in model.source_item_sites))
    return model.source_item_sites


def check_key(node):
    from .native_classes import ClassUnsupported
    def slice_value(expression):
        return isinstance(expression,ast.Slice)or isinstance(expression,ast.Tuple)and any(slice_value(child)for child in expression.elts)
    if slice_value(node.slice):
        raise ClassUnsupported(node.slice,'source item access with a slice key needs a Python slice-object carrier; native source __getitem__/__setitem__ currently pass ordinary values and tuple keys',proof='source item slice object identity')


def analyze(model,plan,node,owner,key,environment,value=None):
    from .native_classes import ClassUnsupported
    from .native_aot_callables import analyze_values
    declaration=source_owner(model,owner)
    if declaration is None:return None
    check_key(node)
    slot='__getitem__'if value is None else'__setitem__'
    if slot not in declaration.methods:
        raise ClassUnsupported(node,'source item access requires '+slot+'; this class has no registered ordinary source '+slot+' protocol',proof='source item method availability')
    from .native_source_display import guard_direct_method
    guard_direct_method(model,declaration,slot,node)
    namespace=model.class_namespaces;member=namespace.member(declaration,slot)
    if member.descriptor!='function':
        raise ClassUnsupported(node,'source '+slot+' uses a nonfunction descriptor; implicit item access through that descriptor is not implemented',proof='source item descriptor binding')
    namespace.observe_method(member,node)
    captured_owner,captured_key=model.flow_copy(owner),model.flow_copy(key)
    arguments=[owner,key]+([]if value is None else[value])
    callback=analyze_values(model.callable_cells,plan,node,namespace.field(member,node),
        CallArguments(tuple(Argument(node)for _ in arguments),()),arguments,[],environment,
        identity=('source_item',slot,declaration.index))
    # Flow snapshots retain the target selected before an augmented RHS can
    # rebind its original primary names. They are not additional evaluations.
    sites(model)[plan.index,id(node),slot]=ItemSite(member,callback,captured_owner,captured_key)
    if value is not None:model.remember(plan,node,value)
    return model.remember(plan,node,callback.result)if value is None else callback.result


def captured_store(model,plan,node,value,environment):
    if not isinstance(node,ast.Subscript):return False
    site=sites(model).get((plan.index,id(node),'__getitem__'))
    if site is None:return False
    analyze(model,plan,node,site.owner,site.key,environment,value)
    return True


def emit(emitter,node,owner,key,wanted=None,value=None):
    from .native_classes import Expression,InstanceType,shape,ClassUnsupported
    from .native_module_linking import ClassReferenceType
    from .native_class_binding_contexts import CapturedClassContext
    from .native_aot_callables import emit_values
    if not isinstance(owner.kind,InstanceType):return None
    slot='__getitem__'if value is None else'__setitem__'
    site=sites(emitter.model).get((emitter.plan.index,id(node),slot))
    if site is None:
        raise ClassUnsupported(node,'source '+slot+' has no matching analyzed item callback site',proof='source item evaluation/effect site')
    reference=emitter.fresh()
    setup='let '+reference+'={'+owner.code+'.borrow().class_definition.clone()};'
    context=Expression(reference,ClassReferenceType(site.member.owner.index))
    function=emitter.model.class_namespaces.emit_get(emitter,node,context,site.member)
    before,function=emitter.capture(function);setup+=before
    arguments=[Expression('('+item.code+').clone()',item.kind)for item in (owner,key)]+([]if value is None else[value])
    result=emit_values(emitter,node,site.callback,function,arguments,[],shape(site.callback.result),
        captured_class_context=CapturedClassContext(site.member,context))
    if value is not None:
        # Python ignores __setitem__'s result, including a non-None result.
        return Expression('{'+setup+result.code+';}', 'none')
    return Expression('{'+setup+emitter.coerce(result,wanted,node)+'}',wanted)
