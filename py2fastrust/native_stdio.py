"""Trusted standard-input references and typed text/byte reads.

Aliases are compile-time facts. Reads keep the shared StandardInput decoder and
binary buffer; no spelling is rewritten to Python's distinct input() operation.
"""
import ast
from dataclasses import dataclass

from .native import _Binding, _Expression, _Function, _Unsupported, _string, _text_expression


@dataclass(frozen=True)
class _IOReference:
    name: str
    binary: bool = False
    line: bool = False
    _native_reference = True


SYS = _IOReference("sys")
TEXT = _IOReference("stdin")
BINARY = _IOReference("buffer", True)
READERS = {(binary, line): _IOReference("reader", binary, line)
           for binary in (False, True) for line in (False, True)}


HELPERS = r'''
fn native_stdin_read_text(reader:&mut StandardInput,count:Option<usize>,line:bool)->Result<String,String> {
    let mut output=String::new();
    reader.read_text_into(&mut output,count,line).map_err(StandardInputError::native_message)?;
    Ok(output)
}
fn native_stdin_read_bytes(reader:&mut StandardInput,count:Option<usize>,line:bool)->Result<Vec<u8>,String> {
    reader.read_binary(count,line).map_err(StandardInputError::native_message)
}
fn native_io_count(value:&Int,binary_read:bool)->Result<Option<usize>,String> {
    let value=value.to_i128().and_then(|number|isize::try_from(number).ok())
        .ok_or_else(||"OverflowError: cannot fit 'int' into an index-sized integer".to_string())?;
    if binary_read&&value< -1{return Err("ValueError: read length must be non-negative or -1".into());}
    Ok(if value<0{None}else{Some(value as usize)})
}
fn native_bytes_space(byte:u8)->bool {matches!(byte,9..=13|32)}
fn native_bytes_repr(value:&[u8])->String {
    use std::fmt::Write as _;
    let quote=if value.contains(&b'\'')&&!value.contains(&b'"'){b'"'}else{b'\''};
    let mut output=String::from("b");output.push(quote as char);
    for &byte in value {
        match byte {
            b'\\'=>output.push_str("\\\\"),b'\n'=>output.push_str("\\n"),
            b'\r'=>output.push_str("\\r"),b'\t'=>output.push_str("\\t"),
            byte if byte==quote=>{output.push('\\');output.push(byte as char);},
            32..=126=>output.push(byte as char),
            _=>write!(&mut output,"\\x{:02x}",byte).unwrap(),
        }
    }
    output.push(quote as char);output
}
fn native_io_parse_bytes(value:&[u8])->Result<Int,String> {
    let invalid=||format!("ValueError: invalid literal for int() with base 10: {:.200}",native_bytes_repr(value));
    if value.iter().any(|&byte|byte>=127||(byte<32&&!native_bytes_space(byte))) {return Err(invalid());}
    Int::parse(std::str::from_utf8(value).unwrap(),10).map_err(|_|invalid())
}
fn native_io_parse_text(value:&str)->Result<Int,String> {
    // C0 separators belong to str.split whitespace, but int() rejects them.
    if value.chars().any(|c|('\u{1c}'..='\u{1f}').contains(&c)) {
        return Err("ValueError: invalid literal for int()".into());
    }
    Int::parse(value,10)
}
fn native_io_number(value:Int)->NativeInt {__NATIVE_NUMBER__}
fn native_bytes_decode(value:&[u8])->Result<String,String> {
    std::str::from_utf8(value).map(str::to_owned).map_err(|_|"UnicodeDecodeError: bytes are not valid UTF-8".to_string())
}
fn native_bytes_strip(value:&[u8],left:bool,right:bool)->Vec<u8> {
    let mut start=0;let mut stop=value.len();
    if left {while start<stop&&native_bytes_space(value[start]){start+=1;}}
    if right {while stop>start&&native_bytes_space(value[stop-1]){stop-=1;}}
    value[start..stop].to_vec()
}
fn native_bytes_get(value:&[u8],index:i128)->Result<NativeInt,String> {
    let index=if index<0 {index.saturating_add(value.len() as i128)}else{index};
    let index=usize::try_from(index).map_err(|_|"IndexError: index out of range".to_string())?;
    value.get(index).map(|byte|native_io_number(Int::from_i128(*byte as i128)))
        .ok_or_else(||"IndexError: index out of range".into())
}
'''


