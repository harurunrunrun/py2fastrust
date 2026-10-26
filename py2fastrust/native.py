"""Conservative scalar/list AOT lowering; unproved programs use the general VM.

The analysis tracks definite bindings along normal control-flow paths and one
stable scalar or uniquely owned integer-list type for every name. No user expression is executed during
analysis. In particular, potentially dynamic Python programs are never
partially lowered by this backend.
"""

import ast
from dataclasses import dataclass
from importlib.resources import files
import symtable


class _Unsupported(Exception):
    pass


@dataclass(frozen=True)
class _Expression:
    code: str
    kind: str
    constant: int | bool | None = None
    owned: bool = True
    length: int | None = None


@dataclass(frozen=True)
class _ListInfo:
    length: int | None


def _string(value):
    out = ['"']
    for char in value:
        if char in ('"', "\\"):
            out.append("\\" + char)
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 32 or ord(char) == 127:
            out.append(f"\\u{{{ord(char):x}}}")
        else:
            out.append(char)
    return "".join(out) + '"'


_HELPERS = r'''
#[derive(Debug)]
struct NativeError { message: String, line: usize }
fn native_at<T>(result: Result<T, String>, line: usize) -> Result<T, NativeError> {
    result.map_err(|message| NativeError { message, line })
}
#[inline]
fn native_divmod(a: NativeInt, b: NativeInt) -> Result<(NativeInt, NativeInt), String> {
    if b == 0 { return Err("ZeroDivisionError: integer division or modulo by zero".into()); }
    if a == NativeInt::MIN && b == -1 { return Ok((NativeInt::MIN, 0)); }
    let (mut q, mut r) = (a / b, a % b);
    if r != 0 && (r < 0) != (b < 0) { q = q.wrapping_sub(1); r = r.wrapping_add(b); }
    Ok((q, r))
}
#[inline]
fn native_shl(a: NativeInt, b: NativeInt) -> Result<NativeInt, String> {
    if b < 0 { return Err("ValueError: negative shift count".into()); }
    Ok(if b >= NativeInt::BITS as NativeInt { 0 } else { a.wrapping_shl(b as u32) })
}
#[inline]
fn native_shr(a: NativeInt, b: NativeInt) -> Result<NativeInt, String> {
    if b < 0 { return Err("ValueError: negative shift count".into()); }
    Ok(if b >= NativeInt::BITS as NativeInt { if a < 0 { -1 } else { 0 } } else { a >> b as u32 })
}
#[inline]
fn native_pow(mut base: NativeInt, mut exponent: NativeInt) -> Result<NativeInt, String> {
    if exponent < 0 { return Err("TypeError: negative exponent is not an integer operation".into()); }
    let mut result: NativeInt = 1;
    while exponent != 0 {
        if exponent & 1 != 0 { result = result.wrapping_mul(base); }
        exponent >>= 1;
        if exponent != 0 { base = base.wrapping_mul(base); }
    }
    Ok(result)
}
// The iterator state is separate from the user's for target. checked_add is
// structural arithmetic: wrapping a cursor could run forever past the stop.
struct NativeRange { cursor: NativeInt, stop: NativeInt, step: NativeInt, active: bool }
impl NativeRange {
    fn new(start: NativeInt, stop: NativeInt, step: NativeInt) -> Result<Self, String> {
        if step == 0 { return Err("ValueError: range() arg 3 must not be zero".into()); }
        Ok(Self { cursor: start, stop, step, active: if step > 0 { start < stop } else { start > stop } })
    }
}
impl Iterator for NativeRange {
    type Item = NativeInt;
    #[inline]
    fn next(&mut self) -> Option<NativeInt> {
        if !self.active { return None; }
        let value = self.cursor;
        if let Some(next) = value.checked_add(self.step) {
            self.cursor = next;
            self.active = if self.step > 0 { next < self.stop } else { next > self.stop };
        } else { self.active = false; }
        Some(value)
    }
}
'''


