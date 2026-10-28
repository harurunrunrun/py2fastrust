"""Direct Rust generation for proved scalar and container operations.

The analysis tracks definite bindings along control-flow paths. A Python name
can change type by moving to a different typed Rust slot; compatible paths join
through scalar copies or uniquely owned integer-container moves. No user
expression is executed during analysis. Missing direct lowering is reported to
the public API; it never selects a general execution backend.
"""

import ast
from .native_types import (TupleType,TupleSequenceType,ListType,MaybeType,TypedListInfo,rust_type,kind_tag,
                           is_maybe,unmaybe,maybe_type,immutable,list_type,default_value,
                           UnionType,NullableType,join_types,EmptyType,EMPTY)
from dataclasses import dataclass, field, replace
from importlib.resources import files
import symtable

from .typeflow import TypeSet
from .native_constraints import ConstraintFailure
from .native_constraint_lowering import result_shapes
from .diagnostics import Diagnostic
from .call_semantics import FunctionSignature, CallBindingError, normalize_call
from .references import DequeConstructor as _DequeConstructor, CANONICAL_REBINDABLES


class _Unsupported(Exception):
    """A missing native operation or proof, with optional source context."""
    def __init__(self, reason=None, *, node=None, operation=None, types=(), proof=None):
        if isinstance(reason,ast.AST):
            positional_node=reason
            node=positional_node if node is None else node
            reason=None
            super().__init__(positional_node)
        else:
            super().__init__(*(()if reason is None else(reason,)))
        self.reason=reason
        self.node=node
        self.operation=operation
        self.operand_types=tuple(types)
        self.proof=proof


def _static_reference(value):
    return isinstance(value, (_Function, _DequeConstructor)) or getattr(value, "_native_reference", False)


def _direct_diagnostic(source, filename, error=None, node=None, unit=None):
    from .native_diagnostics import direct_diagnostic
    return direct_diagnostic(source,filename,error,node,unit)


@dataclass(frozen=True)
class _EdgeMove:
    """A single typed CFG transfer, kept structural until edge emission."""
    destination: str
    kind: object
    source: object = None

    def render(self,generator):
        value="None" if self.source is None else generator.coerce(_Expression(self.source.slot,self.source.kind),self.kind)
        return f"{self.destination} = {value};"


@dataclass(frozen=True)
class _Expression:
    code: str
    kind: object
    constant: int | bool | None = None
    owned: bool = True
    length: int | None = None
    nonempty: bool = False
    stable_borrow: bool = False
    char_code: str | None = None
    text_view: str | None = None
    sequence_view: object | None = None



def _text_expression(code, **metadata):
    """Convert a concrete builder/view result to canonical immutable text."""
    return _Expression(f"NativeText::from({code})","str",**metadata)


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
class _DictInfo:
    length: int | None
    nonempty: bool = False


@dataclass(frozen=True)
class _SetInfo:
    length: int | None


@dataclass(frozen=True)
class _MaybeInfo:
    """A scalar that may still be unbound on a control-flow path."""
    kind: object
    owner: str | None


@dataclass(frozen=True)
class _Binding:
    slot: str
    info: object

    @property
    def kind(self):
        if isinstance(self.info, _MaybeInfo):
            return maybe_type(self.info.kind)
        if getattr(self.info,"_key_info",False):return self.info.kind
        if isinstance(self.info,TypedListInfo):
            return self.info.kind
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
    _native_reference=True
    node: ast.FunctionDef
    rust_name: str
    positional: list[str]
    posonly: set[str]
    kwonly: list[str]
    defaults: dict[str, _Expression]
    local_names: set[str]
    return_kind: object
    dependencies: set[ast.FunctionDef]
    required: set[str]
    imports: set[str]
    global_bindings: dict[str, object] = field(default_factory=dict)
    signature: FunctionSignature | None = None
    global_names: frozenset[str] | None = None
    absent_globals: set[str] = field(default_factory=set)


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
    if b == 0 { return Err("ZeroDivisionError: division by zero".into()); }
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
}
fn native_space(character: char) -> bool {
    character.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&character)
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

