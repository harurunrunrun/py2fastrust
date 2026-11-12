"""Integer power has an integer or binary64 result, selected by exponent sign."""
import ast

from .native_types import union_type

INTEGRAL=frozenset({'int','bool','int_bool'})
RESULT=union_type('int','float')


def exponent_node(node):
    if isinstance(node,ast.BinOp)and isinstance(node.op,ast.Pow):return node.right
    if isinstance(node,ast.AugAssign)and isinstance(node.op,ast.Pow):return node.value
    return None


def node_kind(node,integer):
    from .literal_semantics import Literal,integer_policy
    literal=Literal.from_ast(exponent_node(node))
    if literal is not None and literal.kind in {'int','bool'}:
        bits={'i64':64,'i128':128,'bigint':0}[integer]
        return 'int'if integer_policy(bits).normalize(literal.value)>=0 else'float'
    if isinstance(node,ast.Call):
        from .native_class_numeric_calls import _exponent_literal
        if _exponent_literal(node,None,integer):return 'int'
    return RESULT


def semantic_kind(node):
    """The width-independent solver narrows only literals safe in all modes."""
    from .literal_semantics import Literal
    literal=Literal.from_ast(exponent_node(node))
    if literal is None or literal.kind not in {'int','bool'}:return RESULT
    if 0<=literal.value<1<<63:return 'int'
    if -(1<<63)<=literal.value<0:return 'float'
    return RESULT


def _real(first,second,at,encode,floating,fresh,*,base_is_float=False):
    base,exponent,result=fresh(),fresh(),fresh()
    call=(f'if {base}==0.0_f64&&{exponent}<0.0_f64{{Err("ZeroDivisionError: zero to a negative power".to_owned())}}'
        f'else{{let {result}=({base}).powf({exponent});'
        f'if {result}.is_infinite()&&{base}.is_finite(){{Err("OverflowError: (34, \'Numerical result out of range\')".to_owned())}}'
        f'else{{Ok({result})}}}}')
    return ('{'+f'let {base}={first if base_is_float else floating(first)};let {exponent}={floating(second)};'
        +encode(at(call),'float')+'}')


def _build(bits,first,second,kind,at,encode,floating,fresh):
    integer=at(f'native_pow({first},{second})'if bits else f'({first}).pow(&{second})')
    def real():return _real(first,second,at,encode,floating,fresh)
    if kind=='int':return encode(integer,'int')
    if kind=='float':return real()
    negative=f'{second}<0'if bits else f'({second}).is_negative()'
    return f'if {negative}{{{real()}}}else{{{encode(integer,"int")}}}'


def plain(generator,operator,left,right,node):
    if not isinstance(operator,ast.Pow)or left.kind not in INTEGRAL|{'float'}or right.kind not in INTEGRAL:return None
    from .native import _Expression
    integer='bigint'if not generator.bits else'i64'if generator.bits==64 else'i128'
    kind=('float'if left.kind=='float'else
        ('int'if right.constant>=0 else'float')if right.constant is not None else node_kind(node,integer))
    if kind=='int'and right.constant is not None:return None
    generator.register_type(kind)
    first,second=generator.temporary(),generator.temporary()
    setup=f'let {first}={left.code if left.kind=="float"else generator.number(left)};let {second}={generator.number(right)};'
    def at(code):return generator.at(code,node)
    def encode(code,source):return generator.coerce(_Expression(code,source,owned=True),kind)
    def floating(code):
        generator.has_extended_scalars=True
        if generator.bits:return f'({code})as f64'
        return at(f'({code}).ratio(&Int::exact_small(1)).map_err(|_|"OverflowError: int too large to convert to float".to_owned())')
    code=(_real(first,second,at,encode,floating,generator.temporary,base_is_float=True)if left.kind=='float'else
        _build(generator.bits,first,second,kind,at,encode,floating,generator.temporary))
    return _Expression('{'+setup+code+'}',kind,owned=True)


def frame(emitter,operator,left,right,node,wanted):
    if not isinstance(operator,ast.Pow)or left.kind not in INTEGRAL|{'float'}or right.kind not in INTEGRAL:return None
    from .native_classes import Expression
    kind=('float'if left.kind=='float'else
        ('int'if right.constant>=0 else'float')if right.constant is not None else node_kind(node,emitter.model.integer))
    if kind=='int'and right.constant is not None:return None
    first,second=emitter.fresh(),emitter.fresh()
    setup=f'let {first}={left.code if left.kind=="float"else emitter.number(left)};let {second}={emitter.number(right)};'
    bits={'i64':64,'i128':128,'bigint':0}[emitter.model.integer]
    def at(code):return emitter.at(code,node)
    def encode(code,source):return emitter.encoded(code,source,wanted,node).code
    def floating(code):
        if bits:return f'({code})as f64'
        return at(f'({code}).ratio(&Int::exact_small(1)).map_err(|_|"OverflowError: int too large to convert to float".to_owned())')
    code=(_real(first,second,at,encode,floating,emitter.fresh,base_is_float=True)if left.kind=='float'else
        _build(bits,first,second,kind,at,encode,floating,emitter.fresh))
    return Expression('{'+setup+code+'}',wanted)
