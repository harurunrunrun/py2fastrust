"""Fresh bound-method references over original compiled source methods.

The payload owns its receiver reference. Copies keep the same method object;
separate descriptor reads allocate separate method objects even when Python
method equality compares their function and receiver identities equal.
"""
import ast
from dataclasses import dataclass

from .call_semantics import CallBindingError


@dataclass(frozen=True)
class BoundMethodTarget:
    definition:int
    owner:str

    @property
    def _native_kind_tag(self):return 'bound_method_'+str(self.definition)


@dataclass
class FiniteMethodRead:
    targets:dict


def is_bound_target(target):return isinstance(target,BoundMethodTarget)




class BoundMethods:
    def __init__(self,provider):
        self.provider=provider
        self.model=provider.model
        self.used=set()
        self.sites={}

    @property
    def linked(self):return hasattr(self.model,'module_linker')

    def finite_candidate(self,plan,node,receiver):
        from .native_classes import InstanceType,shape
        from .native_types import alternatives
        from .native_unions import union_kind
        kind=shape(receiver)
        if not union_kind(kind):return False
        name=self.model.resolved_name(plan,node)
        return any(isinstance(part,InstanceType)and name in self.model.classes[part.name].methods
                   for part in alternatives(kind))

    def finite_value(self,plan,node,receiver):
        from .native_classes import InstanceType,ClassUnsupported,shape,domain
        from .native_types import alternatives,ListType,SharedListType,TupleType,TupleSequenceType
        from .native_finite_attributes import BUILTIN_TYPES
        if not self.finite_candidate(plan,node,receiver):return None
        name=self.model.resolved_name(plan,node);targets={}
        for kind in alternatives(shape(receiver)):
            if isinstance(kind,InstanceType):
                owner=self.model.classes[kind.name];method=owner.methods.get(name)
                registry=getattr(self.model,'class_namespaces',None)
                member=registry.members.get((owner.index,name))if registry is not None else None
                if method is not None:
                    if member is not None and member.descriptor!='function':
                        raise ClassUnsupported(node,'method acquisition across finite receivers includes a nonfunction descriptor; per-alternative descriptor binding is not implemented',types=(('receiver',kind),),proof='finite method descriptor binding')
                    target=BoundMethodTarget(self.provider.definition(method),kind.name)
                    self.used.add(target);targets[kind]=target
                elif name in owner.fields or member is not None:
                    raise ClassUnsupported(node,'method acquisition across finite receivers includes an instance or class data attribute; preserving its stored value together with bound-method alternatives needs a mixed attribute-value adapter',types=(('receiver',kind),),proof='finite data and method attribute lookup')
                else:targets[kind]=None
            else:
                if not(isinstance(kind,str)or type(kind)in{ListType,SharedListType,TupleType,TupleSequenceType}):
                    raise ClassUnsupported(node,'method acquisition across this receiver alternative needs a registered descriptor or missing-attribute lookup adapter',types=(('receiver',kind),),proof='closed finite receiver attribute lookup')
                builtin=BUILTIN_TYPES.get(domain(kind))
                if builtin is None:
                    raise ClassUnsupported(node,'method acquisition across this builtin receiver needs its attribute lookup adapter',types=(('receiver',kind),),proof='closed builtin receiver attribute lookup')
                if hasattr(builtin,node.attr):
                    raise ClassUnsupported(node,'method acquisition across finite receivers includes builtin attribute '+repr(node.attr)+'; that builtin descriptor adapter is not registered for this method family',types=(('receiver',kind),),proof='finite builtin method descriptor binding')
                targets[kind]=None
        self.sites[(plan.index,id(node))]=FiniteMethodRead(targets)
        return self.model.remember(plan,node,self.model.cell(plan,node,'function',tuple(target for target in targets.values()if target is not None)))

    def value(self,plan,node,receiver,environment):
        from .native_classes import Cell,ClassUnsupported,shape
        finite=self.finite_value(plan,node,receiver)
        if finite is not None:return finite
        receiver=receiver.root()
        if receiver.tag!='object':
            from .native_types import alternatives
            if any(getattr(kind,'methods',())for kind in alternatives(shape(receiver))):
                raise ClassUnsupported(node,"reading this bound-method attribute needs method-object metadata lookup and forwarding to its underlying function; the typed callable retains its receiver and supports calls, but this attribute lookup adapter is not implemented",operation="bound method attribute "+repr(node.attr),types=(("receiver",shape(receiver)),),proof="bound method metadata and function-attribute lookup")
            return None
        owner=self.model.classes[receiver.args[0]]
        method=owner.methods.get(self.model.resolved_name(plan,node))
        if method is None:return None
        target=BoundMethodTarget(self.provider.definition(method),receiver.args[0])
        self.used.add(target)
        self.sites[(plan.index,id(node))]=target
        return self.model.remember(plan,node,self.model.cell(plan,node,'function',(target,)))

    def read(self,emitter,node):
        from .native_aot_callables import AotFunctionType
        from .native_classes import Expression
        target=self.sites.get((emitter.plan.index,id(node)))
        if target is None:return None
        setup,receiver=emitter.capture(emitter.expression(node.value))
        if isinstance(target,FiniteMethodRead):
            from .native_unions import project
            from .native_class_builtins import _type_name,_error
            from .native import _string
            wanted=emitter.kind(node)
            attribute=self.model.display_name(self.model.resolved_name(emitter.plan,node))
            def branch(kind,code):
                selected=target.targets[kind]
                current=Expression('('+code+').clone()',kind)
                if selected is None:
                    message='format!('+_string("AttributeError: '{}' object has no attribute "+repr(attribute))+','+_type_name(emitter,current,node)+')'
                    return _error(emitter,node,wanted,message).code
                bound=self.expression(emitter,selected,current)
                return emitter.coerce(bound,wanted,node)
            return Expression('{'+setup+project(receiver.kind,receiver.code,branch)+'}',wanted)
        return self.expression(emitter,target,receiver,setup=setup)

    def expression(self,emitter,target,receiver,*,setup=''):
        from .native_aot_callables import AotFunctionType
        from .native_classes import Expression
        fields='receiver:'+receiver.code
        if self.linked:
            context=emitter.fresh()
            setup+='let '+context+'='+receiver.code+'.borrow().class_definition.module.clone();'
            fields+=',module:'+context
        from .native_callable_carriers import construct
        code=construct(self.provider,target,'std::rc::Rc::new(ClassBoundMethod'+str(target.definition)+'{'+fields+'})')
        return Expression('{'+setup+code+'}',AotFunctionType.from_targets((target,)))

    @staticmethod
    def receiver_kind(target):
        from .native_classes import InstanceType
        return getattr(target,"_native_receiver_kind",InstanceType(target.owner))

    def analyze(self,plan,node,target,arguments,positional,keywords,environment,site):
        from .native_aot_callables import binding_error
        from .native_classes import Cell
        method=self.provider.plans[target.definition]
        self.used.add(target)
        try:binding=method.signature.plan(arguments,implicit_count=1,allow_variadic=True)
        except CallBindingError as error:
            site.errors[target]=binding_error(method,arguments,error,implicit_count=1)
            return
        site.targets[target]=binding
        result=self.model.bind_captured(plan,node,method,[self.model.cell_for_kind(self.receiver_kind(target))]+positional,keywords,environment)
        if not self.model.namespace.contribute(site.result,result,node,force=True):self.model.contribute(site.result,result,node)

    def emit(self,emitter,node,target,site,positional,keywords,wanted,error,*,source_call_location=None):
        from .native_classes import Expression,ClassUnsupported,InstanceType,shape
        from .native_class_descriptors import ClassMethodTarget,emit_bound
        if isinstance(target,ClassMethodTarget):return emit_bound(self.provider,emitter,node,target,site,positional,keywords,wanted,error,source_call_location=source_call_location)
        if target in site.errors:return error(site.errors[target])
        method=self.provider.plans[target.definition]
        receiver=Expression('class_selected_method.receiver.clone()',InstanceType(target.owner))
        default_emitter=self.model.emitter(method)
        try:
            from .native_variadic import pack_emission
            binding=method.signature.bind([receiver]+positional,keywords,default_emitter.captured_defaults(method),pack_positional=lambda members:pack_emission(emitter,method,members,node))
        except CallBindingError as failure:raise ClassUnsupported(node,str(failure))from None
        from .native_frame_specialization import native_target
        method=native_target(self.model,method,binding.by_name)
        values=[emitter.coerce(value,shape(method.arguments[name]),node)for name,value in zip(binding.parameters,binding.values)]
        invocation=emitter.function_name(method)+'(class_scope.clone()'+(','+','.join(values)if values else'')+')'
        from .native_class_calls import call
        result=emitter.coerce(Expression(call(emitter,invocation,method,source_call_location or node),shape(method.result)),wanted,node)
        if self.linked:result='{'+self.model.module_linker.call_context(emitter,'class_selected_method.module.clone()')+result+'}'
        return result

    def reference_pattern(self,target,kind=None):
        from .native_aot_callables import AotFunctionType
        from .native_callable_carriers import pattern
        return pattern(self.provider,target,kind or AotFunctionType.from_targets((target,)))

    def call_pattern(self,target,kind=None):
        from .native_aot_callables import AotFunctionType
        from .native_callable_carriers import pattern
        return pattern(self.provider,target,kind or AotFunctionType.from_targets((target,)),call=True)
