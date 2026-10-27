"""Assemble shared immutable string storage and metadata-aware consumers."""
from importlib.resources import files
from .rust_pruning import _lex


def text_length(value,string_mode):
    """Retain the source-level nonnegative, index-sized string length range."""
    if string_mode=="ascii":
        code=value.text_view if value.text_view is not None else value.code
        raw=f"({code}).len()"
    else:raw=f"({value.code}).codepoint_len()"
    return f"native_text_index_size({raw})"


HELPERS=r'''
#[inline]
fn native_text_index_size(length:usize)->usize {
    // A valid Rust str allocation (and its codepoint count) is index-sized.
    assert!(length<=isize::MAX as usize,"native text length exceeds the allocation index range");
    length
}
fn native_text_codepoint(value:&NativeText,index:i128)->Result<u32,String> {
    if NATIVE_TEXT_UNICODE{return value.codepoint_at(index);}
    let index=if index<0{index.saturating_add(value.byte_len()as i128)}else{index};
    let index=usize::try_from(index).ok().filter(|index|*index<value.byte_len())
        .ok_or_else(||"IndexError: string index out of range".to_string())?;
    Ok(value.as_bytes()[index]as u32)
}
impl From<&NativeText> for NativeText {
    fn from(value:&NativeText)->Self {value.clone()}
}
fn native_text_get(value:&NativeText,index:i128)->Result<NativeText,String> {
    if NATIVE_TEXT_UNICODE {return value.char_at(index);}
    let length=value.byte_len() as i128;
    let index=if index<0 {index.saturating_add(length)}else{index};
    let index=usize::try_from(index).ok().filter(|index|*index<value.byte_len())
        .ok_or_else(||"IndexError: string index out of range".to_string())?;
    Ok(NativeText::from(value.as_bytes()[index]as char))
}
'''

_REPLACEMENTS={
'native_string_item':r'''
fn native_string_item(value:&NativeText,index:NativeInt)->Result<NativeText,String> {
    native_text_get(value,index as i128)
}
''',
'native_big_text_item':r'''
fn native_big_text_item(value:&NativeText,index:&Int)->Result<NativeText,String> {
    native_text_get(value,index.to_i128().ok_or_else(||"IndexError: string index out of range".to_string())?)
}
''',
'class_string_get':r'''
fn class_string_get(value:&NativeText,index:&NativeInt)->Result<NativeText,String> {
    let length=if NATIVE_TEXT_UNICODE {value.codepoint_len()}else{value.byte_len()};
    let index=class_index(index,length).map_err(|_|"IndexError: string index out of range".to_string())?;
    native_text_get(value,index as i128)
}
''',
'native_string_add':r'''
fn native_string_add(left:NativeText,right:&str)->Result<NativeText,String> {
    let mut left=left.into_string();
    left.try_reserve(right.len()).map_err(|_|"MemoryError: string is too large".to_string())?;
    left.push_str(right);Ok(NativeText::from(left))
}
''',
'native_big_text_add':r'''
fn native_big_text_add(left:NativeText,right:&str)->Result<NativeText,String> {
    let mut left=left.into_string();
    left.try_reserve(right.len()).map_err(|_|"MemoryError: string is too large".to_string())?;
    left.push_str(right);Ok(NativeText::from(left))
}
''',
'class_string_add':r'''
fn class_string_add(left:NativeText,right:&str)->Result<NativeText,String> {
    let mut left=left.into_string();
    left.try_reserve(right.len()).map_err(|_|"MemoryError: string is too large".to_string())?;
    left.push_str(right);Ok(NativeText::from(left))
}
''',
'native_string_extend':r'''
fn native_string_extend(left:&mut NativeText,right:&str)->Result<(),String> {
    let mut text=std::mem::take(left).into_string();
    if text.try_reserve(right.len()).is_err(){*left=NativeText::from(text);return Err("MemoryError: string is too large".to_string());}
    text.push_str(right);*left=NativeText::from(text);Ok(())
}
''',
'native_text_window':r'''fn native_text_window(text:&NativeText,start:Option<i128>,stop:Option<i128>)->Result<Option<&str>,String> {
    let length=if NATIVE_TEXT_UNICODE{text.codepoint_len()}else{text.byte_len()}as i128;
    let bound=|value:i128|if value<0{value.saturating_add(length).max(0)}else{value};
    let start=start.map(bound).unwrap_or(0);let stop=stop.map(bound).unwrap_or(length).min(length);
    if start>length||start>stop{return Ok(None);}
    let byte=|index:usize|if NATIVE_TEXT_UNICODE{text.byte_offset(index)}else{Ok(Some(index))};
    Ok(match(byte(start as usize)?,byte(stop as usize)?){(Some(a),Some(b))=>text.as_str().get(a..b),_=>None})
}
''',
'native_text_count':r'''fn native_text_count(text:&NativeText,pattern:&str,start:Option<i128>,stop:Option<i128>)->Result<usize,String> {
    if pattern.is_empty(){
        let length=if NATIVE_TEXT_UNICODE{text.codepoint_len()}else{text.byte_len()}as i128;
        let bound=|value:i128|if value<0{value.saturating_add(length).max(0)}else{value};
        let start=start.map(bound).unwrap_or(0);let stop=stop.map(bound).unwrap_or(length).min(length);
        return Ok(if start>length||start>stop{0}else{(stop-start)as usize+1});
    }
    Ok(native_text_window(text,start,stop)?.map_or(0,|part|part.matches(pattern).count()))
}
''',
'native_text_slice':r'''fn native_text_slice(text:&NativeText,indices:NativeSlice,_ascii:bool)->Result<NativeText,String> {
    let mut result=String::new();
    result.try_reserve(indices.len()).map_err(|_|"MemoryError: string is too large".to_string())?;
    if !NATIVE_TEXT_UNICODE {
        for index in indices{result.push(text.as_bytes()[index]as char);}
    }else{
        for index in indices{
            let start=text.byte_offset(index)?.unwrap();let stop=text.byte_offset(index+1)?.unwrap();
            result.push_str(&text.as_str()[start..stop]);
        }
    }
    Ok(NativeText::from(result))
}
''',
'class_split_text':r'''
fn class_split_text(value:&str)->ClassList<NativeText> {
    class_list(value.split(native_space).filter(|value|!value.is_empty()).map(NativeText::from).collect())
}
''',
}


