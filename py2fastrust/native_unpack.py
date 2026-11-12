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
    if all(isinstance(target,ast.Name)for target in plan.target.elts):
        from .native_iterators import _owned
        count=len(plan.target.elts)
        lines=[_check(g,str(len(fields)),count,plan.node)]
        if len(fields)!=count:
            return lines+_placeholders(g,plan.target,environment)
        for target,value in zip(plan.target.elts,fields):
            if target.id in g.iterating_lists or not immutable(value.kind)and not value.owned:
                raise _Unsupported
            lines.append(f"{g.bind(target.id,value,environment)}={_owned(g,value,value.kind)};")
        return lines
    from .native_ordered_targets import fields as assign_fields
    return assign_fields(g,plan.target,fields,environment)


def try_statement(g,node,environment):
    plan=consumer_plan(g,node,environment,{ConsumerKind.UNPACK})
    if plan is None:
        return None
    source_plan=plan.source
    if source_plan.kind is ProducerKind.SEQUENCE:
        lines,fields=[],[]
        for element in source_plan.elements:
            value=g.expression(element,environment)
            from .native_ordered_targets import owned
            temporary=g.temporary()
            lines.append(f"let {temporary}={owned(g,value,element)};")
            fields.append(_Expression(temporary,value.kind,owned=True,length=value.length))
        lines+=_assign(g,plan,fields,environment)
        return "\n".join(lines),environment
    binding=environment.get(source_plan.node.id)if isinstance(source_plan.node,ast.Name)else None
    from .native_constraint_lowering import facts_for
    facts,site=facts_for(g,source_plan.node)
    exact_tuple=(facts is not None and isinstance(unmaybe(
        facts.storage.get(site,facts.expressions.get(site))),TupleType))
    captured=g.expression(source_plan.node,environment)if source_plan.kind is ProducerKind.VALUE or exact_tuple else None
    if captured is not None and isinstance(captured.kind,TupleType):
        value=captured
        owner=g.temporary()
        captured=value.code if value.owned else g.coerce(value,value.kind)
        lines=[f"let {owner}={captured};"]
        fields=[_Expression(f"{owner}.{index}",kind,owned=True)for index,kind in enumerate(value.kind.fields)]
        lines+=_assign(g,plan,fields,environment)
        return "\n".join(lines),environment
    from .native_iterators import Planner, TraceContext, _owned, stream_item
    from .native_words import borrow_immediate_input
    source=Planner(g,borrow_input_words=borrow_immediate_input(g,source_plan,environment)).lower(
        source_plan,environment,captured_value=captured)
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
    length_setup=""
    error=f"String::from({_string(message)})"
    if source.unpack_length is not None:
        length_setup,actual_length=source.unpack_length
        error=f'format!("ValueError: too many values to unpack (expected {count}, got {{}})",{actual_length})'
    overflow=g.at(f"Err::<(),String>({error})",node)
    push=g.at(f"native_typed_push(&mut {result},{item})",node)
    action=(f"let {item}={_owned(g,value,value.kind)};\n"
            f"if {result}.len()=={count} {{{overflow};}}\n{push};")
    body=source.emit(action,TraceContext(g.scope_name(),g.expression_trace_id),g.line_code(node))
    construct=source.setup+"\n"+length_setup+"\n"+source.begin
    lines=[construct,f"let mut {result}:Vec<{rust_type(value.kind)}>=Vec::new();",body,
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
