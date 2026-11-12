"""Concrete lazy states for canonical itertools exports."""
from dataclasses import dataclass

from .native_types import EMPTY,EmptyType


NAMES=frozenset({'repeat','chain','islice','pairwise','accumulate','product','combinations','permutations','combinations_with_replacement'})


@dataclass(frozen=True)
class ToolCall:
    result:object
    iterator:object=None
    error:str|None=None


def _bind(name,positional,keywords):
    """Bind values already evaluated by the shared captured-call binder."""
    keywords=list(keywords)
    if name!='repeat':
        if keywords:return None,f'TypeError: {name}() takes no keyword arguments'
        if name=='pairwise'and len(positional)!=1:
            return None,f'TypeError: pairwise expected 1 argument, got {len(positional)}'
        if name=='islice'and not 2<=len(positional)<=4:
            return None,f'TypeError: islice expected {"at least 2"if len(positional)<2 else"at most 4"} arguments, got {len(positional)}'
        return list(positional),None
    if len(positional)>2:return None,f'TypeError: repeat() takes at most 2 arguments ({len(positional)} given)'
    values=dict(zip(('object','times'),positional))
    for key,value in keywords:
        if key not in {'object','times'}:return None,f"TypeError: repeat() got an unexpected keyword argument '{key}'"
        if key in values:return None,f"TypeError: argument for repeat() given by name ('{key}') and position ({1 if key=='object'else 2})"
        values[key]=value
    if 'object'not in values:return None,"TypeError: repeat() missing required argument 'object' (pos 1)"
    return [values['object'],values.get('times')],None


class ItertoolsAdapter:
    NAMES=NAMES
    TYPES=NAMES
    EAGER_ARGUMENTS={'product':None,'combinations':frozenset({0}),'permutations':frozenset({0}),'combinations_with_replacement':frozenset({0})}
    EAGER_KEYWORDS={name:frozenset({'iterable'})for name in ('combinations','permutations','combinations_with_replacement')}

    @staticmethod
    def match_type(emitter,node,value,name):
        from .native_classes import Expression,domain
        from .native_unions import project,union_kind
        if union_kind(value.kind):
            return project(value.kind,value.code,lambda kind,code:
                ItertoolsAdapter.match_type(emitter,node,Expression(code,kind),name))
        return str(domain(value.kind)=="iterator"and value.kind.record.operation=="itertools_"+name).lower()

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        from .native_classes import Cell,shape
        if identity.name in {'combinations','permutations','combinations_with_replacement'}:
            from .native_itertools_choices import analyze
            return analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,factory=factory)
        if identity.name=='product':
            from .native_itertools_product import analyze
            return analyze(model,plan,node,identity,positional,keywords,environment,factory=factory)
        if identity.name=='accumulate':
            from .native_itertools_accumulate import analyze
            return analyze(model,plan,node,identity,positional,keywords,environment,factory=factory)
        values,error=_bind(identity.name,positional,keywords)
        if error:return ToolCall(factory("none"),error=error)
        registry=model.iterators
        record=registry._record(plan,node,'itertools_'+identity.name)
        record.adapter=ItertoolsState
        record.tool=identity.name
        record.input_values=tuple(values if record.tool=='chain'else values[:1])
        if record.tool=='repeat':
            registry._contribute(record.source,values[0],node)
            registry._contribute(record.element,values[0],node)
        else:
            record.input_types=tuple(registry.source(plan,node,source,('itertools',record.tool,index),environment=environment)
                                     for index,source in enumerate(record.input_values))
            if record.tool=='chain':
                if not values:registry._contribute(record.element,Cell(EMPTY),node)
                for source in record.input_types:registry._contribute(record.element,source.record.element,node)
            elif record.tool=='pairwise':
                item=record.input_types[0].record.element
                if isinstance(shape(item),EmptyType):result=Cell(EMPTY)
                else:result=Cell('tuple',(item,item))
                registry._contribute(record.element,result,node)
            else:registry._contribute(record.element,record.input_types[0].record.element,node)
        return ToolCall(factory(record.kind),record)

    @staticmethod
    def emit(emitter,node,identity,call,positional,keywords):
        from .native_classes import Expression,shape
        from .native import _string
        if call.error is not None:
            return Expression(emitter.at(f'Err::<{emitter.rust_type(shape(call.result))},String>({_string(call.error)}.into())',node),shape(call.result))
        if identity.name in {'combinations','permutations','combinations_with_replacement'}:
            from .native_itertools_choices import emit
            return emit(emitter,node,identity,call,positional,keywords)
        if identity.name=='product':
            from .native_itertools_product import emit
            return emit(emitter,node,identity,call,positional,keywords)
        if identity.name=='accumulate':
            from .native_itertools_accumulate import emit
            return emit(emitter,node,identity,call,positional,keywords)
        values,error=_bind(identity.name,positional,keywords)
        assert error is None
        record=call.iterator;record.emitted=True
        fields=[];setup=''
        if record.tool=='repeat':
            fields=['value:'+values[0].code,'remaining:'+("None"if values[1]is None else'Some('+_index(emitter,node,values[1],'repeat')+')')]
        elif record.tool=='chain':
            for source in record.input_types:source.record.emitted=True
            for index,value in enumerate(values):
                fields.extend((f'original_{index}:Some({value.code})',f'active_{index}:None'))
            fields.extend(('index:0','done:false'))
        else:
            if record.tool=='islice':
                start=values[1]if len(values)>2 else None
                stop=values[2]if len(values)>2 else values[1]
                step=values[3]if len(values)>3 else None
                for name,value in (('start',start),('stop',stop),('step',step)):
                    temporary=emitter.fresh()
                    code=('None'if name=='stop'else'1'if name=='step'else'0')if value is None else _index(emitter,node,value,name)
                    setup+=f'let {temporary}={code};'
                    fields.append(('next'if name=='start'else name)+':'+temporary)
                fields.append('index:0')
            cursor=emitter.model.iterators.construct(emitter,node,values[0],kind=record.input_types[0])
            fields.append('source:Some('+cursor.code+')')
            if record.tool=='pairwise':fields.append('previous:None')
        return Expression('{'+setup+f'Rc::new(RefCell::new(ClassIteratorState_{record.index}{{'+','.join(fields)+'}))}',record.kind)


