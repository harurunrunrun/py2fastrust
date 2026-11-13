"""Delete original typed mapping entries without invoking missing factories."""
import ast


def requires_frames(unit,analysis):
    from .native_key_types import DictType
    from .native_types import alternatives
    for node in ast.walk(unit.tree):
        if not isinstance(node,ast.Delete):continue
        for target in node.targets:
            for child in ast.walk(target):
                if not isinstance(child,ast.Subscript):continue
                choices=[kind for facts in analysis.scopes.values()
                         if (kind:=facts.expressions.get(unit.ordinal(child.value)))is not None]
                if not choices or any(isinstance(part,DictType)
                                      for kind in choices for part in alternatives(kind)):return True
    return False


def analyze(model,plan,node,environment):
    if not isinstance(node,ast.Subscript)or isinstance(node.slice,ast.Slice):return False
    from .native_classes import shape,ClassUnsupported
    from .native_class_mappings import mapping_kind,key_supported,key_pending,unhashable_leaf
    from .native_types import alternatives,EmptyType
    owner=model.expression(plan,node.value,environment)
    kinds=alternatives(shape(owner))
    if None in kinds and not model.final:
        from .native_guard_flow import AnalysisPending
        raise AnalysisPending()
    if not any(mapping_kind(kind)and kind.record.category=='dict'for kind in kinds):return False
    if not all(mapping_kind(kind)and kind.record.category=='dict'for kind in kinds):
        raise ClassUnsupported(node,'indexed deletion from mixed mapping/nonmapping receivers needs a native deletion adapter for every alternative',types=(('receiver',shape(owner)),),proof='finite dictionary deletion alternatives')
    index=model.expression(plan,node.slice,environment)
    for kind in alternatives(shape(index)):
        if key_pending(kind)or isinstance(kind,EmptyType)or key_supported(kind)or unhashable_leaf(kind)is not None:continue
        raise ClassUnsupported(node,'this dictionary deletion key needs a floating/custom hash and equality protocol that is not implemented',types=(('key',kind),),proof='dictionary deletion query hash/equality')
    if not hasattr(model,'mapping_delete_sites'):model.mapping_delete_sites={}
    model.mapping_delete_sites[plan.index,id(node)]=(owner,index)
    model.exceptions.require(node)
    return True


def emit(emitter,node):
    if (emitter.plan.index,id(node))not in getattr(emitter.model,'mapping_delete_sites',{}):return None
    from .native_classes import Expression,shape,ClassUnsupported
    from .native_class_mappings import key_supported,unhashable_leaf,query_type_name,query_canonical
    from .native_unions import project
    from .native_types import EmptyType
    from .native import _string
    before,owner=emitter.capture(emitter.expression(node.value))
    more,key=emitter.capture(emitter.expression(node.slice));before+=more
    def owner_branch(kind,code):
        def key_branch(index_kind,index_code):
            current=Expression('('+index_code+').clone()',index_kind)
            if isinstance(index_kind,EmptyType):return 'native_empty::<()>('+index_code+')'
            if not key_supported(index_kind):
                leaf=unhashable_leaf(index_kind)
                if leaf is None:raise ClassUnsupported(node,'dictionary deletion needs a native hash/equality adapter for this key',types=(('key',index_kind),),proof='dictionary deletion hash protocol')
                error='format!("TypeError: cannot use \'{}\' as a dict key (unhashable type: \'{}\')",'+query_type_name(emitter,current,node)+','+_string(leaf)+')'
                return emitter.at('Err::<(),String>('+error+')',node)
            canonical,removed=(emitter.fresh()for _ in range(2))
            query=query_canonical(emitter,current,shape(kind.record.key))
            body='let '+removed+'=match '+query+'{Some('+canonical+')=>('+code+').borrow_mut().delete(&'+canonical+'),None=>false};'
            if kind.record.flavor!='Counter':
                failure=emitter.at('Err::<(),String>(format!("KeyError: {}",'+emitter.show(current,node,True)+'))',node)
                body+='if !'+removed+'{'+failure+';}'
            return '{'+body+'()}'
        return project(key.kind,key.code,key_branch)
    return before+project(owner.kind,owner.code,owner_branch)+';'
