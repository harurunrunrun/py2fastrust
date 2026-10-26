"""Conservative scalar/container AOT lowering; unproved programs use the VM.

The analysis tracks definite bindings along normal control-flow paths and one
stable scalar or uniquely owned integer-container type for every name. No user expression is executed during
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
    nonempty: bool = False


@dataclass(frozen=True)
class _ListInfo:
    length: int | None


@dataclass(frozen=True)
class _DictInfo:
    length: int | None
    nonempty: bool = False


@dataclass(frozen=True)
class _SetInfo:
    length: int | None


@dataclass
class _Function:
    node: ast.FunctionDef
    rust_name: str
    positional: list[str]
    posonly: set[str]
    kwonly: list[str]
    defaults: dict[str, str]
    local_names: set[str]
    return_kind: str
    dependencies: set[str]
    required: set[str]


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
struct NativeError { message: String, line: usize, function: &'static str, frames: Vec<(usize, &'static str)> }
fn native_at<T>(result: Result<T, String>, line: usize, function: &'static str) -> Result<T, NativeError> {
    result.map_err(|message| NativeError { message, line, function, frames: Vec::new() })
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
struct NativeInput { text: String, position: usize, loaded: bool }
impl NativeInput {
    fn new() -> Self {
        Self { text: String::new(), position: 0, loaded: false }
    }
    fn line(&mut self) -> Result<&str, String> {
        if !self.loaded {
            use std::io::Read;
            // Decoding is an input operation, so earlier print calls must be
            // observable even when the input is not valid UTF-8.
            std::io::stdin().read_to_string(&mut self.text).map_err(|error| {
                let kind = if error.kind() == std::io::ErrorKind::InvalidData { "UnicodeDecodeError" } else { "OSError" };
                format!("{}: {}", kind, error)
            })?;
            self.loaded = true;
        }
        if self.position == self.text.len() { return Err("EOFError: EOF when reading a line".into()); }
        let start = self.position;
        let bytes = self.text.as_bytes();
        while self.position < bytes.len() && bytes[self.position] != b'\n' { self.position += 1; }
        let end = self.position;
        if self.position < bytes.len() { self.position += 1; }
        Ok(&self.text[start..end])
    }
    fn integer(&mut self) -> Result<NativeInt, String> {
        native_parse_integer(self.line()?)
    }
    fn integers(&mut self) -> Result<Vec<NativeInt>, String> {
        self.line()?.split(native_space).filter(|word| !word.is_empty())
            .map(native_parse_integer).collect()
    }
    fn unpack_integers(&mut self, count: usize) -> Result<Vec<NativeInt>, String> {
        let mut words = self.line()?.split(native_space).filter(|word| !word.is_empty());
        let mut result = Vec::with_capacity(count);
        for index in 0..count {
            let word = words.next().ok_or_else(|| format!("ValueError: not enough values to unpack (expected {}, got {})", count, index))?;
            result.push(native_parse_integer(word)?);
        }
        if let Some(word) = words.next() {
            // Unpacking asks a lazy map for precisely one extra item. Later
            // invalid tokens must not replace the too-many-values error.
            native_parse_integer(word)?;
            return Err(format!("ValueError: too many values to unpack (expected {})", count));
        }
        Ok(result)
    }
}
fn native_space(character: char) -> bool {
    character.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&character)
}
#[inline]
fn native_parse_integer(word: &str) -> Result<NativeInt, String> {
    // Decimal contest input avoids arbitrary-precision temporaries entirely.
    // Accumulating with wrapping operations equals normalization of the full
    // mathematical integer, including literals longer than the machine width.
    if word.is_ascii() {
        let word = word.trim_matches(|c: char| c.is_ascii_whitespace());
        let bytes = word.as_bytes();
        let negative = bytes.first() == Some(&b'-');
        let digits = if negative || bytes.first() == Some(&b'+') { &bytes[1..] } else { bytes };
        let mut value: NativeInt = 0;
        let mut preceding_digit = false;
        let mut valid = true;
        for &byte in digits {
            if byte.is_ascii_digit() {
                value = value.wrapping_mul(10).wrapping_add((byte - b'0') as NativeInt);
                preceding_digit = true;
            } else if byte == b'_' && preceding_digit { preceding_digit = false; }
            else { valid = false; break; }
        }
        if valid && preceding_digit { return Ok(if negative { value.wrapping_neg() } else { value }); }
    }
    Int::parse(word, 10).map(|n| n.to_i128().unwrap() as NativeInt)
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
fn native_unpack_length(length: usize, count: usize) -> Result<(), String> {
    if length < count { Err(format!("ValueError: not enough values to unpack (expected {}, got {})", count, length)) }
    else if length > count { Err(format!("ValueError: too many values to unpack (expected {})", count)) }
    else { Ok(()) }
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


_DICT_HELPERS = r'''
// Values are scalars and every dictionary has one proved owner. Entries retain
// Python insertion order while the hash index provides expected O(1) lookup.
struct NativeDict {
    entries: Vec<(NativeInt, NativeInt)>,
    index: std::collections::HashMap<NativeInt, usize>,
}
impl NativeDict {
    fn new() -> Self {
        Self { entries: Vec::new(), index: std::collections::HashMap::new() }
    }
    #[inline]
    fn len(&self) -> usize { self.entries.len() }
    #[inline]
    fn is_empty(&self) -> bool { self.entries.is_empty() }
    #[inline]
    fn contains(&self, key: NativeInt) -> bool { self.index.contains_key(&key) }
    #[inline]
    fn get(&self, key: NativeInt, default: NativeInt) -> NativeInt {
        self.index.get(&key).map_or(default, |&index| self.entries[index].1)
    }
    #[inline]
    fn item(&self, key: NativeInt) -> Result<NativeInt, String> {
        self.index.get(&key).map(|&index| self.entries[index].1)
            .ok_or_else(|| format!("KeyError: {}", key))
    }
    #[inline]
    fn set(&mut self, key: NativeInt, value: NativeInt) {
        match self.index.entry(key) {
            std::collections::hash_map::Entry::Occupied(entry) => self.entries[*entry.get()].1 = value,
            std::collections::hash_map::Entry::Vacant(entry) => {
                entry.insert(self.entries.len());
                self.entries.push((key, value));
            }
        }
    }
}
'''


_SET_HELPERS = r'''
// Only exact integer keys and unobservable iteration order reach this type.
type NativeSet = std::collections::HashSet<NativeInt>;
#[inline]
fn native_set_remove(values: &mut NativeSet, key: NativeInt) -> Result<(), String> {
    if values.remove(&key) { Ok(()) } else { Err(format!("KeyError: {}", key)) }
}
'''


class _Generator:
    BUILTINS = {"int", "input", "print", "range", "abs", "pow", "len", "sum", "list", "map", "dict", "set"}

    def __init__(self, bits, functions=None, function=None, function_input=False):
        self.bits = bits
        self.bindings = {}
        self.names = {}
        self.counter = 0
        self.loops = []
        self.needs_integer_runtime = False
        self.has_input = False
        self.has_lists = False
        self.has_dicts = False
        self.has_sets = False
        self.iterating_lists = []
        self.return_label = None
        self.functions = functions or {}
        self.function = function
        self.function_input = function_input

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
        if (kind not in {"int", "bool", "list_int", "dict_int", "set_int"}
                or name in self.BUILTINS or self.bindings.get(name, kind) != kind):
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
        if expression.kind in {"list_int", "dict_int", "set_int"}:
            return f"!({expression.code}).is_empty()"
        if expression.kind not in {"int", "bool"}:
            raise _Unsupported
        return expression.code if expression.kind == "bool" else f"(({expression.code}) != 0)"

    @staticmethod
    def binding(expression):
        if expression.kind == "list_int":
            return _ListInfo(expression.length)
        if expression.kind == "dict_int":
            return _DictInfo(expression.length, expression.nonempty)
        if expression.kind == "set_int":
            return _SetInfo(expression.length)
        return expression.kind

    @staticmethod
    def consume_list(expression):
        return expression.code if expression.owned else f"({expression.code}).clone()"

    def at(self, code, node):
        scope = self.function.node.name if self.function else "<module>"
        return f"native_at({code}, {node.lineno}, {_string(scope)})?"

    @staticmethod
    def input_words(node):
        if not (isinstance(node, ast.Call) and not node.args and not node.keywords
                and isinstance(node.func, ast.Attribute) and node.func.attr == "split"):
            return False
        source = node.func.value
        return (isinstance(source, ast.Call) and isinstance(source.func, ast.Name)
                and source.func.id == "input" and not source.args and not source.keywords)

    def input_map(self, node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "map" and len(node.args) == 2 and not node.keywords
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "int"
                and self.input_words(node.args[1]))

    def integer_input_list(self, node):
        self.needs_integer_runtime = self.has_input = self.has_lists = True
        return _Expression(self.at("native_input.integers()", node), "list_int")

    def dict_view(self, node, environment):
        """Recognize an immediate view consumer; views never become variables."""
        if (not isinstance(node, ast.Call) or node.args or node.keywords
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr not in {"keys", "values", "items"}):
            return None
        value = self.expression(node.func.value, environment)
        if value.kind != "dict_int":
            raise _Unsupported
        return value, node.func.attr, node.func.value

    def set_iterable(self, node, environment):
        """Return a proved exact-int iterator for a fresh set or update.

        General set iteration remains unsupported: these consumers cannot
        observe order, invoke user code, or mutate their input during iteration.
        """
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "range"):
            setup, iterator, _ = self.range_iterator(node, environment)
            return setup, iterator
        if isinstance(node, (ast.List, ast.Tuple)):
            values = [self.expression(value, environment) for value in node.elts]
            if any(value.kind != "int" for value in values):
                raise _Unsupported
            name = self.temporary()
            # The ephemeral sequence never escapes. A stack array preserves
            # argument evaluation before mutation without allocating a Vec.
            setup = f"let {name}: [NativeInt; {len(values)}] = [" + ", ".join(value.code for value in values) + "];"
            return setup, f"{name}.into_iter()"
        value = self.expression(node, environment)
        if value.kind not in {"list_int", "set_int", "dict_int"}:
            raise _Unsupported
        name = self.temporary()
        binding = value.code if value.owned else f"&({value.code})"
        setup = f"let {name} = {binding};"
        if value.kind == "dict_int":
            iterator = f"{name}.entries.iter().map(|&(key, _)| key)"
        else:
            iterator = f"{name}.iter().copied()"
        return setup, iterator

    def user_call(self, node, function, environment):
        if self.function is None:
            # A callee's globals are looked up at call time, including indirect
            # callees whose definitions may follow the caller definition.
            if any(not isinstance(environment.get(name), _Function) for name in function.required):
                raise _Unsupported
        else:
            self.function.dependencies.add(function.node.name)
        if any(isinstance(value, ast.Starred) for value in node.args):
            raise _Unsupported
        lines, bound = [], {}
        if len(node.args) > len(function.positional):
            raise _Unsupported
        # Evaluate every explicit argument in source order before reordering
        # into Rust's fixed signature. Defaults are proved pure constants.
        for parameter, argument in zip(function.positional, node.args):
            value = self.expression(argument, environment)
            if value.kind != "int":
                raise _Unsupported
            name = self.temporary()
            lines.append(f"let {name} = {value.code};")
            bound[parameter] = name
        for keyword in node.keywords:
            parameter = keyword.arg
            if (parameter is None or parameter in function.posonly or parameter in bound
                    or parameter not in function.positional + function.kwonly):
                raise _Unsupported
            value = self.expression(keyword.value, environment)
            if value.kind != "int":
                raise _Unsupported
            name = self.temporary()
            lines.append(f"let {name} = {value.code};")
            bound[parameter] = name
        arguments = []
        for parameter in function.positional + function.kwonly:
            code = bound.get(parameter, function.defaults.get(parameter))
            if code is None:
                raise _Unsupported
            arguments.append(code)
        if self.function_input:
            arguments.append("&mut native_input")
        arguments.append("&mut native_output")
        scope = self.function.node.name if self.function else "<module>"
        call = f"{function.rust_name}({', '.join(arguments)})"
        call += f".map_err(|mut error| {{ error.frames.push(({node.lineno}, {_string(scope)})); error }})?"
        return _Expression("{ " + " ".join(lines) + f" {call} }}", function.return_kind)

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
            if isinstance(information, _Function):
                raise _Unsupported
            if isinstance(information, _ListInfo):
                return _Expression(self.names[node.id], "list_int", owned=False, length=information.length)
            if isinstance(information, _DictInfo):
                return _Expression(self.names[node.id], "dict_int", owned=False, length=information.length, nonempty=information.nonempty)
            if isinstance(information, _SetInfo):
                return _Expression(self.names[node.id], "set_int", owned=False, length=information.length)
            return _Expression(self.names[node.id], information)
        if isinstance(node, ast.List):
            values = [self.expression(value, environment) for value in node.elts]
            if any(value.kind != "int" for value in values):
                raise _Unsupported
            self.has_lists = True
            return _Expression("vec![" + ", ".join(value.code for value in values) + "]", "list_int", length=len(values))
        if isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise _Unsupported
            pairs = [(self.expression(key, environment), self.expression(value, environment))
                     for key, value in zip(node.keys, node.values)]
            if any(key.kind != "int" or value.kind != "int" for key, value in pairs):
                raise _Unsupported
            self.has_dicts = True
            result = self.temporary()
            lines = [f"let mut {result} = NativeDict::new();"]
            for key, value in pairs:
                key_name, value_name = self.temporary(), self.temporary()
                lines += [f"let {key_name} = {key.code};", f"let {value_name} = {value.code};",
                          f"{result}.set({key_name}, {value_name});"]
            length = len({key.constant for key, _ in pairs}) if all(key.constant is not None for key, _ in pairs) else None
            return _Expression("{ " + " ".join(lines) + f" {result} }}", "dict_int", length=length, nonempty=bool(pairs))
        if isinstance(node, ast.Set):
            values = [self.expression(value, environment) for value in node.elts]
            if any(value.kind != "int" for value in values):
                raise _Unsupported
            self.has_sets = True
            result = self.temporary()
            lines = [f"let mut {result} = NativeSet::new();"]
            for value in values:
                item = self.temporary()
                lines += [f"let {item} = {value.code};", f"{result}.insert({item});"]
            length = len({value.constant for value in values}) if all(value.constant is not None for value in values) else None
            return _Expression("{ " + " ".join(lines) + f" {result} }}", "set_int", length=length)
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                raise _Unsupported
            values = self.expression(node.value, environment)
            if values.kind not in {"list_int", "dict_int"}:
                raise _Unsupported
            index = self.expression(node.slice, environment)
            if values.kind == "dict_int":
                if index.kind != "int":
                    raise _Unsupported
                dictionary, key = self.temporary(), self.temporary()
                binding = values.code if values.owned else f"&({values.code})"
                lookup = self.at(f"{dictionary}.item({key})", node)
                return _Expression(f"{{ let {dictionary} = {binding}; let {key} = {index.code}; {lookup} }}", "int")
            return _Expression(self.at(f"native_get(&({values.code}), {self.number(index)})", node), "int")
        if isinstance(node, ast.ListComp):
            if len(node.generators) == 1:
                gen = node.generators[0]
                if (not gen.is_async and not gen.ifs and isinstance(gen.target, ast.Name)
                        and self.input_words(gen.iter) and isinstance(node.elt, ast.Call)
                        and isinstance(node.elt.func, ast.Name) and node.elt.func.id == "int"
                        and not node.elt.keywords and len(node.elt.args) == 1
                        and isinstance(node.elt.args[0], ast.Name)
                        and node.elt.args[0].id == gen.target.id):
                    return self.integer_input_list(node)
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
            if len({value.kind for value in values}) != 1 or values[0].kind in {"list_int", "dict_int", "set_int"}:
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
            if len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)):
                if values[1].kind not in {"dict_int", "set_int"}:
                    raise _Unsupported
                if values[1].kind == "set_int" and values[0].kind != "int":
                    raise _Unsupported
                key, dictionary = self.temporary(), self.temporary()
                binding = values[1].code if values[1].owned else f"&({values[1].code})"
                argument = f"&{key}" if values[1].kind == "set_int" else key
                check = f"{dictionary}.contains({argument})"
                if isinstance(node.ops[0], ast.NotIn):
                    check = f"!{check}"
                return _Expression(f"{{ let {key} = {self.number(values[0])}; let {dictionary} = {binding}; {check} }}", "bool")
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
            if yes.kind in {"list_int", "dict_int", "set_int"}:
                raise _Unsupported
            return _Expression(f"(if {self.truth(test)} {{ {yes.code} }} else {{ {no.code} }})", yes.kind)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name == "set" and len(node.args) <= 1:
                self.has_sets = True
                if not node.args:
                    return _Expression("NativeSet::new()", "set_int", length=0)
                setup, iterator = self.set_iterable(node.args[0], environment)
                return _Expression(f"{{ {setup} ({iterator}).collect::<NativeSet>() }}", "set_int")
            if name == "dict" and not node.args:
                self.has_dicts = True
                return _Expression("NativeDict::new()", "dict_int", length=0)
            if name == "list" and not node.args:
                self.has_lists = True
                return _Expression("Vec::<NativeInt>::new()", "list_int", length=0)
            if name == "list" and len(node.args) == 1 and self.input_map(node.args[0]):
                return self.integer_input_list(node)
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
                view = self.dict_view(node.args[0], environment)
                value = view[0] if view else self.expression(node.args[0], environment)
                if value.kind not in {"list_int", "dict_int", "set_int"}:
                    raise _Unsupported
                return _Expression(f"(({value.code}).len() as NativeInt)", "int", value.length)
            if name == "sum" and len(node.args) in (1, 2):
                view = self.dict_view(node.args[0], environment)
                value = view[0] if view else self.expression(node.args[0], environment)
                if value.kind not in {"list_int", "dict_int", "set_int"} or (view and view[1] == "items"):
                    raise _Unsupported
                start = self.expression(node.args[1], environment) if len(node.args) == 2 else _Expression(self.literal(0), "int", 0)
                if start.kind != "int":
                    raise _Unsupported
                values_name, start_name = self.temporary(), self.temporary()
                # Borrow a named list, own a temporary list; evaluate start only
                # after evaluating the iterable, as Python does.
                binding = value.code if value.owned else f"&({value.code})"
                iterator = f"{values_name}.iter()"
                pattern = "&value"
                if value.kind == "dict_int":
                    iterator = f"{values_name}.entries.iter()"
                    pattern = "&(_, value)" if view and view[1] == "values" else "&(value, _)"
                code = f"{{ let {values_name} = {binding}; let {start_name} = {self.number(start)}; {iterator}.fold({start_name}, |acc, {pattern}| acc.wrapping_add(value)) }}"
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
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            function = environment.get(node.func.id)
            if isinstance(function, _Function):
                return self.user_call(node, function, environment)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) == 2 and not node.keywords):
            values = self.expression(node.func.value, environment)
            key = self.expression(node.args[0], environment)
            default = self.expression(node.args[1], environment)
            if values.kind != "dict_int" or default.kind != "int":
                raise _Unsupported
            dictionary, key_name, default_name = self.temporary(), self.temporary(), self.temporary()
            binding = values.code if values.owned else f"&({values.code})"
            code = f"{{ let {dictionary} = {binding}; let {key_name} = {self.number(key)}; let {default_name} = {default.code}; {dictionary}.get({key_name}, {default_name}) }}"
            return _Expression(code, "int")
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
        result = {}
        for name, kind in first.items():
            other = second.get(name)
            if isinstance(kind, _ListInfo) and isinstance(other, _ListInfo):
                result[name] = kind if kind == other else _ListInfo(None)
            elif isinstance(kind, _DictInfo) and isinstance(other, _DictInfo):
                result[name] = kind if kind == other else _DictInfo(None, kind.nonempty and other.nonempty)
            elif isinstance(kind, _SetInfo) and isinstance(other, _SetInfo):
                result[name] = kind if kind == other else _SetInfo(None)
            elif other == kind:
                result[name] = kind
        return result

    @staticmethod
    def after_loop(environment):
        # A body can resize or replace a list on any normal/break/continue
        # path. Its pre-loop cardinality is no longer a valid proof.
        return {name: _ListInfo(None) if isinstance(kind, _ListInfo)
                else _DictInfo(None) if isinstance(kind, _DictInfo)
                else _SetInfo(None) if isinstance(kind, _SetInfo) else kind
                for name, kind in environment.items()}

    def statement(self, node, environment):
        if isinstance(node, ast.FunctionDef):
            function = self.functions.get(node.name)
            if self.function is not None or function is None or function.node is not node:
                raise _Unsupported
            environment[node.name] = function
            return "", environment
        if isinstance(node, ast.Return) and self.function is not None:
            if self.function.return_kind == "none":
                if node.value is not None and not (isinstance(node.value, ast.Constant) and node.value.value is None):
                    raise _Unsupported
                return "return Ok(());", None
            if node.value is None:
                raise _Unsupported
            value = self.expression(node.value, environment)
            if value.kind != "int":
                raise _Unsupported
            return f"return Ok({value.code});", None
        if isinstance(node, ast.Return) and self.return_label is not None:
            lines = []
            if node.value is not None and not isinstance(node.value, ast.Constant):
                expression = ast.copy_location(ast.Expr(value=node.value), node)
                rendered, _ = self.statement(expression, environment)
                lines.append(rendered)
            lines.append(f"break '{self.return_label};")
            return "\n".join(lines), None
        if isinstance(node, ast.Pass):
            return ";", environment
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1 and isinstance(node.targets[0], (ast.Tuple, ast.List)):
                targets = node.targets[0].elts
                if not all(isinstance(target, ast.Name) and target.id not in self.iterating_lists for target in targets):
                    raise _Unsupported
                count = len(targets)
                name = self.temporary()
                if self.input_map(node.value):
                    self.needs_integer_runtime = self.has_input = True
                    value_code = self.at(f"native_input.unpack_integers({count})", node)
                    lines = [f"let {name} = {value_code};"]
                else:
                    value = self.expression(node.value, environment)
                    if value.kind != "list_int":
                        raise _Unsupported
                    lines = [f"let {name} = {value.code if value.owned else '&' + value.code};"]
                    check = f'native_unpack_length({name}.len(), {count})'
                    lines.append(f"{self.at(check, node)};")
                # Check all cardinality/conversion errors before binding any
                # target. Scalar copies cannot introduce list aliases.
                for index, target in enumerate(targets):
                    lines.append(f"{self.bind(target.id, 'int')} = {name}[{index}];")
                    environment[target.id] = "int"
                return "\n".join(lines), environment
            value = self.expression(node.value, environment)
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
                target = node.targets[0]
                if value.kind != "int" or not isinstance(target.value, ast.Name) or target.value.id in self.iterating_lists:
                    raise _Unsupported
                values = self.expression(target.value, environment)
                if values.kind not in {"list_int", "dict_int"} or isinstance(target.slice, ast.Slice):
                    raise _Unsupported
                index = self.expression(target.slice, environment)
                result, offset = self.temporary(), self.temporary()
                if values.kind == "dict_int":
                    if index.kind != "int":
                        raise _Unsupported
                    environment[target.value.id] = _DictInfo(None, True)
                    return f"let {result} = {value.code};\nlet {offset} = {index.code};\n{values.code}.set({offset}, {result});", environment
                setter = self.at(f"native_set(&mut {values.code}, {offset}, {result})", node)
                return f"let {result} = {value.code};\nlet {offset} = {self.number(index)};\n{setter};", environment
            if not all(isinstance(target, ast.Name) and target.id not in self.iterating_lists for target in node.targets):
                raise _Unsupported
            if value.kind in {"list_int", "dict_int", "set_int"} and (not value.owned or len(node.targets) != 1):
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
            if values.kind not in {"list_int", "dict_int"}:
                raise _Unsupported
            index = self.expression(target.slice, environment)
            offset, old = self.temporary(), self.temporary()
            if values.kind == "dict_int" and index.kind != "int":
                raise _Unsupported
            getter = self.at(f"{values.code}.item({offset})" if values.kind == "dict_int"
                             else f"native_get(&{values.code}, {offset})", target)
            right = self.expression(node.value, environment)
            value = self.binary(node.op, _Expression(old, "int"), right, node)
            if value.kind != "int":
                raise _Unsupported
            result = self.temporary()
            if values.kind == "dict_int":
                return f"let {offset} = {index.code};\nlet {old} = {getter};\nlet {result} = {value.code};\n{values.code}.set({offset}, {result});", environment
            setter = self.at(f"native_set(&mut {values.code}, {offset}, {result})", node)
            return f"let {offset} = {self.number(index)};\nlet {old} = {getter};\nlet {result} = {value.code};\n{setter};", environment
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            left = self.expression(node.target, environment)
            if left.kind in {"list_int", "dict_int", "set_int"}:
                raise _Unsupported
            right = self.expression(node.value, environment)
            value = self.binary(node.op, left, right, node)
            name = self.bind(node.target.id, value.kind)
            environment[node.target.id] = value.kind
            return f"{name} = {value.code};", environment
        if isinstance(node, ast.If):
            if self.function is None and self.functions and _main_guard(node):
                return self.statements(node.body, environment)
            test = self.expression(node.test, environment)
            yes, yes_environment = self.statements(node.body, environment)
            no, no_environment = self.statements(node.orelse, environment)
            return f"if {self.truth(test)} {{\n{yes}\n}} else {{\n{no}\n}}", self.join(yes_environment, no_environment)
        if isinstance(node, (ast.For, ast.While)):
            if node.orelse:
                raise _Unsupported
            label = self.temporary()
            if isinstance(node, ast.While):
                # Subsequent iterations may see containers resized or replaced
                # by the body. Their entry cardinality is not a loop invariant.
                widened = self.after_loop(environment)
                test = self.expression(node.test, widened)
                self.loops.append(label)
                body, _ = self.statements(node.body, widened)
                self.loops.pop()
                return f"'{label}: while {self.truth(test)} {{\n{body}\n}}", self.after_loop(environment)
            is_range = isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range"
            list_name = None
            item_pair = False
            if is_range:
                if not isinstance(node.target, ast.Name):
                    raise _Unsupported
                setup, iterator, arguments = self.range_iterator(node.iter, environment)
                nonempty = False
                initial = self.literal(0)
                if all(argument.constant is not None for argument in arguments):
                    start, stop, step = (int(argument.constant) for argument in arguments)
                    nonempty = (step > 0 and start < stop) or (step < 0 and start > stop)
                    initial = self.literal(start)
            else:
                view = self.dict_view(node.iter, environment)
                values = view[0] if view else self.expression(node.iter, environment)
                if values.kind not in {"list_int", "dict_int"}:
                    raise _Unsupported
                receiver = view[2] if view else node.iter
                if isinstance(receiver, ast.Name):
                    list_name = receiver.id
                    setup = ""
                    iterable = values.code
                    borrowed = True
                elif values.owned:
                    iterable = self.temporary()
                    setup = f"let {iterable} = {values.code};"
                    borrowed = False
                else:
                    raise _Unsupported
                if values.kind == "dict_int":
                    iterator = f"{iterable}.entries.{'iter().copied()' if borrowed else 'into_iter()'}"
                    kind = view[1] if view else "keys"
                    if kind == "items":
                        item_pair = True
                    else:
                        iterator += ".map(|(key, value)| " + ("value" if kind == "values" else "key") + ")"
                    nonempty = values.nonempty
                else:
                    iterator = f"{iterable}.{'iter().copied()' if borrowed else 'into_iter()'}"
                    nonempty = values.length is not None and values.length > 0
                initial = self.literal(0)
            if item_pair:
                if (not isinstance(node.target, (ast.Tuple, ast.List)) or len(node.target.elts) != 2
                        or not all(isinstance(target, ast.Name) for target in node.target.elts)
                        or len({target.id for target in node.target.elts}) != 2):
                    raise _Unsupported
                targets = node.target.elts
            else:
                if not isinstance(node.target, ast.Name):
                    raise _Unsupported
                targets = [node.target]
            if any(target.id in self.iterating_lists for target in targets):
                raise _Unsupported
            target_names = [self.bind(target.id, "int") for target in targets]
            inside = self.after_loop(environment)
            for target in targets:
                inside[target.id] = "int"
            self.loops.append(label)
            if list_name is not None:
                self.iterating_lists.append(list_name)
            body, _ = self.statements(node.body, inside)
            if list_name is not None:
                self.iterating_lists.pop()
            self.loops.pop()
            item = self.temporary()
            assignments = "\n".join(f"{target} = {item}.{index};" if item_pair else f"{target} = {item};"
                                    for index, target in enumerate(target_names))
            code = f"{setup}\n'{label}: for {item} in {iterator} {{\n{assignments}\n{body}\n}}"
            if nonempty:
                # This initialization is unobservable: the proved nonempty
                # loop assigns its actual first item before any body operation.
                for target, name in zip(targets, target_names):
                    if target.id not in environment:
                        code = f"{name} = {initial};\n" + code
                    environment[target.id] = "int"
            return code, self.after_loop(environment)
        if isinstance(node, (ast.Break, ast.Continue)) and self.loops:
            return f"{'break' if isinstance(node, ast.Break) else 'continue'} '{self.loops[-1]};", None
        if isinstance(node, ast.Expr):
            call = node.value
            if isinstance(call, ast.Constant) and type(call.value) is str:
                return ";", environment
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)):
                target = call.func.value
                values = self.expression(target, environment)
                if values.kind == "set_int":
                    if call.keywords:
                        raise _Unsupported
                    method = call.func.attr
                    if method == "clear" and not call.args:
                        environment[target.id] = _SetInfo(0)
                        return f"{values.code}.clear();", environment
                    if method in {"add", "discard", "remove"} and len(call.args) == 1:
                        argument = self.expression(call.args[0], environment)
                        if argument.kind != "int":
                            raise _Unsupported
                        item = self.temporary()
                        if method == "add":
                            action = f"{values.code}.insert({item})"
                        elif method == "discard":
                            action = f"{values.code}.remove(&{item})"
                        else:
                            action = self.at(f"native_set_remove(&mut {values.code}, {item})", node)
                        environment[target.id] = _SetInfo(None)
                        return f"let {item} = {argument.code};\n{action};", environment
                    if method == "update" and len(call.args) <= 1:
                        if not call.args:
                            return ";", environment
                        if isinstance(call.args[0], ast.Name) and call.args[0].id == target.id:
                            return ";", environment
                        setup, iterator = self.set_iterable(call.args[0], environment)
                        item = self.temporary()
                        environment[target.id] = _SetInfo(None)
                        return f"{{ {setup} for {item} in {iterator} {{ {values.code}.insert({item}); }} }}", environment
                    raise _Unsupported
                if values.kind == "dict_int":
                    expression = self.expression(call, environment)
                    return f"let _ = {expression.code};", environment
                if target.id in self.iterating_lists:
                    raise _Unsupported
                if values.kind != "list_int":
                    raise _Unsupported
                method = call.func.attr
                if method == "append" and len(call.args) == 1 and not call.keywords:
                    argument = self.expression(call.args[0], environment)
                    if argument.kind != "int":
                        raise _Unsupported
                    item = self.temporary()
                    environment[target.id] = _ListInfo(None if values.length is None else values.length + 1)
                    return f"let {item} = {argument.code};\n{values.code}.push({item});", environment
                if method == "extend" and len(call.args) == 1 and not call.keywords:
                    argument = self.expression(call.args[0], environment)
                    if argument.kind != "list_int":
                        raise _Unsupported
                    item = self.temporary()
                    # Own a snapshot before the mutable receiver borrow, even
                    # for a.extend(a), preserving Python's self-extension.
                    length = None if values.length is None or argument.length is None else values.length + argument.length
                    environment[target.id] = _ListInfo(length)
                    return f"let {item} = {self.consume_list(argument)};\n{values.code}.extend({item});", environment
                if method == "reverse" and not call.args and not call.keywords:
                    return f"{values.code}.reverse();", environment
                if method == "sort" and not call.args:
                    reverse = False
                    if call.keywords:
                        if (len(call.keywords) != 1 or call.keywords[0].arg != "reverse"
                                or not isinstance(call.keywords[0].value, ast.Constant)
                                or type(call.keywords[0].value.value) is not bool):
                            raise _Unsupported
                        reverse = call.keywords[0].value.value
                    lines = f"{values.code}.sort_unstable();"
                    if reverse:
                        lines += f"\n{values.code}.reverse();"
                    return lines, environment
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
            return f"let _ = {'&(' + expression.code + ')' if expression.kind in {'list_int', 'dict_int', 'set_int'} and not expression.owned else expression.code};", environment
        raise _Unsupported


def _main_guard(node):
    if not isinstance(node, ast.If) or node.orelse:
        return False
    guard = node.test
    if (not isinstance(guard, ast.Compare) or len(guard.ops) != 1
            or not isinstance(guard.ops[0], ast.Eq) or len(guard.comparators) != 1):
        return False
    left, right = guard.left, guard.comparators[0]
    if isinstance(right, ast.Name) and right.id == "__name__":
        left, right = right, left
    return (isinstance(left, ast.Name) and left.id == "__name__"
            and isinstance(right, ast.Constant) and right.value == "__main__")


def _main_wrapper(tree):
    """Find an unobservable, no-argument entry function and its one call.

    The existing native validator still proves the complete function body. An
    exact top-level shape prevents function objects or local namespace changes
    from becoming observable while lowering the entry body to ordinary Rust.
    """
    statements = list(tree.body)
    while statements and isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant) and type(statements[0].value.value) is str:
        statements.pop(0)
    if len(statements) != 2 or not isinstance(statements[0], ast.FunctionDef):
        return tree.body, False
    function, invocation = statements
    parameters = function.args
    if (function.decorator_list or function.returns is not None or getattr(function, "type_params", ())
            or parameters.posonlyargs or parameters.args or parameters.kwonlyargs
            or parameters.vararg is not None or parameters.kwarg is not None
            or parameters.defaults or parameters.kw_defaults
            or function.name in _Generator.BUILTINS | {"__name__", "__builtins__"}):
        return tree.body, False
    if any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(function)):
        return tree.body, False
    if isinstance(invocation, ast.If):
        guard = invocation.test
        if (invocation.orelse or len(invocation.body) != 1 or not isinstance(guard, ast.Compare)
                or len(guard.ops) != 1 or not isinstance(guard.ops[0], ast.Eq)
                or len(guard.comparators) != 1):
            return tree.body, False
        left, right = guard.left, guard.comparators[0]
        if isinstance(right, ast.Name) and right.id == "__name__":
            left, right = right, left
        if not (isinstance(left, ast.Name) and left.id == "__name__"
                and isinstance(right, ast.Constant) and right.value == "__main__"):
            return tree.body, False
        invocation = invocation.body[0]
    if (not isinstance(invocation, ast.Expr) or not isinstance(invocation.value, ast.Call)
            or not isinstance(invocation.value.func, ast.Name)
            or invocation.value.func.id != function.name
            or invocation.value.args or invocation.value.keywords):
        return tree.body, False
    return function.body, (function.name, invocation.lineno)


def _function_plans(tree, table, bits):
    functions = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        parameters = node.args
        arguments = parameters.posonlyargs + parameters.args + parameters.kwonlyargs
        if (node.name in functions or node.name in _Generator.BUILTINS | {"__builtins__", "__name__"}
                or node.decorator_list or node.returns is not None or node.type_params
                or parameters.vararg or parameters.kwarg
                or any(argument.annotation is not None for argument in arguments)
                or any(isinstance(value, (ast.Yield, ast.YieldFrom, ast.Await, ast.AsyncFor, ast.AsyncWith))
                       for value in ast.walk(node))):
            raise _Unsupported
        matches = [child for child in table.get_children()
                   if child.get_name() == node.name and child.get_lineno() == node.lineno]
        if len(matches) != 1:
            raise _Unsupported
        local_names = {symbol.get_name() for symbol in matches[0].get_symbols()
                       if symbol.is_local() or symbol.is_parameter()}
        positional = [argument.arg for argument in parameters.posonlyargs + parameters.args]
        defaults = {}
        default_generator = _Generator(bits)
        default_nodes = list(zip(positional[len(positional)-len(parameters.defaults):], parameters.defaults))
        default_nodes += [(argument.arg, value) for argument, value in zip(parameters.kwonlyargs, parameters.kw_defaults)
                          if value is not None]
        for name, value in default_nodes:
            expression = default_generator.expression(value, {})
            if expression.kind != "int" or expression.constant is None:
                raise _Unsupported
            defaults[name] = default_generator.literal(expression.constant)
        value_returns = [statement for statement in ast.walk(node) if isinstance(statement, ast.Return)
                         and statement.value is not None
                         and not (isinstance(statement.value, ast.Constant) and statement.value.value is None)]
        functions[node.name] = _Function(node, f"native_function_{len(functions)}", positional,
                                        {argument.arg for argument in parameters.posonlyargs},
                                        [argument.arg for argument in parameters.kwonlyargs], defaults,
                                        local_names, "int" if value_returns else "none", set(), set())
    if functions and any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                         and node.id in functions.keys() | {"__builtins__", "__name__"} for node in ast.walk(tree)):
        raise _Unsupported
    return functions


def _function_requirements(functions):
    """Prove an acyclic direct call graph and its late-bound global names.

    Recursive programs retain the VM's recursion limit/stack behavior. Rust
    stack overflow is not a substitute for Python's RecursionError.
    """
    visiting, visited, depths = set(), set(), {}

    def visit(name):
        if name in visiting:
            raise _Unsupported
        if name in visited:
            return functions[name].required
        visiting.add(name)
        required = {name}
        depth = 1
        for dependency in functions[name].dependencies:
            required |= visit(dependency)
            depth = max(depth, depths[dependency] + 1)
        # Even an acyclic graph can exceed Python's default recursion limit.
        # No accepted program can change that limit; stay well below it rather
        # than substituting Rust stack behavior near an unproved boundary.
        if depth > 128:
            raise _Unsupported
        depths[name] = depth
        functions[name].required = required
        visiting.remove(name)
        visited.add(name)
        return required

    for name in functions:
        visit(name)


def _declarations(generator):
    types = {"int": "NativeInt", "bool": "bool", "list_int": "Vec<NativeInt>",
             "dict_int": "NativeDict", "set_int": "NativeSet"}
    return "\n".join(f"let mut {generator.names[name]}: {types[kind]};"
                     for name, kind in generator.bindings.items())


def try_generate_native(source: str, filename: str, integer: str) -> str | None:
    """Return standalone scalar/container Rust, or None when proof fails.

    This backend implements the wrapping fixed-width integer modes. BigInt and
    programs requiring runtime Python objects use the general backend.
    """
    if integer not in {"i64", "i128"}:
        return None
    try:
        tree = ast.parse(source, filename=filename)
        table = symtable.symtable(source, filename, "exec")
        # Builtins cannot be rebound even on a path that seems unreachable.
        if any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in _Generator.BUILTINS for node in ast.walk(tree)):
            return None
        bits = 64 if integer == "i64" else 128
        statements, wrapper = _main_wrapper(tree)
        functions = {} if wrapper else _function_plans(tree, table, bits)
        function_input = bool(functions) and any(isinstance(node, ast.Name) and node.id == "input" for node in ast.walk(tree))
        generator = _Generator(bits, functions, function_input=function_input)
        if function_input:
            generator.has_input = generator.needs_integer_runtime = True
        function_sources = []
        for function in functions.values():
            local = _Generator(bits, functions, function, function_input)
            environment = {name: value for name, value in functions.items() if name not in function.local_names}
            parameters = function.positional + function.kwonly
            initializers = []
            signature = []
            for index, name in enumerate(parameters):
                initializers.append(f"{local.bind(name, 'int')} = native_argument_{index};")
                environment[name] = "int"
                signature.append(f"native_argument_{index}: NativeInt")
            if function_input:
                signature.append("mut native_input: &mut NativeInput")
            signature.append("mut native_output: &mut String")
            function_body, remaining = local.statements(function.node.body, environment)
            if function.return_kind == "int" and remaining is not None:
                raise _Unsupported
            tail = "\nOk(())" if function.return_kind == "none" and remaining is not None else ""
            return_type = "NativeInt" if function.return_kind == "int" else "()"
            function_sources.append(f"#[inline]\nfn {function.rust_name}({', '.join(signature)}) -> Result<{return_type}, NativeError> {{\n"
                                    "use std::fmt::Write as _;\n" + _declarations(local) + "\n"
                                    + "\n".join(initializers) + "\n" + function_body + tail + "\n}")
            for flag in ("needs_integer_runtime", "has_input", "has_lists", "has_dicts", "has_sets"):
                setattr(generator, flag, getattr(generator, flag) or getattr(local, flag))
        _function_requirements(functions)
        if wrapper:
            generator.return_label = "native_entrypoint"
        body, _ = generator.statements(statements, {})
        if wrapper:
            body = f"'native_entrypoint: {{\n{body}\n}}"
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
        unicode_license = files("py2fastrust").joinpath("stdlib", "UNICODE_LICENSE.txt").read_text(encoding="utf-8")
        result.append("\n".join("// " + line for line in unicode_license.splitlines()) + "\n")
        result.append(runtime.joinpath("integer.rs").read_text(encoding="utf-8"))
    if generator.has_input:
        result.append(_INPUT_HELPERS)
    if generator.has_lists:
        result.append(_LIST_HELPERS)
    if generator.has_dicts:
        result.append(_DICT_HELPERS)
    if generator.has_sets:
        result.append(_SET_HELPERS)
    result.extend(function_sources)
    result.append("fn main() {\nuse std::fmt::Write as _;\nuse std::io::Write as _;\n"
                  "let mut native_output = String::new();\n"
                  "let native_result = (|| -> Result<(), NativeError> {\n")
    if generator.has_input:
        result.append("let mut native_input = NativeInput::new();\n")
    result.append(_declarations(generator))
    result.append(body + "\nOk(())\n})();\n")
    result.append("std::io::stdout().write_all(native_output.as_bytes()).unwrap();\n")
    if wrapper:
        function_name, call_line = wrapper
        result.append("if let Err(error) = native_result {\n"
                      f'eprintln!("Traceback (most recent call last):\\n  File {{:?}}, line {call_line}, in <module>\\n  File {{:?}}, line {{}}, in {{}}\\n{{}}", {_string(filename)}, {_string(filename)}, error.line, {_string(function_name)}, error.message);\n'
                      "std::process::exit(1);\n}\n}\n")
    elif functions:
        result.append("if let Err(error) = native_result {\n"
                      'eprintln!("Traceback (most recent call last):");\n'
                      "for &(line, function) in error.frames.iter().rev() {\n"
                      f'eprintln!("  File {{:?}}, line {{}}, in {{}}", {_string(filename)}, line, function);\n'
                      "}\n"
                      f'eprintln!("  File {{:?}}, line {{}}, in {{}}\\n{{}}", {_string(filename)}, error.line, error.function, error.message);\n'
                      "std::process::exit(1);\n}\n}\n")
    else:
        result.append("if let Err(error) = native_result {\n"
                      f'eprintln!("Traceback (most recent call last):\\n  File {{:?}}, line {{}}, in <module>\\n{{}}", {_string(filename)}, error.line, error.message);\n'
                      "std::process::exit(1);\n}\n}\n")
    return "\n".join(result)
