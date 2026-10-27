"""Typed immutable keys with Python numeric equality and original key retention."""
import ast

from .native import _Binding,_Expression,_DictInfo,_SetInfo,_Unsupported,_string
from .native_types import TupleType,immutable,join_types,tuple_field,rust_type
from .native_key_types import DictType,SetType,KeyInfo,canonical_tuple,compatible_keys


HELPERS = r'''
#[derive(Clone)]
struct NativeKeySet<K,C> { entries:Vec<K>, index:std::collections::HashMap<C,usize> }
impl<K,C:Eq+std::hash::Hash> NativeKeySet<K,C> {
    fn new()->Self {Self {entries:Vec::new(),index:std::collections::HashMap::new()}}
    fn len(&self)->usize {self.entries.len()}
    fn is_empty(&self)->bool {self.entries.is_empty()}
    fn clear(&mut self){self.entries.clear();self.index.clear();}
    fn contains(&self,key:&C)->bool {self.index.contains_key(key)}
    fn add(&mut self,key:K,canonical:C)->Result<(),String> {
        if self.index.contains_key(&canonical){return Ok(());}
        self.entries.try_reserve(1).map_err(|_|"MemoryError".to_string())?;
        self.index.try_reserve(1).map_err(|_|"MemoryError".to_string())?;
        self.index.insert(canonical,self.entries.len());self.entries.push(key);Ok(())
    }
}
#[derive(Clone)]
struct NativeKeyDict<K,V,C> { entries:Vec<(K,V)>, index:std::collections::HashMap<C,usize> }
impl<K,V,C:Eq+std::hash::Hash> NativeKeyDict<K,V,C> {
    fn new()->Self {Self {entries:Vec::new(),index:std::collections::HashMap::new()}}
    fn len(&self)->usize {self.entries.len()}
    fn is_empty(&self)->bool {self.entries.is_empty()}
    fn clear(&mut self){self.entries.clear();self.index.clear();}
    fn contains(&self,key:&C)->bool {self.index.contains_key(key)}
    fn get(&self,key:&C)->Option<&V> {self.index.get(key).map(|&index|&self.entries[index].1)}
    fn set(&mut self,key:K,canonical:C,value:V)->Result<(),String> {
        if let Some(&index)=self.index.get(&canonical){self.entries[index].1=value;return Ok(());}
        self.entries.try_reserve(1).map_err(|_|"MemoryError".to_string())?;
        self.index.try_reserve(1).map_err(|_|"MemoryError".to_string())?;
        self.index.insert(canonical,self.entries.len());self.entries.push((key,value));Ok(())
    }
}
'''

BIG_HASH = r'''
impl std::hash::Hash for Int {
    fn hash<H:std::hash::Hasher>(&self,state:&mut H) {
        use std::hash::Hash;
        match &self.0 {
            IntRepr::Small(value)=>{0_u8.hash(state);value.hash(state);},
            IntRepr::Big{negative,digits}=>{1_u8.hash(state);negative.hash(state);digits.hash(state);},
        }
    }
}
'''


def key_kind(kind):
    from .native_types import EmptyType
    return (isinstance(kind,EmptyType) or kind in {"int","bool","int_bool","str"} or
            isinstance(kind,TupleType) and all(key_kind(field) for field in kind.fields))


def _enable(generator,kind):
    generator.has_key_containers=True
    generator.register_type(kind.key)
    if isinstance(kind,DictType):generator.register_type(kind.value)


def _join(values):
    if not values:raise _Unsupported
    kind=values[0].kind
    for value in values[1:]:
        kind=join_types(kind,value.kind)
        if kind is None:raise _Unsupported
    return kind


