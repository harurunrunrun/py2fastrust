"""Finite primitive operator plans over concrete tagged native alternatives.

Choose a supported operation, a proved Python type error, or a missing protocol
before emission. An unsupported lowering is never retried as an error path.
"""
import ast
from dataclasses import dataclass

from .native_types import alternatives,union_type,ListType,join_types

NUMERIC=frozenset({"int","bool","int_bool","float"})
INTEGRAL=NUMERIC-{"float"}
BITWISE=(ast.BitAnd,ast.BitOr,ast.BitXor)
INTEGER=(ast.Add,ast.Sub,ast.Mult,ast.FloorDiv,ast.Mod,ast.Pow,ast.LShift,ast.RShift)+BITWISE
FLOAT=(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod)


@dataclass(frozen=True)
class PrimitivePlan:
    kind: object=None
    error: str|None=None
    protocol: str|None=None


def classify(operator,left,right,integer):
    from .native_classes import domain
    a,b=domain(left),domain(right)
    if "list"in {a,b}:
        sealed=NUMERIC|{"str","bytes","tuple","none","function","globals_dict","range","list"}
        if {a,b}<=sealed:
            if isinstance(operator,ast.Add)and a=="list"and b!="list":return PrimitivePlan(error="concat")
            if isinstance(operator,ast.Mult):
                other=b if a=="list"else a
                if other not in INTEGRAL:return PrimitivePlan(error="repeat")
                return PrimitivePlan(left if a=="list"else right)
            elif isinstance(operator,ast.Add)and a==b=="list":
                return PrimitivePlan(ListType(join_types(left.element,right.element)))
            elif not(isinstance(operator,ast.Add)and a==b=="list"):
                return PrimitivePlan(error="binary")
        return PrimitivePlan(protocol="per-alternative mutable sequence and inplace-operation storage")
    if isinstance(operator,ast.BitOr):
        if a==b=="globals_dict":return PrimitivePlan(protocol="dictionary union value/mutation protocol")
        for value in (left,right):
            if any(identity.name in {"int","bool","float","str","list","range","map","enumerate"}
                   for identity in getattr(value,"builtins",())):
                return PrimitivePlan(protocol="builtin class union-type protocol")
    if a in NUMERIC and b in NUMERIC:
        if "float"in {a,b}or isinstance(operator,ast.Div):
            if "float"in {a,b}and isinstance(operator,(ast.LShift,ast.RShift)+BITWISE):return PrimitivePlan(error="binary")
            if not isinstance(operator,FLOAT):return PrimitivePlan(protocol="binary64 power/numeric operation")
            if integer=="bigint":return PrimitivePlan(protocol="BigInt/binary64 numeric interoperation")
            return PrimitivePlan("float")
        if isinstance(operator,INTEGER):
            if isinstance(operator,BITWISE)and {a,b}<={"bool","int_bool"}:
                return PrimitivePlan("bool"if a==b=="bool"else"int_bool")
            return PrimitivePlan("int")
        return PrimitivePlan(error="binary")
    if isinstance(operator,ast.Add)and a==b=="str":return PrimitivePlan("str")
    if isinstance(operator,ast.Mult)and "str"in {a,b}and(a if b=="str"else b)in INTEGRAL:return PrimitivePlan("str")
    if isinstance(operator,ast.Mod)and a in {"str","bytes"}:
        return PrimitivePlan(protocol="string/bytes percent-formatting protocol")
    if isinstance(operator,ast.Add)and a==b and a in {"bytes","tuple"}:
        return PrimitivePlan(protocol="bytes/tuple concatenation storage")
    if isinstance(operator,ast.Mult)and(a in {"bytes","tuple"}and b in INTEGRAL or b in {"bytes","tuple"}and a in INTEGRAL):
        return PrimitivePlan(protocol="bytes/tuple repetition storage")
    if isinstance(operator,ast.Add)and a in {"str","bytes","tuple"}:return PrimitivePlan(error="concat")
    if isinstance(operator,ast.Mult)and {a,b}&{"str","bytes","tuple"}:return PrimitivePlan(error="repeat")
    return PrimitivePlan(error="binary")


