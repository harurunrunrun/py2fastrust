"""Direct Rust generation for proved scalar and container operations.

The analysis tracks definite bindings along control-flow paths. A Python name
can change type by moving to a different typed Rust slot; compatible paths join
through scalar copies or uniquely owned integer-container moves. No user
expression is executed during analysis. Missing direct lowering is reported to
the public API; it never selects a general execution backend.
"""

import ast
from dataclasses import dataclass, field, replace
from importlib.resources import files
import symtable

from .typeflow import TypeSet
from .diagnostics import Diagnostic


class _Unsupported(Exception):
    pass


def _direct_diagnostic(source, filename, error=None, node=None):
    """Locate the innermost AST operation whose direct lowering failed."""
    traceback = getattr(error, "__traceback__", None)
    while traceback is not None:
        candidate = traceback.tb_frame.f_locals.get("node")
        if isinstance(candidate, ast.AST) and hasattr(candidate, "lineno"):
            node = candidate
        traceback = traceback.tb_next
    if node is None:
        try:
            tree = ast.parse(source, filename=filename)
            node = tree.body[0] if tree.body else None
        except (SyntaxError, ValueError, RecursionError):
            pass
    line = getattr(node, "lineno", getattr(error, "lineno", 1) or 1)
    column = (getattr(node, "col_offset", 0) + 1 if node is not None else
              getattr(error, "offset", 1) or 1)
    construct = f" ({type(node).__name__})" if node is not None else ""
    return Diagnostic("direct Rust generation is not implemented for this construct or type combination" + construct,
                      filename, line, column, "E006")


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
class _MatrixInfo:
    length: int | None


@dataclass(frozen=True)
class _DequeInfo:
    length: int | None


@dataclass(frozen=True)
class _DequeConstructor:
    name: str


@dataclass(frozen=True)
class _DictInfo:
    length: int | None
    nonempty: bool = False


@dataclass(frozen=True)
class _SetInfo:
    length: int | None


@dataclass(frozen=True)
class _Binding:
    slot: str
    info: object

    @property
    def kind(self):
        if isinstance(self.info, _ListInfo):
            return "list_int"
        if isinstance(self.info, _MatrixInfo):
            return "matrix_int"
        if isinstance(self.info, _DequeInfo):
            return "deque_int"
        if isinstance(self.info, _DictInfo):
            return "dict_int"
        if isinstance(self.info, _SetInfo):
            return "set_int"
        return self.info


@dataclass
class _Function:
    node: ast.FunctionDef
    rust_name: str
    positional: list[str]
    posonly: set[str]
    kwonly: list[str]
    defaults: dict[str, _Expression]
    local_names: set[str]
    return_kind: str
    dependencies: set[ast.FunctionDef]
    required: set[str]
    imports: set[str]
    global_bindings: dict[str, object] = field(default_factory=dict)


class _FunctionPlans(dict):
    """Keep each definition's identity, including sequential redefinitions."""

    def __init__(self):
        super().__init__()
        self.definitions = {}


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


_OUTPUT_HELPERS = r'''
fn native_flush_output(output:&mut String)->Result<(),String> {
    use std::io::Write;
    let mut stdout=std::io::stdout().lock();
    stdout.write_all(output.as_bytes()).map_err(|error|format!("OSError: {error}"))?;
    output.clear();
    stdout.flush().map_err(|error|format!("OSError: {error}"))
}
'''


