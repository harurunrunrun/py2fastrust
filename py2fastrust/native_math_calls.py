"""Shared mathematical operations over already captured native arguments."""
from .native import _Expression, _Unsupported, _string
from .native_types import TupleType, TupleSequenceType, list_type, alternatives
from .native_unions import project, union_kind


INTEGER_NAMES=frozenset({'gcd','lcm','isqrt','factorial','comb','perm'})
REAL_NAMES=frozenset({'sqrt','floor','ceil','trunc'})
NAMES=INTEGER_NAMES|REAL_NAMES

def result_kind(identity):return 'float'if identity.name=='sqrt'else'int'

def requires_frames(analysis,integer):
    if integer!='bigint':return False
    for scope in analysis.scopes.values():
        for fact in scope.calls.values():
            if not any(accepts(identity)and identity.name in REAL_NAMES for identity in fact.identity.alternatives):continue
            if any(accepts(identity)and identity.name=='sqrt'for identity in fact.identity.alternatives):return True
            if any(value.unknown or value.unbound or 'float'in value.alternatives for value in fact.positional):return True
    return False


def accepts(identity):
    from .native_module_calls import BuiltinRef
    return isinstance(identity, BuiltinRef) and identity.module == 'math' and identity.name in NAMES


def binding_error(name, arguments, keywords):
    if keywords:
        return f'TypeError: math.{name}() takes no keyword arguments'
    count = len(arguments)
    if name in {'isqrt','factorial'}|REAL_NAMES and count != 1:
        return f'TypeError: math.{name}() takes exactly one argument ({count} given)'
    if name == 'comb' and count != 2:
        return f'TypeError: comb expected 2 arguments, got {count}'
    if name == 'perm':
        if count < 1:
            return f'TypeError: perm expected at least 1 argument, got {count}'
        if count > 2:
            return f'TypeError: perm expected at most 2 arguments, got {count}'
    return None


def _index_kind(kind):
    return (kind in {'int', 'bool', 'int_bool', 'none', 'float', 'str', 'bytes'}
            or list_type(kind) or isinstance(kind, (TupleType, TupleSequenceType)))


def analyze(model, plan, node, identity, captured_arg_cells, kw_pairs, environment):
    if not accepts(identity):
        return None
    from .native_classes import shape, ClassUnsupported
    if binding_error(identity.name, captured_arg_cells, kw_pairs) is None:
        for index, value in enumerate(captured_arg_cells):
            kind = shape(value)
            if kind is None and not model.final:
                continue
            if identity.name in REAL_NAMES:
                if not all(_real_kind(choice)for choice in alternatives(kind)):
                    protocols={'sqrt':'__float__/__index__','floor':'__floor__/__float__/__index__','ceil':'__ceil__/__float__/__index__','trunc':'__trunc__'}[identity.name]
                    raise ClassUnsupported(node,'math.'+identity.name+' needs its user '+protocols+' conversion protocol; the native adapter accepts captured builtin numbers and reports errors for closed builtin nonnumbers',types=((f'argument {index+1}',kind),),proof='canonical math real-number protocol')
            elif not all(_index_kind(choice) for choice in alternatives(kind)):
                raise ClassUnsupported(node, 'this math argument needs the Python __index__ protocol; '
                                       'its native protocol adapter is not implemented',
                                       types=((f'argument {index + 1}', kind),),
                                       proof='canonical integer-index protocol')
    model.native_math_functions = getattr(model, 'native_math_functions', set()) | {identity.name}
    return model.cell(plan,node,result_kind(identity))


def _bits(generator):
    if hasattr(generator, 'bits'):
        return generator.bits
    return {'i64': 64, 'i128': 128, 'bigint': 0}[generator.model.integer]


def _temporary(generator):
    return generator.temporary() if hasattr(generator, 'temporary') else generator.fresh()


def _index(generator, value, node):
    if union_kind(value.kind):
        return project(value.kind, value.code,
                       lambda kind, code: _index(generator, _Expression(code, kind, owned=False), node))
    if value.kind in {'int', 'bool', 'int_bool'}:
        return generator.number(value)
    if not _index_kind(value.kind):
        raise _Unsupported('this math argument needs an unimplemented __index__ protocol adapter',
                           node=node, types=(('argument', value.kind),),
                           proof='canonical integer-index protocol')
    from .native_comparisons import _type_name
    message = _string("TypeError: '{}' object cannot be interpreted as an integer")
    error = f'Err::<NativeInt,String>(format!({message},{_type_name(value)}))'
    return generator.at(error, node)


def _real_kind(kind):
    from .native_classes import domain
    return domain(kind)in {'int','bool','int_bool','float','none','str','bytes','list','tuple','tuple_sequence','range','dict','set','dict_view','function','deque','globals_dict'}


