"""Resolve standard callables to typed operations, independent of source spelling."""
import ast
from dataclasses import dataclass

from .native import _Binding, _Expression, _ListInfo, _Unsupported


@dataclass(frozen=True)
class ModuleRef:
    name: str
    _native_reference = True


@dataclass(frozen=True)
class BuiltinRef:
    module: str
    name: str
    _native_reference = True


MODULES = {name: ModuleRef(name) for name in ("math", "bisect")}
MEMBERS = {
    "math": {name: BuiltinRef("math",name) for name in
             ("gcd","lcm","isqrt","factorial","comb","perm")},
    "bisect": {name: BuiltinRef("bisect",name) for name in
               ("bisect","bisect_left","bisect_right","insort","insort_left","insort_right")},
}


HELPERS = r'''
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
        .ok_or_else(||"OverflowError: factorial() argument is too large".to_owned())?;
    let mut result=Int::exact_small(1);
    for factor in 2..=count {result=result.exact_mul(&Int::exact_small(factor as i128));}Ok(result)
}
fn native_math_comb(n:&Int,k:&Int)->Result<Int,String> {
    if n.is_negative()||k.is_negative(){return Err("ValueError: n and k must be non-negative integers".into());}
    if k>n{return Ok(Int::exact_small(0));}
    let other=n.exact_add(&k.exact_neg());let k=if k<&other{k}else{&other};
    let count=k.to_usize().ok_or_else(||"OverflowError: number of terms is too large".to_owned())?;
    let base=n.exact_add(&k.exact_neg());let mut result=Int::exact_small(1);
    for i in 1..=count {
        let i=Int::exact_small(i as i128);
        result=result.exact_mul(&base.exact_add(&i)).exact_divmod(&i)?.0;
    }Ok(result)
}
fn native_math_perm(n:&Int,k:Option<&Int>)->Result<Int,String> {
    let k=k.unwrap_or(n);
    if n.is_negative()||k.is_negative(){return Err("ValueError: n and k must be non-negative integers".into());}
    if k>n{return Ok(Int::exact_small(0));}
    let count=k.to_usize().ok_or_else(||"OverflowError: number of terms is too large".to_owned())?;
    let mut result=Int::exact_small(1);
    for i in 0..count {result=result.exact_mul(&n.exact_add(&Int::exact_small(-(i as i128))));}Ok(result)
}
fn native_bisect_bound(value:Option<&Int>,default:isize)->Result<isize,String> {
    match value {
        None=>Ok(default),Some(value)=>value.to_i128().and_then(|n|isize::try_from(n).ok())
            .ok_or_else(||"OverflowError: Python int too large to convert to C ssize_t".to_owned()),
    }
}
fn native_bisect<T:Ord>(values:&[T],x:&T,lo:Option<&Int>,hi:Option<&Int>,right:bool)->Result<usize,String> {
    let mut lo=native_bisect_bound(lo,0)?;
    let mut hi=native_bisect_bound(hi,-1)?;
    if lo<0{return Err("ValueError: lo must be non-negative".into());}
    if hi== -1 {hi=isize::try_from(values.len()).map_err(|_|"OverflowError: sequence is too large".to_owned())?;}
    while lo<hi {
        let mid=lo+((hi-lo)/2);
        let value=values.get(mid as usize).ok_or_else(||"IndexError: list index out of range".to_owned())?;
        if if right{x>=value}else{value<x}{lo=mid+1;}else{hi=mid;}
    }Ok(lo as usize)
}
fn native_insort<T:Ord>(values:&mut Vec<T>,x:T,lo:Option<&Int>,hi:Option<&Int>,right:bool)->Result<(),String> {
    let index=native_bisect(values,&x,lo,hi,right)?.min(values.len());
    values.try_reserve(1).map_err(|_|"MemoryError".to_owned())?;
    values.insert(index,x);Ok(())
}
'''


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
    if isinstance(node,ast.Import):
        if not all(alias.name in MODULES for alias in node.names):return None
        values=[(alias.asname or alias.name,MODULES[alias.name]) for alias in node.names]
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
        module=value.name if isinstance(value,ModuleRef) else value.module
        if module not in g.trusted_imports or name in g.BUILTINS|{"__name__","__builtins__"}:raise _Unsupported
        environment[name]=value
    return "",environment


def _exact(g,value):
    code=g.number(value)
    return code if not g.bits else f"Int::from_i128(({code})as i128)"