def canonical(generator,value):
    from .native_types import EmptyType
    if isinstance(value.kind,EmptyType):return f"match {value.code} {{}}"
    if value.kind in {"int","bool","int_bool"}:
        return f"({generator.number(value)}).clone()"
    if value.kind=="str":return f"({value.code}).clone()"
    if isinstance(value.kind,TupleType):
        return canonical_tuple(canonical(generator,_Expression(tuple_field(value.code,index),kind,owned=False)) for index,kind in enumerate(value.kind.fields))
    raise _Unsupported


def _coerce_key(generator,value,kind):
    if not key_kind(value.kind) or not key_kind(kind):raise _Unsupported
    return generator.coerce(value,kind)


def _lookup_key(generator,value,kind):
    if not key_kind(value.kind) or not compatible_keys(value.kind,kind):raise _Unsupported
    return generator.coerce(value,value.kind)


def _new(kind):
    return "NativeKeySet::new()" if isinstance(kind,SetType) else "NativeKeyDict::new()"


def _value(generator,value,kind):
    if not immutable(value.kind) or not immutable(kind):raise _Unsupported
    return generator.coerce(value,kind)


def _repr(generator,value):
    if isinstance(value.kind,TupleType):
        from .native_tuples import tuple_repr
        return tuple_repr(generator,value)
    if value.kind=="str":
        generator.has_tuples=True
        return f"native_tuple_repr_str(&({value.code}))"
    if value.kind=="bool":return f'(if {value.code}{{"True"}}else{{"False"}}).to_owned()'
    return f"({value.code}).to_string()"


def _construct(generator,keys,values,node,*,kind=None):
    if kind is not None:pass
    elif not keys:
        kind=SetType(TupleType(())) if values is None else DictType(TupleType(()),"int")
    else:
        key=_join(keys)
        if not key_kind(key):raise _Unsupported
        kind=SetType(key) if values is None else DictType(key,_join(values))
        if values is not None and not immutable(kind.value):raise _Unsupported
    _enable(generator,kind)
    owner=generator.temporary();lines=[f"let mut {owner}:{rust_type(kind)}={_new(kind)};"]
    for index,key in enumerate(keys):
        keyname=generator.temporary();lines.append(f"let {keyname}={_coerce_key(generator,key,kind.key)};")
        keyvalue=_Expression(keyname,kind.key)
        if values is not None:
            item=generator.temporary();lines.append(f"let {item}={_value(generator,values[index],kind.value)};")
        # Canonicalization borrows the retained key before it is moved.
        canon=generator.temporary();lines.append(f"let {canon}={canonical(generator,keyvalue)};")
        action=f"{owner}.add({keyname},{canon})" if values is None else f"{owner}.set({keyname},{canon},{item})"
        lines.append(generator.at(action,node)+";")
    return _Expression("{"+" ".join(lines)+f"{owner}}}",kind,length=0 if not keys else None,nonempty=bool(keys))


