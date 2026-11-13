"""Canonical float construction shares typed scalar and frame conversions."""
import ast
from .references import BuiltinIdentity

ASCII_HELPER=r'''
fn native_scalar_float_ascii(source:&[u8])->Result<f64,String>{
    let invalid=||"ValueError: could not convert string to float".to_owned();
    let mut first=0;let mut last=source.len();
    while first<last&&matches!(source[first],9..=13|32){first+=1;}
    while first<last&&matches!(source[last-1],9..=13|32){last-=1;}
    let bytes=&source[first..last];
    if bytes.is_empty(){return Err(invalid());}
    let negative=bytes.first()==Some(&b'-');
    let unsigned=if negative||bytes.first()==Some(&b'+'){&bytes[1..]}else{bytes};
    if unsigned.eq_ignore_ascii_case(b"nan"){return Ok(if negative{-f64::NAN}else{f64::NAN});}
    if unsigned.eq_ignore_ascii_case(b"inf")||unsigned.eq_ignore_ascii_case(b"infinity"){return Ok(if negative{f64::NEG_INFINITY}else{f64::INFINITY});}
    if !bytes.iter().all(|byte|byte.is_ascii_digit()||matches!(byte,b'.'|b'e'|b'E'|b'+'|b'-'|b'_')){return Err(invalid());}
    if bytes.contains(&b'_'){
        let mut normalized=String::with_capacity(bytes.len());
        for(index,&byte)in bytes.iter().enumerate(){
            if byte==b'_'{
                if index==0||index+1==bytes.len()||!bytes[index-1].is_ascii_digit()||!bytes[index+1].is_ascii_digit(){return Err(invalid());}
            }else{normalized.push(byte as char);}
        }
        normalized.parse::<f64>().map_err(|_|invalid())
    }else{std::str::from_utf8(bytes).unwrap().parse::<f64>().map_err(|_|invalid())}
}
'''


def requires_frames(analysis):
    simple={'int','bool','int_bool','float','str','bytes'}
    for facts in analysis.scopes.values():
        for call in facts.calls.values():
            if BuiltinIdentity('float')not in call.identity.alternatives:continue
            if call.keywords or len(call.positional)>1:return True
            if call.positional:
                value=call.positional[0]
                if value.unknown or value.unbound or any(kind not in simple for kind in value.alternatives):return True
    return False


def parser_names(owner):return getattr(owner,'native_float_parsers',set())


def _parser(owner,name):
    if not hasattr(owner,'native_float_parsers'):owner.native_float_parsers=set()
    owner.native_float_parsers.add(name)
    if name=="native_scalar_float":owner.native_float_parsers.add("native_scalar_digit")


def plain_value(generator,value,node):
    from .native import _Expression,_Unsupported
    from .native_unions import union_kind,project
    if union_kind(value.kind):
        code=project(value.kind,value.code,lambda kind,text:plain_value(generator,_Expression('('+text+').clone()',kind),node).code)
        return _Expression(code,'float')
    generator.has_extended_scalars=True
    if value.kind=='float':return _Expression(value.code,'float')
    if value.kind in {'int','bool','int_bool'}:
        if not generator.bits:
            from .native_bigint_reals import floating
            code=floating(generator,value,node)
        else:code='('+generator.number(value)+') as f64'
        return _Expression(code,'float')
    if value.kind in {'str','bytes'}:
        temporary=generator.temporary()
        if value.kind=='str':
            generator.has_tuples=True;representation='native_tuple_repr_str(&'+temporary+')'
            parser='native_scalar_float'if generator.string_mode=='unicode'else'native_scalar_float_ascii'
            argument='&'+temporary if parser=='native_scalar_float'else temporary+'.as_bytes()'
        else:
            from .native_stdio import _enable
            _enable(generator);representation='native_bytes_repr(&'+temporary+')';parser='native_scalar_float_ascii';argument='&'+temporary
        _parser(generator,parser)
        call=parser+'('+argument+').map_err(|_|format!("ValueError: could not convert string to float: {}",'+representation+'))'
        return _Expression('{let '+temporary+'='+value.code+';'+generator.at(call,node)+'}','float')
    raise _Unsupported('float() needs a builtin numeric/text/bytes argument; this value requires an unimplemented object conversion or runtime type-error adapter',node=node,types=(('argument',value.kind),),proof='canonical float argument protocol')


def frame_value(emitter,value,node):
    from .native_classes import Expression,domain,ClassUnsupported
    from .native_class_builtins import _type_name,_error
    tag=domain(value.kind)
    if tag=='float':return value.code
    if tag in {'int','bool','int_bool'}:
        number=emitter.number(value)
        if emitter.model.integer=='bigint':return emitter.at('('+number+').ratio(&Int::exact_small(1)).map_err(|_|"OverflowError: int too large to convert to float".to_owned())',node)
        return '('+number+') as f64'
    if tag=='bytearray':
        temporary,data=emitter.fresh(),emitter.fresh()
        _parser(emitter.model,'native_scalar_float_ascii')
        representation=emitter.show(Expression(temporary,value.kind),node,True)
        call='native_scalar_float_ascii(&'+data+').map_err(|_|format!("ValueError: could not convert string to float: {}",'+representation+'))'
        return '{let '+temporary+'='+value.code+';let '+data+'='+temporary+'.0.borrow().clone();'+emitter.at(call,node)+'}'
    if tag in {'str','bytes'}:
        temporary=emitter.fresh()
        captured=Expression(temporary,value.kind)
        representation=emitter.show(captured,node,True)
        parser='native_scalar_float'if tag=='str'and emitter.model.string_mode=='unicode'else'native_scalar_float_ascii'
        argument='&'+temporary if tag=='bytes'or parser=='native_scalar_float'else temporary+'.as_bytes()'
        _parser(emitter.model,parser)
        call=parser+'('+argument+').map_err(|_|format!("ValueError: could not convert string to float: {}",'+representation+'))'
        return '{let '+temporary+'='+value.code+';'+emitter.at(call,node)+'}'
    if tag=='object':
        owner=emitter.model.classes[value.kind.name]
        if any(name in owner.methods for name in ('__float__','__index__')):
            raise ClassUnsupported(node,'float() requires this class\'s __float__/__index__ conversion protocol; captured custom numeric conversion is not implemented',types=(('argument',value.kind),),proof='custom float/index protocol')
    return _error(emitter,node,'float','format!("TypeError: float() argument must be a string or a real number, not \'{}\'",'+_type_name(emitter,value,node)+')').code


def try_expression(generator,node,environment):
    if not isinstance(node,ast.Call):return None
    from .references import callable_reference
    if callable_reference(generator,node.func,environment)!=BuiltinIdentity('float'):return None
    if node.keywords or len(node.args)>1:
        from .native import _Unsupported
        raise _Unsupported('float() binding errors need the captured builtin call path',node=node,proof='float positional-only constructor signature')
    from .native import _Expression
    if not node.args:
        generator.has_extended_scalars=True
        return _Expression('0.0_f64','float',0.0)
    value=generator.read_expression(node.args[0],environment)
    return plain_value(generator,value,node)
