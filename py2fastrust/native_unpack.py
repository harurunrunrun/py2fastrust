"""Unpacking is an N+1 consumer of the common producer plan."""

import ast

from .native import _Binding, _Expression, _Unsupported, _string
from .native_types import TupleType, immutable, rust_type, unmaybe
from .native_stream_plans import ConsumerKind, ProducerKind, consumer_plan


def _check(g,actual,expected,node):
    helper="native_big_unpack_length"if not g.bits else"native_unpack_length"
    g.has_lists=True
    return g.at(f"{helper}({actual},{expected})",node)+";"


def _placeholders(g,target,environment):
    if isinstance(target,ast.Name):
        return [f"{g.bind(target.id,'int',environment)}={g.literal(0)};"]
    if not isinstance(target,(ast.Tuple,ast.List)):
        raise _Unsupported
    return [line for item in target.elts for line in _placeholders(g,item,environment)]


def _assign(g,plan,fields,environment):
    from .native_iterators import Planner, Stream, _owned
    count=len(plan.target.elts)
    lines=[_check(g,str(len(fields)),count,plan.node)]
    if len(fields)!=count:
        return lines+_placeholders(g,plan.target,environment)
    source=Stream("","",tuple(fields),frozenset(),lambda *_:"",tupled=True)
    for target,value in Planner(g).target_values(plan.target,source):
        if target.id in g.iterating_lists or not immutable(value.kind)and not value.owned:
            raise _Unsupported
        lines.append(f"{g.bind(target.id,value,environment)}={_owned(g,value,value.kind)};")
    return lines


def try_statement(g,node,environment):
    plan=consumer_plan(g,node,environment,{ConsumerKind.UNPACK})
    if plan is None:
        return None
    source_plan=plan.source
    if source_plan.kind is ProducerKind.SEQUENCE:
        lines,fields=[],[]
        for element in source_plan.elements:
            value=g.expression(element,environment)
            if not immutable(value.kind)and not value.owned:
                raise _Unsupported
            temporary=g.temporary()
            lines.append(f"let {temporary}={value.code};")
            fields.append(_Expression(temporary,value.kind,owned=True,length=value.length))
        lines+=_assign(g,plan,fields,environment)
        return "\n".join(lines),environment
    binding=environment.get(source_plan.node.id)if isinstance(source_plan.node,ast.Name)else None
    captured=g.expression(source_plan.node,environment)if source_plan.kind is ProducerKind.VALUE else None
    if captured is not None and isinstance(captured.kind,TupleType):
        value=captured
        owner=g.temporary()
        lines=[f"let {owner}={g.coerce(value,value.kind)};"]
        fields=[_Expression(f"{owner}.{index}",kind,owned=False)for index,kind in enumerate(value.kind.fields)]
        lines+=_assign(g,plan,fields,environment)
        return "\n".join(lines),environment
    from .native_iterators import Planner, TraceContext, _owned, stream_item
    source=Planner(g).lower(source_plan,environment,captured_value=captured)
    if source.integer_words is not None:
        count=len(plan.target.elts)
        result=g.temporary()
        call=source.integer_words.call(g,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node),count)
        lines=[source.construct(),f"let {result}={{{call}}};"]
        fields=[_Expression(f"{result}[{index}]","int",owned=False)for index in range(count)]
        lines+=_assign(g,plan,fields,environment)
        return "\n".join(lines),environment
    value=stream_item(g,source)
    if not immutable(value.kind)and not value.owned:
        raise _Unsupported
    g.has_typed_lists=g.has_lists=True
    g.register_type(value.kind)
    result,item=g.temporary(),g.temporary()
    count=len(plan.target.elts)
    message=f"ValueError: too many values to unpack (expected {count})"
    overflow=g.at(f"Err::<(),String>(String::from({_string(message)}))",node)
    push=g.at(f"native_typed_push(&mut {result},{item})",node)
    action=(f"let {item}={_owned(g,value,value.kind)};\n"
            f"if {result}.len()=={count} {{{overflow};}}\n{push};")
    body=source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))
    lines=[source.construct(),f"let mut {result}:Vec<{rust_type(value.kind)}>=Vec::new();",body,
           _check(g,f"{result}.len()",count,node)]
    iterator=g.temporary()
    lines.append(f"let mut {iterator}={result}.into_iter();")
    fields=[]
    for _ in range(count):
        temporary=g.temporary()
        lines.append(f"let {temporary}={iterator}.next().unwrap();")
        fields.append(_Expression(temporary,value.kind,owned=True))
    lines+=_assign(g,plan,fields,environment)
    return "\n".join(lines),environment
