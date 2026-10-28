"""Resolve standard callables to typed operations, independent of source spelling."""
import ast
from .call_semantics import CallBindingError, normalize_call
from dataclasses import dataclass

from .native import _Expression, _Unsupported


@dataclass(frozen=True)
class ModuleRef:
    name: str
    _native_reference = True


@dataclass(frozen=True)
class BuiltinRef:
    module: str
    name: str
    _native_reference = True


MODULES = {name: ModuleRef(name) for name in ("math", "bisect", "heapq")}
MEMBERS = {
    "math": {name: BuiltinRef("math",name) for name in
             ("gcd","lcm","isqrt","factorial","comb","perm")},
    "bisect": {name: BuiltinRef("bisect",name) for name in
               ("bisect","bisect_left","bisect_right","insort","insort_left","insort_right")},
}

from .native_heapq import NAMES as HEAP_NAMES
MEMBERS["heapq"]={name:BuiltinRef("heapq",name)for name in HEAP_NAMES}


MATH_HELPERS = r'''
fn native_math_abs(value:&Int)->Int {if value.is_negative(){value.exact_neg()}else{value.clone()}}
fn native_math_gcd_pair(a:&Int,b:&Int)->Int {
    let mut a=native_math_abs(a);let mut b=native_math_abs(b);
    while !b.is_zero(){let r=a.exact_divmod(&b).unwrap().1;a=b;b=r;}a
}
fn native_math_gcd(values:&[Int])->Int {
    values.iter().fold(Int::exact_small(0),|g,value|native_math_gcd_pair(&g,value))
}
fn native_math_lcm(values:&[Int])->Int {
    values.iter().fold(Int::exact_small(1),|product,value| {
        if product.is_zero()||value.is_zero(){Int::exact_small(0)}
        else{native_math_abs(&product.exact_divmod(&native_math_gcd_pair(&product,value)).unwrap().0.exact_mul(value))}
    })
}
fn native_math_isqrt(value:&Int)->Result<Int,String> {
    if value.is_negative(){return Err("ValueError: isqrt() argument must be nonnegative".into());}
    if value.is_zero(){return Ok(Int::exact_small(0));}
    let two=Int::exact_small(2);
    let mut guess=Int::exact_small(1).shl(&Int::exact_small(((value.bit_length()+1)/2)as i128))?;
    loop {
        let next=guess.exact_add(&value.exact_divmod(&guess)?.0).exact_divmod(&two)?.0;
        if next>=guess{return Ok(guess);}guess=next;
    }
}
fn native_math_factorial(n:&Int)->Result<Int,String> {
    if n.is_negative(){return Err("ValueError: factorial() not defined for negative values".into());}
    let count=n.to_i128().and_then(|n|isize::try_from(n).ok())
        .ok_or_else(||format!("OverflowError: factorial() argument should not exceed {}",isize::MAX))?;
    let mut result=Int::exact_small(1);
    for factor in 2..=count {result=result.exact_mul(&Int::exact_small(factor as i128));}Ok(result)
}
fn native_math_comb(n:&Int,k:&Int)->Result<Int,String> {
    if n.is_negative(){return Err("ValueError: n must be a non-negative integer".into());}
    if k.is_negative(){return Err("ValueError: k must be a non-negative integer".into());}
    if k>n{return Ok(Int::exact_small(0));}
    let other=n.exact_add(&k.exact_neg());let k=if k<&other{k}else{&other};
    let count=k.to_i128().and_then(|value|isize::try_from(value).ok())
        .ok_or_else(||format!("OverflowError: min(n - k, k) must not exceed {}",isize::MAX))? as usize;
    let base=n.exact_add(&k.exact_neg());let mut result=Int::exact_small(1);
    for i in 1..=count {
        let i=Int::exact_small(i as i128);
        result=result.exact_mul(&base.exact_add(&i)).exact_divmod(&i)?.0;
    }Ok(result)
}
fn native_math_perm(n:&Int,k:Option<&Int>)->Result<Int,String> {
    let k=match k{Some(value)=>value,None=>return native_math_factorial(n)};
    if n.is_negative(){return Err("ValueError: n must be a non-negative integer".into());}
    if k.is_negative(){return Err("ValueError: k must be a non-negative integer".into());}
    if k>n{return Ok(Int::exact_small(0));}
    let count=k.to_i128().and_then(|value|isize::try_from(value).ok())
        .ok_or_else(||format!("OverflowError: k must not exceed {}",isize::MAX))? as usize;
    let mut result=Int::exact_small(1);
    for i in 0..count {result=result.exact_mul(&n.exact_add(&Int::exact_small(-(i as i128))));}Ok(result)
}
'''