def render_helpers(bits,*,integer_runtime=True,input_runtime=True):
    source=HELPERS.replace("__NATIVE_NUMBER__", "value" if not bits else "value.to_i128().unwrap() as NativeInt")
    if bits:
        first=source.index("fn native_io_parse_bytes(");last=source.index("fn native_io_number(",first)
        source=source[:first]+r'''fn native_io_parse_bytes(value:&[u8])->Result<NativeInt,String> {
    native_fixed_parse_ascii(value).ok_or_else(||format!("ValueError: invalid literal for int() with base 10: {:.200}",native_bytes_repr(value)))
}
fn native_io_parse_text(value:&str)->Result<NativeInt,String> {native_parse_integer(value)}
'''+source[last:]
    from .rust_pruning import _lex, _parse
    excluded=set()
    if bits and not integer_runtime:
        excluded.update({"native_io_count","native_io_number","native_bytes_get"})
    if not input_runtime:
        excluded.update({"native_stdin_read_text","native_stdin_read_bytes"})
    if excluded:
        tokens,comments,pairs=_lex(source)
        source="\n".join(source[item.start:item.end]for item in _parse(source,tokens,comments,pairs)
                         if item.name not in excluded)
    return source


def reference(node,environment):
    from .references import resolve_static_callable
    value=resolve_static_callable(node,environment,core_builtins=())
    return value if isinstance(value,_IOReference)else None


def _global_reference(generator,node,environment):
    while isinstance(node,ast.Attribute):
        node=node.value
    if (generator.function is not None and isinstance(node,ast.Name)
            and node.id not in generator.function.local_names
            and isinstance(environment.get(node.id),_IOReference)):
        generator.function.required.add(node.id)


def _enable(generator,*,integer_runtime=False):
    generator.has_stdio=True
    generator.needs_integer_runtime |= integer_runtime


def _number(generator,code):
    # Parsing wrappers already return the selected NativeInt in every mode.
    return code


def _size_number(generator,value):
    number=generator.number(value)
    return number if not generator.bits else f"Int::from_i128(({number}) as i128)"