def try_expression(generator,node,environment):
    if isinstance(node,ast.Name):
        binding=environment.get(node.id)
        if isinstance(binding,_Binding) and isinstance(binding.info,KeyInfo):
            return _Expression(binding.slot,binding.kind,owned=False,length=binding.info.length,nonempty=binding.info.nonempty)
    if isinstance(node,ast.Set):
        keys=[generator.expression(key,environment) for key in node.elts]
        if not generator.bits or any(isinstance(key.kind,TupleType) for key in keys):
            return _construct(generator,keys,None,node)
    if isinstance(node,ast.Dict):
        if any(key is None for key in node.keys):raise _Unsupported
        keys=[generator.expression(key,environment) for key in node.keys]
        if not generator.bits or any(isinstance(key.kind,TupleType) for key in keys):
            values=[generator.expression(value,environment) for value in node.values]
            return _construct(generator,keys,values,node)
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and not node.keywords:
        if node.func.id in {"set","dict"} and not node.args and not generator.bits:
            return _construct(generator,[],None if node.func.id=="set" else [],node)
        if node.func.id in {"len","bool"} and len(node.args)==1:
            value=generator.expression(node.args[0],environment)
            if isinstance(value.kind,(SetType,DictType)):
                if node.func.id=="bool":return _Expression(f"!({value.code}).is_empty()","bool")
                code=f"Int::from_i128(({value.code}).len() as i128)" if not generator.bits else f"(({value.code}).len() as NativeInt)"
                return _Expression(code,"int",value.length)
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
        method=node.func.attr
        if method in {"copy","get","setdefault"}:
            value=generator.expression(node.func.value,environment)
            if not isinstance(value.kind,(SetType,DictType)):return None
            if node.keywords:raise _Unsupported
            if method=="copy" and not node.args:
                return _Expression(f"({value.code}).clone()",value.kind,length=value.length,nonempty=value.nonempty)
            if not isinstance(value.kind,DictType) or method!="get" or not 1<=len(node.args)<=2:raise _Unsupported
            key=generator.expression(node.args[0],environment);default=generator.expression(node.args[1],environment) if len(node.args)==2 else _Expression("()","none")
            kind=join_types(value.kind.value,default.kind)
            if kind is None or not immutable(kind):raise _Unsupported
            generator.register_type(kind)
            owner,keyname,fallback=generator.temporary(),generator.temporary(),generator.temporary()
            receiver=value.code if value.owned else f"&({value.code})"
            lines=[f"let {owner}={receiver};",f"let {keyname}={_lookup_key(generator,key,value.kind.key)};",
                   f"let {fallback}={_value(generator,default,kind)};"]
            number=canonical(generator,_Expression(keyname,key.kind))
            from .native_types import EmptyType
            lookup=f"None::<{rust_type(value.kind.value)}>" if isinstance(value.kind.key,EmptyType) else f"{owner}.get(&({number})).cloned()"
            converted=generator.coerce(_Expression("native_dict_value",value.kind.value),kind)
            return _Expression("{"+" ".join(lines)+f"({lookup}).map(|native_dict_value|{converted}).unwrap_or({fallback})}}",kind)
    if isinstance(node,ast.Subscript) and not isinstance(node.slice,ast.Slice):
        owner=generator.expression(node.value,environment)
        if not isinstance(owner.kind,DictType):return None
        key=generator.expression(node.slice,environment)
        receiver,keyname=generator.temporary(),generator.temporary()
        start=f"let {receiver}={owner.code if owner.owned else '&('+owner.code+')'};let {keyname}={_lookup_key(generator,key,owner.kind.key)};"
        keyvalue=_Expression(keyname,key.kind)
        error=_repr(generator,keyvalue)
        from .native_types import EmptyType
        found=f"None::<{rust_type(owner.kind.value)}>" if isinstance(owner.kind.key,EmptyType) else f'{receiver}.get(&({canonical(generator,keyvalue)})).cloned()'
        lookup=f'{found}.ok_or_else(||format!("KeyError: {{}}",{error}))'
        return _Expression("{"+start+generator.at(lookup,node)+"}",owner.kind.value)
    if isinstance(node,ast.Compare) and len(node.ops)==1 and isinstance(node.ops[0],(ast.In,ast.NotIn)):
        key=generator.expression(node.left,environment);owner=generator.expression(node.comparators[0],environment)
        if not isinstance(owner.kind,(SetType,DictType)):return None
        receiver,keyname=generator.temporary(),generator.temporary()
        start=f"let {keyname}={_lookup_key(generator,key,owner.kind.key)};let {receiver}={owner.code if owner.owned else '&('+owner.code+')'};"
        from .native_types import EmptyType
        check="false" if isinstance(owner.kind.key,EmptyType) else f"{receiver}.contains(&({canonical(generator,_Expression(keyname,key.kind))}))"
        if isinstance(node.ops[0],ast.NotIn):check="!"+check
        return _Expression("{"+start+check+"}","bool")
    return None


def _info(generator,environment,name,length=None,nonempty=False):
    previous=environment[name]
    environment[name]=_Binding(previous.slot,KeyInfo(previous.kind,length,nonempty))