'''


_DICT_HELPERS = r'''
// Values are scalars and every dictionary has one proved owner. Entries retain
// Python insertion order while the hash index provides expected O(1) lookup.
struct NativeDict {
    entries: NativeDictionaryEntries<(NativeInt, NativeInt)>,
    index: std::collections::HashMap<NativeInt, usize>,
}
impl NativeDict {
    fn clear(&mut self) { self.entries.clear(); self.index.clear(); }
    fn new() -> Self {
        Self { entries: NativeDictionaryEntries::new(), index: std::collections::HashMap::new() }
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
    fn set(&mut self, key: NativeInt, value: NativeInt) -> Result<(), String> {
        if let Some(&index)=self.index.get(&key){self.entries[index].1=value;return Ok(());}
        self.index.try_reserve(1).map_err(|_|"MemoryError: cannot allocate dictionary index".to_owned())?;
        let index=native_dict_insert(&mut self.entries,(key,value))?;
        self.index.insert(key,index);Ok(())
    }
    fn delete(&mut self,key:NativeInt)->bool {
        match self.index.remove(&key){Some(slot)=>{native_dict_remove(&mut self.entries,&mut self.index,slot);true},None=>false}
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
    BUILTINS = {"int", "input", "print", "range", "reversed", "abs", "pow", "len", "sum", "any", "all", "min", "max", "list", "map", "filter", "enumerate", "zip", "dict", "set", "sorted", "iter", "next"}

    def __init__(self, bits, functions=None, function=None, function_input=False, constructors=None, specializations=None,
                 string_mode="ascii"):
        self.bits = bits
        self.string_mode = string_mode
        self.bindings = {}
        self.counter = 0
        self.loops = []
        self.needs_integer_runtime = False
        self.has_fixed_parsing = False
        self.has_input = False
        self.has_lists = False
        self.has_dicts = False
        self.has_mapping_delete = False
        self.has_sets = False
        self.has_deques = False
        self.has_scalar_union = False
        self.iterating_lists = []
        self.return_label = None
        self.functions = functions or {}
        self.global_environment = None
        self.global_names = None
        self.source_unit = None
        self.function = function
        self.function_input = function_input
        self.constructors = constructors or {}
        self.specializations = specializations
        self.return_kinds = set()
        self.return_values = {}
        self.union_types = set()
        self.type_analysis=None
        self.constraint_facts=None
        self.range_facts={}
        self.constraint_header_slots={}
        self.has_empty_type=False
        self.expression_scopes = []
        self.expression_trace_id = None
        self.expression_mutations = []
        self.has_iterator_frames = False
        self.has_callback_frames = False
        self.has_slices = False
        self.has_text_methods = False
        self.text_predicates=set()
        self.has_big_text = False
        self.has_key_containers = False
        self.has_tuples = False
        self.has_typed_lists = False
        self.has_native_words = False
        self.has_stdio = False
        self.has_native_modules = False
        self.borrowed_slots = set()
        self.trusted_imports = frozenset()
        self.entry_local_names = set()
        self.entry_scope = None

    def temporary(self):
        self.counter += 1
        return f"native_temp_{self.counter}"

    def normalize(self, value):
        from .literal_semantics import integer_policy
        return integer_policy(self.bits).normalize(value)

    def literal(self, value):
        from .literal_semantics import integer_policy
        return integer_policy(self.bits).rust_literal(value,_string)

    @staticmethod
    def text_is_ascii(value):
        """Physical text predicate over an already captured immutable owner."""
        return f"({value.code}).is_ascii()"

    def slot(self, kind):
        inner=unmaybe(kind)
        if isinstance(inner,(TupleType,TupleSequenceType,ListType,UnionType,NullableType,EmptyType)) or getattr(inner,"_key_container",False):
            self.register_type(inner)
            slot=f"native_var_{len(self.bindings)}"
            self.bindings[slot]=kind
            return slot
        if is_maybe(kind):
            inner = unmaybe(kind)
            if inner not in {"int", "bool", "int_bool", "float", "str", "bytes", "none", "list_int", "dict_int", "set_int", "matrix_int", "deque_int"}:
                raise _Unsupported
            # Register scalar helper requirements through the ordinary slot
            # factory without retaining an extra user-value binding.
            probe = self.slot(inner)
            del self.bindings[probe]
            self.bindings[probe] = kind
            return probe
        if kind not in {"int", "bool", "int_bool", "list_int", "dict_int", "set_int", "matrix_int", "deque_int", "bytes", "none"}:
            raise _Unsupported
        if kind == "int_bool":
            self.has_scalar_union = True
        slot = f"native_var_{len(self.bindings)}"
        self.bindings[slot] = kind
        return slot

    def register_type(self,kind):
        kind=unmaybe(kind)
        if isinstance(kind,EmptyType):self.has_empty_type=True
        elif isinstance(kind,UnionType):
            self.union_types.add(kind)
            for value in kind.alternatives:self.register_type(value)
        elif isinstance(kind,NullableType):self.register_type(kind.value)
        elif getattr(kind,"_key_container",False):
            self.has_key_containers=True
            self.register_type(kind.key)
            if kind._key_container=="dict":self.register_type(kind.value)
        elif kind=="int_bool":self.has_scalar_union=True
        elif kind=="str":
            if self.bits:self.has_extended_scalars=True
            else:self.has_big_text=True
        elif isinstance(kind,TupleSequenceType):
            self.has_tuples=True
            self.register_type(kind.element)
        elif isinstance(kind,TupleType):
            self.has_tuples=True
            for field in kind.fields:self.register_type(field)
        elif isinstance(kind,ListType):
            self.has_typed_lists=True
            self.register_type(kind.element)

    def text_from_codepoint(self, code):
        """Materialize a captured, valid Unicode scalar only when text escapes."""
        self.register_type("str")
        return _Expression(f'NativeText::from(char::from_u32({code}).expect("native character codepoint"))',
                           "str", length=1, nonempty=True, char_code=code)

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
        if isinstance(expression.kind,EmptyType):return f"native_empty::<NativeInt>({expression.code})"
        if expression.kind == "int":
            return expression.code
        if expression.kind == "bool":
            return f"(({expression.code}) as NativeInt)"
        if expression.kind == "int_bool":
            return f"({expression.code}).integer()"
        raise _Unsupported

    @staticmethod
    def coerce(expression, kind):
        if isinstance(expression.kind,EmptyType):return f"native_empty::<{rust_type(kind)}>({expression.code})"
        from .native_tuples import coerce_structural
        from .native_unions import coerce_union
        finite=coerce_union(expression,kind,_Generator.coerce)
        if finite is not None:return finite
        if is_maybe(kind):
            if expression.kind==kind:
                if not immutable(unmaybe(kind)):
                    if not expression.owned:raise _Unsupported
                    return expression.code
                if unmaybe(kind) in {"int","bool","int_bool","float"}:return expression.code
                return f"({expression.code}).clone()"
            if is_maybe(expression.kind):
                if not immutable(unmaybe(expression.kind)):
                    if not expression.owned:raise _Unsupported
                    item=_Expression("native_optional",unmaybe(expression.kind))
                    return f"({expression.code}).map(|native_optional|{_Generator.coerce(item,unmaybe(kind))})"
                item=_Expression("native_optional.clone()",unmaybe(expression.kind))
                return f"({expression.code}).as_ref().map(|native_optional|{_Generator.coerce(item,unmaybe(kind))})"
            return f"Some({_Generator.coerce(expression,unmaybe(kind))})"
        from .native_nested_lists import coerce as shared_coerce
        shared=shared_coerce(expression,kind)
        if shared is not None:return shared
        from .native_constraints import canonical_kind
        source_shape=canonical_kind(expression.kind);target_shape=canonical_kind(kind)
        if isinstance(source_shape,ListType) and isinstance(target_shape,ListType):
            return coerce_structural(replace(expression,kind=source_shape),target_shape,_Generator.coerce)
        structural=coerce_structural(expression,kind,_Generator.coerce)
        if structural is not None:return structural
        if expression.kind == kind:
            return f"({expression.code}).clone()"if kind=="str"else expression.code
        if kind == "int_bool" and expression.kind in {"int", "bool"}:
            variant = "Int" if expression.kind == "int" else "Bool"
            return f"NativeScalar::{variant}({expression.code})"
        raise _Unsupported

    def scalar_kind(self, expressions):
        kind=None
        for value in expressions:
            kind=value.kind if kind is None else join_types(kind,value.kind)
            if kind is None:
                raise _Unsupported("the expression alternatives have no compatible finite native result representation",types=tuple((f"alternative {i+1}",item.kind)for i,item in enumerate(expressions)),proof="finite expression-result type")
        if kind is None or not immutable(kind):
            raise _Unsupported("this expression-result handler only supports immutable values; native move/shared carriers for mutable branch or boolean-expression results are not implemented",types=tuple((f"alternative {i+1}",item.kind)for i,item in enumerate(expressions)),proof="expression-result storage preserving mutable identity")
        self.register_type(kind)
        return kind

    @staticmethod
    def truth(expression):
        if isinstance(expression.kind,EmptyType):return f"native_empty::<bool>({expression.code})"
        if getattr(expression.kind,"_key_container",False):return f"!({expression.code}).is_empty()"
        if isinstance(expression.kind,TupleSequenceType):return f"!({expression.code}).is_empty()"
        if isinstance(expression.kind,TupleType):
            return f"{{let _=&({expression.code}); {str(bool(expression.kind.fields)).lower()}}}"
        from .native_types import SharedListType
        if isinstance(expression.kind,SharedListType):return f"native_shared_len(&({expression.code}))!=0"
        if isinstance(expression.kind,ListType):return f"!({expression.code}).is_empty()"
        if expression.kind in {"list_int", "dict_int", "set_int", "matrix_int", "deque_int", "bytes"}:
            return f"!({expression.code}).is_empty()"
        if expression.kind == "int_bool":
            return f"({expression.code}).truth()"
        if expression.kind not in {"int", "bool"}:
            raise _Unsupported
        return expression.code if expression.kind == "bool" else f"(({expression.code}) != 0)"

    def condition(self,node,environment):
        from .native_conditions import lower
        return lower(self,node,environment)

    @staticmethod
    def binding(expression):
        if getattr(expression.kind,"_key_container",False):
            from .native_key_types import KeyInfo
            return KeyInfo(expression.kind,expression.length,expression.nonempty)
        from .native_types import SharedListType
        if isinstance(expression.kind,SharedListType):return TypedListInfo(expression.kind,None)
        if isinstance(expression.kind,ListType):return TypedListInfo(expression.kind,expression.length)
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
        from .native_iterators import Planner, stream_item
        from .native_typed_lists import _collect
        from .native_stream_plans import context
        plan = context(self, environment).producer(node)
        source = Planner(self).lower(plan, environment, allow_set=True)
        if stream_item(self, source).kind != "int":
            raise _Unsupported
        if source.fields == (("int", "@", True),):
            return source.construct(), source.iterator
        value = _collect(self, source, node)
        owner = self.temporary()
        return f"let {owner}={value.code};", f"{owner}.into_iter()"


    def user_call(self, node, function, environment):
        try:
            call_arguments=normalize_call(node)
        except CallBindingError:
            raise _Unsupported from None
        signature=getattr(function,"signature",None) or FunctionSignature.declaration(
            function.positional,positional_only=function.posonly,keyword_only=function.kwonly,default_names=function.defaults)
        lines=[]
        # Evaluate every explicit argument in source order before reordering
        # into Rust's fixed signature. Defaults are proved pure constants.
        def argument_value(argument):
            value = self.expression(argument, environment)
            if value.kind not in {"int", "bool", "int_bool", "none", "list_int", "float", "str", "bytes"} and not isinstance(value.kind,(TupleType,TupleSequenceType,ListType,UnionType,NullableType)):
                raise _Unsupported
            if list_type(value.kind) and not value.owned:
                # Resolve the binding now, including an unbound-name error,
                # and defer borrowing until later arguments have run.
                # Row lookups have bounds checks/effects and require a richer
                # reference representation before they can be accepted here.
                if not isinstance(argument, ast.Name):
                    raise _Unsupported
                from .native_container_reads import capture
                read = capture(self,argument,value,environment)
                lines.append(read.setup)
                return _Expression(read.owner,value.kind,owned=False,length=value.length,
                                   nonempty=value.nonempty)
            name = self.temporary()
            code=self.coerce(value,value.kind) if isinstance(value.kind,(TupleType,TupleSequenceType,UnionType,NullableType)) and not value.owned else value.code
            lines.append(f"let {name} = {code};")
            return _Expression(name, value.kind, owned=value.owned)

        try:
            call_plan=signature.plan(call_arguments)
            bound=call_plan.capture(lambda expression,parameter:argument_value(expression),defaults=function.defaults)
        except CallBindingError:
            raise _Unsupported from None
        arguments, kinds = [], []
        from .native_types import SharedListType
        for parameter,value in zip(bound.parameters,bound.values):
            kinds.append(value.kind)
            arguments.append(f"&({value.code})" if list_type(value.kind)and not isinstance(value.kind,SharedListType) else value.code)
        namespace=getattr(self,"inline_callback_globals",None)
        if namespace is not None:globals_at_call,names=namespace
        else:
            globals_at_call = environment if self.function is None else self.global_environment
            names=set(environment)if self.function is None else self.global_names
        variant = self.specializations.get(function, tuple(kinds), globals_at_call,global_names=names)
        if self.function is None:
            # A callee's globals are looked up at call time, including indirect
            # callees whose definitions may follow the caller definition.
            if (any(globals_at_call.get(name) is not variant.global_bindings.get(name) for name in variant.required)
                    or any(name in globals_at_call for name in variant.absent_globals)):
                raise _Unsupported
        else:
            self.function.dependencies.add(function.node)
            self.function.required.update(variant.required)
            self.function.absent_globals.update(variant.absent_globals)
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
        from .native_deques import constructor
        return constructor(self,node,environment)

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

    @result_shapes
    def expression(self, node, environment):
        if isinstance(node,(ast.Compare,ast.BoolOp,ast.IfExp)):
            from .native_expression_flow import lower
            return lower(self,node,environment)
        from .native_deques import try_expression as deque_expression
        deque=deque_expression(self,node,environment)
        if deque is not None:return deque
        from .native_clear import try_expression as clear_expression
        cleared=clear_expression(self,node,environment)
        if cleared is not None:return cleared
        from .native_characters import read_local
        character=read_local(self,node,environment)
        if character is not None:return character
        from .native_constraint_lowering import allocation_expression
        allocated=allocation_expression(self,node,environment)
        if allocated is not None:return allocated
        from .native_unions import leaf_expression
        leaf=leaf_expression(self,node,environment)
        if leaf is not None:return leaf
        from .native_module_calls import try_expression as module_expression
        module=module_expression(self,node,environment)
        if module is not None:return module
        from .native_stdio import try_expression
        stdio = try_expression(self,node,environment)
        if stdio is not None:
            return stdio
        from .native_key_containers import try_expression as key_expression
        keyed=key_expression(self,node,environment)
        if keyed is not None:return keyed
        from .native_typed_lists import try_expression
        typed=try_expression(self,node,environment)
        if typed is not None:return typed
        from .native_next import try_expression
        following=try_expression(self,node,environment)
        if following is not None:return following
        from .native_tuples import try_expression
        structural=try_expression(self,node,environment)
        if structural is not None:return structural
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
            from .literal_semantics import Literal
            literal=Literal.from_ast(node)
            if literal is not None and literal.kind in {"int","bool"}:
                value=self.normalize(literal.value) if literal.kind=="int" else literal.value
                return _Expression(literal.rust_atom(self.literal,_string),literal.kind,value)
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
            if isinstance(info,TypedListInfo):
                return _Expression(information.slot,info.kind,owned=False,length=info.length)
            if isinstance(info, _MaybeInfo):
                if info.owner is None:
                    message = f"NameError: name '{node.id}' is not defined"
                elif self.scope_name() != info.owner:
                    message = f"NameError: cannot access free variable '{node.id}' where it is not associated with a value in enclosing scope"
                else:
                    message = f"UnboundLocalError: cannot access local variable '{node.id}' where it is not associated with a value"
                clone=".cloned()" if immutable(info.kind) else ""
                read = f"{information.slot}.as_ref(){clone}.ok_or_else(|| String::from({_string(message)}))"
                return _Expression(self.at(read, node), info.kind,owned=immutable(info.kind))
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
                          self.at(f"{result}.set({key_name}, {value_name})",node)+";"]
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
                from .native_sequence_storage import row_expression
                return row_expression(self,node,values,index,environment)
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
            if len(node.generators) != 1 or node.generators[0].is_async or not isinstance(node.generators[0].target, ast.Name):
                raise _Unsupported
            comprehension = node.generators[0]
            setup, iterator, arguments = self.range_iterator(comprehension.iter, environment)
            target = comprehension.target.id
            local = self.temporary()
            inside = environment.copy()
            inside[target] = _Binding(local, "int")
            filters = [self.condition(condition, inside) for condition in comprehension.ifs]
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
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name == "dict" and not node.args:
                self.has_dicts = True
                return _Expression("NativeDict::new()", "dict_int", length=0)
            if name == "list" and not node.args:
                self.has_lists = True
                return _Expression("Vec::<NativeInt>::new()", "list_int", length=0)
            if name == "int" and not node.args:
                return _Expression(self.literal(0), "int", 0)
            if name == "int" and len(node.args) == 1:
                argument = node.args[0]
                if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Name) and argument.func.id == "input" and not argument.args and not argument.keywords:
                    from .native_integer_parsing import enable
                    enable(self)
                    self.has_input = True
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
            self.expression_mutations.append(environment[target.id])
            self.update_info(environment, target.id, _DequeInfo(None))
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
        from .native_list_operations import binary
        sequence=binary(self,operator,left,right,node)
        if sequence is not None:return sequence
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
        from .native_stream_lowering import integer_range
        return integer_range(self,node,environment)

