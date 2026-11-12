"""Demand-driven native scalar data returns over original source functions."""
import ast
from contextlib import contextmanager
from dataclasses import dataclass

from .native_scalar_fresh_results import Registry as FreshResults


@dataclass
class Request:
    node:object
    owner:object
    consumed:bool=False


class Registry:
    def __init__(self,model):
        self.model=model
        self.fresh=FreshResults(model)
        self.demands=set()
        self.emitted={}
        self.stores=set()
        self.reuse={}

    def expression(self,plan,node):
        from .native_classes import InstanceType
        kind=self.fresh.values.kind(plan,node)
        owner=self.fresh.owner(kind)
        if owner is None:return None
        if isinstance(node,ast.Call):
            return owner if self.fresh.fresh_call(plan,node,owner)else None
        if not isinstance(node,ast.BinOp):return None
        site=self.model.operators.sites.get((plan.index,id(node),None))
        if site is None or not site.branches:return None
        for branch in site.branches.values():
            if not branch.complete or branch.fallback is not None or len(branch.phases)!=1:return None
            phase=branch.phases[0]
            if phase.member.descriptor!='function':return None
            call=phase.site
            if (call.errors or call.builtins or call.members or call.constructors
                    or call.exception_constructors or len(call.targets)!=1):return None
            target=next(iter(call.targets))
            definition=getattr(target,'definition',target)
            callee=self.model.callable_cells.plans.get(definition)
            info=None if callee is None else self.fresh.results.get(callee.index)
            if info is None or info.owner is not owner:return None
        return owner


def prepare(model):model.scalar_data_results=Registry(model)


def registry(emitter):return getattr(emitter.model,'scalar_data_results',None)


@contextmanager
def capture(emitter,node,owner):
    previous=getattr(emitter,'scalar_data_request',None)
    request=Request(node,owner)
    emitter.scalar_data_request=request
    try:yield request
    finally:emitter.scalar_data_request=previous


def constructor_name(emitter,node,owner,name):
    request=getattr(emitter,'scalar_data_request',None)
    if request is None or request.node is not node or request.owner is not owner:return name
    if name=='class_construct_'+str(owner.index):
        request.consumed=True
        return 'class_build_'+str(owner.index)
    if name=='class_state_construct_'+str(owner.index):
        request.consumed=True
        return 'class_state_build_'+str(owner.index)
    return name


def call_name(emitter,node,target,name):
    state=registry(emitter)
    request=getattr(emitter,'scalar_data_request',None)
    if state is None or request is None or request.node is not node:return name
    info=state.fresh.results.get(target.index)
    if info is None or info.owner is not request.owner:return name
    if name=='class_function_'+str(target.index):private=False
    elif name=='class_state_function_'+str(target.index):private=True
    else:return name
    state.demands.add((target.index,private))
    request.consumed=True
    return ('class_state_data_function_'if private else'class_data_function_')+str(target.index)


def bound_call(emitter,node,target,invocation):
    name,separator,arguments=invocation.partition('(')
    return call_name(emitter,node,target,name)+separator+arguments


def expected_type(emitter,node,kind):
    request=getattr(emitter,'scalar_data_request',None)
    from .native_classes import InstanceType
    if (request is not None and request.node is node
            and kind==InstanceType(emitter.model.class_key(request.owner))):
        return 'ClassData_'+str(request.owner.index)
    return emitter.rust_type(kind)


def call_result(emitter,node,invocation,called):
    request=getattr(emitter,'scalar_data_request',None)
    if request is None or request.node is not node:return called
    name=invocation.partition('(')[0]
    request.consumed=True
    if name.startswith(('class_data_function_','class_state_data_function_',
                        'class_build_','class_state_build_')):
        return called
    temporary=emitter.fresh()
    return '{let '+temporary+'='+called+';(*'+temporary+').clone()}'


def function_name(emitter,plan):
    info=getattr(emitter,'scalar_data_result',None)
    if info is None or info.plan is not plan:return None
    return ('class_state_data_function_'if getattr(emitter,'source_state_private',False)
            else'class_data_function_')+str(plan.index)


def result_type(emitter):
    info=getattr(emitter,'scalar_data_result',None)
    return None if info is None else'ClassData_'+str(info.owner.index)


def local_type(emitter,name):
    info=getattr(emitter,'scalar_data_result',None)
    return 'ClassData_'+str(info.owner.index)if info is not None and name in info.locals else None


def reference(emitter,node):
    info=getattr(emitter,'scalar_data_result',None)
    if info is None or id(node)not in info.fields:return None
    from .native_classes import Expression,shape
    from .native import _string
    owner=info.owner;name=emitter.model.resolved_name(emitter.plan,node.value)
    kind=emitter.kind(node.value);slot=emitter.slot(name,kind);receiver=emitter.fresh()
    message="UnboundLocalError: cannot access local variable '"+emitter.model.display_name(name)+"' where it is not associated with a value"
    loaded=emitter.at(slot+'.as_ref().ok_or_else(||'+_string(message)+'.to_owned())',node.value)
    field=emitter.model.resolved_name(emitter.plan,node);index=list(owner.fields).index(field)
    return 'let '+receiver+'='+loaded+';',('field',Expression(receiver,kind),owner,index,shape(owner.fields[field].cell))


def data_value(emitter,node,owner):
    from .native_classes import Expression
    with capture(emitter,node,owner)as request:
        value=data_binary(emitter,node,owner)
        if value is None:value=emitter.expression(node)
    if request.consumed:return value
    # A native callee can retain its ordinary shared return ABI. The original
    # source certificate still proves this result fresh and unpublished; copy
    # only its concrete scalar payload, retaining every actual source effect.
    temporary=emitter.fresh()
    return Expression('{let '+temporary+'='+value.code+';(*'+temporary+').clone()}',value.kind)


