"""Captured integer builtin calls over the existing shared arithmetic runtime."""
import ast
from itertools import product

from .call_semantics import FunctionSignature,normalize_call
from .native_types import alternatives,union_type
from .references import BuiltinIdentity


POW_SIGNATURE=FunctionSignature.declaration(('base','exp','mod'),default_names=('mod',))
INTEGRAL=frozenset({'int','bool','int_bool'})
SEALED=frozenset({'int','bool','int_bool','float','complex','str','bytes','none','list','tuple','function','globals_dict','range'})


def _bind(arguments,keywords,default):
    """Argument Clinic's binding precedence over already evaluated values."""
    keywords=tuple(keywords)
    count=len(arguments)+len(keywords)
    if count>3:return None,f'TypeError: pow() takes at most 3 arguments ({count} given)'
    names={name for name,_ in keywords}
    for position,name in enumerate(('base','exp')):
        if len(arguments)<=position and name not in names:
            return None,f"TypeError: pow() missing required argument '{name}' (pos {position+1})"
    for position,name in enumerate(POW_SIGNATURE.positional):
        if position<len(arguments)and name in names:
            return None,f"TypeError: argument for pow() given by name ('{name}') and position ({position+1})"
    for name,_ in keywords:
        if name not in POW_SIGNATURE.parameters:
            return None,f"TypeError: pow() got an unexpected keyword argument '{name}'"
    return POW_SIGNATURE.bind(arguments,keywords,{'mod':default}),None


def _exponent_literal(node,call_arguments,integer):
    """Only actual explicit call metadata can establish a literal value proof."""
    if not isinstance(node,ast.Call):return False
    metadata=normalize_call(node)if call_arguments is None else call_arguments
    if (len(metadata.positional)!=len(node.args)or len(metadata.keywords)!=len(node.keywords)
            or any(item.expression is not source for item,source in zip(metadata.positional,node.args))
            or any(item.name!=source.arg or item.expression is not source.value
                   for item,source in zip(metadata.keywords,node.keywords))):return False
    binding,error=_bind(metadata.positional,((item.name,item)for item in metadata.keywords),None)
    if error:return False
    from .literal_semantics import Literal,integer_policy
    exponent=Literal.from_ast(binding['exp'].expression)
    bits={'i64':64,'i128':128,'bigint':0}[integer]
    return exponent is not None and exponent.kind in {'int','bool'}and integer_policy(bits).normalize(exponent.value)>=0


def _plan(kinds,nonnegative,integer,node):
    from .native_classes import ClassUnsupported,domain
    tags=tuple(domain(kind)for kind in kinds)
    if not all(tag in SEALED for tag in tags):
        raise ClassUnsupported(node,'pow with these objects needs Python __pow__/__rpow__ and integer-index dispatch; those user object protocols are not implemented by this native numeric adapter',types=tuple(zip(('base','exp','mod'),kinds)),proof='power operand special-method protocol')
    if tags[2]=='none':
        if 'complex'in tags[:2]and set(tags[:2])<=INTEGRAL|{'float','complex'}:return 'complex'
        if tags[0]=='float'and tags[1]in INTEGRAL:return 'float'
        if set(tags[:2])<=INTEGRAL:
            if not nonnegative:
                return union_type('int','float')
            return 'int'
        if set(tags[:2])<=INTEGRAL|{'float'}:
            from .native_float_powers import RESULT
            return RESULT
        return 'none'
    return 'int'if set(tags)<=INTEGRAL else'none'


def analyze(model,plan,node,identity,arguments,keywords,environment,*,factory,call_arguments=None):
    if identity!=BuiltinIdentity('pow'):return None
    from .native_classes import Cell,shape
    binding,error=_bind(arguments,keywords,Cell('none'))
    if error:return factory('none')
    kinds=tuple(shape(value)for value in binding.values)
    if None in kinds and not model.final:return factory()
    if kinds[2]=='none':
        from .native_float_powers import record_call
        record_call(model,plan,node,call_arguments)
        custom=model.operators.binary(plan,node,ast.Pow(),binding['base'],binding['exp'],environment,identity=('builtin_pow',identity))
        if custom is not None:
            result=factory()
            model.contribute(result,custom,node)
            return result
    proof=_exponent_literal(node,call_arguments,model.integer)
    outputs=[_plan(choices,proof,model.integer,node)for choices in product(*(alternatives(kind)for kind in kinds))]
    from .native_float_powers import kind as power_kind,RESULT
    outputs=[power_kind(node,model.integer,model=model,plan=plan)if output==RESULT else output for output in outputs]
    result=factory()
    model.contribute(result,model.cell_for_kind(union_type(*outputs)),node)
    return result


def _error(emitter,node,kind,message):
    from .native_classes import Expression
    return Expression(emitter.at(f'Err::<{emitter.rust_type(kind)},String>({message})',node),kind)


def emit(emitter,node,identity,arguments,keywords,wanted):
    if identity!=BuiltinIdentity('pow'):return None
    from .native import _string
    from .native_classes import Expression,domain
    from .native_unions import project,union_kind
    binding,error=_bind(arguments,tuple(keywords.items())if hasattr(keywords,'items')else keywords,Expression('()','none'))
    if error:return _error(emitter,node,wanted,_string(error)+'.to_owned()')
    custom=emitter.model.operators.emit_binary(emitter,ast.Pow(),binding['base'],binding['exp'],node,wanted,identity=('builtin_pow',identity))
    if custom is not None:return custom
    def lower(values):
        for index,value in enumerate(values):
            if union_kind(value.kind):
                return Expression(project(value.kind,value.code,lambda kind,code:lower(
                    values[:index]+[Expression(f'({code}).clone()',kind)]+values[index+1:]).code),wanted)
        tags=tuple(domain(value.kind)for value in values)
        from .native_complex_powers import dispatch,convert
        selected=dispatch(tags)
        if selected=='complex':
            if tags[2]=='none':return emitter.binary(ast.Pow(),values[0],values[1],node,wanted)
            first,second=emitter.fresh(),emitter.fresh()
            setup='let '+first+'='+convert(emitter,values[0],node)+';let '+second+'='+convert(emitter,values[1],node)+';'
            value=_error(emitter,node,wanted,_string('ValueError: complex modulo')+'.to_owned()')
            return Expression('{'+setup+value.code+'}',wanted)
        if selected=='float_mod':return _error(emitter,node,wanted,_string('TypeError: pow() 3rd argument not allowed unless all arguments are integers')+'.to_owned()')
        if tags[2]=='none'and set(tags[:2])<=INTEGRAL|{'float'}:
            return emitter.binary(ast.Pow(),values[0],values[1],node,wanted)
        if set(tags)<=INTEGRAL:
            numbers=[emitter.number(value)for value in values]
            if emitter.model.integer=='bigint':
                call=f'({numbers[0]}).modpow(&({numbers[1]}),&({numbers[2]}))'
                code=emitter.at(call,node)
            else:
                call='native_fixed_modpow('+','.join(numbers)+')'
                code=emitter.at(call,node)
            return emitter.encoded(code,'int',wanted,node)
        from .native_class_builtins import _type_name
        count=2 if tags[2]=='none'else 3
        message=("TypeError: unsupported operand type(s) for ** or pow(): '{}', '{}', '{}'"if count==3 else
                 "TypeError: unsupported operand type(s) for ** or pow(): '{}' and '{}'")
        names=','.join(_type_name(emitter,value,node)for value in values[:count])
        return _error(emitter,node,wanted,f'format!({_string(message)},{names})')
    return lower(list(binding.values))
