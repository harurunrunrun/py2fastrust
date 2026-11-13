"""Stable sorting over captured typed values and original compiled callbacks."""
import ast
from dataclasses import dataclass,field

from .call_semantics import Argument,CallArguments


@dataclass
class SortSite:
    key:object
    element:object
    callback:object=None
    source_kind:object=None
    error:str|None=None
    comparators:dict=field(default_factory=dict)
    rich_comparisons:dict=field(default_factory=dict)


def requires_frames(unit,analysis):
    from .references import BuiltinIdentity
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for facts in analysis.scopes.values():
        for site,call in facts.calls.items():
            if BuiltinIdentity('sorted')not in call.identity.alternatives:continue
            node=nodes.get(site)
            if isinstance(node,ast.Call)and any(isinstance(argument,ast.GeneratorExp)for argument in node.args):return True
    return False


def _sites(model):
    if not hasattr(model,'sorting_sites'):model.sorting_sites={}
    return model.sorting_sites


def _bind(arguments,keywords,*,method):
    values=dict(keywords)
    if arguments:
        if method:return None,"TypeError: sort() takes no positional arguments"
        if len(arguments)>1:return None,f'TypeError: sorted expected 1 argument, got {len(arguments)}'
    elif not method:return None,'TypeError: sorted expected 1 argument, got 0'
    for name in values:
        if name not in {'key','reverse'}:
            return None,f"TypeError: sort() got an unexpected keyword argument {name!r}"
    return values,None


def _analyze(model,plan,node,source,key,environment,*,method,error=None):
    from .native_classes import Cell,shape,Environment
    from .native_types import alternatives,EmptyType
    kind=None
    if method:element=source.root().args[0]
    else:
        from .native_immediate_generators import GeneratorType
        if isinstance(shape(source),GeneratorType):
            kind=shape(source)
            element=model.generators.demand(plan,node,source,environment)
        else:
            element=model.mappings.sorted_element(source,key,node)
            if element is None:
                kind=model.iterators.source(plan,node,source,environment=environment)
                element=model.iterators.demand(plan,node,Cell(kind),environment)
    site=SortSite(key,element,source_kind=kind,error=error)
    _sites(model)[(plan.index,id(node))]=site
    if not error and not isinstance(shape(element),EmptyType)and any(value!='none'for value in alternatives(shape(key))):
        from .native_aot_callables import analyze_values
        inside=Environment(environment)
        from .native_cmp_keys import CmpKeyType,analyze_comparison
        ordinary=model.cell(plan,node,identity=('sorting_ordinary_key',method))
        has_ordinary=False
        for branch in alternatives(shape(key)):
            if isinstance(branch,CmpKeyType):site.comparators[branch]=analyze_comparison(model,plan,node,branch,element,inside)
            elif branch!='none':
                cell=Cell('function',branch.targets)if getattr(branch,'_native_function_reference',False)else Cell(branch)
                model.contribute(ordinary,cell,node);has_ordinary=True
        if has_ordinary:
            site.callback=analyze_values(model.callable_cells,plan,node,ordinary,
                CallArguments((Argument(node),),()),[element],[],inside,identity=('sorting_key',method))
        model.replace_environment(environment,model.join(environment,inside,node,'sorting_key'))
    from .native_rich_sorting import analyze as rich_comparison
    rich_comparison(model,plan,node,site,environment,method=method)
    return site


def analyze_builtin(model,plan,node,arguments,keywords,environment,*,factory):
    from .native_classes import Cell
    values,error=_bind(arguments,keywords,method=False)
    if error and len(arguments)!=1:
        _sites(model)[(plan.index,id(node))]=SortSite(Cell('none'),Cell(),error=error)
        return factory('none')
    site=_analyze(model,plan,node,arguments[0],(values or{}).get('key',Cell('none')),environment,method=False,error=error)
    return factory('list',(site.element,))


