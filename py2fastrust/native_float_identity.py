"""Demanded float-object identity for typed builtin container comparisons."""
import ast
import dis
import math
from .native_types import ListType,TupleType,TupleSequenceType,NullableType,MaybeType,UnionType,alternatives

NUMERIC=frozenset({'int','bool','int_bool','float'})


def floating(kind):
    if kind=='float':return True
    if isinstance(kind,(NullableType,MaybeType)):return floating(kind.value)
    if isinstance(kind,UnionType):return any(floating(child)for child in kind.alternatives)
    if isinstance(kind,TupleType):return any(floating(child)for child in kind.fields)
    if isinstance(kind,(ListType,TupleSequenceType)):return floating(kind.element)
    return False


def container(kind):
    return any(isinstance(child,(ListType,TupleType,TupleSequenceType))and floating(child)for child in alternatives(kind))


def require(model,plan,node,role,*values):
    demands=getattr(model,'native_float_identity_demands',None)
    if demands is None:demands=model.native_float_identity_demands={}
    demands[plan.index,id(node),role]=values


def comparison_demand(left,right,operator):
    if isinstance(operator,(ast.Is,ast.IsNot)):return False
    if isinstance(operator,(ast.In,ast.NotIn)):return container(right)
    for a in alternatives(left):
        for b in alternatives(right):
            same=isinstance(a,ListType)and isinstance(b,ListType)or isinstance(a,(TupleType,TupleSequenceType))and isinstance(b,(TupleType,TupleSequenceType))
            if same and(floating(a)or floating(b)):return True
    return False


def prepare(model):
    from .native_classes import shape
    active=False
    for(_,_,role),values in getattr(model,'native_float_identity_demands',{}).items():
        if isinstance(role,tuple)and role[0]=='comparison':
            active|=comparison_demand(shape(values[0]),shape(values[1]),role[1]())
        else:active|=any(container(shape(value))for value in values)
    active|=any(floating(shape(record.key))for record in model.mappings.records)
    model.native_float_identity_enabled=active


def enabled(model):return getattr(model,'native_float_identity_enabled',False)


def requires_frames(unit,analysis):
    from .native_module_calls import BuiltinRef
    from .native_heapq import CORE
    names=frozenset(CORE)|frozenset(name+'_max'for name in CORE)
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for facts in analysis.scopes.values():
        for site,call in facts.calls.items():
            if not any(isinstance(value,BuiltinRef)and value.module=='heapq'and value.name in names for value in call.identity.alternatives):continue
            term=analysis.graph.expressions.get(site)
            args=term.operands[1]if term is not None and term.operation=='call'else()
            for argument in args:
                kind=facts.expressions.get(argument.site)
                if isinstance(kind,ListType)and container(kind.element):return True
                if container(kind)and not isinstance(kind,ListType):return True
        for site,node in nodes.items():
            if not isinstance(node,ast.Compare)or site not in facts.expressions:continue
            values=[facts.expressions.get(unit.ordinal(child))for child in(node.left,*node.comparators)]
            if any(comparison_demand(values[index],values[index+1],operator)for index,operator in enumerate(node.ops)):return True
    return False


def raw(emitter,value):
    if enabled(emitter.model)and value.kind=='float':
        from .native_classes import Expression
        return Expression('('+value.code+').value','float',value.constant)
    return value


def wrap(emitter,code,node):
    return emitter.at('native_identity_float('+code+')',node)if enabled(emitter.model)else code


def literal(emitter,code,value,node):
    if not enabled(emitter.model):return code
    if math.isnan(value):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'this NaN constant needs its original compiler constant-object identity; that constant-origin adapter is not implemented',proof='source-owned NaN constant origin')
    return 'NativeIdentityFloat::constant('+code+')'


def folded_nan(node):
    if any(isinstance(child,(ast.Name,ast.Call,ast.Attribute,ast.Subscript))for child in ast.walk(node)):return False
    try:code=compile(ast.Expression(node),'<float-constant-origin>','eval',optimize=0)
    except (TypeError,ValueError,SyntaxError,OverflowError):return False
    return any(instruction.opname=='LOAD_CONST'and type(instruction.argval)is float and math.isnan(instruction.argval)for instruction in dis.get_instructions(code))


def binary(emitter,operator,left,right,node,wanted):
    if not enabled(emitter.model):return None
    if left.kind not in NUMERIC or right.kind not in NUMERIC:return None
    if isinstance(operator,ast.Pow)and right.kind in {'int','bool','int_bool'}:
        from .native_integral_powers import frame
        return frame(emitter,operator,left,right,node,wanted)
    if 'float'not in {left.kind,right.kind}and not isinstance(operator,ast.Div):
        if isinstance(operator,ast.Pow)and floating(wanted):
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,'floating power results need retained float identity at every power-result producer; that adapter is not implemented',proof='floating power result identity')
        return None
    if isinstance(operator,ast.Pow):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'floating power results need retained float/complex identity at their actual producer; that adapter is not implemented',proof='floating power result identity')
    if not isinstance(operator,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod)):return None
    if folded_nan(node):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'the official compiler folds this arithmetic to a cached NaN object; retaining that source constant identity is not implemented',proof='source-owned NaN constant origin')
    result=emitter.numeric.binary(operator,raw(emitter,left),raw(emitter,right),node)
    from .native_classes import Expression,ClassUnsupported
    if result.kind!='float':raise ClassUnsupported(node,'this numeric result has no registered identity-preserving float producer',proof='typed float result producer')
    value=Expression(wrap(emitter,result.code,node),'float')
    return Expression(emitter.coerce(value,wanted,node),wanted)


