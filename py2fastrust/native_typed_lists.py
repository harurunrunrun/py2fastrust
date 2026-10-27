"""Uniquely owned native lists with structural immutable element types."""

import ast

from .native import _Binding, _DequeInfo, _Expression, _ListInfo, _Unsupported, _string
from .native_types import ListType, TupleType, TypedListInfo, immutable, join_types, rust_type, tuple_code


HELPERS = r'''
fn native_typed_reserve<T>(values:&mut Vec<T>,additional:usize)->Result<(),String> {
    let length=values.len().checked_add(additional).ok_or("MemoryError")?;
    if length>isize::MAX as usize{return Err("MemoryError".into());}
    values.try_reserve(additional).map_err(|_|"MemoryError".to_string())
}
fn native_typed_push<T>(values:&mut Vec<T>,value:T)->Result<(),String> {
    native_typed_reserve(values,1)?;
    values.push(value);
    Ok(())
}
fn native_typed_copy<T:Clone>(values:&[T])->Result<Vec<T>,String> {
    let mut result=Vec::new();
    native_typed_reserve(&mut result,values.len())?;
    result.extend(values.iter().cloned());
    Ok(result)
}
fn native_typed_whitespace(character:char)->bool {
    character.is_whitespace()||('\u{1c}'..='\u{1f}').contains(&character)
}
fn native_typed_split(text:&str,separator:Option<&str>,maximum:i128)->Result<Vec<String>,String> {
    let maximum=isize::try_from(maximum).map_err(|_|"OverflowError: Python int too large to convert to C ssize_t".to_string())?;
    let mut result=Vec::new();
    if let Some(separator)=separator {
        if separator.is_empty(){return Err("ValueError: empty separator".into());}
        if maximum<0 {
            for word in text.split(separator){native_typed_push(&mut result,word.to_owned())?;}
        }else{
            for word in text.splitn(maximum as usize+1,separator){native_typed_push(&mut result,word.to_owned())?;}
        }
        return Ok(result);
    }
    let mut cursor=0;
    let mut remaining=maximum;
    loop {
        while cursor<text.len() {
            let character=text[cursor..].chars().next().unwrap();
            if !native_typed_whitespace(character){break;}
            cursor+=character.len_utf8();
        }
        if cursor==text.len(){break;}
        if remaining==0 {
            native_typed_push(&mut result,text[cursor..].to_owned())?;
            break;
        }
        let start=cursor;
        while cursor<text.len() {
            let character=text[cursor..].chars().next().unwrap();
            if native_typed_whitespace(character){break;}
            cursor+=character.len_utf8();
        }
        native_typed_push(&mut result,text[start..cursor].to_owned())?;
        if remaining>0{remaining-=1;}
    }
    Ok(result)
}
'''


def _enable(g):
    g.has_typed_lists = True
    # The existing checked structural index helper is shared by both list
    # implementations. Its integer-specific get/set functions are pruned.
    g.has_lists = True


def _length(g, code):
    return f"Int::from_i128(({code}) as i128)" if not g.bits else f"(({code}) as NativeInt)"


def _index(g, code, length, node, *, assignment=False):
    call = f"native_big_list_index(&({code}),{length})" if not g.bits else f"native_index({code},{length})"
    if assignment:
        call += '.map_err(|_|String::from("IndexError: list assignment index out of range"))'
    return g.at(call, node)


def _clone(g, value, kind):
    return value.code if value.kind == kind and value.owned else g.coerce(value, kind)


def _ordering(g,left,right,node):
    numeric = {"int","bool","int_bool"}
    if left.kind in numeric and right.kind in numeric:
        return f"({g.number(left)}).cmp(&({g.number(right)}))"
    if left.kind == right.kind and left.kind in {"str","bytes"}:
        return f"({left.code}).cmp(&({right.code}))"
    if isinstance(left.kind,TupleType) and isinstance(right.kind,TupleType):
        from .native_tuples import tuple_ordering
        return tuple_ordering(g,left,right,node)
    raise _Unsupported