def _index(emitter,node,value,role):
    """Validate structural counters without normalizing them to target integers."""
    from .native_classes import Expression,domain
    from .native_unions import project,union_kind
    from .native import _string
    from .native_class_builtins import _type_name
    if role=='repeat':message=None
    elif role=='step':message='ValueError: Step for islice() must be a positive integer or None.'
    else:message=f'ValueError: {"Stop argument"if role=="stop"else"Indices"} for islice() must be None or an integer: 0 <= x <= sys.maxsize.'
    def branch(kind,code):
        if kind=='none'and role!='repeat':return 'None'if role=='stop'else'1'if role=='step'else'0'
        if domain(kind)not in {'int','bool','int_bool'}:
            error=(_string(message)+'.to_owned()'if message is not None else
                   'format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,Expression(code,kind),node)+')')
            wanted='Option<usize>'if role=='stop'else'usize'
            return emitter.at(f'Err::<{wanted},String>({error})',node)
        number=emitter.number(Expression(code,kind));temporary=emitter.fresh()
        convert='('+number+').to_i128()'if emitter.model.integer=='bigint'else'Some(('+number+') as i128)'
        if role=='repeat':
            error='"OverflowError: Python int too large to convert to C ssize_t".to_owned()'
            result=f'if {temporary}<0{{0}}else{{{temporary} as usize}}'
        else:
            error=_string(message)+'.to_owned()'
            result=f'Some({temporary} as usize)'if role=='stop'else f'{temporary} as usize'
        lower='isize::MIN as i128'if role=='repeat'else'1'if role=='step'else'0'
        valid=f'*{temporary}>={lower}&&*{temporary}<=isize::MAX as i128'
        checked=emitter.at(f'{convert}.filter(|{temporary}|{valid}).ok_or_else(||{error})',node)
        return '{'+f'let {temporary}={checked};'+result+'}'
    return project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code)