def _result(g,code):
    return code if not g.bits else f"({code}).normalized().to_i128().unwrap()as NativeInt"


def _bind(g,node,environment,parameters,*,minimum,defaults=(),kwonly=()):
    if len(node.args)>len(parameters) or any(isinstance(arg,ast.Starred) for arg in node.args):raise _Unsupported
    bound={};lines=[]
    def save(name,value):
        if name in bound:raise _Unsupported
        if isinstance(value,ast.Constant) and value.value is None:
            if name not in {"hi","k"}:raise _Unsupported
            bound[name]=None
            return
        result=g.expression(value,environment)
        temporary=g.temporary()
        lines.append(f"let {temporary}={_exact(g,result)};")
        bound[name]=temporary
    for name,value in zip(parameters,node.args):save(name,value)
    for keyword in node.keywords:
        if keyword.arg not in (*parameters,*kwonly):raise _Unsupported
        if keyword.arg=="key":
            if not(isinstance(keyword.value,ast.Constant)and keyword.value.value is None):raise _Unsupported
            if "key" in bound:raise _Unsupported
            bound["key"]=None
        else:save(keyword.arg,keyword.value)
    if any(name not in bound for name in parameters[:minimum]):raise _Unsupported
    for name in defaults:bound.setdefault(name,None)
    return lines,bound


def try_expression(g,node,environment):
    if not isinstance(node,ast.Call):return None
    function=reference(node.func,environment)
    if not isinstance(function,BuiltinRef):return None
    _read_reference(g,node.func,environment)
    g.has_native_modules=True
    g.needs_integer_runtime=True
    name=function.name
    if function.module=="math":
        if node.keywords:raise _Unsupported
        if name in {"gcd","lcm"}:
            if node.keywords or any(isinstance(arg,ast.Starred)for arg in node.args):raise _Unsupported
            values=[g.expression(arg,environment)for arg in node.args]
            names=[g.temporary()for _ in values]
            lines=[f"let {name}={_exact(g,value)};"for name,value in zip(names,values)]
            code=f"native_math_{name}(&[{','.join(names)}])"
        else:
            params=("n","k")if name in {"comb","perm"}else("n",)
            minimum=2 if name=="comb"else 1
            lines,args=_bind(g,node,environment,params,minimum=minimum,defaults=("k",)if name=="perm"else())
            if args.get("n") is None or name=="comb"and args.get("k") is None:raise _Unsupported
            values=[f"&{args['n']}"]
            if name=="comb":values.append(f"&{args['k']}")
            elif name=="perm":values.append("None"if args["k"]is None else f"Some(&{args['k']})")
            code=g.at(f"native_math_{name}({','.join(values)})",node)
        return _Expression("{ "+" ".join(lines)+f" {_result(g,code)} }}","int")
    if not 2<=len(node.args)<=4:raise _Unsupported
    array_node=node.args[0]
    array=g.expression(array_node,environment)
    if array.kind!="list_int":raise _Unsupported
    owner=g.temporary()
    mutating=name.startswith("insort")
    if mutating:
        if (not isinstance(array_node,ast.Name) or array_node.id in g.iterating_lists
                or array.code in g.borrowed_slots):raise _Unsupported
        lines=[]
    else:
        lines=[f"let {owner}:&[NativeInt]=&({array.code});"]
    value=g.expression(node.args[1],environment);item=g.temporary()
    lines.append(f"let {item}={g.number(value)};")
    bounds_call=ast.copy_location(ast.Call(func=node.func,args=node.args[2:],keywords=node.keywords),node)
    bound_lines,bounds=_bind(g,bounds_call,environment,("lo","hi"),minimum=0,defaults=("lo","hi"),kwonly=("key",))
    lines+=bound_lines
    args=["None"if bounds[name]is None else f"Some(&{bounds[name]})"for name in ("lo","hi")]
    right=str(not name.endswith("_left")).lower()
    if mutating:
        code=g.at(f"native_insort(&mut {array.code},{item},{','.join(args)},{right})",node)
        g.update_info(environment,array_node.id,_ListInfo(None))
        kind="none"
    else:
        code=g.at(f"native_bisect({owner},&{item},{','.join(args)},{right})",node)
        code=f"({code})as NativeInt"if g.bits else f"Int::from_i128(({code})as i128)"
        kind="int"
    return _Expression("{ "+" ".join(lines)+f" {code} }}",kind)
