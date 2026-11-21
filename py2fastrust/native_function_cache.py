"""Unbounded functools.cache / lru_cache(maxsize=None) on module functions.

The decorated name is bound once to the memoizing wrapper and is only called
directly, so every call site can consult the wrapper's table before entering
the function frame. A hit returns the stored result without a Python frame,
as CPython's C wrapper does; a miss calls the function and stores its result
only after normal completion. Keys are the exact positional argument tuple.
"""
import ast
from dataclasses import dataclass

from .native_types import TupleType


@dataclass
class CachedFunction:
    name: str
    decorator: ast.expr
    table: str
    layout: tuple | None = None


def candidate(node):
    """Defer one decorator whose identity can only be proved with bindings."""
    if not isinstance(node,ast.FunctionDef)or len(node.decorator_list)!=1:return None
    decorator=node.decorator_list[0]
    target=decorator.func if isinstance(decorator,ast.Call)else decorator
    return decorator if isinstance(target,(ast.Name,ast.Attribute))else None


def _unsupported(node,reason):
    from .native_classes import ClassUnsupported
    return ClassUnsupported(node,reason,operation='cached function decorator',proof='native memoized function wrapper')


def _identity(model,plan,target,environment):
    from .native_module_calls import BuiltinRef
    linker=getattr(model,'module_linker',None)
    cell=None if linker is None else linker.pure_cell(plan,target,environment)
    root=None if cell is None else cell.root()
    if root is None or root.tag!='function'or len(root.args)!=1:return None
    identity=root.args[0]
    if isinstance(identity,BuiltinRef)and identity.module=='functools'and identity.name in {'cache','lru_cache'}:
        return identity.name
    return None


def _unbounded(decorator):
    if not isinstance(decorator,ast.Call):return False
    none=lambda value:isinstance(value,ast.Constant)and value.value is None
    if len(decorator.args)==1 and not decorator.keywords:return none(decorator.args[0])
    return (not decorator.args and len(decorator.keywords)==1
            and decorator.keywords[0].arg=='maxsize'and none(decorator.keywords[0].value))


def validate(model,plan,node,function,environment):
    decorator=function.cache_decorator
    target=decorator.func if isinstance(decorator,ast.Call)else decorator
    name=_identity(model,plan,target,environment)
    if name is None:
        raise _unsupported(decorator,'decorator calls can replace the function object at definition time; only canonical functools.cache and lru_cache(maxsize=None) wrappers are implemented natively')
    if name=='cache'and isinstance(decorator,ast.Call)or name=='lru_cache'and not _unbounded(decorator):
        raise _unsupported(decorator,'only functools.cache and lru_cache(maxsize=None) are implemented; bounded LRU eviction and typed keys are not')
    if not(model.is_module_plan(plan)and node in model.tree.body):
        raise _unsupported(decorator,'a cached function must be defined once by a top-level module statement; a fresh cache for each execution of a nested or repeated definition is not implemented')
    arguments=node.args
    if arguments.posonlyargs or arguments.vararg or arguments.kwonlyargs or arguments.kwarg or arguments.defaults:
        raise _unsupported(decorator,'cache keys are the exact passed arguments; only plain positional parameters without defaults are implemented')
    key=model.definition_name(node)
    unit=model.unit
    parents={}
    for parent in ast.walk(model.tree):
        for child in ast.iter_child_nodes(parent):parents[id(child)]=parent
    for item in ast.walk(model.tree):
        if item is node:continue
        if isinstance(item,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))and model.definition_name(item)==key:
            raise _unsupported(item,'the cached function name is rebound by another definition; wrapper identity across rebinding is not implemented')
        if not isinstance(item,ast.Name):continue
        try:resolved=unit.name_for(item)
        except KeyError:continue
        if resolved!=key:continue
        parent=parents.get(id(item))
        if not isinstance(item.ctx,ast.Load):
            raise _unsupported(item,'the cached function name is rebound or deleted; wrapper identity across rebinding is not implemented')
        if not(isinstance(parent,ast.Call)and parent.func is item):
            raise _unsupported(item,'the cache wrapper is used as a value; its first-class object protocol (cache_info, cache_clear, repr, passing) is not implemented')
        if parent.keywords or any(isinstance(value,ast.Starred)for value in parent.args)or len(parent.args)!=len(arguments.args):
            raise _unsupported(parent,'cache keys distinguish keyword, expanded and positional spellings; only calls passing every parameter positionally are implemented')
    sites=getattr(model,'native_cached_functions',None)
    if sites is None:sites=model.native_cached_functions={}
    sites[function.index]=CachedFunction(key,decorator,'CLASS_CACHE_'+str(function.index))


