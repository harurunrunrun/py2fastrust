"""Exact integer deques share one typed storage and ordered call lowering."""
import ast

from .call_semantics import FunctionSignature,CallBindingError
from .references import DequeConstructor,callable_reference


def _kind(g,node,environment):
    from .native import _Binding
    from .native_types import unmaybe
    from .native_sequence_storage import binding_name
    name=binding_name(g,node)
    binding=environment.get(name)if name is not None else None
    if isinstance(binding,_Binding):return unmaybe(binding.kind)
    from .native_constraint_lowering import facts_for
    facts,site=facts_for(g,node)
    return None if facts is None else facts.expressions.get(site)


def import_statement(g,node,environment):
    """Bind trusted imports in their actual scope; never infer from spelling."""
    from .native import _Unsupported
    from .native_module_calls import ModuleRef
    assigned=item_statement(g,node,environment)
    if assigned is not None:return assigned
    values=None
    if isinstance(node,ast.ImportFrom)and node.module=='collections'and not node.level:
        if not all(alias.name=='deque'for alias in node.names):return None
        values=[(alias.asname or alias.name,DequeConstructor(alias.asname or alias.name))for alias in node.names]
    elif isinstance(node,ast.Import)and all(alias.name=='collections'for alias in node.names):
        values=[(alias.asname or alias.name,ModuleRef('collections'))for alias in node.names]
    elif isinstance(node,ast.Assign)and isinstance(node.value,(ast.Name,ast.Attribute)):
        reference=callable_reference(g,node.value,environment)
        if not isinstance(reference,DequeConstructor):return None
        if not all(isinstance(target,ast.Name)for target in node.targets):raise _Unsupported
        values=[(target.id,reference)for target in node.targets]
    if values is None:return None
    if 'collections'not in g.trusted_imports:
        raise _Unsupported('deque import does not resolve to the trusted standard collections module',node=node,proof='trusted module identity')
    for name,value in values:
        if name in g.BUILTINS|{'__name__','__builtins__'}or name in g.iterating_lists:
            raise _Unsupported('deque import or alias would replace a protected binding',node=node,proof='lexical callable identity')
        environment[name]=value
    return '',environment


def _length(g,code):return f'({code}) as NativeInt'if g.bits else f'Int::from_i128(({code}) as i128)'


def _ssize(g,value,node,*,clamp=False,index_error=False):
    from .native import _Unsupported
    if value.kind not in {'int','bool','int_bool'}:
        raise _Unsupported('deque size/index requires a proved integer value',node=node,types=(('index',value.kind),))
    code=g.number(value)
    if clamp:
        return f'({code}) as i128'if g.bits else f'({code}).to_i128().unwrap_or_else(||if ({code}).is_negative(){{i128::MIN}}else{{i128::MAX}})'
    error="IndexError: cannot fit 'int' into an index-sized integer"if index_error else'OverflowError: Python int too large to convert to C ssize_t'
    from .native import _string
    number=f'Some(({code}) as i128)'if g.bits else f'({code}).to_i128()'
    return g.at(f'({number}).and_then(|value|isize::try_from(value).ok()).ok_or_else(||String::from({_string(error)}))',node)


def _source(g,node,environment):
    from .native_iterators import Planner
    return Planner(g).stream(node,environment)


def _collect(g,stream,owner,node,left=False):
    from .native import _Unsupported
    from .native_iterators import stream_item,TraceContext,_owned
    value=stream_item(g,stream)
    if value.kind!='int':
        raise _Unsupported('deque element storage currently requires proved integers',node=node,types=(('element',value.kind),),proof='integer deque element representation')
    action=g.at(f'{owner}.push_{"front"if left else"back"}({_owned(g,value,"int")})',node)+';'
    return stream.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))


