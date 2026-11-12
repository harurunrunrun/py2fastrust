"""Checked builtin integer-index conversion after call argument evaluation."""
from .native_integral_powers import INTEGRAL


def frame(emitter,value,node):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_unions import union_kind,project
    if union_kind(value.kind):
        return project(value.kind,value.code,lambda kind,code:frame(emitter,Expression(f'({code}).clone()',kind),node))
    if value.kind in INTEGRAL:return emitter.number(value)
    if domain(value.kind)=='object':
        raise ClassUnsupported(node,'this integer-index argument requires the class __index__ protocol; that conversion is not implemented',types=(('argument',value.kind),),proof='custom integer-index protocol')
    from .native_class_builtins import _type_name
    return emitter.at('Err::<NativeInt,String>(format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,value,node)+'))',node)


def plain(generator,value,node):
    from .native import _Expression,_Unsupported
    from .native_unions import union_kind,project
    if union_kind(value.kind):
        return project(value.kind,value.code,lambda kind,code:plain(generator,_Expression(f'({code}).clone()',kind),node))
    if value.kind in INTEGRAL:return generator.number(value)
    if value.kind not in {'float','none','str','bytes'}:
        raise _Unsupported('this integer-index argument needs an unimplemented native __index__ or type-error adapter',node=node,types=(('argument',value.kind),),proof='integer-index protocol')
    from .native_comparisons import _type_name
    return generator.at('Err::<NativeInt,String>(format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(value)+'))',node)
