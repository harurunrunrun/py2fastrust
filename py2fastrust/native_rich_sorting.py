"""Source rich comparisons over the existing fallible stable index sorter."""
import ast


def analyze(model,plan,node,site,environment,*,method):
    from .native_classes import Environment,shape
    from .native_types import alternatives,EmptyType
    from .native_cmp_keys import CmpKeyType
    site.rich_comparisons={}
    if site.error or isinstance(shape(site.element),EmptyType):return
    inside=Environment(environment)
    for branch in alternatives(shape(site.key)):
        if isinstance(branch,CmpKeyType):continue
        element=site.element if branch=='none'else(site.callback.result if site.callback is not None else None)
        if element is None:continue
        index=('sorting_less',method,branch)
        comparison=model.operators.comparison(plan,node,index,ast.Lt(),element,element,inside)
        if comparison is not None:site.rich_comparisons[branch]=index
    if site.rich_comparisons:
        model.replace_environment(environment,model.join(environment,inside,node,'sorting_comparison'))


def _class_identity(emitter,value,node):
    from .native_classes import Expression,InstanceType
    from .native_unions import union_kind,project
    if union_kind(value.kind):
        return project(value.kind,value.code,lambda kind,code:_class_identity(emitter,Expression(code,kind),node))
    if isinstance(value.kind,InstanceType):
        owner=emitter.model.classes[value.kind.name]
        return 'Some(('+str(owner.index)+'usize,Rc::as_ptr(&('+value.code+').borrow().class_definition)as usize))'
    return 'None::<(usize,usize)>'

def emit(emitter,node,values,element,reverse,key,site):
    from .native_classes import Expression
    from .native_class_calls import entry_result
    first,second,order,error,identity,homogeneous,item=(emitter.fresh()for _ in range(7))
    prefix='.0'if key.kind!='none'else''
    left=Expression(values+'['+first+']'+prefix+'.clone()',element)
    right=Expression(values+'['+second+']'+prefix+'.clone()',element)
    before,left=emitter.capture(left);more,right=emitter.capture(right);before+=more
    comparison=emitter.model.operators.emit_comparison(emitter,node,site.rich_comparisons[key.kind],ast.Lt(),left,right,repeat_left_not_implemented_if=homogeneous)
    more,comparison=emitter.capture(comparison);before+=more
    body=before+'Ok::<bool,NativeError>('+emitter.truth(comparison,node)+')'
    asynchronous=not entry_result(emitter.model,emitter.plan)
    modes=getattr(emitter.model,'cmp_sort_modes',None)
    if modes is None:modes=set();emitter.model.cmp_sort_modes=modes
    modes.add(asynchronous)
    closure=('async 'if asynchronous else'')+'|'+first+':usize,'+second+':usize|{'+body+'}'
    memory='||native_at::<()>(Err("MemoryError: cannot allocate sorting indices".to_owned()),'+str(node.lineno)+','+emitter.location_code()+').unwrap_err()'
    invocation='native_cmp_sort_indices'+('_async'if asynchronous else'')+'('+values+'.len(),'+reverse+','+closure+','+memory+')'+('.await'if asynchronous else'')+'?'
    fingerprint=_class_identity(emitter,Expression('(*'+item+')'+prefix,element),node)
    proof='let '+identity+'='+values+'.first().and_then(|'+item+'|'+fingerprint+');let '+homogeneous+'='+identity+'.is_some()&&'+values+'.iter().all(|'+item+'|'+fingerprint+'=='+identity+');'
    return (proof+'let(mut '+order+','+error+')='+invocation+';native_cmp_sort_apply(&mut '+values+',&mut '+order+');'
            'if let Some(error)='+error+'{return Err(error);}')
