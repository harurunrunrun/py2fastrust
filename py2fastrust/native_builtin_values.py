"""Apply a proved builtin identity to already lowered scalar arguments."""
from .native import _Expression, _Unsupported, _text_expression
from .references import BuiltinIdentity


def integer_from_float(g, value, node):
    if value.kind != 'float':
        raise _Unsupported
    if g.bits:
        g.has_extended_scalars = True
        operation = f'native_float_integer({value.code})'
    else:
        operation = f'Int::from_f64({value.code})'
    return _Expression(g.at(operation, node), 'int')

UNARY_BUILTINS=frozenset({"int","bool","abs","str","len","float"})


def unary_capability(identity,kind):
    """The operand representations implemented by this scalar adapter."""
    if not isinstance(identity,BuiltinIdentity):return False
    name=identity.name
    if name=="bool":
        from .native_types import (EmptyType,TupleType,TupleSequenceType,ListType,DequeType,
                                   UnionType,NullableType,alternatives)
        if isinstance(kind,(UnionType,NullableType)):
            return all(unary_capability(identity,part)for part in alternatives(kind))
        return(isinstance(kind,(EmptyType,TupleType,TupleSequenceType,ListType,DequeType))
               or getattr(kind,"_key_container",False)
               or kind in {"int","bool","int_bool","float","str","bytes","none",
                           "list_int","dict_int","set_int","matrix_int","deque_int"})
    if name=="float":return kind in {"int","bool","int_bool","float","str","bytes"}
    if name=="int":return kind in {"int","bool","int_bool","float","str","bytes"}
    if name=="abs":return kind in {"int","bool","int_bool","float"}
    if name=="str":return kind in {"int","bool","int_bool","str"}
    if name=="len":return kind in {"str","bytes","list_int","matrix_int","dict_int","set_int","deque_int"}
    return False

def unary(g, identity, value, node):
    if not isinstance(identity, BuiltinIdentity):
        return None
    if not unary_capability(identity,value.kind):raise _Unsupported
    name=identity.name
    if name=="float":
        from .native_float_constructor import plain_value
        return plain_value(g,value,node)
    if name == "bool":
        return _Expression(g.truth(value),"bool")
    if name == "int":
        if value.kind == 'float':
            return integer_from_float(g, value, node)
        if value.kind in {"int","bool","int_bool"}:
            return _Expression(g.number(value),"int",value.constant)
        if value.kind in {"str","bytes"}:
            from .native_stdio import _enable, _number
            _enable(g)
            parser="native_io_parse_text" if value.kind=="str" else "native_io_parse_bytes"
            from .native_integer_parsing import parse_value
            call=parse_value(g,value,node) or g.at(f"{parser}(&({value.code}))",node)
            return _Expression(_number(g,call),"int")
    if name == "abs" and value.kind=='float':
        return _Expression(f"({value.code}).abs()",'float')
    if name == "abs" and value.kind in {"int","bool","int_bool"}:
        code=g.number(value)
        return _Expression(f"({code}).wrapping_abs()" if g.bits else f"({code}).abs()","int")
    if name == "str" and value.kind in {"int","bool","int_bool","str"}:
        if g.bits:g.has_extended_scalars=True
        else:g.has_big_text=True
        code=(g.coerce(value,"str") if value.kind=="str" else
              f'(if {value.code} {{"True"}}else{{"False"}}).to_owned()' if value.kind=="bool" else
              f"({value.code}).to_string()")
        return _text_expression(code,char_code=value.char_code if value.kind=="str"else None)
    if name == "len" and value.kind in {"str","bytes","list_int","matrix_int","dict_int","set_int","deque_int"}:
        from .native_characters import length as character_length
        projected=character_length(g,value)
        if projected is not None:return projected
        from .native_cached_text import text_length
        length=text_length(value,g.string_mode)if value.kind=="str"else f"({value.code}).len()"
        code=f"({length}) as NativeInt"if g.bits else f"Int::from_i128(({length}) as i128)"
        return _Expression(code,"int",value.length)
    raise _Unsupported


def try_expression(g,node,environment):
    """A captured scalar builtin uses its identity even after name shadowing."""
    import ast
    if not isinstance(node,ast.Call):return None
    from .references import callable_reference
    identity=callable_reference(g,node.func,environment)
    if not isinstance(identity,BuiltinIdentity) or identity.name not in UNARY_BUILTINS:
        return None
    if isinstance(node.func,ast.Name) and node.func.id==identity.name:
        return None
    from .call_semantics import FunctionSignature,CallBindingError
    from .native_stream_plans import context
    normalizer=context(g,environment)
    signature=FunctionSignature.declaration(("value",),positional_only=("value",))
    try:bound=normalizer.bind(normalizer.invocation(node),signature)
    except CallBindingError as error:raise _Unsupported from error
    read=getattr(g,"read_expression",g.expression) if identity.name in {"len","int","bool"} else g.expression
    value=read(bound.binding["value"].expression,environment)
    return unary(g,identity,value,node)
