"""Guarded scalar entry specializations for individual AOT function Code IDs.

Proof records are compiler metadata; the original executable instructions remain
the fallback. This deliberately excludes passthrough returns because large int
identity must survive a plain name load or unary plus.
"""

import ast
import json


_BINARY = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.BitAnd: '&',
           ast.BitOr: '|', ast.BitXor: '^'}
_UNARY = {ast.USub: '-', ast.Invert: '~', ast.Not: 'not'}
_COMPARE = {ast.Eq: '==', ast.NotEq: '!=', ast.Lt: '<', ast.LtE: '<=',
            ast.Gt: '>', ast.GtE: '>='}


def prove_native_leaf(node, code, mangle=lambda name: name):
    """Return immutable proof metadata, or None without changing the Code."""
    if not isinstance(node, ast.FunctionDef) or node.type_params or code.is_generator:
        return None
    if code.kind != 'Function' or code.params.vararg or code.params.kwarg:
        return None
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return None
    expression = body[0].value
    if isinstance(expression, (ast.Name, ast.Constant)) or expression is None:
        return None
    parameters = tuple(code.params.positional + code.params.kwonly)
    if not parameters:
        return None
    used = False

    def prove(expression):
        nonlocal used
        if isinstance(expression, ast.Name) and isinstance(expression.ctx, ast.Load):
            name = mangle(expression.id)
            if name not in parameters:
                raise ValueError
            used = True
            return ('param', parameters.index(name))
        if isinstance(expression, ast.Constant) and type(expression.value) in (int, bool):
            return ('bool' if type(expression.value) is bool else 'int', expression.value)
        if isinstance(expression, ast.BinOp) and type(expression.op) in _BINARY:
            return ('binary', _BINARY[type(expression.op)], prove(expression.left), prove(expression.right))
        if isinstance(expression, ast.UnaryOp) and type(expression.op) in _UNARY:
            return ('unary', _UNARY[type(expression.op)], prove(expression.operand))
        if isinstance(expression, ast.Compare) and all(type(op) in _COMPARE for op in expression.ops):
            return ('compare', tuple(_COMPARE[type(op)] for op in expression.ops),
                    tuple(prove(value) for value in [expression.left, *expression.comparators]))
        raise ValueError

    try:
        proof = prove(expression)
    except ValueError:
        return None
    return (parameters, proof) if used else None


class _Lower:
    def __init__(self, bits):
        self.bits = bits
        self.integer = 'i' + str(bits)
        self.counter = 0

    def temporary(self):
        self.counter += 1
        return 'native_leaf_value_' + str(self.counter)

    def number(self, value):
        value %= 1 << self.bits
        if value >= 1 << (self.bits - 1):
            value -= 1 << self.bits
        return self.integer + '::MIN' if value == -(1 << (self.bits - 1)) else f'({value}_{self.integer})'

    def numeric(self, expression, kind):
        return f'({expression} as {self.integer})' if kind == 'bool' else expression

    def lower(self, proof):
        tag, *args = proof
        if tag == 'param':
            return f'native_leaf_arg_{args[0]}', 'int'
        if tag == 'int':
            return self.number(args[0]), 'int'
        if tag == 'bool':
            return str(args[0]).lower(), 'bool'
        if tag == 'unary':
            operation, child = args
            expression, kind = self.lower(child)
            if operation == 'not':
                return (f'(!({expression}))' if kind == 'bool' else f'(({expression}) == 0)'), 'bool'
            expression = self.numeric(expression, kind)
            return (f'({expression}).wrapping_neg()' if operation == '-' else f'(!({expression}))'), 'int'
        if tag == 'binary':
            operation, left, right = args
            left, lk = self.lower(left)
            right, rk = self.lower(right)
            if operation in {'&', '|', '^'} and lk == rk == 'bool':
                return f'(({left}) {operation} ({right}))', 'bool'
            left, right = self.numeric(left, lk), self.numeric(right, rk)
            if operation in {'+', '-', '*'}:
                method = {'+': 'wrapping_add', '-': 'wrapping_sub', '*': 'wrapping_mul'}[operation]
                return f'({left}).{method}({right})', 'int'
            return f'(({left}) {operation} ({right}))', 'int'
        if tag == 'compare':
            operations, children = args
            values = [self.lower(child) for child in children]
            names = [self.temporary() for _ in values]
            clauses = []
            for index, operation in enumerate(operations):
                left = self.numeric(names[index], values[index][1])
                right = self.numeric(names[index + 1], values[index + 1][1])
                comparison = f'(({left}) {operation} ({right}))'
                # Evaluate each chained operand once, only on the taken path.
                clauses.append((names[index + 1], values[index + 1][0], comparison))
            tail = 'true'
            for name, value, comparison in reversed(clauses):
                tail = f'{{let {name}={value}; {comparison} && {tail}}}'
            return f'{{let {names[0]}={values[0][0]}; {tail}}}', 'bool'
        raise AssertionError('invalid native leaf proof')


def generate_native_leaves(program, integer, *, enabled=False):
    """Emit a total entry guard; disabled/BigInt output is a no-op stub."""
    arms = []
    if enabled and integer in {'i64', 'i128'}:
        bits = int(integer[1:])
        for code_id, (parameters, proof) in sorted(program.native_leaves.items()):
            lower = _Lower(bits)
            expression, kind = lower.lower(proof)
            body = []
            for index, name in enumerate(parameters):
                key = json.dumps(name, ensure_ascii=False)
                body.append(f'let native_leaf_arg_{index}: {lower.integer}=match locals.get({key})? {{Value::Int(value)=>{lower.integer}::try_from(value.to_i128()?).ok()?,_=>return None}};')
            body.append(f'// PY2FASTRUST_NATIVE_LEAF_HIT code={code_id}')
            result = f'Value::Bool({expression})' if kind == 'bool' else f'Value::Int(Int::from_i128(({expression}) as i128).into())'
            body.append('Some(' + result + ')')
            arms.append(str(code_id) + '=>{' + '\n'.join(body) + '}')
    if not arms:
        return 'impl Runtime { fn try_native_leaf(&self, _frame:&Frame)->Option<Value> {None} }\n'
    return '''
impl Runtime {
    fn try_native_leaf(&self, frame:&Frame)->Option<Value> {
        if INT_BITS==0 || frame.pc!=1 {return None;}
        let locals=match self.heap.get(frame.locals).and_then(Option::as_ref) {
            Some(Object::Namespace(locals,_))=>locals,
            _=>return None,
        };
        match frame.code {
''' + ',\n'.join(arms) + (',\n' if arms else '') + '''
            _=>None,
        }
    }
}
'''
