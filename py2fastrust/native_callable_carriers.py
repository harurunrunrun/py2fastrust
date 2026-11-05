"""Physical callable payloads for exact original finite target families.

Singletons are payload structs, not a common callable enum. A real semantic
join carries only its proved alternatives. Payload ownership and source
definition identity are independent of native function-body specialization.
"""
import ast
import hashlib
from dataclasses import dataclass


def tag(target):
    from .native_bound_methods import BoundMethodTarget
    from .native_module_calls import BuiltinRef
    from .references import BuiltinIdentity
    if isinstance(target,BoundMethodTarget):return 'D'+str(target.definition)
    if isinstance(target,BuiltinRef):return 'M_'+target.module+'_'+target.name
    if isinstance(target,BuiltinIdentity):return 'B_'+target.name
    return 'F'+str(target)


def payload_type(target):return 'ClassCallablePayload_'+tag(target)


def family_type(kind):
    if len(kind.targets)==1:return payload_type(kind.targets[0])
    digest=hashlib.sha256(kind._native_kind_tag.encode()).hexdigest()[:20]
    return 'ClassCallableFamily_'+digest


@dataclass(frozen=True)
class Layout:
    target:object
    fields:tuple
    same_value:str
    same_identity:str


class Registry:
    def __init__(self,model):
        self.model=model
        self.kinds={}
        self.targets={}
        self.finalized=False

    def register(self,kind):
        name=family_type(kind)
        if self.finalized and name not in self.kinds:
            raise RuntimeError('a callable carrier was first demanded after its complete runtime declaration pass')
        previous=self.kinds.setdefault(name,kind)
        if previous!=kind:raise RuntimeError('callable carrier identity collision')
        for target in kind.targets:
            previous=self.targets.setdefault(tag(target),target)
            if previous!=target:raise RuntimeError('distinct callable targets require distinct physical payload identities')
        return name

    def complete(self):
        """Collect nested schemas and implicit builtin/default demands first."""
        from .native_aot_callables import AotFunctionType,ordered_targets
        from .native_classes import shape
        from .native_types import TupleType,ListType,TupleSequenceType,UnionType,NullableType,MaybeType
        model=self.model;provider=model.callable_cells
        seen=set()
        def visit(kind):
            if kind is None or kind in seen:return
            seen.add(kind)
            if isinstance(kind,AotFunctionType):self.register(kind)
            if isinstance(kind,TupleType):
                for child in kind.fields:visit(child)
            elif isinstance(kind,(ListType,TupleSequenceType)):visit(kind.element)
            elif isinstance(kind,UnionType):
                for child in kind.alternatives:visit(child)
            elif isinstance(kind,(NullableType,MaybeType)):visit(kind.value)
            for child in getattr(kind,'_native_owned_kinds',()):visit(child)
        for target in ordered_targets(tuple(provider.used)+tuple(provider.builtin_used)+tuple(provider.member_used)+tuple(provider.bound_methods.used)):
            visit(AotFunctionType.from_targets((target,)))
        for cell in model.records.values():visit(shape(cell))
        for _,kind in (*model.namespace.fields(),*model.namespace.default_fields()):visit(kind)
        for owner in model.classes.values():
            for field in owner.fields.values():visit(shape(field.cell))
        for plan in model.plans:
            if not plan.reachable:continue
            visit(shape(plan.result))
            for cell in plan.arguments.values():visit(shape(cell))
        while True:
            before=len(self.kinds),len(self.targets)
            for kind in tuple(self.kinds.values()):visit(kind)
            for target in tuple(self.targets.values()):
                for child in getattr(target,'_native_owned_kinds',()):visit(child)
                self.layout(target)
            if before==(len(self.kinds),len(self.targets)):break
        self.finalized=True

    def layout(self,target):
        from .native_bound_methods import BoundMethodTarget
        from .native_class_descriptors import ClassMethodTarget
        from .native_value_classes import identity_equal
        from .native_classes import InstanceType
        from .native_module_calls import BuiltinRef
        from .references import BuiltinIdentity
        model=self.model;provider=model.callable_cells
        if isinstance(target,BoundMethodTarget):
            field_type='Rc<ClassBoundMethod'+str(target.definition)+'>'
            if isinstance(target,ClassMethodTarget):
                equal='Rc::ptr_eq(&left.bound.receiver,&right.bound.receiver)&&left.bound.function==right.bound.function'
            else:
                equal=identity_equal(model,InstanceType(target.owner),'left.bound.receiver','right.bound.receiver')
                if getattr(provider.bound_methods,'linked',False):equal+='&&Rc::ptr_eq(&left.bound.module,&right.bound.module)'
            return Layout(target,(('bound',field_type),),equal,'Rc::ptr_eq(&left.bound,&right.bound)')
        if isinstance(target,(BuiltinIdentity,BuiltinRef)):
            return Layout(target,(),'true','true')
        plan=provider.plans[target];parent=model.lexical.parent_scope(plan)
        fields=[];equal=[]
        if isinstance(plan.node,ast.Lambda):
            fields.append(('environment','Rc<'+model.lambda_cells.payload_type(plan)+'>'))
            equal.append('Rc::ptr_eq(&left.environment,&right.environment)')
        elif parent:
            from .native_function_instances import instanced,reference_type
            if instanced(model.lexical,plan):
                fields.append(('environment',reference_type(model.lexical,plan)))
                equal.extend(('Rc::ptr_eq(&left.environment.data,&right.environment.data)',
                              'Rc::ptr_eq(&left.environment.environment,&right.environment.environment)'))
            else:
                fields.append(('environment','Rc<'+model.lexical.environment_type(parent)+'>'))
                equal.append('Rc::ptr_eq(&left.environment,&right.environment)')
        if getattr(model,'module_linker',None)is not None:
            fields.append(('module','ClassModuleRef'))
            equal.append('Rc::ptr_eq(&left.module,&right.module)')
        code='&&'.join(equal)or'true'
        return Layout(target,tuple(fields),code,code)

    def runtime(self):
        provider=self.model.callable_cells
        self.complete()
        declarations=[]
        from .native_bound_methods import BoundMethodTarget
        from .native_class_descriptors import ClassMethodTarget
        for target in tuple(self.targets.values()):
            if not isinstance(target,BoundMethodTarget):continue
            if isinstance(target,ClassMethodTarget):
                from .native_aot_callables import AotFunctionType
                function_type=family_type(AotFunctionType((target.definition,)))
                fields='receiver:ClassClassRef,function:'+function_type
            else:
                owner=self.model.classes[target.owner]
                fields='receiver:ClassHandle_'+str(owner.index)
                if getattr(provider.bound_methods,'linked',False):fields+=',module:ClassModuleRef'
            declarations.append('struct ClassBoundMethod'+str(target.definition)+'{'+fields+'}')
        for target in tuple(self.targets.values()):
            layout=self.layout(target);name=payload_type(target)
            declarations.append('#[derive('+('Clone'if layout.fields else'Clone,Copy')+')]\nstruct '+name+'{'+','.join(field+':'+kind for field,kind in layout.fields)+'}')
            declarations.append('impl PartialEq for '+name+'{fn eq(&self,other:&Self)->bool{let left=self;let right=other;'+layout.same_value+'}}')
            declarations.append('impl '+name+'{fn class_same_identity(&self,other:&Self)->bool{let left=self;let right=other;'+layout.same_identity+'}}')
        for name,kind in self.kinds.items():
            if len(kind.targets)==1:continue
            declarations.append('#[derive(Clone)]\nenum '+name+'{'+','.join(tag(target)+'('+payload_type(target)+')'for target in kind.targets)+'}')
            values=[];identities=[]
            for target in kind.targets:
                pattern='(Self::'+tag(target)+'(left),Self::'+tag(target)+'(right))=>'
                values.append(pattern+'left==right')
                identities.append(pattern+'left.class_same_identity(right)')
            declarations.append('impl PartialEq for '+name+'{fn eq(&self,other:&Self)->bool{match(self,other){'+','.join(values)+(',_=>false'if values else'')+'}}}')
            declarations.append('impl '+name+'{fn class_same_identity(&self,other:&Self)->bool{match(self,other){'+','.join(identities)+(',_=>false'if identities else'')+'}}}')
        return '\n'.join(declarations)


