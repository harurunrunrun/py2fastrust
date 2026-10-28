"""Fixed immutable scalar tuples lowered to ordinary Rust tuple values."""
import ast
import re
from importlib.resources import files

from .native import _Binding, _Expression, _Function, _Unsupported, _string, _text_expression
from .native_types import TupleType,TupleSequenceType,ListType,TypedListInfo,join_types,tuple_code,tuple_field,unmaybe


HELPERS = r'''
fn native_tuple_index(index:i128,length:usize)->Result<usize,String> {
    let index=if index<0{index.saturating_add(length as i128)}else{index};
    usize::try_from(index).ok().filter(|index|*index<length)
        .ok_or_else(||"IndexError: tuple index out of range".to_string())
}
fn native_tuple_printable(character:char)->bool {
    let index=NATIVE_TUPLE_PRINTABLE.partition_point(|&(_,end)|end<character as u32);
    NATIVE_TUPLE_PRINTABLE.get(index).is_some_and(|&(start,_)|start<=character as u32)
}
fn native_tuple_repr_str(value:&str)->String {
    use std::fmt::Write as _;
    let quote=if value.contains('\'')&&!value.contains('"'){'"'}else{'\''};
    let mut result=String::new();result.push(quote);
    for character in value.chars(){match character {
        '\n'=>result.push_str("\\n"),'\r'=>result.push_str("\\r"),'\t'=>result.push_str("\\t"),
        '\\'=>result.push_str("\\\\"),character if character==quote=>{result.push('\\');result.push(character);},
        character if !native_tuple_printable(character)=>{
            let value=character as u32;
            if value<=255{write!(&mut result,"\\x{value:02x}").unwrap();}
            else if value<=65535{write!(&mut result,"\\u{value:04x}").unwrap();}
            else{write!(&mut result,"\\U{value:08x}").unwrap();}
        },
        character=>result.push(character),
    }}
    result.push(quote);result
}
'''


def render_helpers():
    text=files("py2fastrust").joinpath("runtime","text.rs").read_text(encoding="utf-8")
    table=re.search(r"const TEXT_PRINTABLE: &\[\(u32, u32\)\] = &\[.*?\n\];",text,re.S)
    if table is None:
        raise RuntimeError("the bundled Unicode printable table is missing")
    from .native_tuple_sequences import HELPERS as sequence_helpers
    return table[0].replace("TEXT_PRINTABLE","NATIVE_TUPLE_PRINTABLE")+"\n"+HELPERS+sequence_helpers


def tuple_kind(kind):
    return isinstance(kind,TupleType)


def coerce_structural(expression,kind,coerce):
    if isinstance(kind,TupleSequenceType):
        if expression.kind!=kind:
            raise _Unsupported("converting an existing tuple to a different homogeneous element representation would change tuple identity; preserve a finite typed alternative instead",types=(("source",expression.kind),("destination",kind)),proof="tuple identity during value flow")
        return f"({expression.code}).clone()"
    if isinstance(kind,TupleType):
        if not isinstance(expression.kind,TupleType) or len(kind.fields)!=len(expression.kind.fields):
            raise _Unsupported
        if expression.kind==kind:
            return f"({expression.code}).clone()"
        fields=[coerce(_Expression(f"native_tuple_copy.{index}",source),target)
                for index,(source,target) in enumerate(zip(expression.kind.fields,kind.fields))]
        return f"{{let native_tuple_copy=({expression.code}).clone(); {tuple_code(fields)}}}"
    if isinstance(kind,ListType):
        if expression.kind==kind:
            return expression.code
        if not isinstance(expression.kind,ListType):
            raise _Unsupported
        item=coerce(_Expression("native_tuple_item",expression.kind.element),kind.element)
        return f"({expression.code}).into_iter().map(|native_tuple_item|{item}).collect::<Vec<_>>()"
    return None


def _mark(generator,kind):
    generator.has_tuples=True
    generator.register_type(kind)


