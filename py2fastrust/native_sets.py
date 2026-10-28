"""Canonical set materialization from already normalized typed streams."""
from .native import _Expression, _Unsupported
from .native_types import rust_type
from .native_key_types import SetType
from .native_stream_plans import ConsumerKind, consumer_plan


def try_expression(g,node,environment):
    plan=consumer_plan(g,node,environment,{ConsumerKind.SET})
    if plan is None:return None
    from .native_iterators import Planner,TraceContext,stream_item,_owned
    from .native_key_containers import key_kind,canonical,_enable
    source=Planner(g).lower(plan.source,environment,allow_set=True)
    item=stream_item(g,source)
    if not key_kind(item.kind):raise _Unsupported
    kind="set_int" if g.bits and item.kind=="int" else SetType(item.kind)
    # Future mutations can widen this allocation's key representation. The
    # shared solver owns that proof; collection only coerces admitted keys.
    from .native_constraint_lowering import facts_for
    from .native_constraints import native_kind
    facts,site=facts_for(g,node)
    if facts is not None:
        proved=facts.allocations.get(site)
        if isinstance(proved,SetType) and key_kind(proved.key):kind=native_kind(proved,g.bits)
    owner=g.temporary()
    lines=[source.construct()]
    if kind=="set_int":
        g.has_sets=True
        lines.append(f"let mut {owner}:NativeSet=NativeSet::new();")
        action=f"{owner}.insert({_owned(g,item,'int')});"
    else:
        _enable(g,kind)
        lines.append(f"let mut {owner}:{rust_type(kind)}=NativeKeySet::new();")
        if source.length==0:
            action='unreachable!("proved empty set source yielded");'
        else:
            key,normalized=g.temporary(),g.temporary()
            action=(f"let {key}={_owned(g,item,kind.key)};"
                    f"let {normalized}={canonical(g,_Expression(key,kind.key))};"
                    +g.at(f"{owner}.add({key},{normalized})",node)+";")
    lines.append(source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node)))
    lines.append(owner)
    return _Expression("{\n"+"\n".join(lines)+"\n}",kind,
                       length=0 if source.length==0 else None,nonempty=source.nonempty)
