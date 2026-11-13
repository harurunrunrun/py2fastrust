"""Explicit-base integer conversions over original captured call arguments."""
from .native_types import alternatives
from .references import BuiltinIdentity


def binding_error(count,keywords):
    keywords=tuple(keywords)
    if count+len(keywords)>2:
        return (f'TypeError: int() takes at most 2 arguments ({count+len(keywords)} given)'if keywords else
                f'TypeError: int expected at most 2 arguments, got {count}')
    for name in keywords:
        if name!='base':return f"TypeError: int() got an unexpected keyword argument '{name}'"
    if not count and keywords:return 'TypeError: int() missing string argument'
    return None


def requires_frames(analysis):
    return any(BuiltinIdentity('int')in fact.identity.alternatives and
               (len(fact.positional)>1 or fact.keywords)
               for scope in analysis.scopes.values()for fact in scope.calls.values())


def analyze(model,plan,node,arguments,keywords,*,factory):
    if len(arguments)<=1 and not keywords:return None
    error=binding_error(len(arguments),(name for name,_ in keywords))
    if error:return factory('none')
    from .native_classes import ClassUnsupported,shape,domain
    base=arguments[1]if len(arguments)>1 else dict(keywords)['base']
    if shape(base)is None and not model.final:return factory()
    for kind in alternatives(shape(base)):
        if domain(kind)=='object':
            raise ClassUnsupported(node,'this int base requires its user-defined __index__ protocol; the native explicit-base adapter currently accepts builtin integer and boolean bases',types=(('base',kind),),proof='explicit int base index protocol')
    return factory('int')


def emit(emitter,node,arguments,keywords,wanted):
    if len(arguments)<=1 and not keywords:return None
    from .native import _string
    from .native_classes import Expression,domain
    from .native_class_builtins import _error,_type_name
    from .native_unions import project,union_kind
    keywords=dict(keywords)
    error=binding_error(len(arguments),keywords)
    if error:return _error(emitter,node,wanted,_string(error)+'.to_owned()')
    base=arguments[1]if len(arguments)>1 else keywords['base']
    def convert_base(kind,code):
        if domain(kind)not in {'int','bool','int_bool'}:
            failure='format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,Expression(code,kind),node)+')'
            return emitter.at('Err::<u32,String>('+failure+')',node)
        number=emitter.number(Expression(code,kind))
        cast='('+number+').to_i128()'if emitter.model.integer=='bigint'else'Some(('+number+')as i128)'
        error='"ValueError: int() base must be >= 2 and <= 36, or 0".to_owned()'
        return emitter.at(cast+'.filter(|value|*value==0||(2..=36).contains(value)).map(|value|value as u32).ok_or_else(||'+error+')',node)
    code=project(base.kind,base.code,convert_base)if union_kind(base.kind)else convert_base(base.kind,base.code)
    radix=emitter.fresh();prefix='let '+radix+':u32='+code+';'
    text=arguments[0]
    def parse(kind,code):
        if getattr(kind,'_native_bytearray',False):
            data=emitter.fresh()
            return '{let '+data+'=('+code+').0.borrow().clone();'+parse('bytes',data)+'}'
        if kind not in {'str','bytes'}:
            return _error(emitter,node,wanted,'"TypeError: int() can\'t convert non-string with explicit base".to_owned()').code
        emitter.model.explicit_radix_used=True
        parser='native_radix_parse_text'if kind=='str'else'native_radix_parse_bytes'
        representation=('text_repr_str(('+code+').as_str())'if kind=='str'else'text_repr_bytes(&('+code+'))')
        result=emitter.at(parser+'(&('+code+'),'+radix+').map_err(|_|format!("ValueError: invalid literal for int() with base {}: {:.200}",'+radix+','+representation+'))',node)
        return emitter.coerce(Expression(result,'int'),wanted,node)
    result=project(text.kind,text.code,parse)if union_kind(text.kind)else parse(text.kind,text.code)
    return Expression('{'+prefix+result+'}',wanted)


def runtime(model):
    if not getattr(model,'explicit_radix_used',False):return ''
    if model.integer=='bigint':
        text=('Int::parse(value,base)'if model.string_mode=='unicode'else'Int::parse_ascii(value.as_bytes(),base)')
        return ('fn native_radix_parse_text(value:&str,base:u32)->Result<NativeInt,String>{'+text+'}\n'
                'fn native_radix_parse_bytes(value:&[u8],base:u32)->Result<NativeInt,String>{Int::parse_ascii(value,base)}\n')
    text=(r'''native_fixed_parse_radix(value.trim_matches(native_fixed_text_space).chars(),base,|character|
        native_fixed_decimal_digit(character as u32).map(|digit|digit as u32).or_else(||character.to_digit(36)))'''
          if model.string_mode=='unicode'else'native_radix_parse_bytes(value.as_bytes(),base)')
    return FIXED+'\nfn native_radix_parse_text(value:&str,base:u32)->Result<NativeInt,String>{'+text+'}\n'


FIXED=r'''
fn native_fixed_parse_radix<I,D>(characters:I,mut base:u32,digit:D)->Result<NativeInt,String>
where I:Iterator<Item=char>,D:Fn(char)->Option<u32>{
    let invalid=||"ValueError: invalid literal for int()".to_owned();
    let mut characters=characters.peekable();
    let negative=characters.peek()==Some(&'-');
    if matches!(characters.peek(),Some('+'|'-')){characters.next();}
    let first=characters.next().ok_or_else(invalid)?;
    let auto=base==0;
    let detected=if digit(first)==Some(0){match characters.peek(){Some('x'|'X')=>16,Some('o'|'O')=>8,Some('b'|'B')=>2,_=>0}}else{0};
    let prefix=detected!=0&&(base==0||base==detected);
    let mut initial=Some(first);
    if prefix{base=detected;characters.next();initial=None;if characters.peek()==Some(&'_'){characters.next();}}
    if base==0{base=10;}
    let mut value:NativeInt=0;
    let mut previous_digit=false;
    let mut first_zero=false;
    let mut any_nonzero=false;
    let mut seen=false;
    for character in initial.into_iter().chain(characters){
        if character=='_'{if !previous_digit{return Err(invalid());}previous_digit=false;continue;}
        let number=digit(character).filter(|&number|number<base).ok_or_else(invalid)?;
        if !seen{first_zero=number==0;}
        seen=true;any_nonzero|=number!=0;
        value=value.wrapping_mul(base as NativeInt).wrapping_add(number as NativeInt);
        previous_digit=true;
    }
    if !previous_digit||(auto&&!prefix&&first_zero&&any_nonzero){return Err(invalid());}
    Ok(if negative{value.wrapping_neg()}else{value})
}
fn native_radix_parse_bytes(value:&[u8],base:u32)->Result<NativeInt,String>{
    let mut first=0;let mut last=value.len();
    while first<last&&native_fixed_int_space(value[first]){first+=1;}
    while first<last&&native_fixed_int_space(value[last-1]){last-=1;}
    native_fixed_parse_radix(value[first..last].iter().map(|&byte|byte as char),base,|character|character.to_digit(36))
}
'''
