"""Immutable binary64 complex leaves; numeric arithmetic remains explicit."""

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
