"""Resolved builtin length with one argument evaluation and no probing passes."""
import ast

from .call_semantics import CallBindingError,FunctionSignature,normalize_call
from .native import _Binding,_Expression,_Unsupported,_string
from .native_types import ListType,TupleType,TupleSequenceType
from .native_key_types import DictType,SetType
from .references import BuiltinIdentity,callable_reference


_SIGNATURE=FunctionSignature.declaration(("obj",),positional_only=("obj",))
_VIEW_SIGNATURE=FunctionSignature.declaration()
_CONTAINERS={"list_int","matrix_int","deque_int","dict_int","set_int","bytes"}


def _text_read(g,node,environment):
    """Prove a borrowable text read without lowering an unknown expression."""
    from .native_characters import CharacterBinding
    if isinstance(node,ast.Name):
        binding=environment.get(node.id)
        return isinstance(binding,CharacterBinding)or isinstance(binding,_Binding)and binding.kind=="str"
    if isinstance(node,ast.Constant):return type(node.value)is str
    if (isinstance(node,ast.Call)and len(node.args)==1 and not node.keywords
            and callable_reference(g,node.func,environment)==BuiltinIdentity("str")):
        return _text_read(g,node.args[0],environment)
    return False


def _length(g,value,node):
    """Return usize from a captured value; never visit its source AST again."""
    kind=value.kind
    if isinstance(kind,TupleType):return f"{len(kind.fields)}_usize"
    if isinstance(kind,(ListType,TupleSequenceType,DictType,SetType))or kind in _CONTAINERS:
        return f"({value.code}).len()"
    if kind=="str":
        from .native_cached_text import text_length
        return text_length(value,g.string_mode)
    from .native_unions import union_kind,project
    if union_kind(kind):
        code=project(kind,value.code,lambda child,inner:_length_result(g,_Expression(inner,child),node))
        return g.at(code,node)
    if kind in {"int","bool","int_bool","float","none"}:
        return g.at(_length_result(g,value,node),node)
    raise _Unsupported("builtin len requires a native __len__ protocol adapter for this value representation; that adapter is not implemented",node=node,types=(("argument",kind),),proof="Python length protocol and nonnegative index-sized result")


def _length_result(g,value,node):
    kind=value.kind
    if kind in {"int","bool","int_bool","float","none"}:
        if kind=="int_bool":
            name=f'match &({value.code}){{NativeScalar::Int(_)=>"int",NativeScalar::Bool(_)=>"bool"}}'
            message=f'format!("TypeError: object of type \'{{}}\' has no len()",{name})'
        else:message=_string("TypeError: object of type '"+("NoneType"if kind=="none"else kind)+"' has no len()")+".to_owned()"
        return f"Err::<usize,String>({message})"
    return f"Ok::<usize,String>({_length(g,value,node)})"


def _argument(g,node,environment):
    """A builtin dict view has the owner's length, without materialization."""
    if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and node.func.attr in {"keys","values","items"}:
        try:_VIEW_SIGNATURE.plan(normalize_call(node))
        except CallBindingError as error:
            raise _Unsupported("binding this dictionary-view call requires a supported zero-argument view signature ("+str(error)+")",node=node,proof="builtin dictionary view call binding")from error
        owner=g.expression(node.func.value,environment)
        if not (owner.kind=="dict_int"or isinstance(owner.kind,DictType)):
            raise _Unsupported("len of this member result needs a proved dictionary-view identity; the receiver is not a supported builtin dictionary representation",node=node,types=(("receiver",owner.kind),),proof="builtin dictionary view identity")
        return owner
    if _text_read(g,node,environment):return g.read_expression(node,environment)
    return g.expression(node,environment)


def try_expression(g,node,environment):
    if not isinstance(node,ast.Call)or callable_reference(g,node.func,environment)!=BuiltinIdentity("len"):
        return None
    try:
        arguments=normalize_call(node)
        binding=_SIGNATURE.bind(arguments.positional,tuple((argument.name,argument)for argument in arguments.keywords))
    except CallBindingError as error:
        raise _Unsupported("binding builtin len requires exactly one positional argument; emitting Python TypeError for this call is not implemented ("+str(error)+")",node=node,operation="builtin len argument binding")from error
    value=_argument(g,binding.by_name["obj"].expression,environment)
    from .native_characters import length as character_length
    character=character_length(g,value)
    if character is not None:return character
    owner=g.temporary()
    # Borrowing an existing container avoids moving its caller's storage. An
    # owned producer stays alive only through this call's length observation.
    captured=value.code if value.owned else f"&({value.code})"
    length=_length(g,_Expression(owner,value.kind),node)
    number=f"({length}) as NativeInt"if g.bits else f"Int::from_i128(({length}) as i128)"
    return _Expression(f"{{let {owner}={captured};{number}}}","int")
