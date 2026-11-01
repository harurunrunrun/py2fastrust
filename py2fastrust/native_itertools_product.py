"""Cartesian products retain concrete immutable pools and native indices."""
from .native_types import alternatives


def analyze(model,plan,node,identity,positional,keywords,environment,*,factory):
    from .native_classes import Cell,Environment,shape
    from .native_types import EMPTY
    from .native_itertools import ToolCall
    if any(name!='repeat'for name,value in keywords):
        invalid=next(name for name,value in keywords if name!='repeat')
        return ToolCall(factory('none'),error=f"TypeError: product() got an unexpected keyword argument '{invalid}'")
    fixed_repeat=_fixed_repeat(model,node,keywords)
    if fixed_repeat is not None and fixed_repeat<0:
        return ToolCall(factory('none'),error='ValueError: repeat argument cannot be negative')
    registry=model.iterators;record=registry._record(plan,node,'itertools_product')
    record.adapter=ProductState;record.tool='product'
    if not hasattr(record,'pool_element'):record.pool_element=Cell()
    record.input_values=tuple(positional)
    inside=Environment(environment);sources=[]
    for index,value in enumerate(positional if fixed_repeat!=0 else()):
        if getattr(shape(value),'_native_class_generator',False):
            sources.append(shape(value));item=model.generators.demand(plan,node,value,inside)
        else:
            source=registry.source(plan,node,value,('product',index));sources.append(source)
            item=registry.demand(plan,node,Cell(source),inside)
        registry._contribute(record.pool_element,item,node)
    if not positional or fixed_repeat==0:registry._contribute(record.pool_element,Cell(EMPTY),node)
    record.input_types=tuple(sources)
    fixed_rank=None if fixed_repeat is None else len(positional)*fixed_repeat
    record.fixed_fields=(tuple(source.record.element for source in sources)*fixed_repeat
                         if fixed_rank is not None and fixed_rank<=64 else None)
    result=(Cell('tuple',record.fixed_fields)if record.fixed_fields is not None
            else Cell('tuple_sequence',(record.pool_element,)))
    registry._contribute(record.element,result,node)
    model.replace_environment(environment,model.join(environment,inside,node,'product_materialization'))
    model.materialized_tuple=True
    return ToolCall(factory(record.kind),record)


def _fixed_repeat(model,node,keywords):
    if not keywords:return 1
    from .literal_semantics import Literal,integer_policy
    if len(node.keywords)!=1 or node.keywords[0].arg!='repeat':return None
    literal=Literal.from_ast(node.keywords[0].value)
    if literal is None or literal.kind not in {'int','bool'}:return None
    bits=0 if model.integer=='bigint'else 64 if model.integer=='i64'else 128
    value=integer_policy(bits).normalize(literal.value)
    # Out-of-range structural arguments must retain the checked constructor.
    if not -(1<<63)<=value<(1<<63):return None
    return value


def repeat_count(emitter,node,value):
    from .native_classes import Expression,domain
    from .native_unions import project,union_kind
    from .native_class_builtins import _type_name
    def branch(kind,text):
        if domain(kind)not in {'int','bool','int_bool'}:
            message='format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,Expression(text,kind),node)+')'
            return emitter.at('Err::<usize,String>('+message+')',node)
        number=emitter.number(Expression(text,kind));temporary=emitter.fresh()
        converted='('+number+').to_i128()'if emitter.model.integer=='bigint'else'Some(('+number+') as i128)'
        error='"OverflowError: Python int too large to convert to C ssize_t".to_owned()'
        checked=emitter.at(converted+'.filter(|value|*value>=isize::MIN as i128&&*value<=isize::MAX as i128).ok_or_else(||'+error+')',node)
        negative=emitter.at('Err::<(),String>("ValueError: repeat argument cannot be negative".to_owned())',node)
        return '{let '+temporary+'='+checked+';if '+temporary+'<0{'+negative+';}'+temporary+' as usize}'
    return project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code)


