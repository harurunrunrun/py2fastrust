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


def is_bound_target(target):return isinstance(target,BoundMethodTarget)


def variant(target):return 'ClassFunctionRef::D'+str(target.definition)


class BoundMethods:
    def __init__(self,provider):
        self.provider=provider
        self.model=provider.model
        self.used=set()
        self.sites={}

    @property
    def linked(self):return hasattr(self.model,'module_linker')

    def value(self,plan,node,receiver,environment):
        from .native_classes import Cell,ClassUnsupported,shape
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
        fields='receiver:'+receiver.code
        if self.linked:
            context=emitter.fresh()
            setup+='let '+context+'='+receiver.code+'.borrow().class_definition.module.clone();'
            fields+=',module:'+context
        code=variant(target)+'(std::rc::Rc::new(ClassBoundMethod'+str(target.definition)+'{'+fields+'}))'
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
        values=[emitter.coerce(value,shape(method.arguments[name]),node)for name,value in zip(binding.parameters,binding.values)]
        invocation=emitter.function_name(method)+'(class_scope.clone()'+(','+','.join(values)if values else'')+')'
        from .native_class_calls import call
        result=emitter.coerce(Expression(call(emitter,invocation,method,source_call_location or node),shape(method.result)),wanted,node)
        if self.linked:result='{'+self.model.module_linker.call_context(emitter,'class_selected_method.module.clone()')+result+'}'
        return result

    def reference_pattern(self,target):return variant(target)+'(..)'

    def call_pattern(self,target):return variant(target)+'(class_selected_method)'

    def runtime_parts(self):
        declarations=[];variants=[];equals=[];identical=[]
        for target in sorted(self.used,key=lambda value:value.definition):
            from .native_class_descriptors import ClassMethodTarget,runtime_bound
            if isinstance(target,ClassMethodTarget):
                declaration,variant,equal,identity=runtime_bound(target)
                declarations.append(declaration);variants.append(variant);equals.append(equal);identical.append(identity)
                continue
            owner=self.model.classes[target.owner]
            tag='D'+str(target.definition)
            fields='receiver:ClassHandle_'+str(owner.index)
            if self.linked:fields+=',module:ClassModuleRef'
            declarations.append('struct ClassBoundMethod'+str(target.definition)+'{'+fields+'}')
            variants.append(tag+'(std::rc::Rc<ClassBoundMethod'+str(target.definition)+'>)')
            equals.append('(Self::'+tag+'(left),Self::'+tag+'(right))=>std::rc::Rc::ptr_eq(&left.receiver,&right.receiver)')
            identical.append('(Self::'+tag+'(left),Self::'+tag+'(right))=>std::rc::Rc::ptr_eq(left,right)')
        identity=('impl ClassFunctionRef{fn class_same_identity(&self,other:&Self)->bool{match(self,other){'+','.join(identical)+',_=>self==other}}}')if identical else''
        return '\n'.join(declarations),variants,equals,identity
