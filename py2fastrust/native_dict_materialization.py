"""Materialize original dictionary comprehensions into proved owned storage."""
import ast

from .native import _Expression, _Unsupported
from .native_key_types import DictType
from .native_types import immutable, rust_type


def comprehension(g, node, environment):
    if not isinstance(node, ast.DictComp):
        return None
    # A walrus publishes into its enclosing lexical scope. The ordinary
    # comprehension environment is private; do not pretend it is that cell.
    assignment=next((child for child in ast.walk(node) if isinstance(child,ast.NamedExpr)),None)
    if assignment is not None:
        raise _Unsupported('assignment expressions in dictionary comprehensions require enclosing-scope cell writes; that direct adapter is not implemented',node=assignment,proof='comprehension assignment-expression lexical cells')
    from .native_constraint_lowering import facts_for
    from .native_constraints import native_kind
    facts, site=facts_for(g,node)
    logical=facts.allocations.get(site) if facts is not None else None
    if not isinstance(logical,DictType):
        raise _Unsupported('dictionary comprehension key/value allocation types remain unresolved; an owned typed dictionary representation has not been proved',node=node,types=(('dictionary',logical),),proof='resolved comprehension allocation fields')
    from .native_key_containers import key_kind,canonical,_enable
    if not key_kind(logical.key) or not immutable(logical.value):
        raise _Unsupported('dictionary comprehension requires native immutable keys and values; hash callbacks or shared mutable values require a different proved storage representation',node=node,types=(('dictionary',logical),),proof='owned native dictionary key/value storage')
    from .native_stream_plans import context
    from .native_iterators import Planner,TraceContext,_owned
    plan=context(g,environment).comprehension(node)
    source=Planner(g).lower(plan,environment)
    if not source.tupled or len(source.values)!=2:
        raise _Unsupported('dictionary comprehension did not establish separate ordered key/value expressions',node=node,proof='ordered dictionary key/value producer')
    kind=native_kind(logical,g.bits)
    owner,key,item=g.temporary(),g.temporary(),g.temporary()
    key_value,item_value=source.values
    lines=[source.construct()]
    if kind=='dict_int':
        g.has_dicts=True
        lines.append(f'let mut {owner}:NativeDict=NativeDict::new();')
        action=(f'let {key}={_owned(g,key_value,"int")};'
                f'let {item}={_owned(g,item_value,"int")};'
                +g.at(f'{owner}.set({key},{item})',node)+';')
    else:
        _enable(g,kind)
        lines.append(f'let mut {owner}:{rust_type(kind)}=NativeKeyDict::new();')
        normalized=g.temporary()
        action=(f'let {key}={_owned(g,key_value,kind.key)};'
                f'let {item}={_owned(g,item_value,kind.value)};'
                f'let {normalized}={canonical(g,_Expression(key,kind.key))};'
                +g.at(f'{owner}.set({key},{normalized},{item})',node)+';')
    lines.append(source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node)))
    lines.append(owner)
    return _Expression('{\n'+'\n'.join(lines)+'\n}',kind,
                       length=0 if source.length==0 else None,nonempty=source.nonempty)