def constructor(g,node,environment):
    from .native import _Expression,_Unsupported
    from .native_stream_plans import context
    signature=FunctionSignature.declaration(('iterable','maxlen'),default_names=('iterable','maxlen'))
    try:bound=context(g,environment).bind(context(g,environment).invocation(node),signature,(("iterable",None),("maxlen",None)))
    except CallBindingError as error:raise _Unsupported(str(error),node=node)from error
    lines=[];stream=None;maximum=None
    for operand in bound.explicit_order:
        if operand.parameter=='iterable':
            stream=_source(g,operand.expression,environment)
            lines.append(stream.setup)
            if stream.eager:lines.append(stream.begin)
        else:
            value=g.expression(operand.expression,environment);name=g.temporary()
            lines.append(f'let {name}={value.code};')
            maximum=_Expression(name,value.kind)
    maximum_code='None'
    if maximum is not None:
        from .native_unions import project
        def cap(kind,code):
            if kind=='none':return f'{{let _=&({code});None}}'
            value=_Expression(code,kind,owned=False)
            return f'Some({g.at(f"native_deque_maxlen({_ssize(g,value,node)})",node)})'
        maximum_code=project(maximum.kind,maximum.code,cap)
    owner=g.temporary();lines.append(f'let mut {owner}=NativeDeque::<NativeInt>::new({maximum_code});')
    if stream is not None:
        if not stream.eager:lines.append(stream.begin)
        lines.append(_collect(g,stream,owner,node))
    g.has_deques=True
    return _Expression('{'+''.join(lines)+owner+'}','deque_int')


def extend(g,node,environment,*,plan=None):
    from .native import _Expression,_Unsupported
    from .native_stream_plans import context,ProducerKind
    from .native_sequence_storage import capture_owned
    if plan is None:
        try:plan=context(g,environment).method(node)
        except CallBindingError as error:raise _Unsupported(str(error),node=node)from error
    if plan is None:return None
    receiver=plan.receiver.captured
    if receiver.kind!='deque_int':return None
    storage=capture_owned(g,receiver,node.func.value,environment,mutates=True)
    lines=list(storage.setup)
    from .native_iterators import Planner
    operand=plan.invocation.binding['iterable'];planner=Planner(g)
    source_plan=context(g,environment).producer(operand.expression)
    same=(source_plan.kind is ProducerKind.VALUE and isinstance(operand.expression,ast.Name)
          and storage.binding_name is not None and operand.expression.id==storage.binding_name)
    if same:
        copied=g.temporary();lines.append(f'let {copied}=({receiver.code}).clone();')
        stream=planner.lower(source_plan,environment,captured_value=_Expression(copied,'deque_int'))
        stream.owners=frozenset()
    else:stream=planner.lower(source_plan,environment)
    if storage.binding_name is not None and storage.binding_name in stream.owners:
        raise _Unsupported('extending this deque would mutate its active source iterator; identity-preserving mutation checks are not implemented for this storage',node=node,proof='deque iteration mutation tracking')
    lines.append(stream.setup)
    lines.append(stream.begin)
    lines.append(_collect(g,stream,f'({storage.mutable})',node,left=node.func.attr=='extendleft'))
    if storage.binding_name is not None:
        from .native import _DequeInfo
        binding=environment[storage.binding_name];g.expression_mutations.append(binding)
        g.update_info(environment,storage.binding_name,_DequeInfo(None))
    g.has_deques=True
    return _Expression('{'+''.join(lines)+'()}','none')


def try_expression(g,node,environment):
    from .native import _Expression
    from .native_types import NullableType
    if isinstance(node,ast.Call):
        if isinstance(callable_reference(g,node.func,environment),DequeConstructor):return constructor(g,node,environment)
        if (isinstance(node.func,ast.Attribute)and node.func.attr in {'extend','extendleft'}
                and _kind(g,node.func.value,environment)=='deque_int'):
            return extend(g,node,environment)
        if isinstance(node.func,ast.Name)and node.func.id in {'len','bool','str','repr'}and len(node.args)==1 and not node.keywords and _kind(g,node.args[0],environment)=='deque_int':
            value=g.expression(node.args[0],environment);g.has_deques=True
            if node.func.id=='len':return _Expression(_length(g,f'({value.code}).len()'),'int',value.length)
            if node.func.id=='bool':return _Expression(f'!({value.code}).is_empty()','bool')
            return _Expression(f'NativeText::from(native_deque_repr(&({value.code})))','str')
    if isinstance(node,ast.Attribute)and node.attr=='maxlen'and _kind(g,node.value,environment)=='deque_int':
        value=g.expression(node.value,environment);g.has_deques=True
        return _Expression(f'({value.code}).maxlen.map(|value|{_length(g,"value")})',NullableType('int'))
    if isinstance(node,ast.Subscript)and not isinstance(node.slice,ast.Slice)and _kind(g,node.value,environment)=='deque_int':
        value=g.expression(node.value,environment);index=g.expression(node.slice,environment)
        owner,offset=g.temporary(),g.temporary();binding=value.code if value.owned else f'&({value.code})'
        checked=g.at(f'native_deque_index({offset},{owner}.len())',node)
        code=f'{{let {owner}={binding};let {offset}={_ssize(g,index,node,index_error=True)};{owner}.values[{checked}].clone()}}'
        g.has_deques=True;return _Expression(code,'int')
    return None


