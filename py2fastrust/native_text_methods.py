"""Proved Rust string operations and eager, typed string joining."""
import ast

from .native import _Expression, _Unsupported


HELPERS = r'''
fn native_text_whitespace(c:char)->bool {c.is_whitespace()||('\u{1c}'..='\u{1f}').contains(&c)}
fn native_text_strip(text:&str, characters:Option<&str>, left:bool, right:bool)->String {
    let predicate=|c:char|characters.map_or_else(||native_text_whitespace(c),|characters|characters.contains(c));
    let text=if left {text.trim_start_matches(predicate)}else{text};
    let text=if right {text.trim_end_matches(predicate)}else{text};
    text.to_owned()
}
fn native_text_window(text:&str,start:Option<i128>,stop:Option<i128>)->Option<&str> {
    let ascii=text.is_ascii();
    let length=if ascii {text.len()}else{text.chars().count()};
    let length=length as i128;
    let bound=|value:i128|if value<0 {value.saturating_add(length).max(0)}else{value};
    let start=start.map(bound).unwrap_or(0);
    let stop=stop.map(bound).unwrap_or(length).min(length);
    if start>length||start>stop {return None;}
    let byte=|index:i128|if ascii {index as usize}
        else{text.char_indices().nth(index as usize).map_or(text.len(),|(index,_)|index)};
    Some(&text[byte(start)..byte(stop)])
}
fn native_text_count(text:&str,pattern:&str,start:Option<i128>,stop:Option<i128>)->usize {
    match native_text_window(text,start,stop) {
        None=>0,
        Some(part)=>if pattern.is_empty(){part.chars().count()+1}else{part.matches(pattern).count()},
    }
}
fn native_text_join_push(values:&mut Vec<String>,value:String)->Result<(),String> {
    values.try_reserve(1).map_err(|_|"MemoryError: string sequence is too large".to_owned())?;
    values.push(value);Ok(())
}
fn native_text_join(separator:&str,values:Vec<String>)->Result<String,String> {
    let separators=values.len().saturating_sub(1).checked_mul(separator.len())
        .ok_or_else(||"OverflowError: join() result is too long for a Python string".to_owned())?;
    let length=values.iter().try_fold(separators,|total,value|total.checked_add(value.len()))
        .filter(|length|*length<=isize::MAX as usize)
        .ok_or_else(||"OverflowError: join() result is too long for a Python string".to_owned())?;
    let mut result=String::new();
    result.try_reserve_exact(length).map_err(|_|"MemoryError: string is too large".to_owned())?;
    for (index,value) in values.into_iter().enumerate() {
        if index!=0 {result.push_str(separator);}
        result.push_str(&value);
    }
    Ok(result)
}
'''


def try_text_method(generator, node, environment):
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"strip", "lstrip", "rstrip", "count", "join"}):
        return None
    g = generator
    owner = g.read_expression(node.func.value, environment)
    if owner.kind != "str":
        return None
    if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
        raise _Unsupported
    name = node.func.attr
    receiver = g.temporary()
    lines = [f"let {receiver}:&str={owner.code};"]
    g.has_text_methods = True
    if name in {"strip", "lstrip", "rstrip"}:
        if len(node.args) > 1:
            raise _Unsupported
        chars = "None"
        if node.args and not (isinstance(node.args[0], ast.Constant) and node.args[0].value is None):
            value = g.read_expression(node.args[0], environment)
            if value.kind != "str":
                raise _Unsupported
            target = g.temporary()
            lines.append(f"let {target}:&str={value.code};")
            chars = f"Some({target})"
        expression = f"native_text_strip({receiver},{chars},{str(name!='rstrip').lower()},{str(name!='lstrip').lower()})"
        kind = "str"
    elif name == "count":
        if not 1 <= len(node.args) <= 3:
            raise _Unsupported
        needle = g.read_expression(node.args[0], environment)
        if needle.kind != "str":
            raise _Unsupported
        pattern = g.temporary()
        lines.append(f"let {pattern}:&str={needle.code};")
        bounds = []
        for bound in node.args[1:]:
            if isinstance(bound, ast.Constant) and bound.value is None:
                bounds.append("None")
                continue
            value = g.expression(bound, environment)
            name = g.temporary()
            lines.append(f"let {name}={g.number(value)};")
            bounds.append(f"Some({name} as i128)")
        bounds += ["None"] * (2-len(bounds))
        expression = f"native_text_count({receiver},{pattern},{','.join(bounds)}) as NativeInt"
        kind = "int"
    else:
        if len(node.args) != 1:
            raise _Unsupported
        from .native_iterators import Planner
        source = node.args[0]
        if isinstance(source, (ast.List, ast.Tuple)) and not source.elts:
            expression = "String::new()"
        else:
            stream = Planner(g).stream(source, environment)
            if stream.tupled or len(stream.values) != 1 or stream.values[0].kind != "str":
                raise _Unsupported
            values = g.temporary()
            # Python join() exhausts its iterable before constructing the
            # result. Retain that timing for generator errors and side effects.
            lines.append(stream.construct())
            lines.append(f"let mut {values}=Vec::<String>::new();")
            push = g.at(f"native_text_join_push(&mut {values},{stream.values[0].code})", node) + ";"
            lines.append(stream.emit(push, g.scope_name(), node.lineno))
            expression = g.at(f"native_text_join({receiver},{values})", node)
        kind = "str"
    return _Expression("{ " + " ".join(lines) + f" {expression} }}", kind)