def _scalar(kind):
    from .native_types import UnionType,NullableType
    if isinstance(kind,UnionType):return all(_scalar(value) for value in kind.alternatives)
    if isinstance(kind,NullableType):return _scalar(kind.value)
    if isinstance(kind,TupleSequenceType):return _scalar(kind.element)
    return (all(_scalar(field) for field in kind.fields) if isinstance(kind,TupleType) else
            kind in {"int","bool","int_bool","str","bytes","none"})


def _equal(generator,left,right):
    from .native_unions import union_kind,project
    if union_kind(left.kind) or union_kind(right.kind):
        return project(left.kind,left.code,lambda a,x:project(right.kind,right.code,
            lambda b,y:_equal(generator,_Expression(x,a,owned=False),_Expression(y,b,owned=False))))
    if isinstance(left.kind,TupleSequenceType)or isinstance(right.kind,TupleSequenceType):
        from .native_tuple_sequences import _equal as sequence_equal
        return sequence_equal(generator,left,right,None)
    if left.kind=="none" or right.kind=="none":return str(left.kind==right.kind).lower()
    if isinstance(left.kind,TupleType) or isinstance(right.kind,TupleType):
        return tuple_compare(generator,left,right,ast.Eq(),None)
    if left.kind in {"int","bool","int_bool"} and right.kind in {"int","bool","int_bool"}:
        return f"({generator.number(left)})==({generator.number(right)})"
    if left.kind==right.kind and left.kind in {"str","bytes"}:
        return f"({left.code})==({right.code})"
    return "false"


def _order(generator,left,right,operator,node):
    from .native_comparisons import ordering
    operation={"<":ast.Lt,">":ast.Gt,"<=":ast.LtE,">=":ast.GtE}[operator]
    return ordering(generator,left,right,operation(),node)


def tuple_compare(generator,left,right,operator,node):
    if not isinstance(left.kind,TupleType) and not isinstance(right.kind,TupleType):
        if not _scalar(left.kind) or not _scalar(right.kind):raise _Unsupported
        if isinstance(operator,(ast.Eq,ast.NotEq)):
            result=_equal(generator,left,right)
            return f"!({result})" if isinstance(operator,ast.NotEq) else result
        symbol={ast.Lt:"<",ast.LtE:"<=",ast.Gt:">",ast.GtE:">="}[type(operator)]
        return _order(generator,left,right,symbol,node)
    if not isinstance(left.kind,TupleType) or not isinstance(right.kind,TupleType):
        if isinstance(operator,(ast.Eq,ast.NotEq)):
            return str(isinstance(operator,ast.NotEq)).lower()
        return generator.at('Err::<bool,String>("TypeError: values do not support tuple ordering".into())',node)
    pairs=[(_Expression(tuple_field(left.code,index),a,owned=False),_Expression(tuple_field(right.code,index),b,owned=False))
           for index,(a,b) in enumerate(zip(left.kind.fields,right.kind.fields))]
    if isinstance(operator,(ast.Eq,ast.NotEq)):
        result=" && ".join(f"({_equal(generator,a,b)})" for a,b in pairs) or "true"
        if len(left.kind.fields)!=len(right.kind.fields):result="false"
        return f"!({result})" if isinstance(operator,ast.NotEq) else f"({result})"
    symbol={ast.Lt:"<",ast.LtE:"<=",ast.Gt:">",ast.GtE:">="}[type(operator)]
    first,second=len(left.kind.fields),len(right.kind.fields)
    result=str(first<second if isinstance(operator,ast.Lt) else first<=second if isinstance(operator,ast.LtE)
               else first>second if isinstance(operator,ast.Gt) else first>=second).lower()
    for a,b in reversed(pairs):
        result=f"if {_equal(generator,a,b)} {{{result}}}else{{{_order(generator,a,b,symbol,node)}}}"
    return "{"+result+"}"