def _sort_options(g,node,environment,owners=()):
    reverse,key = "false",None
    lines,seen = [],set()
    depth = len(g.iterating_lists)
    g.iterating_lists.extend(owners)
    try:
        for keyword in node.keywords:
            if keyword.arg not in {"reverse","key"} or keyword.arg in seen:
                raise _Unsupported
            seen.add(keyword.arg)
            value = keyword.value
            if keyword.arg == "key":
                if isinstance(value,ast.Constant) and value.value is None:
                    continue
                if not isinstance(value,ast.Name):
                    raise _Unsupported
                key = value
            else:
                direction = (_Expression("false","bool",False) if isinstance(value,ast.Constant) and value.value is None else
                             g.expression(value,environment))
                name = g.temporary()
                lines.append(f"let {name}={g.truth(direction)};")
                reverse = name
    finally:
        del g.iterating_lists[depth:]
    return lines,reverse,key


def _sort_code(g,owner,element,node,environment,reverse,key):
    left,right = g.temporary(),g.temporary()
    if key is None:
        comparison = _ordering(g,_Expression(f"(*{left})",element),_Expression(f"(*{right})",element),node)
        return f"{owner}.sort_by(|{left},{right}|{{let native_order={comparison};if {reverse} {{native_order.reverse()}}else{{native_order}}}});"
    item = g.temporary()
    argument = "\0sort_" + g.temporary()
    inside = environment.copy()
    inside[argument] = _Binding(f"(*{item})",element)
    call = ast.copy_location(ast.Call(func=key,args=[ast.Name(id=argument,ctx=ast.Load())],keywords=[]),node)
    ast.fix_missing_locations(call)
    value = g.expression(call,inside)
    if not immutable(value.kind):
        raise _Unsupported
    g.register_type(value.kind)
    comparison = _ordering(g,_Expression(f"{left}.0",value.kind),_Expression(f"{right}.0",value.kind),node)
    decorated = g.temporary()
    push = g.at(f"native_typed_push(&mut {decorated},({value.code},{item}.clone()))",node)
    return (f"let mut {decorated}:Vec<({rust_type(value.kind)},{rust_type(element)})>=Vec::new();\n"
            f"for {item} in {owner}.iter() {{{push};}}\n"
            f"{decorated}.sort_by(|{left},{right}|{{let native_order={comparison};if {reverse} {{native_order.reverse()}}else{{native_order}}}});\n"
            f"{owner}.clear();\nfor (_, {item}) in {decorated} {{{owner}.push({item});}}")


def _collect(g,source,node,*,constructed=False):
    from .native_iterators import TraceContext, _owned
    if source.tupled:
        element = TupleType(tuple(value.kind for value in source.values))
        code = tuple_code(_owned(g,value,value.kind) for value in source.values)
        value = _Expression(code,element)
    elif len(source.values) == 1:
        value = source.values[0]
        element = value.kind
    else:
        raise _Unsupported
    if not immutable(element):
        raise _Unsupported
    kind = "list_int" if element == "int" else ListType(element)
    g.register_type(kind)
    _enable(g)
    result = g.temporary()
    action = g.at(f"native_typed_push(&mut {result},{_clone(g,value,element)})",node) + ";"
    body = source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))
    code = ("" if constructed else source.construct()) + f"\nlet mut {result}:{rust_type(kind)}=Vec::new();\n" + body + f"\n{result}"
    return _Expression("{\n" + code + "\n}",kind,length=source.length)


