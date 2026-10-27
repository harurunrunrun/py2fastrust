"""Typed flat-list and Unicode string slicing with checked structural indices."""
import ast

from .native import _Expression, _Unsupported


SLICE_HELPERS = r'''
struct NativeSlice { cursor:i128, step:i128, remaining:usize }
impl Iterator for NativeSlice {
    type Item=usize;
    fn next(&mut self)->Option<usize> {
        if self.remaining==0 {return None;}
        let index=usize::try_from(self.cursor).expect("validated slice index");
        self.remaining-=1;
        if self.remaining!=0 {
            self.cursor=self.cursor.checked_add(self.step).expect("bounded slice progress");
        }
        Some(index)
    }
    fn size_hint(&self)->(usize,Option<usize>) {(self.remaining,Some(self.remaining))}
}
impl ExactSizeIterator for NativeSlice {}
fn native_slice_indices(length:usize,start:Option<i128>,stop:Option<i128>,step:Option<i128>)->Result<NativeSlice,String> {
    let step=step.unwrap_or(1);
    if step==0 {return Err("ValueError: slice step cannot be zero".into());}
    let length=i128::try_from(length).map_err(|_|"OverflowError: sequence length is too large".to_string())?;
    let forward=step>0;
    let lower=if forward {0}else{-1};
    let upper=if forward {length}else{length-1};
    let bound=|value:i128| {
        let value=if value<0 {value.saturating_add(length)}else{value};
        value.clamp(lower,upper)
    };
    let start=start.map(bound).unwrap_or(if forward {0}else{length-1});
    let stop=stop.map(bound).unwrap_or(if forward {length}else{-1});
    let distance=if forward && start<stop {stop-start}
                 else if !forward && start>stop {start-stop}else{0};
    let count=if distance==0 {0}else{1+(distance as u128-1)/step.unsigned_abs()};
    let remaining=usize::try_from(count).map_err(|_|"OverflowError: slice length is too large".to_string())?;
    let limit=length.checked_add(1).ok_or_else(||"OverflowError: sequence length is too large".to_string())?;
    let bounded_step=step.clamp(-limit,limit);
    Ok(NativeSlice {cursor:start,step:bounded_step,remaining})
}
fn native_flat_slice<T:Clone>(values:&[T],indices:NativeSlice)->Vec<T> {
    let mut result=Vec::with_capacity(indices.len());
    for index in indices {result.push(values[index].clone());}
    result
}
fn native_text_slice(text:&str,indices:NativeSlice,ascii:bool)->String {
    let mut result=String::with_capacity(indices.len());
    if ascii {
        let bytes=text.as_bytes();
        for index in indices {result.push(bytes[index] as char);}
    } else {
        let characters:Vec<char>=text.chars().collect();
        for index in indices {result.push(characters[index]);}
    }
    result
}
'''


def try_slice(generator, node, environment):
    if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
        return None
    read = getattr(generator, "read_expression", generator.expression)
    owner = read(node.value, environment)
    if owner.kind not in {"list_int", "str"}:
        # Nested mutable rows require shared handles for Python's shallow copy.
        raise _Unsupported
    generator.has_slices = True
    container = generator.temporary()
    if owner.kind == "str":
        lines = [f"let {container}:&str={owner.code};"]
    else:
        generator.has_lists = True
        lines = [f"let {container}:&[NativeInt]=&({owner.code});"]
    bounds = []
    constants = []
    known = True
    for expression in (node.slice.lower, node.slice.upper, node.slice.step):
        if expression is None or isinstance(expression, ast.Constant) and expression.value is None:
            bounds.append("None")
            constants.append(None)
            continue
        value = generator.expression(expression, environment)
        number = generator.number(value)
        name = generator.temporary()
        lines.append(f"let {name}={number};")
        if generator.bits:
            normalized = f"({name}) as i128"
        else:
            normalized = (f"{name}.to_i128().unwrap_or_else(||if {name}.is_negative()"
                          "{i128::MIN}else{i128::MAX})")
        bounds.append(f"Some({normalized})")
        constants.append(value.constant)
        known &= value.constant is not None
    length = f"{container}.len()"
    ascii_name = None
    if owner.kind == "str":
        ascii_name = generator.temporary()
        lines.append(f"let {ascii_name}={container}.is_ascii();")
        length = f"if {ascii_name} {{{container}.len()}}else{{{container}.chars().count()}}"
    plan = generator.temporary()
    call = generator.at(f"native_slice_indices({length},{','.join(bounds)})", node)
    lines.append(f"let {plan}={call};")
    result = (f"native_text_slice({container},{plan},{ascii_name})" if owner.kind == "str"
              else f"native_flat_slice({container},{plan})")
    result_length = None
    if owner.length is not None and known:
        try:
            result_length = len(range(*slice(*constants).indices(owner.length)))
        except ValueError:
            pass
    return _Expression("{ " + " ".join(lines) + f" {result} }}", owner.kind,
                       owned=True, length=result_length)


def sorted_list(generator, node, environment):
    """Make a new integer list, evaluating the iterable before keyword values."""
    if len(node.args) != 1 or any(isinstance(arg, ast.Starred) for arg in node.args):
        raise _Unsupported
    value = generator.expression(node.args[0], environment)
    if value.kind != "list_int":
        raise _Unsupported
    owner, result = generator.temporary(), generator.temporary()
    # A named input must remain available after sorted(). Its reference is
    # captured before keywords, and its elements are copied only afterwards.
    code = value.code if value.owned else f"&({value.code})"
    owner_type = "Vec<NativeInt>" if value.owned else "&[NativeInt]"
    lines = [f"let {owner}:{owner_type}={code};"]
    reverse = "false"
    seen = set()
    for keyword in node.keywords:
        if keyword.arg not in {"key", "reverse"} or keyword.arg in seen:
            raise _Unsupported
        seen.add(keyword.arg)
        if keyword.arg == "key":
            if not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None):
                raise _Unsupported
        else:
            direction = generator.expression(keyword.value, environment)
            if direction.kind not in {"bool", "int", "int_bool"}:
                raise _Unsupported
            name = generator.temporary()
            lines.append(f"let {name}={generator.truth(direction)};")
            reverse = name
    generator.has_lists = True
    lines.append(f"let mut {result}=" + (owner if value.owned else f"{owner}.to_vec()") + ";")
    lines.append(f"{result}.sort_unstable(); if {reverse} {{{result}.reverse();}}")
    return _Expression("{ " + " ".join(lines) + f" {result} }}", "list_int", length=value.length)