def tuple_ordering(generator,left,right,node):
    """A total lexicographic comparator for proved comparable tuple shapes."""
    if not isinstance(left.kind,TupleType) or not isinstance(right.kind,TupleType):raise _Unsupported
    result=("std::cmp::Ordering::Less" if len(left.kind.fields)<len(right.kind.fields) else
            "std::cmp::Ordering::Greater" if len(left.kind.fields)>len(right.kind.fields) else "std::cmp::Ordering::Equal")
    for index,(a,b) in reversed(list(enumerate(zip(left.kind.fields,right.kind.fields)))):
        if isinstance(a,TupleType) and isinstance(b,TupleType):
            first=_Expression(tuple_field(left.code,index),a,owned=False);second=_Expression(tuple_field(right.code,index),b,owned=False)
            comparison=tuple_ordering(generator,first,second,node)
            temporary=generator.temporary()
            result=f"{{let {temporary}={comparison};if {temporary}==std::cmp::Ordering::Equal{{{result}}}else{{{temporary}}}}}"
            continue
        if not (a in {"int","bool","int_bool"} and b in {"int","bool","int_bool"} or a==b=="str"):
            raise _Unsupported
        first=_Expression(tuple_field(left.code,index),a,owned=False);second=_Expression(tuple_field(right.code,index),b,owned=False)
        result=f"if {_equal(generator,first,second)}{{{result}}}else if {_order(generator,first,second,'<',node)}{{std::cmp::Ordering::Less}}else{{std::cmp::Ordering::Greater}}"
    return "{"+result+"}"


def tuple_repr(generator,value):
    if not isinstance(value.kind,TupleType):
        raise _Unsupported
    _mark(generator,value.kind)
    name,result=generator.temporary(),generator.temporary()
    receiver=value.code if value.owned else f"&({value.code})"
    lines=[f"let {name}={receiver};",f'let mut {result}=String::from("(");']
    for index,kind in enumerate(value.kind.fields):
        if index:lines.append(f'{result}.push_str(", ");')
        item=f"{name}.{index}"
        from .native_unions import union_kind
        if union_kind(kind) or kind=="none":
            from .native_typed_lists import _representation
            nested=_representation(generator,_Expression(item,kind,owned=False),quoted=True)
            lines.append(f"{result}.push_str(&({nested}));")
        elif isinstance(kind,TupleType):
            nested=tuple_repr(generator,_Expression(item,kind,owned=False))
            lines.append(f"{result}.push_str(&({nested}));")
        elif kind=="str":lines.append(f"{result}.push_str(&native_tuple_repr_str(&{item}));")
        else:
            display=f'if {item}{{"True"}}else{{"False"}}' if kind=="bool" else item
            lines.append(f'write!(&mut {result},"{{}}",{display}).unwrap();')
    if len(value.kind.fields)==1:lines.append(f"{result}.push(',');")
    lines.append(f"{result}.push(')'); {result}")
    return "{"+" ".join(lines)+"}"