def registry(model):
    result=getattr(model,'callable_carriers',None)
    if result is None:
        result=Registry(model);model.callable_carriers=result
    return result


def rust_type(model,kind):return registry(model).register(kind)


def construct(provider,target,*values):
    from .native_aot_callables import AotFunctionType
    current=registry(provider.model)
    current.register(AotFunctionType.from_targets((target,)))
    layout=current.layout(target)
    if len(values)!=len(layout.fields):raise RuntimeError('callable payload schema differs from its source capture')
    return payload_type(target)+'{'+','.join(name+':'+value for(name,_),value in zip(layout.fields,values))+'}'


def pattern(provider,target,kind,*,call=False):
    current=registry(provider.model);current.register(kind)
    layout=current.layout(target)
    names={'environment':'class_selected_environment','module':'class_defining_module','bound':'class_selected_method'}
    fields=','.join(name+':'+names[name]for name,_ in layout.fields)if call else'..'
    value=payload_type(target)+'{'+fields+'}'
    return value if len(kind.targets)==1 else family_type(kind)+'::'+tag(target)+'('+value+')'


def bind_payload(provider,target,code):
    from .native_aot_callables import AotFunctionType
    kind=AotFunctionType.from_targets((target,))
    return 'let '+pattern(provider,target,kind,call=True)+'='+code+';'


