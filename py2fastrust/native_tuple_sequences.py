"""Immutable homogeneous tuples materialized from the common typed pull plan."""
import ast

from .native_types import TupleSequenceType,TupleType,immutable,rust_type


HELPERS=r'''
#[derive(Clone)]
struct NativeTuple<T>(Option<std::rc::Rc<Vec<T>>>);
impl<T> NativeTuple<T> {
    fn from_vec(values:Vec<T>)->Self {
        if values.is_empty(){Self(None)}else{Self(Some(std::rc::Rc::new(values)))}
    }
    fn as_slice(&self)->&[T] {self.0.as_deref().map(Vec::as_slice).unwrap_or(&[])}
    fn len(&self)->usize {self.as_slice().len()}
    fn is_empty(&self)->bool {self.0.is_none()}
    fn iter(&self)->std::slice::Iter<'_,T> {self.as_slice().iter()}
}
fn native_tuple_same<A,B>(left:&NativeTuple<A>,right:&NativeTuple<B>)->bool {
    match(&left.0,&right.0){
        (None,None)=>true,
        (Some(a),Some(b))=>std::ptr::eq(std::rc::Rc::as_ptr(a).cast::<()>(),std::rc::Rc::as_ptr(b).cast::<()>()),
        _=>false,
    }
}
'''


def mark(g,kind):
    g.has_tuples=True
    g.register_type(kind)


def materialize(g,node,environment):
    from .native import _Expression,_Unsupported
    from .native_iterators import Planner,TraceContext,stream_item,_owned
    from .native_stream_plans import context,ProducerKind
    plan=context(g,environment).producer(node.args[0])
    # tuple(existing_tuple) returns the same immutable object. Ordinary calls
    # such as map must be consumed by Planner rather than scalar expression().
    if plan.kind is ProducerKind.VALUE or isinstance(node.args[0],ast.Tuple):
        value=g.expression(node.args[0],environment)
        if isinstance(value.kind,(TupleType,TupleSequenceType)):return value
        source=Planner(g).lower(plan,environment,captured_value=value)
    else:source=Planner(g).lower(plan,environment)
    value=stream_item(g,source)
    if not immutable(value.kind):
        raise _Unsupported("tuple materialization with mutable payloads needs an alias-preserving shared tuple element representation; this ordinary native tuple adapter currently proves immutable elements",node=node,types=(("element",value.kind),),proof="immutable tuple element storage")
    kind=TupleSequenceType(value.kind);mark(g,kind)
    g.has_typed_lists=g.has_lists=True
    result=g.temporary()
    action=g.at(f"native_typed_push(&mut {result},{_owned(g,value,value.kind)})",node)+";"
    body=source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))
    code=source.construct()+f"let mut {result}:Vec<{rust_type(value.kind)}>=Vec::new();"+body+f"NativeTuple::from_vec({result})"
    return _Expression("{"+code+"}",kind,length=source.length)


def representation(g,value):
    from .native import _Expression
    from .native_typed_lists import _representation
    mark(g,value.kind)
    owner,result,index,item=(g.temporary()for _ in range(4))
    text=_representation(g,_Expression(f"(*{item})",value.kind.element,owned=False),quoted=True)
    return (f'{{let {owner}=&({value.code});let mut {result}=String::from("(");'
            f'for({index},{item})in {owner}.iter().enumerate(){{if {index}>0{{{result}.push_str(", ");}}'
            f'{result}.push_str(&({text}));}}if {owner}.len()==1{{{result}.push(\',\');}}'
            f'{result}.push(\')\');{result}}}')


def try_expression(g,node,environment):
    from .native import _Binding,_Expression,_Unsupported,_text_expression
    from .references import BuiltinIdentity,callable_reference
    if isinstance(node,ast.Name):
        binding=environment.get(node.id)
        if isinstance(binding,_Binding)and isinstance(binding.kind,TupleSequenceType):
            mark(g,binding.kind)
            return _Expression(binding.slot,binding.kind,owned=False)
    if isinstance(node,ast.Call)and isinstance(node.func,ast.Name)and len(node.args)==1 and not node.keywords:
        identity=callable_reference(g,node.func,environment)
        if identity==BuiltinIdentity('tuple'):return materialize(g,node,environment)
        if identity in (BuiltinIdentity('len'),BuiltinIdentity('bool'),BuiltinIdentity('str')):
            value=g.expression(node.args[0],environment)
            if isinstance(value.kind,TupleSequenceType):
                mark(g,value.kind)
                if node.func.id=='str':return _text_expression(representation(g,value))
                if node.func.id=='bool':return _Expression(f"!({value.code}).is_empty()",'bool')
                number=f"(({value.code}).len() as NativeInt)"if g.bits else f"Int::from_i128(({value.code}).len() as i128)"
                return _Expression(number,'int')
    if isinstance(node,ast.Subscript)and not isinstance(node.slice,ast.Slice):
        value=g.expression(node.value,environment)
        if not isinstance(value.kind,TupleSequenceType):return None
        mark(g,value.kind)
        index=g.expression(node.slice,environment)
        owner,offset=g.temporary(),g.temporary()
        wide=f"({offset}) as i128"if g.bits else f"{offset}.to_i128().unwrap_or_else(||if {offset}.is_negative(){{i128::MIN}}else{{i128::MAX}})"
        checked=g.at(f"native_tuple_index({wide},{owner}.len())",node)
        code=f"{{let {owner}=({value.code}).clone();let {offset}={g.number(index)};{owner}.as_slice()[{checked}].clone()}}"
        return _Expression(code,value.kind.element)
    return None