def analyze_method(model,plan,node,receiver,arguments,keywords,environment):
    from .native_classes import Cell
    values,error=_bind(arguments,keywords,method=True)
    _analyze(model,plan,node,receiver,(values or{}).get('key',Cell('none')),environment,method=True,error=error)
    return model.cell(plan,node,'none')


def _error(emitter,node,message,kind):
    from .native import _string
    return emitter.at(f'Err::<{emitter.rust_type(kind)},String>({_string(message)}.to_owned())',node)


def _ordering(emitter,left,right,node):
    from .native_classes import ClassUnsupported,Expression,domain
    from .native_types import TupleType,ListType
    from .native_unions import union_kind,project
    from .native_class_builtins import _type_name
    if union_kind(left.kind):
        return project(left.kind,left.code,lambda kind,code:_ordering(emitter,Expression(f'({code}).clone()',kind),right,node))
    if union_kind(right.kind):
        return project(right.kind,right.code,lambda kind,code:_ordering(emitter,left,Expression(f'({code}).clone()',kind),node))
    a,b=left.kind,right.kind
    if a=='float'or b=='float':
        raise ClassUnsupported(node,'sorting binary64 values needs Python stable less-than behavior for NaN and its exact comparison schedule; a total Rust floating ordering would change Python results and is not implemented',types=(('left key',a),('right key',b)),proof='Python NaN-aware stable ordering')
    if a in {'int','bool','int_bool'}and b in {'int','bool','int_bool'}:
        return f'Ok(({emitter.number(left)}).cmp(&({emitter.number(right)})))'
    if a==b and a in {'str','bytes'}:return f'Ok(({left.code}).cmp(&({right.code})))'
    from .native_types import TupleSequenceType
    if isinstance(a,(TupleType,TupleSequenceType))and isinstance(b,(TupleType,TupleSequenceType))and(isinstance(a,TupleSequenceType)or isinstance(b,TupleSequenceType)):
        from .native_variadic import sorted_order
        return sorted_order(emitter,left,right,node,_ordering)
    if isinstance(a,TupleType)and isinstance(b,TupleType):
        result=f'Ok({len(a.fields)}_usize.cmp(&{len(b.fields)}_usize))'
        for index in reversed(range(min(len(a.fields),len(b.fields)))):
            x=Expression(f'({left.code}).{index}',a.fields[index]);y=Expression(f'({right.code}).{index}',b.fields[index])
            equal=emitter.comparison(ast.Eq(),x,y,node)
            result=f'if {equal}{{{result}}}else{{{_ordering(emitter,x,y,node)}}}'
        return '{'+result+'}'
    if isinstance(a,ListType)and isinstance(b,ListType):
        x,y,first,second,result,owner_a,owner_b=(emitter.fresh()for _ in range(7))
        lx=Expression(x+'.clone()',a.element);ry=Expression(y+'.clone()',b.element)
        equal=emitter.comparison(ast.Eq(),lx,ry,node)
        nested=_ordering(emitter,lx,ry,node)
        return ('{'+f'let {owner_a}=({left.code}).clone();let {owner_b}=({right.code}).clone();let {first}={owner_a}.borrow();let {second}={owner_b}.borrow();'
            f'let mut {result}=Ok({first}.len().cmp(&{second}.len()));'
            f'for ({x},{y})in {first}.iter().zip({second}.iter()){{if !({equal}){{{result}={nested};break;}}}}{result}'+'}')
    if domain(a)=='object'or domain(b)=='object':
        for kind in (a,b):
            if domain(kind)=='object'and any(name in emitter.model.classes[kind.name].methods for name in ('__lt__','__gt__')):
                raise ClassUnsupported(node,'sorting these keys requires captured rich-comparison method calls and reflected dispatch, which this typed sorting comparator does not yet implement',types=(('left key',a),('right key',b)),proof='rich comparison dispatch during stable sorting')
    return 'Err(format!("TypeError: \'<\' not supported between instances of \'{}\' and \'{}\'",'+_type_name(emitter,left,node)+','+_type_name(emitter,right,node)+'))'


