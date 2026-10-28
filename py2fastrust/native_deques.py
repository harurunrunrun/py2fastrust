"""Exact builtin deques share typed element storage and ordered call lowering."""
import ast

from .call_semantics import FunctionSignature,CallBindingError
from .references import DequeConstructor,BuiltinIdentity,callable_reference
from .native_types import DequeType,deque_type,EmptyType,shared_payload,rust_type


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


def _collect(g,stream,owner,node,element,left=False):
    from .native import _Unsupported
    from .native_iterators import stream_item,TraceContext,_owned
    value=stream_item(g,stream)
    if not shared_payload(element):
        raise _Unsupported('deque elements require an identity-safe immutable payload; mutable/custom element handles and protocols are not implemented',node=node,types=(('element',element),),proof='typed deque element identity')
    action=g.at(f'{owner}.push_{"front"if left else"back"}({_owned(g,value,element)})',node)+';'
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
    from .native_constraint_lowering import facts_for
    from .native_constraints import native_kind
    from .native_types import EMPTY
    facts,site=facts_for(g,node)
    expected=facts.allocations.get(site) if facts is not None else None
    if isinstance(expected,DequeType):element=expected.element
    elif expected=='deque_int':element='int'
    elif stream is not None:
        from .native_iterators import stream_item
        element=stream_item(g,stream).kind
    else:element=EMPTY
    if not shared_payload(element):
        raise _Unsupported('deque elements require an identity-safe immutable payload; mutable/custom element handles and protocols are not implemented',node=node,types=(('element',element),),proof='typed deque element identity')
    kind=native_kind(DequeType(element),g.bits);g.register_type(kind)
    owner=g.temporary();lines.append(f'let mut {owner}=NativeDeque::<{rust_type(element)}>::new({maximum_code});')
    if stream is not None:
        if not stream.eager:lines.append(stream.begin)
        lines.append(_collect(g,stream,owner,node,element))
    g.has_deques=True
    return _Expression('{'+''.join(lines)+owner+'}',kind)


def extend(g,node,environment,*,plan=None):
    from .native import _Expression,_Unsupported
    from .native_stream_plans import context,ProducerKind
    from .native_sequence_storage import capture_owned
    if plan is None:
        try:plan=context(g,environment).method(node)
        except CallBindingError as error:raise _Unsupported(str(error),node=node)from error
    if plan is None:return None
    receiver=plan.receiver.captured
    if not deque_type(receiver.kind):return None
    storage=capture_owned(g,receiver,node.func.value,environment,mutates=True)
    lines=list(storage.setup)
    from .native_iterators import Planner
    operand=plan.invocation.binding['iterable'];planner=Planner(g)
    source_plan=context(g,environment).producer(operand.expression)
    same=(source_plan.kind is ProducerKind.VALUE and isinstance(operand.expression,ast.Name)
          and storage.binding_name is not None and operand.expression.id==storage.binding_name)
    if same:
        copied=g.temporary();lines.append(f'let {copied}={copy_code(g,receiver,node)};')
        stream=planner.lower(source_plan,environment,captured_value=_Expression(copied,receiver.kind))
        stream.owners=frozenset()
    else:stream=planner.lower(source_plan,environment)
    if storage.binding_name is not None and storage.binding_name in stream.owners:
        raise _Unsupported('extending this deque would mutate its active source iterator; identity-preserving mutation checks are not implemented for this storage',node=node,proof='deque iteration mutation tracking')
    lines.append(stream.setup)
    lines.append(stream.begin)
    lines.append(_collect(g,stream,f'({storage.mutable})',node,storage.element,left=node.func.attr=='extendleft'))
    if storage.binding_name is not None:
        from .native import _DequeInfo
        binding=environment[storage.binding_name];g.expression_mutations.append(binding)
        g.update_info(environment,storage.binding_name,g.binding(_Expression('',receiver.kind)))
    g.has_deques=True
    return _Expression('{'+''.join(lines)+'()}','none')