def item_statement(g,node,environment):
    from .native import _Expression,_Unsupported,_DequeInfo
    from .native_sequence_storage import capture_owned
    deleting=isinstance(node,ast.Delete)
    if deleting:
        if len(node.targets)!=1:return None
        target=node.targets[0]
    elif isinstance(node,ast.AugAssign):target=node.target
    elif isinstance(node,ast.Assign)and len(node.targets)==1:target=node.targets[0]
    else:return None
    if not(isinstance(target,ast.Subscript)and not isinstance(target.slice,ast.Slice)
           and _kind(g,target.value,environment)=='deque_int'):return None
    lines=[]
    if isinstance(node,ast.Assign):
        value=g.expression(node.value,environment);item=g.temporary()
        if value.kind!='int':raise _Unsupported('deque item assignment requires a proved integer value',node=node,types=(('value',value.kind),))
        lines.append(f'let {item}={value.code};')
    receiver=g.expression(target.value,environment)
    storage=capture_owned(g,receiver,target.value,environment,mutates=True)
    lines.extend(storage.setup)
    index=g.expression(target.slice,environment);offset=g.temporary()
    lines.append(f'let {offset}={_ssize(g,index,target,index_error=True)};')
    if isinstance(node,ast.AugAssign):
        old=g.temporary();position=g.at(f'native_deque_index({offset},({storage.read}).len())',target)
        lines.append(f'let {old}=({storage.read}).values[{position}].clone();')
        right=g.expression(node.value,environment)
        value=g.binary(node.op,_Expression(old,'int'),right,node);item=g.temporary()
        if value.kind!='int':raise _Unsupported('deque augmented item assignment requires integer arithmetic',node=node,types=(('result',value.kind),))
        lines.append(f'let {item}={value.code};')
    position=g.at(f'native_deque_index({offset},({storage.read}).len())',target)
    checked=g.temporary();lines.append(f'let {checked}={position};')
    if deleting:lines.append(f'({storage.mutable}).values.remove({checked});')
    else:lines.append(f'({storage.mutable}).values[{checked}]={item};')
    if storage.binding_name is not None:
        binding=environment[storage.binding_name];g.expression_mutations.append(binding)
        g.update_info(environment,storage.binding_name,_DequeInfo(None))
    g.has_deques=True
    return ''.join(lines),environment


