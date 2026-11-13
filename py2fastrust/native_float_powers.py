"""Binary64 power with a finite real/complex native result.

Semantic reference: CPython 3.14 Objects/floatobject.c, float_pow.
This independent implementation uses Rust's native floating operations.
"""
import ast
import math

from .native_types import union_type, alternatives

INTEGRAL=frozenset({'int','bool','int_bool'})
NUMERIC=INTEGRAL|{'float'}
RESULT=union_type('float','complex')


def _real_literals(base,exponent,integer=None):
    from .literal_semantics import Literal,integer_policy
    power=Literal.from_ast(exponent)
    if power is not None and power.kind=='float':
        if not math.isfinite(power.value)or power.value.is_integer():return True
    value=Literal.from_ast(base)
    if value is None:return False
    if value.kind=='float':return not math.isfinite(value.value)or value.value>=0
    if value.kind in{'int','bool'}:
        if integer is None:return 0<=int(value.value)<1<<63
        bits={'i64':64,'i128':128,'bigint':0}[integer]
        return integer_policy(bits).normalize(int(value.value))>=0
    return False


def real_node(node,integer=None):
    if isinstance(node,ast.BinOp)and isinstance(node.op,ast.Pow):
        return _real_literals(node.left,node.right,integer)
    if isinstance(node,ast.AugAssign)and isinstance(node.op,ast.Pow):
        return _real_literals(node.target,node.value,integer)
    return False


def record_call(model,plan,node,call_arguments):
    """A literal proof belongs to the original explicitly bound invocation."""
    from .call_semantics import normalize_call
    from .native_class_numeric_calls import _bind
    proof=False
    if isinstance(node,ast.Call):
        metadata=normalize_call(node)if call_arguments is None else call_arguments
        if (len(metadata.positional)==len(node.args)and len(metadata.keywords)==len(node.keywords)
                and all(item.expression is source for item,source in zip(metadata.positional,node.args))
                and all(item.name==source.arg and item.expression is source.value
                        for item,source in zip(metadata.keywords,node.keywords))):
            bound,error=_bind(metadata.positional,((item.name,item)for item in metadata.keywords),None)
            if error is None:proof=_real_literals(bound['base'].expression,bound['exp'].expression,model.integer)
    sites=getattr(model,'float_power_real_sites',None)
    if sites is None:sites=model.float_power_real_sites={}
    key=plan.index,id(node)
    sites[key]=sites.get(key,True)and proof


def kind(node,integer=None,*,model=None,plan=None):
    real=real_node(node,integer)
    if model is not None and plan is not None:
        real=real or getattr(model,'float_power_real_sites',{}).get((plan.index,id(node)),False)
    return 'float'if real else RESULT


def requires_frames(unit,analysis):
    from .references import BuiltinIdentity
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for facts in analysis.scopes.values():
        for site,node in nodes.items():
            if isinstance(node,(ast.BinOp,ast.AugAssign))and isinstance(node.op,ast.Pow):
                base,exponent=(node.left,node.right)if isinstance(node,ast.BinOp)else(node.target,node.value)
                if ('complex'in alternatives(facts.expressions.get(unit.ordinal(base)))
                        or set(alternatives(facts.expressions.get(unit.ordinal(exponent))))&{'float','complex'}):return True
        for call in facts.calls.values():
            if BuiltinIdentity('pow')not in call.identity.alternatives:continue
            exponent=call.positional[1]if len(call.positional)>1 else dict(call.keywords).get('exp')
            if exponent is not None and set(exponent.alternatives)&{'float','complex'}:return True
    return False


def frame(emitter,operator,left,right,node,wanted):
    if not isinstance(operator,ast.Pow)or left.kind not in NUMERIC or right.kind!='float':return None
    from .native_classes import Expression
    from .native_float_constructor import frame_value
    emitter.model.float_power_required=True
    first,second,parts=emitter.fresh(),emitter.fresh(),emitter.fresh()
    setup='let '+first+'='+frame_value(emitter,left,node)+';let '+second+'='+right.code+';'
    setup+='let '+parts+'='+emitter.at('native_float_power_parts('+first+','+second+')',node)+';'
    result=kind(node,emitter.model.integer,model=emitter.model,plan=emitter.plan)
    real=emitter.coerce(Expression(parts+'.0','float'),wanted,node)
    if result=='float':return Expression('{'+setup+real+'}',wanted)
    emitter.model.complex_values_required=True
    complex_value='NativeComplex{real:'+parts+'.0,imag:'+parts+'.1}'
    other=emitter.coerce(Expression(complex_value,'complex'),wanted,node)
    return Expression('{'+setup+'if '+parts+'.2{'+other+'}else{'+real+'}'+'}',wanted)


RUNTIME=r'''
fn native_float_power_parts(base:f64,exponent:f64)->Result<(f64,f64,bool),String>{
    let real=|value|(value,0.0_f64,false);
    if exponent==0.0{return Ok(real(1.0));}
    if base.is_nan(){return Ok(real(base));}
    if exponent.is_nan(){return Ok(real(if base==1.0{1.0}else{exponent}));}
    let magnitude=base.abs();
    if exponent.is_infinite(){
        return Ok(real(if magnitude==1.0{1.0}else if(exponent>0.0)==(magnitude>1.0){f64::INFINITY}else{0.0}));
    }
    let odd=exponent.abs()%2.0==1.0;
    if base.is_infinite(){
        return Ok(real(if exponent>0.0{if odd{base}else{magnitude}}else if odd{0.0_f64.copysign(base)}else{0.0}));
    }
    if base==0.0{
        if exponent<0.0{return Err("ZeroDivisionError: zero to a negative power".to_owned());}
        return Ok(real(if odd{base}else{0.0}));
    }
    let complex=base<0.0&&exponent.fract()!=0.0;
    let value=if magnitude==1.0{1.0}else{magnitude.powf(exponent)};
    if value.is_infinite(){
        return Err(if complex{"OverflowError: complex exponentiation"}else{"OverflowError: (34, 'Numerical result out of range')"}.to_owned());
    }
    if value.is_nan(){return Err("ValueError: invalid floating exponentiation".to_owned());}
    if complex{
        let phase=std::f64::consts::PI*exponent;
        return Ok((value*phase.cos(),value*phase.sin(),true));
    }
    Ok(real(if base<0.0&&odd{-value}else{value}))
}
'''