def _split(g, node, environment):
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "split"):
        return None
    owner = g.expression(node.func.value, environment)
    if owner.kind != "str":
        return None
    if len(node.args) > 2 or any(isinstance(arg, ast.Starred) for arg in node.args):
        raise _Unsupported
    text = g.temporary()
    lines = [f"let {text}={owner.code};"]
    values = {}
    for name, argument in zip(("sep", "maxsplit"), node.args):
        values[name] = argument
    ordered = [(name, argument) for name, argument in zip(("sep", "maxsplit"), node.args)]
    for keyword in node.keywords:
        if keyword.arg not in {"sep", "maxsplit"} or keyword.arg in values:
            raise _Unsupported
        values[keyword.arg] = keyword.value
        ordered.append((keyword.arg, keyword.value))
    separator, maximum = "None", "-1_i128"
    for name, argument in ordered:
        if name == "sep" and isinstance(argument, ast.Constant) and argument.value is None:
            continue
        value = g.expression(argument, environment)
        temporary = g.temporary()
        if name == "sep":
            if value.kind != "str":
                raise _Unsupported
            lines.append(f"let {temporary}={value.code};")
            separator = f"Some({temporary}.as_str())"
        else:
            number = g.number(value)
            lines.append(f"let {temporary}={number};")
            maximum = (f"({temporary}) as i128" if g.bits else
                       f"{temporary}.to_i128().unwrap_or_else(||if {temporary}.is_negative(){{i128::MIN}}else{{i128::MAX}})")
    _enable(g)
    call = g.at(f"native_typed_split(&{text},{separator},{maximum})", node)
    return _Expression("{ " + " ".join(lines) + f" {call} }}", ListType("str"))


def _comprehension(g, node, environment):
    from .native_iterators import Planner, TraceContext
    if not node.generators or any(clause.is_async for clause in node.generators):
        raise _Unsupported
    planner = Planner(g)
    inside = environment
    clauses = []
    owners = set()
    guard_depth = len(g.iterating_lists)
    mutation_start = len(g.expression_mutations)
    try:
        for clause in node.generators:
            source = planner.stream(clause.iter, inside)
            inside = planner.bind_target(clause.target, source, inside)
            owners.update(source.owners)
            g.iterating_lists.extend(source.owners)
            filters = [g.expression(condition, inside) for condition in clause.ifs]
            clauses.append((source, filters))
        element = g.expression(node.elt, inside)
    finally:
        del g.iterating_lists[guard_depth:]
    if clauses[0][0].length != 0:
        changed = {id(binding) for binding in g.expression_mutations[mutation_start:]}
        for name,binding in list(environment.items()):
            if id(binding) in changed and isinstance(binding.info,_DequeInfo):
                g.update_info(environment,name,_DequeInfo(None))
    if not immutable(element.kind):
        # Mutable nested elements need shared identity, even if every source
        # expression is new. The integer matrix backend handles its own proof.
        return None
    kind = "list_int" if element.kind == "int" else ListType(element.kind)
    g.register_type(kind)
    result = g.temporary()
    body = g.at(f"native_typed_push(&mut {result},{_clone(g,element,element.kind)})", node.elt) + ";"
    for source, filters in reversed(clauses):
        for condition in reversed(filters):
            body = f"if {g.truth(condition)} {{\n{body}\n}}"
        body = source.emit(body, TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))
        if source is not clauses[0][0]:
            body = source.construct() + "\n" + body
    _enable(g)
    return _Expression("{ " + clauses[0][0].construct() + f"\nlet mut {result}:{rust_type(kind)}=Vec::new();\n{body}\n{result} }}", kind)


def _slice(g, node, owner, environment):
    g.has_slices = True
    container = g.temporary()
    lines = [f"let {container}:&[{rust_type(owner.kind.element)}]=&({owner.code});"]
    bounds, constants = [], []
    known = True
    for expression in (node.slice.lower,node.slice.upper,node.slice.step):
        if expression is None or isinstance(expression,ast.Constant) and expression.value is None:
            bounds.append("None")
            constants.append(None)
            continue
        value = g.expression(expression,environment)
        temporary = g.temporary()
        lines.append(f"let {temporary}={g.number(value)};")
        bound = (f"({temporary}) as i128" if g.bits else
                 f"{temporary}.to_i128().unwrap_or_else(||if {temporary}.is_negative(){{i128::MIN}}else{{i128::MAX}})")
        bounds.append(f"Some({bound})")
        constants.append(value.constant)
        known &= value.constant is not None
    indices = g.temporary()
    lines.append(f"let {indices}={g.at(f'native_slice_indices({container}.len(),{",".join(bounds)})',node)};")
    length = None
    if owner.length is not None and known:
        try:
            length = len(range(*slice(*constants).indices(owner.length)))
        except ValueError:
            pass
    return _Expression("{ " + " ".join(lines) + f" native_flat_slice({container},{indices}) }}",owner.kind,length=length)