def comparison(g,node,values):
    from .native import _Expression,_Unsupported
    if not any(value.kind=='deque_int'for value in values):return None
    if len(node.ops)==1 and isinstance(node.ops[0],(ast.In,ast.NotIn))and values[1].kind=='deque_int':
        from .native_tuples import _equal,_scalar
        if not _scalar(values[0].kind):
            raise _Unsupported('deque membership requires a proved identity-safe scalar equality operation',node=node,types=(('needle',values[0].kind),),proof='deque element equality protocol')
        key,queue,item=g.temporary(),g.temporary(),g.temporary()
        needle=_Expression(f'(*{key})',values[0].kind,owned=False)
        equal=_equal(g,_Expression(f'(*{item})','int',owned=False),needle)
        check=f'{queue}.iter().any(|{item}|{equal})'
        if isinstance(node.ops[0],ast.NotIn):check=f'!({check})'
        g.has_deques=True
        return _Expression(f'{{let {key}=&({values[0].code});let {queue}=&({values[1].code});{check}}}','bool')
    symbols={ast.Eq:'==',ast.NotEq:'!=',ast.Lt:'<',ast.LtE:'<=',ast.Gt:'>',ast.GtE:'>='}
    if any(type(operator)not in symbols for operator in node.ops):
        raise _Unsupported('deque identity needs shared identity-preserving object storage',node=node,proof='deque object identity')
    names=[g.temporary()for value in values];tail='true'
    for index in reversed(range(len(node.ops))):
        first,second=values[index:index+2];operator=node.ops[index]
        if first.kind==second.kind=='deque_int':check=f'{names[index]}.values{symbols[type(operator)]}{names[index+1]}.values'
        elif isinstance(operator,(ast.Eq,ast.NotEq)):
            if first.kind=='deque_int'or second.kind=='deque_int':check=str(isinstance(operator,ast.NotEq)).lower()
            else:
                from .native_tuples import tuple_compare
                check=tuple_compare(g,_Expression(f'(*{names[index]})',first.kind,owned=False),_Expression(f'(*{names[index+1]})',second.kind,owned=False),operator,node)
        else:raise _Unsupported('ordering a deque against a different type needs a container/type-error comparator',node=node,types=(('left',first.kind),('right',second.kind)))
        tail=f'{{let {names[index+1]}=&({second.code});({check})&&({tail})}}'
    g.has_deques=True
    return _Expression(f'{{let {names[0]}=&({values[0].code});{tail}}}','bool')


def lower(g,storage,method,bound,node,environment):
    from .native import _Expression,_Unsupported
    from .native_sequence_methods import _bound
    owner=f'({storage.mutable})';read=storage.read;name=method.name
    if name in {'append','appendleft','insert'}:
        value=bound['value']
        if value.kind!='int':raise _Unsupported('deque element storage currently requires proved integers',node=node,types=(('value',value.kind),),proof='integer deque element representation')
        item=value.code if value.owned else g.coerce(value,'int')
        if name=='insert':code=g.at(f'{owner}.insert({_ssize(g,bound["index"],node)},{item})',node)
        else:code=g.at(f'{owner}.push_{"front"if name=="appendleft"else"back"}({item})',node)
    elif name in {'pop','popleft'}:
        code=g.at(f'{owner}.values.pop_{"front"if name=="popleft"else"back"}().ok_or_else(||String::from("IndexError: pop from an empty deque"))',node)
    elif name=='clear':code=f'{owner}.clear()'
    elif name=='reverse':code=f'{owner}.values.make_contiguous().reverse()'
    elif name=='rotate':
        amount=_ssize(g,bound['n'],node)if'n'in bound else'1_isize'
        code=f'{owner}.rotate({amount})'
    elif name=='copy':code=f'({read}).clone()'
    elif name in {'count','index','remove'}:
        from .native_tuples import _equal,_scalar
        needle=bound['value'];item=g.temporary()
        if not _scalar(needle.kind):
            raise _Unsupported('deque search requires a proved identity-safe scalar equality operation',node=node,types=(('needle',needle.kind),),proof='deque element equality protocol')
        equal=_equal(g,_Expression(f'(*{item})','int',owned=False),needle)
        if name=='count':code=_length(g,f'native_deque_count({read},|{item}|{equal})')
        elif name=='remove':code=g.at(f'native_deque_remove({owner},|{item}|{equal})',node)
        else:
            start=_bound(g,bound.get('start'),'0_i128');stop='None'if'stop'not in bound else f'Some({_bound(g,bound["stop"],None)})'
            code=_length(g,g.at(f'native_deque_search({read},{start},{stop},|{item}|{equal})',node))
    else:raise _Unsupported('this deque operation has no native lowering',node=node,operation=name)
    g.has_deques=True
    kind='deque_int'if name=='copy'else'int'if name in {'pop','popleft','index','count'}else'none'
    return _Expression(code,kind)