def try_expression(g,node,environment):
    from .native import _Expression
    from .native_types import NullableType
    from .native_sequence_plans import element_type
    if isinstance(node,ast.Call):
        if isinstance(callable_reference(g,node.func,environment),DequeConstructor):return constructor(g,node,environment)
        if (isinstance(node.func,ast.Attribute)and node.func.attr in {'extend','extendleft'}
                and deque_type(_kind(g,node.func.value,environment))):
            return extend(g,node,environment)
        identity=callable_reference(g,node.func,environment)
        if isinstance(identity,BuiltinIdentity)and identity.name in {'len','bool','str','repr'}and len(node.args)==1 and not node.keywords and deque_type(_kind(g,node.args[0],environment)):
            value=g.expression(node.args[0],environment);g.has_deques=True
            if identity.name=='len':return _Expression(_length(g,f'({value.code}).len()'),'int',value.length)
            if identity.name=='bool':return _Expression(f'!({value.code}).is_empty()','bool')
            return _Expression(f'NativeText::from({representation(g,value)})','str')
    if isinstance(node,ast.Attribute)and node.attr=='maxlen'and deque_type(_kind(g,node.value,environment)):
        value=g.expression(node.value,environment);g.has_deques=True
        return _Expression(f'({value.code}).maxlen.map(|value|{_length(g,"value")})',NullableType('int'))
    if isinstance(node,ast.Subscript)and not isinstance(node.slice,ast.Slice)and deque_type(_kind(g,node.value,environment)):
        value=g.expression(node.value,environment);index=g.expression(node.slice,environment)
        owner,offset=g.temporary(),g.temporary();binding=value.code if value.owned else f'&({value.code})'
        checked=g.at(f'native_deque_index({offset},{owner}.len())',node)
        code=f'{{let {owner}={binding};let {offset}={_ssize(g,index,node,index_error=True)};{g.coerce(_Expression(f'{owner}.values[{checked}]',element_type(value.kind),owned=False),element_type(value.kind))}}}'
        g.has_deques=True;return _Expression(code,element_type(value.kind))
    return None


def item_statement(g,node,environment):
    from .native import _Expression,_Unsupported,_DequeInfo
    from .native_sequence_storage import capture_owned
    from .native_sequence_plans import element_type
    deleting=isinstance(node,ast.Delete)
    if deleting:
        if len(node.targets)!=1:return None
        target=node.targets[0]
    elif isinstance(node,ast.AugAssign):target=node.target
    elif isinstance(node,ast.Assign)and len(node.targets)==1:target=node.targets[0]
    else:return None
    if not(isinstance(target,ast.Subscript)and not isinstance(target.slice,ast.Slice)
           and deque_type(_kind(g,target.value,environment))):return None
    lines=[]
    if isinstance(node,ast.Assign):
        value=g.expression(node.value,environment);item=g.temporary()
        element=element_type(_kind(g,target.value,environment))
        lines.append(f'let {item}={g.coerce(value,element)};')
    receiver=g.expression(target.value,environment)
    storage=capture_owned(g,receiver,target.value,environment,mutates=True)
    lines.extend(storage.setup)
    index=g.expression(target.slice,environment);offset=g.temporary()
    lines.append(f'let {offset}={_ssize(g,index,target,index_error=True)};')
    if isinstance(node,ast.AugAssign):
        old=g.temporary();position=g.at(f'native_deque_index({offset},({storage.read}).len())',target)
        lines.append(f'let {old}={g.coerce(_Expression(f"({storage.read}).values[{position}]",storage.element,owned=False),storage.element)};')
        right=g.expression(node.value,environment)
        value=g.binary(node.op,_Expression(old,storage.element),right,node);item=g.temporary()
        lines.append(f'let {item}={g.coerce(value,storage.element)};')
    position=g.at(f'native_deque_index({offset},({storage.read}).len())',target)
    checked=g.temporary();lines.append(f'let {checked}={position};')
    if deleting:lines.append(f'({storage.mutable}).values.remove({checked});')
    else:lines.append(f'({storage.mutable}).values[{checked}]={item};')
    if storage.binding_name is not None:
        binding=environment[storage.binding_name];g.expression_mutations.append(binding)
        g.update_info(environment,storage.binding_name,g.binding(_Expression('',receiver.kind)))
    g.has_deques=True
    return ''.join(lines),environment


def _equal(g,left,right):
    from .native_tuples import _equal as scalar_equal
    if isinstance(left.kind,EmptyType):return f'native_empty::<bool>({left.code})'
    if isinstance(right.kind,EmptyType):return f'native_empty::<bool>({right.code})'
    return scalar_equal(g,left,right)


