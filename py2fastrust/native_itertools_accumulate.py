"""Prefix folds use the same typed value and captured-call planners."""
import ast

from .call_semantics import Argument,CallArguments
from .native_types import EmptyType,alternatives


def bind(positional,keywords):
    if len(positional)>2:
        return None,f'TypeError: accumulate() takes at most 2 positional arguments ({len(positional)} given)'
    values=dict(zip(('iterable','func'),positional))
    for name,value in keywords:
        if name not in {'iterable','func','initial'}:
            return None,f"TypeError: accumulate() got an unexpected keyword argument '{name}'"
        if name in values:
            return None,f"TypeError: argument for accumulate() given by name ('{name}') and position ({1 if name=='iterable'else 2})"
        values[name]=value
    if 'iterable'not in values:return None,"TypeError: accumulate() missing required argument 'iterable' (pos 1)"
    return [values['iterable'],values.get('func'),values.get('initial')],None


def analyze(model,plan,node,identity,positional,keywords,environment,*,factory):
    from .native_classes import Cell,shape
    from .native_itertools import ToolCall
    values,error=bind(positional,keywords)
    if error:return ToolCall(factory('none'),error=error)
    registry=model.iterators
    record=registry._record(plan,node,'itertools_accumulate')
    from .native_iterator_hints import ABSENT
    record.hint_protocol=ABSENT
    record.adapter=AccumulateState;record.tool='accumulate'
    if record.callback is None:record.callback=Cell()
    if not hasattr(record,'initial'):record.initial=Cell()
    registry._contribute(record.source,values[0],node)
    registry._contribute(record.callback,values[1]if values[1]is not None else Cell('none'),node)
    registry._contribute(record.initial,values[2]if values[2]is not None else Cell('none'),node)
    record.input_types=(registry.source(plan,node,values[0],('accumulate',0),environment=environment),)
    registry._contribute(record.element,record.input_types[0].record.element,node)
    for kind in alternatives(shape(record.initial)):
        if kind is not None and kind!='none':registry._contribute(record.element,model.cell_for_kind(kind),node)
    return ToolCall(factory(record.kind),record)


def emit(emitter,node,identity,call,positional,keywords):
    from .native_classes import Expression,shape
    from .native_unions import project,union_kind
    values,error=bind(positional,keywords);assert error is None
    record=call.iterator;record.emitted=True
    callback=values[1]if values[1]is not None else Expression('()','none')
    initial=values[2]if values[2]is not None else Expression('()','none')
    def branch(kind,code):
        owned='('+code+').clone()'if union_kind(initial.kind)else code
        return 'None'if kind=='none'else'Some('+emitter.coerce(Expression(owned,kind),shape(record.element),node)+')'
    initial_code=project(initial.kind,initial.code,branch)if union_kind(initial.kind)else branch(initial.kind,initial.code)
    total=emitter.fresh()
    source=emitter.model.iterators.construct(emitter,node,values[0],kind=record.input_types[0])
    code='{'+f'let {total}:Option<{emitter.rust_type(shape(record.element))}>={initial_code};'
    code+=f'Rc::new(RefCell::new(ClassIteratorState_{record.index}{{source:{source.code},callback:{callback.code},pending:{total}.is_some(),total:{total}}}))'+'}'
    return Expression(code,record.kind)


class AccumulateState:
    @staticmethod
    def owned(record):
        from .native_classes import shape
        return (*record.input_types,shape(record.callback),shape(record.initial),shape(record.element))

    @staticmethod
    def demand(registry,plan,node,record,environment,active):
        from .native_classes import Cell,Environment,shape
        from .native_aot_callables import analyze_values
        item=registry.demand(plan,node,Cell(record.input_types[0]),environment,active+(record.index,))
        registry._contribute(record.element,item,node)
        if isinstance(shape(item),EmptyType)or shape(item)is None:return record.element
        for kind in alternatives(shape(record.callback)):
            if kind is None:continue
            if kind=='none':
                result=registry.model.binary(plan,node,ast.Add(),record.element,item,
                    identity=('accumulate_add',record.index),environment=environment)
            else:
                inside=Environment(environment)
                metadata=CallArguments((Argument(record.node),Argument(record.node)),())
                site=analyze_values(registry.model.callable_cells,plan,node,
                    registry.model.cell_for_kind(kind),metadata,[record.element,item],[],inside,
                    identity=('accumulate_callback',record.index,kind))
                record.demands[(plan.index,id(node),kind)]=site
                registry.model.replace_environment(environment,registry.model.join(environment,inside,node,'accumulate_callback'))
                result=site.result
            registry._contribute(record.element,result,node)
        return record.element

    @staticmethod
    def may_call(registry,record,seen):
        from .native_classes import shape,InstanceType
        from .native_types import alternatives
        return (shape(record.callback)!='none'or any(isinstance(kind,InstanceType)for kind in alternatives(shape(record.element)))
                or registry.may_call(record.input_types[0],seen|{record.index}))

    @staticmethod
    def fields(emitter,record):
        from .native_classes import shape
        return (f'source:ClassIterator_{record.input_types[0].index},pending:bool,'
                f'total:Option<{emitter.rust_type(shape(record.element))}>,callback:{emitter.rust_type(shape(record.callback))}')

    @staticmethod
    def pull(registry,emitter,node,value,active):
        from .native_classes import ClassUnsupported,Expression,shape
        from .native_unions import project,union_kind
        from .native_aot_callables import emit_values
        record=value.kind.record;wanted=shape(record.element)
        state,source,item,previous,callback,result=(emitter.fresh()for _ in range(6))
        label='accumulate_pull_'+emitter.fresh()
        nested=registry.pull(emitter,node,Expression(source,record.input_types[0]),active+(record.index,))
        code="'"+label+':{'
        code+='{let mut '+state+'='+value.code+'.borrow_mut();if '+state+'.pending{'+state+'.pending=false;break \''+label+' '+state+'.total.clone();}}'
        code+='let '+source+'={'+value.code+'.borrow().source.clone()};'
        code+='let Some('+item+')=('+nested.code+')else{break \''+label+' None;};'
        if isinstance(nested.kind,EmptyType):return Expression('{'+code+'match '+item+'{}}}',wanted)
        code+='let ('+previous+','+callback+')={let '+state+'='+value.code+'.borrow();('+state+'.total.clone(),'+state+'.callback.clone())};'
        def branch(kind,code):
            if kind=='none':return emitter.binary(ast.Add(),Expression(previous+'.clone()',wanted),Expression(item,nested.kind),node,wanted,identity=('accumulate_add',record.index)).code
            site=record.demands.get((emitter.plan.index,id(node),kind))
            if site is None:raise ClassUnsupported(node,'the deferred accumulate callback has no matching typed demand proof',proof='deferred accumulate callback demand site')
            return emit_values(emitter,node,site,Expression("("+code+").clone()",kind),[Expression(previous+'.clone()',wanted),Expression(item,nested.kind)],[],wanted).code
        operation=project(shape(record.callback),callback,branch)if union_kind(shape(record.callback))else branch(shape(record.callback),callback)
        optional=registry._callback_result(emitter,Expression(operation,wanted))
        code+='let '+result+'=if let Some('+previous+')='+previous+'{let Some(value)=('+optional.code+')else{break \''+label+' None;};value}else{'+emitter.coerce(Expression(item,nested.kind),wanted,node)+'};'
        code+=value.code+'.borrow_mut().total=Some('+result+'.clone());Some('+result+')}'
        return Expression('{'+code+'}',wanted)