    def statements(self, statements, environment):
        environment = environment.copy()
        code = []
        for statement in statements:
            if environment is None:
                break
            rendered, environment = self.statement(statement, environment)
            code.append(rendered)
        return "\n".join(code), environment

    def join(self, environments, preferred=None, *, structured=False):
        """Merge normal paths, emitting moves into a typed phi slot per name.

        Scalar names that are absent on a path use Option<T>. Reads retain a
        source-located unbound-name check; established paths stay native T.
        """
        live = [environment for environment in environments if environment is not None]
        moves = [[] for _ in environments]
        if not live:
            return None, moves
        result = {}
        names = dict.fromkeys(name for environment in live for name in environment)
        for name in names:
            values = [environment.get(name) for environment in live]
            first = next(value for value in values if value is not None)
            if _static_reference(first):
                if all(value is first for value in values):
                    result[name] = first
                continue
            if not isinstance(first, _Binding):
                continue
            optional = any(value is None or isinstance(value, _Binding) and isinstance(value.info, _MaybeInfo)
                           for value in values)
            types = TypeSet()
            for value in values:
                if isinstance(value, _Binding):
                    current = value.info.kind if isinstance(value.info, _MaybeInfo) else value.kind
                    from .native_constraints import canonical_kind
                    types = types.join(TypeSet.from_kind(canonical_kind(current)))
                elif value is not None:
                    types = types.join(TypeSet(unknown=True))
            from .native_types import SharedListType
            physical=[unmaybe(value.kind) for value in values if isinstance(value,_Binding)]
            kind=types.native_kind
            from .native_expression_results import has_shared,join_layouts
            if kind is not None and any(has_shared(item)for item in physical):
                kind=physical[0]
                for item in physical[1:]:kind=join_layouts(kind,item)
            if kind is not None:
                from .native_constraints import native_kind
                kind=native_kind(kind,self.bits)
            if kind is None:
                continue
            if kind == "int_bool":
                self.has_scalar_union = True
            infos = [value.info for value in values if isinstance(value, _Binding)]
            if optional:
                owner = self.function.node.name if self.function else self.entry_scope
                info = _MaybeInfo(kind, owner)
                kind = maybe_type(kind)
            else:
                info = kind if kind == "int_bool" or isinstance(kind,(TupleType,TupleSequenceType,UnionType,NullableType)) else infos[0]
                if isinstance(kind,ListType):
                    lengths=[info.length for info in infos if isinstance(info,TypedListInfo)]
                    info=TypedListInfo(kind,lengths[0] if lengths and all(length==lengths[0] for length in lengths) else None)
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
            elif all(isinstance(value, _Binding) and value.kind == kind and value.slot == first.slot for value in values):
                slot = first.slot
            else:
                slot = self.slot(kind)
            result[name] = _Binding(slot, info)
            for index, environment in enumerate(environments):
                if environment is not None:
                    source = environment.get(name)
                    if source is None:
                        moves[index].append(_EdgeMove(slot,kind))
                    elif source.slot != slot:
                        moves[index].append(_EdgeMove(slot,kind,source))
        return result, moves if structured else [[move.render(self) for move in edge] for edge in moves]

