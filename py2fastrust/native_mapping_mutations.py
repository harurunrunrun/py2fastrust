"""Mutate builtin mapping entries with single evaluation and stable order."""
import ast

from .native import _Binding,_Expression,_Unsupported
from .native_key_types import DictType,compatible_keys
from .native_types import EmptyType,is_maybe,unmaybe


def _targets(node):
    if isinstance(node,(ast.Tuple,ast.List)):
        for child in node.elts:yield from _targets(child)
    else:yield node


def _kind(g,source,environment):
    from .native_sequence_storage import binding_name
    binding=environment.get(binding_name(g,source))
    kind=unmaybe(binding.kind)if isinstance(binding,_Binding)else None
    if kind is None:
        from .native_constraint_lowering import facts_for
        facts,site=facts_for(g,source)
        if facts is not None:
            from .native_constraints import native_kind
            kind=native_kind(facts.expressions.get(site),g.bits)
    return kind


def _receiver(g,target,environment):
    value=g.expression(target.value,environment)
    from .native_sequence_storage import binding_name
    name=binding_name(g,target.value);binding=environment.get(name)
    if value.owned:
        owner=g.temporary();lines=[f'let mut {owner}={value.code};']
    elif isinstance(binding,_Binding):
        if name in g.iterating_lists or binding.slot in g.borrowed_slots:
            raise _Unsupported('this dictionary is held by an active native iterator or a read-only function argument; mutation-aware mapping iteration and shared mutable argument storage are not implemented here',node=target,types=(('receiver',value.kind),),proof='mapping identity and active iteration/mutation effects')
        lines=[f'let _=&({value.code});']
        owner=(f'{binding.slot}.as_mut().expect("validated dictionary receiver")'
               if is_maybe(binding.kind)else binding.slot)
    else:
        raise _Unsupported('the dictionary producer has no owned result or proved stable binding that can retain its identity across key evaluation',node=target,types=(('receiver',value.kind),),proof='single evaluation and stable dictionary identity')
    return value,name,binding,owner,lines


def _key(g,target,value,environment,lines):
    key=g.expression(target.slice,environment)
    from .native_key_containers import key_kind,canonical,_repr
    if not key_kind(key.kind):
        raise _Unsupported('dictionary mutation requires a proved immutable builtin key; hashing and equality for this key representation are not implemented',node=target.slice,types=(('key',key.kind),),proof='builtin dictionary key hash/equality')
    expected='int'if value.kind=='dict_int'else value.kind.key
    if not compatible_keys(key.kind,expected):
        raise _Unsupported('these dictionary and lookup key representations have no shared canonical hashing/equality layout',node=target.slice,types=(('dictionary key',expected),('lookup key',key.kind)),proof='compatible builtin dictionary key hash/equality')
    item=g.temporary();lines.append(f'let {item}={g.coerce(key,key.kind)};')
    saved=_Expression(item,key.kind,owned=False)
    code=None
    if not isinstance(expected,EmptyType):
        code=g.temporary();lines.append(f'let {code}={canonical(g,saved)};')
    return saved,code,_repr(g,saved)


def _mutated(g,value,name,binding,environment):
    if value.kind=='dict_int':g.has_dicts=True
    else:g.has_key_containers=True
    if isinstance(binding,_Binding)and not value.owned:
        if not is_maybe(binding.kind):g.update_info(environment,name,g.binding(_Expression('',value.kind)))
        g.expression_mutations.append(binding)


def augmented(g,node,environment):
    target=node.target
    if not isinstance(target,ast.Subscript)or isinstance(target.slice,ast.Slice):return None
    kind=_kind(g,target.value,environment)
    if kind!='dict_int'and not isinstance(kind,DictType):return None
    value,name,binding,owner,lines=_receiver(g,target,environment)
    key,code,error=_key(g,target,value,environment,lines)
    stored='int'if value.kind=='dict_int'else value.kind.value
    from .native_types import immutable,rust_type
    if not immutable(stored):
        raise _Unsupported('augmented dictionary entries need an immutable typed scalar/tuple representation; mutable value in-place protocols are not implemented',node=target,types=(('value',stored),),proof='typed augmented dictionary value and in-place effects')
    if value.kind=='dict_int':lookup=f'{owner}.item({code})'
    else:
        found=f'{owner}.get(&{code}).cloned()'if code is not None else f'None::<{rust_type(stored)}>'
        lookup=f'{found}.ok_or_else(||format!("KeyError: {{}}",{error}))'
    old=g.temporary();lines.append(f'let {old}={g.at(lookup,target)};')
    if isinstance(stored,EmptyType):return '{'+''.join(lines)+f'match {old}{{}}'+'}',environment
    right=g.expression(node.value,environment)
    if isinstance(binding,_Binding)and environment.get(name)!=binding:
        current=environment.get(name)
        if not isinstance(current,_Binding)or current.slot!=binding.slot or current.kind!=binding.kind:
            raise _Unsupported('the augmented dictionary receiver changed physical storage while its right operand ran; a shared mapping identity handle across that transition is not implemented',node=node,proof='captured dictionary identity through right-operand effects')
    rhs=g.temporary();lines.append(f'let {rhs}={g.coerce(right,right.kind)};')
    result=g.binary(node.op,_Expression(old,stored),_Expression(rhs,right.kind,right.constant),node)
    from .native_key_containers import _coerce_key,_value
    calculated=g.temporary();lines.append(f'let {calculated}={_value(g,result,stored)};')
    action=(f'{owner}.set({g.number(key)},{calculated})'if value.kind=='dict_int'else
            f'{owner}.set({_coerce_key(g,key,value.kind.key)},{code},{calculated})')
    lines.append(g.at(action,node)+';')
    _mutated(g,value,name,binding,environment)
    return '{'+''.join(lines)+'}',environment


def lower(g,node,environment):
    if isinstance(node,ast.AugAssign):return augmented(g,node,environment)
    if not isinstance(node,ast.Delete):return None
    targets=[leaf for target in node.targets for leaf in _targets(target)]
    if not all(isinstance(target,ast.Subscript)and not isinstance(target.slice,ast.Slice)for target in targets):return None
    # Leave other subscript families to their existing emitters without
    # visiting effectful receiver expressions twice during dispatch.
    kind=_kind(g,targets[0].value,environment)
    if kind!='dict_int'and not isinstance(kind,DictType):return None
    lines=[]
    for target in targets:
        value,name,binding,owner,setup=_receiver(g,target,environment)
        if value.kind!='dict_int'and not isinstance(value.kind,DictType):
            raise _Unsupported('deletion through this subscript has no typed mapping-delete adapter; list/slice and custom __delitem__ deletion need their own storage/protocol lowering',node=target,types=(('receiver',value.kind),),proof='builtin mapping deletion storage')
        lines.extend(setup)
        saved,code,error=_key(g,target,value,environment,lines)
        if code is None:found='false'
        elif value.kind=='dict_int':found=f'{owner}.delete({code})'
        else:found=f'{owner}.delete(&{code})'
        action=f'if {found}{{Ok(())}}else{{Err(format!("KeyError: {{}}",{error}))}}'
        lines.append(g.at(action,target)+';')
        g.has_mapping_delete=True
        _mutated(g,value,name,binding,environment)
    return '{'+''.join(lines)+'}',environment