_INPUT_HELPERS = r'''
struct NativeInput { reader: StandardInput, line: String }
impl NativeInput {
    fn new() -> Self {Self {reader:StandardInput::new(),line:String::new()}}
    fn line(&mut self,output:&mut String)->Result<&str,String> {
        if !output.is_empty(){native_flush_output(output)?;}
        self.reader.read_text_into(&mut self.line,None,true).map_err(StandardInputError::native_message)?;
        if self.line.is_empty(){return Err("EOFError: EOF when reading a line".into());}
        if self.line.ends_with('\n'){self.line.pop();}
        Ok(&self.line)
    }
    fn integer(&mut self,output:&mut String) -> Result<NativeInt, String> {
        native_parse_integer(self.line(output)?)
    }
    fn integers(&mut self,output:&mut String) -> Result<Vec<NativeInt>, String> {
        self.line(output)?.split(native_space).filter(|word| !word.is_empty())
            .map(native_parse_integer).collect()
    }
    fn unpack_integers_vec(&mut self, count: usize,output:&mut String) -> Result<Vec<NativeInt>, String> {
        let mut words = self.line(output)?.split(native_space).filter(|word| !word.is_empty());
        let mut result = Vec::with_capacity(count);
        for index in 0..count {
            let word = words.next().ok_or_else(|| format!("ValueError: not enough values to unpack (expected {}, got {})", count, index))?;
            result.push(native_parse_integer(word)?);
        }
        if let Some(word) = words.next() {
            native_parse_integer(word)?;
            return Err(format!("ValueError: too many values to unpack (expected {})", count));
        }
        Ok(result)
    }
    fn unpack_integers<const N: usize>(&mut self,output:&mut String) -> Result<[NativeInt; N], String> {
        let mut words = self.line(output)?.split(native_space).filter(|word| !word.is_empty());
        // The target count is a compile-time fact. No heap allocation is
        // needed for each edge's a,b input tuple, including error paths.
        let mut result = [0; N];
        for index in 0..N {
            let word = words.next().ok_or_else(|| format!("ValueError: not enough values to unpack (expected {}, got {})", N, index))?;
            result[index] = native_parse_integer(word)?;
        }
        if let Some(word) = words.next() {
            // Unpacking asks a lazy map for precisely one extra item. Later
            // invalid tokens must not replace the too-many-values error.
            native_parse_integer(word)?;
            return Err(format!("ValueError: too many values to unpack (expected {})", N));
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
fn native_row(values: &[Vec<NativeInt>], index: NativeInt) -> Result<&Vec<NativeInt>, String> {
    native_index(index, values.len()).map(|index| &values[index])
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


_DEQUE_HELPERS = r'''
#[inline]
fn native_deque_get(values: &std::collections::VecDeque<NativeInt>, index: NativeInt) -> Result<NativeInt, String> {
    native_index(index, values.len()).map(|index| values[index])
        .map_err(|_| "IndexError: deque index out of range".to_string())
}
#[inline]
fn native_deque_popleft(values: &mut std::collections::VecDeque<NativeInt>) -> Result<NativeInt, String> {
    values.pop_front().ok_or_else(|| "IndexError: pop from an empty deque".to_string())
}
'''


_SCALAR_UNION_HELPERS = r'''
// A proved finite bool/int union lives on the stack.
#[derive(Clone, Copy)]
enum NativeScalar { Int(NativeInt), Bool(bool) }
impl NativeScalar {
    #[inline]
    fn integer(self) -> NativeInt { match self { Self::Int(value)=>value,Self::Bool(value)=>value as NativeInt } }
    #[inline]
    fn truth(self) -> bool { self.integer()!=0 }
    #[inline]
    fn bitand(self,other:Self)->Self {
        match (self,other) {(Self::Bool(a),Self::Bool(b))=>Self::Bool(a&b),_=>Self::Int(self.integer()&other.integer())}
    }
    #[inline]
    fn bitor(self,other:Self)->Self {
        match (self,other) {(Self::Bool(a),Self::Bool(b))=>Self::Bool(a|b),_=>Self::Int(self.integer()|other.integer())}
    }
    #[inline]
    fn bitxor(self,other:Self)->Self {
        match (self,other) {(Self::Bool(a),Self::Bool(b))=>Self::Bool(a^b),_=>Self::Int(self.integer()^other.integer())}
    }
}
impl std::fmt::Display for NativeScalar {
    fn fmt(&self,formatter:&mut std::fmt::Formatter<'_>)->std::fmt::Result {
        match self {Self::Int(value)=>std::fmt::Display::fmt(value,formatter),Self::Bool(value)=>formatter.write_str(if *value {"True"}else{"False"})}
    }
}
'''


class _Generator:
    BUILTINS = {"int", "input", "print", "range", "abs", "pow", "len", "sum", "any", "all", "min", "max", "list", "map", "filter", "enumerate", "zip", "dict", "set", "sorted"}

    def __init__(self, bits, functions=None, function=None, function_input=False, constructors=None, specializations=None):
        self.bits = bits
        self.bindings = {}
        self.counter = 0
        self.loops = []
        self.needs_integer_runtime = False
        self.has_input = False
        self.has_lists = False
        self.has_dicts = False
        self.has_sets = False
        self.has_deques = False
        self.has_scalar_union = False
        self.iterating_lists = []
        self.return_label = None
        self.functions = functions or {}
        self.global_environment = None
        self.function = function
        self.function_input = function_input
        self.constructors = constructors or {}
        self.specializations = specializations
        self.return_kinds = set()
        self.expression_scopes = []
        self.expression_trace_id = None
        self.has_iterator_frames = False
        self.has_slices = False
        self.has_text_methods = False
        self.entry_scope = None

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

    def slot(self, kind):
        if kind not in {"int", "bool", "int_bool", "list_int", "dict_int", "set_int", "matrix_int", "deque_int"}:
            raise _Unsupported
        if kind == "int_bool":
            self.has_scalar_union = True
        slot = f"native_var_{len(self.bindings)}"
        self.bindings[slot] = kind
        return slot

    def bind(self, name, value, environment):
        if name in self.BUILTINS:
            raise _Unsupported
        kind = value.kind if isinstance(value, _Expression) else value
        previous = environment.get(name)
        slot = previous.slot if isinstance(previous, _Binding) and previous.kind == kind else self.slot(kind)
        info = self.binding(value) if isinstance(value, _Expression) else value
        environment[name] = _Binding(slot, info)
        return slot

    def function_alias_assignment(self, node, environment):
        """Copy a proved function identity without constructing runtime values."""
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)):
            return None
        function = environment.get(node.value.id)
        if not isinstance(function, _Function):
            return None
        if not all(isinstance(target, ast.Name) and target.id not in self.BUILTINS
                   and target.id not in self.iterating_lists for target in node.targets):
            raise _Unsupported
        if self.function is not None and node.value.id not in self.function.local_names:
            self.function.required.add(node.value.id)
        for target in node.targets:
            environment[target.id] = function
        return "", environment

    @staticmethod
    def update_info(environment, name, info):
        previous = environment[name]
        if not isinstance(previous, _Binding):
            raise _Unsupported
        environment[name] = _Binding(previous.slot, info)

    @staticmethod
    def number(expression):
        if expression.kind == "int":
            return expression.code
        if expression.kind == "bool":
            return f"(({expression.code}) as NativeInt)"
        if expression.kind == "int_bool":
            return f"({expression.code}).integer()"
        raise _Unsupported

    @staticmethod
    def coerce(expression, kind):
        if expression.kind == kind:
            return expression.code
        if kind == "int_bool" and expression.kind in {"int", "bool"}:
            variant = "Int" if expression.kind == "int" else "Bool"
            return f"NativeScalar::{variant}({expression.code})"
        raise _Unsupported

    def scalar_kind(self, expressions):
        types = TypeSet()
        for value in expressions:
            if value.kind not in {"int", "bool", "int_bool"}:
                raise _Unsupported
            types = types.join(TypeSet.from_kind(value.kind))
        if types.native_kind == "int_bool":
            self.has_scalar_union = True
        return types.native_kind

    @staticmethod
    def truth(expression):
        if expression.kind in {"list_int", "dict_int", "set_int", "matrix_int", "deque_int"}:
            return f"!({expression.code}).is_empty()"
        if expression.kind == "int_bool":
            return f"({expression.code}).truth()"
        if expression.kind not in {"int", "bool"}:
            raise _Unsupported
        return expression.code if expression.kind == "bool" else f"(({expression.code}) != 0)"

    @staticmethod
    def binding(expression):
        if expression.kind == "list_int":
            return _ListInfo(expression.length)
        if expression.kind == "matrix_int":
            return _MatrixInfo(expression.length)
        if expression.kind == "deque_int":
            return _DequeInfo(expression.length)
        if expression.kind == "dict_int":
            return _DictInfo(expression.length, expression.nonempty)
        if expression.kind == "set_int":
            return _SetInfo(expression.length)
        return expression.kind

    @staticmethod
    def consume_list(expression):
        return expression.code if expression.owned else f"({expression.code}).clone()"

    def scope_name(self):
        if self.expression_scopes:
            return self.expression_scopes[-1]
        return self.function.node.name if self.function else self.entry_scope or "<module>"

    def at(self, code, node):
        scope, line = self.scope_code(), self.line_code(node)
        result = f"native_at({code}, {line}, {scope})"
        if self.expression_trace_id is not None:
            result += f".map_err(&{self.expression_trace_id})"
        return result + "?"

    def scope_code(self):
        scope = self.scope_name()
        return scope.scope_code if hasattr(scope, "scope_code") else _string(scope)

    def line_code(self, node):
        scope = self.scope_name()
        return scope.line_code if hasattr(scope, "line_code") else node.lineno

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
        return _Expression(self.at("native_input.integers(&mut native_output)", node), "list_int")

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

    def extremum(self, node, environment):
        """Lower exact scalar extrema without introducing runtime objects."""
        name = node.func.id
        if not node.args or any(isinstance(value, ast.Starred) for value in node.args):
            raise _Unsupported
        default = None
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                continue
            if keyword.arg == "default" and len(node.args) == 1:
                default = self.expression(keyword.value, environment)
            else:
                raise _Unsupported
        compare = ">" if name == "max" else "<"
        if len(node.args) >= 2:
            values = [self.expression(value, environment) for value in node.args]
            kind = self.scalar_kind(values)
            names = [self.temporary() for _ in values]
            # Python evaluates every argument before making any comparisons.
            setup = " ".join(f"let {local} = {self.coerce(value, kind)};" for local, value in zip(names, values))
            best = self.temporary()
            best_number = self.number(_Expression(best, kind))
            updates = " ".join(f"if {self.number(_Expression(local, kind))} {compare} {best_number} {{ {best} = {local}; }}" for local in names[1:])
            constant = None
            if all(value.constant is not None for value in values):
                constant = (max if name == "max" else min)(value.constant for value in values)
            return _Expression(f"{{ {setup} let mut {best} = {names[0]}; {updates} {best} }}", kind, constant)
        source = node.args[0]
        setup = ""
        if isinstance(source, (ast.List, ast.Tuple)):
            values = [self.expression(value, environment) for value in source.elts]
            kind = self.scalar_kind(values + ([default] if default else [])) if values or default else "int"
            local = self.temporary()
            rust_type = {"int": "NativeInt", "bool": "bool", "int_bool": "NativeScalar"}[kind]
            setup = f"let {local}: [{rust_type}; {len(values)}] = [" + ", ".join(self.coerce(value, kind) for value in values) + "];"
            iterator = f"{local}.into_iter()"
        else:
            if isinstance(source, ast.Call) and isinstance(source.func, ast.Name) and source.func.id == "range":
                setup, iterator, _ = self.range_iterator(source, environment)
                local = self.temporary()
                setup += f" let {local} = {iterator};"
                iterator = local
            else:
                view = self.dict_view(source, environment)
                value = self.integer_input_list(source) if self.input_map(source) else (view[0] if view else self.expression(source, environment))
                if value.kind not in {"list_int", "set_int", "dict_int", "deque_int"} or view and view[1] == "items":
                    raise _Unsupported
                local = self.temporary()
                # Delay a borrow of a named owner until after default has run.
                # A default expression can mutate the same uniquely owned list.
                binding = value.code if value.owned else f"&({value.code})"
                line = f"let {local} = {binding};"
                if value.owned:
                    setup = line
                else:
                    setup = ""
                iterator = (f"{local}.entries.iter().map(|&(_, value)| value)" if view and view[1] == "values" else
                            f"{local}.entries.iter().map(|&(key, _)| key)" if value.kind == "dict_int" else f"{local}.iter().copied()")
                if not value.owned:
                    iterator = f"{{ {line} {iterator} }}"
            kind = self.scalar_kind([_Expression("", "int")] + ([default] if default else []))
            if kind == "int_bool":
                iterator = f"({iterator}).map(NativeScalar::Int)"
        default_name = self.temporary() if default else None
        if default:
            setup += f" let {default_name} = {self.coerce(default, kind)};"
        best, item = self.temporary(), self.temporary()
        test = f"{self.number(_Expression(item, kind))} {compare} {self.number(_Expression(best, kind))}"
        reduction = f"({iterator}).reduce(|{best}, {item}| if {test} {{ {item} }} else {{ {best} }})"
        result = (f"{reduction}.unwrap_or({default_name})" if default else
                  self.at(f'{reduction}.ok_or_else(|| "ValueError: {name}() iterable argument is empty".to_string())', node))
        return _Expression(f"{{ {setup} {result} }}", kind)

    def user_call(self, node, function, environment):
        if any(isinstance(value, ast.Starred) for value in node.args):
            raise _Unsupported
        lines, bound = [], {}
        if len(node.args) > len(function.positional):
            raise _Unsupported
        # Evaluate every explicit argument in source order before reordering
        # into Rust's fixed signature. Defaults are proved pure constants.
        def argument_value(argument):
            value = self.expression(argument, environment)
            if value.kind not in {"int", "bool", "list_int", "float", "str"}:
                raise _Unsupported
            if value.kind == "list_int" and not value.owned:
                # Reading an ordinary binding has no side effect. Delay the
                # Rust borrow until all later arguments are evaluated, so a
                # later argument can still mutate this uniquely owned list.
                # Row lookups have bounds checks/effects and require a richer
                # reference representation before they can be accepted here.
                if not isinstance(argument, ast.Name):
                    raise _Unsupported
                return value
            name = self.temporary()
            lines.append(f"let {name} = {value.code};")
            return _Expression(name, value.kind, owned=value.owned)

        for parameter, argument in zip(function.positional, node.args):
            bound[parameter] = argument_value(argument)
        for keyword in node.keywords:
            parameter = keyword.arg
            if (parameter is None or parameter in function.posonly or parameter in bound
                    or parameter not in function.positional + function.kwonly):
                raise _Unsupported
            bound[parameter] = argument_value(keyword.value)
        arguments, kinds = [], []
        for parameter in function.positional + function.kwonly:
            value = bound.get(parameter, function.defaults.get(parameter))
            if value is None:
                raise _Unsupported
            kinds.append(value.kind)
            arguments.append(f"&({value.code})" if value.kind == "list_int" else value.code)
        globals_at_call = environment if self.function is None else self.global_environment
        variant = self.specializations.get(function, tuple(kinds), globals_at_call)
        if self.function is None:
            # A callee's globals are looked up at call time, including indirect
            # callees whose definitions may follow the caller definition.
            if any(environment.get(name) is not variant.global_bindings.get(name) for name in variant.required):
                raise _Unsupported
        else:
            self.function.dependencies.add(function.node)
            self.function.required.update(variant.required)
            if node.func.id not in self.function.local_names:
                self.function.required.add(node.func.id)
        if self.function_input:
            arguments.append("&mut native_input")
        arguments.append("&mut native_output")
        scope, line = self.scope_code(), self.line_code(node)
        call = f"{variant.rust_name}({', '.join(arguments)})"
        trace = f"{self.expression_trace_id}(error)" if self.expression_trace_id is not None else "error"
        call += f".map_err(|mut error| {{ error.frames.push(({line}, {scope})); {trace} }})?"
        return _Expression("{ " + " ".join(lines) + f" {call} }}", variant.return_kind)

    def deque_constructor(self, node, environment):
        # Bounded queues and subclass/protocol iterables need direct lowering. An
        # unbounded constructor accepts the documented iterable keyword too.
        if len(node.args) > 1 or any(isinstance(value, ast.Starred) for value in node.args):
            raise _Unsupported
        source = node.args[0] if node.args else None
        seen = set()
        for keyword in node.keywords:
            if keyword.arg in seen:
                raise _Unsupported
            seen.add(keyword.arg)
            if keyword.arg == "iterable" and source is None:
                source = keyword.value
            elif keyword.arg == "maxlen" and isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                pass
            else:
                raise _Unsupported
        if self.function is not None:
            self.function.imports.add(node.func.id)
        self.has_deques = self.has_lists = True
        if source is None:
            return _Expression("std::collections::VecDeque::<NativeInt>::new()", "deque_int")
        if (isinstance(source, ast.Call) and isinstance(source.func, ast.Name)
                and source.func.id == "range"):
            setup, iterator, _ = self.range_iterator(source, environment)
            return _Expression(f"{{ {setup} ({iterator}).collect::<std::collections::VecDeque<NativeInt>>() }}", "deque_int")
        if isinstance(source, ast.Tuple):
            source = ast.copy_location(ast.List(elts=source.elts, ctx=ast.Load()), source)
        value = self.expression(source, environment)
        if value.kind not in {"list_int", "deque_int"}:
            raise _Unsupported
        iterator = f"({value.code}).into_iter()" if value.owned else f"({value.code}).iter().copied()"
        return _Expression(f"({iterator}).collect::<std::collections::VecDeque<NativeInt>>()", "deque_int")

    def row_target(self, node, environment, assignment=False):
        """Evaluate a direct row receiver before evaluating method arguments.

        No row borrow escapes into the Python environment. Holding the checked
        index rather than a mutable Rust borrow also preserves argument order.
        """
        if (not isinstance(node, ast.Subscript) or not isinstance(node.value, ast.Name)
                or node.value.id in self.iterating_lists or isinstance(node.slice, ast.Slice)):
            raise _Unsupported
        matrix = self.expression(node.value, environment)
        if matrix.kind != "matrix_int":
            raise _Unsupported
        index = self.expression(node.slice, environment)
        offset = self.temporary()
        check = f"native_index({self.number(index)}, {matrix.code}.len())"
        if assignment:
            check += '.map_err(|_| "IndexError: list assignment index out of range".to_string())'
        setup = f"let {offset} = {self.at(check, node)};"
        return setup, f"{matrix.code}[{offset}]"

    def integer_bit_query(self, node, environment):
        """Lower exact integer/bool methods without attribute dispatch."""
        value = self.expression(node.func.value, environment)
        number = self.number(value)
        method = node.func.attr
        if method == "bit_length":
            code = f"((NativeInt::BITS - ({number}).unsigned_abs().leading_zeros()) as NativeInt)"
        else:
            code = f"(({number}).unsigned_abs().count_ones() as NativeInt)"
        constant = None if value.constant is None else getattr(int(value.constant), method)()
        return _Expression(code, "int", constant)

    def expression(self, node, environment):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            from .native_slices import try_slice
            return try_slice(self, node, environment)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sorted":
            from .native_slices import sorted_list
            return sorted_list(self, node, environment)
        from .native_iterators import try_reduction
        reduction = try_reduction(self, node, environment)
        if reduction is not None:
            return reduction
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"bit_length", "bit_count"}
                and not node.args and not node.keywords):
            return self.integer_bit_query(node, environment)
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
            if not isinstance(information, _Binding):
                raise _Unsupported
            info = information.info
            if isinstance(info, _ListInfo):
                return _Expression(information.slot, "list_int", owned=False, length=info.length)
            if isinstance(info, _MatrixInfo):
                return _Expression(information.slot, "matrix_int", owned=False, length=info.length)
            if isinstance(info, _DequeInfo):
                return _Expression(information.slot, "deque_int", owned=False, length=info.length)
            if isinstance(info, _DictInfo):
                return _Expression(information.slot, "dict_int", owned=False, length=info.length, nonempty=info.nonempty)
            if isinstance(info, _SetInfo):
                return _Expression(information.slot, "set_int", owned=False, length=info.length)
            return _Expression(information.slot, info)
        if isinstance(node, ast.List):
            values = [self.expression(value, environment) for value in node.elts]
            kind = "list_int"
            if values and all(value.kind == "list_int" and value.owned for value in values):
                kind = "matrix_int"
            elif any(value.kind != "int" for value in values):
                raise _Unsupported
            self.has_lists = True
            return _Expression("vec![" + ", ".join(value.code for value in values) + "]", kind, length=len(values))
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
            if values.kind not in {"list_int", "dict_int", "matrix_int", "deque_int"}:
                raise _Unsupported
            index = self.expression(node.slice, environment)
            if values.kind == "matrix_int":
                # A row borrow cannot escape or outlive its unique parent.
                if not isinstance(node.value, ast.Name):
                    raise _Unsupported
                return _Expression(self.at(f"native_row(&{values.code}, {self.number(index)})", node), "list_int", owned=False)
            if values.kind == "deque_int":
                offset = self.temporary()
                receiver = self.temporary() if values.owned else values.code
                setup = f"let {receiver} = {values.code}; " if values.owned else ""
                lookup = self.at(f"native_deque_get(&{receiver}, {offset})", node)
                return _Expression(f"{{ {setup}let {offset} = {self.number(index)}; {lookup} }}", "int")
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
            inside = environment.copy()
            inside[target] = _Binding(local, "int")
            filters = [self.expression(condition, inside) for condition in comprehension.ifs]
            element = self.expression(node.elt, inside)
            if element.kind == "int":
                kind, rust_type = "list_int", "NativeInt"
            elif element.kind == "list_int" and element.owned:
                kind, rust_type = "matrix_int", "Vec<NativeInt>"
            else:
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
            code = f"{{ {setup} let mut {result}: Vec<{rust_type}> = Vec::new(); for {local} in {iterator} {{ {insertion} }} {result} }}"
            return _Expression(code, kind, length=length)
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
            kind = self.scalar_kind(values)
            code = self.coerce(values[-1], kind)
            for value in reversed(values[:-1]):
                name = self.temporary()
                check = self.truth(_Expression(name, kind))
                yes, no = (code, name) if isinstance(node.op, ast.And) else (name, code)
                code = f"{{ let {name} = {self.coerce(value, kind)}; if {check} {{ {yes} }} else {{ {no} }} }}"
            return _Expression(code, kind)
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
            kind = self.scalar_kind([yes, no])
            return _Expression(f"(if {self.truth(test)} {{ {self.coerce(yes, kind)} }} else {{ {self.coerce(no, kind)} }})", kind)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"min", "max"}:
            return self.extremum(node, environment)
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
                    return _Expression(self.at("native_input.integer(&mut native_output)", argument), "int")
                value = self.expression(argument, environment)
                return _Expression(self.number(value), "int", value.constant)
            if name == "abs" and len(node.args) == 1:
                value = self.expression(node.args[0], environment)
                constant = None if value.constant is None else self.normalize(abs(value.constant))
                return _Expression(f"({self.number(value)}).wrapping_abs()", "int", constant)
            if name == "len" and len(node.args) == 1:
                view = self.dict_view(node.args[0], environment)
                value = view[0] if view else self.expression(node.args[0], environment)
                if value.kind not in {"list_int", "dict_int", "set_int", "matrix_int", "deque_int"}:
                    raise _Unsupported
                return _Expression(f"(({value.code}).len() as NativeInt)", "int", value.length)
            if name == "sum" and len(node.args) in (1, 2):
                view = self.dict_view(node.args[0], environment)
                value = view[0] if view else self.expression(node.args[0], environment)
                if value.kind not in {"list_int", "dict_int", "set_int", "deque_int"} or (view and view[1] == "items"):
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
                if value.kind == "deque_int" and not value.owned:
                    # start can pop from this same queue. Python creates the
                    # iterator only after all arguments have been evaluated.
                    code = f"{{ let {start_name} = {self.number(start)}; ({value.code}).iter().fold({start_name}, |acc, &value| acc.wrapping_add(value)) }}"
                    return _Expression(code, "int")
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
            if isinstance(function, _DequeConstructor):
                return self.deque_constructor(node, environment)
            if isinstance(function, _Function):
                return self.user_call(node, function, environment)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.attr in {"popleft", "pop"}
                and not node.args and not node.keywords):
            target = node.func.value
            values = self.expression(target, environment)
            if values.kind != "deque_int" or target.id in self.iterating_lists:
                raise _Unsupported
            function = "native_deque_popleft" if node.func.attr == "popleft" else None
            code = (f"{function}(&mut {values.code})" if function else
                    f'{values.code}.pop_back().ok_or_else(|| "IndexError: pop from an empty deque".to_string())')
            return _Expression(self.at(code, node), "int")
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
        if (isinstance(operator, (ast.BitAnd, ast.BitOr, ast.BitXor))
                and "int_bool" in (left.kind, right.kind)
                and left.kind in {"bool", "int_bool"} and right.kind in {"bool", "int_bool"}):
            self.has_scalar_union = True
            method = {ast.BitAnd: "bitand", ast.BitOr: "bitor", ast.BitXor: "bitxor"}[type(operator)]
            return _Expression(f"({self.coerce(left, 'int_bool')}).{method}({self.coerce(right, 'int_bool')})", "int_bool")
        if isinstance(operator, (ast.BitAnd, ast.BitOr, ast.BitXor)) and left.kind == right.kind == "bool":
            # bool's three bitwise operations retain a bool only when both
            # operands are bool; mixed bool/int operations still return int.
            symbol = {ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^"}[type(operator)]
            constant = None
            if left.constant is not None and right.constant is not None:
                a, b = bool(left.constant), bool(right.constant)
                constant = a & b if isinstance(operator, ast.BitAnd) else a | b if isinstance(operator, ast.BitOr) else a ^ b
            return _Expression(f"(({left.code}) {symbol} ({right.code}))", "bool", constant)
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

    def join(self, environments, preferred=None):
        """Merge normal paths, emitting moves into a typed phi slot per name.

        An incompatible or possibly unbound name is deliberately absent. A
        later independent assignment can restore its proof; a read cannot.
        """
        live = [environment for environment in environments if environment is not None]
        moves = [[] for _ in environments]
        if not live:
            return None, moves
        result = {}
        for name, first in live[0].items():
            values = [environment.get(name) for environment in live]
            if isinstance(first, (_Function, _DequeConstructor)):
                if all(value is first for value in values):
                    result[name] = first
                continue
            if not isinstance(first, _Binding):
                continue
            types = TypeSet()
            for value in values:
                types = types.join(TypeSet.from_kind(value.kind) if isinstance(value, _Binding) else TypeSet(maybe_unbound=True))
            kind = types.native_kind
            if kind is None:
                continue
            if kind == "int_bool":
                self.has_scalar_union = True
            infos = [value.info for value in values]
            info = kind if kind == "int_bool" else infos[0]
            if isinstance(info, _ListInfo) and any(value != info for value in infos):
                info = _ListInfo(None)
            elif isinstance(info, _MatrixInfo) and any(value != info for value in infos):
                info = _MatrixInfo(None)
            elif isinstance(info, _DequeInfo) and any(value != info for value in infos):
                info = _DequeInfo(None)
            elif isinstance(info, _DictInfo) and any(value != info for value in infos):
                info = _DictInfo(None, all(value.nonempty for value in infos))
            elif isinstance(info, _SetInfo) and any(value != info for value in infos):
                info = _SetInfo(None)
            candidate = (preferred or {}).get(name)
            if isinstance(candidate, _Binding) and candidate.kind == kind:
                slot = candidate.slot
            elif all(value.slot == first.slot for value in values):
                slot = first.slot
            else:
                slot = self.slot(kind)
            result[name] = _Binding(slot, info)
            for index, environment in enumerate(environments):
                if environment is not None and environment[name].slot != slot:
                    source = environment[name]
                    moves[index].append(f"{slot} = {self.coerce(_Expression(source.slot, source.kind), kind)};")
        return result, moves

    @staticmethod
    def after_loop(environment):
        # A body can resize or replace a list on any normal/break/continue
        # path. Its pre-loop cardinality is no longer a valid proof.
        result = {}
        for name, binding in environment.items():
            if isinstance(binding, _Binding):
                info = binding.info
                widened = (_ListInfo(None) if isinstance(info, _ListInfo)
                           else _MatrixInfo(None) if isinstance(info, _MatrixInfo)
                           else _DequeInfo(None) if isinstance(info, _DequeInfo)
                           else _DictInfo(None) if isinstance(info, _DictInfo)
                           else _SetInfo(None) if isinstance(info, _SetInfo) else info)
                binding = _Binding(binding.slot, widened)
            result[name] = binding
        return result

    @staticmethod
    def read_before_write(statements):
        """Conservative loop-header liveness; nested loops cannot prove stores."""
        reads = set()

        def loads(node, defined):
            reads.update(value.id for value in ast.walk(node)
                         if isinstance(value, ast.Name) and isinstance(value.ctx, ast.Load) and value.id not in defined)

        def targets(node):
            if isinstance(node, ast.Name):
                return {node.id}
            if isinstance(node, (ast.Tuple, ast.List)):
                return set().union(*(targets(value) for value in node.elts))
            return set()

        def block(body, defined):
            defined = set(defined)
            for statement in body:
                if isinstance(statement, ast.Assign):
                    loads(statement.value, defined)
                    for target in statement.targets:
                        loads(target, defined)
                        defined |= targets(target)
                elif isinstance(statement, ast.AugAssign):
                    loads(statement.target, defined)
                    if isinstance(statement.target, ast.Name) and statement.target.id not in defined:
                        reads.add(statement.target.id)
                    loads(statement.value, defined)
                    defined |= targets(statement.target)
                elif isinstance(statement, ast.If):
                    loads(statement.test, defined)
                    yes = block(statement.body, defined)
                    no = block(statement.orelse, defined)
                    if yes is None and no is None:
                        return None
                    defined = no if yes is None else yes if no is None else yes & no
                elif isinstance(statement, (ast.Break, ast.Continue, ast.Return)):
                    loads(statement, defined)
                    return None
                else:
                    # This includes nested loops and comprehensions. Their
                    # loads are safe overapproximations; their stores do not
                    # establish a binding on every current iteration.
                    loads(statement, defined)
            return defined

        block(statements, set())
        return reads

    def loop_header(self, node, environment):
        """Widen finite scalar kinds before lowering reads on a back edge.

        This pass only adds possible bool/int kinds. Unsupported values still
        fail the ordinary body proof; no result narrows an existing type set.
        """
        header = self.after_loop(environment)
        live = self.read_before_write(node.body)
        if isinstance(node, ast.While):
            live |= {value.id for value in ast.walk(node.test) if isinstance(value, ast.Name) and isinstance(value.ctx, ast.Load)}
        else:
            live -= {value.id for value in ast.walk(node.target) if isinstance(value, ast.Name)}
        entry = {name: TypeSet.from_kind(value.kind)
                 for name, value in environment.items() if isinstance(value, _Binding)}
        unknown = TypeSet.from_kind("unknown")

        def infer(expression, state):
            if isinstance(expression, ast.Constant) and type(expression.value) in {int, bool}:
                return TypeSet.from_kind("bool" if type(expression.value) is bool else "int")
            if isinstance(expression, ast.Name):
                return state.get(expression.id, TypeSet(maybe_unbound=True))
            if isinstance(expression, ast.Compare):
                return TypeSet.from_kind("bool")
            if isinstance(expression, ast.UnaryOp):
                return TypeSet.from_kind("bool" if isinstance(expression.op, ast.Not) else "int") if infer(expression.operand, state).kinds <= {"bool", "int"} else unknown
            if isinstance(expression, (ast.BoolOp, ast.IfExp)):
                values = expression.values if isinstance(expression, ast.BoolOp) else [expression.body, expression.orelse]
                kinds = TypeSet()
                for value in values:
                    current = infer(value, state)
                    if not current.kinds <= {"int", "bool"}:
                        return unknown
                    kinds = kinds.join(current)
                return kinds
            if isinstance(expression, ast.BinOp):
                left, right = infer(expression.left, state), infer(expression.right, state)
                if not left.kinds <= {"int", "bool"} or not right.kinds <= {"int", "bool"}:
                    return unknown
                kinds = TypeSet.from_kind("int")
                if isinstance(expression.op, (ast.BitAnd, ast.BitOr, ast.BitXor)) and "bool" in left.kinds and "bool" in right.kinds:
                    kinds = TypeSet.from_kind("bool")
                    if "int" in left.kinds or "int" in right.kinds:
                        kinds = kinds.join(TypeSet.from_kind("int"))
                return kinds
            if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name) and expression.func.id in {"int", "abs", "pow", "len", "sum"}:
                return TypeSet.from_kind("int")
            return unknown

        if sum(1 for statement in node.body for _ in ast.walk(statement)) > 2048:
            return "", header

        def merge(states):
            states = [state for state in states if state is not None]
            if not states:
                return None
            joined = {}
            for name in set().union(*(state.keys() for state in states)):
                types = TypeSet()
                for state in states:
                    types = types.join(state.get(name, TypeSet(maybe_unbound=True)))
                joined[name] = types
            return joined

        def block(statements, incoming):
            state = incoming.copy()
            continues, breaks = [], []
            for statement in statements:
                if isinstance(statement, ast.Assign):
                    types = infer(statement.value, state)
                    for target in statement.targets:
                        if isinstance(target, ast.Name):
                            state[target.id] = types
                elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
                    expression = ast.BinOp(left=statement.target, op=statement.op, right=statement.value)
                    state[statement.target.id] = infer(expression, state)
                elif isinstance(statement, ast.If):
                    yes, yc, yb = block(statement.body, state)
                    no, nc, nb = block(statement.orelse, state)
                    continues += yc + nc
                    breaks += yb + nb
                    state = merge([yes, no])
                    if state is None:
                        return None, continues, breaks
                elif isinstance(statement, ast.Continue):
                    return None, continues + [state], breaks
                elif isinstance(statement, ast.Break):
                    return None, continues, breaks + [state]
                elif isinstance(statement, ast.Return):
                    return None, continues, breaks
                elif isinstance(statement, (ast.For, ast.While)):
                    inner, normal, exits = loop(statement, state)
                    state = merge([inner, normal, *exits])
            return state, continues, breaks

        def loop(statement, incoming):
            current = incoming.copy()
            while True:
                body_entry = current.copy()
                if isinstance(statement, ast.For):
                    for target in ast.walk(statement.target):
                        if isinstance(target, ast.Name):
                            body_entry[target.id] = TypeSet.from_kind("int")
                normal, continues, breaks = block(statement.body, body_entry)
                joined = merge([incoming, normal, *continues])
                if joined == current:
                    return current, normal, breaks
                current = joined

        possibilities, _, _ = loop(node, entry)
        initializers = []
        for name in sorted(live):
            old = environment.get(name)
            if (isinstance(old, _Binding) and old.kind in {"int", "bool"}
                    and possibilities.get(name, TypeSet()).native_kind == "int_bool"):
                slot = self.slot("int_bool")
                header[name] = _Binding(slot, "int_bool")
                initializers.append(f"{slot} = {self.coerce(_Expression(old.slot, old.kind), 'int_bool')};")
        return "\n".join(initializers), header

    def finish_loop(self, node, entry, header, context, body, remaining, nonempty, may_repeat, zero=False):
        if remaining is not None:
            marker = "// " + self.temporary() + "_edge"
            context["edges"].append((marker, "normal", remaining))
            body += "\n" + marker
        edges = context["edges"]
        environments = ([entry] if not nonempty else []) + [environment for _, _, environment in edges]
        if zero:
            environments = [entry]
        joined, post_moves = self.join(environments, preferred=entry)
        if joined is None:
            # All executed paths leave the function. Keeping only old definite
            # bindings conservatively lets the Rust tail remain type checked.
            joined = self.after_loop(entry)
        initializers = []
        entry_slots = {value.slot for value in entry.values() if isinstance(value, _Binding)}
        for name, binding in joined.items():
            if isinstance(binding, _Binding) and binding.slot not in entry_slots:
                default = {"int": "0", "bool": "false", "int_bool": "NativeScalar::Int(0)", "list_int": "Vec::new()",
                           "dict_int": "NativeDict::new()", "set_int": "NativeSet::new()",
                           "matrix_int": "Vec::new()", "deque_int": "std::collections::VecDeque::new()",
                           "float": "0.0_f64", "str": "String::new()"}[binding.kind]
                if isinstance(entry.get(name), _Binding) and entry[name].kind in {"int", "bool", "int_bool"} and binding.kind == "int_bool":
                    default = self.coerce(_Expression(entry[name].slot, entry[name].kind), binding.kind)
                initializers.append(f"{binding.slot} = {default};")
        live = self.read_before_write(node.body)
        if isinstance(node, ast.While):
            live |= {value.id for value in ast.walk(node.test) if isinstance(value, ast.Name) and isinstance(value.ctx, ast.Load)}
        else:
            live -= {value.id for value in ast.walk(node.target) if isinstance(value, ast.Name)}
        replacements = {}
        offset = 0 if nonempty else 1
        for index, (marker, kind, environment) in enumerate(edges):
            copies = []
            if kind != "break" and may_repeat and not zero:
                for name, previous in header.items():
                    if isinstance(previous, (_Function, _DequeConstructor)):
                        if name in live and environment.get(name) is not previous:
                            raise _Unsupported
                        continue
                    if not isinstance(previous, _Binding):
                        continue
                    current = environment.get(name)
                    compatible = isinstance(current, _Binding) and (current.kind == previous.kind or previous.kind == "int_bool" and current.kind in {"int", "bool"})
                    if not compatible:
                        if name in live:
                            raise _Unsupported
                    elif current.slot != previous.slot:
                        copies.append(f"{previous.slot} = {self.coerce(_Expression(current.slot, current.kind), previous.kind)};")
            if not zero:
                copies += post_moves[index + offset]
            # Same-kind header/post phis use the same slot. Moving an owned
            # container once is required; duplicating the move would alias it.
            replacements[marker] = "\n".join(dict.fromkeys(copies))
        # Markers occupy entire generated lines, so replacement never touches
        # user strings (their newlines are escaped by _string).
        body = "\n".join(replacements.get(line, line) for line in body.split("\n"))
        return "\n".join(initializers), body, self.after_loop(joined)

    def statement(self, node, environment):
        alias = self.function_alias_assignment(node, environment)
        if alias is not None:
            return alias
        if isinstance(node, ast.ImportFrom):
            if self.function is not None or node.module != "collections" or node.level:
                raise _Unsupported
            for alias in node.names:
                name = alias.asname or alias.name
                if (alias.name != "deque" or name not in self.constructors
                        or name in self.BUILTINS | {"__name__", "__builtins__"}):
                    raise _Unsupported
                environment[name] = self.constructors[name]
            return "", environment
        if isinstance(node, ast.FunctionDef):
            function = getattr(self.functions, "definitions", {}).get(node)
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
            if value.kind not in {"int", "bool", "float", "str"}:
                raise _Unsupported
            self.return_kinds.add(value.kind)
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
                    # Keep unusually large unpackings off the Rust stack.
                    unpack = (f"native_input.unpack_integers::<{count}>(&mut native_output)" if count <= 32 else
                              f"native_input.unpack_integers_vec({count}, &mut native_output)")
                    value_code = self.at(unpack, node)
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
                    lines.append(f"{self.bind(target.id, 'int', environment)} = {name}[{index}];")
                return "\n".join(lines), environment
            value = self.expression(node.value, environment)
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
                target = node.targets[0]
                if isinstance(target.value, ast.Subscript):
                    if value.kind != "int" or isinstance(target.slice, ast.Slice):
                        raise _Unsupported
                    setup, row = self.row_target(target.value, environment)
                    index = self.expression(target.slice, environment)
                    result, offset = self.temporary(), self.temporary()
                    setter = self.at(f"native_set(&mut {row}, {offset}, {result})", node)
                    return f"let {result} = {value.code};\n{setup}\nlet {offset} = {self.number(index)};\n{setter};", environment
                if isinstance(target.value, ast.Name):
                    parent = self.expression(target.value, environment)
                    if parent.kind == "matrix_int":
                        if value.kind != "list_int" or not value.owned:
                            raise _Unsupported
                        result = self.temporary()
                        setup, row = self.row_target(target, environment, assignment=True)
                        return f"let {result} = {value.code};\n{setup}\n{row} = {result};", environment
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
                    self.update_info(environment, target.value.id, _DictInfo(None, True))
                    return f"let {result} = {value.code};\nlet {offset} = {index.code};\n{values.code}.set({offset}, {result});", environment
                setter = self.at(f"native_set(&mut {values.code}, {offset}, {result})", node)
                return f"let {result} = {value.code};\nlet {offset} = {self.number(index)};\n{setter};", environment
            if not all(isinstance(target, ast.Name) and target.id not in self.iterating_lists for target in node.targets):
                raise _Unsupported
            if value.kind in {"list_int", "dict_int", "set_int", "matrix_int", "deque_int"} and (not value.owned or len(node.targets) != 1):
                raise _Unsupported
            name = self.temporary()
            lines = [f"let {name} = {value.code};"]
            for target in node.targets:
                lines.append(f"{self.bind(target.id, value, environment)} = {name};")
            return "\n".join(lines), environment
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Subscript):
            target = node.target
            if isinstance(target.value, ast.Subscript):
                if isinstance(target.slice, ast.Slice):
                    raise _Unsupported
                setup, row = self.row_target(target.value, environment)
                index = self.expression(target.slice, environment)
                offset, old, result = self.temporary(), self.temporary(), self.temporary()
                getter = self.at(f"native_get(&{row}, {offset})", target)
                right = self.expression(node.value, environment)
                value = self.binary(node.op, _Expression(old, "int"), right, node)
                setter = self.at(f"native_set(&mut {row}, {offset}, {result})", node)
                return f"{setup}\nlet {offset} = {self.number(index)};\nlet {old} = {getter};\nlet {result} = {value.code};\n{setter};", environment
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
            if left.kind in {"list_int", "dict_int", "set_int", "matrix_int", "deque_int"}:
                raise _Unsupported
            right = self.expression(node.value, environment)
            value = self.binary(node.op, left, right, node)
            name = self.bind(node.target.id, value, environment)
            return f"{name} = {value.code};", environment
        if isinstance(node, ast.If):
            if self.function is None and self.functions and _main_guard(node):
                return self.statements(node.body, environment)
            test = self.expression(node.test, environment)
            yes, yes_environment = self.statements(node.body, environment)
            no, no_environment = self.statements(node.orelse, environment)
            joined, moves = self.join([yes_environment, no_environment])
            yes += "\n" + "\n".join(moves[0])
            no += "\n" + "\n".join(moves[1])
            return f"if {self.truth(test)} {{\n{yes}\n}} else {{\n{no}\n}}", joined
        if isinstance(node, (ast.For, ast.While)):
            if node.orelse:
                raise _Unsupported
            label = self.temporary()
            context = {"label": label, "edges": []}
            header_initializers, widened = self.loop_header(node, environment)
            if isinstance(node, ast.While):
                # Subsequent iterations may see containers resized or replaced
                # by the body. Their entry cardinality is not a loop invariant.
                test = self.expression(node.test, widened)
                self.loops.append(context)
                body, remaining = self.statements(node.body, widened)
                self.loops.pop()
                nonempty = test.constant is not None and bool(test.constant)
                zero = test.constant is not None and not bool(test.constant)
                initialization, body, joined = self.finish_loop(node, environment, widened, context, body, remaining,
                                                               nonempty, not zero, zero)
                return f"{header_initializers}\n{initialization}\n'{label}: while {self.truth(test)} {{\n{body}\n}}", joined
            is_range = isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Name) and node.iter.func.id == "range"
            list_name = None
            item_pair = False
            count = None
            if is_range:
                if not isinstance(node.target, ast.Name):
                    raise _Unsupported
                setup, iterator, arguments = self.range_iterator(node.iter, environment)
                nonempty = False
                if all(argument.constant is not None for argument in arguments):
                    start, stop, step = (int(argument.constant) for argument in arguments)
                    nonempty = (step > 0 and start < stop) or (step < 0 and start > stop)
                    if step > 0:
                        count = max(0, (stop-start+step-1)//step)
                    elif step < 0:
                        count = max(0, (start-stop-step-1)//-step)
            else:
                view = self.dict_view(node.iter, environment)
                values = view[0] if view else self.expression(node.iter, environment)
                if values.kind not in {"list_int", "dict_int", "deque_int"}:
                    raise _Unsupported
                receiver = view[2] if view else node.iter
                if isinstance(receiver, ast.Name):
                    list_name = receiver.id
                    setup = ""
                    iterable = values.code
                    borrowed = True
                elif (isinstance(receiver, ast.Subscript) and isinstance(receiver.value, ast.Name)
                      and isinstance(environment.get(receiver.value.id), _Binding)
                      and environment[receiver.value.id].kind == "matrix_int"):
                    list_name = receiver.value.id
                    iterable = self.temporary()
                    setup = f"let {iterable} = {values.code};"
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
                count = values.length
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
            if any(target.id in self.iterating_lists or target.id == list_name for target in targets):
                raise _Unsupported
            inside = widened.copy()
            target_names = [self.bind(target.id, "int", inside) for target in targets]
            self.loops.append(context)
            if list_name is not None:
                self.iterating_lists.append(list_name)
            body, remaining = self.statements(node.body, inside)
            if list_name is not None:
                self.iterating_lists.pop()
            self.loops.pop()
            initialization, body, joined = self.finish_loop(node, environment, inside, context, body, remaining,
                                                           nonempty, count is None or count > 1, count == 0)
            item = self.temporary()
            assignments = "\n".join(f"{target} = {item}.{index};" if item_pair else f"{target} = {item};"
                                    for index, target in enumerate(target_names))
            code = f"{setup}\n{header_initializers}\n{initialization}\n'{label}: for {item} in {iterator} {{\n{assignments}\n{body}\n}}"
            return code, joined
        if isinstance(node, (ast.Break, ast.Continue)) and self.loops:
            context = self.loops[-1]
            kind = "break" if isinstance(node, ast.Break) else "continue"
            marker = "// " + self.temporary() + "_edge"
            context["edges"].append((marker, kind, environment.copy()))
            return f"{marker}\n{kind} '{context['label']};", None
        if isinstance(node, ast.Expr):
            call = node.value
            if isinstance(call, ast.Constant) and type(call.value) is str:
                return ";", environment
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Subscript)):
                # Resolve the row before its arguments, including failing
                # index checks. Its integer elements have no alias identity.
                setup, row = self.row_target(call.func.value, environment)
                method = call.func.attr
                if call.keywords:
                    raise _Unsupported
                if method == "append" and len(call.args) == 1:
                    argument = self.expression(call.args[0], environment)
                    if argument.kind != "int":
                        raise _Unsupported
                    item = self.temporary()
                    return f"{setup}\nlet {item} = {argument.code};\n{row}.push({item});", environment
                if method == "clear" and not call.args:
                    return f"{setup}\n{row}.clear();", environment
                raise _Unsupported
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)):
                target = call.func.value
                values = self.expression(target, environment)
                if values.kind in {"matrix_int", "deque_int"}:
                    if target.id in self.iterating_lists or call.keywords:
                        raise _Unsupported
                    method = call.func.attr
                    if method == "clear" and not call.args:
                        if values.kind == "matrix_int":
                            self.update_info(environment, target.id, _MatrixInfo(0))
                        return f"{values.code}.clear();", environment
                    if method in {"append", "appendleft"} and len(call.args) == 1:
                        argument = self.expression(call.args[0], environment)
                        if values.kind == "matrix_int":
                            if method != "append" or argument.kind != "list_int" or not argument.owned:
                                raise _Unsupported
                            self.update_info(environment, target.id, _MatrixInfo(None))
                            action = "push"
                        else:
                            if argument.kind != "int":
                                raise _Unsupported
                            action = "push_back" if method == "append" else "push_front"
                        item = self.temporary()
                        return f"let {item} = {argument.code};\n{values.code}.{action}({item});", environment
                    if values.kind == "deque_int" and method in {"popleft", "pop"} and not call.args:
                        value = self.expression(call, environment)
                        return f"let _ = {value.code};", environment
                    raise _Unsupported
                if values.kind == "set_int":
                    if call.keywords:
                        raise _Unsupported
                    method = call.func.attr
                    if method == "clear" and not call.args:
                        self.update_info(environment, target.id, _SetInfo(0))
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
                        self.update_info(environment, target.id, _SetInfo(None))
                        return f"let {item} = {argument.code};\n{action};", environment
                    if method == "update" and len(call.args) <= 1:
                        if not call.args:
                            return ";", environment
                        if isinstance(call.args[0], ast.Name) and call.args[0].id == target.id:
                            return ";", environment
                        setup, iterator = self.set_iterable(call.args[0], environment)
                        item = self.temporary()
                        self.update_info(environment, target.id, _SetInfo(None))
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
                    self.update_info(environment, target.id, _ListInfo(None if values.length is None else values.length + 1))
                    return f"let {item} = {argument.code};\n{values.code}.push({item});", environment
                if method == "extend" and len(call.args) == 1 and not call.keywords:
                    argument = self.expression(call.args[0], environment)
                    if argument.kind != "list_int":
                        raise _Unsupported
                    item = self.temporary()
                    # Own a snapshot before the mutable receiver borrow, even
                    # for a.extend(a), preserving Python's self-extension.
                    length = None if values.length is None or argument.length is None else values.length + argument.length
                    self.update_info(environment, target.id, _ListInfo(length))
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
                flush = False
                seen = set()
                for keyword in call.keywords:
                    if keyword.arg not in {"sep", "end", "flush"} or keyword.arg in seen or not isinstance(keyword.value, ast.Constant):
                        raise _Unsupported
                    seen.add(keyword.arg)
                    if keyword.arg == "flush":
                        if type(keyword.value.value) is not bool: raise _Unsupported
                        flush = keyword.value.value
                    else:
                        if type(keyword.value.value) is not str: raise _Unsupported
                        if keyword.arg == "sep": separator = keyword.value.value
                        else: end = keyword.value.value
                values = [self.expression(argument.value if isinstance(argument, ast.Starred) else argument, environment)
                          for argument in call.args]
                starred = [isinstance(argument, ast.Starred) for argument in call.args]
                if any(value.kind not in ({"list_int", "deque_int"} if star else {"int", "bool", "int_bool"})
                       for value, star in zip(values, starred)):
                    raise _Unsupported
                names = [self.temporary() for _ in values]
                lines = [f"let {name} = {('(' + value.code + ').clone()') if star and value.kind == 'deque_int' and not value.owned else ('&(' + value.code + ')') if star and not value.owned else value.code};"
                         for name, value, star in zip(names, values, starred)]
                if any(starred):
                    first = self.temporary()
                    lines.append(f"let mut {first} = true;")
                    for name, value, star in zip(names, values, starred):
                        item = self.temporary() if star else name
                        if star:
                            lines.append(f"for {item} in {name}.iter() {{")
                        lines.append(f"if !{first} {{ native_output.push_str({_string(separator)}); }}")
                        lines.append(f"{first} = false;")
                        formatted = item if value.kind != "bool" else f'(if {item} {{ "True" }} else {{ "False" }})'
                        lines.append(f'write!(&mut native_output, "{{}}", {formatted}).unwrap();')
                        if star:
                            lines.append("}")
                    lines.append(f"native_output.push_str({_string(end)});")
                    if flush: lines.append(self.at("native_flush_output(&mut native_output)", node) + ";")
                    return "\n".join(lines), environment
                for index, (name, value) in enumerate(zip(names, values)):
                    if index:
                        lines.append(f"native_output.push_str({_string(separator)});")
                    formatted = name if value.kind in {"int", "int_bool"} else f'(if {name} {{ "True" }} else {{ "False" }})'
                    lines.append(f'write!(&mut native_output, "{{}}", {formatted}).unwrap();')
                lines.append(f"native_output.push_str({_string(end)});")
                if flush: lines.append(self.at("native_flush_output(&mut native_output)", node) + ";")
                return "\n".join(lines), environment
            expression = self.expression(call, environment)
            return f"let _ = {'&(' + expression.code + ')' if expression.kind in {'list_int', 'dict_int', 'set_int', 'matrix_int', 'deque_int'} and not expression.owned else expression.code};", environment
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


def _function_plans(tree, table, bits, generator_type=_Generator):
    functions = _FunctionPlans()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        parameters = node.args
        arguments = parameters.posonlyargs + parameters.args + parameters.kwonlyargs
        if (node.name in generator_type.BUILTINS | {"__builtins__", "__name__"}
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
        default_generator = generator_type(bits)
        default_nodes = list(zip(positional[len(positional)-len(parameters.defaults):], parameters.defaults))
        default_nodes += [(argument.arg, value) for argument, value in zip(parameters.kwonlyargs, parameters.kw_defaults)
                          if value is not None]
        for name, value in default_nodes:
            literal = value.operand if isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.UAdd, ast.USub)) else value
            if isinstance(literal, ast.Constant) and type(literal.value) in {str, float}:
                if literal is not value and type(literal.value) is not float:
                    raise _Unsupported
                expression = default_generator.expression(value, {})
                defaults[name] = expression
                continue
            # A constant result does not imply a pure evaluation: len([input()])
            # has a known length but consumes input at definition time. Only
            # closed numeric syntax can be folded without executing effects or
            # hiding an exception in a container element or a call argument.
            if any(not isinstance(item, (ast.Constant, ast.BinOp, ast.UnaryOp,
                                         ast.operator, ast.unaryop))
                   or isinstance(item, ast.Constant) and type(item.value) not in {int, bool}
                   for item in ast.walk(value)):
                raise _Unsupported
            expression = default_generator.expression(value, {})
            if expression.kind not in {"int", "bool"} or expression.constant is None:
                raise _Unsupported
            code = (str(expression.constant).lower() if expression.kind == "bool"
                    else default_generator.literal(expression.constant))
            defaults[name] = _Expression(code, expression.kind, expression.constant)
        value_returns = [statement for statement in ast.walk(node) if isinstance(statement, ast.Return)
                         and statement.value is not None
                         and not (isinstance(statement.value, ast.Constant) and statement.value.value is None)]
        function = _Function(node, f"native_function_{len(functions.definitions)}", positional,
                                        {argument.arg for argument in parameters.posonlyargs},
                                        [argument.arg for argument in parameters.kwonlyargs], defaults,
                                        local_names, "int" if value_returns else "none", set(), set(), set())
        functions[node.name] = function
        functions.definitions[node] = function
    if functions and any(isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                         and node.id in {"__builtins__", "__name__"} for node in ast.walk(tree)):
        raise _Unsupported
    return functions


class _Specializations:
    """Prove and emit only the exact argument-kind variants actually called."""

    def __init__(self, bits, functions, constructors, function_input, generator_type=_Generator):
        self.bits = bits
        self.functions = functions
        self.constructors = constructors
        self.function_input = function_input
        self.generator_type = generator_type
        self.variants = {}
        self.active = set()
        self.sources = []
        self.generators = []
        self.names = set()

    @staticmethod
    def readonly_arrays(node, names):
        # Arrays borrow their caller's storage. Reject writes and mutating
        # operations rather than copying the list or changing Python aliases.
        def rooted(value):
            while isinstance(value, (ast.Subscript, ast.Attribute)):
                value = value.value
            return isinstance(value, ast.Name) and value.id in names

        for value in ast.walk(node):
            if isinstance(value, (ast.Name, ast.Subscript, ast.Attribute)):
                if isinstance(value.ctx, (ast.Store, ast.Del)) and rooted(value):
                    raise _Unsupported
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                if rooted(value.func.value) and value.func.attr not in {"count", "index", "copy"}:
                    raise _Unsupported

    def get(self, function, kinds, global_environment):
        # Function bodies can only read proved callable globals. Numeric or
        # mutable globals still require another direct representation. Snapshot
        # identities are part of the cache key so later rebindings cannot reuse
        # an earlier helper specialization.
        globals_at_call = {name: value for name, value in global_environment.items()
                           if isinstance(value, (_Function, _DequeConstructor))}
        context = tuple((name, id(value)) for name, value in sorted(globals_at_call.items()))
        key = (id(function.node), kinds, context)
        if key in self.variants:
            return self.variants[key]
        # Type-changing recursion is still recursion. Keep Python's frame and
        # RecursionError behavior instead of relying on Rust's host stack.
        if id(function.node) in self.active or len(self.active) >= 128:
            raise _Unsupported
        # Further specialization growth needs a direct-generation implementation.
        if len(self.variants) + len(self.active) >= 128:
            raise _Unsupported
        if any(kind not in {"int", "bool", "list_int", "float", "str"} for kind in kinds):
            raise _Unsupported
        self.active.add(id(function.node))
        rust_name = function.rust_name + "_" + ("_".join(kinds) or "void")
        if rust_name in self.names:
            rust_name += f"_context_{len(self.names)}"
        self.names.add(rust_name)
        variant = replace(function, rust_name=rust_name, dependencies=set(), required=set(), imports=set(),
                          global_bindings=globals_at_call)
        local = self.generator_type(self.bits, self.functions, variant, self.function_input,
                           self.constructors, self)
        local.global_environment = globals_at_call
        environment = {name: value for name, value in globals_at_call.items()
                       if name not in function.local_names}
        initializers, signature = [], []
        parameters = function.positional + function.kwonly
        arrays = {name for name, kind in zip(parameters, kinds) if kind == "list_int"}
        self.readonly_arrays(function.node, arrays)
        for index, (name, kind) in enumerate(zip(parameters, kinds)):
            argument = f"native_argument_{index}"
            if kind == "list_int":
                signature.append(f"{argument}: &[NativeInt]")
                environment[name] = _Binding(argument, _ListInfo(None))
                local.has_lists = True
            else:
                signature.append(f"{argument}: " + {"bool": "bool", "int": "NativeInt", "float": "f64", "str": "String"}[kind])
                initializers.append(f"{local.bind(name, kind, environment)} = {argument};")
        if self.function_input:
            signature.append("mut native_input: &mut NativeInput")
        signature.append("mut native_output: &mut String")
        body, remaining = local.statements(function.node.body, environment)
        if variant.return_kind != "none":
            if remaining is not None or len(local.return_kinds) != 1:
                raise _Unsupported
            variant.return_kind = next(iter(local.return_kinds))
        tail = "\nOk(())" if variant.return_kind == "none" and remaining is not None else ""
        variant.required.update(variant.imports)
        return_type = {"int": "NativeInt", "bool": "bool", "float": "f64", "str": "String", "none": "()"}[variant.return_kind]
        source = (f"#[inline]\nfn {variant.rust_name}({', '.join(signature)}) -> Result<{return_type}, NativeError> {{\n"
                  "use std::fmt::Write as _;\n" + _declarations(local) + "\n"
                  + "\n".join(initializers) + "\n" + body + tail + "\n}")
        self.variants[key] = variant
        self.sources.append(source)
        self.generators.append(local)
        self.active.remove(id(function.node))
        return variant


def _declarations(generator):
    types = {"int": "NativeInt", "bool": "bool", "int_bool": "NativeScalar", "list_int": "Vec<NativeInt>",
             "dict_int": "NativeDict", "set_int": "NativeSet",
             "matrix_int": "Vec<Vec<NativeInt>>", "deque_int": "std::collections::VecDeque<NativeInt>"}
    return "\n".join(f"let mut {slot};" if kind in {"float", "str"} else f"let mut {slot}: {types[kind]};"
                     for slot, kind in generator.bindings.items())


def try_generate_native(source: str, filename: str, integer: str, *, trusted_imports=frozenset(),
                        prune_output=True, diagnostic_out=None) -> str | None:
    """Return direct Rust, or None with an optional positioned diagnostic.

    Fixed-width modes use native Rust integers; BigInt selects the owned
    arbitrary-precision scalar backend. An unimplemented direct path fails.
    trusted_imports must come from Compiler's actual vendored-module resolution;
    a spelling such as "collections" in user source is insufficient evidence.
    """
    if integer == "bigint":
        from .native_bigint import try_generate_bigint
        return try_generate_bigint(source, filename, prune_output=prune_output,
                                   diagnostic_out=diagnostic_out)
    if integer not in {"i64", "i128"}:
        if diagnostic_out is not None:
            diagnostic_out.append(_direct_diagnostic(source, filename))
        return None
    from .native_scalar import ScalarGenerator, SCALAR_HELPERS, TEXT_INPUT_HELPERS
    try:
        tree = ast.parse(source, filename=filename)
        table = symtable.symtable(source, filename, "exec")
        # Builtins cannot be rebound even on a path that seems unreachable.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in ScalarGenerator.BUILTINS:
                raise _Unsupported
        bits = 64 if integer == "i64" else 128
        constructors = {}
        if "collections" in trusted_imports:
            for statement in tree.body:
                if isinstance(statement, ast.ImportFrom) and statement.module == "collections" and statement.level == 0:
                    for alias in statement.names:
                        if alias.name == "deque":
                            name = alias.asname or alias.name
                            constructors.setdefault(name, _DequeConstructor(name))
        statements, wrapper = _main_wrapper(tree)
        functions = {} if wrapper else _function_plans(tree, table, bits, ScalarGenerator)
        function_input = bool(functions) and any(isinstance(node, ast.Name) and node.id == "input" for node in ast.walk(tree))
        specializations = _Specializations(bits, functions, constructors, function_input, ScalarGenerator)
        generator = ScalarGenerator(bits, functions, function_input=function_input, constructors=constructors,
                               specializations=specializations)
        if function_input:
            generator.has_input = generator.needs_integer_runtime = True
        if wrapper:
            generator.return_label = "native_entrypoint"
            generator.entry_scope = wrapper[0]
        body, _ = generator.statements(statements, {})
        function_sources = specializations.sources
        for local in specializations.generators:
            for flag in ("needs_integer_runtime", "has_input", "has_lists", "has_dicts", "has_sets", "has_deques", "has_scalar_union", "has_extended_scalars", "has_iterator_frames", "has_slices", "has_text_methods"):
                setattr(generator, flag, getattr(generator, flag) or getattr(local, flag))
        if wrapper:
            body = f"'native_entrypoint: {{\n{body}\n}}"
    except (SyntaxError, _Unsupported, RecursionError) as error:
        if diagnostic_out is not None:
            diagnostic_out.append(_direct_diagnostic(source, filename, error))
        return None
    runtime = files("py2fastrust").joinpath("runtime")
    notice = runtime.joinpath("NOTICE.txt").read_text(encoding="utf-8")
    result = [
        "// Generated by py2fastrust: native scalar AOT backend.\n"
        "#![allow(dead_code, unused_imports, unused_variables, unused_mut, unused_assignments, unused_parens, unused_labels)]\n",
        f"const INT_BITS: u32 = {generator.bits};\ntype NativeInt = {integer};\n",
        "/*\n" + notice + "\n*/\n",
        _HELPERS,
        _OUTPUT_HELPERS,
    ]
    if generator.needs_integer_runtime:
        unicode_license = files("py2fastrust").joinpath("stdlib", "UNICODE_LICENSE.txt").read_text(encoding="utf-8")
        result.append("\n".join("// " + line for line in unicode_license.splitlines()) + "\n")
        result.append(runtime.joinpath("integer.rs").read_text(encoding="utf-8"))
    if generator.has_input:
        result.append(runtime.joinpath("streaming_io.rs").read_text(encoding="utf-8"))
        result.append(_INPUT_HELPERS if generator.needs_integer_runtime else TEXT_INPUT_HELPERS)
    if generator.has_extended_scalars:
        result.append(SCALAR_HELPERS)
        for license_name in ("PYTHON_LICENSE.txt", "UNICODE_LICENSE.txt"):
            license_text = files("py2fastrust").joinpath("stdlib", license_name).read_text(encoding="utf-8")
            result.append("\n".join("// " + line for line in license_text.splitlines()) + "\n")
    if generator.has_lists:
        result.append(_LIST_HELPERS)
    if generator.has_slices:
        from .native_slices import SLICE_HELPERS
        result.append(SLICE_HELPERS)
    if generator.has_text_methods:
        from .native_text_methods import HELPERS as TEXT_METHOD_HELPERS
        result.append(TEXT_METHOD_HELPERS)
    if generator.has_dicts:
        result.append(_DICT_HELPERS)
    if generator.has_sets:
        result.append(_SET_HELPERS)
    if generator.has_deques:
        result.append(_DEQUE_HELPERS)
    if generator.has_scalar_union:
        result.append(_SCALAR_UNION_HELPERS)
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
                      f'eprintln!("Traceback (most recent call last):\\n  File {{:?}}, line {call_line}, in <module>", {_string(filename)});\n'
                      "for &(line, function) in error.frames.iter().rev() {\n"
                      f'eprintln!("  File {{:?}}, line {{}}, in {{}}", {_string(filename)}, line, function);\n'
                      "}\n"
                      f'eprintln!("  File {{:?}}, line {{}}, in {{}}\\n{{}}", {_string(filename)}, error.line, error.function, error.message);\n'
                      "std::process::exit(1);\n}\n}\n")
    elif functions or generator.has_iterator_frames:
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
    source = "\n".join(result)
    if prune_output:
        from .rust_pruning import prune_rust_source
        source = prune_rust_source(source)
    return source
