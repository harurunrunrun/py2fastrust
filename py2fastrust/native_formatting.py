"""Original-AST format fields and canonical format calls over typed values."""
import ast
from functools import lru_cache
from importlib.resources import files
import re
from .references import BuiltinIdentity


def requires_frames(unit,analysis):
    recorded={site for facts in analysis.scopes.values()for site in facts.expressions}
    return any(isinstance(node,ast.JoinedStr)and unit.ordinal(node)in recorded for node in ast.walk(unit.tree)) or any(
        any(BuiltinIdentity(name)in fact.identity.alternatives for name in ('format','repr','ascii'))
        for facts in analysis.scopes.values()for fact in facts.calls.values())


def analyze_joined(model,plan,node,environment):
    for child in node.values:
        if isinstance(child,ast.FormattedValue):
            value=model.expression(plan,child.value,environment)
            from .native_source_display import analyze as analyze_display
            if child.conversion!=-1:analyze_display(model,plan,child,value,environment,child.conversion in (114,97))
            if child.format_spec is not None:model.expression(plan,child.format_spec,environment)
            nonempty=(child.format_spec is not None and all(isinstance(part,ast.Constant)and isinstance(part.value,str)for part in child.format_spec.values)
                      and bool(''.join(part.value for part in child.format_spec.values)))
            if child.conversion==-1 and not nonempty:analyze_display(model,plan,child,value,environment)
        else:model.expression(plan,child,environment)
    return model.cell(plan,node,'str')


def conversion(emitter,node,value,mode):
    from .native_classes import Expression
    _display_protocol(emitter,node,value.kind,mode in (114,97),set())
    rendered=emitter.show(value,node,mode in (114,97))
    if mode==97:
        emitter.model.format_ascii_required=True
        rendered=f'native_format_ascii(&({rendered}))'
    return Expression(f'NativeText::from({rendered})','str')


def _display_protocol(emitter,node,kind,representation,seen):
    from .native_classes import ClassUnsupported,domain,shape
    from .native_types import ListType,TupleType,TupleSequenceType,alternatives
    if kind in seen:return
    seen.add(kind)
    for child in alternatives(kind):
        if child!=kind:
            _display_protocol(emitter,node,child,representation,seen);continue
        tag=domain(child)
        if tag=='object':
            methods=emitter.model.classes[child.name].methods
            names=('__repr__',)if representation else('__str__','__repr__')
            # Source observers are analyzed at their original call/format site.
            # Emitter.show consumes that exact canonical callback proof.
        elif isinstance(child,(ListType,TupleSequenceType)):
            _display_protocol(emitter,node,child.element,True,seen)
        elif isinstance(child,TupleType):
            for value in child.fields:_display_protocol(emitter,node,value,True,seen)
        elif getattr(child,'_native_class_mapping',False):
            _display_protocol(emitter,node,shape(child.record.key),True,seen)
            _display_protocol(emitter,node,shape(child.record.value),True,seen)


def emit_joined(emitter,node):
    from .native_classes import Expression
    result=emitter.fresh();parts=[f'let mut {result}=String::new();']
    for child in node.values:
        if isinstance(child,ast.Constant):
            value=emitter.expression(child)
        elif isinstance(child,ast.FormattedValue):
            before,value=emitter.capture(emitter.expression(child.value));parts.append(before)
            if child.conversion!=-1:
                before,value=emitter.capture(conversion(emitter,child,value,child.conversion));parts.append(before)
            if child.format_spec is None:
                value=conversion(emitter,child,value,115)
            else:
                before,specification=emitter.capture(emitter.expression(child.format_spec));parts.append(before)
                value=format_value(emitter,child,value,specification)
        else:raise AssertionError('unexpected official JoinedStr child')
        parts.append(f'{result}.push_str(&({value.code}));')
    constant=''.join(child.value for child in node.values)if all(isinstance(child,ast.Constant)and isinstance(child.value,str)for child in node.values)else None
    return Expression('{'+''.join(parts)+f'NativeText::from({result})'+'}','str',constant)


