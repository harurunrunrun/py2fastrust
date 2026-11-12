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
fn native_unpack_integer_words<const N:usize,I,F,C>(words:I,mut parse:F,mut consumer_error:C)->Result<[NativeInt;N],NativeError>
where I:IntoIterator,F:FnMut(I::Item)->Result<NativeInt,NativeError>,C:FnMut(String)->NativeError {
    let mut values:[Option<NativeInt>;N]=std::array::from_fn(|_|None);
    let mut length=0;
    for word in words {
        let value=parse(word)?;
        if length==N{return Err(consumer_error(format!("ValueError: too many values to unpack (expected {})",N)));}
        values[length]=Some(value);length+=1;
    }
    if length<N{return Err(consumer_error(format!("ValueError: not enough values to unpack (expected {}, got {})",N,length)));}
    Ok(values.map(Option::unwrap))
}
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
#[derive(Clone,Copy)]
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
#[derive(Clone,Copy)]
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
class InputWordView:
    node:object
    operation:str


@dataclass(frozen=True)
class WordSource:
    kind: str
    buffer: str
    cursor: str
    method: object
    readline: InputWordView | None = None
    scoped_setup: str = ''


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
        if expected is not None and expected <= 32:
            call=(f"native_unpack_integer_words::<{expected},_,_,_>({self.source.cursor},|native_word|{parsed},"
                  f"|native_failure|{consumer_error})?")
        else:
            call=(f"native_collect_integer_words({self.source.cursor},|native_word|{parsed},{limit},"
                  f"|native_failure|{consumer_error})?")
        body=self.prefix(g,caller,line)+call
        if self.source.readline is not None:
            view=self.source.readline
            error=g.at('Err::<(),String>(native_failure)',view.node)[:-1]+'.unwrap_err()'
            method='with_byte_line'if view.operation=='bytes'else'with_text_line'
            return (f'native_input.{method}(|native_failure|{error},|{self.source.buffer}|{{'
                    +self.source.scoped_setup+self.prefix(g,caller,line)+'Ok('+call+')})?')
        return body


def borrow_immediate_input(generator,plan,environment):
    """Borrow one input line only through a closed immediate integer consumer."""
    from .native_stream_plans import ProducerKind
    from .references import BuiltinIdentity,callable_reference
    if (plan is None or plan.kind is not ProducerKind.MAP
            or plan.callback!=BuiltinIdentity('int') or len(plan.sources)!=1
            or plan.node.keywords):
        return False
    source=plan.sources[0]
    if source.kind is not ProducerKind.WORDS or source.method is None:
        return False
    method=source.method
    if method.invocation.explicit_order:
        return False
    node=method.receiver.expression
    if not isinstance(node,ast.Call)or node.args or node.keywords:
        return False
    from .native_stdio import READERS
    target=callable_reference(generator,node.func,environment)
    if target in READERS.values() and target.line:
        kind='bytes'if target.binary else'str'
        if method.identity.owner==kind:
            return InputWordView(node,'bytes'if target.binary else'text')
        return False
    if method.identity.owner!='str':
        return False
    # A static target identity alone does not justify omitting a binding read.
    # Restrict this view to builtin lookup, not a stored/rebound callable slot.
    if ('input' in environment or 'input' in (generator.global_environment or {})
            or 'input' in (generator.global_names or ())):
        return False
    local_names=(generator.function.local_names if generator.function is not None
                 else getattr(generator,'entry_local_names',()))
    if 'input' in local_names:
        return False
    if (isinstance(node.func,ast.Name) and node.func.id=='input'
            and target==BuiltinIdentity('input')):
        return InputWordView(node,'input')
    return False


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
    if word.kind=='str':
        g.has_tuples=True
        parser+='.map_err(|_|format!("ValueError: invalid literal for int() with base 10: {:.200}",native_tuple_repr_str(@)))'
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
    view=planner.borrow_input_words
    readline=view if isinstance(view,InputWordView)and view.operation!='input'else None
    if readline is not None:
        g.has_borrowed_word_input=True
        lines=[]
    elif view:
        # No callback or later argument can read input before this immediate
        # integer consumer finishes. The reader retains and reuses its buffer.
        read=g.at('native_input.line(&mut native_output)',method.receiver.expression)
        lines=[f"let {buffer}={read};"]
    else:
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
    setup="\n".join(lines)
    result=planner.leaf(''if readline is not None else setup,"",cursor,((kind,field,True),))
    snapshot=g.temporary()
    result.unpack_length=(f"let {snapshot}={cursor}.clone();",f"{snapshot}.count()")
    result.words=WordSource(kind,buffer,cursor,method,readline,setup if readline is not None else'')
    return result


INPUT_VIEW_HELPERS = r'''
const NATIVE_INPUT_LINE_CACHE_LIMIT:usize=1<<20;
impl NativeInput {
    fn with_text_line<T,E,F>(&mut self,error:E,consume:F)->Result<T,NativeError>
    where E:FnOnce(String)->NativeError,F:FnOnce(&str)->Result<T,NativeError> {
        self.reader.read_text_into(&mut self.line,None,true)
            .map_err(StandardInputError::native_message).map_err(error)?;
        let result=consume(&self.line);
        if self.line.capacity()>NATIVE_INPUT_LINE_CACHE_LIMIT {self.line=String::new();}
        result
    }
    fn with_byte_line<T,E,F>(&mut self,error:E,consume:F)->Result<T,NativeError>
    where E:FnOnce(String)->NativeError,F:FnOnce(&[u8])->Result<T,NativeError> {
        let mut bytes=std::mem::take(&mut self.line).into_bytes();
        let result=match self.reader.read_binary_into(&mut bytes,None,true) {
            Ok(())=>consume(&bytes),
            Err(failure)=>Err(error(failure.native_message())),
        };
        if bytes.capacity()<=NATIVE_INPUT_LINE_CACHE_LIMIT {
            bytes.clear();
            self.line=String::from_utf8(bytes).unwrap();
        }
        result
    }
}
'''


def render_helpers(generator):
    return HELPERS+(INPUT_VIEW_HELPERS if generator.has_borrowed_word_input else'')
