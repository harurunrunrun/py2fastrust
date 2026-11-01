"""Single-pass extrema over captured candidates and canonical key callbacks."""
import ast
from dataclasses import dataclass

from .call_semantics import Argument,CallArguments
from .references import BuiltinIdentity
from .native_types import EMPTY,EmptyType,alternatives,union_type


@dataclass
class ExtremaSite:
    element:object
    key:object
    source:object=None
    callback:object=None
    error:str|None=None


def _sites(model):
    if not hasattr(model,'extrema_sites'):model.extrema_sites={}
    return model.extrema_sites


def requires_frames(unit,analysis):
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for facts in analysis.scopes.values():
        for site,fact in facts.calls.items():
            if not any(BuiltinIdentity(name)in fact.identity.alternatives for name in ('min','max')):continue
            node=nodes.get(site)
            if isinstance(node,ast.Call)and any(keyword.arg!='key'or not isinstance(keyword.value,ast.Constant)or keyword.value.value is not None for keyword in node.keywords):return True
    return False


def binding_error(name,count,keywords):
    if not count:return f'TypeError: {name} expected at least 1 argument, got 0'
    for key in keywords:
        if key not in {'key','default'}:return f'TypeError: {name}() got an unexpected keyword argument {key!r}'
    if count>1 and 'default'in keywords:return f'TypeError: Cannot specify a default for {name}() with multiple positional arguments'
    return None


def _contribute(model,destination,value,node):
    if not model.namespace.contribute(destination,value,node,force=True):model.contribute(destination,value,node)


def analyze(model,plan,node,name,arguments,keywords,environment,*,factory):
    from .native_classes import Cell,shape,Environment
    values=dict(keywords);error=binding_error(name,len(arguments),values)
    element=model.cell(plan,node,identity=('extrema_element',name))
    site=ExtremaSite(element,values.get('key',Cell('none')),error=error)
    _sites(model)[(plan.index,id(node),name)]=site
    if error:return factory('none')
    if len(arguments)==1:
        source=arguments[0]
        if not getattr(shape(source),'_native_class_generator',False):
            site.source=model.iterators.source(plan,node,source,('extrema',name))
            source=Cell(site.source)
        _contribute(model,element,model.iterators.demand(plan,node,source,environment),node)
    else:
        for value in arguments:_contribute(model,element,value,node)
    result=factory()
    _contribute(model,result,element,node)
    if 'default'in values:_contribute(model,result,values['default'],node)
    key_kinds=[kind for kind in alternatives(shape(site.key))if kind!='none']if shape(site.key)is not None else[]
    if key_kinds and not isinstance(shape(element),EmptyType):
        from .native_aot_callables import analyze_values
        inside=Environment(environment)
        callback=model.cell_for_kind(union_type(*key_kinds))
        site.callback=analyze_values(model.callable_cells,plan,node,callback,
            CallArguments((Argument(node),),()),[element],[],inside,identity=('extrema_key',name))
        model.replace_environment(environment,model.join(environment,inside,node,('extrema_key',name)))
    return result


def kinds(model):
    from .native_classes import shape
    for site in _sites(model).values():
        yield shape(site.element)
        if site.callback is not None:yield shape(site.callback.result)


def snapshot(model):
    from .native_classes import shape
    return tuple((key,shape(site.element),shape(site.key),None if site.callback is None else shape(site.callback.result))for key,site in sorted(_sites(model).items()))


def emit(emitter,node,name,arguments,keywords,wanted):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    site=_sites(emitter.model)[(emitter.plan.index,id(node),name)]
    if site.error:
        from .native_class_builtins import _error
        from .native import _string
        return _error(emitter,node,wanted,_string(site.error)+'.to_owned()')
    key=keywords.get('key',Expression('()','none'))
    if union_kind(key.kind):
        code=project(key.kind,key.code,lambda kind,code:_select(emitter,node,name,site,arguments,keywords,Expression('('+code+').clone()',kind),wanted).code)
        return Expression(code,wanted)
    return _select(emitter,node,name,site,arguments,keywords,key,wanted)


def _select(emitter,node,name,site,arguments,keywords,key,wanted):
    from .native_classes import Expression,shape,ClassUnsupported
    from .native_class_builtins import _error
    from .native import _string
    element=shape(site.element)
    if element is None:raise ClassUnsupported(node,'the min/max iterable element representation remains unresolved',proof='solved extrema candidate representation')
    callback_kind=element if key.kind=='none'else shape(site.callback.result)if site.callback is not None else'none'
    if callback_kind is None:raise ClassUnsupported(node,'the min/max key callback result representation remains unresolved',proof='solved extrema key result')
    best=emitter.fresh();saved=emitter.fresh();key_saved=emitter.fresh()
    setup=f'let mut {best}:Option<({emitter.rust_type(element)},{emitter.rust_type(callback_kind)})>=None;'
    def append_item(e,item):
        if isinstance(item.kind,EmptyType):return 'match '+item.code+'{};'
        before,candidate=e.capture(Expression(e.coerce(item,element,node),element))
        if key.kind=='none':computed=Expression(candidate.code+'.clone()',element)
        else:
            from .native_aot_callables import emit_values
            computed=emit_values(e,node,site.callback,Expression('('+key.code+').clone()',key.kind),[Expression(candidate.code+'.clone()',element)],[],callback_kind)
        more,score=e.capture(computed)
        decision=e.comparison(ast.Lt()if name=='min'else ast.Gt(),Expression(score.code+'.clone()',callback_kind),Expression(key_saved+'.clone()',callback_kind),node)
        return before+more+f'let replace=match &{best}{{Some((_,{key_saved}))=>{decision},None=>true}};if replace{{{best}=Some(({candidate.code},{score.code}));}}'
    if len(arguments)>1:
        body=''.join(append_item(emitter,value)for value in arguments)
    elif getattr(arguments[0].kind,'_native_class_generator',False):
        body=emitter.model.generators.consume(emitter,node,'extrema',arguments[0],[],{},'none',append_item=append_item).code+';'
    else:
        source=emitter.model.iterators.construct(emitter,node,arguments[0],kind=site.source)
        before,source=emitter.capture(source);pulled=emitter.model.iterators.pull(emitter,node,source);current=emitter.fresh()
        body=before+f'loop{{let Some({current})=({pulled.code})else{{break;}};'+append_item(emitter,Expression(current,pulled.kind))+'}'
    present=emitter.coerce(Expression(saved,element),wanted,node)
    absent=(emitter.coerce(keywords['default'],wanted,node)if'default'in keywords else _error(emitter,node,wanted,_string(f'ValueError: {name}() iterable argument is empty')+'.to_owned()').code)
    return Expression('{'+setup+body+f'match {best}{{Some(({saved},_))=>{present},None=>{absent}}}'+'}',wanted)