def try_expression(g, node, environment):
    if isinstance(node,ast.Name):
        binding = environment.get(node.id)
        if isinstance(binding,_Binding) and isinstance(binding.info,TypedListInfo):
            return _Expression(binding.slot,binding.info.kind,owned=False,length=binding.info.length)
        return None
    split = _split(g,node,environment)
    if split is not None:
        return split
    if isinstance(node,ast.ListComp):
        return _comprehension(g,node,environment)
    if isinstance(node,ast.List) and node.elts:
        values = [g.expression(value,environment) for value in node.elts]
        element = values[0].kind
        for value in values[1:]:
            element = join_types(element,value.kind)
            if element is None:
                raise _Unsupported
        if element == "int" or not immutable(element):
            return None
        _enable(g)
        g.register_type(ListType(element))
        return _Expression("vec![" + ",".join(_clone(g,value,element) for value in values) + "]",ListType(element),length=len(values))
    if isinstance(node,ast.Subscript):
        owner = g.expression(node.value,environment)
        if not isinstance(owner.kind,ListType):
            return None
        _enable(g)
        if isinstance(node.slice,ast.Slice):
            return _slice(g,node,owner,environment)
        value = g.expression(node.slice,environment)
        container,index = g.temporary(),g.temporary()
        checked = _index(g,index,f"{container}.len()",node)
        return _Expression(f"{{ let {container}=&({owner.code}); let {index}={g.number(value)}; {container}[{checked}].clone() }}",owner.kind.element)
    if not isinstance(node,ast.Call):
        return None
    if isinstance(node.func,ast.Name) and node.func.id == "sorted":
        if len(node.args) != 1 or any(isinstance(argument,ast.Starred) for argument in node.args):
            raise _Unsupported
        from .native_iterators import Planner
        source = Planner(g).stream(node.args[0],environment)
        result = _collect(g,source,node,constructed=True)
        iterable_syntax = (isinstance(node.args[0],ast.GeneratorExp) or isinstance(node.args[0],ast.Call)
                           and isinstance(node.args[0].func,ast.Name)
                           and node.args[0].func.id in {"range","iter","map","filter","zip","enumerate","reversed"})
        if result.kind == "list_int" and not iterable_syntax:
            # Preserve the established arithmetic/list backend for native
            # integer sequences; structural lists use this generic path.
            return None
        lines = [source.setup + ("\n"+source.begin if source.eager else "")]
        options,reverse,key = _sort_options(g,node,environment,source.owners if source.eager else ())
        lines.extend(options)
        if not source.eager:
            lines.append(source.begin)
        owner = g.temporary()
        lines.append(f"let mut {owner}={result.code};")
        element = "int" if result.kind == "list_int" else result.kind.element
        lines.append(_sort_code(g,owner,element,node,environment,reverse,key))
        return _Expression("{\n"+"\n".join(lines)+f"\n{owner}\n}}",result.kind,length=result.length)
    if isinstance(node.func,ast.Name) and node.func.id == "len" and len(node.args) == 1 and not node.keywords:
        value = g.expression(node.args[0],environment)
        if isinstance(value.kind,ListType):
            return _Expression(_length(g,f"({value.code}).len()"),"int",value.length)
    if isinstance(node.func,ast.Attribute) and node.func.attr == "copy" and not node.args and not node.keywords:
        value = g.expression(node.func.value,environment)
        if isinstance(value.kind,ListType):
            _enable(g)
            return _Expression(g.at(f"native_typed_copy(&({value.code}))",node),value.kind,length=value.length)
    if isinstance(node.func,ast.Name) and node.func.id == "list" and len(node.args) == 1 and not node.keywords:
        if g.input_map(node.args[0],environment):
            return None
        from .native_iterators import Planner
        return _collect(g,Planner(g).stream(node.args[0],environment),node)
    return None


