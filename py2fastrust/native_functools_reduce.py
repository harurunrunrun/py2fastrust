"""Captured eager reductions use typed source pulls and native callback calls."""
import ast
from dataclasses import dataclass

from .call_semantics import Argument,CallArguments
from .native_types import EmptyType,TupleType,alternatives


@dataclass
class ReduceCall:
    result:object
    total:object=None
    source:object=None
    callback:object=None
    invoke:object=None
    error:str|None=None
    seed:object=None
    once:bool=False


def bind(positional,keywords):
    keywords=list(keywords)
    if len(positional)<2:return None,f'TypeError: reduce() takes at least 2 positional arguments ({len(positional)} given)'
    count=len(positional)+len(keywords)
    if count>3:return None,f'TypeError: reduce() takes at most 3 arguments ({count} given)'
    for key,_ in keywords:
        if key!='initial':return None,f"TypeError: reduce() got an unexpected keyword argument '{key}'"
    initial=positional[2]if len(positional)==3 else dict(keywords).get('initial')
    return (positional[0],positional[1],initial),None


def _count(node,metadata):
    if not isinstance(node,ast.Call):return None
    if (len(metadata.positional)!=len(node.args)or len(metadata.keywords)!=len(node.keywords)
            or any(item.expression is not source for item,source in zip(metadata.positional,node.args))
            or any(item.name!=source.arg or item.expression is not source.value for item,source in zip(metadata.keywords,node.keywords))):return None
    source=metadata.positional[1].expression
    if isinstance(source,(ast.List,ast.Tuple))and not any(isinstance(item,ast.Starred)for item in source.elts):return len(source.elts)
    return None