def _real(generator,value,node,name):
    if union_kind(value.kind):
        return project(value.kind,value.code,lambda kind,code:_real(generator,_Expression('('+code+').clone()',kind),node,name))
    if value.kind in {'int','bool','int_bool'}:
        integer=generator.number(value)
        if name!='sqrt':return integer
        if _bits(generator):return '('+integer+') as f64'
        return generator.at('('+integer+').ratio(&Int::exact_small(1)).map_err(|_|"OverflowError: int too large to convert to float".to_owned())',node)
    if value.kind=='float':
        if name=='sqrt':return value.code
        conversion='native_float_integer'if _bits(generator)else'Int::from_f64'
        return generator.at(conversion+'(('+value.code+').'+name+'())',node)
    if not _real_kind(value.kind):
        raise _Unsupported('math.'+name+' needs its user conversion protocol; only builtin numeric values have a proved direct representation',node=node,types=(('argument',value.kind),),proof='canonical math real-number protocol')
    if hasattr(generator,'model'):
        from .native_class_builtins import _type_name
        typename=_type_name(generator,value,node)
    else:
        from .native_comparisons import _type_name
        typename=_type_name(value)
    message=("TypeError: type {} doesn't define __trunc__ method"if name=='trunc'else'TypeError: must be real number, not {}')
    result='f64'if name=='sqrt'else'NativeInt'
    return generator.at('Err::<'+result+',String>(format!('+_string(message)+','+typename+'))',node)


def emit(generator, node, identity, captured_arg_Expressions, kw_map, wanted=None):
    """Do not evaluate a callee or source argument: the caller captured them."""
    if not accepts(identity):
        return None
    owner = getattr(generator, 'model', generator)
    owner.native_math_functions = getattr(owner, 'native_math_functions', set()) | {identity.name}
    if owner is generator:
        generator.has_native_modules = True
    raw_kind=result_kind(identity)
    if wanted is None:wanted=raw_kind
    if identity.name in REAL_NAMES and not hasattr(generator,'model'):generator.has_extended_scalars=True
    error = binding_error(identity.name, captured_arg_Expressions, kw_map)
    if error is not None:
        result='f64'if raw_kind=='float'else'NativeInt'
        code=generator.at(f'Err::<{result},String>({_string(error)}.into())',node)
    elif identity.name in REAL_NAMES:
        value=_real(generator,captured_arg_Expressions[0],node,identity.name)
        code=generator.at('native_math_sqrt('+value+')',node)if identity.name=='sqrt'else value
    else:
        names, lines = [], []
        for index, value in enumerate(captured_arg_Expressions):
            if identity.name == 'perm' and index == 1 and value.kind == 'none':
                names.append(None)
                continue
            name = _temporary(generator)
            lines.append(f'let {name}={_index(generator, value, node)};')
            names.append(name)
        name = identity.name
        if name in {'gcd', 'lcm'}:
            code = f'native_math_{name}(&[{",".join(names)}])'
        else:
            arguments = ['&' + names[0]] if not _bits(generator) else [names[0]]
            if name == 'comb':
                arguments.append('&' + names[1] if not _bits(generator) else names[1])
            elif name == 'perm':
                optional = names[1] if len(names) > 1 else None
                arguments.append('None' if optional is None else
                                 'Some(' + ('&' if not _bits(generator) else '') + optional + ')')
            code = generator.at(f'native_math_{name}({",".join(arguments)})', node)
        code = '{' + ''.join(lines) + code + '}'
    result=_Expression(code,raw_kind)
    if wanted!=raw_kind:
        result = _Expression(generator.coerce(result, wanted, node), wanted)
    return result