def try_expression(generator,node,environment):
    from .native_tuple_sequences import try_expression as sequence_expression
    sequence=sequence_expression(generator,node,environment)
    if sequence is not None:return sequence
    if isinstance(node,ast.Tuple):
        values=[generator.expression(value,environment) for value in node.elts]
        if any(not _scalar(value.kind) for value in values):
            raise _Unsupported("this tuple payload needs value/identity or mutable-alias handling beyond the registered native scalar tuple fields; the required tuple storage/protocol adapter is not implemented",node=node,operation="tuple allocation",types=(("tuple",TupleType(tuple(value.kind for value in values))),),proof="tuple payload value and identity semantics")
        kind=TupleType(tuple(value.kind for value in values));_mark(generator,kind)
        return _Expression(tuple_code(value.code for value in values),kind,length=len(values))
    if isinstance(node,ast.Name):
        binding=environment.get(node.id)
        if isinstance(binding,_Binding) and isinstance(binding.kind,TupleType):
            _mark(generator,binding.kind)
            return _Expression(binding.slot,binding.kind,owned=False,length=len(binding.kind.fields))
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and not node.keywords:
        from .references import BuiltinIdentity,callable_reference
        identity=callable_reference(generator,node.func,environment)
        name=identity.name if isinstance(identity,BuiltinIdentity)else None
        if name=="tuple" and not node.args:
            kind=TupleType(());_mark(generator,kind)
            return _Expression("()",kind,length=0)
        if name in {"tuple","len","bool","str"} and len(node.args)==1:
            value=generator.expression(node.args[0],environment)
            if isinstance(value.kind,TupleType):
                _mark(generator,value.kind)
                if name=="tuple":return value
                if name=="str":return _text_expression(tuple_repr(generator,value))
                constant=len(value.kind.fields) if name=="len" else bool(value.kind.fields)
                code=generator.literal(constant) if name=="len" else str(constant).lower()
                return _Expression(f"{{let _=&({value.code}); {code}}}","int" if name=="len" else "bool",constant)
    if isinstance(node,ast.Subscript) and not isinstance(node.slice,ast.Slice):
        value=generator.expression(node.value,environment)
        if not isinstance(value.kind,TupleType):return None
        _mark(generator,value.kind)
        index=generator.expression(node.slice,environment)
        number=generator.number(index)
        owner,offset,checked=generator.temporary(),generator.temporary(),generator.temporary()
        wide=(f"({offset}) as i128" if generator.bits else
              f"{offset}.to_i128().unwrap_or_else(||if {offset}.is_negative(){{i128::MIN}}else{{i128::MAX}})")
        receiver=value.code if value.owned else f"&({value.code})"
        setup=f"let {owner}={receiver};let {offset}={number};let {checked}={generator.at(f'native_tuple_index({wide},{len(value.kind.fields)})',node)};"
        constant=index.constant
        if constant is not None and not -len(value.kind.fields)<=int(constant)<len(value.kind.fields):
            # The checked index always exits with IndexError. Keep a concrete
            # unreachable result type without inventing a dynamic tuple value.
            return _Expression("{"+setup+generator.literal(0)+"}","int")
        if constant is not None and -len(value.kind.fields)<=int(constant)<len(value.kind.fields):
            index=int(constant)%len(value.kind.fields)
            kind=value.kind.fields[index]
            result=generator.coerce(_Expression(f"{owner}.{index}",kind,owned=False),kind)
        else:
            kind=None
            for field in value.kind.fields:
                kind=field if kind is None else join_types(kind,field)
                if kind is None:raise _Unsupported
            kind=kind or "int"
            arms=",".join(f"{index}=>{generator.coerce(_Expression(f'{owner}.{index}',field,owned=False),kind)}" for index,field in enumerate(value.kind.fields))
            result=f"match {checked}{{{arms}{',' if arms else ''}_=>unreachable!()}}"
            generator.register_type(kind)
        return _Expression("{"+setup+result+"}",kind)
    return None


