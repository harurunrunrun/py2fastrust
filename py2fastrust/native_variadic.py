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
    if isinstance(operator,(ast.Lt,ast.LtE,ast.Gt,ast.GtE)):
        return ordered(emitter,operator,left,right,node)
    if isinstance(operator,(ast.In,ast.NotIn)):
        return membership(emitter,operator,left,right,node)
    if not isinstance(operator, (ast.Eq, ast.NotEq)):
        raise ClassUnsupported(node, "this shared runtime tuple comparison operator has no registered native adapter", proof="shared tuple comparison operator")
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



def ordered(emitter,operator,left,right,node):
    # Reuse the ordinary kernel on already captured values, with frame-owned
    # temporaries and error locations. No source expression is evaluated here.
    from types import SimpleNamespace
    from .native_tuple_sequences import _ordering
    from .native_comparisons import ORDERING
    tuples=(TupleType,TupleSequenceType)
    if isinstance(left.kind,tuples)and isinstance(right.kind,tuples)and any(
            isinstance(value.kind,TupleSequenceType)and isinstance(value.kind.element,EmptyType)
            for value in (left,right)):
        length=lambda value:str(len(value.kind.fields))+'_usize'if isinstance(value.kind,TupleType)else'('+value.code+').len()'
        return length(left)+ORDERING[type(operator)]+length(right)
    adapter=SimpleNamespace(temporary=emitter.fresh,number=emitter.number,at=emitter.at,
        bits=0 if emitter.model.integer=='bigint'else 128 if emitter.model.integer=='i128'else 64)
    return _ordering(adapter,left,right,operator,node)


def membership(emitter,operator,left,right,node):
    from .native_classes import Expression,ClassUnsupported
    from .native_tuples import _scalar
    if not isinstance(right.kind,(TupleType,TupleSequenceType)):return None
    fields=right.kind.fields if isinstance(right.kind,TupleType)else(right.kind.element,)
    if not _scalar(left.kind)or any(not isinstance(field,EmptyType)and not _scalar(field)for field in fields):
        raise ClassUnsupported(node,'tuple membership needs Python identity-aware element equality; floating NaN and custom/mutable payload equality are not implemented by this native adapter',types=(('item',left.kind),('container',right.kind)),proof='identity-safe tuple element equality')
    if isinstance(right.kind,TupleSequenceType):
        if isinstance(right.kind.element,EmptyType):code='false'
        else:
            item=emitter.fresh()
            test=emitter.comparison(ast.Eq(),left,Expression(item+'.clone()',right.kind.element),node)
            code=f'({right.code}).iter().any(|{item}|{test})'
    else:
        tests=[emitter.comparison(ast.Eq(),left,Expression(f'({right.code}).{index}.clone()',kind),node)for index,kind in enumerate(fields)]
        code='||'.join('('+test+')'for test in tests)or'false'
    return '!('+code+')'if isinstance(operator,ast.NotIn)else'('+code+')'



def sorted_order(emitter,left,right,node,compare):
    from .native_classes import Expression,ClassUnsupported
    from .native_tuples import _scalar
    a,b=left.kind,right.kind
    if any(isinstance(kind,TupleSequenceType)and isinstance(kind.element,EmptyType)for kind in (a,b)):
        length=lambda value:str(len(value.kind.fields))+'_usize'if isinstance(value.kind,TupleType)else'('+value.code+').len()'
        return 'Ok(('+length(left)+').cmp(&('+length(right)+')))'
    if any(not _scalar(kind)for kind in (a,b)):
        raise ClassUnsupported(node,'sorting these runtime tuple keys requires identity-aware floating/custom element comparison; this adapter proves only builtin immutable element equality and ordering',types=(('left key',a),('right key',b)),proof='identity-safe runtime tuple sort comparison')
    if isinstance(a,TupleType):
        # Compare in the original direction, including mixed-type error names.
        tail=f'Ok({len(a.fields)}_usize.cmp(&({right.code}).len()))'
        for index,kind in reversed(list(enumerate(a.fields))):
            x=Expression(f'({left.code}).{index}.clone()',kind)
            y=Expression(f'({right.code}).as_slice()[{index}].clone()',b.element)
            equal=emitter.comparison(ast.Eq(),x,y,node)
            tail=f'if ({right.code}).len()<={index}{{Ok(std::cmp::Ordering::Greater)}}else if {equal}{{{tail}}}else{{{compare(emitter,x,y,node)}}}'
        return '{'+tail+'}'
    if isinstance(b,TupleType):
        tail=f'Ok(({left.code}).len().cmp(&{len(b.fields)}_usize))'
        for index,kind in reversed(list(enumerate(b.fields))):
            x=Expression(f'({left.code}).as_slice()[{index}].clone()',a.element)
            y=Expression(f'({right.code}).{index}.clone()',kind)
            equal=emitter.comparison(ast.Eq(),x,y,node)
            tail=f'if ({left.code}).len()<={index}{{Ok(std::cmp::Ordering::Less)}}else if {equal}{{{tail}}}else{{{compare(emitter,x,y,node)}}}'
        return '{'+tail+'}'
    result=f'Ok(({left.code}).len().cmp(&({right.code}).len()))'
    if any(isinstance(kind.element,EmptyType)for kind in (a,b)):return result
    x,y,saved=(emitter.fresh()for _ in range(3))
    lhs=Expression(x+'.clone()',a.element);rhs=Expression(y+'.clone()',b.element)
    equal=emitter.comparison(ast.Eq(),lhs,rhs,node)
    nested=compare(emitter,lhs,rhs,node)
    return ('{'+f'let mut {saved}={result};for({x},{y})in({left.code}).iter().zip(({right.code}).iter()){{'
            f'if !({equal}){{{saved}={nested};break;}}}}{saved}'+'}')


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
