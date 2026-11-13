"""Official complex literal leaves and their concrete primitive consumers."""
import ast

NUMERIC=frozenset({'int','bool','int_bool','float','complex'})
CLOSED=NUMERIC|{'none','str','bytes'}


def requires_frames(unit,analysis):
    sites={unit.ordinal(node)for node in ast.walk(unit.tree)
           if isinstance(node,ast.Constant)and type(node.value)is complex}
    return any(site in sites for facts in analysis.scopes.values()for site in facts.expressions)


def _kind(operator,kind):
    if kind not in NUMERIC:return None
    if isinstance(operator,ast.Invert)and kind in {'float','complex'}:return None
    return kind if kind in {'float','complex'}else 'int'


def analyze_unary(model,plan,node,operator,value):
    from .native_classes import shape
    from .native_types import alternatives,union_type
    kinds=alternatives(shape(value))
    if 'complex'not in kinds or not set(kinds)<=CLOSED:return None
    outputs=[kind for source in kinds if(kind:=_kind(operator,source))is not None]
    result=model.cell(plan,node)
    model.contribute(result,model.cell_for_kind(union_type(*outputs)if outputs else 'none'),node)
    return result


def unary(emitter,operator,value,node,wanted):
    from .native_classes import Expression
    from .native_types import alternatives
    from .native_unions import union_kind,project
    from .native_class_builtins import _type_name,_error
    from .native import _string
    kinds=alternatives(value.kind)
    if 'complex'not in kinds or not set(kinds)<=CLOSED:return None
    def lower(kind,code):
        current=Expression('('+code+').clone()',kind)
        if _kind(operator,kind)is None:
            symbol={ast.UAdd:'+',ast.USub:'-',ast.Invert:'~'}[type(operator)]
            return _error(emitter,node,wanted,'format!('+_string("TypeError: bad operand type for unary "+symbol+": '{}'")+','+_type_name(emitter,current,node)+')').code
        if kind!='complex':return emitter.unary_builtin(operator,current,node,wanted).code
        emitter.model.complex_values_required=True
        raw=(current.code if isinstance(operator,ast.UAdd)else
             'NativeComplex{real:-('+current.code+').real,imag:-('+current.code+').imag}')
        return emitter.coerce(Expression(raw,'complex'),wanted,node)
    code=project(value.kind,value.code,lower)if union_kind(value.kind)else lower(value.kind,value.code)
    return Expression(code,wanted)


def absolute(emitter,value,node,wanted):
    if value.kind!='complex':return None
    from .native_classes import Expression
    from .native_float_identity import wrap
    emitter.model.complex_values_required=True
    emitter.model.complex_abs_required=True
    raw=emitter.at('native_complex_abs(&('+value.code+'))',node)
    return Expression(emitter.coerce(Expression(wrap(emitter,raw,node),'float'),wanted,node),wanted)


def runtime(model):
    if not getattr(model,'complex_abs_required',False):return ''
    return r'''
fn native_complex_abs(value:&NativeComplex)->Result<f64,String>{
 let result=value.real.hypot(value.imag);
 if result.is_infinite()&&value.real.is_finite()&&value.imag.is_finite(){return Err("OverflowError: absolute value too large".to_owned());}
 Ok(result)
}
'''