def _sort(emitter,node,values,element,reverse,key,site):
    from .native_classes import Expression,shape
    from .native_types import EmptyType,alternatives
    from .native_unions import union_kind,project
    if isinstance(element,EmptyType):return ''
    if union_kind(key.kind):
        return project(key.kind,key.code,lambda kind,code:'{'+_sort(emitter,node,values,element,reverse,Expression(f'({code}).clone()',kind),site)+'}')+';'
    if getattr(key.kind,'_native_cmp_key',False):
        from .native_cmp_keys import sort
        return sort(emitter,node,values,element,reverse,key,site)
    first,second,order,error=(emitter.fresh()for _ in range(4))
    key_kind=element if key.kind=='none'else shape(site.callback.result)
    if key_kind is None:
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'the sorting key result has no solved stored type',proof='solved captured sorting callback result')
    decorated=values
    code=''
    if key.kind!='none':
        from .native_aot_callables import emit_values
        decorated,item=(emitter.fresh()for _ in range(2))
        value=emit_values(emitter,node,site.callback,Expression(key.code+'.clone()',key.kind),[Expression(item+'.clone()',element)],[],key_kind)
        code+=f'let mut {decorated}=Vec::<({emitter.rust_type(key_kind)},{emitter.rust_type(element)})>::new();'
        code+=emitter.at(f'{decorated}.try_reserve({values}.len()).map_err(|_|"MemoryError: cannot allocate sorting keys".to_owned())',node)+';'
        code+=f'for {item} in {values}.iter(){{{decorated}.push(({value.code},{item}.clone()));}}'
    if key.kind in site.rich_comparisons:
        from .native_rich_sorting import emit as rich_comparison
        code+=rich_comparison(emitter,node,decorated,key_kind,reverse,key,site)
        if key.kind!='none':code+=f'{values}={decorated}.into_iter().map(|(_,value)|value).collect();'
        return code
    prefix='.0'if key.kind!='none'else''
    comparison=_ordering(emitter,Expression(f'(*{first}){prefix}',key_kind),Expression(f'(*{second}){prefix}',key_kind),node)
    code+=f'let mut {error}:Option<String>=None;'
    code+=f'if std::mem::size_of::<{emitter.rust_type(key_kind)}>()==0&&{decorated}.len()>1{{let {first}=&{decorated}[1];let {second}=&{decorated}[0];let {order}:Result<std::cmp::Ordering,String>=(||{{{comparison}}})();if let Err(value)={order}{{{error}=Some(value);}}}}'
    code+=f'{decorated}.sort_by(|{first},{second}|{{if {error}.is_some(){{return std::cmp::Ordering::Equal;}}let {order}:Result<std::cmp::Ordering,String>=(||{{{comparison}}})();'
    code+=f'match {order}{{Ok(value)=>if {reverse}{{value.reverse()}}else{{value}},Err(value)=>{{{error}=Some(value);std::cmp::Ordering::Equal}}}}}});'
    if key.kind!='none':code+=f'{values}={decorated}.into_iter().map(|(_,value)|value).collect();'
    code+=f'if let Some(error)={error}{{'+emitter.at('Err::<(),String>(error)',node)+';}'
    return code


