"""Typed bounded top-k selection with captured source and key protocols.

The public route contract is documented by Python's heapq API. The native
bounded heap uses this project's existing heap helpers and stable ordinals.
"""
from dataclasses import dataclass
from types import SimpleNamespace
from .call_semantics import Argument,CallArguments,FunctionSignature,CallBindingError
from .native_types import EmptyType,alternatives,union_type

NAMES=frozenset({'nlargest','nsmallest'})
SIGNATURE=FunctionSignature.declaration(('n','iterable','key'),default_names=('key',))

@dataclass
class SelectionCall:
    result:object
    binding:object=None
    element:object=None
    key:object=None
    source:object=None
    callback:object=None
    error:str|None=None


def requires_frames(analysis):
    from .native_module_calls import BuiltinRef
    return any(isinstance(identity,BuiltinRef)and identity.module=='heapq'and identity.name in NAMES
               for facts in analysis.scopes.values()for call in facts.calls.values()for identity in call.identity.alternatives)


def _sites(model):
    if not hasattr(model,'heap_selection_sites'):
        model.heap_selection_sites={}
        from .native_callback_effects import register
        register(model,lambda plan,node:any(key[:2]==(plan.index,id(node))and site.callback is not None for key,site in model.heap_selection_sites.items()))
        from .native_owned_kinds import register as register_kinds
        from .native_classes import shape
        register_kinds(model,lambda:(shape(site.callback.result)for site in model.heap_selection_sites.values()if site.callback is not None))
    return model.heap_selection_sites


def analyze(model,plan,node,identity,metadata,positional,keywords,environment,*,factory):
    from .native_classes import Cell,Environment,ClassUnsupported,shape
    from .native_aot_callables import analyze_values,binding_error
    try:binding=SIGNATURE.plan(metadata)
    except CallBindingError as error:
        target=SimpleNamespace(signature=SIGNATURE,qualified_name=identity.name,node=None)
        return SelectionCall(factory('none'),error=binding_error(target,metadata,error))
    values=iter(positional+[value for _,value in keywords])
    bound=binding.capture(lambda expression,parameter:next(values),defaults={'key':Cell('none')}).by_name
    count=shape(bound['n'])
    if count is not None and any(kind not in {'int','bool','int_bool'}for kind in alternatives(count)):
        raise ClassUnsupported(node,'heap selection count needs an integer range bound; noninteger and user __index__ count protocols, including the floating count route, are not implemented',types=(('count',count),),proof='integer bounded-selection count')
    source=bound['iterable'];inside=Environment(environment)
    if getattr(shape(source),'_native_class_generator',False):
        source_kind=shape(source);element=model.generators.demand(plan,node,source,inside)
    else:
        source_kind=model.iterators.source(plan,node,source,('heap_selection',identity.name))
        element=model.iterators.demand(plan,node,Cell(source_kind),inside)
    site=SelectionCall(factory('list',(element,)),binding,element,bound['key'],source_kind)
    _sites(model)[(plan.index,id(node),identity.name)]=site
    key_kinds=[kind for kind in alternatives(shape(site.key))if kind!='none']if shape(site.key)is not None else[]
    if key_kinds and not isinstance(shape(element),EmptyType)and shape(element)is not None:
        callback=model.cell_for_kind(union_type(*key_kinds))
        site.callback=analyze_values(model.callable_cells,plan,node,callback,CallArguments((Argument(node),),()),[element],[],inside,identity=('heap_selection_key',identity.name))
    model.replace_environment(environment,model.join(environment,inside,node,('heap_selection',identity.name)))
    return site


def emit(emitter,node,identity,site,positional,keywords):
    from .native_classes import Expression,shape
    from .native_class_builtins import _error
    from .native_unions import union_kind,project
    from .native import _string
    wanted=shape(site.result)
    if site.error:return _error(emitter,node,wanted,_string(site.error)+'.to_owned()')
    values=iter(positional+[value for _,value in keywords])
    bound=site.binding.capture(lambda expression,parameter:next(values),defaults={'key':Expression('()','none')}).by_name
    key=bound['key']
    def selected(key):
        from .native_heap_selection_emit import emit_selected
        return emit_selected(emitter,node,identity,site,bound['n'],bound['iterable'],key,wanted)
    code=project(key.kind,key.code,lambda kind,text:selected(Expression('('+text+').clone()',kind)))if union_kind(key.kind)else selected(key)
    return Expression(code,wanted)
