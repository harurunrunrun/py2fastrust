"""Fixed-width integer division with a separately proved successful divisor.

Operand code is always evaluated in Python order. A singleton value fact does
not establish presence or permit dropping the original checked operand read.
"""
import ast


def code(emitter, operator, left, right, divisor):
    if not isinstance(operator, (ast.Mod, ast.FloorDiv)) or divisor == 0:
        return None
    if left.kind not in {'int', 'bool', 'int_bool'} or right.kind not in {'int', 'bool', 'int_bool'}:
        return None
    literal = emitter.literal(int(divisor))
    a, b = emitter.number(left), emitter.number(right)
    remainder = 'class_divisor_remainder'
    adjustment = f'{remainder}!=0&&({remainder}<0)!=({literal}<0)'
    if isinstance(operator, ast.Mod):
        result = f'if {adjustment}{{{remainder}.wrapping_add({literal})}}else{{{remainder}}}'
    else:
        result = (f'let class_divisor_quotient=class_dividend.wrapping_div({literal});'
                  f'if {adjustment}{{class_divisor_quotient.wrapping_sub(1)}}else{{class_divisor_quotient}}')
    return (f'{{let class_dividend={a};let class_checked_divisor={b};'
            f'let _=class_checked_divisor;let {remainder}=class_dividend.wrapping_rem({literal});{result}}}')


def frame(emitter, operator, left, right, node, wanted):
    if emitter.model.integer not in {'i64', 'i128'}:
        return None
    registry = getattr(emitter.model, 'scalar_heap_constants', None)
    operand = node.right if isinstance(node, ast.BinOp) else node.value if isinstance(node, ast.AugAssign) else None
    if registry is None or registry.reason is not None or operand is None:
        return None
    fact = registry.graph.constant(registry.expr(emitter.plan, operand))
    if fact is None or fact.kind not in {'int', 'bool'}:
        return None
    result = code(emitter, operator, left, right, fact.low)
    return None if result is None else emitter.encoded(result, 'int', wanted, node)
