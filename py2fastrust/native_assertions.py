"""Shared conditional assertion failure, independent of Rust optimization."""
import ast


def literal_truth(node,bits=None):
    """A total literal proof may discard the unreachable failure expression."""
    from .literal_semantics import Literal,integer_policy
    literal=Literal.from_ast(node)
    if isinstance(node,ast.UnaryOp)and isinstance(node.op,(ast.UAdd,ast.USub)):
        operand=Literal.from_ast(node.operand)
        if operand is not None and operand.kind in {'int','bool','float'}:
            literal=Literal.from_value(-operand.value if isinstance(node.op,ast.USub)else +operand.value)
    if literal is None:return None
    value=literal.value
    if literal.kind=='int':
        if bits is None:
            # The profile-independent solver cannot assume huge literals have
            # the same truth after i64/i128 normalization.
            if not -(1<<63)<=value<(1<<63):return None
        else:value=integer_policy(bits).normalize(value)
    return bool(value)


def analyze(model,plan,node,environment):
    from .native_classes import Environment
    model.condition(plan,node.test,environment)
    bits=0 if model.integer=='bigint'else 128 if model.integer=='i128'else 64
    if node.msg is not None and literal_truth(node.test,bits)is not True:
        # This path raises; its binding effects never reach the normal edge.
        model.expression(plan,node.msg,Environment(environment))


def _message_supported(kind):
    from .native_types import ListType,TupleType,NullableType,MaybeType,UnionType,EmptyType
    if isinstance(kind,EmptyType):return True
    if isinstance(kind,(NullableType,MaybeType)):return _message_supported(kind.value)
    if isinstance(kind,UnionType):return all(_message_supported(value)for value in kind.alternatives)
    if isinstance(kind,ListType):return _message_supported(kind.element)
    if isinstance(kind,TupleType):return all(_message_supported(value)for value in kind.fields)
    if getattr(kind,'_key_container',False):
        return _message_supported(kind.key)and(not hasattr(kind,'value')or _message_supported(kind.value))
    return kind in {'int','bool','int_bool','str','bytes','float','none','list_int','dict_int','set_int','deque_int','matrix_int'}


def lower(g,node,environment=None):
    from .native import _Expression,_Unsupported
    framed=environment is None
    condition=g.condition(node.test)if framed else g.condition(node.test,environment)
    name=g.fresh()if framed else g.temporary()
    setup=f'let {name}={condition.code};'
    known=condition.constant
    if known is None:
        bits=(0 if g.model.integer=='bigint'else 128 if g.model.integer=='i128'else 64)if framed else g.bits
        known=literal_truth(node.test,bits)
    if known is True:return setup
    if node.msg is None:failure='String::from("AssertionError")'
    else:
        value=g.expression(node.msg)if framed else g.expression(node.msg,environment.copy())
        if not _message_supported(value.kind):
            raise _Unsupported('this assertion message requires Python object/function string conversion or recursive container protocols; those exception-message protocols are not implemented',node=node.msg,operation='assertion message conversion',types=(('message',value.kind),),proof='Python AssertionError message string protocol')
        captured=g.fresh()if framed else g.temporary()
        text=g.fresh()if framed else g.temporary()
        saved=_Expression(captured,value.kind,owned=False)
        captured_code=value.code
        if not value.owned:
            from .native_types import reference_cloneable
            if framed:captured_code=f'({value.code}).clone()'
            elif reference_cloneable(value.kind):captured_code=g.coerce(value,value.kind)
            else:captured_code=f'&({value.code})'
        try:
            if framed:formatted=g.show(saved,node.msg)
            elif value.kind=='none':formatted='String::from("None")'
            else:
                from .native_typed_lists import _representation
                formatted=_representation(g,saved)
        except _Unsupported as error:
            raise _Unsupported('the assertion message has no complete builtin representation adapter for its solved native storage; conditional failure is implemented, but this value needs additional Python string/repr protocol support',node=node.msg,operation='assertion message representation',types=(('message',value.kind),),proof='exception message representation')from error
        failure=('{let '+captured+'='+captured_code+';let '+text+'='+formatted+';'
                 'if '+text+'.is_empty(){String::from("AssertionError")}else{format!("AssertionError: {}",'+text+')}}')
    error=g.at('Err::<(),String>('+failure+')',node)
    return setup+'if !'+name+'{'+error+';}'
