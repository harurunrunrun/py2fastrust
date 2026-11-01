"""Direct binary64 operations alongside arbitrary-precision integral operands."""
import ast
from .native import _Expression,_Unsupported


def floating(generator,value,node):
    if value.kind=='float':return value.code
    if value.kind not in {'int','bool','int_bool'}:
        raise _Unsupported('binary64 arithmetic needs a builtin numeric operand; user conversion protocols are not implemented',node=node,types=(('operand',value.kind),),proof='builtin real operand conversion')
    return generator.at('('+generator.number(value)+').ratio(&Int::exact_small(1)).map_err(|_|"OverflowError: int too large to convert to float".to_owned())',node)


def binary(generator,operator,left,right,node):
    if 'float'not in {left.kind,right.kind}:return None
    numeric={'int','bool','int_bool','float'}
    if left.kind not in numeric or right.kind not in numeric:return None
    if not isinstance(operator,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod)):
        raise _Unsupported('this binary64 operation needs its power, complex-result or integer-only protocol',node=node,types=(('left',left.kind),('right',right.kind)),proof='binary64 operation selection')
    generator.has_extended_scalars=True
    first,second,a,b=(generator.temporary()for _ in range(4))
    # Both Python operands evaluate before primitive numeric conversion begins.
    setup='let '+first+'='+left.code+';let '+second+'='+right.code+';'
    setup+='let '+a+'='+floating(generator,_Expression(first,left.kind),node)+';'
    setup+='let '+b+'='+floating(generator,_Expression(second,right.kind),node)+';'
    if isinstance(operator,(ast.Add,ast.Sub,ast.Mult)):
        symbol={ast.Add:'+',ast.Sub:'-',ast.Mult:'*'}[type(operator)]
        result=a+symbol+b
    elif isinstance(operator,ast.Div):result=generator.at('native_float_div('+a+','+b+')',node)
    else:result=generator.at('native_float_divmod('+a+','+b+')',node)+('.0'if isinstance(operator,ast.FloorDiv)else'.1')
    return _Expression('{'+setup+result+'}','float')