def inject(model,target,wanted,payload):
    rust_type(model,wanted)
    return payload if len(wanted.targets)==1 else family_type(wanted)+'::'+tag(target)+'('+payload+')'


def dispatch(emitter,kind,code,branch,*,borrow=False):
    registry(emitter.model).register(kind)
    temporary=emitter.fresh()
    if borrow:code='&('+code+')'
    if len(kind.targets)==1:
        return '{let '+temporary+'='+code+';'+branch(kind.targets[0],temporary)+'}'
    arms=[family_type(kind)+'::'+tag(target)+'('+temporary+')=>'+branch(target,temporary)for target in kind.targets]
    return 'match '+code+'{'+','.join(arms)+'}'


def convert(emitter,node,stored,wanted,code,*,narrow=False):
    from .native_classes import ClassUnsupported
    if stored==wanted:return code
    if not narrow and not set(stored.targets)<=set(wanted.targets):
        raise ClassUnsupported(node,'this function reference has targets outside the solved receiving family',types=(('value',stored),('destination',wanted)),proof='finite callable family inclusion')
    def branch(target,payload):
        if target not in wanted.targets:return 'unreachable!("callable binding contradicts solved control flow")'
        return inject(emitter.model,target,wanted,payload)
    return dispatch(emitter,stored,code,branch)


def comparison(emitter,left,right,*,identity=False):
    def first(target,a):
        def second(other,b):
            if target!=other:return 'false'
            return a+'.class_same_identity('+b+')'if identity else a+'=='+b
        return dispatch(emitter,right.kind,right.code,second,borrow=True)
    return dispatch(emitter,left.kind,left.code,first,borrow=True)


def test_target(kind,code,target):
    if len(kind.targets)==1:
        return '{let _=&('+code+');'+str(kind.targets[0]==target).lower()+'}'
    return 'matches!(&('+code+'),'+family_type(kind)+'::'+tag(target)+'(..))'


def runtime(model):return registry(model).runtime()