def emit_builtin(emitter,node,arguments,keywords,wanted):
    from .native_classes import Expression,shape
    from .native_types import ListType,alternatives
    site=_sites(emitter.model)[(emitter.plan.index,id(node))]
    if site.error and site.source_kind is None:return Expression(_error(emitter,node,site.error,wanted),wanted)
    key=keywords.get('key',Expression('()','none'));reverse=keywords.get('reverse',Expression('false','bool'))
    values,direction,current=(emitter.fresh()for _ in range(3))
    element=shape(site.element)
    from .native_classes import domain
    from .native_class_mappings import mapping_kind
    from .native_immediate_generators import GeneratorType
    if isinstance(arguments[0].kind,GeneratorType):
        def append(e,item):
            reserve=e.at(f'{values}.try_reserve(1).map_err(|_|"MemoryError: cannot allocate list".to_owned())',node)
            return reserve+';'+f'{values}.push({e.coerce(item,element,node)});'
        consumed=emitter.model.generators.consume(emitter,node,'sorted',arguments[0],[],{},'none',append_item=append)
        materialize=f'let mut {values}=Vec::<{emitter.rust_type(element)}>::new();'+consumed.code+';'
    elif all(mapping_kind(kind)for kind in alternatives(arguments[0].kind)):
        materialize=f'let mut {values}='+emitter.model.mappings.sorted_values(emitter,node,arguments[0],element)+';'
    elif domain(arguments[0].kind)=='list'and arguments[0].kind.element==element:
        materialize=f'let mut {values}={arguments[0].code}.borrow().clone();'
    else:
        source=emitter.model.iterators.construct(emitter,node,arguments[0],kind=site.source_kind)
        setup,source=emitter.capture(source);pulled=emitter.model.iterators.pull(emitter,node,source)
        item=emitter.coerce(Expression(current,pulled.kind),element,node)
        materialize=(setup+f'let mut {values}=Vec::<{emitter.rust_type(element)}>::new();'
            f'loop{{let Some({current})=({pulled.code})else{{break;}};{values}.push({item});}}')
    body=(materialize+
        ( _error(emitter,node,site.error,'none')+';'if site.error else'')+f'let {direction}={emitter.truth(reverse)};'+
        _sort(emitter,node,values,element,direction,key,site)+f'Ok(class_list({values}))')
    from .native_class_calls import entry_result
    if entry_result(emitter.model,emitter.plan):code='( ||->Result<'+emitter.rust_type(ListType(element))+',NativeError>{'+body+'})()?'
    else:code='(async{'+body+'}).await?'
    return emitter.encoded(code,ListType(element),wanted,node)


def emit_method(emitter,node):
    from .native_classes import Expression,shape
    from .call_semantics import normalize_call
    site=_sites(emitter.model)[(emitter.plan.index,id(node))]
    setup,receiver=emitter.capture(emitter.expression(node.func.value))
    arguments=[];keywords={}
    metadata=normalize_call(node)
    for argument in metadata.evaluation_order:
        before,value=emitter.capture(emitter.expression(argument.expression));setup+=before
        if argument.name is None:arguments.append(value)
        else:keywords[argument.name]=value
    if site.error:return Expression('{'+setup+_error(emitter,node,site.error,'none')+'}','none')
    key=keywords.get('key',Expression('()','none'));reverse=keywords.get('reverse',Expression('false','bool'))
    values,direction,result,modified=(emitter.fresh()for _ in range(4))
    element=shape(site.element)
    # No RefCell borrow spans a user callback. The detached vector is restored
    # after both key failure and successful sorting before propagating errors.
    from .native_class_calls import entry_result
    operation=_sort(emitter,node,values,element,direction,key,site)+'Ok::<(),NativeError>(())'
    operation=('(||->Result<(),NativeError>{'+operation+'})()'if entry_result(emitter.model,emitter.plan)else'(async{'+operation+'}).await')
    body=(f'let {direction}={emitter.truth(reverse)};let mut {values}=std::mem::take(&mut *{receiver.code}.borrow_mut());'
        f'let {result}='+operation+';'
        f'let {modified}={receiver.code}.borrow().capacity()!=0;*{receiver.code}.borrow_mut()={values};'
        f'{result}?;if {modified}{{'+_error(emitter,node,'ValueError: list modified during sort','none')+';}Ok(())')
    operation=('(||->Result<(),NativeError>{'+body+'})()?'if entry_result(emitter.model,emitter.plan)else'(async{'+body+'}).await?')
    return Expression('{'+setup+operation+'}','none')