def guard_value(result,node):
    """A canonical cache factory is admitted only as a resolved decorator."""
    from .native_module_calls import BuiltinRef
    root=result.root()if hasattr(result,'root')else None
    if root is None or root.tag!='function'or len(root.args)!=1:return
    identity=root.args[0]
    if isinstance(identity,BuiltinRef)and identity.module=='functools'and identity.name in {'cache','lru_cache'}:
        raise _unsupported(node,f'functools.{identity.name} is lowered only as the decorator of a module-level function that is called directly; a first-class cache factory or wrapper object is not implemented')


def require_validated(model):
    """Every admitted decorator must have been proved before emission."""
    records=getattr(model,'native_cached_functions',{})
    for plan in model.plans:
        decorator=getattr(plan,'cache_decorator',None)
        if decorator is not None and plan.index not in records:
            raise _unsupported(decorator,'a cached function must be defined once by a top-level module statement; a fresh cache for each execution of a nested or repeated definition is not implemented')


def cached(model,function):
    return getattr(model,'native_cached_functions',{}).get(getattr(function,'index',None))


def _key_kind(kind):
    if isinstance(kind,TupleType)and not getattr(kind,'_native_named_tuple',False):return all(_key_kind(field)for field in kind.fields)
    return kind in {'int','bool','str','none'}


def _value_kind(kind):
    if isinstance(kind,TupleType)and not getattr(kind,'_native_named_tuple',False):return all(_value_kind(field)for field in kind.fields)
    return kind in {'int','bool','str','none','float'}


def wrap(emitter,node,record,callee,parameters,arguments,call):
    """Look up the captured argument tuple before the call enters a frame."""
    from .native_classes import shape
    kinds=[shape(callee.arguments[name])for name in parameters]
    result=shape(callee.result)
    if not all(_key_kind(kind)for kind in kinds):
        raise _unsupported(node,'this cache key needs Python hash/equality for its argument types (for example float or mixed int/bool keys that compare equal); only exact int, bool, str, None and tuples of them are implemented')
    if not _value_kind(result):
        raise _unsupported(node,'the cached result is a mutable or identity-bearing object that every hit must share; only immutable scalar and tuple results are implemented')
    key_type='('+''.join(emitter.rust_type(kind)+','for kind in kinds)+')'
    layout=(key_type,emitter.rust_type(result))
    if record.layout is not None and record.layout!=layout:
        raise _unsupported(node,'calls of this cached function use different native argument layouts; one shared table for several specializations is not implemented')
    record.layout=layout
    key,hit,value=emitter.fresh(),emitter.fresh(),emitter.fresh()
    table=record.table
    tuple_code='('+''.join(argument+'.clone(),'for argument in arguments)+')'
    return (f'{{let {key}={tuple_code};match {table}.with(|table|table.borrow().get(&{key}).cloned()){{Some({hit})=>{hit},'
            f'None=>{{let {value}={call};{table}.with(|table|table.borrow_mut().insert({key},{value}.clone()));{value}}}}}}}')


HASHER=r'''
#[derive(Default)]
struct ClassCacheHasher{state:u64}
impl ClassCacheHasher{#[inline]fn absorb(&mut self,value:u64){let product=((self.state^value)as u128)*0xa0761d6478bd642f_u128;self.state=(product as u64)^((product>>64)as u64);}}
impl std::hash::Hasher for ClassCacheHasher{
 #[inline]fn finish(&self)->u64{self.state}
 fn write(&mut self,bytes:&[u8]){self.absorb(bytes.len()as u64);for chunk in bytes.chunks(8){let mut word=[0_u8;8];word[..chunk.len()].copy_from_slice(chunk);self.absorb(u64::from_le_bytes(word));}}
 #[inline]fn write_u8(&mut self,value:u8){self.absorb(value as u64)}
 #[inline]fn write_u64(&mut self,value:u64){self.absorb(value)}
 #[inline]fn write_i64(&mut self,value:i64){self.absorb(value as u64)}
 #[inline]fn write_usize(&mut self,value:usize){self.absorb(value as u64)}
 #[inline]fn write_i128(&mut self,value:i128){self.absorb(value as u64);self.absorb((value>>64)as u64)}
}
type ClassCacheBuild=std::hash::BuildHasherDefault<ClassCacheHasher>;
'''


def runtime(source,model):
    tables=[record for record in getattr(model,'native_cached_functions',{}).values()if record.layout is not None]
    if not tables:return source
    pieces=[HASHER]
    for record in tables:
        key,value=record.layout
        pieces.append(f'thread_local!{{static {record.table}:std::cell::RefCell<std::collections::HashMap<{key},{value},ClassCacheBuild>>=std::cell::RefCell::new(std::collections::HashMap::default());}}\n')
    if model.integer=='bigint'and'impl std::hash::Hash for Int 'not in source and'impl std::hash::Hash for Int{'not in source:
        from .native_key_containers import BIG_HASH
        pieces.append(BIG_HASH)
    return source+''.join(pieces)