def data_binary(emitter,node,owner):
    if not isinstance(node,ast.BinOp):return None
    proof=getattr(emitter.model,'scalar_data_locals',None)
    if (proof is None or not proof.view_formals(proof.phases(emitter.plan,node))
            or not proof.node_safe(emitter.plan,node,owner)):return None
    from .native_classes import Expression,InstanceType
    def operand(node):
        kind=emitter.kind(node)
        if not isinstance(kind,InstanceType):return emitter.expression(node)
        if emitter.model.classes[kind.name]is not owner:return None
        if isinstance(node,ast.Subscript):
            from .native_types import ListType
            if not isinstance(emitter.kind(node.value),ListType)or isinstance(node.slice,ast.Slice):return None
            from .native_scalar_data_locals import data_value as list_data
            return list_data(emitter,node,owner)
        if isinstance(node,ast.Name)and emitter.model.value_classes.local(emitter.plan,node,owner):
            from .native_scalar_data_parameters import read as parameter
            direct=parameter(emitter,node)
            if direct is not None:return Expression('('+direct.code+').clone()',kind)
            from .native_scalar_data_locals import local_type as snapshot_type
            name=emitter.model.resolved_name(emitter.plan,node)
            slot=emitter.slot(name,kind)
            from .native import _string
            message="UnboundLocalError: cannot access local variable '"+emitter.model.display_name(name)+"' where it is not associated with a value"
            loaded=emitter.at(slot+'.as_ref().ok_or_else(||'+_string(message)+'.to_owned())',node)
            info=getattr(emitter,'scalar_data_result',None)
            concrete=snapshot_type(emitter,name)is not None or info is not None and name in info.locals
            variable=emitter.fresh()
            return Expression('{let '+variable+'='+loaded+';'+('(*'if concrete else'(**')+variable+').clone()}',kind)
        return None
    left=operand(node.left);right=operand(node.right)
    if left is None or right is None:return None
    before,left=emitter.capture(left);more,right=emitter.capture(right)
    result=emitter.binary(node.op,left,right,node,emitter.kind(node))
    return Expression('{'+before+more+result.code+'}',result.kind)


def statement(emitter,node):
    state=registry(emitter)
    if state is None:return None
    info=getattr(emitter,'scalar_data_result',None)
    if info is not None:
        if isinstance(node,ast.Return)and id(node)in info.returns:
            value=(emitter.expression(node.value)if isinstance(node.value,ast.Name)
                   else data_value(emitter,node.value,info.owner))
            return 'return Ok('+value.code+');'
        value=info.assignments.get(id(node))
        if value is not None:
            target=node.targets[0]if isinstance(node,ast.Assign)else node.target
            before,result=emitter.capture(data_value(emitter,value,info.owner))
            return before+emitter.assign(target,result)
    if not isinstance(node,ast.Assign)or len(node.targets)!=1:return None
    target=node.targets[0]
    if not isinstance(target,ast.Subscript):return None
    from .native_types import ListType
    owner=state.expression(emitter.plan,node.value)
    kind=emitter.kind(target.value)
    if owner is None or not isinstance(kind,ListType)or emitter.kind(target)!=emitter.kind(node.value):return None
    before,place=emitter.reference(target)
    if place[0]not in {'index','list_region'}:return None
    _,container,index,element=place
    setup,value=emitter.capture(data_value(emitter,node.value,owner))
    state.stores.add(owner.index)
    call=(('class_slice_set_data_'+str(owner.index)+'(&mut '+container.storage(True)
           if place[0]=='list_region'else'class_list_set_data_'+str(owner.index)+'(&'+container.code)
          +',&('+emitter.number(index)+'),'+value.code+')')
    return setup+before+emitter.at(call,target)+';'


def bodies(model):
    state=getattr(model,'scalar_data_results',None)
    if state is None:return []
    output=[]
    done=set()
    while state.demands-done:
        index,private=min(state.demands-done)
        done.add((index,private));info=state.fresh.results[index]
        emitter=model.emitter(info.plan)
        emitter.native_direct_body=True
        emitter.scalar_data_result=info
        if private:
            source=model.source_state;abi=source.abis[index]
            emitter.source_state_private=True
            emitter.source_state_active=(source.modes['function',index],
                {slot.key:'class_state_value_'+str(i)for i,slot in enumerate(abi.slots)})
        name=function_name(emitter,info.plan)
        state.emitted[name]=info.plan
        output.append(emitter.generate())
    from .native_class_identity_demand import Unproved
    for index in sorted(state.stores):
        owner=next(owner for owner in model.classes.values()if owner.index==index)
        try:model.class_identity_demand.prove(owner)
        except Unproved:reuse=False
        else:reuse=True
        state.reuse[index]=reuse
        store=('if let Some(previous)=Rc::get_mut(target){*previous=value;}else{*target=Rc::new(value);}'
               if reuse else'*target=Rc::new(value);')
        output.append('#[inline(always)]\nfn class_list_set_data_'+str(index)
            +'(values:&ClassList<ClassHandle_'+str(index)+'>,index:&NativeInt,value:ClassData_'+str(index)
            +')->Result<(),String>{class_slice_set_data_'+str(index)+'(&mut values.borrow_mut(),index,value)}')
        output.append('#[inline(always)]\nfn class_slice_set_data_'+str(index)
            +'(values:&mut [ClassHandle_'+str(index)+'],index:&NativeInt,value:ClassData_'+str(index)
            +')->Result<(),String>{let target=class_slice_get_mut(values,index)?;'+store+'Ok(())}')
    return output