_FIXED = r'''
fn native_math_unsigned_gcd(mut left:MathUnsigned,mut right:MathUnsigned)->MathUnsigned {
    while right!=0 {let remainder=left%right;left=right;right=remainder;}left
}
fn native_math_gcd(values:&[NativeInt])->NativeInt {
    let mut result:MathUnsigned=0;
    for value in values {result=native_math_unsigned_gcd(result,value.unsigned_abs());}
    result as NativeInt
}
fn native_math_lcm(values:&[NativeInt])->NativeInt {
    if values.len()<=2 {
        let mut result:MathUnsigned=1;
        for value in values {
            let value=value.unsigned_abs();
            if value==0{return 0;}
            result=(result/native_math_unsigned_gcd(result,value)).wrapping_mul(value);
        }
        return result as NativeInt;
    }
    let mut factors:Vec<MathUnsigned>=Vec::with_capacity(values.len());
    let mut result:MathUnsigned=1;
    for value in values {
        let mut remaining=value.unsigned_abs();
        if remaining==0{return 0;}
        for &factor in &factors {
            remaining/=native_math_unsigned_gcd(remaining,factor);
            if remaining==1{break;}
        }
        if remaining>1 {factors.push(remaining);result=result.wrapping_mul(remaining);}
    }
    result as NativeInt
}
fn native_math_isqrt(value:NativeInt)->Result<NativeInt,String> {
    if value<0{return Err("ValueError: isqrt() argument must be nonnegative".into());}
    let value=value as MathUnsigned;
    if value==0{return Ok(0);}
    let shift=(MathUnsigned::BITS-value.leading_zeros()+1)/2;
    let mut guess=(1 as MathUnsigned)<<shift;
    loop {
        let next=(guess+value/guess)/2;
        if next>=guess{return Ok(guess as NativeInt);}
        guess=next;
    }
}
fn native_math_factorial(value:NativeInt)->Result<NativeInt,String> {
    if value<0{return Err("ValueError: factorial() not defined for negative values".into());}
    if (value as MathUnsigned)>(isize::MAX as MathUnsigned) {
        return Err(format!("OverflowError: factorial() argument should not exceed {}",isize::MAX));
    }
    let count=value as MathUnsigned;
    if count-(count.count_ones()as MathUnsigned)>=NativeInt::BITS as MathUnsigned{return Ok(0);}
    let mut result:NativeInt=1;let mut factor:MathUnsigned=2;
    while factor<=count {result=result.wrapping_mul(factor as NativeInt);factor+=1;}
    Ok(result)
}
fn native_math_perm(n:NativeInt,k:Option<NativeInt>)->Result<NativeInt,String> {
    let k=match k{Some(value)=>value,None=>return native_math_factorial(n)};
    if n<0{return Err("ValueError: n must be a non-negative integer".into());}
    if k<0{return Err("ValueError: k must be a non-negative integer".into());}
    if k>n{return Ok(0);}
    if (k as MathUnsigned)>(isize::MAX as MathUnsigned){return Err(format!("OverflowError: k must not exceed {}",isize::MAX));}
    let n=n as MathUnsigned;let count=k as MathUnsigned;let mut index:MathUnsigned=0;
    let mut result:NativeInt=1;
    while index<count {
        result=result.wrapping_mul((n-index)as NativeInt);
        if result==0{return Ok(0);}
        index+=1;
    }
    Ok(result)
}
fn native_math_comb(n:NativeInt,k:NativeInt)->Result<NativeInt,String> {
    if n<0{return Err("ValueError: n must be a non-negative integer".into());}
    if k<0{return Err("ValueError: k must be a non-negative integer".into());}
    if k>n{return Ok(0);}
    let k=k.min(n-k)as MathUnsigned;
    if k>(isize::MAX as MathUnsigned){return Err(format!("OverflowError: min(n - k, k) must not exceed {}",isize::MAX));}
    let base=(n as MathUnsigned)-k;
    let mut numerator:MathUnsigned=1;let mut denominator:MathUnsigned=1;
    let mut twos:i32=0;let mut index:MathUnsigned=1;
    while index<=k {
        let top=base+index;let bottom=index;
        let top_twos=top.trailing_zeros();let bottom_twos=bottom.trailing_zeros();
        twos+=top_twos as i32-bottom_twos as i32;
        numerator=numerator.wrapping_mul(top>>top_twos);
        denominator=denominator.wrapping_mul(bottom>>bottom_twos);
        index+=1;
    }
    let mut inverse:MathUnsigned=1;let mut precision=1;
    while precision<MathUnsigned::BITS {
        inverse=inverse.wrapping_mul((2 as MathUnsigned).wrapping_sub(denominator.wrapping_mul(inverse)));
        precision*=2;
    }
    Ok(if twos as u32>=NativeInt::BITS{0}else{numerator.wrapping_mul(inverse).wrapping_shl(twos as u32)as NativeInt})
}
'''


def helpers(integer, names=NAMES):
    if not set(names)&NAMES:return ''
    pieces=[]
    if set(names)&INTEGER_NAMES:
        if integer=='bigint':
            from .native_module_calls import MATH_HELPERS
            pieces.append(MATH_HELPERS)
        else:
            bits={'i64':64,'i128':128}[integer]
            pieces.append(f'type MathUnsigned=u{bits};\n'+_FIXED)
    if 'sqrt'in names:
        pieces.append('fn native_math_sqrt(value:f64)->Result<f64,String>{if value<0.0{Err(format!("ValueError: expected a nonnegative input, got {}",native_float_text(value)))}else{Ok(value.sqrt())}}')
    return '\n'.join(pieces)
