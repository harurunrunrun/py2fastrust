"""Unpack a shared typed iterator before storing any target at this level."""
import ast

from .native_class_iterators import iterator_kind


def analyze(model, plan, target, value, environment):
    from .native_classes import ClassUnsupported, shape
    if not iterator_kind(shape(value)):
        return False
    if any(isinstance(node, ast.Starred) for node in target.elts):
        raise ClassUnsupported(target, "a starred iterator unpack needs remainder-list construction and trailing-target binding", proof="starred unpack remainder storage")
    member = model.iterators.demand(plan, target, value, environment)
    for node in target.elts:
        model.target(plan, node, member, environment)
    return True


def emit(emitter, target, value):
    from .native import _string
    from .native_classes import ClassUnsupported, Expression
    if not iterator_kind(value.kind):
        return None
    if any(isinstance(node, ast.Starred) for node in target.elts):
        raise ClassUnsupported(target, "a starred iterator unpack needs remainder-list construction and trailing-target binding", proof="starred unpack remainder storage")
    setup, source = emitter.capture(value)
    pulled = emitter.model.iterators.pull(emitter, target, source)
    expected = len(target.elts)
    members = []
    for index in range(expected):
        name = emitter.fresh()
        message = f"ValueError: not enough values to unpack (expected {expected}, got {index})"
        missing = emitter.at(f'Err::<{emitter.rust_type(pulled.kind)},String>({_string(message)}.to_owned())', target)
        setup += f"let {name}=match {pulled.code}{{Some(value)=>value,None=>{missing}}};"
        members.append(Expression(name, pulled.kind))
    message = f"ValueError: too many values to unpack (expected {expected})"
    excess = emitter.at(f'Err::<(),String>({_string(message)}.to_owned())', target)
    setup += f"if ({pulled.code}).is_some(){{{excess};}}"
    return setup + "".join(emitter.assign(node, member) for node, member in zip(target.elts, members))
