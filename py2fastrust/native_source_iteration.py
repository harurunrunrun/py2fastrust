"""Canonical source __iter__ calls return their original typed cursor handles."""
from dataclasses import dataclass

from .call_semantics import Argument,CallArguments


@dataclass
class IterationSite:
    member:object
    callback:object


def has_protocol(model,kind):
    from .native_classes import InstanceType
    return isinstance(kind,InstanceType)and '__iter__'in model.classes[kind.name].methods


def sites(registry):
    if not hasattr(registry,'source_protocol_sites'):
        registry.source_protocol_sites={}
        from .native_callback_effects import register
        register(registry.model,lambda plan,node:any(key[:2]==(plan.index,id(node))for key in registry.source_protocol_sites))
    return registry.source_protocol_sites


def analyze(registry,plan,node,value,environment):
    from .native_classes import ClassUnsupported,shape
    from .native_guard_flow import AnalysisPending
    from .native_class_iterators import iterator_kind
    from .native_aot_callables import analyze_values
    model=registry.model;kind=shape(value)
    if not has_protocol(model,kind):return None
    key=plan.index,id(node),kind
    if environment is None:
        site=sites(registry).get(key)
        if site is None:
            raise ClassUnsupported(node,'source __iter__ construction needs its original argument-evaluation environment; this implicit iterable consumer has not implemented that protocol call boundary',proof='source __iter__ construction effects')
    else:
        owner=model.classes[kind.name];namespace=getattr(model,'class_namespaces',None)
        if namespace is None:
            raise ClassUnsupported(node,'source __iter__ needs its canonical retained class namespace and method identity',proof='source iteration method identity')
        member=namespace.member(owner,'__iter__')
        if member.descriptor!='function':
            raise ClassUnsupported(node,'source __iter__ uses a nonfunction descriptor; implicit iteration through staticmethod/classmethod or custom descriptors is not implemented',proof='source __iter__ descriptor binding')
        namespace.observe_method(member,node)
        callback=analyze_values(model.callable_cells,plan,node,member.function_cell,
            CallArguments((Argument(node),),()),[value],[],environment,
            identity=('source_iter_protocol',kind))
        site=IterationSite(member,callback);sites(registry)[key]=site
    returned=shape(site.callback.result)
    if returned is None:
        if not model.final:raise AnalysisPending()
        raise ClassUnsupported(node,'source __iter__ return storage is unresolved after source-method analysis',proof='resolved source __iter__ cursor')
    if not iterator_kind(returned):
        raise ClassUnsupported(node,'source __iter__ must return a registered native iterator; this return value needs noniterator TypeError handling or an unimplemented user __next__ protocol',types=(('__iter__ return',returned),),proof='registered source __iter__ result protocol')
    return returned


def construct(registry,emitter,node,source):
    from .native_classes import Expression,shape,ClassUnsupported
    from .native_module_linking import ClassReferenceType
    from .native_class_binding_contexts import CapturedClassContext
    from .native_aot_callables import emit_values
    if not has_protocol(registry.model,source.kind):return None
    site=sites(registry).get((emitter.plan.index,id(node),source.kind))
    if site is None:
        raise ClassUnsupported(node,'source __iter__ construction has no matching original analyzed iteration site',proof='source iteration effect/lookup site')
    setup,owner=emitter.capture(source);reference=emitter.fresh()
    setup+='let '+reference+'={'+owner.code+'.borrow().class_definition.clone()};'
    context=Expression(reference,ClassReferenceType(site.member.owner.index))
    function=registry.model.class_namespaces.emit_get(emitter,node,context,site.member)
    before,function=emitter.capture(function);setup+=before
    result=emit_values(emitter,node,site.callback,function,[owner],[],shape(site.callback.result),
        captured_class_context=CapturedClassContext(site.member,context))
    return Expression('{'+setup+result.code+'}',result.kind)
