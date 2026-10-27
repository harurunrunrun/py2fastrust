"""Select emitted text helpers for the explicitly configured string model.

ASCII mode indexes bytes directly. Unicode mode preserves Python code-point
indices. Selection uses Rust tokens, so Python provenance and Rust literals are
never rewritten as if they were helper definitions.
"""

from .rust_pruning import _lex


_ASCII_HELPERS = {
    "native_string_item": r'''
fn native_string_item(value:&str,index:NativeInt)->Result<String,String> {
    let length=value.len();
    let index=if index<0 {
        let magnitude=index.unsigned_abs() as u128;
        if magnitude>length as u128 {return Err("IndexError: string index out of range".into());}
        length-magnitude as usize
    } else {usize::try_from(index).unwrap_or(usize::MAX)};
    let byte=value.as_bytes().get(index).ok_or_else(||"IndexError: string index out of range".to_owned())?;
    Ok((*byte as char).to_string())
}
''',
    "native_big_text_item": r'''
fn native_big_text_item(text:&str,index:&Int)->Result<String,String> {
    let error=||"IndexError: string index out of range".to_owned();
    let index=index.to_i128().ok_or_else(error)?;
    let index=if index<0 {index.checked_add(text.len() as i128).ok_or_else(error)?}else{index};
    let index=usize::try_from(index).map_err(|_|error())?;
    let byte=text.as_bytes().get(index).ok_or_else(error)?;
    Ok((*byte as char).to_string())
}
''',
    "class_string_get": r'''
fn class_string_get(value:&str,index:&NativeInt)->Result<String,String> {
    let index=class_index(index,value.len()).map_err(|_|"IndexError: string index out of range".to_string())?;
    Ok((value.as_bytes()[index] as char).to_string())
}
''',
    "native_text_window": r'''
fn native_text_window(text:&str,start:Option<i128>,stop:Option<i128>)->Option<&str> {
    let length=text.len() as i128;
    let bound=|value:i128|if value<0 {value.saturating_add(length).max(0)}else{value};
    let start=start.map(bound).unwrap_or(0);
    let stop=stop.map(bound).unwrap_or(length).min(length);
    if start>length||start>stop {return None;}
    text.get(start as usize..stop as usize)
}
''',
    "native_text_count": r'''
fn native_text_count(text:&str,pattern:&str,start:Option<i128>,stop:Option<i128>)->usize {
    match native_text_window(text,start,stop) {
        None=>0,
        Some(part)=>if pattern.is_empty(){part.len()+1}else{part.matches(pattern).count()},
    }
}
''',
    "native_text_slice": r'''
fn native_text_slice(text:&str,indices:NativeSlice,_ascii:bool)->String {
    let mut result=String::with_capacity(indices.len());
    let bytes=text.as_bytes();
    for index in indices {result.push(bytes[index] as char);}
    result
}
''',
}

_BORROW_HELPERS = {
    "native_string_item_ref": r'''
fn native_string_item_ref(value:&str,index:NativeInt)->Result<&str,String> {
    let index=index as i128;
    let index=if index<0 {index.saturating_add(value.len() as i128)}else{index};
    let error=||"IndexError: string index out of range".to_owned();
    let index=usize::try_from(index).ok().filter(|index|*index<value.len()).ok_or_else(error)?;
    value.get(index..index+1).ok_or_else(error)
}
''',
    "native_big_text_item_ref": r'''
fn native_big_text_item_ref<'a>(value:&'a str,index:&Int)->Result<&'a str,String> {
    let error=||"IndexError: string index out of range".to_owned();
    let index=index.to_i128().ok_or_else(error)?;
    let index=if index<0 {index.saturating_add(value.len() as i128)}else{index};
    let index=usize::try_from(index).ok().filter(|index|*index<value.len()).ok_or_else(error)?;
    value.get(index..index+1).ok_or_else(error)
}
''',
}


def apply_text_policy(source: str, string_mode: str = "ascii") -> str:
    """Specialize internal helper definitions before Rust reachability pruning."""
    if string_mode == "unicode":
        return source
    if string_mode != "ascii":
        raise ValueError(f"unknown string mode: {string_mode}")
    tokens, _comments, pairs = _lex(source)
    edits = []
    for index, token in enumerate(tokens[:-1]):
        if token.text != "fn":
            continue
        name = tokens[index + 1].text
        replacement = _ASCII_HELPERS.get(name)
        if replacement is None:
            continue
        cursor = index + 2
        while cursor < len(tokens) and tokens[cursor].text != "{":
            if tokens[cursor].text in {"(", "["}:
                cursor = pairs[cursor] + 1
            else:
                cursor += 1
        if cursor == len(tokens):
            raise ValueError(f"missing body for internal text helper: {name}")
        edits.append((token.start, tokens[pairs[cursor]].end, replacement.strip()))
    for start, end, replacement in reversed(edits):
        source = source[:start] + replacement + source[end:]
    identifiers = {token.text for token in tokens if token.kind == "identifier"}
    for name, helper in _BORROW_HELPERS.items():
        if name in identifiers:
            source += "\n" + helper
    return source