class FunctoolsAdapter:
    NAMES=frozenset({'reduce','cmp_to_key'})
    TYPES=frozenset()
    EAGER_ARGUMENTS={'reduce':frozenset({1})}

    @staticmethod
    def analyze(model,plan,node,identity,metadata,positional,keywords,environment,*,factory):
        if identity.name=='cmp_to_key':
            from .native_cmp_keys import analyze
            return analyze(model,plan,node,identity,metadata,positional,keywords,environment,factory=factory)
        from .native_classes import Cell,Environment,shape
        from .native_aot_callables import analyze_values
        from .native_callback_effects import register
        values,error=bind(positional,keywords)
        result=factory()
        if error:
            model.contribute(result,Cell('none'),node)
            return ReduceCall(result,error=error)
        callback,source,initial=values
        total=model.cell(plan,node,identity=('reduce_accumulator',identity))
        inside=Environment(environment)
        count=_count(node,metadata)
        if count==0 and source.root().tag=='list':
            from .native_types import EMPTY
            model.contribute(source.root().args[0],Cell(EMPTY),node)
        if getattr(shape(source),'_native_class_generator',False):
            source_kind=shape(source);item=model.generators.demand(plan,node,source,inside)
        else:
            source_kind=model.iterators.source(plan,node,source,('reduce_source',identity),environment=inside)
            item=model.iterators.demand(plan,node,Cell(source_kind),inside)
        empty=isinstance(shape(item),EmptyType)or count==0
        seed=item if initial is None else initial
        once=count==(2 if initial is None else 1)
        model.contribute(total,seed,node)
        invoke=None
        if not empty and (initial is not None or count!=1)and shape(item)is not None:
            arguments=CallArguments((Argument(node),Argument(node)),())
            invoke=analyze_values(model.callable_cells,plan,node,callback,arguments,
                [seed if once else total,item],[],inside,identity=('reduce_callback',identity))
            model.contribute(total,invoke.result,node)
        if empty and initial is None:model.contribute(result,Cell('none'),node)
        else:
            seed_visible=(count in (None,0)if initial is not None else count in (None,1))
            if seed_visible:model.contribute(result,seed,node)
            if invoke is not None:model.contribute(result,invoke.result,node)
        model.replace_environment(environment,model.join(environment,inside,node,'reduce_consumption'))
        sites=getattr(model,'reduce_sites',None)
        if sites is None:
            sites={};model.reduce_sites=sites
            register(model,lambda plan,node:bool(getattr(model,'reduce_sites',{}).get((plan.index,id(node)))and
                model.reduce_sites[(plan.index,id(node))].invoke is not None))
            from .native_owned_kinds import register as register_kinds
            register_kinds(model,lambda:(shape(site.total)for site in model.reduce_sites.values()if site.total is not None))
        record=ReduceCall(result,total,source_kind,callback,invoke,seed=seed,once=once)
        sites[(plan.index,id(node))]=record
        return record

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        if identity.name=='cmp_to_key':
            from .native_cmp_keys import emit
            return emit(emitter,node,identity,record,positional,keywords)
        from .native import _string
        from .native_classes import Expression,shape,ClassUnsupported
        from .native_aot_callables import emit_values
        wanted=shape(record.result)
        if record.error is not None:
            return Expression(emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(record.error)+'.to_owned())',node),wanted)
        values,error=bind(positional,keywords);assert error is None
        callback,source,initial=values
        total=emitter.fresh();kind=shape(record.total)
        beginning='None'if initial is None else'Some('+emitter.coerce(initial,kind,node)+')'
        code='let mut '+total+':Option<'+emitter.rust_type(kind)+'>='+beginning+';'

        def append(current,item):
            if isinstance(item.kind,EmptyType):return 'match '+item.code+'{};'
            if record.invoke is None:return total+'=Some('+current.coerce(item,kind,node)+');'
            previous=current.fresh()
            previous_value=Expression(previous,kind)
            if record.once:
                previous_value=Expression(_narrow(current,node,previous_value,shape(record.seed)),shape(record.seed))
            result=emit_values(current,node,record.invoke,Expression('('+callback.code+').clone()',callback.kind),
                [previous_value,item],[],kind)
            if initial is not None:
                return 'let '+previous+'='+total+'.take().unwrap();'+total+'=Some('+result.code+');'
            return (total+'=Some(if let Some('+previous+')='+total+'.take(){'+result.code+'}else{'+
                current.coerce(item,kind,node)+'});')

        if getattr(source.kind,'_native_class_generator',False):
            code+=emitter.model.generators.consume(emitter,node,'eager_member',source,[source],{},'none',append_item=append).code+';'
        else:
            constructed=emitter.model.iterators.construct(emitter,node,source,kind=record.source)
            acquisition='(||Ok::<'+emitter.rust_type(constructed.kind)+',NativeError>('+constructed.code+'))()'
            acquisition+='.map_err(|mut error|{if error.message=="TypeError"||error.message.starts_with("TypeError:"){error.message="TypeError: reduce() arg 2 must support iteration".to_owned();}error})?'
            before,cursor=emitter.capture(Expression(acquisition,constructed.kind));code+=before
            pulled=emitter.model.iterators.pull(emitter,node,cursor);item=emitter.fresh()
            code+='loop{let Some('+item+')=('+pulled.code+')else{break;};'+append(emitter,Expression(item,pulled.kind))+'}'
        last=emitter.at(total+'.ok_or_else(||"TypeError: reduce() of empty iterable with no initial value".to_owned())',node)
        code+=_narrow(emitter,node,Expression(last,kind),wanted)
        return Expression('{'+code+'}',wanted)


def _narrow(emitter,node,value,wanted):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    from .native_types import tuple_code
    if isinstance(value.kind,EmptyType):return 'native_empty::<'+emitter.rust_type(wanted)+'>('+value.code+')'
    if value.kind==wanted:return emitter.coerce(value,wanted,node)
    if isinstance(value.kind,TupleType)and isinstance(wanted,TupleType)and len(value.kind.fields)==len(wanted.fields):
        temporary=emitter.fresh()
        fields=[_narrow(emitter,node,Expression(temporary+'.'+str(index)+'.clone()',old),new)
                for index,(old,new)in enumerate(zip(value.kind.fields,wanted.fields))]
        return '{let '+temporary+'='+value.code+';'+tuple_code(fields)+'}'
    allowed=alternatives(wanted)
    before,value=emitter.capture(value)
    def branch(kind,code):
        if kind=='int_bool'and kind not in allowed:
            selected='int'if'int'in allowed else'bool'if'bool'in allowed else None
            if selected is not None:
                variant='Int'if selected=='int'else'Bool'
                decoded='match ('+code+').clone(){NativeScalar::'+variant+'(value)=>value,_=>unreachable!("fold result violates proved callback cardinality")}'
                return emitter.coerce(Expression(decoded,selected),wanted,node)
        if kind not in allowed:return 'unreachable!("fold result violates proved callback cardinality")'
        return emitter.coerce(Expression('('+code+').clone()',kind),wanted,node)
    return '{'+before+(project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code))+'}'
