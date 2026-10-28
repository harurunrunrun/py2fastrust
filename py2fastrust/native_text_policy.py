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


def _codepoint_helper(name,index_type,conversion):
    return f'''
fn {name}(value:&str,index:{index_type})->Result<u32,String> {{
    let error=||"IndexError: string index out of range".to_owned();
    let index={conversion};
    let index=if index<0 {{index.saturating_add(value.len() as i128)}}else{{index}};
    let index=usize::try_from(index).map_err(|_|error())?;
    value.as_bytes().get(index).map(|byte|u32::from(*byte)).ok_or_else(error)
}}
'''

_BORROW_HELPERS["native_ascii_codepoint"]=_codepoint_helper("native_ascii_codepoint","i128","index")
_BORROW_HELPERS["native_big_ascii_codepoint"]=_codepoint_helper("native_big_ascii_codepoint","&Int","index.to_i128().ok_or_else(error)?")


# The ASCII profile applies to numeric text, whitespace and repr as well as
# indices. Select definitions before reachability pruning so Unicode data never
# becomes a dependency of a default-profile program.
_ASCII_PRIMITIVES = {
    "native_space": r'''fn native_space(c:char)->bool {matches!(c,'\u{9}'..='\u{d}'|'\u{1c}'..='\u{20}')}''',
    "native_text_whitespace": r'''fn native_text_whitespace(c:char)->bool {matches!(c,'\u{9}'..='\u{d}'|'\u{1c}'..='\u{20}')}''',
    "native_words_space": r'''fn native_words_space(c:char)->bool {matches!(c,'\u{9}'..='\u{d}'|'\u{1c}'..='\u{20}')}''',
    "native_scalar_space": r'''fn native_scalar_space(c:char)->bool {matches!(c,'\u{9}'..='\u{d}'|' ')}''',
    "decimal_digit": r'''fn decimal_digit(c:char)->Option<u32> {c.to_digit(36)}''',
    "format_digit": r'''fn format_digit(c:char)->Option<usize> {
    if c.is_ascii_digit(){Some((c as u8-b'0')as usize)}else{None}
}''',
    "native_scalar_digit": r'''fn native_scalar_digit(c:char)->Option<u32> {
    if c.is_ascii_digit(){Some(c as u32-'0' as u32)}else{None}
}''',
    "native_tuple_printable": r'''fn native_tuple_printable(c:char)->bool {(32..127).contains(&(c as u32))}''',
    "text_repr_str": r'''fn text_repr_str(source:&str)->String {native_ascii_repr(source)}''',
    "native_tuple_repr_str": r'''fn native_tuple_repr_str(source:&str)->String {native_ascii_repr(source)}''',
    "native_parse_integer": r'''fn native_parse_integer(word:&str)->Result<NativeInt,String> {
    let word=word.trim_matches(native_ascii_numeric_space);
    let bytes=word.as_bytes();
    let negative=bytes.first()==Some(&b'-');
    let digits=if negative||bytes.first()==Some(&b'+'){&bytes[1..]}else{bytes};
    let mut value:NativeInt=0;let mut preceding_digit=false;
    for &byte in digits {
        if byte.is_ascii_digit(){value=value.wrapping_mul(10).wrapping_add((byte-b'0')as NativeInt);preceding_digit=true;}
        else if byte==b'_'&&preceding_digit{preceding_digit=false;}
        else{return Err("ValueError: invalid literal for int()".into());}
    }
    if !preceding_digit{return Err("ValueError: invalid literal for int()".into());}
    Ok(if negative{value.wrapping_neg()}else{value})
}''',
    "decode_pending": r'''fn decode_pending(&mut self,_final:bool)->Result<(),StandardInputError> {
    if let Some(start)=self.pending.iter().position(|byte|!byte.is_ascii()){
        return Err(StandardInputError::Decode{object:self.pending.clone(),start,end:start+1,reason:"non-ASCII input in the ASCII profile"});
    }
    self.decoded.push_str(std::str::from_utf8(&self.pending).unwrap());
    self.pending.clear();Ok(())
}''',
    "read_text_into": r'''fn read_text_into(&mut self,out:&mut String,count:Option<usize>,line:bool)->Result<(),StandardInputError> {
    out.clear();
    if count==Some(0){
        if line&&self.position==self.decoded.len(){self.fill_text()?;}
        return Ok(());
    }
    if count.is_none()&&!line{
        let previous=self.pending.len();
        std::io::Read::read_to_end(&mut self.reader,&mut self.pending).map_err(StandardInputError::Io)?;
        self.eof=true;
        if let Err(error)=self.decode_pending(true){self.pending.truncate(previous);return Err(error);}
        out.push_str(&self.decoded[self.position..]);self.decoded.clear();self.position=0;
        return Ok(());
    }
    let mut length=0;
    loop{
        if self.position==self.decoded.len()&&!self.fill_text()?{return Ok(());}
        let available=&self.decoded[self.position..];
        let mut end=count.map_or(available.len(),|count|available.len().min(count-length));
        if line{if let Some(index)=available[..end].find('\n'){end=index+1;}}
        let selected=&available[..end];let newline=selected.ends_with('\n');
        length+=selected.len();out.push_str(selected);self.position+=end;
        if line&&newline||count==Some(length){return Ok(());}
    }
}''',
}


