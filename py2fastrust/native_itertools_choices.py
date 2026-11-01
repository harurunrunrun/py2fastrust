"""Lazy positional choices over one eagerly captured native input pool."""
from .native_types import alternatives

NAMES=frozenset({'combinations','permutations','combinations_with_replacement'})


def bind(name,positional,keywords,default):
    from .call_semantics import FunctionSignature
    keywords=list(keywords)
    count=len(positional)+len(keywords)
    if count>2:return None,f'TypeError: {name}() takes at most 2 arguments ({count} given)'
    names={key for key,_ in keywords}
    for index,key in enumerate(('iterable','r')):
        if name=='permutations'and key=='r':continue
        if len(positional)<=index and key not in names:
            return None,f"TypeError: {name}() missing required argument '{key}' (pos {index+1})"
    for index,key in enumerate(('iterable','r')):
        if len(positional)>index and key in names:
            return None,f"TypeError: argument for {name}() given by name ('{key}') and position ({index+1})"
    for key,_ in keywords:
        if key not in {'iterable','r'}:return None,f"TypeError: {name}() got an unexpected keyword argument '{key}'"
    signature=FunctionSignature.declaration(('iterable','r'),default_names=('r',)if name=='permutations'else())
    return signature.bind(positional,keywords,{'r':default}if name=='permutations'else{}).by_name,None


def _fixed_rank(model,node,metadata,name):
    import ast
    from .literal_semantics import Literal,integer_policy
    if not isinstance(node,ast.Call):return None
    if (len(metadata.positional)!=len(node.args)or len(metadata.keywords)!=len(node.keywords)
            or any(item.expression is not source for item,source in zip(metadata.positional,node.args))
            or any(item.name!=source.arg or item.expression is not source.value for item,source in zip(metadata.keywords,node.keywords))):return None
    bound,error=bind(name,metadata.positional,((item.name,item)for item in metadata.keywords),None)
    if error or bound['r']is None:return None
    literal=Literal.from_ast(bound['r'].expression)
    if literal is None or literal.kind not in {'int','bool'}:return None
    value=integer_policy({'i64':64,'i128':128,'bigint':0}[model.integer]).normalize(literal.value)
    return value if 0<=value<=64 else None


def analyze(model,plan,node,identity,metadata,positional,keywords,environment,*,factory):
    from .native_classes import Cell,Environment,shape,domain
    from .native_types import EMPTY
    from .native_itertools import ToolCall
    bound,error=bind(identity.name,positional,keywords,Cell('none'))
    if error:return ToolCall(factory('none'),error=error)
    if shape(bound['r'])is None and not model.final:return ToolCall(factory())
    registry=model.iterators;record=registry._record(plan,node,'itertools_'+identity.name)
    record.adapter=ChoiceState;record.tool=identity.name
    if not hasattr(record,'pool_element'):record.pool_element=Cell()
    rank_kinds=alternatives(shape(bound['r']))
    record.skip_pool=(identity.name!='permutations'and rank_kinds and
                      all(domain(kind)not in {'int','bool','int_bool'}for kind in rank_kinds))
    inside=Environment(environment)
    if record.skip_pool:
        record.input_type=None;registry._contribute(record.pool_element,Cell(EMPTY),node)
    else:
        value=bound['iterable']
        if getattr(shape(value),'_native_class_generator',False):
            record.input_type=shape(value);item=model.generators.demand(plan,node,value,inside)
        else:
            record.input_type=registry.source(plan,node,value,('choice_pool',record.tool))
            item=registry.demand(plan,node,Cell(record.input_type),inside)
        registry._contribute(record.pool_element,item,node)
    rank=_fixed_rank(model,node,metadata,identity.name)
    record.fixed_fields=None if rank is None else tuple(record.pool_element for _ in range(rank))
    result=Cell('tuple_sequence',(record.pool_element,))if rank is None else Cell('tuple',record.fixed_fields)
    registry._contribute(record.element,result,node)
    model.replace_environment(environment,model.join(environment,inside,node,'choice_materialization'))
    model.materialized_tuple=True
    return ToolCall(factory(record.kind),record)


def _rank(emitter,node,value,name,*,error_kind=None):
    from .native_classes import Expression,domain
    from .native_class_builtins import _type_name
    from .native_unions import project,union_kind
    def branch(kind,code):
        if name=='permutations'and kind=='none':return 'None'
        if domain(kind)not in {'int','bool','int_bool'}:
            message=('"TypeError: Expected int as r".to_owned()'if name=='permutations'else
                'format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,Expression(code,kind),node)+')')
            error_type='Option<i128>'if error_kind is None else emitter.rust_type(error_kind)
            return emitter.at('Err::<'+error_type+',String>('+message+')',node)
        number=emitter.number(Expression(code,kind))
        converted='('+number+').to_i128()'if emitter.model.integer=='bigint'else'Some(('+number+') as i128)'
        checked=emitter.at(converted+'.filter(|value|*value>=isize::MIN as i128&&*value<=isize::MAX as i128).ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned())',node)
        return 'Some('+checked+')'
    return project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code)


