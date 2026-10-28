"""One typed split producer for materialization and lazy integer conversion."""

import ast
from dataclasses import dataclass

from .native import _Expression, _Unsupported


HELPERS = r'''
fn native_words_limit(value:i128)->Result<isize,String> {
    isize::try_from(value).map_err(|_|"OverflowError: Python int too large to convert to C ssize_t".to_string())
}
fn native_words_space(character:char)->bool {
    character.is_whitespace()||('\u{1c}'..='\u{1f}').contains(&character)
}
fn native_words_byte_space(byte:u8)->bool {matches!(byte,9..=13|32)}
fn native_collect_integer_words<I,F,C>(words:I,mut parse:F,expected:Option<usize>,mut consumer_error:C)->Result<Vec<NativeInt>,NativeError>
where I:IntoIterator,F:FnMut(I::Item)->Result<NativeInt,NativeError>,C:FnMut(String)->NativeError {
    let mut values=Vec::new();
    for word in words {
        let value=parse(word)?;
        if expected==Some(values.len()){return Err(consumer_error(format!("ValueError: too many values to unpack (expected {})",values.len())));}
        values.try_reserve(1).map_err(|_|consumer_error("MemoryError".to_string()))?;values.push(value);
    }
    if let Some(expected)=expected {
        if values.len()<expected{return Err(consumer_error(format!("ValueError: not enough values to unpack (expected {}, got {})",expected,values.len())));}
    }
    Ok(values)
}
struct NativeWords<'a> {text:&'a str,separator:Option<&'a str>,cursor:usize,remaining:isize,done:bool}
impl<'a> NativeWords<'a> {
    fn new(text:&'a str,separator:Option<&'a str>,maximum:i128)->Result<Self,String> {
        let remaining=native_words_limit(maximum)?;
        if separator.is_some_and(str::is_empty){return Err("ValueError: empty separator".into());}
        Ok(Self{text,separator,cursor:0,remaining,done:false})
    }
}
impl<'a> Iterator for NativeWords<'a> {
    type Item=&'a str;
    fn next(&mut self)->Option<Self::Item> {
        if self.done{return None;}
        if let Some(separator)=self.separator {
            let start=self.cursor;
            if self.remaining!=0 {
                if let Some(offset)=self.text[start..].find(separator) {
                    let stop=start+offset;self.cursor=stop+separator.len();
                    if self.remaining>0{self.remaining-=1;}
                    return Some(&self.text[start..stop]);
                }
            }
            self.done=true;return Some(&self.text[start..]);
        }
        while self.cursor<self.text.len() {
            let character=self.text[self.cursor..].chars().next().unwrap();
            if !native_words_space(character){break;}self.cursor+=character.len_utf8();
        }
        if self.cursor==self.text.len(){self.done=true;return None;}
        let start=self.cursor;
        if self.remaining==0{self.done=true;return Some(&self.text[start..]);}
        while self.cursor<self.text.len() {
            let character=self.text[self.cursor..].chars().next().unwrap();
            if native_words_space(character){break;}self.cursor+=character.len_utf8();
        }
        if self.remaining>0{self.remaining-=1;}
        Some(&self.text[start..self.cursor])
    }
}
struct NativeByteWords<'a> {text:&'a[u8],separator:Option<&'a[u8]>,cursor:usize,remaining:isize,done:bool}
impl<'a> NativeByteWords<'a> {
    fn new(text:&'a[u8],separator:Option<&'a[u8]>,maximum:i128)->Result<Self,String> {
        let remaining=native_words_limit(maximum)?;
        if separator.is_some_and(|value|value.is_empty()){return Err("ValueError: empty separator".into());}
        Ok(Self{text,separator,cursor:0,remaining,done:false})
    }
}
impl<'a> Iterator for NativeByteWords<'a> {
    type Item=&'a[u8];
    fn next(&mut self)->Option<Self::Item> {
        if self.done{return None;}
        if let Some(separator)=self.separator {
            let start=self.cursor;
            if self.remaining!=0 {
                if let Some(offset)=self.text[start..].windows(separator.len()).position(|value|value==separator) {
                    let stop=start+offset;self.cursor=stop+separator.len();
                    if self.remaining>0{self.remaining-=1;}
                    return Some(&self.text[start..stop]);
                }
            }
            self.done=true;return Some(&self.text[start..]);
        }
        while self.cursor<self.text.len()&&native_words_byte_space(self.text[self.cursor]){self.cursor+=1;}
        if self.cursor==self.text.len(){self.done=true;return None;}
        let start=self.cursor;
        if self.remaining==0{self.done=true;return Some(&self.text[start..]);}
        while self.cursor<self.text.len()&&!native_words_byte_space(self.text[self.cursor]){self.cursor+=1;}
        if self.remaining>0{self.remaining-=1;}
        Some(&self.text[start..self.cursor])
    }
}
'''