def _upgrade(generator,environment,name,kind):
    previous=environment.get(name)
    if not isinstance(previous,_Binding):raise _Unsupported
    info=previous.info
    if not (isinstance(info,(KeyInfo,_SetInfo,_DictInfo)) and info.length==0):raise _Unsupported
    slot=generator.bind(name,_Expression(_new(kind),kind,length=0),environment)
    _enable(generator,kind)
    return f"{slot}={_new(kind)};",generator.expression(ast.Name(id=name,ctx=ast.Load()),environment)


def _widen(generator,environment,name,kind,node):
    previous=generator.expression(ast.Name(id=name,ctx=ast.Load()),environment)
    if previous.kind==kind:return "",previous
    old=generator.temporary();key=generator.temporary();canon=generator.temporary();raw=generator.temporary()
    slot=generator.bind(name,_Expression(_new(kind),kind,length=previous.length,nonempty=previous.nonempty),environment)
    _enable(generator,kind)
    lines=[f"let {old}={previous.code};",f"{slot}={_new(kind)};"]
    if isinstance(kind,SetType):
        original=_Expression(raw,previous.kind.key)
        action=f"{slot}.add({key},{canon})"
        body=f"let {key}={_coerce_key(generator,original,kind.key)};let {canon}={canonical(generator,_Expression(key,kind.key))};"
    else:
        value=generator.temporary()
        body=(f"let {key}={_coerce_key(generator,_Expression(raw+'.0',previous.kind.key),kind.key)};"
              f"let {value}={_value(generator,_Expression(raw+'.1',previous.kind.value),kind.value)};"
              f"let {canon}={canonical(generator,_Expression(key,kind.key))};")
        action=f"{slot}.set({key},{canon},{value})"
    lines.append(f"for {raw} in {old}.entries{{{body}{generator.at(action,node)};}}")
    return "\n".join(lines),generator.expression(ast.Name(id=name,ctx=ast.Load()),environment)