def emit(emitter,node,identity,call,positional,keywords):
    from .native_classes import Expression,shape
    from .native_itertools_product import collect_pool
    record=call.iterator;record.emitted=True
    bound,error=bind(identity.name,positional,keywords.items()if isinstance(keywords,dict)else keywords,Expression('()','none'))
    assert error is None
    if record.skip_pool:return Expression(_rank(emitter,node,bound['r'],identity.name,error_kind=record.kind),record.kind)
    rank,pool,indices,cycles=(emitter.fresh()for _ in range(4));code=''
    if identity.name!='permutations':code+='let '+rank+'='+_rank(emitter,node,bound['r'],identity.name)+';'
    code+=collect_pool(emitter,node,bound['iterable'],record.input_type,shape(record.pool_element),pool)
    if identity.name=='permutations':code+='let '+rank+'='+_rank(emitter,node,bound['r'],identity.name)+';'
    code+='let '+rank+'='+rank+'.unwrap_or('+pool+'.len() as i128);if '+rank+'<0{'+emitter.at('Err::<(),String>("ValueError: r must be non-negative".to_owned())',node)+';}let '+rank+'='+rank+' as usize;'
    count=pool+'.len()'if identity.name=='permutations'else rank
    code+='let mut '+indices+':Vec<usize>=Vec::new();'+emitter.at(indices+'.try_reserve_exact('+count+').map_err(|_|"MemoryError".to_owned())',node)+';'
    if identity.name=='permutations':
        code+='let mut '+cycles+':Vec<usize>=Vec::new();'+emitter.at(cycles+'.try_reserve_exact('+rank+').map_err(|_|"MemoryError".to_owned())',node)+';'
        code+='if '+rank+'<='+pool+'.len(){'+indices+'.extend(0..'+pool+'.len());'+cycles+'.extend((0..'+rank+').map(|i|'+pool+'.len()-i));}'
    elif identity.name=='combinations':code+='if '+rank+'<='+pool+'.len(){'+indices+'.extend(0..'+rank+');}'
    else:code+=indices+'.resize('+rank+',0);'
    done=(rank+'>'+pool+'.len()'if identity.name!='combinations_with_replacement'else rank+'>0&&'+pool+'.is_empty()')
    code+='let done='+done+';'+f'Rc::new(RefCell::new(ClassIteratorState_{record.index}'+'{pool:Rc::new('+pool+'),indices:'+indices+',rank:'+rank+',started:false,done'+(',cycles:'+cycles if identity.name=='permutations'else'')+'}))'
    return Expression('{'+code+'}',record.kind)


class ChoiceState:
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
        return ('pool:Rc<Vec<'+emitter.rust_type(shape(record.pool_element))+'>>,indices:Vec<usize>,rank:usize,started:bool,done:bool'+
                (',cycles:Vec<usize>'if record.tool=='permutations'else''))

    @staticmethod
    def pull(registry,emitter,node,value,active):
        from .native_classes import Expression,shape
        from .native_types import tuple_code
        record=value.kind.record;kind=shape(record.element)
        state,position,found,values=(emitter.fresh()for _ in range(4))
        label='choice_pull_'+emitter.fresh()
        code="'"+label+':{let mut '+state+'='+value.code+'.borrow_mut();if '+state+'.done{break \''+label+' None;}'
        code+='if '+state+'.started{let mut '+found+'=false;'
        if record.tool=='permutations':
            code+='for '+position+' in (0..'+state+'.rank).rev(){'+state+'.cycles['+position+']-=1;if '+state+'.cycles['+position+']==0{'+state+'.indices['+position+'..].rotate_left(1);'+state+'.cycles['+position+']='+state+'.pool.len()-'+position+';}else{let last='+state+'.pool.len()-'+state+'.cycles['+position+'];'+state+'.indices.swap('+position+',last);'+found+'=true;break;}}'
        elif record.tool=='combinations':
            code+='for '+position+' in (0..'+state+'.rank).rev(){if '+state+'.indices['+position+']<'+position+'+('+state+'.pool.len()-'+state+'.rank){'+state+'.indices['+position+']+=1;for j in ('+position+'+1)..'+state+'.rank{'+state+'.indices[j]='+state+'.indices[j-1]+1;}'+found+'=true;break;}}'
        else:
            code+='for '+position+' in (0..'+state+'.rank).rev(){if '+state+'.indices['+position+']<'+state+'.pool.len()-1{let next='+state+'.indices['+position+']+1;for j in '+position+'..'+state+'.rank{'+state+'.indices[j]=next;}'+found+'=true;break;}}'
        code+='if !'+found+'{'+state+'.done=true;break \''+label+' None;}}else{'+state+'.started=true;}'
        if record.fixed_fields is not None:
            fields=[state+'.pool['+state+'.indices['+str(index)+']].clone()'for index in range(len(record.fixed_fields))]
            ending=tuple_code(fields)
        else:
            code+='let mut '+values+'=Vec::new();'+emitter.at(values+'.try_reserve_exact('+state+'.rank).map_err(|_|"MemoryError".to_owned())',node)+';for '+position+' in 0..'+state+'.rank{'+values+'.push('+state+'.pool['+state+'.indices['+position+']].clone());}'
            ending='NativeTuple::from_vec('+values+')'
        return Expression(code+'Some('+ending+')}',kind)
