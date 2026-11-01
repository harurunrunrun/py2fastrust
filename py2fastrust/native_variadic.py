"""Typed positional argument packs over the original function signature.

Only newly constructed packs use the callee's solved element ABI. Existing
tuple objects are never widened by copying them into another representation.
"""
import ast

from .native_types import TupleSequenceType, TupleType, EmptyType, EMPTY


def parameters(plan):
    return list(plan.signature.parameters)


def initialize(plan):
    from .native_classes import Cell
    if plan.signature.variadic_positional:
        plan.variadic_element = Cell()


def pack_analysis(model, callee, members, node):
    from .native_classes import Cell
    if callee.signature.variadic_positional in getattr(callee,"erased_context_parameters",()):
        return callee.arguments[callee.signature.variadic_positional]
    for value in members:
        model.contribute(callee.variadic_element, value, node)
    return Cell("tuple_sequence", (callee.variadic_element,))


def default_empty(model):
    from .native_classes import Cell, merge
    for plan in model.plans:
        element = getattr(plan, "variadic_element", None)
        if plan.reachable and element is not None and element.root().tag is None:
            merge(element, Cell(EMPTY), plan.node)


def pack_emission(emitter, callee, members, node):
    from .native_classes import Expression, shape
    if callee.signature.variadic_positional in getattr(callee,"erased_context_parameters",()):
        return Expression("()",shape(callee.arguments[callee.signature.variadic_positional]))
    kind = TupleSequenceType(shape(callee.variadic_element))
    values = [emitter.coerce(value, kind.element, node) for value in members]
    return Expression("NativeTuple::from_vec(vec![" + ",".join(values) + "])", kind)


def show(emitter, value, node):
    from .native_classes import Expression
    item = emitter.fresh()
    rendered = emitter.show(Expression(item + ".clone()", value.kind.element), node, True)
    return 'class_tuple_text(&(' + value.code + ').iter().map(|' + item + '|' + rendered + ').collect::<Vec<_>>())'


def comparison(emitter, operator, left, right, node):
    from .native_classes import Expression, ClassUnsupported, has_float_payload
    from .native_types import union_type
    a, b = left.kind, right.kind
    if not isinstance(a, TupleSequenceType) and not isinstance(b, TupleSequenceType):
        return None
    if isinstance(operator, (ast.Is, ast.IsNot)):
        if isinstance(a, TupleSequenceType) and isinstance(b, TupleSequenceType):
            code = f"native_tuple_same(&({left.code}),&({right.code}))"
        elif isinstance(a, TupleSequenceType) and b == TupleType(()):
            code = f"({left.code}).is_empty()"
        elif isinstance(b, TupleSequenceType) and a == TupleType(()):
            code = f"({right.code}).is_empty()"
        else:
            code = "false"
        return f"!({code})" if isinstance(operator, ast.IsNot) else code
    if not isinstance(operator, (ast.Eq, ast.NotEq)):
        raise ClassUnsupported(node, "shared runtime tuple ordering/membership needs its per-element comparison protocol on typed frames", proof="shared tuple comparison protocol")
    if has_float_payload(a) or has_float_payload(b):
        raise ClassUnsupported(node, "tuple equality with floating payloads needs Python element identity, including repeated NaN objects", proof="floating tuple element identity")
    def equal(x, y):
        if isinstance(x.kind, EmptyType):return f"native_empty::<bool>({x.code})"
        if isinstance(y.kind, EmptyType):return f"native_empty::<bool>({y.code})"
        return emitter.comparison(ast.Eq(), x, y, node)
    if isinstance(a, TupleSequenceType) and isinstance(b, TupleSequenceType):
        x, y = emitter.fresh(), emitter.fresh()
        test = equal(Expression(x + ".clone()", a.element), Expression(y + ".clone()", b.element))
        code = f"({left.code}).len()==({right.code}).len()&&({left.code}).iter().zip(({right.code}).iter()).all(|({x},{y})|{test})"
    elif isinstance(a, TupleSequenceType) and isinstance(b, TupleType):
        tests = [equal(Expression(f"({left.code}).as_slice()[{i}].clone()", a.element), Expression(f"({right.code}).{i}.clone()", field)) for i, field in enumerate(b.fields)]
        code = f"({left.code}).len()=={len(b.fields)}" + "".join("&&(" + test + ")" for test in tests)
    elif isinstance(a, TupleType) and isinstance(b, TupleSequenceType):
        return comparison(emitter, operator, right, left, node)
    else:code = "false"
    return f"!({code})" if isinstance(operator, ast.NotEq) else "(" + code + ")"


def runtime(model):
    if not getattr(model,'materialized_tuple',False)and not any(plan.reachable and getattr(plan, "variadic_element", None) is not None for plan in model.plans):
        return ""
    from .native_tuple_sequences import HELPERS
    from .native_constraint_lowering import EMPTY_HELPERS
    unpack = '''
fn class_tuple_unpack_length(length:usize,count:usize)->Result<(),String>{
    if length<count{return Err(format!("ValueError: not enough values to unpack (expected {}, got {})",count,length));}
    if length>count{return Err(format!("ValueError: too many values to unpack (expected {}, got {})",count,length));}
    Ok(())
}
'''
    from .native_classes import shape
    emitted_empty=any(record.emitted and isinstance(shape(record.element),EmptyType) for record in model.iterators.records)
    return HELPERS + "\n" + ("" if emitted_empty else EMPTY_HELPERS) + unpack
