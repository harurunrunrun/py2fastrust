"""Builtin bytes allocation from typed counts, without source-pattern shortcuts."""


def requires_frames(analysis):
    from .references import BuiltinIdentity
    return any(BuiltinIdentity('bytes')in call.identity.alternatives for facts in analysis.scopes.values()for call in facts.calls.values())


def analyze(model,plan,node,arguments,keywords,factory):
    from .native_classes import ClassUnsupported,shape
    if len(arguments)>1 or keywords:
        raise ClassUnsupported(node,'bytes() text encoding/errors or keyword source binding is not implemented by the native bytes constructor; empty construction and one integral count/bytes source are implemented',proof='native bytes constructor signature/conversion')
    if arguments:
        from .native_types import alternatives,EmptyType
        for kind in alternatives(shape(arguments[0])):
            if getattr(kind,'_native_bytearray',False):continue
            if isinstance(kind,EmptyType)or kind is None or kind in {'int','bool','int_bool','bytes','float','none','str'}:continue
            raise ClassUnsupported(node,'bytes() from this value needs its iterable, __bytes__ or __index__ conversion protocol; those object/iterable forms are not implemented by the native bytes constructor',types=(('source',kind),),proof='native bytes source conversion')
    model.native_bytes_constructor_required=True
    return factory('bytes')


def emit(emitter,node,arguments):
    from .native_classes import Expression
    from .native_unions import union_kind,project
    from .native_class_builtins import _type_name
    if not arguments:return 'Vec::<u8>::new()'
    value=arguments[0]
    if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:emit(emitter,node,[Expression(code,kind)]))
    from .native_types import EmptyType
    if isinstance(value.kind,EmptyType):return 'native_empty::<Vec<u8>>('+value.code+')'
    if getattr(value.kind,'_native_bytearray',False):return '{let result=('+value.code+').0.borrow().clone();result}'
    if value.kind=='bytes':return '('+value.code+').clone()'
    if value.kind in {'int','bool','int_bool'}:return emitter.at('class_bytes_count(&('+emitter.number(value)+'))',node)
    message='"TypeError: string argument without an encoding".to_owned()'if value.kind=='str'else'format!("TypeError: cannot convert \'{}\' object to bytes",'+_type_name(emitter,value,node)+')'
    return emitter.at('Err::<Vec<u8>,String>('+message+')',node)


def runtime(model):
    if not getattr(model,'native_bytes_constructor_required',False):return ''
    number='value.to_i128()'if model.integer=='bigint'else'Some(*value as i128)'
    return 'fn class_bytes_count(value:&NativeInt)->Result<Vec<u8>,String>{let value='+number+'.ok_or_else(||"OverflowError: cannot fit \'int\' into an index-sized integer".to_owned())?;if value<isize::MIN as i128||value>isize::MAX as i128{return Err("OverflowError: cannot fit \'int\' into an index-sized integer".to_owned());}if value<0{return Err("ValueError: negative count".to_owned());}let mut bytes=Vec::new();bytes.try_reserve(value as usize).map_err(|_|"MemoryError".to_owned())?;bytes.resize(value as usize,0);Ok(bytes)}'