@dataclass(frozen=True)
class WordSource:
    kind: str
    buffer: str
    cursor: str
    method: object


@dataclass(frozen=True)
class IntegerWords:
    source: WordSource
    parse: str
    scope: object
    trace: str | None
    node: object
    frame: str | None
    fixed_scope: bool

    def prefix(self,g,caller,line):
        from .native_iterators import _context,_scope_code,_deferred_prefix
        if self.fixed_scope:return ""
        if self.frame is None:return _deferred_prefix(self.scope,self.trace,caller,line)
        caller=_context(caller)
        parent=f"{caller.trace_id}(error)"if caller.trace_id is not None else"error"
        return (f"let {self.trace}=|mut error:NativeError|{{error.frames.push(({line},{_scope_code(caller.name)})); {parent}}};\n")

    def call(self,g,caller,line,expected=None):
        from .native_iterators import _scope,_context,_scope_code
        limit="None"if expected is None else f"Some({expected})"
        parser=self.parse.replace("@","native_word")
        with _scope(g,self.scope,self.trace):
            parsed=g.at(parser,self.node)[:-1]
        current=_context(caller)
        consumer_error=f"native_at::<()>(Err(native_failure),{line},{_scope_code(current.name)})"
        if current.trace_id is not None:consumer_error+=f".map_err(&{current.trace_id})"
        consumer_error+=".unwrap_err()"
        call=(f"native_collect_integer_words({self.source.cursor},|native_word|{parsed},{limit},"
              f"|native_failure|{consumer_error})?")
        return self.prefix(g,caller,line)+call


def integer_map(g,source,planner,node,*,frame=None,inline=False):
    from .native_iterators import DeferredScope,_scope
    word=source.words
    if word is None:return None
    if word.kind=="bytes":
        from .native_stdio import _enable
        _enable(g)
        parser="native_io_parse_bytes(@)"
        if g.bits:
            from .native_integer_parsing import enable
            enable(g)
    elif g.bits:
        from .native_integer_parsing import enable
        enable(g)
        parser="native_parse_integer(@)"
    else:
        parser="Int::parse(@,10)"
    if inline:
        scope,trace=g.scope_name(),g.expression_trace_id
    elif frame is not None:
        g.has_iterator_frames=True
        scope,trace=frame,g.temporary()
    else:
        scope,trace=DeferredScope(g.temporary(),g.temporary()),g.temporary()
    info=IntegerWords(word,parser,scope,trace,node,frame,inline)
    with _scope(g,scope,trace):
        value=g.at(parser,node)
    result=planner.leaf(source.setup,source.begin,word.cursor,(("int",value,True),),source.owners,
                        eager=True,length=source.length,nonempty=source.nonempty)
    emit=result.emit_body
    def contextual(action,caller,line,continue_label=None):
        return info.prefix(g,caller,line)+emit(action,caller,line,continue_label)
    result.emit_body=contextual
    result.integer_words=info
    return result


def lower(g,plan,environment,planner):
    """Capture a proved split call once, using the normalized argument order."""
    method=plan.method
    if method is None or method.identity.name!="split":
        raise _Unsupported
    g.has_native_words=True
    kind=method.identity.owner
    buffer,cursor=g.temporary(),g.temporary()
    lines=[f"let {buffer}={method.receiver.captured.code};"]
    separator,maximum="None","-1_i128"
    for operand in method.invocation.explicit_order:
        expression=operand.expression
        if operand.parameter=="sep" and isinstance(expression,ast.Constant) and expression.value is None:
            continue
        value=g.expression(expression,environment)
        temporary=g.temporary()
        if operand.parameter=="sep":
            if value.kind!=kind:raise _Unsupported
            lines.append(f"let {temporary}={value.code};")
            separator=f"Some({temporary}.as_str())" if kind=="str" else f"Some({temporary}.as_slice())"
        else:
            lines.append(f"let {temporary}={g.number(value)};")
            maximum=(f"({temporary}) as i128" if g.bits else
                     f"{temporary}.to_i128().unwrap_or_else(||if {temporary}.is_negative(){{i128::MIN}}else{{i128::MAX}})")
    factory="NativeWords" if kind=="str" else "NativeByteWords"
    call=g.at(f"{factory}::new(&{buffer},{separator},{maximum})",plan.node)
    lines.append(f"let {cursor}={call};")
    field="NativeText::from(@)" if kind=="str" else "@.to_vec()"
    result=planner.leaf("\n".join(lines),"",cursor,((kind,field,True),))
    result.words=WordSource(kind,buffer,cursor,method)
    return result