def try_statement(generator,node,environment):
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Subscript):
        target=node.targets[0]
        if not isinstance(target.value,ast.Name) or isinstance(target.slice,ast.Slice):return None
        if target.value.id in generator.iterating_lists:raise _Unsupported
        binding=environment.get(target.value.id)
        if not isinstance(binding,_Binding):return None
        key=generator.expression(target.slice,environment)
        if not isinstance(binding.kind,DictType) and not isinstance(key.kind,TupleType):return None
        value=generator.expression(node.value,environment)
        setup=""
        if not isinstance(binding.kind,DictType) or binding.info.length==0 and (binding.kind.key!=key.kind or binding.kind.value!=value.kind):
            kind=DictType(key.kind,value.kind)
            if not key_kind(kind.key) or not immutable(kind.value):raise _Unsupported
            setup,owner=_upgrade(generator,environment,target.value.id,kind)
        else:
            joined_key=join_types(binding.kind.key,key.kind);joined_value=join_types(binding.kind.value,value.kind)
            if joined_key is None or joined_value is None:raise _Unsupported
            setup,owner=_widen(generator,environment,target.value.id,DictType(joined_key,joined_value),node)
        item,keyname,canon=generator.temporary(),generator.temporary(),generator.temporary()
        # RHS runs before resolving the assignment target, then the tuple key.
        lines=[f"let {item}={_value(generator,value,owner.kind.value)};",setup,
               f"let {keyname}={_coerce_key(generator,key,owner.kind.key)};",
               f"let {canon}={canonical(generator,_Expression(keyname,owner.kind.key))};"]
        lines.append(generator.at(f"{owner.code}.set({keyname},{canon},{item})",node)+";")
        _info(generator,environment,target.value.id,nonempty=True)
        return "\n".join(lines),environment
    if isinstance(node,ast.Assign) and all(isinstance(target,ast.Name) for target in node.targets):
        candidate=node.value
        known=(isinstance(candidate,(ast.Dict,ast.Set)) or isinstance(candidate,ast.Name) and isinstance(environment.get(candidate.id),_Binding) and isinstance(environment[candidate.id].kind,(SetType,DictType))
               or isinstance(candidate,ast.Call) and (isinstance(candidate.func,ast.Name) and candidate.func.id in {"dict","set"}
                   or isinstance(candidate.func,ast.Attribute) and candidate.func.attr=="copy"))
        if not known:return None
        value=generator.expression(candidate,environment)
        if isinstance(value.kind,(SetType,DictType)):
            if not value.owned or len(node.targets)!=1:raise _Unsupported
            target=node.targets[0]
            if target.id in generator.iterating_lists:raise _Unsupported
            slot=generator.bind(target.id,value,environment)
            return f"{slot}={value.code};",environment
    if not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute)
            and isinstance(node.value.func.value,ast.Name)):return None
    call=node.value;name=call.func.value.id;binding=environment.get(name)
    if not isinstance(binding,_Binding):return None
    method=call.func.attr
    if method=="add" and len(call.args)==1 and not call.keywords:
        argument=generator.expression(call.args[0],environment)
        if not isinstance(binding.kind,SetType) and not isinstance(argument.kind,TupleType):return None
        if name in generator.iterating_lists:raise _Unsupported
        setup=""
        if not isinstance(binding.kind,SetType) or binding.info.length==0 and binding.kind.key!=argument.kind:
            if not key_kind(argument.kind):raise _Unsupported
            setup,owner=_upgrade(generator,environment,name,SetType(argument.kind))
        else:
            joined=join_types(binding.kind.key,argument.kind)
            if joined is None:raise _Unsupported
            setup,owner=_widen(generator,environment,name,SetType(joined),node)
        keyname,canon=generator.temporary(),generator.temporary()
        lines=[setup,f"let {keyname}={_coerce_key(generator,argument,owner.kind.key)};",
               f"let {canon}={canonical(generator,_Expression(keyname,owner.kind.key))};",
               generator.at(f"{owner.code}.add({keyname},{canon})",node)+";"]
        _info(generator,environment,name,nonempty=True)
        return "\n".join(lines),environment
    if isinstance(binding.kind,(SetType,DictType)) and method=="clear" and not call.args and not call.keywords:
        if name in generator.iterating_lists:raise _Unsupported
        _info(generator,environment,name,length=0)
        return f"{binding.slot}.clear();",environment
    return None


def stream(generator,node,environment,planner,allow_set=False):
    """Dict views preserve insertion order; sets permit order-free consumers."""
    source=node;mode="keys"
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {"keys","values","items"}:
        source=node.func.value;mode=node.func.attr
        if node.args or node.keywords:raise _Unsupported
    known=(isinstance(source,ast.Name) and isinstance(environment.get(source.id),_Binding)
           and isinstance(environment[source.id].kind,(SetType,DictType)))
    if not known and not isinstance(source,(ast.Dict,ast.Set)):return None
    value=generator.expression(source,environment)
    if not isinstance(value.kind,(SetType,DictType)):return None
    if isinstance(value.kind,SetType) and not allow_set:raise _Unsupported
    owner=generator.temporary() if value.owned else value.code
    setup=f"let {owner}={value.code};" if value.owned else ""
    cursor=generator.temporary()
    begin=f"let {cursor}={owner}.entries.iter();"
    if isinstance(value.kind,SetType):fields=((value.kind.key,"*@",False),)
    elif mode=="items":fields=((value.kind.key,"@.0",False),(value.kind.value,"@.1",False))
    elif mode=="values":fields=((value.kind.value,"@.1",False),)
    else:fields=((value.kind.key,"@.0",False),)
    owners={source.id} if isinstance(source,ast.Name) else set()
    return planner.leaf(setup,begin,cursor,fields,owners,tupled=mode=="items",length=value.length,nonempty=value.nonempty)
