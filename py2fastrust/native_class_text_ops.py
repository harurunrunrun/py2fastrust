"""Bound builtin text operations reuse native kernels and captured operands."""
from dataclasses import dataclass
from .call_semantics import FunctionSignature,CallBindingError
from .native_types import alternatives

STRIP_NAMES=frozenset({'strip','lstrip','rstrip'})
STRIP_SIGNATURE=FunctionSignature.declaration(('chars',),positional_only=('chars',),default_names=('chars',))


@dataclass
class TextSite:
    name:str
    error:str|None=None


def _sites(model):
    if not hasattr(model,'text_operation_sites'):model.text_operation_sites={}
    return model.text_operation_sites


def bind(arguments,keywords,default):
    try:return STRIP_SIGNATURE.bind(arguments,keywords,{'chars':default}).by_name,None
    except CallBindingError:
        return None,'keywords'if keywords else'count'


def requires_frames(unit,analysis):
    from .native_class_text_replace import requires_frames as replace_requires_frames
    if replace_requires_frames(unit,analysis):return True
    import ast
    from .native_constraints import MethodValue,value
    from .call_semantics import normalize_call
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for scope in analysis.scopes.values():
        for ordinal,fact in scope.calls.items():
            for identity in fact.identity.alternatives:
                if not isinstance(identity,MethodValue)or identity.name not in STRIP_NAMES:continue
                from .native_text_receiver_facts import builtin_text_receiver_kinds
                kinds=builtin_text_receiver_kinds(unit,scope,nodes.get(ordinal),identity)
                if not kinds:continue
                if kinds!={'str'}:return True
                bound,error=bind(fact.positional,fact.keywords,value('none'))
                if error:return True
                characters=bound['chars']
                if characters.unknown or characters.unbound or not characters.alternatives<={'str','none'}:return True
                if 'none'in characters.alternatives:
                    try:original=STRIP_SIGNATURE.plan(normalize_call(nodes[ordinal])).capture(lambda expression,parameter:expression,defaults={'chars':None})['chars']
                    except CallBindingError:return True
                    if original is not None and not(isinstance(original,ast.Constant)and original.value is None):return True
    return False


def analyze(model,plan,node,receiver,arguments,keywords):
    from .native_class_text_replace import analyze as analyze_replace
    replacement=analyze_replace(model,plan,node,receiver,arguments,keywords)
    if replacement is not None:return replacement
    from .native_classes import Cell,shape
    name=node.func.attr
    if name not in STRIP_NAMES:return None
    kinds=alternatives(shape(receiver))
    if not kinds or not all(kind in {'str','bytes'}for kind in kinds):return None
    _,error=bind(arguments,keywords,Cell('none'))
    _sites(model)[(plan.index,id(node))]=TextSite(name,error)
    result=model.cell(plan,node)
    for kind in kinds:model.contribute(result,Cell(kind),node)
    return result


def emit(emitter,node,receiver,arguments,keywords,wanted):
    from .native_class_text_replace import emit as emit_replace
    replacement=emit_replace(emitter,node,receiver,arguments,keywords,wanted)
    if replacement is not None:return replacement
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_unions import project,union_kind
    from .native_class_builtins import _error,_type_name
    site=_sites(emitter.model).get((emitter.plan.index,id(node)))
    if site is None:return None
    bound,error=bind(arguments,list(keywords.items()),Expression('()','none'))
    def owner_branch(kind,text):
        if error:
            message=(f'TypeError: {kind}.{site.name}() takes no keyword arguments'if error=='keywords'
                     else f'TypeError: {site.name} expected at most 1 argument, got {len(arguments)}')
            return _error(emitter,node,wanted,'"'+message+'".to_owned()').code
        characters=bound['chars']
        def chars_branch(chars_kind,chars):
            if chars_kind not in {kind,'none'}:
                if kind=='bytes'and domain(chars_kind)=='object':
                    raise ClassUnsupported(node,'these bytes stripping characters need a user buffer protocol; the native strip adapter currently accepts builtin bytes or None',types=(('chars',chars_kind),),proof='strip builtin byte buffer representation')
                message=('"TypeError: '+site.name+' arg must be None or str".to_owned()'if kind=='str'else
                         'format!("TypeError: a bytes-like object is required, not \'{}\'",'+_type_name(emitter,Expression(chars,chars_kind),node)+')')
                return _error(emitter,node,wanted,message).code
            optional='None'if chars_kind=='none'else'Some(('+chars+').as_str())'if kind=='str'else'Some(('+chars+').as_slice())'
            name='native_text_strip'if kind=='str'else'native_frame_bytes_strip'
            code=name+'(&('+text+'),'+optional+','+str(site.name!='rstrip').lower()+','+str(site.name!='lstrip').lower()+')'
            if kind=='str':code='NativeText::from('+code+')'
            return emitter.coerce(Expression(code,kind),wanted,node)
        return project(characters.kind,characters.code,chars_branch)if union_kind(characters.kind)else chars_branch(characters.kind,characters.code)
    code=project(receiver.kind,receiver.code,owner_branch)if union_kind(receiver.kind)else owner_branch(receiver.kind,receiver.code)
    return Expression(code,wanted)


BYTES_STRIP=r'''
fn native_frame_bytes_strip(text:&[u8],characters:Option<&[u8]>,left:bool,right:bool)->Vec<u8>{
    let matches=|byte:u8|characters.map_or_else(||matches!(byte,9..=13|32),|characters|characters.contains(&byte));
    let mut start=0;let mut stop=text.len();
    if left{while start<stop&&matches(text[start]){start+=1;}}
    if right{while stop>start&&matches(text[stop-1]){stop-=1;}}
    text[start..stop].to_vec()
}
'''


def runtime(model):
    from .native_class_text_replace import runtime as replace_runtime
    replacement=replace_runtime(model)
    if not getattr(model,'text_operation_sites',None):return replacement
    from .native_text_methods import HELPERS
    return HELPERS+'\n'+BYTES_STRIP+'\n'+replacement