def operation_plan(operator,left,right,integer,node):
    from .native_classes import domain
    if isinstance(node,ast.AugAssign)and isinstance(operator,ast.Add)and domain(left)=="list"and domain(right)!="list":
        if domain(right)in NUMERIC|{"none","function"}:return PrimitivePlan(error="inplace_iter")
        return PrimitivePlan(protocol="per-alternative list inplace extension from this iterable's registered pull adapter")
    return classify(operator,left,right,integer)


def analyze(model,plan,node,operator,left,right,*,identity=None):
    from .native_classes import ClassUnsupported,shape,Cell,merge
    from .native_union_sequences import branches
    kinds=[]
    sequences=[]
    sources=getattr(model,"sequence_sources",None)
    if sources is None:sources=model.sequence_sources={}
    for a in branches(left):
        for b in branches(right):
            child=None
            if a.tag==b.tag=="list"and isinstance(operator,ast.Add):
                merge(a.args[0],b.args[0],node,allow_unresolved=not model.final)
                child=a.args[0]
            elif isinstance(operator,ast.Mult)and(a.tag=="list"and b.tag in INTEGRAL or b.tag=="list"and a.tag in INTEGRAL):
                source=a if a.tag=="list"else b
                child=source.args[0]
            if child is not None:
                # Namespace flow inputs can be weak. Own this operation's
                # constructor facts independently of a transient solver pass.
                key=plan.index,id(node),identity,a,b
                source=sources.setdefault(key,Cell("list",(child,)))
                source.args=(child,)
                sequences.append(source)
    for a in alternatives(shape(left)):
        for b in alternatives(shape(right)):
            selected=operation_plan(operator,a,b,model.integer,node)
            if selected.protocol:
                raise ClassUnsupported(node,"this finite operand combination needs "+selected.protocol+"; that per-alternative native operation is not implemented",types=(("left",a),("right",b)),proof=selected.protocol)
            if selected.kind is not None:kinds.append(selected.kind)
    if isinstance(operator,ast.Pow)and"int"in kinds:
        from .literal_semantics import Literal,integer_policy
        expression=getattr(node,"right",getattr(node,"value",None))
        literal=Literal.from_ast(expression)
        bits=0 if model.integer=="bigint"else 64 if model.integer=="i64"else 128
        if literal is None or literal.kind not in {"int","bool"}or integer_policy(bits).normalize(literal.value)<0:
            raise ClassUnsupported(node,"this finite power needs proof of a nonnegative exponent; negative integral powers produce binary64 results whose runtime result carrier is not implemented here",proof="power exponent/result-type proof")
    kind=union_type(*kinds)if kinds else"none"
    result=model.cell(plan,node,identity=identity)
    if sequences:
        for value in sequences:
            if not model.namespace.contribute(result,value,node,force=True):model.contribute(result,value,node)
        for kind in kinds:
            if not isinstance(kind,ListType):model.contribute(result,model.cell_for_kind(kind),node)
    else:model.contribute(result,model.cell_for_kind(kind),node)
    return result


def emit(emitter,operator,left,right,node,wanted):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_unions import project,union_kind
    if union_kind(left.kind):
        return Expression(project(left.kind,left.code,lambda kind,code:emit(emitter,operator,Expression(f"({code}).clone()",kind),right,node,wanted).code),wanted)
    if union_kind(right.kind):
        return Expression(project(right.kind,right.code,lambda kind,code:emit(emitter,operator,left,Expression(f"({code}).clone()",kind),node,wanted).code),wanted)
    selected=operation_plan(operator,left.kind,right.kind,emitter.model.integer,node)
    if selected.protocol:
        raise ClassUnsupported(node,"this operand combination needs "+selected.protocol,proof=selected.protocol)
    if selected.kind is not None:
        from .native_classes import domain
        if isinstance(node,ast.AugAssign)and domain(left.kind)=="list":
            if isinstance(operator,ast.Add):
                operation=f"class_list_extend(&{left.code},&{right.code});"
            elif isinstance(operator,ast.Mult):
                operation=emitter.at(f"class_list_repeat_in_place(&{left.code},&({emitter.number(right)}))",node)+";"
            else:operation=None
            if operation is not None:
                value=Expression("{"+operation+left.code+".clone()}",left.kind)
                return Expression(emitter.coerce(value,wanted,node),wanted)
        value=emitter.binary(operator,left,right,node,selected.kind)
        return Expression(emitter.coerce(value,wanted,node),wanted)
    from .native import _string
    from .native_class_builtins import _type_name,_error
    a,b=domain(left.kind),domain(right.kind)
    if selected.error=="inplace_iter":
        template="'{}' object is not iterable"
        values=[_type_name(emitter,right,node)]
    elif selected.error=="concat":
        if a=="bytes":template="can't concat {} to bytes"
        else:template=f'can only concatenate {a} (not "{{}}") to {a}'
        values=[_type_name(emitter,right,node)]
    elif selected.error=="repeat":
        other=right if a in {"str","bytes","tuple","list"}else left
        template="can't multiply sequence by non-int of type '{}'"
        values=[_type_name(emitter,other,node)]
    else:
        from .native_diagnostics import _OPERATORS
        symbol="** or pow()"if isinstance(operator,ast.Pow)else _OPERATORS[type(operator)]
        template=f"unsupported operand type(s) for {symbol}: '{{}}' and '{{}}'"
        values=[_type_name(emitter,left,node),_type_name(emitter,right,node)]
    return _error(emitter,node,wanted,'format!('+_string("TypeError: "+template)+','+','.join(values)+')')