_INPUT_HELPERS = r'''
struct NativeInput { text: String, position: usize }
impl NativeInput {
    fn new() -> Result<Self, String> {
        use std::io::Read;
        let mut text = String::new();
        std::io::stdin().read_to_string(&mut text).map_err(|e| format!("OSError: {}", e))?;
        Ok(Self { text, position: 0 })
    }
    fn integer(&mut self) -> Result<NativeInt, String> {
        if self.position == self.text.len() { return Err("EOFError: EOF when reading a line".into()); }
        let start = self.position;
        let bytes = self.text.as_bytes();
        while self.position < bytes.len() && bytes[self.position] != b'\n' { self.position += 1; }
        let end = self.position;
        if self.position < bytes.len() { self.position += 1; }
        Int::parse(&self.text[start..end], 10).map(|n| n.to_i128().unwrap() as NativeInt)
    }
}
'''


_LIST_HELPERS = r'''
#[inline]
fn native_index(index: NativeInt, length: usize) -> Result<usize, String> {
    if index < 0 {
        let magnitude = index.unsigned_abs() as u128;
        if magnitude <= length as u128 { return Ok(length - magnitude as usize); }
    } else if (index as u128) < length as u128 { return Ok(index as usize); }
    Err("IndexError: list index out of range".into())
}
#[inline]
fn native_get(values: &[NativeInt], index: NativeInt) -> Result<NativeInt, String> {
    native_index(index, values.len()).map(|index| values[index])
}
#[inline]
fn native_set(values: &mut [NativeInt], index: NativeInt, value: NativeInt) -> Result<(), String> {
    let index = native_index(index, values.len()).map_err(|_| "IndexError: list assignment index out of range".to_string())?;
    values[index] = value;
    Ok(())
}
fn native_repeat(values: Vec<NativeInt>, count: NativeInt) -> Result<Vec<NativeInt>, String> {
    let count = isize::try_from(count).map_err(|_| "OverflowError: cannot fit 'int' into an index-sized integer".to_string())?;
    if count <= 0 || values.is_empty() { return Ok(Vec::new()); }
    let count = count as usize;
    let size = values.len().checked_mul(count).ok_or_else(|| "MemoryError: repeated list is too large".to_string())?;
    let mut result = Vec::new();
    result.try_reserve_exact(size).map_err(|_| "MemoryError: repeated list is too large".to_string())?;
    if values.len() == 1 { result.resize(size, values[0]); }
    else { for _ in 0..count { result.extend_from_slice(&values); } }
    Ok(result)
}
'''


