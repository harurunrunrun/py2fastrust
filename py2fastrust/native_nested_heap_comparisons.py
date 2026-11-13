"""Compile fixed tuple heap keys into ordered, typed comparison expressions.

Only the compiler walks these plans. Generated Rust contains ordinary tuple
field accesses, short-circuit branches and the existing source callback ABI.
"""
import ast
from dataclasses import dataclass,field

from .native_types import EmptyType,ListType,TupleType,TupleSequenceType,alternatives


@dataclass
class Plan:
    left:object
    right:object
    equal:bool
    operation:str
    branches:dict=field(default_factory=dict)
    fields:list=field(default_factory=list)
    index:object=None
    truth:object=None
    rich:bool=False
    identity:bool=False


@dataclass
class Comparison:
    plan:object
    _native_nested_heap_comparison=True


def contains(kind,predicate):
    for choice in alternatives(kind):
        if predicate(choice):return True
        if isinstance(choice,TupleType)and any(contains(child,predicate)for child in choice.fields):return True
        if isinstance(choice,(ListType,TupleSequenceType))and contains(choice.element,predicate):return True
    return False


def _join(model,node,states,role):
    joined=None
    for state in states:joined=state if joined is None else model.join(joined,state,node,role)
    return joined


def analyze(model,caller,node,name,heap,environment):
    from .native_classes import shape,InstanceType,ClassUnsupported,Environment
    from .native_fallible_heapq import builtin_kind
    kind=shape(heap.args[0])
    from .native_class_identity_demand import observe_implicit
    observer=('heap_nested',name)
    reason='a fixed tuple heap element comparison observes source instance identity'
    def absent():
        observe_implicit(model,caller,node,observer,(),reason)
        return None
    roots=alternatives(kind)
    if not any(isinstance(choice,TupleType)for choice in roots):return absent()
    floating=contains(kind,lambda child:child=='float')
    source=contains(kind,lambda child:isinstance(child,InstanceType))
    if not floating and not source:return absent()
    if floating:
        if not model.final:return absent()
        raise ClassUnsupported(node,'nested heap float equality needs a proved absence of NaN or retained Python float identity; raw binary64 storage cannot distinguish a shared NaN from distinct NaN objects',types=(('element',kind),),proof='identity-aware floating tuple element equality')
    if not all(isinstance(choice,TupleType)and not getattr(choice,'_native_named_tuple',False)for choice in roots):
        if not model.final:return absent()
        raise ClassUnsupported(node,'source-object tuple heap keys mixed with other root key types need their cross-type reflected tuple comparison protocol',types=(('element',kind),),proof='fixed tuple heap key alternatives')

    def supported(value):
        for child in alternatives(value):
            if isinstance(child,TupleType):
                if getattr(child,'_native_named_tuple',False)or not all(supported(field)for field in child.fields):return False
            elif not(isinstance(child,InstanceType)or builtin_kind(child)):return False
        return True
    if not supported(kind):
        if not model.final:return absent()
        raise ClassUnsupported(node,'this nested heap key needs live mutable/runtime-length container comparison or a descriptor/key-wrapper protocol beyond fixed tuples and source-object leaves',types=(('element',kind),),proof='typed fixed tuple comparison payload')

    def view(value,wanted):return model.namespace.representation(wanted,[value],node)

    observed=set()
    def compare(left,right,equal,inside,path):
        a,b=shape(left),shape(right)
        first,second=alternatives(a),alternatives(b)
        if len(first)>1 or len(second)>1:
            result=Plan(a,b,equal,'union');states=[]
            for x in first:
                for y in second:
                    branch=Environment(inside)
                    result.branches[x,y]=compare(view(left,x),view(right,y),equal,branch,path+('pair',x,y))
                    states.append(branch)
            model.replace_environment(inside,_join(model,node,states,('heap_nested_union',path,equal)))
            return result
        if isinstance(a,TupleType)and isinstance(b,TupleType):
            result=Plan(a,b,equal,'tuple');remaining=Environment(inside);states=[]
            lvalue,rvalue=view(left,a),view(right,b)
            for index in range(min(len(a.fields),len(b.fields))):
                x,y=lvalue.args[index],rvalue.args[index]
                equality=compare(x,y,True,remaining,path+('field',index,'eq'))
                if equal:
                    states.append(Environment(remaining));result.fields.append((equality,None))
                else:
                    # A less-than branch terminates this tuple comparison.
                    # Its effects must not precede a later field's equality.
                    unequal=Environment(remaining)
                    less=compare(x,y,False,unequal,path+('field',index,'lt'))
                    states.append(unequal);result.fields.append((equality,less))
            states.append(remaining)
            model.replace_environment(inside,_join(model,node,states,('heap_nested_tuple',path,equal)))
            return result
        if (isinstance(a,TupleType)or isinstance(b,TupleType))and(isinstance(a,InstanceType)or isinstance(b,InstanceType)):
            raise ClassUnsupported(node,'a nested tuple/source-object pair needs reflected whole-tuple special-method dispatch; this heap adapter currently supports source objects as scalar leaves on both sides',types=(('left',a),('right',b)),proof='reflected cross-type tuple rich comparison')
        identity=equal and isinstance(a,InstanceType)and a==b
        if identity:observed.add(a)
        result=Plan(a,b,equal,'scalar',identity=identity)
        result.index=('heap_nested',name,path,'eq'if equal else'lt',a,b)
        result.truth=('heap_nested_truth',result.index)
        branch=Environment(inside)
        value=model.operators.comparison(caller,node,result.index,ast.Eq()if equal else ast.Lt(),left,right,branch,canonical_slots=True)
        if value is not None:
            from .native_source_lengths import analyze_truth
            result.rich=True
            analyze_truth(model,caller,node,value,branch,identity=result.truth)
        model.replace_environment(inside,model.join(inside,branch,node,('heap_nested_identity',path))if identity else branch)
        return result

    inside=Environment(environment)
    result=compare(heap.args[0],heap.args[0],False,inside,())
    observe_implicit(model,caller,node,observer,observed,reason)
    model.replace_environment(environment,model.join(environment,inside,node,'heap_nested_comparison'))
    return Comparison(result)