def unary(emitter,operator,value,node,wanted):
    if not enabled(emitter.model)or value.kind!='float':return None
    from .native_classes import Expression
    code=value.code if isinstance(operator,ast.UAdd)else wrap(emitter,'-('+raw(emitter,value).code+')',node)
    return Expression(emitter.coerce(Expression(code,'float'),wanted,node),wanted)


def scalar_comparison(emitter,operator,left,right,node,*,identity=False):
    if not enabled(emitter.model)or 'float'not in {left.kind,right.kind}:return None
    if left.kind not in NUMERIC or right.kind not in NUMERIC:return None
    if isinstance(operator,(ast.Is,ast.IsNot)):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'explicit float identity also observes non-NaN constant/object origins; only identity-aware container equality is implemented by this float carrier',proof='explicit float object identity')
    a,b=raw(emitter,left),raw(emitter,right)
    if emitter.model.integer=='bigint':
        from .native_comparisons import real_comparison
        code=real_comparison(emitter.numeric,a,b,operator,node)
    else:
        from types import SimpleNamespace
        code=emitter.numeric.compare(SimpleNamespace(ops=[operator]),[a,b]).code
    if identity and isinstance(operator,ast.Eq)and left.kind==right.kind=='float':
        code='(('+left.code+').nan_identity!=0&&('+left.code+').nan_identity==('+right.code+').nan_identity)||('+code+')'
    return code


def builtin_container(kind):
    if type(kind)is str:return kind in NUMERIC|{'str','bytes','none'}
    if isinstance(kind,(NullableType,MaybeType)):return builtin_container(kind.value)
    if isinstance(kind,UnionType):return all(builtin_container(child)for child in kind.alternatives)
    if isinstance(kind,TupleType):return not getattr(kind,'_native_named_tuple',False)and all(builtin_container(child)for child in kind.fields)
    if isinstance(kind,(ListType,TupleSequenceType)):return builtin_container(kind.element)
    from .native_types import EmptyType
    return isinstance(kind,EmptyType)


def container_comparison(emitter,operator,left,right,node):
    if not enabled(emitter.model)or not(container(left.kind)or container(right.kind)):return None
    if not builtin_container(left.kind)or not builtin_container(right.kind):return None
    from .native_fallible_heapq import _builtin
    if isinstance(operator,(ast.In,ast.NotIn)):
        from .native_classes import Expression
        if isinstance(right.kind,TupleType):
            from .native_types import tuple_field
            tests=[_builtin(emitter,ast.Eq(),left,Expression(tuple_field(right.code,index)+'.clone()',kind),node)for index,kind in enumerate(right.kind.fields)]
            code='||'.join('('+test+')'for test in tests)or'false'
        elif isinstance(right.kind,(ListType,TupleSequenceType)):
            owner,item=emitter.fresh(),emitter.fresh()
            access=owner+'.borrow()'if isinstance(right.kind,ListType)else owner+'.as_slice()'
            equal=_builtin(emitter,ast.Eq(),left,Expression(item+'.clone()',right.kind.element),node)
            code='{let '+owner+'=('+right.code+').clone();let found='+access+'.iter().any(|'+item+'|'+equal+');found}'
        else:return None
        return '!('+code+')'if isinstance(operator,ast.NotIn)else code
    if isinstance(operator,(ast.Eq,ast.Lt)):return _builtin(emitter,operator,left,right,node)
    if isinstance(operator,ast.NotEq):return '!('+_builtin(emitter,ast.Eq(),left,right,node)+')'
    if isinstance(operator,ast.LtE):return '('+_builtin(emitter,ast.Eq(),left,right,node)+')||('+_builtin(emitter,ast.Lt(),left,right,node)+')'
    if isinstance(operator,ast.Gt):return _builtin(emitter,ast.Lt(),right,left,node)
    if isinstance(operator,ast.GtE):return '('+_builtin(emitter,ast.Eq(),left,right,node)+')||('+_builtin(emitter,ast.Lt(),right,left,node)+')'
    return None


def placeholder(model,kind,code):
    return 'NativeIdentityFloat::constant(0.0_f64)'if enabled(model)and kind=='float'else code


def runtime(model):
    if not enabled(model):return ''
    return RUNTIME


RUNTIME=r'''
#[derive(Clone,Copy)]
struct NativeIdentityFloat{value:f64,nan_identity:usize}
impl NativeIdentityFloat{fn constant(value:f64)->Self{debug_assert!(!value.is_nan());Self{value,nan_identity:0}}}
impl PartialEq for NativeIdentityFloat{fn eq(&self,other:&Self)->bool{self.value==other.value}}
impl PartialOrd for NativeIdentityFloat{fn partial_cmp(&self,other:&Self)->Option<std::cmp::Ordering>{self.value.partial_cmp(&other.value)}}
impl std::ops::Deref for NativeIdentityFloat{type Target=f64;fn deref(&self)->&f64{&self.value}}
thread_local!{static NATIVE_FLOAT_IDENTITY:std::cell::Cell<usize>=const{std::cell::Cell::new(0)};}
fn native_identity_float(value:f64)->Result<NativeIdentityFloat,String>{
    let nan_identity=if value.is_nan(){NATIVE_FLOAT_IDENTITY.with(|counter|{let next=counter.get().checked_add(1).ok_or_else(||"MemoryError: float identity capacity".to_owned())?;counter.set(next);Ok::<usize,String>(next)})?}else{0};
    Ok(NativeIdentityFloat{value,nan_identity})
}
impl ClassDisplay for NativeIdentityFloat{fn class_str(&self)->String{native_float_text(self.value)}}
'''
