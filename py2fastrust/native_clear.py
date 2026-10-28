"""Exact builtin clear calls are expressions returning Python None."""
import ast


def try_expression(g,node,environment):
    if not(isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)
           and node.func.attr=="clear"):return None
    from .native import _Binding,_Expression,_MaybeInfo,_Unsupported
    from .native_types import ListType,unmaybe
    from .native_key_types import SetType,DictType
    # Route from pure type facts before lowering a receiver. Lists already use
    # the canonical sequence method plan (including owned temporaries and rows).
    # Returning None must never replay an effectful receiver expression.
    binding=environment.get(node.func.value.id) if isinstance(node.func.value,ast.Name) else None
    if isinstance(binding,_Binding):kind=unmaybe(binding.kind)
    else:
        from .native_constraint_lowering import facts_for
        from .native_constraints import native_kind
        facts,site=facts_for(g,node.func.value)
        kind=None if facts is None else facts.expressions.get(site)
        if kind is not None:kind=native_kind(kind,g.bits)
    if kind in {"list_int","deque_int"}or isinstance(kind,ListType):return None
    if not(kind in {"matrix_int","deque_int","dict_int","set_int"}
           or isinstance(kind,(SetType,DictType))):return None
    receiver=g.expression(node.func.value,environment)
    if receiver.kind!=kind:raise _Unsupported("clear receiver storage differs from its proved type")
    if node.args or node.keywords:raise _Unsupported("clear() accepts no arguments")
    if receiver.owned:
        owner=g.temporary()
        return _Expression(f"{{let mut {owner}={receiver.code};{owner}.clear();()}}","none")
    if not isinstance(node.func.value,ast.Name):
        raise _Unsupported("mutable clear receiver needs a proved storage binding")
    name=node.func.value.id;binding=environment.get(name)
    if not isinstance(binding,_Binding)or name in g.iterating_lists or binding.slot in g.borrowed_slots:
        raise _Unsupported("clear receiver is not uniquely mutable")
    g.expression_mutations.append(binding)
    if isinstance(binding.info,_MaybeInfo):
        check=f"let _=&({receiver.code});"
        owner=f'{binding.slot}.as_mut().expect("validated clear receiver")'
    else:
        check="";owner=binding.slot
        g.update_info(environment,name,g.binding(_Expression("",kind,length=0)))
    return _Expression(f"{{{check}{owner}.clear();()}}","none")
