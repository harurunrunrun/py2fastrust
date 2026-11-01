"""Shared enumerate state over the canonical typed source cursor."""
import ast

from .native_types import EmptyType


def bind(positional,keywords):
    total=len(positional)+len(keywords)
    if total>2:
        if not positional:return None,"TypeError: enumerate() missing required argument 'iterable'"
        return None,f'TypeError: enumerate() takes at most 2 arguments ({total} given)'
    values=dict(zip(('iterable','start'),positional))
    for name,value in keywords:
        if name not in {'iterable','start'}or name in values:
            return None,f"TypeError: '{name}' is an invalid keyword argument for enumerate()"
        values[name]=value
    if 'iterable'not in values:
        if keywords:return None,f"TypeError: '{keywords[0][0]}' is an invalid keyword argument for enumerate()"
        return None,"TypeError: enumerate() missing required argument 'iterable'"
    return (values['iterable'],values.get('start')),None


def contribute_element(registry,record,item,node):
    from .native_classes import Cell,shape
    if shape(item)is None:return
    value=Cell(shape(item))if isinstance(shape(item),EmptyType)else Cell('tuple',(Cell('int'),item))
    registry._contribute(record.element,value,node)


def analyze(model,plan,node,arguments,keywords,environment,*,factory):
    from .native_classes import Cell
    values,error=bind(arguments,keywords)
    if error:return factory('none')
    source,start=values;registry=model.iterators
    record=registry._record(plan,node,'enumerate')
    registry._contribute(record.source,source,node)
    record.input_type=registry.source(plan,node,source,('enumerate',0))
    if not hasattr(record,'index_start'):record.index_start=Cell()
    registry._contribute(record.index_start,Cell('int')if start is None else start,node)
    contribute_element(registry,record,record.input_type.record.element,node)
    return factory(record.kind)


def index_value(emitter,node,value):
    from .native_classes import Expression,domain
    from .native_unions import project,union_kind
    from .native_class_builtins import _type_name
    def branch(kind,text):
        if domain(kind)in {'int','bool','int_bool'}:
            return emitter.number(Expression('('+text+').clone()'if union_kind(value.kind)else text,kind))
        if isinstance(kind,EmptyType):return 'native_empty::<NativeInt>('+text+')'
        message='format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,Expression(text,kind),node)+')'
        return emitter.at('Err::<NativeInt,String>('+message+')',node)
    return project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code)


def emit(emitter,node,arguments,keywords,wanted):
    from .native_classes import Expression
    from .native import _string
    values,error=bind(arguments,list(keywords.items()))
    if error:return Expression(emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(error)+'.to_owned())',node),wanted)
    source,start=values;record=wanted.record;record.emitted=True
    start=Expression(emitter.literal(0),'int',0)if start is None else start
    index=emitter.fresh();cursor=emitter.fresh()
    # CP converts start before asking the source for its iterator.
    code='let '+index+'='+index_value(emitter,node,start)+';'
    constructed=emitter.model.iterators.construct(emitter,node,source,kind=record.input_type)
    code+='let '+cursor+'='+constructed.code+';'
    return Expression('{'+code+f'Rc::new(RefCell::new(ClassIteratorState_{record.index}{{source:{cursor},index:{index}}}))'+'}',wanted)


def pull(registry,emitter,node,value,active):
    from .native_classes import Expression,shape
    record=value.kind.record;kind=shape(record.element)
    source,item,state,index=(emitter.fresh()for _ in range(4));label='enumerate_pull_'+emitter.fresh()
    nested=registry.pull(emitter,node,Expression(source,record.input_type),active+(record.index,))
    code="'"+label+':{let '+source+'={'+value.code+'.borrow().source.clone()};'
    code+='let Some('+item+')=('+nested.code+')else{break \''+label+' None;};'
    if isinstance(nested.kind,EmptyType):return Expression('{'+code+'match '+item+'{}}}',kind)
    # A reentrant source pull can advance this very enumerator. Read the index
    # only after that pull returns, then increment once for the yielded item.
    code+='let '+index+'={let mut '+state+'='+value.code+'.borrow_mut();let '+index+'='+state+'.index.clone();'
    advanced=emitter.numeric.binary(ast.Add(),emitter.scalar(Expression(index+'.clone()','int')),
        emitter.scalar(Expression(emitter.literal(1),'int',1)),node)
    code+=state+'.index='+advanced.code+';'+index+'};Some(('+index+','+item+'))}'
    return Expression('{'+code+'}',kind)