def try_statement(g,node,environment):
    printed = _print(g,node,environment)
    if printed is not None:
        return printed
    if isinstance(node,ast.Assign) and any(isinstance(target,(ast.Tuple,ast.List)) for target in node.targets):
        if g.input_map(node.value,environment):
            # The established unpack consumer converts at most N+1 values;
            # materializing a map here would change surplus-item errors.
            return None
        value = g.expression(node.value,environment)
        if isinstance(value.kind,ListType):
            if any(not isinstance(target,(ast.Tuple,ast.List)) for target in node.targets):
                raise _Unsupported
            from .native_iterators import Planner, Stream
            _enable(g)
            owner = g.temporary()
            code = value.code if value.owned else f"&({value.code})"
            lines = [f"let {owner}={code};"]
            for target in node.targets:
                count = len(target.elts)
                check = (f"native_big_unpack_length({owner}.len(),{count})" if not g.bits else
                         f"native_unpack_length({owner}.len(),{count})")
                lines.append(g.at(check,node)+";")
                values = tuple(_Expression(f"{owner}[{index}].clone()",value.kind.element)
                               for index in range(count))
                source = Stream("","",values,frozenset(),lambda *_:"",tupled=True)
                for name,item in Planner(g).target_values(target,source):
                    if name.id in g.iterating_lists:
                        raise _Unsupported
                    lines.append(f"{g.bind(name.id,item,environment)}={_clone(g,item,item.kind)};")
            return "\n".join(lines),environment
    if isinstance(node,ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0],ast.Subscript):
        target = node.targets[0]
        if not isinstance(target.value,ast.Name) or isinstance(target.slice,ast.Slice):
            return None
        binding = environment.get(target.value.id)
        if not isinstance(binding,_Binding) or not isinstance(binding.info,TypedListInfo):
            return None
        if target.value.id in g.iterating_lists:
            raise _Unsupported
        value = g.expression(node.value,environment)
        index = g.expression(target.slice,environment)
        item,offset,position = g.temporary(),g.temporary(),g.temporary()
        checked = _index(g,offset,f"{binding.slot}.len()",target,assignment=True)
        return (f"let {item}={_clone(g,value,binding.kind.element)};\nlet {offset}={g.number(index)};\n"
                f"let {position}={checked};\n{binding.slot}[{position}]={item};"),environment
    if not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
            and isinstance(node.value.func,ast.Attribute) and isinstance(node.value.func.value,ast.Name)):
        return None
    call = node.value
    target = call.func.value
    binding = environment.get(target.id)
    if not isinstance(binding,_Binding):
        return None
    empty = isinstance(binding.info,_ListInfo) and binding.info.length == 0
    if not isinstance(binding.info,TypedListInfo) and not empty:
        return None
    if call.func.attr not in {"append","clear","reverse","sort"} or call.keywords and call.func.attr != "sort":
        return None
    if target.id in g.iterating_lists:
        raise _Unsupported
    if call.func.attr == "append" and len(call.args) == 1:
        value = g.expression(call.args[0],environment)
        if empty and value.kind != "int":
            if not immutable(value.kind):
                raise _Unsupported
            kind = ListType(value.kind)
            probe = getattr(g,"_empty_list_probe",None)
            if probe is not None:
                probe.append((target.id,binding.slot,kind))
            slot = g.bind(target.id,_Expression("",kind,length=0),environment)
            initialization = f"{slot}=Vec::new();\n"
            length = 0
        elif isinstance(binding.info,TypedListInfo):
            kind,slot = binding.kind,binding.slot
            initialization = ""
            length = binding.info.length
        else:
            return None
        item = g.temporary()
        _enable(g)
        g.update_info(environment,target.id,TypedListInfo(kind,None if length is None else length+1))
        call = g.at(f"native_typed_push(&mut {slot},{item})",node)
        return f"{initialization}let {item}={_clone(g,value,kind.element)};\n{call};",environment
    if not isinstance(binding.info,TypedListInfo):
        return None
    if call.func.attr == "sort" and not call.args:
        options,reverse,key = _sort_options(g,call,environment,{target.id})
        code = _sort_code(g,binding.slot,binding.kind.element,node,environment,reverse,key)
        return "\n".join(options+[code]),environment
    if call.func.attr in {"clear","reverse"} and not call.args:
        if call.func.attr == "clear":
            g.update_info(environment,target.id,TypedListInfo(binding.kind,0))
        return f"{binding.slot}.{call.func.attr}();",environment
    return None


