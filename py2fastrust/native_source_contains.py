"""Native membership calls to the original source __contains__ slot."""
import ast
from .call_semantics import Argument,CallArguments


def analyze(operators,plan,node,index,operator,left,right,environment):
    if not isinstance(operator,(ast.In,ast.NotIn)):return None
    from .native_classes import Cell,ClassUnsupported,InstanceType,shape
    from .native_types import alternatives
    if not any(isinstance(kind,InstanceType)for kind in alternatives(shape(right))):return None
    from .native_class_operators import BinarySite,Branch,Phase
    from .native_union_sequences import branches
    from .native_aot_callables import analyze_values
    model=operators.model;key=plan.index,id(node),index
    site=operators.comparison_sites.setdefault(key,BinarySite(model.cell(plan,node,identity=('source_contains',index)),operator))
    site.source_contains=True;site.branches={}
    model.contribute(site.result,Cell('bool'),node)
    for first in branches(left):
        for second in branches(right):
            a,b=shape(first),shape(second);branch=Branch(first,second);site.branches[a,b]=branch
            if not isinstance(b,InstanceType):
                branch.fallback='builtin';branch.complete=True;continue
            owner=model.classes[b.name]
            if '__contains__'not in owner.methods:
                raise ClassUnsupported(node,"class "+repr(owner.node.name)+" has no directly supported source __contains__ method; its descriptor/iterator/sequence membership fallback is not implemented",proof='source membership fallback protocol')
            namespace=model.class_namespaces;member=namespace.member(owner,'__contains__')
            if member.descriptor!='function':
                raise ClassUnsupported(node,'implicit __contains__ uses a nonfunction descriptor; descriptor-aware membership calls are not implemented',proof='source membership descriptor binding')
            from .native_source_display import guard_direct_method
            guard_direct_method(model,owner,'__contains__',node)
            namespace.observe_method(member,node)
            callback=analyze_values(model.callable_cells,plan,node,namespace.field(member,node),
                CallArguments((Argument(node),Argument(node)),()),[second,first],[],environment,
                identity=('source_contains',index,a,b))
            branch.phases.append(Phase(member,True,callback))
            from .native_source_lengths import analyze_truth
            analyze_truth(model,plan,node,callback.result,environment,identity=('source_contains_truth',index,a,b))
            branch.complete=shape(callback.result)is not None
            model.exceptions.require(node)
    return site.result


def emit(operators,emitter,node,index,operator,left,right):
    site=operators.comparison_sites.get((emitter.plan.index,id(node),index))
    if site is None or not getattr(site,'source_contains',False):return None
    from .native_classes import Expression,ClassUnsupported,InstanceType,shape
    from .native_module_linking import ClassReferenceType
    from .native_class_binding_contexts import CapturedClassContext
    from .native_aot_callables import emit_values
    from .native_builtin_singletons import NOT_IMPLEMENTED
    from .native_unions import project,union_kind
    def pair(first,second):
        branch=site.branches[first.kind,second.kind]
        if not branch.complete:
            raise ClassUnsupported(node,'source __contains__ result remains unresolved after callback analysis',proof='resolved membership callback result')
        if not branch.phases:return emitter.comparison_builtin(operator,first,second,node)
        phase=branch.phases[0];reference=emitter.fresh()
        setup='let '+reference+'={'+second.code+'.borrow().class_definition.clone()};'
        context=Expression(reference,ClassReferenceType(phase.member.owner.index))
        function=operators.model.class_namespaces.emit_get(emitter,node,context,phase.member)
        before,function=emitter.capture(function);setup+=before
        args=[Expression(value.code+'.clone()',value.kind)for value in (second,first)]
        returned=emit_values(emitter,node,phase.site,function,args,[],shape(phase.site.result),
            captured_class_context=CapturedClassContext(phase.member,context))
        before,returned=emitter.capture(returned);setup+=before
        def truth(kind,code):
            if kind==NOT_IMPLEMENTED:
                return emitter.at('Err::<bool,String>("TypeError: NotImplemented should not be used in a boolean context".to_owned())',node)
            try:return emitter.truth(Expression('('+code+').clone()',kind),node,identity=('source_contains_truth',index,first.kind,second.kind))
            except ClassUnsupported:
                raise ClassUnsupported(node,'source __contains__ returned a value without an implemented native truth conversion',types=(('return',kind),),proof='membership result truth conversion')from None
        result=project(returned.kind,returned.code,truth)if union_kind(returned.kind)else truth(returned.kind,returned.code)
        if isinstance(operator,ast.NotIn):result='!('+result+')'
        return '{'+setup+result+'}'
    def rhs(first):
        return project(right.kind,right.code,lambda kind,code:pair(first,Expression('('+code+').clone()',kind)))if union_kind(right.kind)else pair(first,right)
    code=project(left.kind,left.code,lambda kind,code:rhs(Expression('('+code+').clone()',kind)))if union_kind(left.kind)else rhs(left)
    return Expression(code,'bool')