def emit(emitter,node,identity,call,positional,keywords):
    from .native_classes import Expression,shape
    record=call.iterator;record.emitted=True
    repeat=dict(keywords).get('repeat')
    count=emitter.fresh();dimensions=emitter.fresh();pools=emitter.fresh();indices=emitter.fresh()
    element=shape(record.pool_element);rendered=emitter.rust_type(element)
    code='let '+count+'='+('1_usize'if repeat is None else repeat_count(emitter,node,repeat))+';'
    checked=emitter.at(f'{len(positional)}_usize.checked_mul({count}).filter(|value|*value<=isize::MAX as usize).ok_or_else(||"OverflowError: repeat argument too large".to_owned())',node)
    code+='let '+dimensions+'='+checked+';let mut '+pools+':Vec<Rc<Vec<'+rendered+'>>>=Vec::new();let mut '+indices+':Vec<usize>=Vec::new();'
    for target in (pools,indices):code+=emitter.at(target+'.try_reserve_exact('+dimensions+').map_err(|_|"MemoryError".to_owned())',node)+';'
    code+=indices+'.resize('+dimensions+',0);if '+count+'>0{'
    for value,source_kind in zip(positional,record.input_types):
        pool=emitter.fresh();code+='let mut '+pool+':Vec<'+rendered+'>=Vec::new();'
        def append(current,item):
            reserve=current.at(pool+'.try_reserve(1).map_err(|_|"MemoryError".to_owned())',node)
            return reserve+';'+pool+'.push('+current.coerce(item,element,node)+');'
        if getattr(value.kind,'_native_class_generator',False):
            code+=emitter.model.generators.consume(emitter,node,'eager_member',value,[value],{},'none',append_item=append).code+';'
        else:
            before,source=emitter.capture(emitter.model.iterators.construct(emitter,node,value,kind=source_kind));code+=before
            pulled=emitter.model.iterators.pull(emitter,node,source);item=emitter.fresh()
            code+='loop{let Some('+item+')=('+pulled.code+')else{break;};'+append(emitter,Expression(item,pulled.kind))+'}'
        code+=pools+'.push(Rc::new('+pool+'));'
    if positional:
        cursor=emitter.fresh()
        code+='for '+cursor+' in '+str(len(positional))+'..'+dimensions+'{let next='+pools+'['+cursor+'%'+str(len(positional))+'].clone();'+pools+'.push(next);}'
    code+='}'
    code+=f'Rc::new(RefCell::new(ClassIteratorState_{record.index}{{pools:{pools},indices:{indices},started:false,done:false}}))'
    return Expression('{'+code+'}',record.kind)


class ProductState:
    @staticmethod
    def owned(record):
        from .native_classes import shape
        return (shape(record.pool_element),)

    @staticmethod
    def demand(registry,plan,node,record,environment,active):return record.element

    @staticmethod
    def may_call(registry,record,seen):return False

    @staticmethod
    def fields(emitter,record):
        from .native_classes import shape
        return f'pools:Vec<Rc<Vec<{emitter.rust_type(shape(record.pool_element))}>>>,indices:Vec<usize>,started:bool,done:bool'

    @staticmethod
    def pull(registry,emitter,node,value,active):
        from .native_classes import Expression,shape
        record=value.kind.record;kind=shape(record.element)
        state,position,next_index,found,values=(emitter.fresh()for _ in range(5))
        label='product_pull_'+emitter.fresh()
        code="'"+label+':{let mut '+state+'='+value.code+'.borrow_mut();if '+state+'.done{break \''+label+' None;}'
        code+='if '+state+'.started{let mut '+found+'=false;for '+position+' in (0..'+state+'.indices.len()).rev(){'
        advanced=emitter.at(state+'.indices['+position+'].checked_add(1).ok_or_else(||"OverflowError: product iterator index overflow".to_owned())',node)
        code+='let '+next_index+'='+advanced+';if '+next_index+'<'+state+'.pools['+position+'].len(){'+state+'.indices['+position+']='+next_index+';for value in &mut '+state+'.indices[('+position+'+1)..]{*value=0;}'+found+'=true;break;}}'
        code+='if !'+found+'{'+state+'.done=true;break \''+label+' None;}}else{'+state+'.started=true;if '+state+'.pools.iter().any(|pool|pool.is_empty()){'+state+'.done=true;break \''+label+' None;}}'
        if record.fixed_fields is not None:
            from .native_types import tuple_code
            fields=[]
            for index,field in enumerate(record.fixed_fields):
                raw=state+'.pools['+str(index)+']['+state+'.indices['+str(index)+']]'
                fields.append(_project_pool(emitter,node,raw,shape(record.pool_element),shape(field)))
            return Expression('{'+code+'Some('+tuple_code(fields)+')}}',kind)
        code+='let mut '+values+'=Vec::new();'+emitter.at(values+'.try_reserve_exact('+state+'.indices.len()).map_err(|_|"MemoryError".to_owned())',node)+';'
        code+='for '+position+' in 0..'+state+'.indices.len(){'+values+'.push('+state+'.pools['+position+']['+state+'.indices['+position+']].clone());}Some(NativeTuple::from_vec('+values+'))}'
        return Expression('{'+code+'}',kind)


def _project_pool(emitter,node,text,source,wanted):
    """The immutable pool position retains its original constructor type."""
    from .native_classes import Expression
    from .native_unions import project,union_kind
    allowed=alternatives(wanted)
    def branch(kind,code):
        if kind=='int_bool'and kind not in allowed:
            number='int'if'int'in allowed else'bool'if'bool'in allowed else None
            if number is not None:
                variant='Int'if number=='int'else'Bool'
                decoded='match ('+code+').clone(){NativeScalar::'+variant+'(value)=>value,_=>unreachable!("pooled input violates its numeric constructor proof")}'
                return emitter.coerce(Expression(decoded,number),wanted,node)
        if kind not in allowed:return 'unreachable!("pooled input violates its constructor proof")'
        return emitter.coerce(Expression('('+code+').clone()',kind),wanted,node)
    return project(source,text,branch)if union_kind(source)else branch(source,text)