def _equal(g,left,right,node):
    from .native import _Expression,_Unsupported
    from .native_tuples import _scalar,_equal as scalar_equal
    if not _scalar(left.kind)or not _scalar(right.kind):
        raise _Unsupported('tuple comparison needs identity-aware equality for this payload, including floating NaN or mutable/custom values; that protocol is not implemented',node=node,types=(('left',left.kind),('right',right.kind)),proof='tuple element equality and identity shortcuts')
    a,b=left.kind,right.kind
    if not isinstance(a,TupleSequenceType)and not isinstance(b,TupleSequenceType):return scalar_equal(g,left,right)
    if isinstance(a,TupleSequenceType)and isinstance(b,TupleSequenceType):
        x,y=g.temporary(),g.temporary()
        inner=scalar_equal(g,_Expression(f'(*{x})',a.element,owned=False),_Expression(f'(*{y})',b.element,owned=False))
        return f'(({left.code}).len()==({right.code}).len()&&({left.code}).iter().zip(({right.code}).iter()).all(|({x},{y})|{inner}))'
    if isinstance(a,TupleSequenceType)and isinstance(b,TupleType):
        tests=[scalar_equal(g,_Expression(f'({left.code}).as_slice()[{index}]',a.element,owned=False),_Expression(f'({right.code}).{index}',field,owned=False))for index,field in enumerate(b.fields)]
        return f'(({left.code}).len()=={len(b.fields)}'+''.join(f'&&({test})'for test in tests)+')'
    if isinstance(a,TupleType)and isinstance(b,TupleSequenceType):return _equal(g,right,left,node)
    return 'false'


def _ordering(g,left,right,operator,node):
    from .native import _Expression,_Unsupported
    from .native_comparisons import ordering,ORDERING
    from .native_tuples import _scalar,_equal as scalar_equal
    a,b=left.kind,right.kind
    if not isinstance(a,TupleSequenceType)and not isinstance(b,TupleSequenceType):return ordering(g,left,right,operator,node)
    if not _scalar(a)or not _scalar(b):raise _Unsupported('tuple ordering requires proved identity-safe built-in element comparisons',node=node,types=(('left',a),('right',b)),proof='tuple element ordering')
    symbol=ORDERING[type(operator)]
    strict=ast.Lt()if isinstance(operator,(ast.Lt,ast.LtE))else ast.Gt()
    if isinstance(a,TupleSequenceType)and isinstance(b,TupleSequenceType):
        x,y,result=g.temporary(),g.temporary(),g.temporary()
        lhs=_Expression(f'(*{x})',a.element,owned=False);rhs=_Expression(f'(*{y})',b.element,owned=False)
        equal=scalar_equal(g,lhs,rhs);test=ordering(g,lhs,rhs,strict,node)
        return (f'{{let mut {result}=None;for({x},{y})in ({left.code}).iter().zip(({right.code}).iter())'
                f'{{if !({equal}){{{result}=Some({test});break;}}}}'
                f'{result}.unwrap_or_else(||({left.code}).len(){symbol}({right.code}).len())}}')
    if isinstance(a,TupleSequenceType)and isinstance(b,TupleType):
        tail=f'({left.code}).len(){symbol}{len(b.fields)}'
        for index,kind in reversed(list(enumerate(b.fields))):
            lhs=_Expression(f'({left.code}).as_slice()[{index}]',a.element,owned=False);rhs=_Expression(f'({right.code}).{index}',kind,owned=False)
            equal=scalar_equal(g,lhs,rhs);test=ordering(g,lhs,rhs,strict,node)
            short='true'if isinstance(operator,(ast.Lt,ast.LtE))else'false'
            tail=f'if ({left.code}).len()<={index}{{{short}}}else if {equal}{{{tail}}}else{{{test}}}'
        return '{'+tail+'}'
    if isinstance(a,TupleType)and isinstance(b,TupleSequenceType):
        reverse={ast.Lt:ast.Gt,ast.LtE:ast.GtE,ast.Gt:ast.Lt,ast.GtE:ast.LtE}[type(operator)]
        return _ordering(g,right,left,reverse(),node)
    from .native_comparisons import _unsupported_pair
    return _unsupported_pair(g,left,right,operator,node)