def format_value(emitter,node,value,specification):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_class_builtins import _type_name,_error
    from .native_unions import project,union_kind
    if union_kind(specification.kind):
        return Expression(project(specification.kind,specification.code,lambda kind,code:
            format_value(emitter,node,value,Expression(f'({code}).clone()',kind)).code),'str')
    if specification.kind!='str':
        name='"None"'if specification.kind=='none'else _type_name(emitter,specification,node)
        return _error(emitter,node,'str',f'format!("TypeError: format() argument 2 must be str, not {{}}",{name})')
    if union_kind(value.kind):
        return Expression(project(value.kind,value.code,lambda kind,code:
            format_value(emitter,node,Expression(f'({code}).clone()',kind),specification).code),'str')
    tag=domain(value.kind);spec=specification.code
    _display_protocol(emitter,node,value.kind,False,set())
    emitter.model.formatting_required=True
    if tag in {'int','bool','int_bool'}:
        number=emitter.number(value);shown=emitter.show(value,node)
        code=f'if ({spec}).is_empty(){{{shown}}}else{{'+emitter.at(f'native_format_integer(&({number}),&({spec}))',node)+'}'
    elif tag=='float':code=emitter.at(f'native_format_float({value.code},&({spec}))',node)
    elif tag=='str':code=emitter.at(f'native_format_string(&({value.code}),&({spec}))',node)
    else:
        if tag=='object':
            owner=emitter.model.classes[value.kind.name]
            if '__format__'in owner.methods:
                raise ClassUnsupported(node,'formatting this class instance requires its source-defined __format__/__str__/__repr__ method dispatch; that formatting protocol is not implemented',proof='instance formatting special-method dispatch')
        name=_type_name(emitter,value,node)
        failure=_error(emitter,node,'str',f'format!("TypeError: unsupported format string passed to {{}}.__format__",{name})').code
        if tag=='object'and isinstance(specification.constant,str)and specification.constant:return Expression(failure,'str')
        shown=emitter.show(value,node)
        return Expression(f'if ({spec}).is_empty(){{NativeText::from({shown})}}else{{{failure}}}','str')
    return Expression(f'NativeText::from({code})','str')


def emit_builtin(emitter,node,name,arguments,keywords,wanted):
    from .native_classes import Expression
    if name in {'repr','ascii'}:return conversion(emitter,node,arguments[0],114 if name=='repr'else 97)
    specification=arguments[1]if len(arguments)>1 else Expression('NativeText::new()','str','')
    if (name=='format'and len(arguments)==len(node.args)and len(node.args)>1
            and not any(isinstance(argument,ast.Starred)for argument in node.args)
            and isinstance(node.args[1],ast.Constant)and isinstance(node.args[1].value,str)):
        specification=Expression(specification.code,specification.kind,node.args[1].value)
    return format_value(emitter,node,arguments[0],specification)


def runtime(model):
    result=[]
    from .native_source_display import runtime as display_runtime
    result.append(display_runtime(model))
    if getattr(model,'formatting_required',False):result.append(_helpers(model.integer,model.string_mode))
    if getattr(model,'format_ascii_required',False):result.append(ASCII)
    return '\n'.join(result)