def try_expression(generator,node,environment):
    from .native_builtin_values import try_expression as builtin_value
    canonical=builtin_value(generator,node,environment)
    if canonical is not None:return canonical
    if isinstance(node,ast.Call):
        from .references import BuiltinIdentity,callable_reference
        target=callable_reference(generator,node.func,environment)
        if isinstance(target,BuiltinIdentity)and target.name=="input":
            from .call_semantics import FunctionSignature
            from .native_stream_plans import context
            normalizer=context(generator,environment)
            signature=FunctionSignature.declaration()
            from .call_semantics import CallBindingError
            try:
                normalizer.bind(normalizer.invocation(node),signature)
            except CallBindingError as error:
                raise _Unsupported from error
            generator.has_input=True
            if generator.bits:generator.has_extended_scalars=True
            else:generator.has_big_text=True
            return _text_expression(generator.at("native_input.line(&mut native_output)",node))
    local_names=generator.function.local_names if generator.function is not None else generator.entry_local_names
    direct_input=(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id == "input")
    wrapped_input=(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id == "int"
                   and len(node.args)==1 and isinstance(node.args[0],ast.Call)
                   and isinstance(node.args[0].func,ast.Name) and node.args[0].func.id == "input")
    if ((direct_input or wrapped_input) and "input" in local_names and "input" not in environment):
        raise _Unsupported
    if direct_input and "input" in environment and reference(node.func,environment) not in READERS.values():
        raise _Unsupported
    if isinstance(node,ast.Name):
        binding=environment.get(node.id)
        if isinstance(binding,_Binding) and binding.kind == "bytes":
            return _Expression(f"({binding.slot}).clone()",binding.kind)
    if isinstance(node,ast.Constant):
        if type(node.value) is bytes:
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            return _Expression(literal.rust_atom(generator.literal,_string),literal.kind,length=len(literal.value))
    if isinstance(node,ast.Call):
        reader=reference(node.func,environment)
        if reader is not None and reader.name == "reader":
            if len(node.args)>1 or node.keywords:
                raise _Unsupported
            _global_reference(generator,node.func,environment)
            _enable(generator)
            generator.has_input=True
            setup=""
            count="None"
            if node.args:
                argument=node.args[0]
                if isinstance(argument,ast.Constant) and argument.value is None:
                    if reader.line and not reader.binary:
                        call=generator.at('Err::<String,String>("TypeError: None cannot be interpreted as an integer".into())',node)
                        return _text_expression(call)
                else:
                    value=generator.expression(argument,environment)
                    name=generator.temporary()
                    size=generator.at(f"native_io_count(&{name},{str(reader.binary and not reader.line).lower()})",node)
                    generator.needs_integer_runtime=True
                    setup=f"let {name}={_size_number(generator,value)};"
                    count=size
            kind="bytes" if reader.binary else "text"
            call=generator.at(f"native_stdin_read_{kind}(&mut native_input.reader,{count},{str(reader.line).lower()})",node)
            return (_Expression(f"{{{setup} {call}}}","bytes")if reader.binary else _text_expression(f"{{{setup} {call}}}"))
        if isinstance(node.func,ast.Name) and node.func.id in {"int","len","bool"} and len(node.args)==1 and not node.keywords:
            argument=node.args[0]
            if (isinstance(argument,ast.Call) and isinstance(argument.func,ast.Name)
                    and argument.func.id == "input" and "input" not in environment):
                return None
            value=getattr(generator,"read_expression",generator.expression)(argument,environment)
            if value.kind in {"str","bytes"}:
                if node.func.id == "len":
                    from .native_characters import length as character_length
                    projected=character_length(generator,value)
                    if projected is not None:return projected
                    from .native_cached_text import text_length
                    length=text_length(value,generator.string_mode)if value.kind=="str"else f"({value.code}).len()"
                    code=f"Int::from_i128(({length}) as i128)" if not generator.bits else f"(({length}) as NativeInt)"
                    return _Expression(code,"int",value.length)
                if node.func.id == "bool":
                    return _Expression(generator.truth(value),"bool")
                _enable(generator)
                kind="bytes" if value.kind == "bytes" else "text"
                from .native_integer_parsing import parse_value
                code=parse_value(generator,value,node) or generator.at(f"native_io_parse_{kind}(&({value.code}))",node)
                return _Expression(_number(generator,code),"int")
        if isinstance(node.func,ast.Attribute):
            method=node.func.attr
            if method in {"decode","strip","rstrip","lstrip"}:
                value=generator.expression(node.func.value,environment)
                if value.kind != "bytes":
                    return None
                if node.keywords:
                    raise _Unsupported
                _enable(generator)
                if method == "decode":
                    if len(node.args)>1 or node.args and not (isinstance(node.args[0],ast.Constant) and node.args[0].value in {"utf-8","utf8"}):
                        raise _Unsupported
                    return _text_expression(generator.at(f"native_bytes_decode(&({value.code}))",node))
                if node.args:
                    raise _Unsupported
                return _Expression(f"native_bytes_strip(&({value.code}),{str(method!='rstrip').lower()},{str(method!='lstrip').lower()})","bytes")
    if isinstance(node,ast.Subscript) and not isinstance(node.slice,ast.Slice):
        value=generator.expression(node.value,environment)
        if value.kind == "bytes":
            _enable(generator,integer_runtime=True)
            index=generator.expression(node.slice,environment)
            owner,offset=generator.temporary(),generator.temporary()
            number=generator.number(index)
            index=(f"{offset}.to_i128().unwrap_or_else(||if {offset}.is_negative(){{i128::MIN}}else{{i128::MAX}})"
                   if not generator.bits else f"({offset}) as i128")
            call=generator.at(f"native_bytes_get(&{owner},{index})",node)
            return _Expression(f"{{let {owner}={value.code}; let {offset}={number}; {call}}}","int")
    return None