from .native_heapq import HELPERS as HEAP_HELPERS
HELPERS = MATH_HELPERS + HEAP_HELPERS


def helpers(generator):
    from .native_bisect import helpers as bisection_helpers
    from .native_math_calls import helpers as math_helpers
    integer='bigint'if not generator.bits else'i'+str(generator.bits)
    return math_helpers(integer)+HEAP_HELPERS+bisection_helpers(generator.bits)


def reference(node,environment):
    from .references import resolve_static_callable
    value=resolve_static_callable(node,environment,core_builtins=())
    return value if isinstance(value,(ModuleRef,BuiltinRef))else None


def _read_reference(g,node,environment):
    while isinstance(node,ast.Attribute):node=node.value
    if (g.function is not None and isinstance(node,ast.Name)
            and node.id not in g.function.local_names and reference(node,environment) is not None):
        g.function.required.add(node.id)


def try_statement(g,node,environment):
    from .native_stdio import SYS
    if isinstance(node,ast.Import):
        if not all(alias.name in MODULES or alias.name=="sys"for alias in node.names):return None
        values=[(alias.asname or alias.name,SYS if alias.name=="sys"else MODULES[alias.name])for alias in node.names]
    elif isinstance(node,ast.ImportFrom) and node.module in MODULES and not node.level:
        if not all(alias.name in MEMBERS[node.module] for alias in node.names):raise _Unsupported
        values=[(alias.asname or alias.name,MEMBERS[node.module][alias.name]) for alias in node.names]
    elif isinstance(node,ast.Assign):
        value=reference(node.value,environment)
        if value is None:return None
        if not all(isinstance(target,ast.Name) for target in node.targets):raise _Unsupported
        _read_reference(g,node.value,environment)
        values=[(target.id,value) for target in node.targets]
    elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(reference(node.value.func,environment),BuiltinRef):
        value=try_expression(g,node.value,environment)
        return f"let _={value.code};",environment
    else:return None
    for name,value in values:
        module="sys"if value is SYS else value.name if isinstance(value,ModuleRef) else value.module
        if module not in g.trusted_imports or name in g.BUILTINS|{"__name__","__builtins__"}:raise _Unsupported
        environment[name]=value
    return "",environment


def try_expression(g,node,environment):
    if not isinstance(node,ast.Call):return None
    function=reference(node.func,environment)
    if not isinstance(function,BuiltinRef):return None
    _read_reference(g,node.func,environment)
    if function.module=="heapq":
        from .native_heapq import lower
        return lower(g,node,environment,function)
    if function.module=="bisect":
        from .native_bisect import lower
        return lower(g,node,environment,function)
    if function.module=="math":
        from .native_math_calls import emit
        try:arguments=normalize_call(node)
        except CallBindingError:raise _Unsupported from None
        lines=[];positional=[];keywords={}
        for argument in arguments.evaluation_order:
            value=g.expression(argument.expression,environment)
            name=g.temporary();lines.append(f"let {name}={value.code};")
            captured=_Expression(name,value.kind,value.constant)
            if argument.name is None:positional.append(captured)
            else:keywords[argument.name]=captured
        result=emit(g,node,function,positional,keywords)
        return _Expression("{"+"".join(lines)+result.code+"}",result.kind)
    raise _Unsupported('this standard callable has no registered native lowering',node=node)