@lru_cache(maxsize=6)
def _helpers(integer,string_mode):
    runtime=files('py2fastrust').joinpath('runtime')
    text=runtime.joinpath('text.rs').read_text(encoding='utf-8')
    source=text[text.index('struct TextFormatSpec {'):text.index('\nimpl Runtime {\n    fn text_format_value',text.index('struct TextFormatSpec {'))]
    source=source.replace('PyResult<','Result<').replace('Result<Self>','Result<Self,String>').replace('Result<Option<usize>>','Result<Option<usize>,String>').replace('Result<String>','Result<String,String>')
    source=source.replace('pyerr(', 'native_format_error(').replace('Int::decimal_digit(*ch)','native_format_digit(*ch)')
    source=source.replace('.checked_add(digit as usize)).ok_or_else(','.checked_add(digit as usize)).filter(|value|*value<=isize::MAX as usize).ok_or_else(')
    source=source.replace('_ => format!("{:?}", magnitude),','_ => native_float_text(magnitude),')
    source=source.replace('struct TextFormatSpec','struct NativeFormatSpec').replace('impl TextFormatSpec','impl NativeFormatSpec').replace('&TextFormatSpec','&NativeFormatSpec')
    data=runtime.joinpath('integer.rs').read_text(encoding='utf-8')
    body=data[data.index('    fn format_integer('):data.index('    fn bit_length(',data.index('    fn format_integer('))]
    body=body.replace('    fn format_integer(&self, spec: &str)','fn native_format_integral(value: &NativeInt, spec: &str)').replace('Self::format_digit','native_format_digit').replace('self.to_string()','value.to_string()').replace('self.is_negative()','value.is_negative()'if integer=='bigint'else'*value<0').replace('self\n                .to_i128()','value\n                .to_i128()'if integer=='bigint'else'Some(*value as i128)').replace("self.unsigned_radix(base, kind == 'X')","value.unsigned_radix(base, kind == 'X')"if integer=='bigint'else"native_format_radix(*value,base,kind=='X')")
    body=body.replace('return Err("ValueError: Invalid format specifier for object of type \'int\'".into());', 'return Err(format!("ValueError: Invalid format specifier \'{spec}\' for object of type \'int\'"));')
    as_float='value.to_f64()'if integer=='bigint'else'*value as f64'
    digit="fn native_format_digit(value:char)->Option<usize>{value.to_digit(10).map(|value|value as usize)}"
    if string_mode=='unicode':
        zeroes=re.search(r'fn decimal_digit\(.*?const ZEROES:\s*&\[u32\]\s*=\s*&\[(.*?)\];',data,re.S)[1]
        digit='const NATIVE_FORMAT_ZEROES:&[u32]=&['+zeroes+'];\n'+r'''
fn native_format_digit(value:char)->Option<usize>{let code=value as u32;if code<128{return if value.is_ascii_digit(){Some((code-48)as usize)}else{None}}let index=NATIVE_FORMAT_ZEROES.partition_point(|&zero|zero<=code);if index==0{return None}let digit=code-NATIVE_FORMAT_ZEROES[index-1];(digit<10).then_some(digit as usize)}
'''
    radix=''if integer=='bigint'else r'''
fn native_format_radix(value:NativeInt,base:u32,uppercase:bool)->String{
    let mut value=(value as i128).unsigned_abs();let mut digits=Vec::new();
    loop{let digit=(value%base as u128)as u8;digits.push(if digit<10{b'0'+digit}else{(if uppercase{b'A'}else{b'a'})+digit-10});value/=base as u128;if value==0{break}}
    digits.reverse();String::from_utf8(digits).unwrap()
}
'''
    return source+'\n'+body+'\n'+FOOTER.replace('FORMAT_FLOAT',as_float)+'\n'+digit+'\n'+radix


FOOTER=r'''
fn native_format_error(kind:&str,message:impl std::fmt::Display)->String{format!("{kind}: {message}")}
fn native_format_integer(value:&NativeInt,spec:&str)->Result<String,String>{
    if let Some(result)=native_format_integral(value,spec)?{return Ok(result)}
    let value=FORMAT_FLOAT;
    if !value.is_finite(){return Err("OverflowError: int too large to convert to float".into())}
    native_format_float(value,spec)
}
fn native_format_float(value:f64,spec:&str)->Result<String,String>{
    if spec.is_empty(){return Ok(native_float_text(value))}
    text_format_float(value,&NativeFormatSpec::parse(spec,true).map_err(|message|native_format_parse_error(message,"float"))?)
}
fn native_format_parse_error(message:String,kind:&str)->String{if message.starts_with("ValueError: Invalid format specifier '"){format!("{message} for object of type '{kind}'")}else{message}}
fn native_format_string(value:&str,spec:&str)->Result<String,String>{
    let options=NativeFormatSpec::parse(spec,false).map_err(|message|native_format_parse_error(message,"str"))?;
    if let Some(code)=options.presentation{if code!='s'{return Err(format!("ValueError: Unknown format code '{code}' for object of type 'str'"))}}
    if options.sign.is_some(){return Err("ValueError: Sign not allowed in string format specifier".into())}
    if options.negative_zero{return Err("ValueError: Negative zero coercion (z) not allowed in string format specifier".into())}
    if options.alternate{return Err("ValueError: Alternate form (#) not allowed in string format specifier".into())}
    if let Some(group)=options.integer_group.or(options.fractional_group){return Err(format!("ValueError: Cannot specify '{group}' with 's'."))}
    if options.align=='='{return Err("ValueError: '=' alignment not allowed in string format specifier".into())}
    let text=if let Some(precision)=options.precision{value.chars().take(precision).collect()}else{value.to_owned()};
    text_format_pad(text,&options,0)
}
'''


ASCII=r'''
fn native_format_ascii(value:&str)->String{
    let mut output=String::new();for character in value.chars(){let code=character as u32;if code<128{output.push(character)}else if code<=255{output.push_str(&format!("\\x{code:02x}"))}else if code<=65535{output.push_str(&format!("\\u{code:04x}"))}else{output.push_str(&format!("\\U{code:08x}"))}}output
}
'''