    @staticmethod
    def after_loop(environment):
        # A body can resize or replace a list on any normal/break/continue
        # path. Its pre-loop cardinality is no longer a valid proof.
        result = {}
        for name, binding in environment.items():
            if isinstance(binding, _Binding):
                info = binding.info
                if getattr(info,"_key_info",False):
                    from .native_key_types import KeyInfo
                    info=KeyInfo(info.kind,None,False)
                widened = (TypedListInfo(info.kind,None) if isinstance(info,TypedListInfo) else _ListInfo(None) if isinstance(info, _ListInfo)
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
        from .native_constraint_lowering import loop_header
        return loop_header(self,node,environment)

    def finish_loop(self, node, entry, header, context, body, remaining, nonempty, may_repeat, zero=False):
        from .native_constraint_lowering import finish_loop
        return finish_loop(self,node,entry,header,context,body,remaining,nonempty,may_repeat,zero)

    def statement(self, node, environment):
        from .native_nested_lists import try_statement as shared_statement
        shared=shared_statement(self,node,environment)
        if shared is not None:return shared
        from .native_deques import import_statement as deque_import
        imported=deque_import(self,node,environment)
        if imported is not None:return imported
        from .native_constraint_lowering import reset_statement
        reset=reset_statement(self,node,environment)
        if reset is not None:return reset
        from .native_module_calls import try_statement as module_statement
        module=module_statement(self,node,environment)
        if module is not None:return module
        from .native_stdio import try_statement
        stdio = try_statement(self,node,environment)
        if stdio is not None:
            return stdio
        from .native_key_containers import try_statement as key_statement
        keyed=key_statement(self,node,environment)
        if keyed is not None:return keyed
        from .native_typed_lists import try_statement
        typed=try_statement(self,node,environment)
        if typed is not None:return typed
        from .native_tuples import try_statement
        structural=try_statement(self,node,environment)
        if structural is not None:return structural
        alias = self.function_alias_assignment(node, environment)
        if alias is not None:
            return alias
        if isinstance(node, ast.For):
            from .native_iterators import try_for_loop
            return try_for_loop(self, node, environment)
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
            if self.function is not None:
                raise _Unsupported("a nested function needs a new callable object and captured lexical cells on each enclosing call; native closure/function-object binding is not implemented",node=node,operation=f"nested function definition {node.name!r}",proof="closure-cell lifetime and callable identity")
            if function is None or function.node is not node:
                raise _Unsupported("the function definition has no matching lexical native call plan",node=node,proof="definition/callable identity")
            environment[node.name] = function
            return "", environment
        if isinstance(node, ast.Return) and self.function is not None:
            value = self.expression(node.value, environment) if node.value is not None else _Expression("()","none")
            if not immutable(value.kind):
                binding=environment.get(node.value.id) if isinstance(node.value,ast.Name) else None
                if not value.owned and (not isinstance(binding,_Binding) or binding.slot not in self.bindings):
                    raise _Unsupported
            self.register_type(value.kind)
            self.return_kinds.add(value.kind)
            marker="// "+self.temporary()+"_typed_return"
            if not immutable(value.kind) and not value.owned:value=replace(value,owned=True)
            self.return_values[marker]=(node,value)
            return marker,None
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
                    setter=self.at(f"{values.code}.set({offset}, {result})",node)
                    return f"let {result} = {value.code};\nlet {offset} = {index.code};\n{setter};", environment
                setter = self.at(f"native_set(&mut {values.code}, {offset}, {result})", node)
                return f"let {result} = {value.code};\nlet {offset} = {self.number(index)};\n{setter};", environment
            if not all(isinstance(target, ast.Name) and target.id not in self.iterating_lists for target in node.targets):
                raise _Unsupported
            from .native_types import reference_cloneable
            if not reference_cloneable(value.kind) and (not value.owned or len(node.targets) != 1):
                raise _Unsupported("these names would share one mutable container, but the selected storage requires a proved unique owner; alias-preserving shared mutable storage is not implemented for this assignment",node=node,types=(("value",value.kind),),proof="mutable alias identity and lifetime")
            name = self.temporary()
            assigned=self.coerce(value,value.kind) if reference_cloneable(value.kind) and not value.owned else value.code
            lines = [f"let {name} = {assigned};"]
            for index,target in enumerate(node.targets):
                item=self.coerce(_Expression(name,value.kind),value.kind) if index+1<len(node.targets) else name
                lines.append(f"{self.bind(target.id, value, environment)} = {item};")
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
                setter=self.at(f"{values.code}.set({offset}, {result})",node)
                return f"let {offset} = {index.code};\nlet {old} = {getter};\nlet {result} = {value.code};\n{setter};", environment
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
            if self.function is None and self.functions and "__name__" not in environment and _main_guard(node):
                return self.statements(node.body, environment)
            test = self.condition(node.test, environment)
            yes, yes_environment = self.statements(node.body, environment)
            no, no_environment = self.statements(node.orelse, environment)
            joined, moves = self.join([yes_environment, no_environment])
            yes += "\n" + "\n".join(moves[0])
            no += "\n" + "\n".join(moves[1])
            return f"if {self.truth(test)} {{\n{yes}\n}} else {{\n{no}\n}}", joined
        if isinstance(node, (ast.For, ast.While)):
            if node.orelse:
                raise _Unsupported
            refinement = ""
            label = self.temporary()
            context = {"label": label, "edges": []}
            header_initializers, widened = self.loop_header(node, environment)
            if isinstance(node, ast.While):
                # Subsequent iterations may see containers resized or replaced
                # by the body. Their entry cardinality is not a loop invariant.
                test = self.condition(node.test, widened)
                self.loops.append(context)
                body, remaining = self.statements(node.body, widened)
                self.loops.pop()
                nonempty = test.constant is not None and bool(test.constant)
                zero = test.constant is not None and not bool(test.constant)
                initialization, body, joined = self.finish_loop(node, environment, widened, context, body, remaining,
                                                               nonempty, not zero, zero)
                return f"{refinement}\n{header_initializers}\n{initialization}\n'{label}: while {self.truth(test)} {{\n{body}\n}}", joined
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
            destination = context.get(kind + "_label", context["label"])
            prefix = f"{context['break_flag']} = true;\n" if kind == "break" and context.get("break_flag") else ""
            return f"{marker}\n{prefix}{kind} '{destination};", None
        if isinstance(node, ast.Expr):
            call = node.value
            if isinstance(call, ast.Constant) and type(call.value) is str:
                return ";", environment
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
                raise _Unsupported
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
                if any(value.kind not in ({"list_int", "deque_int"} if star else {"int", "bool", "int_bool", "str"})
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
                    formatted = name if value.kind != "bool" else f'(if {name} {{ "True" }} else {{ "False" }})'
                    lines.append(f'write!(&mut native_output, "{{}}", {formatted}).unwrap();')
                lines.append(f"native_output.push_str({_string(end)});")
                if flush: lines.append(self.at("native_flush_output(&mut native_output)", node) + ";")
                return "\n".join(lines), environment
            expression = self.expression(call, environment)
            return f"let _ = {'&(' + expression.code + ')' if (expression.kind in {'list_int', 'dict_int', 'set_int', 'matrix_int', 'deque_int'} or isinstance(expression.kind,ListType) or getattr(expression.kind,"_key_container",False)) and not expression.owned else expression.code};", environment
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


def _function_plans(tree, table, bits, generator_type=_Generator, unit=None):
    functions = _FunctionPlans()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        parameters = node.args
        arguments = parameters.posonlyargs + parameters.args + parameters.kwonlyargs
        if node.name in generator_type.BUILTINS | {"__builtins__", "__name__"}:
            raise _Unsupported("a function definition replaces a builtin/reserved binding; native callable versioning for this definition is not implemented",node=node)
        if node.decorator_list:
            raise _Unsupported("decorator calls can replace the function object at definition time; native decorated-callable storage is not implemented",node=node.decorator_list[0],operation=f"decorator of function {node.name!r}")
        if node.type_params:
            raise _Unsupported("generic type-parameter objects and lazy bound/default evaluation are not implemented for native functions",node=node,operation=f"generic function definition {node.name!r}")
        if node.returns is not None or any(argument.annotation is not None for argument in arguments):
            raise _Unsupported("lazy function-annotation objects and their namespace evaluation are not implemented on this native function path",node=node,operation=f"annotations of function {node.name!r}")
        for parameter,label in ((parameters.vararg,"positional"),(parameters.kwarg,"keyword")):
            if parameter is not None:
                raise _Unsupported(f"variadic {label} arguments require packing and binding {'a tuple'if label=='positional'else'a dictionary'} for {parameter.arg!r}; that native call-frame storage is not implemented",node=parameter,operation=f"signature of function {node.name!r}")
        suspended=next((value for value in ast.walk(node)if isinstance(value,(ast.Yield,ast.YieldFrom,ast.Await,ast.AsyncFor,ast.AsyncWith))),None)
        if suspended is not None:
            raise _Unsupported("this suspension requires a resumable native generator/coroutine frame; function suspension is not implemented on this path",node=suspended)

        if unit is not None:
            signature=unit.signature_for(node)
        else:
            matches=[child for child in table.get_children()if child.get_name()==node.name and child.get_lineno()==node.lineno]
            if len(matches)!=1:raise _Unsupported
            local_names={symbol.get_name()for symbol in matches[0].get_symbols()if symbol.is_local()or symbol.is_parameter()}
            signature=FunctionSignature.from_ast(node,local_names=local_names)
        local_names=set(signature.local_names)
        positional=list(signature.positional)
        defaults={}
        default_generator=generator_type(bits)
        # Capture only proved immutable defaults during definition planning.
        # The shared call binder consumes these values and never reevaluates AST.
        default_nodes=[(slot.name,slot.expression)for slot in signature.defaults]
        for name, value in default_nodes:
            if isinstance(value,(ast.List,ast.Set,ast.Dict)):
                raise _Unsupported(f"default parameter {name!r} must retain one shared mutable object across calls; native definition-time default-cell storage is not implemented",node=value,operation=f"default of function {node.name!r}",proof="shared default-object identity")
            if isinstance(value,ast.Tuple):
                if any(not isinstance(item,(ast.Tuple,ast.Load,ast.Constant,ast.BinOp,ast.UnaryOp,ast.operator,ast.unaryop))
                       or isinstance(item,ast.Constant) and type(item.value) not in {int,bool,str} for item in ast.walk(value)):
                    raise _Unsupported(f"tuple default parameter {name!r} lacks a proved immutable, identity-preserving native representation for every element",node=value,operation=f"default of function {node.name!r}",proof="immutable default storage")
                from .native_types import tuple_code
                def tuple_default(item):
                    if isinstance(item,ast.Tuple):
                        fields=[tuple_default(field) for field in item.elts]
                        return _Expression(tuple_code(field.code for field in fields),TupleType(tuple(field.kind for field in fields)))
                    field=default_generator.expression(item,{})
                    if field.kind not in {"int","bool","str"} or field.kind!="str" and field.constant is None:
                        raise _Unsupported
                    return field
                defaults[name]=tuple_default(value)
                continue
            if isinstance(value,ast.Constant) and value.value is None:
                defaults[name]=_Expression("()","none")
                continue
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
                raise _Unsupported(f"default parameter {name!r} needs definition-time expression evaluation and capture; calls, name lookups and their effects/exceptions cannot be folded away, and native initialization for this default is not implemented",node=value,operation=f"default of function {node.name!r}",proof="definition-time evaluation and capture")
            expression = default_generator.expression(value, {})
            if expression.kind not in {"int", "bool"} or expression.constant is None:
                raise _Unsupported(f"default parameter {name!r} is not a proved exception-free constant; native fallible default initialization is not implemented",node=value,operation=f"default of function {node.name!r}",types=(("default",expression.kind),))
            code = (str(expression.constant).lower() if expression.kind == "bool"
                    else default_generator.literal(expression.constant))
            defaults[name] = _Expression(code, expression.kind, expression.constant)
        value_returns = [statement for statement in ast.walk(node) if isinstance(statement, ast.Return)
                         and statement.value is not None
                         and not (isinstance(statement.value, ast.Constant) and statement.value.value is None)]
        function = _Function(node, f"native_function_{len(functions.definitions)}", positional,
                                        set(signature.positional_only),
                                        list(signature.keyword_only), defaults,
                                        local_names, "int" if value_returns else "none", set(), set(), set(), signature=signature)
        functions[node.name] = function
        functions.definitions[node] = function
    return functions


class _Specializations:
    """Prove and emit only the exact argument-kind variants actually called."""

    def __init__(self, bits, functions, constructors, function_input, generator_type=_Generator,
                 string_mode="ascii"):
        self.bits = bits
        self.string_mode = string_mode
        self.functions = functions
        self.constructors = constructors
        self.function_input = function_input
        self.generator_type = generator_type
        self.variants = {}
        self.active = set()
        self.sources = []
        self.generators = []
        self.names = set()
        self.trusted_imports = frozenset()
        self.source_unit = None
        self.type_analysis=None

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
                    raise _Unsupported("this function argument borrows its caller's container for reads, but the function writes or deletes through that argument; shared mutable argument storage and alias-preserving call effects are not implemented on this ordinary-function path",node=value,proof="mutable function-argument identity and caller-visible effects")
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                if rooted(value.func.value) and value.func.attr not in {"count", "index", "copy"}:
                    raise _Unsupported(f"method {value.func.attr!r} may mutate a borrowed container argument; this ordinary-function path has no alias-preserving mutable argument/call-effect representation",node=value,proof="mutable function-argument identity and caller-visible effects")

    def get(self, function, kinds, global_environment, global_names=None):
        # Function bodies can only read proved callable globals. Numeric or
        # mutable globals still require another direct representation. Snapshot
        # identities are part of the cache key so later rebindings cannot reuse
        # an earlier helper specialization.
        globals_at_call = {name: value for name, value in global_environment.items()
                           if _static_reference(value)}
        names=frozenset(global_environment)if global_names is None else frozenset(global_names)
        context=(tuple((name,id(value))for name,value in sorted(globals_at_call.items())),tuple(sorted(names)))
        key = (id(function.node), kinds, context)
        if key in self.variants:
            return self.variants[key]
        # Type-changing recursion is still recursion. Keep Python's frame and
        # RecursionError behavior instead of relying on Rust's host stack.
        if id(function.node) in self.active or len(self.active) >= 128:
            raise _Unsupported("a recursive ordinary function needs Python-compatible resumable frames and recursion-limit checks; that function-frame path is not implemented",operation=f"recursive call to {function.node.name!r}",types=tuple((f"argument {i+1}",kind)for i,kind in enumerate(kinds)),proof="recursive function frame state")
        # Further specialization growth needs a direct-generation implementation.
        if len(self.variants) + len(self.active) >= 128:
            raise _Unsupported("native function specialization exceeded its 128-variant budget; a finite shared call representation is not implemented for further variants",operation=f"specialization of function {function.node.name!r}",proof="bounded specialization growth")
        if any(kind not in {"int", "bool", "int_bool", "none", "list_int", "float", "str", "bytes"} and not isinstance(kind,(TupleType,TupleSequenceType,ListType,UnionType,NullableType)) for kind in kinds):
            raise _Unsupported
        self.active.add(id(function.node))
        rust_name = function.rust_name + "_" + ("_".join(kind_tag(kind) for kind in kinds) or "void")
        if rust_name in self.names:
            rust_name += f"_context_{len(self.names)}"
        self.names.add(rust_name)
        variant = replace(function, rust_name=rust_name, dependencies=set(), required=set(), imports=set(),
                          global_bindings=globals_at_call,global_names=names,absent_globals=set())
        local = self.generator_type(self.bits, self.functions, variant, self.function_input,
                           self.constructors, self)
        local.string_mode = self.string_mode
        local.global_environment = globals_at_call
        local.global_names = names
        local.source_unit = self.source_unit
        local.type_analysis=self.type_analysis
        local.constraint_facts=self.type_analysis.scope(function.node,kinds) if self.type_analysis is not None else None
        if self.type_analysis is not None:
            from .native_range_facts import derive_regions
            local.range_facts=derive_regions(self.type_analysis,local.constraint_facts,self.bits,
                                            body=self.type_analysis.graph.functions[self.source_unit.ordinal(function.node)].body)
        local.trusted_imports = self.trusted_imports
        environment = {name: value for name, value in globals_at_call.items()
                       if name not in function.local_names}
        initializers, signature = [], []
        parameters = function.positional + function.kwonly
        from .native_types import SharedListType
        arrays = {name for name, kind in zip(parameters, kinds) if list_type(kind)and not isinstance(kind,SharedListType)}
        self.readonly_arrays(function.node, arrays)
        for index, (name, kind) in enumerate(zip(parameters, kinds)):
            argument = f"native_argument_{index}"
            if isinstance(kind,SharedListType):
                signature.append(f"{argument}: {rust_type(kind)}")
                environment[name]=_Binding(argument,TypedListInfo(kind,None))
                local.register_type(kind)
            elif list_type(kind):
                element="int" if kind=="list_int" else kind.element
                signature.append(f"{argument}: &[{rust_type(element)}]")
                environment[name]=_Binding(argument,_ListInfo(None) if kind=="list_int" else TypedListInfo(kind,None))
                local.borrowed_slots.add(argument)
                local.has_lists |= kind=="list_int"
                local.has_typed_lists |= isinstance(kind,ListType)
            else:
                signature.append(f"{argument}: {rust_type(kind)}")
                initializers.append(f"{local.bind(name, kind, environment)} = {argument};")
        if self.function_input:
            signature.append("mut native_input: &mut NativeInput")
        signature.append("mut native_output: &mut String")
        body, remaining = local.statements(function.node.body, environment)
        if remaining is not None:local.return_kinds.add("none")
        from .native_expression_results import join_layouts
        result=None
        for kind in sorted(local.return_kinds,key=kind_tag):
            result=kind if result is None else join_layouts(result,kind)
            if result is None:raise _Unsupported
        variant.return_kind=result or "none"
        local.register_type(variant.return_kind)
        resolved={}
        for marker,(node,value) in local.return_values.items():
            resolved[marker]=f"return Ok({local.coerce(value,variant.return_kind)});"
        body="\n".join(resolved.get(line,line) for line in body.split("\n"))
        tail=("\nOk("+local.coerce(_Expression("()","none"),variant.return_kind)+")") if remaining is not None else ""
        variant.required.update(variant.imports)
        return_type = rust_type(variant.return_kind)
        source = (f"#[inline]\nfn {variant.rust_name}({', '.join(signature)}) -> Result<{return_type}, NativeError> {{\n"
                  "use std::fmt::Write as _;\n" + _declarations(local) + "\n"
                  + "\n".join(initializers) + "\n" + body + tail + "\n}")
        self.variants[key] = variant
        self.sources.append(source)
        self.generators.append(local)
        self.active.remove(id(function.node))
        return variant


def _declarations(generator):
    return "\n".join(f"let mut {slot}: {rust_type(kind)};" for slot,kind in generator.bindings.items())


def try_generate_native(source: str, filename: str, integer: str, *, trusted_imports=frozenset(),
                        prune_output=True, diagnostic_out=None, unit=None, string_mode="ascii") -> str | None:
    """Return direct Rust, or None with an optional positioned diagnostic.

    Fixed-width modes use native Rust integers; BigInt selects the owned
    arbitrary-precision scalar backend. An unimplemented direct path fails.
    SourceUnit carries the shared resolver's actual standard-module proof;
    a spelling such as "collections" in user source is insufficient evidence.
    """
    from .frontend import build_program, native_namespace_diagnostic
    from .diagnostics import CompilationError
    try:
        if unit is None:
            from dataclasses import replace
            unit = build_program(source, filename).main
            # Internal callers historically opt into standard-module helpers.
            # Restrict that proof to origins verified by the shared resolver.
            unit = replace(unit, native_imports=unit.native_imports.intersection(trusted_imports))
        unit.check_identity(source, filename)
    except CompilationError as error:
        if diagnostic_out is not None:diagnostic_out.append(error.diagnostic)
        return None
    namespace_error = native_namespace_diagnostic(unit)
    if namespace_error is not None:
        if diagnostic_out is not None:diagnostic_out.append(namespace_error)
        return None
    trusted_imports = unit.native_imports
    from .native_frame_selection import select_frames
    try:
        frame_selection=select_frames(unit)
    except (SyntaxError,_Unsupported,RecursionError,ConstraintFailure)as error:
        if diagnostic_out is not None:diagnostic_out.append(_direct_diagnostic(source,filename,error,unit=unit))
        return None
    if frame_selection.required:
        from .native_classes import try_generate_classes
        return try_generate_classes(source, filename, integer, trusted_imports=trusted_imports,
                                    prune_output=prune_output, diagnostic_out=diagnostic_out, unit=unit,
                                    string_mode=string_mode,frame_selection=frame_selection)
    if integer == "bigint":
        from .native_bigint import try_generate_bigint
        return try_generate_bigint(source, filename, prune_output=prune_output,
                                   diagnostic_out=diagnostic_out,trusted_imports=trusted_imports,unit=unit,
                                   string_mode=string_mode,type_analysis=frame_selection.analysis)
    if integer not in {"i64", "i128"}:
        if diagnostic_out is not None:
            diagnostic_out.append(_direct_diagnostic(source, filename, unit=unit))
        return None
    from .native_scalar import ScalarGenerator, SCALAR_HELPERS, TEXT_INPUT_HELPERS
    try:
        tree, table = unit.tree, unit.table
        # Legacy spelling-based calls need a namespace proof. Canonical call
        # families resolve the actual binding at each source position.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in ScalarGenerator.BUILTINS-{"input"}-CANONICAL_REBINDABLES:
                raise _Unsupported(f"rebinding builtin name {node.id!r} invalidates existing static callable identities; native rebinding/versioning for this builtin is not implemented",node=node,operation=f"assignment to builtin {node.id!r}",proof="callable identity after rebinding")
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
        functions = {} if wrapper else _function_plans(tree, table, bits, ScalarGenerator, unit=unit)
        function_input = bool(functions) and ("sys" in trusted_imports or any(isinstance(node, ast.Name) and node.id == "input" for node in ast.walk(tree)))
        specializations = _Specializations(bits, functions, constructors, function_input, ScalarGenerator,
                                          string_mode=string_mode)
        specializations.trusted_imports = trusted_imports
        specializations.source_unit=unit
        generator = ScalarGenerator(bits, functions, function_input=function_input, constructors=constructors,
                               specializations=specializations, string_mode=string_mode)
        generator.trusted_imports = trusted_imports
        generator.source_unit=unit
        from .native_constraints import analyze
        generator.type_analysis=specializations.type_analysis=frame_selection.analysis
        generator.constraint_facts=generator.type_analysis.scope()
        if function_input:
            generator.has_input = True
        if wrapper:
            generator.return_label = "native_entrypoint"
            generator.entry_scope = wrapper[0]
            entry=next(node for node in tree.body if isinstance(node,ast.FunctionDef)and node.name==wrapper[0])
            generator.constraint_facts=generator.type_analysis.scope(entry,())
            generator.entry_local_names={symbol.name for symbol in unit.scope_for(entry).symbols
                                         if symbol.has("local")or symbol.has("parameter")}
            generator.global_names=frozenset({wrapper[0]})
        from .native_range_facts import derive_regions
        range_body=(generator.type_analysis.graph.functions[unit.ordinal(entry)].body if wrapper else generator.type_analysis.graph.body)
        generator.range_facts=derive_regions(generator.type_analysis,generator.constraint_facts,bits,body=range_body)
        body, _ = generator.statements(statements, {})
        function_sources = specializations.sources
        for local in specializations.generators:
            generator.union_types.update(local.union_types)
            generator.text_predicates.update(local.text_predicates)
        for local in specializations.generators:
            for flag in ("needs_integer_runtime", "has_fixed_parsing", "has_input", "has_lists", "has_dicts", "has_mapping_delete", "has_sets", "has_deques", "has_scalar_union", "has_extended_scalars", "has_iterator_frames", "has_callback_frames", "has_slices", "has_text_methods", "has_stdio", "has_tuples", "has_typed_lists", "has_native_modules", "has_key_containers", "has_native_words", "has_empty_type"):
                setattr(generator, flag, getattr(generator, flag) or getattr(local, flag))
        if wrapper:
            body = f"'native_entrypoint: {{\n{body}\n}}"
    except (SyntaxError, _Unsupported, RecursionError, ConstraintFailure) as error:
        if diagnostic_out is not None:
            diagnostic_out.append(_direct_diagnostic(source, filename, error, unit=unit))
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
    if generator.has_fixed_parsing or generator.has_extended_scalars or generator.has_stdio:
        from .native_integer_parsing import render_helpers as parsing_helpers
        result.append(parsing_helpers(string_mode))
    if generator.has_input:
        result.append(runtime.joinpath("streaming_io.rs").read_text(encoding="utf-8"))
        result.append(_INPUT_HELPERS if generator.has_fixed_parsing else TEXT_INPUT_HELPERS)
    if generator.has_key_containers or generator.has_dicts:
        from .native_ordered_entries import helpers as dictionary_entries
        result.append(dictionary_entries(getattr(generator,"has_mapping_delete",False)))
    if generator.has_key_containers:
        from .native_key_containers import HELPERS as KEY_HELPERS
        result.append(KEY_HELPERS)
    if generator.has_tuples:
        from .native_tuples import render_helpers
        result.append(render_helpers())
        if not generator.needs_integer_runtime and not generator.has_extended_scalars:
            # --no-optimize keeps the printable table even for integer-only
            # tuples, so its Unicode notice must be present in that case too.
            notice=files("py2fastrust").joinpath("stdlib","UNICODE_LICENSE.txt").read_text(encoding="utf-8")
            result.append("\n".join("// "+line for line in notice.splitlines())+"\n")
    if generator.has_typed_lists:
        from .native_typed_lists import HELPERS as TYPED_LIST_HELPERS
        result.append(TYPED_LIST_HELPERS)
    if generator.has_native_words:
        from .native_words import HELPERS as WORD_HELPERS
        result.append(WORD_HELPERS)
    if generator.has_stdio:
        from .native_stdio import render_helpers
        result.append(render_helpers(generator.bits,integer_runtime=generator.needs_integer_runtime,input_runtime=generator.has_input))
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
        from .native_deques import HELPERS as DEQUE_HELPERS
        result.append(DEQUE_HELPERS)
    if generator.has_scalar_union:
        result.append(_SCALAR_UNION_HELPERS)
    if generator.has_native_modules:
        from .native_module_calls import helpers as module_helpers
        result.append(module_helpers(generator))
    if generator.has_empty_type:
        from .native_constraint_lowering import EMPTY_HELPERS
        result.append(EMPTY_HELPERS)
    if generator.union_types:
        from .native_unions import render_types
        result.append(render_types(generator.union_types))
    if generator.text_predicates:
        from .native_text_predicates import render_helpers
        result.append(render_helpers(generator.text_predicates,string_mode))
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
    elif functions or generator.has_iterator_frames or generator.has_callback_frames:
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
    from .native_text_policy import apply_text_policy
    source = apply_text_policy(source, string_mode)
    from .native_cached_text import apply_cached_text
    source = apply_cached_text(source,string_mode)
    if prune_output:
        from .rust_pruning import prune_rust_source
        source = prune_rust_source(source)
    from .native_notices import retain_native_notices
    return retain_native_notices(source)
