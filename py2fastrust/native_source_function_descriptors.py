"""Bind actual class-slot Python function values to their captured instance."""
import ast
from dataclasses import dataclass
from .native_class_descriptors import ClassMethodTarget


@dataclass(frozen=True)
class InstanceFunctionTarget(ClassMethodTarget):
    _native_instance_function_target=True
    @property
    def _native_receiver_kind(self):
        from .native_classes import InstanceType
        return InstanceType(self.owner)
    @property
    def _native_kind_tag(self):return 'instance_function_'+str(self.definition)+'_'+str(self.class_definition)


def structure(target):return 'ClassInstanceFunction_'+str(target.definition)+'_'+str(target.class_definition)


@dataclass
class InstanceRead:
    owner:object
    member:object
    field:object=None


def bind_kind(registry,owner,value,node):
    from .native_classes import Cell,shape
    from .native_types import alternatives
    from .native_aot_callables import function_kind
    result=Cell()
    for kind in alternatives(shape(value)):
        if not function_kind(kind):
            registry.model.contribute(result,registry.model.cell_for_kind(kind),node)
            continue
        targets=[]
        for target in kind.targets:
            if isinstance(target,int):
                target=InstanceFunctionTarget(target,registry.model.class_key(owner),owner.index)
                registry.model.callable_cells.bound_methods.used.add(target)
                definitions=getattr(registry.model,'instance_function_definitions',None)
                if definitions is None:definitions=registry.model.instance_function_definitions=set()
                definitions.add(target.definition)
            targets.append(target)
        registry.model.contribute(result,Cell('function',tuple(targets)),node)
    return result


def analyze(registry,plan,node,receiver,environment):
    from .native_classes import Cell,shape,InstanceType,ClassUnsupported,domain
    from .native_types import alternatives,EMPTY
    from .native_aot_callables import function_kind
    choices=alternatives(shape(receiver))
    name=registry.model.resolved_name(plan,node)
    members=[];required=False
    for kind in choices:
        if not isinstance(kind,InstanceType):members.append((kind,None,None));continue
        owner=registry.model.classes[kind.name];member=registry.members.get((owner.index,name))
        if member is not None:
            value=registry.field(member,node)
            required|=(member.plan is not None and member.descriptor=='function'
                       or any(function_kind(part)and part.definitions for part in alternatives(shape(value))))
        members.append((kind,owner,member))
    if not required:return None
    result=registry.model.cell(plan,node,identity='instance_function_descriptor_result')
    cases={}
    for kind,owner,member in members:
        if owner is None:
            from .native_finite_attributes import BUILTIN_TYPES
            builtin=BUILTIN_TYPES.get(domain(kind))
            if builtin is None or hasattr(builtin,node.attr):
                raise ClassUnsupported(node,'finite function-descriptor lookup includes an unregistered builtin descriptor receiver',types=(('receiver',kind),),proof='finite function descriptor receiver lookup')
            cases[kind]=None
            continue
        field=owner.fields.get(name)
        field=field if field is not None and field.written else None
        cases[kind]=InstanceRead(owner,member,field)
        if member is None:value=Cell(EMPTY)
        else:
            registry.check_metadata(member,node)
            if member.plan is not None:registry.observe_method(member,node)
            value=registry.field(member,node)
            if member.plan is not None and member.descriptor!='function':
                from .native_class_descriptors import analyze_member
                value=analyze_member(registry,plan,node,member,registry.model.cell_for_kind(kind),environment)
            else:value=bind_kind(registry,owner,value,node)
        registry.model.namespace.contribute(result,value,node,force=True)
        if field is not None:registry.model.namespace.contribute(result,field.cell,node,force=True)
    sites=getattr(registry,'instance_function_reads',None)
    if sites is None:sites=registry.instance_function_reads={}
    sites[plan.index,id(node)]=cases
    return registry.model.remember(plan,node,result)


def bind_value(registry,emitter,node,owner,receiver,value,wanted):
    from .native_classes import Expression
    from .native_aot_callables import function_kind,AotFunctionType
    from .native_unions import project
    def branch(kind,code):
        if not function_kind(kind):return emitter.coerce(Expression(code,kind),wanted,node)
        from .native_callable_carriers import dispatch,construct
        def target_value(target,payload):
            if not isinstance(target,int):return emitter.coerce(Expression(payload,AotFunctionType.from_targets((target,))),wanted,node)
            selected=InstanceFunctionTarget(target,registry.model.class_key(owner),owner.index)
            fields='receiver:('+receiver.code+').clone(),function:'+payload
            from .native_immediate_classmethod import stack_payload
            bound=stack_payload(emitter,node,selected,fields)
            if bound is None:bound=construct(registry.model.callable_cells,selected,'Rc::new('+structure(selected)+'{'+fields+'})')
            return emitter.coerce(Expression(bound,AotFunctionType.from_targets((selected,))),wanted,node)
        return dispatch(emitter,kind,code,target_value)
    return Expression(project(value.kind,value.code,branch),wanted)


def emit(registry,emitter,node):
    cases=getattr(registry,'instance_function_reads',{}).get((emitter.plan.index,id(node)))
    if cases is None:return None
    from .native_classes import Expression,shape
    from .native_unions import project
    from .native_module_linking import ClassReferenceType
    from .native_class_builtins import _error,_type_name
    from .native import _string
    setup,receiver=emitter.capture(emitter.expression(node.value));wanted=emitter.kind(node)
    def branch(kind,code):
        current=Expression('('+code+').clone()',kind);case=cases[kind]
        if case is None:return _error(emitter,node,wanted,'format!('+_string("AttributeError: '{}' object has no attribute "+repr(node.attr))+','+_type_name(emitter,current,node)+')').code
        owner,member,field=case.owner,case.member,case.field
        if member is None:fallback=_error(emitter,node,wanted,_string('AttributeError: '+repr(owner.node.name)+' object has no attribute '+repr(node.attr))+'.into()').code
        else:
            reference=emitter.fresh();before='let '+reference+'={'+current.code+'.borrow().class_definition.clone()};'
            class_reference=Expression(reference,ClassReferenceType(owner.index))
            loaded=registry.emit_get(emitter,node,class_reference,member,instance=True)
            if member.plan is not None and member.descriptor!='function':
                from .native_class_descriptors import emit_member
                more,loaded_value=emitter.capture(loaded);before+=more
                loaded=emit_member(registry,emitter,node,member,class_reference,loaded_value)
            else:loaded=bind_value(registry,emitter,node,owner,current,loaded,wanted)
            fallback='{'+before+emitter.coerce(loaded,wanted,node)+'}'
        if field is None:return fallback
        from .native_copy_scalar_fields import load
        index=list(owner.fields).index(field.name);stored=emitter.fresh()
        actual=emitter.coerce(Expression('value',shape(field.cell)),wanted,node)
        return '{let '+stored+'={'+load(registry.model,owner,current.code,index)+'};match '+stored+'{Some(value)=>'+actual+',None=>'+fallback+'}}'
    return Expression('{'+setup+project(receiver.kind,receiver.code,branch)+'}',wanted)