class ItertoolsState:
    @staticmethod
    def owned(record):
        from .native_classes import shape
        if record.tool=='repeat':return (shape(record.source),)
        return (*record.input_types,*(shape(value)for value in record.input_values))

    @staticmethod
    def demand(registry,plan,node,record,environment,active):
        from .native_classes import Cell
        for source in record.input_types:
            registry.demand(plan,node,Cell(source),environment,active+(record.index,))
        return record.element

    @staticmethod
    def may_call(registry,record,seen):
        return any(registry.may_call(source,seen|{record.index})for source in record.input_types)

    @staticmethod
    def fields(emitter,record):
        from .native_classes import shape
        if record.tool=='repeat':return f'value:{emitter.rust_type(shape(record.source))},remaining:Option<usize>'
        if record.tool=='chain':
            fields=['index:usize','done:bool']
            for index,(value,source)in enumerate(zip(record.input_values,record.input_types)):
                fields.extend((f'original_{index}:Option<{emitter.rust_type(shape(value))}>',f'active_{index}:Option<ClassIterator_{source.index}>'))
            return ','.join(fields)
        fields=f'source:Option<ClassIterator_{record.input_types[0].index}>'
        if record.tool=='pairwise':return fields+f',previous:Option<{emitter.rust_type(shape(record.input_types[0].record.element))}>'
        return fields+',index:usize,next:usize,stop:Option<usize>,step:usize'

    @staticmethod
    def pull(registry,emitter,node,value,active):
        from .native_classes import Expression,shape
        record=value.kind.record;kind=shape(record.element)
        state=emitter.fresh()
        if record.tool=='repeat':
            return Expression('{let mut '+state+'='+value.code+'.borrow_mut();match '+state+'.remaining{Some(0)=>None,Some(n)=>{'+state+'.remaining=Some(n-1);Some('+state+'.value.clone())},None=>Some('+state+'.value.clone())}}',kind)
        if record.tool=='chain':return ItertoolsState._chain(registry,emitter,node,value,active)
        source=emitter.fresh();current=emitter.fresh();label='itertools_pull_'+emitter.fresh()
        item_kind=shape(record.input_types[0].record.element)
        nested=registry.pull(emitter,node,Expression(source,record.input_types[0]),active+(record.index,))
        code="'"+label+':{let Some('+source+')=({'+value.code+'.borrow().source.clone()})else{break \''+label+' None;};'
        cleanup='{let mut state='+value.code+'.borrow_mut();state.source=None;'+('state.previous=None;'if record.tool=='pairwise'else'')+'}'
        from .native_iterator_stop_policy import cleanup_pull
        nested=cleanup_pull(emitter,nested,cleanup)
        exhausted=cleanup+'break \''+label+' None;'
        if record.tool=='pairwise':
            previous=emitter.fresh()
            code+='let '+previous+'={'+value.code+'.borrow().previous.clone()};let '+previous+'=if let Some(value)='+previous+'{value}else{let Some(value)=('+nested.code+')else{'+exhausted+'};'+value.code+'.borrow_mut().previous=Some(value.clone());value};'
            code+='let Some('+current+')=('+nested.code+')else{'+exhausted+'};'+value.code+'.borrow_mut().previous=Some('+current+'.clone());'
            ending='match '+current+'{}'if isinstance(kind,EmptyType)else'Some(('+previous+','+current+'))'
            return Expression('{'+code+ending+'}}',kind)
        target=emitter.fresh();index=emitter.fresh()
        code+='loop{let ('+index+','+target+')={let '+state+'='+value.code+'.borrow();('+state+'.index,'+state+'.next)};if '+index+'>='+target+'{break;}let Some('+current+')=('+nested.code+')else{'+exhausted+'};'
        advance=emitter.at(f'{state}.index.checked_add(1).ok_or_else(||"OverflowError: islice iterator index overflow".to_owned())',node)
        code+='{let mut '+state+'='+value.code+'.borrow_mut();'+state+'.index='+advance+';}}'
        code+='if {let '+state+'='+value.code+'.borrow();'+state+'.stop.is_some_and(|stop|'+state+'.index>=stop)}{'+exhausted+'}'
        code+='let Some('+current+')=('+nested.code+')else{'+exhausted+'};{let mut '+state+'='+value.code+'.borrow_mut();'
        increment=emitter.at(f'{state}.index.checked_add(1).ok_or_else(||"OverflowError: islice iterator index overflow".to_owned())',node)
        code+=state+'.index='+increment+';'+state+'.next='+state+'.next.checked_add('+state+'.step).unwrap_or(isize::MAX as usize).min('+state+'.stop.unwrap_or(isize::MAX as usize));}'
        return Expression('{'+code+'Some('+current+')}}',kind)

    @staticmethod
    def _chain(registry,emitter,node,value,active):
        from .native_classes import Expression,shape
        record=value.kind.record;kind=shape(record.element)
        label='chain_pull_'+emitter.fresh();code="'"+label+':loop{if '+value.code+'.borrow().done{break None;}let index='+value.code+'.borrow().index;match index{'
        arms=[]
        for index,source_kind in enumerate(record.input_types):
            cursor=emitter.fresh();raw=emitter.fresh();item=emitter.fresh()
            constructed=registry.construct(emitter,node,Expression(raw,shape(record.input_values[index])),kind=source_kind)
            pulled=registry.pull(emitter,node,Expression(cursor,source_kind),active+(record.index,),stop='clear')
            converted=emitter.coerce(Expression(item,pulled.kind),kind,node)
            body='let '+cursor+'={'+value.code+f'.borrow().active_{index}.clone()'+'};let '+cursor+'=if let Some(value)='+cursor+'{value}else{'
            body+='let '+raw+'={let mut state='+value.code+f'.borrow_mut();state.done=true;state.original_{index}.take().unwrap()'+'};let cursor='+constructed.code+';{let mut state='+value.code+f'.borrow_mut();state.done=false;state.active_{index}=Some(cursor.clone());'+'}cursor};'
            body+='if let Some('+item+')='+pulled.code+'{break \''+label+' Some('+converted+');}{let mut state='+value.code+f'.borrow_mut();state.index+=1;state.active_{index}=None;'+'}'
            arms.append(str(index)+'=>{'+body+'}')
        code+=','.join(arms+["_=>{"+value.code+'.borrow_mut().done=true;break None;}'])+'}}'
        return Expression('{'+code+'}',kind)