def comparison(g,node,values,environment=None):
    from .native import _Expression,_Unsupported
    from .native_sequence_plans import element_type
    if not any(deque_type(value.kind)for value in values):return None
    names=[g.temporary()for value in values];captures=[];operands=(node.left,*node.comparators)
    for source,value,name in zip(operands,values,names):
        if deque_type(value.kind):
            from .native_container_reads import capture
            if environment is None and not value.owned:
                raise _Unsupported('capturing this deque comparison requires stable binding facts',node=node,proof='deque identity through later operand effects')
            read=capture(g,source,value,environment or {})
            captures.append((read.setup,read.owner))
        else:captures.append((f'let {name}=&({value.code});',f'(*{name})'))
    if len(node.ops)==1 and isinstance(node.ops[0],(ast.In,ast.NotIn))and deque_type(values[1].kind):
        from .native_tuples import _scalar
        if not _scalar(values[0].kind)and not isinstance(values[0].kind,EmptyType):
            raise _Unsupported('deque membership requires a proved identity-safe scalar equality operation',node=node,types=(('needle',values[0].kind),),proof='deque element equality protocol')
        item=g.temporary();key,queue=(part[1]for part in captures)
        equal=_equal(g,_Expression(f'(*{item})',element_type(values[1].kind),owned=False),_Expression(key,values[0].kind,owned=False))
        check=f'({queue}).iter().any(|{item}|{equal})'
        if isinstance(node.ops[0],ast.NotIn):check=f'!({check})'
        g.has_deques=True
        return _Expression('{'+''.join(part[0]for part in captures)+check+'}','bool')
    symbols={ast.Eq:'==',ast.NotEq:'!=',ast.Lt:'<',ast.LtE:'<=',ast.Gt:'>',ast.GtE:'>='}
    if any(type(operator)not in symbols for operator in node.ops):
        raise _Unsupported('deque identity needs shared identity-preserving object storage',node=node,proof='deque object identity')
    tail='true'
    for index in reversed(range(len(node.ops))):
        first,second=values[index:index+2];operator=node.ops[index];a,b=(captures[i][1]for i in(index,index+1))
        if first.kind==second.kind=='deque_int':check=f'({a}).values{symbols[type(operator)]}({b}).values'
        elif deque_type(first.kind)and deque_type(second.kind):
            x,y=g.temporary(),g.temporary()
            left=_Expression(f'(*{x})',element_type(first.kind),owned=False);right=_Expression(f'(*{y})',element_type(second.kind),owned=False)
            equal=_equal(g,left,right)
            if isinstance(operator,(ast.Eq,ast.NotEq)):
                check=f'({a}).len()==({b}).len()&&({a}).iter().zip(({b}).iter()).all(|({x},{y})|{equal})'
                if isinstance(operator,ast.NotEq):check=f'!({check})'
            else:
                from .native_comparisons import ordering
                order=(f'native_empty::<bool>({left.code})'if isinstance(left.kind,EmptyType)else
                       f'native_empty::<bool>({right.code})'if isinstance(right.kind,EmptyType)else ordering(g,left,right,operator,node))
                label=g.temporary()
                check=(f"'{label}:{{for({x},{y})in ({a}).iter().zip(({b}).iter()){{if !({equal}){{break '{label} {order};}}}}"
                       f'({a}).len(){symbols[type(operator)]}({b}).len()}}')
        elif isinstance(operator,(ast.Eq,ast.NotEq)):
            if deque_type(first.kind)or deque_type(second.kind):check=str(isinstance(operator,ast.NotEq)).lower()
            else:
                from .native_tuples import tuple_compare
                check=tuple_compare(g,_Expression(a,first.kind,owned=False),_Expression(b,second.kind,owned=False),operator,node)
        else:raise _Unsupported('ordering a deque against a different type needs a container/type-error comparator',node=node,types=(('left',first.kind),('right',second.kind)))
        tail='{'+captures[index+1][0]+f'({check})&&({tail})'+'}'
    g.has_deques=True
    return _Expression('{'+captures[0][0]+tail+'}','bool')