def apply_cached_text(source,string_mode):
    """Override complete internal helper items; never rewrite source literals."""
    tokens,_comments,pairs=_lex(source)
    identifiers={token.text for token in tokens if token.kind=="identifier"}
    if not identifiers.intersection({"NativeText","NativeTextLiteral"}):return source
    edits=[]
    for index,token in enumerate(tokens[:-1]):
        if token.text!='fn':continue
        name=tokens[index+1].text
        replacement=_REPLACEMENTS.get(name)
        if replacement is None:continue
        cursor=index+2
        while cursor<len(tokens)and tokens[cursor].text!='{':
            cursor=pairs[cursor]+1 if tokens[cursor].text in {'(','['}else cursor+1
        if cursor==len(tokens):raise ValueError('missing cached text helper body: '+name)
        edits.append((token.start,tokens[pairs[cursor]].end,replacement.strip()))
    for start,end,replacement in reversed(edits):source=source[:start]+replacement+source[end:]
    kernel=files('py2fastrust').joinpath('runtime','native_text.rs').read_text(encoding='utf-8')
    helpers=HELPERS
    if "native_big_text_codepoint"in identifiers:
        helpers+=r'''fn native_big_text_codepoint(value:&NativeText,index:&Int)->Result<u32,String> {
    let index=index.to_i128().ok_or_else(||"IndexError: string index out of range".to_string())?;
    native_text_codepoint(value,index)
}
'''
    if "ClassDisplay"in identifiers:
        helpers+='\nimpl ClassDisplay for NativeText {fn class_str(&self)->String{self.as_str().to_string()} fn class_repr(&self)->String{text_repr_str(self.as_str())}}\n'
    prefix='\nconst NATIVE_TEXT_UNICODE:bool='+str(string_mode=='unicode').lower()+';\n'+kernel+'\n'+helpers+'\n'
    position=0
    for index,token in enumerate(tokens[:-2]):
        if token.text=='#'and tokens[index+1].text=='!'and tokens[index+2].text=='[':
            position=tokens[pairs[index+2]].end
            break
    return source[:position]+prefix+source[position:]