def try_statement(generator,node,environment):
    from .references import capture_builtin_assignment
    captured=capture_builtin_assignment(generator,node,environment)
    if captured is not None:return captured
    if isinstance(node,(ast.Import,ast.ImportFrom)):
        if isinstance(node,ast.Import):
            if any(alias.name != "sys" for alias in node.names):
                return None
            aliases=[(alias.asname or "sys",SYS) for alias in node.names]
        elif node.module == "sys" and not node.level:
            if any(alias.name != "stdin" for alias in node.names):
                raise _Unsupported
            aliases=[(alias.asname or "stdin",TEXT) for alias in node.names]
        else:
            return None
        if "sys" not in generator.trusted_imports:
            raise _Unsupported
        for name,value in aliases:
            if name in generator.BUILTINS and name != "input":
                raise _Unsupported
            environment[name]=value
        return "",environment
    if isinstance(node,ast.Assign):
        value=reference(node.value,environment)
        if value is not None:
            if not all(isinstance(target,ast.Name) and target.id not in generator.iterating_lists
                       and (target.id not in generator.BUILTINS or target.id == "input") for target in node.targets):
                raise _Unsupported
            _global_reference(generator,node.value,environment)
            for target in node.targets:
                environment[target.id]=value
            return "",environment
        if isinstance(node.value,ast.Name) and isinstance(environment.get(node.value.id),_Function):
            return None
        if all(isinstance(target,ast.Name) for target in node.targets):
            value=generator.expression(node.value,environment)
            if value.kind == "bytes":
                temp=generator.temporary()
                lines=[f"let {temp}={value.code};"]
                for index,target in enumerate(node.targets):
                    if target.id in generator.iterating_lists:
                        raise _Unsupported
                    assigned=temp if index+1==len(node.targets) else f"{temp}.clone()"
                    lines.append(f"{generator.bind(target.id,value,environment)}={assigned};")
                return "\n".join(lines),environment
    if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id == "print":
        call=node.value
        if any(isinstance(argument,ast.Starred) for argument in call.args):
            return None
        values=[generator.expression(argument,environment) for argument in call.args]
        if not any(value.kind == "bytes" for value in values):
            return None
        if any(value.kind not in {"int","bool","int_bool","str","bytes","float"} for value in values):
            # Structural values use the common typed printer, which also
            # renders bytes. Reuse the already lowered ordered arguments.
            from .native_typed_lists import _print
            printed=_print(generator,node,environment,values=tuple((False,value)for value in values))
            if printed is None:raise _Unsupported
            return printed
        separator,end,flush=" ","\n",False
        seen=set()
        for keyword in call.keywords:
            if keyword.arg in seen or keyword.arg not in {"sep","end","flush"} or not isinstance(keyword.value,ast.Constant):
                raise _Unsupported
            seen.add(keyword.arg)
            if keyword.arg == "flush":
                if type(keyword.value.value) is not bool:raise _Unsupported
                flush=keyword.value.value
            else:
                if type(keyword.value.value) is not str:raise _Unsupported
                if keyword.arg == "sep":separator=keyword.value.value
                else:end=keyword.value.value
        names=[generator.temporary() for _ in values]
        lines=[f"let {name}={value.code};" for name,value in zip(names,values)]
        for index,(name,value) in enumerate(zip(names,values)):
            if index:lines.append(f"native_output.push_str({_string(separator)});")
            if value.kind == "bytes":
                _enable(generator)
                name=f"native_bytes_repr(&{name})"
            elif value.kind == "bool":name=f'if {name}{{"True"}}else{{"False"}}'
            elif value.kind == "float":name=f"native_float_text({name})"
            lines.append(f'write!(&mut native_output,"{{}}",{name}).unwrap();')
        lines.append(f"native_output.push_str({_string(end)});")
        if flush:lines.append(generator.at("native_flush_output(&mut native_output)",node)+";")
        return "\n".join(lines),environment
    return None

def comparison(generator,node,values):
    if len(node.ops)!=1 or type(node.ops[0]) not in {ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE}:
        raise _Unsupported
    left,right=values
    if left.kind != right.kind:
        if not isinstance(node.ops[0],(ast.Eq,ast.NotEq)):
            raise _Unsupported
        first,second=generator.temporary(),generator.temporary()
        return _Expression(f"{{let {first}=&({left.code}); let {second}=&({right.code}); {str(isinstance(node.ops[0],ast.NotEq)).lower()}}}","bool")
    op={ast.Eq:"==",ast.NotEq:"!=",ast.Lt:"<",ast.LtE:"<=",ast.Gt:">",ast.GtE:">="}[type(node.ops[0])]
    return _Expression(f"({left.code}) {op} ({right.code})","bool")