def lower(g,storage,method,bound,node,environment):
    from .native import _Expression,_Unsupported
    from .native_sequence_methods import _bound
    owner=f'({storage.mutable})';read=storage.read;name=method.name
    if name in {'append','appendleft','insert'}:
        value=bound['value']
        item=value.code if value.owned and value.kind==storage.element else g.coerce(value,storage.element)
        if name=='insert':code=g.at(f'{owner}.insert({_ssize(g,bound["index"],node)},{item})',node)
        else:code=g.at(f'{owner}.push_{"front"if name=="appendleft"else"back"}({item})',node)
    elif name in {'pop','popleft'}:
        code=g.at(f'{owner}.values.pop_{"front"if name=="popleft"else"back"}().ok_or_else(||String::from("IndexError: pop from an empty deque"))',node)
    elif name=='clear':code=f'{owner}.clear()'
    elif name=='reverse':code=f'{owner}.values.make_contiguous().reverse()'
    elif name=='rotate':
        amount=_ssize(g,bound['n'],node)if'n'in bound else'1_isize'
        code=f'{owner}.rotate({amount})'
    elif name=='copy':code=copy_code(g,_Expression(f'(*{read})',storage.kind,owned=False),node)
    elif name in {'count','index','remove'}:
        from .native_tuples import _scalar
        needle=bound['value'];item=g.temporary()
        if not _scalar(needle.kind):
            raise _Unsupported('deque search requires a proved identity-safe scalar equality operation',node=node,types=(('needle',needle.kind),),proof='deque element equality protocol')
        equal=_equal(g,_Expression(f'(*{item})',storage.element,owned=False),needle)
        if name=='count':code=_length(g,f'native_deque_count({read},|{item}|{equal})')
        elif name=='remove':code=g.at(f'native_deque_remove({owner},|{item}|{equal})',node)
        else:
            start=_bound(g,bound.get('start'),'0_i128');stop='None'if'stop'not in bound else f'Some({_bound(g,bound["stop"],None)})'
            code=_length(g,g.at(f'native_deque_search({read},{start},{stop},|{item}|{equal})',node))
    else:raise _Unsupported('this deque operation has no native lowering',node=node,operation=name)
    g.has_deques=True
    kind=storage.kind if name=='copy'else storage.element if name in {'pop','popleft'}else'int'if name in {'index','count'}else'none'
    return _Expression(code,kind)


def copy_code(g,value,node):
    if value.kind=='deque_int':return f'({value.code}).clone()'
    from .native import _Expression
    from .native_sequence_plans import element_type
    element=element_type(value.kind);item=g.temporary()
    cloned=g.coerce(_Expression(f'(*{item})',element,owned=False),element)
    owner=g.temporary();result=g.temporary()
    copied=g.at(f'native_deque_mapped_copy({owner},|{item}|{cloned})',node)
    return '{'+f'let {owner}=&({value.code});let {result}={copied};{result}'+'}'


def representation(g,value):
    # Capture before the generic helper's expected type can constrain a `?`
    # expression that already returns a borrowed optional-name value.
    owner=g.temporary()
    if value.kind=='deque_int':rendered=f'native_deque_repr({owner})'
    else:
        from .native import _Expression
        from .native_typed_lists import _representation
        from .native_sequence_plans import element_type
        item=g.temporary();element=_representation(g,_Expression(f'(*{item})',element_type(value.kind),owned=False),quoted=True)
        rendered=f'native_deque_repr_with({owner},|{item}|{element})'
    return '{'+f'let {owner}=&({value.code});'+rendered+'}'


HELPERS=r'''
fn native_deque_mapped_copy<T,F:FnMut(&T)->T>(source:&NativeDeque<T>,mut clone:F)->Result<NativeDeque<T>,String> {
    let mut result=NativeDeque::new(source.maxlen);
    result.values.try_reserve(source.len()).map_err(|_|"MemoryError".to_string())?;
    for item in source.iter(){result.values.push_back(clone(item));}Ok(result)
}
fn native_deque_repr_with<T,F:FnMut(&T)->String>(queue:&NativeDeque<T>,mut repr:F)->String {
    use std::fmt::Write as _;let mut result=String::from("deque([");
    for(index,item)in queue.iter().enumerate(){if index>0{result.push_str(", ");}result.push_str(&repr(item));}
    result.push(']');if let Some(maxlen)=queue.maxlen{write!(&mut result,", maxlen={}",maxlen).unwrap();}result.push(')');result
}

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