def emit_plain(generator,operator,left,right,node):
    """Use the same plans on the ordinary native scalar/BigInt path."""
    from .native import _Expression,_Unsupported,_string
    from .native_unions import project,union_kind
    from .native_types import rust_type
    if not(union_kind(left.kind)or union_kind(right.kind)or left.kind=="none"or right.kind=="none"):return None
    allowed=NUMERIC|{"str","bytes","none"}
    if any(kind not in allowed for value in (left,right)for kind in alternatives(value.kind)):return None
    integer="bigint"if not generator.bits else"i64"if generator.bits==64 else"i128"
    kinds=[]
    for a in alternatives(left.kind):
        for b in alternatives(right.kind):
            selected=classify(operator,a,b,integer)
            if selected.protocol:
                raise _Unsupported("this finite operand combination needs "+selected.protocol,node=node,types=(("left",a),("right",b)),proof=selected.protocol)
            if selected.kind is not None:kinds.append(selected.kind)
    if isinstance(operator,ast.Pow)and"int"in kinds and(right.constant is None or right.constant<0):
        raise _Unsupported("this finite power needs proof of a nonnegative exponent; negative integral powers require a binary64 result carrier",node=node,proof="power exponent/result-type proof")
    wanted=union_type(*kinds)if kinds else"none"
    generator.register_type(wanted)
    first,second=generator.temporary(),generator.temporary()
    setup=f"let {first}={generator.coerce(left,left.kind)};let {second}={generator.coerce(right,right.kind)};"
    def typename(kind,code):
        if kind=="int_bool":return f'match {code}{{NativeScalar::Int(_)=>"int",NativeScalar::Bool(_)=>"bool"}}'
        return _string("NoneType"if kind=="none"else kind)
    def leaf(a,x,b,y):
        selected=classify(operator,a,b,integer)
        if selected.kind is not None:
            value=generator.binary(operator,_Expression(x,a,left.constant if a==left.kind else None),
                _Expression(y,b,right.constant if b==right.kind else None),node)
            return generator.coerce(value,wanted)
        if selected.error=="concat":
            template="can't concat {} to bytes"if a=="bytes"else f'can only concatenate {a} (not "{{}}") to {a}'
            values=[typename(b,y)]
        elif selected.error=="repeat":
            kind,code=(b,y)if a in {"str","bytes","tuple"}else(a,x)
            template="can't multiply sequence by non-int of type '{}'";values=[typename(kind,code)]
        else:
            from .native_diagnostics import _OPERATORS
            symbol="** or pow()"if isinstance(operator,ast.Pow)else _OPERATORS[type(operator)]
            template=f"unsupported operand type(s) for {symbol}: '{{}}' and '{{}}'"
            values=[typename(a,x),typename(b,y)]
        message='format!('+_string("TypeError: "+template)+','+','.join(values)+')'
        return generator.at(f"Err::<{rust_type(wanted)},String>({message})",node)
    code=project(left.kind,first,lambda a,x:project(right.kind,second,
        lambda b,y:leaf(a,f"({x}).clone()",b,f"({y}).clone()")))
    return _Expression("{"+setup+code+"}",wanted)