def _representation(g,value,*,quoted=False):
    kind,code = value.kind,value.code
    if kind == "str":
        if quoted:
            g.has_tuples = True
            return f"native_tuple_repr_str(&({code}))"
        return f"({code}).clone()"
    if kind == "bool":
        return f'(if {code} {{"True"}}else{{"False"}}).to_owned()'
    if kind in {"int","int_bool"}:
        return f"({code}).to_string()"
    if kind == "float":
        g.has_extended_scalars = True
        return f"native_float_text({code})"
    if kind == "bytes":
        from .native_stdio import _enable
        _enable(g)
        return f"native_bytes_repr(&({code}))"
    if isinstance(kind,TupleType):
        owner,result = g.temporary(),g.temporary()
        lines = [f"let {owner}=&({code});",f'let mut {result}=String::from("(");']
        for index,field in enumerate(kind.fields):
            if index:
                lines.append(f'{result}.push_str(", ");')
            representation = _representation(g,_Expression(f"{owner}.{index}",field),quoted=True)
            lines.append(f"{result}.push_str(&({representation}));")
        if len(kind.fields) == 1:
            lines.append(f"{result}.push(',');")
        lines.append(f"{result}.push(')'); {result}")
        return "{" + " ".join(lines) + "}"
    if kind == "list_int" or isinstance(kind,ListType):
        element = "int" if kind == "list_int" else kind.element
        owner,result,index,item = (g.temporary() for _ in range(4))
        representation = _representation(g,_Expression(f"(*{item})",element),quoted=True)
        return (f'{{let {owner}=&({code}); let mut {result}=String::from("["); '
                f'for ({index},{item}) in {owner}.iter().enumerate() {{if {index}>0 {{{result}.push_str(", ");}} '
                f"{result}.push_str(&({representation}));}} {result}.push(']'); {result}}}")
    raise _Unsupported


