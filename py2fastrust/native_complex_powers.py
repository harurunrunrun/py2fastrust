"""Typed complex powers and closed builtin ternary-power slot ordering.

The arithmetic is implemented from complex multiplication, reciprocal and
polar identities; CPython 3.14 supplies the observable dispatch/error contract.
"""
import ast

NUMERIC=frozenset({'int','bool','int_bool','float','complex'})


def dispatch(tags):
    """Choose the first supported sealed power slot, with original operands."""
    for tag in tags:
        if tag=='float'and tags[2]!='none':return 'float_mod'
        if tag=='complex'and set(tags[:2])<=NUMERIC:return 'complex'
    return None


def convert(emitter,value,node):
    from .native_float_constructor import frame_value
    if value.kind=='complex':return value.code
    real=emitter.scalar(value).code if value.kind=='float'else frame_value(emitter,value,node)
    return 'NativeComplex{real:'+real+',imag:0.0}'


def frame(emitter,operator,left,right,node,wanted):
    if not isinstance(operator,ast.Pow)or 'complex'not in {left.kind,right.kind}:return None
    if not {left.kind,right.kind}<=NUMERIC:return None
    from .native_classes import Expression
    first,second=emitter.fresh(),emitter.fresh()
    setup='let '+first+'='+convert(emitter,left,node)+';let '+second+'='+convert(emitter,right,node)+';'
    emitter.model.complex_values_required=True
    emitter.model.complex_power_required=True
    value=Expression(emitter.at('native_complex_power('+first+','+second+')',node),'complex')
    return Expression('{'+setup+emitter.coerce(value,wanted,node)+'}',wanted)


def ordering(emitter,operator,left,right,node):
    if not isinstance(operator,(ast.Lt,ast.LtE,ast.Gt,ast.GtE))or 'complex'not in {left.kind,right.kind}:return None
    from .native_classes import domain
    from .native_class_builtins import _type_name
    from .native import _string
    # Source callbacks have already been offered the operation. Do not turn
    # an unrepresented user protocol into a guessed builtin error.
    closed=NUMERIC|{'none','str','bytes','list','tuple','tuple_sequence','dict','set','frozenset','range','function','globals_dict'}
    if any(domain(value.kind)not in closed for value in(left,right)):return None
    symbol={ast.Lt:'<',ast.LtE:'<=',ast.Gt:'>',ast.GtE:'>='}[type(operator)]
    message='format!('+_string("TypeError: '"+symbol+"' not supported between instances of '{}' and '{}'")+','+_type_name(emitter,left,node)+','+_type_name(emitter,right,node)+')'
    return emitter.at('Err::<bool,String>('+message+')',node)


def runtime(model):
    return RUNTIME if getattr(model,'complex_power_required',False)else ''


RUNTIME=r'''
fn native_complex_product(left:NativeComplex,right:NativeComplex)->NativeComplex{
 let mut a=[left.real,left.imag];let mut b=[right.real,right.imag];
 let products=[a[0]*b[0],a[1]*b[1],a[0]*b[1],a[1]*b[0]];
 let mut result=NativeComplex{real:products[0]-products[1],imag:products[2]+products[3]};
 if result.real.is_nan()&&result.imag.is_nan(){
  let mut restore=false;
  if a.iter().any(|value|value.is_infinite()){
   for value in a.iter_mut(){*value=(if value.is_infinite(){1.0_f64}else{0.0}).copysign(*value);}
   for value in b.iter_mut(){if value.is_nan(){*value=0.0_f64.copysign(*value);}}restore=true;
  }
  if b.iter().any(|value|value.is_infinite()){
   for value in b.iter_mut(){*value=(if value.is_infinite(){1.0_f64}else{0.0}).copysign(*value);}
   for value in a.iter_mut(){if value.is_nan(){*value=0.0_f64.copysign(*value);}}restore=true;
  }
  if !restore&&products.iter().any(|value|value.is_infinite()){
   for value in a.iter_mut().chain(b.iter_mut()){if value.is_nan(){*value=0.0_f64.copysign(*value);}}restore=true;
  }
  if restore{result=NativeComplex{real:f64::INFINITY*(a[0]*b[0]-a[1]*b[1]),imag:f64::INFINITY*(a[0]*b[1]+a[1]*b[0])};}
 }result
}
fn native_complex_reciprocal(value:NativeComplex)->Result<NativeComplex,String>{
 let a=value.real;let b=value.imag;
 if a==0.0&&b==0.0{return Err("ZeroDivisionError: zero to a negative or complex power".to_owned());}
 let mut result=if a.abs()>=b.abs(){let ratio=b/a;let divisor=a+b*ratio;NativeComplex{real:(1.0+0.0*ratio)/divisor,imag:(0.0-ratio)/divisor}}
 else if b.abs()>=a.abs(){let ratio=a/b;let divisor=a*ratio+b;NativeComplex{real:(ratio+0.0)/divisor,imag:(0.0*ratio-1.0)/divisor}}
 else{NativeComplex{real:f64::NAN,imag:f64::NAN}};
 if result.real.is_nan()&&result.imag.is_nan()&&(a.is_infinite()||b.is_infinite()){
  let x=(if a.is_infinite(){1.0_f64}else{0.0}).copysign(a);let y=(if b.is_infinite(){1.0_f64}else{0.0}).copysign(b);
  result=NativeComplex{real:0.0*(x+0.0*y),imag:0.0*(0.0*x-y)};
 }Ok(result)
}
fn native_complex_power(base:NativeComplex,exponent:NativeComplex)->Result<NativeComplex,String>{
 let integer=exponent.imag==0.0&&exponent.real.fract()==0.0&&exponent.real.abs()<=100.0;
 let result=if integer{
  let mut count=exponent.real.abs()as u32;let mut factor=base;let mut output=NativeComplex{real:1.0,imag:0.0};
  while count!=0{if count&1!=0{output=native_complex_product(output,factor);}factor=native_complex_product(factor,factor);count>>=1;}
  if exponent.real>0.0{output}else{native_complex_reciprocal(output)?}
 }else if exponent.real==0.0&&exponent.imag==0.0{NativeComplex{real:1.0,imag:0.0}}
 else if base.real==0.0&&base.imag==0.0{
  if exponent.imag!=0.0||exponent.real<0.0{return Err("ZeroDivisionError: zero to a negative or complex power".to_owned());}
  NativeComplex{real:0.0,imag:0.0}
 }else{
  let magnitude=base.real.hypot(base.imag);let angle=base.imag.atan2(base.real);
  let mut radius=magnitude.powf(exponent.real);let mut phase=angle*exponent.real;
  if exponent.imag!=0.0{radius*=(-angle*exponent.imag).exp();phase+=exponent.imag*magnitude.ln();}
  if phase.is_infinite(){return Err("ZeroDivisionError: zero to a negative or complex power".to_owned());}
  NativeComplex{real:radius*phase.cos(),imag:radius*phase.sin()}
 };
 if result.real.is_infinite()||result.imag.is_infinite(){return Err("OverflowError: complex exponentiation".to_owned());}
 Ok(result)
}
'''