class _Generator:
    BUILTINS = {"int", "input", "print", "range", "abs", "pow", "len", "sum"}

    def __init__(self, bits):
        self.bits = bits
        self.bindings = {}
        self.names = {}
        self.counter = 0
        self.loops = []
        self.needs_integer_runtime = False
        self.has_input = False
        self.has_lists = False
        self.iterating_lists = []

    def temporary(self):
        self.counter += 1
        return f"native_temp_{self.counter}"

    def normalize(self, value):
        value = int(value) % (1 << self.bits)
        return value if value < 1 << (self.bits - 1) else value - (1 << self.bits)

    def literal(self, value):
        value = self.normalize(value)
        if value == -(1 << (self.bits - 1)):
            return "NativeInt::MIN"
        return f"({value}_i128 as NativeInt)"

    def bind(self, name, kind):
        if name in self.BUILTINS or self.bindings.get(name, kind) != kind:
            raise _Unsupported
        self.bindings[name] = kind
        if name not in self.names:
            self.names[name] = f"native_var_{len(self.names)}"
        return self.names[name]

    @staticmethod
    def number(expression):
        if expression.kind == "int":
            return expression.code
        if expression.kind == "bool":
            return f"(({expression.code}) as NativeInt)"
        raise _Unsupported

    @staticmethod
    def truth(expression):
        if expression.kind == "list_int":
            return f"!({expression.code}).is_empty()"
        return expression.code if expression.kind == "bool" else f"(({expression.code}) != 0)"

    @staticmethod
    def binding(expression):
        return _ListInfo(expression.length) if expression.kind == "list_int" else expression.kind

    @staticmethod
    def consume_list(expression):
        return expression.code if expression.owned else f"({expression.code}).clone()"

    @staticmethod
    def at(code, node):
        return f"native_at({code}, {node.lineno})?"

    def expression(self, node, environment):
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return _Expression(str(node.value).lower(), "bool", node.value)
            if type(node.value) is int:
                return _Expression(self.literal(node.value), "int", self.normalize(node.value))
            raise _Unsupported
        if isinstance(node, ast.Name):
            if node.id not in environment:
                raise _Unsupported
            information = environment[node.id]
            if isinstance(information, _ListInfo):
                return _Expression(self.names[node.id], "list_int", owned=False, length=information.length)
            return _Expression(self.names[node.id], information)
        if isinstance(node, ast.List):
            values = [self.expression(value, environment) for value in node.elts]
            if any(value.kind != "int" for value in values):
                raise _Unsupported
            self.has_lists = True
            return _Expression("vec![" + ", ".join(value.code for value in values) + "]", "list_int", length=len(values))
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                raise _Unsupported
            values = self.expression(node.value, environment)
            if values.kind != "list_int":
                raise _Unsupported
            index = self.expression(node.slice, environment)
            return _Expression(self.at(f"native_get(&({values.code}), {self.number(index)})", node), "int")
        if isinstance(node, ast.ListComp):
            if len(node.generators) != 1 or node.generators[0].is_async or not isinstance(node.generators[0].target, ast.Name):
                raise _Unsupported
            comprehension = node.generators[0]
            setup, iterator, arguments = self.range_iterator(comprehension.iter, environment)
            target = comprehension.target.id
            local = self.temporary()
            previous = self.names.get(target)
            self.names[target] = local
            inside = environment.copy()
            inside[target] = "int"
            try:
                filters = [self.expression(condition, inside) for condition in comprehension.ifs]
                element = self.expression(node.elt, inside)
            finally:
                if previous is None:
                    self.names.pop(target, None)
                else:
                    self.names[target] = previous
            if element.kind != "int":
                raise _Unsupported
            self.has_lists = True
            result = self.temporary()
            insertion = f"{result}.push({element.code});"
            for condition in reversed(filters):
                insertion = f"if {self.truth(condition)} {{ {insertion} }}"
            length = None
            if not filters and all(argument.constant is not None for argument in arguments):
                start, stop, step = (int(argument.constant) for argument in arguments)
                if step > 0:
                    length = max(0, (stop - start + step - 1) // step)
                elif step < 0:
                    length = max(0, (start - stop - step - 1) // -step)
            code = f"{{ {setup} let mut {result}: Vec<NativeInt> = Vec::new(); for {local} in {iterator} {{ {insertion} }} {result} }}"
            return _Expression(code, "list_int", length=length)
        if isinstance(node, ast.UnaryOp):
            value = self.expression(node.operand, environment)
            if isinstance(node.op, ast.Not):
                return _Expression(f"(!({self.truth(value)}))", "bool", None if value.constant is None else not value.constant)
            number = self.number(value)
            if isinstance(node.op, ast.UAdd):
                return _Expression(number, "int", value.constant)
            if isinstance(node.op, ast.USub):
                return _Expression(f"({number}).wrapping_neg()", "int", None if value.constant is None else self.normalize(-value.constant))
            if isinstance(node.op, ast.Invert):
                return _Expression(f"(!({number}))", "int", None if value.constant is None else self.normalize(~value.constant))
            raise _Unsupported
        if isinstance(node, ast.BinOp):
            left = self.expression(node.left, environment)
            right = self.expression(node.right, environment)
            return self.binary(node.op, left, right, node)
        if isinstance(node, ast.BoolOp):
            values = [self.expression(value, environment) for value in node.values]
            if len({value.kind for value in values}) != 1 or values[0].kind == "list_int":
                raise _Unsupported
            code = values[-1].code
            for value in reversed(values[:-1]):
                name = self.temporary()
                check = self.truth(_Expression(name, value.kind))
                yes, no = (code, name) if isinstance(node.op, ast.And) else (name, code)
                code = f"{{ let {name} = {value.code}; if {check} {{ {yes} }} else {{ {no} }} }}"
            return _Expression(code, values[0].kind)
        if isinstance(node, ast.Compare):
            values = [self.expression(value, environment) for value in [node.left, *node.comparators]]
            operators = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
            if any(type(op) not in operators for op in node.ops):
                raise _Unsupported
            names = [self.temporary() for _ in values]
            tail = "true"
            for index in reversed(range(len(node.ops))):
                compare = f"{names[index]} {operators[type(node.ops[index])]} {names[index + 1]}"
                tail = f"{{ let {names[index + 1]} = {self.number(values[index + 1])}; {compare} && ({tail}) }}"
            code = f"{{ let {names[0]} = {self.number(values[0])}; {tail} }}"
            return _Expression(code, "bool")
        if isinstance(node, ast.IfExp):
            test = self.expression(node.test, environment)
            yes = self.expression(node.body, environment)
            no = self.expression(node.orelse, environment)
            if yes.kind != no.kind:
                raise _Unsupported
            if yes.kind == "list_int":
                raise _Unsupported
            return _Expression(f"(if {self.truth(test)} {{ {yes.code} }} else {{ {no.code} }})", yes.kind)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name == "int" and not node.args:
                return _Expression(self.literal(0), "int", 0)
            if name == "int" and len(node.args) == 1:
                argument = node.args[0]
                if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Name) and argument.func.id == "input" and not argument.args and not argument.keywords:
                    self.needs_integer_runtime = self.has_input = True
                    return _Expression(self.at("native_input.integer()", argument), "int")
                value = self.expression(argument, environment)
                return _Expression(self.number(value), "int", value.constant)
            if name == "abs" and len(node.args) == 1:
                value = self.expression(node.args[0], environment)
                constant = None if value.constant is None else self.normalize(abs(value.constant))
                return _Expression(f"({self.number(value)}).wrapping_abs()", "int", constant)
            if name == "len" and len(node.args) == 1:
                value = self.expression(node.args[0], environment)
                if value.kind != "list_int":
                    raise _Unsupported
                return _Expression(f"(({value.code}).len() as NativeInt)", "int", value.length)
            if name == "sum" and len(node.args) in (1, 2):
                value = self.expression(node.args[0], environment)
                if value.kind != "list_int":
                    raise _Unsupported
                start = self.expression(node.args[1], environment) if len(node.args) == 2 else _Expression(self.literal(0), "int", 0)
                if start.kind != "int":
                    raise _Unsupported
                values_name, start_name = self.temporary(), self.temporary()
                # Borrow a named list, own a temporary list; evaluate start only
                # after evaluating the iterable, as Python does.
                binding = value.code if value.owned else f"&({value.code})"
                code = f"{{ let {values_name} = {binding}; let {start_name} = {self.number(start)}; {values_name}.iter().fold({start_name}, |acc, &value| acc.wrapping_add(value)) }}"
                return _Expression(code, "int")
            if name == "pow" and len(node.args) in (2, 3):
                arguments = [self.expression(value, environment) for value in node.args]
                if len(arguments) == 2:
                    return self.binary(ast.Pow(), *arguments, node)
                self.needs_integer_runtime = True
                names = [self.temporary() for _ in arguments]
                code = " ".join(f"let {name} = Int::from_i128(({self.number(value)}) as i128);" for name, value in zip(names, arguments))
                call = self.at(f"{names[0]}.modpow(&{names[1]}, &{names[2]})", node)
                return _Expression(f"{{ {code} ({call}).to_i128().unwrap() as NativeInt }}", "int")
        raise _Unsupported

    def binary(self, operator, left, right, node):
        if isinstance(operator, ast.Mult) and "list_int" in (left.kind, right.kind):
            values, count = (left, right) if left.kind == "list_int" else (right, left)
            self.number(count)
            self.has_lists = True
            # Snapshot both operands in source order. List repetition produces
            # a fresh list, so copying the immutable scalar elements is exact.
            first, second = self.temporary(), self.temporary()
            left_code = self.consume_list(left) if left.kind == "list_int" else self.number(left)
            right_code = self.consume_list(right) if right.kind == "list_int" else self.number(right)
            list_name, count_name = (first, second) if left.kind == "list_int" else (second, first)
            repeated = self.at(f"native_repeat({list_name}, {count_name})", node)
            code = f"{{ let {first} = {left_code}; let {second} = {right_code}; {repeated} }}"
            length = None if values.length is None or count.constant is None else values.length * max(0, int(count.constant))
            return _Expression(code, "list_int", length=length)
        a, b = self.number(left), self.number(right)
        simple = {ast.Add: "wrapping_add", ast.Sub: "wrapping_sub", ast.Mult: "wrapping_mul"}
        bitwise = {ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^"}
        constant = None
        if type(operator) in simple:
            code = f"({a}).{simple[type(operator)]}({b})"
        elif type(operator) in bitwise:
            code = f"(({a}) {bitwise[type(operator)]} ({b}))"
        elif isinstance(operator, (ast.FloorDiv, ast.Mod)):
            code = f"({self.at(f'native_divmod({a}, {b})', node)}).{0 if isinstance(operator, ast.FloorDiv) else 1}"
        elif isinstance(operator, (ast.LShift, ast.RShift)):
            function = "native_shl" if isinstance(operator, ast.LShift) else "native_shr"
            code = self.at(f"{function}({a}, {b})", node)
        elif isinstance(operator, ast.Pow):
            # A negative exponent changes the result to float. Only a proved
            # nonnegative exponent belongs to this scalar integer backend.
            if right.constant is None or right.constant < 0:
                raise _Unsupported
            code = self.at(f"native_pow({a}, {b})", node)
        else:
            raise _Unsupported
        if left.constant is not None and right.constant is not None:
            x, y = int(left.constant), int(right.constant)
            try:
                if isinstance(operator, ast.Add): constant = x + y
                elif isinstance(operator, ast.Sub): constant = x - y
                elif isinstance(operator, ast.Mult): constant = x * y
                elif isinstance(operator, ast.FloorDiv): constant = x // y
                elif isinstance(operator, ast.Mod): constant = x % y
                elif isinstance(operator, ast.BitAnd): constant = x & y
                elif isinstance(operator, ast.BitOr): constant = x | y
                elif isinstance(operator, ast.BitXor): constant = x ^ y
                elif isinstance(operator, ast.Pow): constant = pow(x, y, 1 << self.bits)
                elif isinstance(operator, ast.LShift) and y >= 0: constant = 0 if y >= self.bits else x << y
                elif isinstance(operator, ast.RShift) and y >= 0: constant = x >> y
            except (ValueError, ZeroDivisionError):
                pass
            if constant is not None:
                constant = self.normalize(constant)
        return _Expression(code, "int", constant)

    def range_iterator(self, node, environment):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "range" or node.keywords or not 1 <= len(node.args) <= 3:
            raise _Unsupported
        arguments = [self.expression(value, environment) for value in node.args]
        if len(arguments) == 1:
            arguments.insert(0, _Expression(self.literal(0), "int", 0))
        if len(arguments) == 2:
            arguments.append(_Expression(self.literal(1), "int", 1))
        names = [self.temporary() for _ in arguments]
        setup = "\n".join(f"let {name} = {self.number(argument)};" for name, argument in zip(names, arguments))
        if arguments[2].constant == 1:
            iterator = f"({names[0]}..{names[1]})"
        elif arguments[2].constant == -1:
            iterator = f"({names[1]}..{names[0]}).rev().map(|native_descending_value: NativeInt| native_descending_value.wrapping_add(1))"
        else:
            iterator = self.at(f"NativeRange::new({', '.join(names)})", node)
        return setup, iterator, arguments

    def statements(self, statements, environment):
        environment = environment.copy()
        code = []
        for statement in statements:
            if environment is None:
                break
            rendered, environment = self.statement(statement, environment)
            code.append(rendered)
        return "\n".join(code), environment

    @staticmethod
    def join(first, second):
        if first is None:
            return second
        if second is None:
            return first
        return {name: kind for name, kind in first.items() if second.get(name) == kind}

    def statement(self, node, environment):
        if isinstance(node, ast.Pass):
            return ";", environment
        if isinstance(node, ast.Assign):
            value = self.expression(node.value, environment)
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
                target = node.targets[0]
                if value.kind != "int" or not isinstance(target.value, ast.Name) or target.value.id in self.iterating_lists:
                    raise _Unsupported
                values = self.expression(target.value, environment)
                if values.kind != "list_int" or isinstance(target.slice, ast.Slice):
                    raise _Unsupported
                index = self.expression(target.slice, environment)
                result, offset = self.temporary(), self.temporary()
                setter = self.at(f"native_set(&mut {values.code}, {offset}, {result})", node)
                return f"let {result} = {value.code};\nlet {offset} = {self.number(index)};\n{setter};", environment
            if not all(isinstance(target, ast.Name) and target.id not in self.iterating_lists for target in node.targets):
                raise _Unsupported
            if value.kind == "list_int" and (not value.owned or len(node.targets) != 1):
                raise _Unsupported
            name = self.temporary()
            lines = [f"let {name} = {value.code};"]
            for target in node.targets:
                lines.append(f"{self.bind(target.id, value.kind)} = {name};")
                environment[target.id] = self.binding(value)
            return "\n".join(lines), environment
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Subscript):
            target = node.target
            if not isinstance(target.value, ast.Name) or target.value.id in self.iterating_lists or isinstance(target.slice, ast.Slice):
                raise _Unsupported
            values = self.expression(target.value, environment)
            if values.kind != "list_int":
                raise _Unsupported
            index = self.expression(target.slice, environment)
            offset, old = self.temporary(), self.temporary()
            getter = self.at(f"native_get(&{values.code}, {offset})", target)
            right = self.expression(node.value, environment)
            value = self.binary(node.op, _Expression(old, "int"), right, node)
            if value.kind != "int":
                raise _Unsupported
            result = self.temporary()
            setter = self.at(f"native_set(&mut {values.code}, {offset}, {result})", node)
            return f"let {offset} = {self.number(index)};\nlet {old} = {getter};\nlet {result} = {value.code};\n{setter};", environment
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            left = self.expression(node.target, environment)
            if left.kind == "list_int":
                raise _Unsupported
            right = self.expression(node.value, environment)
            value = self.binary(node.op, left, right, node)
            name = self.bind(node.target.id, value.kind)
            environment[node.target.id] = value.kind
            return f"{name} = {value.code};", environment
        if isinstance(node, ast.If):
            test = self.expression(node.test, environment)
            yes, yes_environment = self.statements(node.body, environment)
            no, no_environment = self.statements(node.orelse, environment)
            return f"if {self.truth(test)} {{\n{yes}\n}} else {{\n{no}\n}}", self.join(yes_environment, no_environment)
        if isinstance(node, (ast.For, ast.While)):
            if node.orelse:
                raise _Unsupported
            label = self.temporary()
            if isinstance(node, ast.While):
                test = self.expression(node.test, environment)
                self.loops.append(label)
                body, _ = self.statements(node.body, environment)
                self.loops.pop()
                return f"'{label}: while {self.truth(test)} {{\n{body}\n}}", environment
            if not isinstance(node.target, ast.Name):
                raise _Unsupported
            is_range = isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range"
            list_name = None
            if is_range:
                setup, iterator, arguments = self.range_iterator(node.iter, environment)
                nonempty = False
                initial = self.literal(0)
                if all(argument.constant is not None for argument in arguments):
                    start, stop, step = (int(argument.constant) for argument in arguments)
                    nonempty = (step > 0 and start < stop) or (step < 0 and start > stop)
                    initial = self.literal(start)
            else:
                values = self.expression(node.iter, environment)
                if values.kind != "list_int":
                    raise _Unsupported
                if isinstance(node.iter, ast.Name):
                    list_name = node.iter.id
                    setup = ""
                    iterator = f"{values.code}.iter().copied()"
                elif values.owned:
                    iterable = self.temporary()
                    setup = f"let {iterable} = {values.code};"
                    iterator = f"{iterable}.into_iter()"
                else:
                    raise _Unsupported
                nonempty = values.length is not None and values.length > 0
                initial = self.literal(0)
            target = self.bind(node.target.id, "int")
            inside = environment.copy()
            inside[node.target.id] = "int"
            self.loops.append(label)
            if list_name is not None:
                self.iterating_lists.append(list_name)
            body, _ = self.statements(node.body, inside)
            if list_name is not None:
                self.iterating_lists.pop()
            self.loops.pop()
            item = self.temporary()
            code = f"{setup}\n'{label}: for {item} in {iterator} {{\n{target} = {item};\n{body}\n}}"
            if nonempty:
                # This initialization is unobservable: the proved nonempty
                # loop assigns its actual first item before any body operation.
                if node.target.id not in environment:
                    code = f"{target} = {initial};\n" + code
                environment[node.target.id] = "int"
            return code, environment
        if isinstance(node, (ast.Break, ast.Continue)) and self.loops:
            return f"{'break' if isinstance(node, ast.Break) else 'continue'} '{self.loops[-1]};", None
        if isinstance(node, ast.Expr):
            call = node.value
            if isinstance(call, ast.Constant) and type(call.value) is str:
                return ";", environment
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "print":
                separator, end = " ", "\n"
                seen = set()
                for keyword in call.keywords:
                    if keyword.arg not in {"sep", "end"} or keyword.arg in seen or not isinstance(keyword.value, ast.Constant) or type(keyword.value.value) is not str:
                        raise _Unsupported
                    seen.add(keyword.arg)
                    if keyword.arg == "sep": separator = keyword.value.value
                    else: end = keyword.value.value
                values = [self.expression(argument, environment) for argument in call.args]
                if any(value.kind not in {"int", "bool"} for value in values):
                    raise _Unsupported
                names = [self.temporary() for _ in values]
                lines = [f"let {name} = {value.code};" for name, value in zip(names, values)]
                for index, (name, value) in enumerate(zip(names, values)):
                    if index:
                        lines.append(f"native_output.push_str({_string(separator)});")
                    formatted = name if value.kind == "int" else f'(if {name} {{ "True" }} else {{ "False" }})'
                    lines.append(f'write!(&mut native_output, "{{}}", {formatted}).unwrap();')
                lines.append(f"native_output.push_str({_string(end)});")
                return "\n".join(lines), environment
            expression = self.expression(call, environment)
            return f"let _ = {'&(' + expression.code + ')' if expression.kind == 'list_int' and not expression.owned else expression.code};", environment
        raise _Unsupported


def try_generate_native(source: str, filename: str, integer: str) -> str | None:
    """Return standalone scalar/list Rust, or None when semantic proof fails.

    This backend implements the wrapping fixed-width integer modes. BigInt and
    programs requiring runtime Python objects use the general backend.
    """
    if integer not in {"i64", "i128"}:
        return None
    try:
        tree = ast.parse(source, filename=filename)
        symtable.symtable(source, filename, "exec")
        # Builtins cannot be rebound even on a path that seems unreachable.
        if any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in _Generator.BUILTINS for node in ast.walk(tree)):
            return None
        generator = _Generator(64 if integer == "i64" else 128)
        body, _ = generator.statements(tree.body, {})
    except (SyntaxError, _Unsupported, RecursionError):
        return None
    runtime = files("py2fastrust").joinpath("runtime")
    notice = runtime.joinpath("NOTICE.txt").read_text(encoding="utf-8")
    result = [
        "// Generated by py2fastrust: native scalar AOT backend.\n"
        "#![allow(dead_code, unused_imports, unused_variables, unused_mut, unused_assignments, unused_parens, unused_labels)]\n",
        f"const INT_BITS: u32 = {generator.bits};\ntype NativeInt = {integer};\n",
        "/*\n" + notice + "\n*/\n",
        _HELPERS,
    ]
    if generator.needs_integer_runtime:
        result.append(runtime.joinpath("integer.rs").read_text(encoding="utf-8"))
    if generator.has_input:
        result.append(_INPUT_HELPERS)
    if generator.has_lists:
        result.append(_LIST_HELPERS)
    result.append("fn main() {\nuse std::fmt::Write as _;\nuse std::io::Write as _;\n"
                  "let mut native_output = String::new();\n"
                  "let native_result = (|| -> Result<(), NativeError> {\n")
    if generator.has_input:
        result.append("let mut native_input = native_at(NativeInput::new(), 1)?;\n")
    for name, kind in generator.bindings.items():
        rust_type = {"int": "NativeInt", "bool": "bool", "list_int": "Vec<NativeInt>"}[kind]
        result.append(f"let mut {generator.names[name]}: {rust_type};\n")
    result.append(body + "\nOk(())\n})();\n")
    result.append("std::io::stdout().write_all(native_output.as_bytes()).unwrap();\n")
    result.append("if let Err(error) = native_result {\n"
                  f'eprintln!("Traceback (most recent call last):\\n  File {{:?}}, line {{}}, in <module>\\n{{}}", {_string(filename)}, error.line, error.message);\n'
                  "std::process::exit(1);\n}\n}\n")
    return "\n".join(result)