HELPERS=r'''
#[derive(Clone)]
struct NativeDeque<T> { values:std::collections::VecDeque<T>, maxlen:Option<usize> }
impl<T> NativeDeque<T> {
    fn new(maxlen:Option<usize>)->Self {Self {values:std::collections::VecDeque::new(),maxlen}}
    fn len(&self)->usize {self.values.len()}
    fn is_empty(&self)->bool {self.values.is_empty()}
    fn iter(&self)->std::collections::vec_deque::Iter<'_,T> {self.values.iter()}
    fn clear(&mut self){self.values.clear();}
    fn reserve_one(&mut self)->Result<(),String> {
        let length=self.len().checked_add(1).ok_or("MemoryError")?;
        if length>isize::MAX as usize{return Err("MemoryError".into());}
        self.values.try_reserve(1).map_err(|_|"MemoryError".to_string())
    }
    fn push_back(&mut self,value:T)->Result<(),String> {
        if self.maxlen==Some(0){return Ok(());}
        if self.maxlen==Some(self.len()){self.values.pop_front();}else{self.reserve_one()?;}
        self.values.push_back(value);Ok(())
    }
    fn push_front(&mut self,value:T)->Result<(),String> {
        if self.maxlen==Some(0){return Ok(());}
        if self.maxlen==Some(self.len()){self.values.pop_back();}else{self.reserve_one()?;}
        self.values.push_front(value);Ok(())
    }
    fn insert(&mut self,index:isize,value:T)->Result<(),String> {
        if self.maxlen==Some(self.len()){return Err("IndexError: deque already at its maximum size".into());}
        let length=self.len() as i128;let index=index as i128;
        let index=if index<0{index.saturating_add(length).max(0)}else{index.min(length)}as usize;
        self.reserve_one()?;self.values.insert(index,value);Ok(())
    }
    fn rotate(&mut self,amount:isize){
        if self.is_empty(){return;}
        let shift=(amount as i128).rem_euclid(self.len()as i128)as usize;
        self.values.rotate_right(shift);
    }
}
impl<T> IntoIterator for NativeDeque<T> {
    type Item=T;type IntoIter=std::collections::vec_deque::IntoIter<T>;
    fn into_iter(self)->Self::IntoIter {self.values.into_iter()}
}
fn native_deque_maxlen(value:isize)->Result<usize,String> {
    usize::try_from(value).map_err(|_|"ValueError: maxlen must be non-negative".to_string())
}
fn native_deque_index(index:isize,length:usize)->Result<usize,String> {
    let index=index as i128;let length=length as i128;
    let index=if index<0{index+length}else{index};
    usize::try_from(index).ok().filter(|&index|index<length as usize)
        .ok_or_else(||"IndexError: deque index out of range".to_string())
}
fn native_deque_count<T,F:FnMut(&T)->bool>(queue:&NativeDeque<T>,mut equal:F)->usize {
    queue.iter().filter(|value|equal(value)).count()
}
fn native_deque_search<T,F:FnMut(&T)->bool>(queue:&NativeDeque<T>,start:i128,stop:Option<i128>,mut equal:F)->Result<usize,String> {
    let length=queue.len()as i128;
    let bound=|value:i128|if value<0{value.saturating_add(length).max(0)}else{value.min(length)}as usize;
    let start=bound(start);let stop=stop.map(bound).unwrap_or(queue.len());
    for index in start..stop{if equal(&queue.values[index]){return Ok(index);}}
    Err("ValueError: deque.index(x): x not in deque".into())
}
fn native_deque_remove<T,F:FnMut(&T)->bool>(queue:&mut NativeDeque<T>,mut equal:F)->Result<(),String> {
    let index=queue.iter().position(|value|equal(value)).ok_or_else(||"ValueError: deque.remove(x): x not in deque".to_string())?;
    queue.values.remove(index);Ok(())
}
fn native_deque_repr<T:std::fmt::Display>(queue:&NativeDeque<T>)->String {
    use std::fmt::Write as _;
    let mut result=String::from("deque([");
    for (index,value)in queue.iter().enumerate(){if index>0{result.push_str(", ");}write!(&mut result,"{}",value).unwrap();}
    result.push(']');if let Some(maxlen)=queue.maxlen{write!(&mut result,", maxlen={}",maxlen).unwrap();}result.push(')');result
}
'''