_ASCII_REPR_HELPER=r'''
fn native_ascii_repr(source:&str)->String {
    use std::fmt::Write as _;
    let quote=if source.contains('\'')&&!source.contains('"'){b'"'}else{b'\''};
    let mut result=String::with_capacity(source.len()+2);result.push(quote as char);
    for &byte in source.as_bytes(){match byte{
        b'\n'=>result.push_str("\\n"),b'\r'=>result.push_str("\\r"),b'\t'=>result.push_str("\\t"),b'\\'=>result.push_str("\\\\"),
        byte if byte==quote=>{result.push('\\');result.push(byte as char);},
        32..=126=>result.push(byte as char),
        byte=>write!(&mut result,"\\x{byte:02x}").unwrap(),
    }}result.push(quote as char);result
}
'''


def _ascii_whitespace_calls(source):
    """Select numeric whitespace predicates without touching source literals."""
    tokens,_comments,pairs=_lex(source)
    edits=[]
    for index,token in enumerate(tokens):
        if token.kind!='identifier':continue
        if (token.text=='is_whitespace'and index>=3
                and [part.text for part in tokens[index-3:index]]==['char',':',':']):
            edits.append((tokens[index-3].start,token.end,'native_ascii_numeric_space'))
        elif (token.text=='trim'and index>0 and tokens[index-1].text=='.'
              and index+2<len(tokens)and tokens[index+1].text=='('
              and pairs[index+1]==index+2):
            edits.append((token.start,tokens[index+2].end,'trim_matches(native_ascii_numeric_space)'))
    for start,end,replacement in reversed(edits):source=source[:start]+replacement+source[end:]
    return source+"\nfn native_ascii_numeric_space(c:char)->bool {matches!(c,'\\u{9}'..='\\u{d}'|' ')}\n"

def _discard_unicode_repr_tables(source):
    """ASCII repr helpers cannot reference these bundled Unicode constants."""
    tokens,_comments,pairs=_lex(source)
    edits=[]
    for index,token in enumerate(tokens[:-1]):
        if token.text!='const'or tokens[index+1].text not in {'TEXT_PRINTABLE','NATIVE_TUPLE_PRINTABLE'}:continue
        cursor=index+2
        while cursor<len(tokens)and tokens[cursor].text!=';':
            cursor=pairs[cursor]+1 if tokens[cursor].text in {'(','[','{'}else cursor+1
        if cursor==len(tokens):raise ValueError('missing end of an internal Unicode table')
        edits.append((token.start,tokens[cursor].end))
    for start,end in reversed(edits):source=source[:start]+source[end:]
    return source


def _ascii_word_iterator(source):
    """Whitespace splitting uses byte cursors in the ASCII storage profile."""
    tokens,_comments,pairs=_lex(source)
    edits=[]
    for index,token in enumerate(tokens):
        if token.text!='impl':continue
        cursor=index+1
        while cursor<len(tokens)and tokens[cursor].text!='{':cursor+=1
        if cursor==len(tokens):continue
        header=[part.text for part in tokens[index:cursor]]
        if not any(header[offset:offset+3]==['Iterator','for','NativeWords']for offset in range(len(header)-2)):continue
        edits.append((token.start,tokens[pairs[cursor]].end,r'''impl<'a> Iterator for NativeWords<'a> {
    type Item=&'a str;
    fn next(&mut self)->Option<Self::Item> {
        if self.done{return None;}
        if let Some(separator)=self.separator{
            let start=self.cursor;
            if self.remaining!=0{
                if let Some(offset)=self.text[start..].find(separator){
                    let stop=start+offset;self.cursor=stop+separator.len();
                    if self.remaining>0{self.remaining-=1;}
                    return Some(&self.text[start..stop]);
                }
            }
            self.done=true;return Some(&self.text[start..]);
        }
        let bytes=self.text.as_bytes();
        while self.cursor<bytes.len()&&matches!(bytes[self.cursor],9..=13|28..=32){self.cursor+=1;}
        if self.cursor==bytes.len(){self.done=true;return None;}
        let start=self.cursor;
        if self.remaining==0{self.done=true;return Some(&self.text[start..]);}
        while self.cursor<bytes.len()&&!matches!(bytes[self.cursor],9..=13|28..=32){self.cursor+=1;}
        if self.remaining>0{self.remaining-=1;}
        Some(&self.text[start..self.cursor])
    }
}'''))
    for start,end,replacement in reversed(edits):source=source[:start]+replacement+source[end:]
    return source


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
        replacement = _ASCII_PRIMITIVES.get(name)or _ASCII_HELPERS.get(name)
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
        if name=='native_parse_integer'and any(part.text=='Int'for part in tokens[index:cursor]):
            # The class BigInt emitter uses the same helper name with an exact
            # Int result. Its parser gets ASCII digit/space definitions above.
            continue
        edits.append((token.start, tokens[pairs[cursor]].end, replacement.strip()))
    for start, end, replacement in reversed(edits):
        source = source[:start] + replacement + source[end:]
    identifiers = {token.text for token in tokens if token.kind == "identifier"}
    for name, helper in _BORROW_HELPERS.items():
        if name in identifiers:
            source += "\n" + helper
    if identifiers.intersection({'text_repr_str','native_tuple_repr_str'}):source+='\n'+_ASCII_REPR_HELPER
    return _ascii_word_iterator(_discard_unicode_repr_tables(_ascii_whitespace_calls(source)))