def comparison(g,node,values):
    from .native import _Expression,_Unsupported
    from .native_types import alternatives
    from .native_unions import project
    if not any(isinstance(kind,TupleSequenceType)for value in values for kind in alternatives(value.kind)):return None
    names=[g.temporary()for _value in values]
    def pair(left,right,operator):
        def both(a,x,b,y):
            lhs=_Expression(x,a,owned=False);rhs=_Expression(y,b,owned=False)
            if isinstance(operator,(ast.Is,ast.IsNot)):
                if isinstance(a,TupleSequenceType)and isinstance(b,TupleSequenceType):test=f'native_tuple_same(&({x}),&({y}))'
                elif isinstance(a,TupleSequenceType)and b==TupleType(()):test=f'({x}).is_empty()'
                elif isinstance(b,TupleSequenceType)and a==TupleType(()):test=f'({y}).is_empty()'
                elif isinstance(a,TupleType)or isinstance(b,TupleType):
                    raise _Unsupported('identity of copied fixed tuple values is not retained; only shared runtime tuple identity and the canonical empty tuple are proved',node=node,proof='stable tuple object identity')
                elif a==b=="none":test="true"
                elif a==b=="bool":test=f"({x})==({y})"
                elif a==b or {a,b}<={"int","bool","int_bool"}:
                    raise _Unsupported('identity of copied scalar values is not retained by this representation',node=node,proof='stable scalar object identity')
                else:test='false'
                return f'!({test})'if isinstance(operator,ast.IsNot)else test
            if isinstance(operator,(ast.Eq,ast.NotEq)):
                test=_equal(g,lhs,rhs,node)
                return f'!({test})'if isinstance(operator,ast.NotEq)else test
            if isinstance(operator,(ast.In,ast.NotIn)):
                if not isinstance(b,TupleSequenceType):raise _Unsupported('this membership adapter requires an immutable dynamic tuple container',node=node,proof='tuple membership protocol')
                from .native_tuples import _equal as scalar_equal
                item=g.temporary();test=scalar_equal(g,lhs,_Expression(f'(*{item})',b.element,owned=False))
                test=f'({y}).iter().any(|{item}|{test})'
                return f'!({test})'if isinstance(operator,ast.NotIn)else test
            return _ordering(g,lhs,rhs,operator,node)
        return project(left.kind,left.code,lambda a,x:project(right.kind,right.code,lambda b,y:both(a,x,b,y)))
    tail='true'
    for index in reversed(range(len(node.ops))):
        left=_Expression(names[index],values[index].kind);right=_Expression(names[index+1],values[index+1].kind)
        test=pair(left,right,node.ops[index])
        tail=f'{{let {names[index+1]}={g.coerce(values[index+1],values[index+1].kind)};({test})&&({tail})}}'
    return _Expression(f'{{let {names[0]}={g.coerce(values[0],values[0].kind)};{tail}}}','bool')


def total_order(g,left,right,node):
    """Non-fallible lexicographic ordering for proved builtin tuple payloads."""
    from .native import _Expression,_Unsupported
    from .native_types import EmptyType
    a,b=left.kind,right.kind
    if isinstance(a,EmptyType)and isinstance(b,EmptyType):return 'std::cmp::Ordering::Equal'
    numeric={'int','bool','int_bool'}
    if a in numeric and b in numeric:return f'({g.number(left)}).cmp(&({g.number(right)}))'
    if a==b and a in {'str','bytes'}:return f'({left.code}).cmp(&({right.code}))'
    if a==b=='none':return 'std::cmp::Ordering::Equal'
    if isinstance(a,TupleSequenceType)and isinstance(b,TupleSequenceType):
        x,y,result,step=(g.temporary()for _ in range(4))
        nested=total_order(g,_Expression(f'(*{x})',a.element,owned=False),_Expression(f'(*{y})',b.element,owned=False),node)
        return (f'{{let mut {result}=std::cmp::Ordering::Equal;'
                f'for({x},{y})in ({left.code}).iter().zip(({right.code}).iter()){{let {step}={nested};'
                f'if {step}!=std::cmp::Ordering::Equal{{{result}={step};break;}}}}'
                f'if {result}==std::cmp::Ordering::Equal{{({left.code}).len().cmp(&({right.code}).len())}}else{{{result}}}}}')
    if isinstance(a,TupleType)and isinstance(b,TupleType):
        result=f'{len(a.fields)}_usize.cmp(&{len(b.fields)}_usize)'
        for index in reversed(range(min(len(a.fields),len(b.fields)))):
            step=g.temporary()
            nested=total_order(g,_Expression(f'({left.code}).{index}',a.fields[index],owned=False),_Expression(f'({right.code}).{index}',b.fields[index],owned=False),node)
            result=f'{{let {step}={nested};if {step}==std::cmp::Ordering::Equal{{{result}}}else{{{step}}}}}'
        return result
    raise _Unsupported('this tuple payload has no proved non-fallible native total ordering; float/NaN identity, custom comparison protocols and mixed unorderable alternatives need a fallible comparator',node=node,types=(('left',a),('right',b)),proof='non-fallible built-in tuple element ordering')
