"""List operators planned from lowered operand types, independently of syntax."""

import ast
from dataclasses import dataclass

from .native import _Expression, _Unsupported
from .native_types import ListType, immutable, join_types, list_type, rust_type


HELPERS = r'''
fn native_typed_concat<A:Clone,B:Clone,T,F:FnMut(A)->T,G:FnMut(B)->T>(
    left:&[A],right:&[B],mut first:F,mut second:G
)->Result<Vec<T>,String> {
    let length=left.len().checked_add(right.len()).ok_or("MemoryError")?;
    let mut result=Vec::new();
    native_typed_reserve(&mut result,length)?;
    result.extend(left.iter().cloned().map(&mut first));
    result.extend(right.iter().cloned().map(&mut second));
    Ok(result)
}
fn native_typed_repeat<T:Clone>(values:&[T],count:i128)->Result<Vec<T>,String> {
    let count=isize::try_from(count)
        .map_err(|_|"OverflowError: cannot fit 'int' into an index-sized integer".to_string())?;
    if count<=0||values.is_empty(){return Ok(Vec::new());}
    let length=values.len().checked_mul(count as usize).ok_or("MemoryError")?;
    let mut result=Vec::new();
    native_typed_reserve(&mut result,length)?;
    if values.len()==1 {result.resize(length,values[0].clone());}
    else {for _ in 0..count {result.extend(values.iter().cloned());}}
    Ok(result)
}
'''


def _element(kind):
    return "int" if kind == "list_int" else kind.element


@dataclass(frozen=True)
class ListOperation:
    operation: str
    result: object
    element: object
    sequence_left: bool = True
    empty_side: str | None = None
    length: int | None = None


def plan_binary(operator, left, right):
    """Resolve list operator meaning after each operand has been lowered once."""
    a, b = list_type(left.kind), list_type(right.kind)
    if not (a or b):
        return None
    if isinstance(operator, ast.Add) and a and b:
        first, second = _element(left.kind), _element(right.kind)
        if left.length == 0:
            return ListOperation("concat", right.kind, second, empty_side="left", length=right.length)
        if right.length == 0:
            return ListOperation("concat", left.kind, first, empty_side="right", length=left.length)
        element = join_types(first, second)
        if element is None or not immutable(element):
            raise _Unsupported
        result = "list_int" if element == "int" else ListType(element)
        length = None if left.length is None or right.length is None else left.length + right.length
        return ListOperation("concat", result, element, length=length)
    if isinstance(operator, ast.Mult) and a != b:
        values, count = (left, right) if a else (right, left)
        if count.kind not in {"int", "bool", "int_bool"} or not immutable(_element(values.kind)):
            raise _Unsupported
        length = None
        if values.length is not None and count.constant is not None and -(1 << 31) <= count.constant < (1 << 31):
            length = values.length * max(0, int(count.constant))
        return ListOperation("repeat", values.kind, _element(values.kind), a, length=length)
    return None


def binary(generator, operator, left, right, node):
    plan = plan_binary(operator, left, right)
    if plan is None:
        return None
    generator.has_lists = generator.has_typed_lists = True
    generator.register_type(plan.result)
    first, second = generator.temporary(), generator.temporary()

    def capture(name, value):
        if list_type(value.kind):
            return f"let {name}:&[{rust_type(_element(value.kind))}]=&({value.code})[..];"
        return f"let {name}={generator.number(value)};"

    setup = capture(first,left) + capture(second,right)
    if plan.operation == "concat":
        if plan.empty_side is not None:
            owner = second if plan.empty_side == "left" else first
            call = generator.at(f"native_typed_copy({owner})", node)
        else:
            a = generator.coerce(_Expression("native_sequence_item", _element(left.kind)), plan.element)
            b = generator.coerce(_Expression("native_sequence_item", _element(right.kind)), plan.element)
            call = generator.at(
                f"native_typed_concat({first},{second},"
                f"|native_sequence_item|{a},|native_sequence_item|{b})", node)
    else:
        values, count = (first, second) if plan.sequence_left else (second, first)
        if generator.bits:
            number = f"({count}) as i128"
        else:
            number = generator.at(
                f'{count}.to_i128().ok_or_else(||String::from("OverflowError: cannot fit \'int\' into an index-sized integer"))', node)
        call = generator.at(f"native_typed_repeat({values},{number})", node)
    return _Expression("{" + setup + call + "}", plan.result, length=plan.length)
