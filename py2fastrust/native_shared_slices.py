"""A list slice copies the outer vector and retains shared child identities."""
import ast

from .native_types import ListType


def expression(generator,node,owner,environment):
    from .native import _Expression
    generator.has_slices=generator.has_lists=generator.has_typed_lists=True
    handle=generator.temporary()
    lines=[f'let {handle}={owner.code};']
    bounds=[]
    for bound in (node.slice.lower,node.slice.upper,node.slice.step):
        if bound is None or isinstance(bound,ast.Constant)and bound.value is None:
            bounds.append('None')
            continue
        value=generator.expression(bound,environment)
        captured=generator.temporary()
        lines.append(f'let {captured}={generator.number(value)};')
        number=(f'({captured})as i128'if generator.bits else
            f'{captured}.to_i128().unwrap_or_else(||if {captured}.is_negative(){{i128::MIN}}else{{i128::MAX}})')
        bounds.append(f'Some({number})')
    guard,indices=generator.temporary(),generator.temporary()
    lines.append(f'let {guard}={handle}.borrow();')
    lines.append(f'let {indices}='+generator.at(f'native_slice_indices({guard}.len(),{",".join(bounds)})',node)+';')
    kind='list_int'if owner.kind.element=='int'else ListType(owner.kind.element)
    generator.register_type(kind)
    code='{'+''.join(lines)+f'native_flat_slice(&{guard},{indices})'+'}'
    return _Expression(code,kind,owned=True)
