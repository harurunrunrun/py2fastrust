"""Immutable binary64 complex leaves and ordered additive conversions."""
import ast


def additive(emitter,operator,left,right,node,wanted):
    if not isinstance(operator,(ast.Add,ast.Sub))or 'complex'not in{left.kind,right.kind}:return None
    numeric={'int','bool','int_bool','float','complex'}
    if left.kind not in numeric or right.kind not in numeric:return None
    from .native_classes import Expression
    from .native_float_constructor import frame_value
    emitter.model.complex_values_required=True
    def convert(value):
        if value.kind=='complex':return value
        code=emitter.scalar(value).code if value.kind=='float'else frame_value(emitter,value,node)
        return Expression(code,'float')
    before,first=emitter.capture(convert(left));more,second=emitter.capture(convert(right))
    symbol='+'if isinstance(operator,ast.Add)else'-'
    real=lambda value:value.code+'.real'if value.kind=='complex'else value.code
    if first.kind==second.kind=='complex':imag=first.code+'.imag'+symbol+second.code+'.imag'
    elif first.kind=='complex':imag=first.code+'.imag'
    else:imag=('-'if isinstance(operator,ast.Sub)else'')+second.code+'.imag'
    value=Expression('NativeComplex{real:'+real(first)+symbol+real(second)+',imag:'+imag+'}','complex')
    return Expression('{'+before+more+emitter.coerce(value,wanted,node)+'}',wanted)

RUNTIME=r'''
#[derive(Clone,Copy,Debug)]
struct NativeComplex{real:f64,imag:f64}
impl NativeComplex{
    fn is_true(&self)->bool{self.real!=0.0||self.imag!=0.0}
}
fn native_complex_component(value:f64)->String{
    let mut text=native_float_text(value);
    if text.ends_with(".0"){text.truncate(text.len()-2);}
    text
}
fn native_complex_text(value:&NativeComplex)->String{
    if value.real==0.0&&!value.real.is_sign_negative(){return format!("{}j",native_complex_component(value.imag));}
    let negative=value.imag.is_sign_negative()&&!value.imag.is_nan();
    format!("({}{}{}j)",native_complex_component(value.real),if negative{"-"}else{"+"},native_complex_component(value.imag.abs()))
}
'''