def try_statement(generator,node,environment):
    if isinstance(node,ast.Assign):
        candidate=node.value
        if isinstance(candidate,ast.Name):
            binding=environment.get(candidate.id)
            if not isinstance(binding,_Binding) or not isinstance(unmaybe(binding.kind),TupleType):return None
        elif isinstance(candidate,ast.Call):
            if not (isinstance(candidate.func,ast.Name) and
                    (candidate.func.id=="tuple" or isinstance(environment.get(candidate.func.id),_Function))):return None
        elif isinstance(candidate,ast.Subscript):
            binding=environment.get(candidate.value.id) if isinstance(candidate.value,ast.Name) else None
            if not (isinstance(binding,_Binding) and isinstance(binding.kind,ListType) and isinstance(binding.kind.element,TupleType)):return None
        elif not isinstance(candidate,(ast.Tuple,ast.IfExp)):
            return None
        value=generator.expression(node.value,environment)
        if not isinstance(value.kind,TupleType):return None
        code=value.code if value.owned else generator.coerce(value,value.kind)
        name=generator.temporary();lines=[f"let {name}={code};"]
        for target in node.targets:
            if isinstance(target,ast.Name):
                if target.id in generator.iterating_lists:raise _Unsupported
                lines.append(f"{generator.bind(target.id,value,environment)}={name}.clone();")
            elif isinstance(target,(ast.Tuple,ast.List)) and all(isinstance(item,ast.Name) for item in target.elts):
                if len(target.elts)!=len(value.kind.fields):
                    message=(f"ValueError: not enough values to unpack (expected {len(target.elts)}, got {len(value.kind.fields)})"
                             if len(target.elts)>len(value.kind.fields) else f"ValueError: too many values to unpack (expected {len(target.elts)})")
                    lines.append(generator.at(f'Err::<(),String>(String::from({_string(message)}))',node)+";")
                    # Bind placeholders solely to keep statically unreachable
                    # Rust uses well typed; the prior error always exits.
                    for item in target.elts:
                        lines.append(f"{generator.bind(item.id,'int',environment)}={generator.literal(0)};")
                    continue
                for index,(item,kind) in enumerate(zip(target.elts,value.kind.fields)):
                    if item.id in generator.iterating_lists:raise _Unsupported
                    code=generator.coerce(_Expression(f"{name}.{index}",kind,owned=False),kind)
                    lines.append(f"{generator.bind(item.id,kind,environment)}={code};")
            else:raise _Unsupported
        return "\n".join(lines),environment
    if not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=="print"):
        return None
    call=node.value;values=[];setup=[];has_tuple=False
    for argument in call.args:
        star=isinstance(argument,ast.Starred)
        value=generator.expression(argument.value if star else argument,environment)
        if star:
            if not isinstance(value.kind,TupleType):return None
            has_tuple=True;name=generator.temporary();receiver=value.code if value.owned else f"&({value.code})";setup.append(f"let {name}={receiver};")
            values.extend(_Expression(f"{name}.{index}",kind,owned=False) for index,kind in enumerate(value.kind.fields))
        else:
            has_tuple|=isinstance(value.kind,TupleType)
            name=generator.temporary();receiver=f"&({value.code})" if isinstance(value.kind,TupleType) and not value.owned else value.code
            setup.append(f"let {name}={receiver};");values.append(_Expression(name,value.kind))
    if not has_tuple:return None
    sep,end,flush=" ","\n",False;seen=set()
    for keyword in call.keywords:
        if keyword.arg in seen or keyword.arg not in {"sep","end","flush"} or not isinstance(keyword.value,ast.Constant):raise _Unsupported
        seen.add(keyword.arg)
        if keyword.arg=="flush":
            if type(keyword.value.value) is not bool:raise _Unsupported
            flush=keyword.value.value
        else:
            if type(keyword.value.value) is not str:raise _Unsupported
            if keyword.arg=="sep":sep=keyword.value.value
            else:end=keyword.value.value
    for index,value in enumerate(values):
        if index:setup.append(f"native_output.push_str({_string(sep)});")
        code=tuple_repr(generator,value) if isinstance(value.kind,TupleType) else value.code
        if value.kind=="bool":code=f'if {code}{{"True"}}else{{"False"}}'
        if not isinstance(value.kind,TupleType) and value.kind not in {"int","bool","int_bool","str"}:raise _Unsupported
        setup.append(f'write!(&mut native_output,"{{}}",{code}).unwrap();')
    setup.append(f"native_output.push_str({_string(end)});")
    if flush:setup.append(generator.at("native_flush_output(&mut native_output)",node)+";")
    return "\n".join(setup),environment

def comparison(generator,node,expressions):
    if any(type(operator) not in {ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE} for operator in node.ops):
        raise _Unsupported
    names=[generator.temporary() for _ in expressions];tail="true"
    for index in reversed(range(len(node.ops))):
        a,b=expressions[index:index+2]
        comparison=tuple_compare(generator,_Expression(names[index],a.kind),_Expression(names[index+1],b.kind),node.ops[index],node)
        tail=f"{{let {names[index+1]}=&({b.code}); ({comparison})&&({tail})}}"
    return _Expression(f"{{let {names[0]}=&({expressions[0].code});{tail}}}","bool")