def emit(emitter,node,comparison,left,right):
    from .native_classes import Expression
    from .native_unions import project
    from .native_fallible_heapq import _builtin

    def compare(plan,a,b):
        if plan.operation=='union':
            return project(a.kind,a.code,lambda x,first:project(b.kind,b.code,
                lambda y,second:compare(plan.branches[x,y],Expression('('+first+').clone()',x),Expression('('+second+').clone()',y))))
        if plan.operation=='tuple':
            result=str(len(plan.left.fields)==len(plan.right.fields)if plan.equal else len(plan.left.fields)<len(plan.right.fields)).lower()
            for index in reversed(range(len(plan.fields))):
                x=Expression('('+a.code+').'+str(index)+'.clone()',plan.left.fields[index])
                y=Expression('('+b.code+').'+str(index)+'.clone()',plan.right.fields[index])
                equality,less=plan.fields[index];same=compare(equality,x,y)
                result='('+same+')&&('+result+')'if plan.equal else'if '+same+'{'+result+'}else{'+compare(less,x,y)+'}'
            return '{'+result+'}'
        operator=ast.Eq()if plan.equal else ast.Lt()
        if plan.rich:
            value=emitter.model.operators.emit_comparison(emitter,node,plan.index,operator,a,b)
            before,value=emitter.capture(value)
            result='{'+before+emitter.truth(value,node,identity=plan.truth)+'}'
        else:result=_builtin(emitter,operator,a,b,node)
        if plan.identity:
            same=emitter.comparison_builtin(ast.Is(),a,b,node)
            result='('+same+')||('+result+')'
        return result

    return compare(comparison.plan,left,right)