def _print(g,node,environment):
    if not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
            and isinstance(node.value.func,ast.Name) and node.value.func.id == "print"):
        return None
    call = node.value
    values = [(isinstance(argument,ast.Starred),g.expression(argument.value if isinstance(argument,ast.Starred) else argument,environment))
              for argument in call.args]
    if not any(isinstance(value.kind,(ListType,TupleType)) or not star and value.kind == "list_int" for star,value in values):
        return None
    separator,end,flush = " ","\n",False
    seen = set()
    for keyword in call.keywords:
        if keyword.arg in seen or keyword.arg not in {"sep","end","flush"} or not isinstance(keyword.value,ast.Constant):
            raise _Unsupported
        seen.add(keyword.arg)
        value = keyword.value.value
        if keyword.arg == "flush":
            if type(value) is not bool:
                raise _Unsupported
            flush = value
        else:
            if type(value) is not str:
                raise _Unsupported
            if keyword.arg == "sep":
                separator = value
            else:
                end = value
    lines = []
    arguments = []
    for star,value in values:
        temporary = g.temporary()
        code = f"&({value.code})" if (isinstance(value.kind,(ListType,TupleType)) or value.kind == "list_int") and not value.owned else value.code
        lines.append(f"let {temporary}={code};")
        arguments.append((star,_Expression(temporary,value.kind)))
    first = g.temporary()
    lines.append(f"let mut {first}=true;")
    def write(value):
        display = _representation(g,value)
        return (f"if !{first} {{native_output.push_str({_string(separator)});}} {first}=false;\n"
                f"native_output.push_str(&({display}));")
    for star,value in arguments:
        if not star:
            lines.append(write(value))
        elif value.kind == "list_int" or isinstance(value.kind,ListType):
            element = "int" if value.kind == "list_int" else value.kind.element
            item = g.temporary()
            lines.append(f"for {item} in {value.code}.iter() {{\n{write(_Expression(f'(*{item})',element))}\n}}")
        elif isinstance(value.kind,TupleType):
            for index,kind in enumerate(value.kind.fields):
                lines.append(write(_Expression(f"{value.code}.{index}",kind)))
        else:
            raise _Unsupported
    lines.append(f"native_output.push_str({_string(end)});")
    if flush:
        lines.append(g.at("native_flush_output(&mut native_output)",node)+";")
    return "\n".join(lines),environment


def refine_empty_lists(g,node,environment,pairs,owners=()):
    """Solve element constraints of uniquely owned, initially empty lists.

    The body proof is a compiler pass: it constructs no source values and
    executes no Python expressions. A second lowering uses the solved element
    type on every back edge, including the zero-iteration path.
    """
    targets = {target.id for target,_ in pairs}
    candidates = {name:binding for name,binding in environment.items()
                  if name not in targets and isinstance(binding,_Binding)
                  and isinstance(binding.info,_ListInfo) and binding.info.length == 0}
    if not candidates:
        return "",environment
    previous = getattr(g,"_empty_list_probe",None)
    constraints = []
    g._empty_list_probe = constraints
    inside = environment.copy()
    for target,value in pairs:
        inside[target.id] = _Binding(value.code,g.binding(value))
    context = {"label":g.temporary(),"edges":[]}
    depth = len(g.iterating_lists)
    g.iterating_lists.extend(set(owners)-targets)
    g.loops.append(context)
    try:
        try:
            g.statements(node.body,inside)
        except _Unsupported:
            # The actual proof is rerun below. A branch may lose its binding
            # before the common element type has been solved.
            pass
    finally:
        g.loops.pop()
        del g.iterating_lists[depth:]
        g._empty_list_probe = previous
    solved = {}
    for name,slot,kind in constraints:
        if name not in candidates or candidates[name].slot != slot:
            continue
        if name in solved:
            kind = join_types(solved[name],kind)
            if kind is None:
                raise _Unsupported
        solved[name] = kind
    if not solved:
        return "",environment
    result = environment.copy()
    lines = []
    for name,kind in solved.items():
        if previous is not None:
            previous.append((name,candidates[name].slot,kind))
        slot = g.bind(name,_Expression("",kind,length=0),result)
        lines.append(f"{slot}=Vec::new();")
    return "\n".join(lines),result


def stream(g,node,environment,planner,*,value=None):
    from .native_iterators import Stream
    value = g.expression(node,environment) if value is None else value
    if not isinstance(value.kind,ListType):
        return None
    if not immutable(value.kind.element):
        raise _Unsupported
    _enable(g)
    cursor = g.temporary()
    owners = {node.id} if isinstance(node,ast.Name) else set()
    if value.owned:
        owner = g.temporary()
        setup = f"let {owner}={value.code};"
    else:
        owner,setup = value.code,""
    fields = ((value.kind.element,"@.clone()",True),)
    return planner.leaf(setup,f"let {cursor}={owner}.iter();",cursor,fields,owners,length=value.length)
