// Shared instruction contract: the Python and dynamic compilers emit these types.
#[derive(Clone, Debug, PartialEq)]
enum ScopeKind {
    Module,
    Function,
    Class,
    Comprehension,
    Annotation,
}
#[derive(Clone, Debug, Default)]
struct Params {
    posonly: usize,
    positional: Vec<String>,
    kwonly: Vec<String>,
    vararg: Option<String>,
    kwarg: Option<String>,
}
#[derive(Clone, Debug)]
struct Code {
    name: String,
    filename: String,
    kind: ScopeKind,
    locals: Vec<String>,
    globals: Vec<String>,
    nonlocals: Vec<String>,
    params: Params,
    ops: Vec<Instr>,
    is_generator: bool,
}
#[derive(Clone, Debug)]
struct Instr {
    op: Op,
    line: usize,
    column: usize,
}
#[derive(Clone, Debug)]
enum Const {
    None,
    Bool(bool),
    Int(String),
    Float(f64),
    Str(String),
    Bytes(Vec<u8>),
}
#[derive(Clone, Debug)]
enum Op {
    Const(Const),
    Load(String),
    Store(String),
    Delete(String),
    Pop,
    Dup,
    Swap,
    Rotate(usize),
    Binary(String),
    Unary(String),
    Compare(String),
    Jump(usize),
    JumpFalse(usize),
    JumpTrue(usize),
    BuildList(usize),
    BuildTuple(usize),
    BuildSet(usize),
    BuildDict(usize),
    BuildSlice(usize),
    GetItem,
    SetItem,
    DelItem,
    GetAttr(String),
    GetSpecialAttr(String),
    SetAttr(String),
    DelAttr(String),
    GetIter,
    ForIter(usize),
    Call {
        pos: usize,
        keywords: Vec<String>,
    },
    MakeFunction {
        code: usize,
        defaults: usize,
        kwdefaults: Vec<String>,
    },
    Return,
    Yield,
    Raise(usize),
    SetupExcept(usize),
    PopHandler,
    ClearException,
    LoadException,
    SetupFinally(usize),
    EndFinally,
    MakeClass {
        name: String,
        code: usize,
        bases: usize,
        keywords: Vec<String>,
    },
    Unpack(usize),
    ListAppend(usize),
    SetAdd(usize),
    MapAdd(usize),
    Import {
        module: String,
        names: Vec<String>,
        level: usize,
    },
    ImportFrom(String),
    FormatValue {
        conversion: i32,
        spec: bool,
    },
    BuildString(usize),
    Nop,
    PrintExpr,
    Match(MatchPattern),
    ExceptionMatch,
    Break(usize),
    Continue(usize),
    YieldFrom,
    UnpackEx {
        before: usize,
        after: usize,
    },
    BuildListUnpack(usize),
    BuildTupleUnpack(usize),
    CallEx {
        kwargs: bool,
    },
    GetYieldFromIter,
}

use std::collections::HashMap;
use std::io::{Read, Write};

struct OutputBuffer(Vec<u8>);
impl OutputBuffer {
    fn new() -> Self {
        Self(Vec::new())
    }
    fn push_str(&mut self, s: &str) {
        self.0.extend_from_slice(s.as_bytes())
    }
    fn push(&mut self, c: char) {
        let mut bytes = [0; 4];
        self.push_str(c.encode_utf8(&mut bytes))
    }
    fn as_bytes(&self) -> &[u8] {
        &self.0
    }
    fn clear(&mut self) {
        self.0.clear()
    }
    fn write_bytes(&mut self, b: &[u8]) {
        self.0.extend_from_slice(b)
    }
}

#[derive(Clone, Debug)]
enum Value {
    None,
    Bool(bool),
    Int(Int),
    Float(f64),
    Str(String),
    Bytes(Vec<u8>),
    Obj(usize),
    Builtin(String),
    Type(String),
}
#[derive(Clone, Debug)]
struct PyException {
    kind: String,
    message: String,
    value: Option<Value>,
    trace: Vec<(String, usize, String)>,
}
type PyResult<T> = Result<T, PyException>;
fn pyerr(kind: &str, message: impl Into<String>) -> PyException {
    PyException {
        kind: kind.into(),
        message: message.into(),
        value: None,
        trace: Vec::new(),
    }
}
fn int_error(s: String) -> PyException {
    let mut p = s.splitn(2, ':');
    pyerr(
        p.next().unwrap_or("ValueError"),
        p.next().unwrap_or("").trim(),
    )
}
#[derive(Clone, Debug)]
struct Function {
    annotate: Option<Value>,
    annotations_evaluated: bool,
    attrs: usize,
    name: String,
    qualname: String,
    module: Value,
    doc: Value,
    annotations: Value,
    type_params: Value,
    code: usize,
    globals: usize,
    closure: Option<usize>,
    defaults: Vec<Value>,
    kwdefaults: HashMap<String, Value>,
}
#[derive(Clone, Debug)]
struct Class {
    name: String,
    bases: Vec<Value>,
    attrs: usize,
    metaclass: Value,
}
#[derive(Clone, Debug)]
struct CacheEntry {
    args: Vec<Value>,
    kwargs: Vec<(String, Value)>,
    value: Value,
}
#[derive(Clone, Debug)]
struct CachedFunction {
    attrs: Option<usize>,
    function: Value,
    entries: Vec<CacheEntry>,
    maxsize: Option<usize>,
    typed: bool,
    hits: usize,
    misses: usize,
}
#[derive(Clone, Debug)]
enum IteratorState {
    Tools(Box<ToolsState>),
    Values(Vec<Value>, usize),
    List(usize, usize),
    Range(Int, Int, Int),
    Enumerate(Value, Int),
    Zip(Vec<Value>),
    Map(Value, Vec<Value>),
    Filter(Value, Value),
    Callable(Value, Value),
    Reversed(Value, isize),
}
#[derive(Clone, Debug)]
enum Object {
    BuiltinInstance {
        class: Value,
        attrs: usize,
        payload: Value,
    },
    Partial {
        function: Value,
        args: Vec<Value>,
        args_tuple: usize,
        keywords: usize,
        attrs: usize,
    },
    Cached(CachedFunction),
    Record {
        name: String,
        fields: Vec<(String, Value)>,
    },
    List(Vec<Value>),
    Tuple(Vec<Value>),
    Dict(Vec<(Value, Value)>),
    Set(Vec<Value>),
    Namespace(HashMap<String, Value>, Option<usize>),
    Function(Function),
    Class(Class),
    Instance {
        class: Value,
        attrs: usize,
    },
    Bound(Value, Value),
    Iterator(IteratorState),
    Generator(Frame),
    Module {
        name: String,
        attrs: usize,
    },
    Exception(PyException),
    Slice(Option<Int>, Option<Int>, Option<Int>),
    Cell(Option<Value>),
    Code(usize),
    Range(Int, Int, Int),
    Static(Value),
    ClassMethod(Value),
    Property {
        get: Value,
        set: Option<Value>,
        del: Option<Value>,
    },
}
#[derive(Clone, Debug)]
enum Pending {
    Normal,
    Return(Value),
    Jump(usize),
    Raise(PyException),
}
#[derive(Clone, Debug)]
struct Handler {
    finally_end: usize,
    pending_depth: usize,
    target: usize,
    depth: usize,
    finally: bool,
    start: usize,
}
#[derive(Clone, Debug)]
struct Frame {
    code: usize,
    pc: usize,
    locals: usize,
    temps: usize,
    globals: usize,
    closure: Option<usize>,
    stack: Vec<Value>,
    handlers: Vec<Handler>,
    pending: Vec<Pending>,
    exception: Option<PyException>,
    exception_stack: Vec<Option<PyException>>,
    next_call: Option<Box<Frame>>,
    resume_value: Option<Value>,
    injected_exception: Option<PyException>,
    finally_regions: Vec<(usize, usize, bool)>,
}
#[derive(Clone, Debug)]
enum FrameExit {
    Return(Value),
    Yield(Value),
}
struct Runtime {
    codes: Vec<Code>,
    heap: Vec<Option<Object>>,
    free: Vec<usize>,
    roots: Vec<Vec<Value>>,
    modules: HashMap<String, Value>,
    module_codes: HashMap<String, usize>,
    builtins: usize,
    globals: usize,
    output: OutputBuffer,
    input: Vec<u8>,
    input_pos: usize,
    recursion: usize,
    recursion_limit: usize,
    allocations: usize,
    scope_bindings: HashMap<usize, Vec<String>>,
    running_generators: Vec<usize>,
    scope_parents: HashMap<usize, usize>,
    gc_running: bool,
    finalized: std::collections::HashSet<usize>,
}
impl Runtime {
    fn take_keyword(kw: &mut Vec<(String, Value)>, name: &str) -> Option<Value> {
        kw.iter()
            .position(|(n, _)| n == name)
            .map(|i| kw.remove(i).1)
    }
    fn native_payload(&self, v: &Value) -> Option<Value> {
        if let Value::Obj(i) = v {
            if let Some(Object::BuiltinInstance { payload, .. }) =
                self.heap.get(*i).and_then(|o| o.as_ref())
            {
                return Some(payload.clone());
            }
        }
        None
    }
    fn instance_allows_dict(&self, i: usize) -> bool {
        match self.heap.get(i).and_then(|o| o.as_ref()) {
            Some(Object::BuiltinInstance { class, .. }) => self.builtin_instance_allows_dict(class),
            _ => true,
        }
    }
    fn rich_comparison(&mut self, op: &str, a: &Value, b: &Value) -> PyResult<Option<Value>> {
        let (left, right) = match op {
            "==" => ("__eq__", "__eq__"),
            "!=" => ("__ne__", "__ne__"),
            "<" => ("__lt__", "__gt__"),
            "<=" => ("__le__", "__ge__"),
            ">" => ("__gt__", "__lt__"),
            ">=" => ("__ge__", "__le__"),
            _ => return Ok(None),
        };
        let ac = self.object_class(a);
        let bc = self.object_class(b);
        let reverse = if let (Some(ac), Some(bc)) = (&ac, &bc) {
            !Self::same_type(ac, bc) && self.is_subclass(bc, ac)?
        } else {
            false
        };
        let mut pairs = vec![(a, b, left), (b, a, right)];
        if reverse {
            pairs.reverse()
        }
        for (obj, arg, name) in pairs {
            if let Some(class) = self.object_class(obj) {
                if let Some(method) = self.class_lookup(&class, name, 0) {
                    let callable = self.bind_descriptor(method, Some(obj.clone()), class)?;
                    let value = self.call(callable, vec![arg.clone()], Vec::new(), None)?;
                    if !matches!(&value,Value::Builtin(n)if n=="NotImplemented") {
                        return Ok(Some(value));
                    }
                }
            }
        }
        Ok(None)
    }
    fn equal(&mut self, a: &Value, b: &Value) -> PyResult<bool> {
        if let Some(value) = self.rich_comparison("==", a, b)? {
            return self.truth(&value);
        }
        self.equal_default(a, b)
    }
    fn compare(&mut self, op: &str, a: &Value, b: &Value) -> PyResult<bool> {
        let value = self.compare_value(op, a, b)?;
        self.truth(&value)
    }
    fn compare_value(&mut self, op: &str, a: &Value, b: &Value) -> PyResult<Value> {
        if let Some(value) = self.rich_comparison(op, a, b)? {
            return Ok(value);
        }
        if op == "!=" {
            if let Some(value) = self.rich_comparison("==", a, b)? {
                return Ok(Value::Bool(!self.truth(&value)?));
            }
        }
        Ok(Value::Bool(self.compare_default(op, a, b)?))
    }
    fn object_class(&self, v: &Value) -> Option<Value> {
        if let Value::Obj(i) = v {
            match self.heap.get(*i).and_then(|o| o.as_ref()) {
                Some(Object::Instance { class, .. } | Object::BuiltinInstance { class, .. }) => {
                    Some(class.clone())
                }
                Some(Object::Class(c)) => Some(c.metaclass.clone()),
                _ => None,
            }
        } else {
            None
        }
    }
    fn special_method(&mut self, v: Value, name: &str) -> PyResult<Value> {
        if let Some(class) = self.object_class(&v) {
            if let Some(method) = self.class_lookup(&class, name, 0) {
                return self.bind_descriptor(method, Some(v), class);
            }
            if let Some(payload) = self.native_payload(&v) {
                return self.getattr_default(payload, name);
            }
            return Err(pyerr("AttributeError", name));
        }
        self.getattr_default(v, name)
    }
    fn getattr(&mut self, v: Value, name: &str) -> PyResult<Value> {
        if let Some(class) = self.object_class(&v) {
            if let Some(method) = self.class_lookup(&class, "__getattribute__", 0) {
                let bound = self.obj_value(Object::Bound(method, v.clone()));
                match self.call(bound, vec![Value::Str(name.into())], Vec::new(), None) {
                    Ok(value) => return Ok(value),
                    Err(e) if e.kind == "AttributeError" => {
                        if let Some(method) = self.class_lookup(&class, "__getattr__", 0) {
                            let bound = self.obj_value(Object::Bound(method, v));
                            return self.call(
                                bound,
                                vec![Value::Str(name.into())],
                                Vec::new(),
                                None,
                            );
                        }
                        return Err(e);
                    }
                    Err(e) => return Err(e),
                }
            }
        }
        self.getattr_default(v, name)
    }
    fn setattr(&mut self, obj: Value, name: &str, value: Value) -> PyResult<()> {
        if let Some(class) = self.object_class(&obj) {
            if let Some(method) = self.class_lookup(&class, "__setattr__", 0) {
                let bound = self.obj_value(Object::Bound(method, obj));
                self.call(
                    bound,
                    vec![Value::Str(name.into()), value],
                    Vec::new(),
                    None,
                )?;
                return Ok(());
            }
        }
        self.setattr_default(obj, name, value)
    }
    fn delattr(&mut self, obj: Value, name: &str) -> PyResult<()> {
        if let Some(class) = self.object_class(&obj) {
            if let Some(method) = self.class_lookup(&class, "__delattr__", 0) {
                let bound = self.obj_value(Object::Bound(method, obj));
                self.call(bound, vec![Value::Str(name.into())], Vec::new(), None)?;
                return Ok(());
            }
        }
        self.delattr_default(obj, name)
    }
    fn stream_call(&mut self, name: &str, args: Vec<Value>, binary: bool) -> PyResult<Value> {
        let (target, method) = name.split_once(':').unwrap_or(("stdin", name));
        match method {
            "isatty" => return Ok(Value::Bool(false)),
            "readable" => return Ok(Value::Bool(target == "stdin")),
            "writable" => return Ok(Value::Bool(target != "stdin")),
            "flush" => {
                self.finish();
                return Ok(Value::None);
            }
            "write" => {
                if target == "stdin" {
                    return Err(pyerr("OSError", "not writable"));
                }
                let v = args
                    .first()
                    .ok_or_else(|| pyerr("TypeError", "write expected 1 argument"))?;
                let (bytes, count) = if binary {
                    match v {
                        Value::Bytes(xs) => (xs.clone(), xs.len()),
                        _ => return Err(pyerr("TypeError", "a bytes-like object is required")),
                    }
                } else {
                    match v {
                        Value::Str(s) => (s.as_bytes().to_vec(), s.chars().count()),
                        _ => return Err(pyerr("TypeError", "write() argument must be str")),
                    }
                };
                if target == "stderr" {
                    let _ = std::io::stderr().write_all(&bytes);
                } else {
                    self.output.write_bytes(&bytes)
                }
                return Ok(Value::Int(Int::from_i128(count as i128)));
            }
            _ => {}
        }
        if target != "stdin" {
            return Err(pyerr("OSError", "not readable"));
        }
        let count = if let Some(v) = args.first() {
            self.as_int(v)?.to_i128().unwrap_or(-1)
        } else {
            -1
        };
        let start = self.input_pos;
        let mut end = self.input.len();
        if method == "readline" {
            end = self.input[start..]
                .iter()
                .position(|b| *b == b'\n')
                .map(|i| start + i + 1)
                .unwrap_or(end)
        }
        if count >= 0 {
            if binary {
                end = end.min(start.saturating_add(count as usize));
            } else {
                let s = std::str::from_utf8(&self.input[start..end])
                    .map_err(|_| pyerr("UnicodeDecodeError", "input is not valid UTF-8"))?;
                end = s
                    .char_indices()
                    .nth(count as usize)
                    .map(|(i, _)| start + i)
                    .unwrap_or(end)
            }
        }
        let bytes = self.input[start..end].to_vec();
        self.input_pos = end;
        if method == "readlines" {
            let mut lines = Vec::new();
            for line in bytes.split_inclusive(|b| *b == b'\n') {
                lines.push(if binary {
                    Value::Bytes(line.to_vec())
                } else {
                    Value::Str(
                        String::from_utf8(line.to_vec())
                            .map_err(|_| pyerr("UnicodeDecodeError", "input is not valid UTF-8"))?,
                    )
                })
            }
            return Ok(self.obj_value(Object::List(lines)));
        }
        if method != "read" && method != "readline" {
            return Err(pyerr("AttributeError", method));
        }
        Ok(if binary {
            Value::Bytes(bytes)
        } else {
            Value::Str(
                String::from_utf8(bytes)
                    .map_err(|_| pyerr("UnicodeDecodeError", "input is not valid UTF-8"))?,
            )
        })
    }
    fn find_finally_end(&self, code: usize, start: usize) -> usize {
        let mut depth = 0;
        for (i, ins) in self.codes[code].ops.iter().enumerate().skip(start) {
            match ins.op {
                Op::SetupFinally(_) => depth += 1,
                Op::EndFinally => {
                    if depth == 0 {
                        return i;
                    } else {
                        depth -= 1
                    }
                }
                _ => {}
            }
        }
        usize::MAX
    }
    fn discard_finalizers(f: &mut Frame, keep: usize) {
        while f.finally_regions.len() > keep {
            if let Some((_, _, raised)) = f.finally_regions.pop() {
                if raised {
                    f.exception = f.exception_stack.pop().flatten();
                }
            }
            f.pending.pop();
        }
        f.pending.truncate(keep);
    }
    fn code_needs_class_cell(&self, code: usize, depth: usize) -> bool {
        if depth > 100 {
            return false;
        }
        self.codes[code].ops.iter().any(|ins| match &ins.op {
            Op::Load(n) if n == "__class__" || n == "super" => true,
            Op::MakeFunction { code, .. } => self.code_needs_class_cell(*code, depth + 1),
            _ => false,
        })
    }
    fn cache_key_check(&mut self, v: &Value) -> PyResult<()> {
        if let Value::Obj(i) = v {
            match self.object(*i)? {
                Object::List(_) | Object::Dict(_) | Object::Set(_) | Object::Namespace(..) => {
                    return Err(pyerr(
                        "TypeError",
                        format!("unhashable type: '{}'", self.typename(v)),
                    ))
                }
                Object::Tuple(xs) => {
                    for x in xs {
                        self.cache_key_check(&x)?
                    }
                }
                _ => {}
            }
        }
        Ok(())
    }
    fn cached_call(
        &mut self,
        i: usize,
        mut cache: CachedFunction,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
        caller: Option<&Frame>,
    ) -> PyResult<Value> {
        for v in args.iter().chain(kwargs.iter().map(|(_, v)| v)) {
            self.cache_key_check(v)?
        }
        for (j, e) in cache.entries.iter().enumerate() {
            if e.args.len() != args.len() || e.kwargs.len() != kwargs.len() {
                continue;
            }
            let mut same = true;
            for (a, b) in e.args.iter().zip(&args) {
                if (cache.typed && self.typename(a) != self.typename(b)) || !self.equal(a, b)? {
                    same = false;
                    break;
                }
            }
            if same {
                for ((an, a), (bn, b)) in e.kwargs.iter().zip(&kwargs) {
                    if an != bn
                        || (cache.typed && self.typename(a) != self.typename(b))
                        || !self.equal(a, b)?
                    {
                        same = false;
                        break;
                    }
                }
            }
            if same {
                let entry = cache.entries.remove(j);
                let result = entry.value.clone();
                cache.entries.push(entry);
                cache.hits += 1;
                self.heap[i] = Some(Object::Cached(cache));
                return Ok(result);
            }
        }
        cache.misses += 1;
        let fun = cache.function.clone();
        self.heap[i] = Some(Object::Cached(cache));
        let value = self.call(fun, args.clone(), kwargs.clone(), caller)?;
        if let Object::Cached(mut cache) = self.object(i)? {
            if cache.maxsize != Some(0) {
                cache.entries.push(CacheEntry {
                    args,
                    kwargs,
                    value: value.clone(),
                });
                if let Some(max) = cache.maxsize {
                    if cache.entries.len() > max {
                        cache.entries.remove(0);
                    }
                }
                self.heap[i] = Some(Object::Cached(cache));
            }
        }
        Ok(value)
    }
    fn mapping_get(&mut self, i: usize, n: &str) -> PyResult<Option<Value>> {
        if matches!(
            self.heap.get(i).and_then(|o| o.as_ref()),
            Some(Object::Instance { .. })
        ) {
            match self.getitem(Value::Obj(i), Value::Str(n.into())) {
                Ok(v) => Ok(Some(v)),
                Err(e) if e.kind == "KeyError" => Ok(None),
                Err(e) => Err(e),
            }
        } else {
            Ok(self.ns_get(i, n))
        }
    }
    fn mapping_set(&mut self, i: usize, n: String, v: Value) -> PyResult<()> {
        if matches!(
            self.heap.get(i).and_then(|o| o.as_ref()),
            Some(Object::Instance { .. })
        ) {
            self.setitem(Value::Obj(i), Value::Str(n), v)
        } else {
            self.ns_set(i, n, v);
            Ok(())
        }
    }
    fn mapping_del(&mut self, i: usize, n: &str) -> PyResult<bool> {
        if matches!(
            self.heap.get(i).and_then(|o| o.as_ref()),
            Some(Object::Instance { .. })
        ) {
            match self.delitem(Value::Obj(i), Value::Str(n.into())) {
                Ok(()) => Ok(true),
                Err(e) if e.kind == "KeyError" => Ok(false),
                Err(e) => Err(e),
            }
        } else {
            Ok(self.ns_del(i, n))
        }
    }
    fn new(codes: Vec<Code>, modules: Vec<(String, usize)>) -> Self {
        let mut rt = Self {
            codes,
            heap: Vec::new(),
            free: Vec::new(),
            roots: Vec::new(),
            modules: HashMap::new(),
            module_codes: modules.into_iter().collect(),
            builtins: 0,
            globals: 0,
            output: OutputBuffer::new(),
            input: Vec::new(),
            input_pos: 0,
            recursion: 0,
            recursion_limit: 1000,
            allocations: 0,
            scope_bindings: HashMap::new(),
            running_generators: Vec::new(),
            scope_parents: HashMap::new(),
            gc_running: false,
            finalized: std::collections::HashSet::new(),
        };
        rt.builtins = rt.alloc(Object::Namespace(HashMap::new(), None));
        rt.globals = rt.alloc(Object::Namespace(HashMap::new(), None));
        for name in [
            "abs",
            "all",
            "any",
            "ascii",
            "bin",
            "bool",
            "bytearray",
            "bytes",
            "callable",
            "chr",
            "classmethod",
            "compile",
            "complex",
            "delattr",
            "dict",
            "dir",
            "divmod",
            "enumerate",
            "eval",
            "exec",
            "filter",
            "float",
            "format",
            "frozenset",
            "getattr",
            "globals",
            "hasattr",
            "hash",
            "hex",
            "id",
            "input",
            "int",
            "isinstance",
            "issubclass",
            "iter",
            "len",
            "list",
            "locals",
            "map",
            "max",
            "min",
            "next",
            "object",
            "oct",
            "open",
            "ord",
            "pow",
            "print",
            "property",
            "range",
            "repr",
            "reversed",
            "round",
            "set",
            "setattr",
            "slice",
            "sorted",
            "staticmethod",
            "str",
            "sum",
            "super",
            "tuple",
            "type",
            "vars",
            "zip",
            "__import__",
        ] {
            rt.ns_set(rt.builtins, name.into(), Value::Builtin(name.into()));
        }
        for name in [
            "BaseException",
            "Exception",
            "ArithmeticError",
            "AssertionError",
            "AttributeError",
            "EOFError",
            "ImportError",
            "ModuleNotFoundError",
            "IndexError",
            "KeyError",
            "LookupError",
            "NameError",
            "NotImplementedError",
            "OSError",
            "OverflowError",
            "RecursionError",
            "RuntimeError",
            "StopIteration",
            "SyntaxError",
            "TypeError",
            "UnboundLocalError",
            "ValueError",
            "ZeroDivisionError",
            "GeneratorExit",
            "SystemExit",
        ] {
            rt.ns_set(rt.builtins, name.into(), Value::Type(name.into()));
        }
        rt.ns_set(
            rt.builtins,
            "Ellipsis".into(),
            Value::Builtin("Ellipsis".into()),
        );
        rt.ns_set(
            rt.builtins,
            "NotImplemented".into(),
            Value::Builtin("NotImplemented".into()),
        );
        rt.ns_set(rt.globals, "__name__".into(), Value::Str("__main__".into()));
        rt.ns_set(rt.globals, "__builtins__".into(), Value::Obj(rt.builtins));
        let main = rt.alloc(Object::Module {
            name: "__main__".into(),
            attrs: rt.globals,
        });
        rt.modules.insert("__main__".into(), Value::Obj(main));
        let _ = std::io::stdin().read_to_end(&mut rt.input);
        rt
    }
    fn alloc(&mut self, obj: Object) -> usize {
        self.allocations += 1;
        if let Some(i) = self.free.pop() {
            self.scope_bindings.remove(&i);
            self.scope_parents.remove(&i);
            self.finalized.remove(&i);
            self.heap[i] = Some(obj);
            i
        } else {
            let i = self.heap.len();
            self.heap.push(Some(obj));
            i
        }
    }
    fn object(&self, i: usize) -> PyResult<Object> {
        self.heap
            .get(i)
            .and_then(|o| o.clone())
            .ok_or_else(|| pyerr("RuntimeError", "invalid object reference"))
    }
    fn obj_value(&mut self, o: Object) -> Value {
        Value::Obj(self.alloc(o))
    }
    fn ns_get(&self, i: usize, name: &str) -> Option<Value> {
        match self.heap.get(i).and_then(|o| o.as_ref()) {
            Some(Object::Namespace(m, _)) => m.get(name).cloned(),
            Some(Object::Dict(m)) => m.iter().find_map(|(k, v)| match k {
                Value::Str(s) if s == name => Some(v.clone()),
                _ => None,
            }),
            _ => None,
        }
    }
    fn ns_set(&mut self, i: usize, name: String, v: Value) {
        if let Some(Some(o)) = self.heap.get_mut(i) {
            match o {
                Object::Namespace(m, _) => {
                    m.insert(name, v);
                }
                Object::Dict(m) => {
                    if let Some((_, old)) = m
                        .iter_mut()
                        .find(|(k, _)| matches!(k,Value::Str(s) if s==&name))
                    {
                        *old = v;
                    } else {
                        m.push((Value::Str(name), v));
                    }
                }
                _ => {}
            }
        }
    }
    fn ns_del(&mut self, i: usize, name: &str) -> bool {
        match self.heap.get_mut(i).and_then(|o| o.as_mut()) {
            Some(Object::Namespace(m, _)) => m.remove(name).is_some(),
            Some(Object::Dict(m)) => {
                if let Some(p) = m
                    .iter()
                    .position(|(k, _)| matches!(k,Value::Str(s) if s==name))
                {
                    m.remove(p);
                    true
                } else {
                    false
                }
            }
            _ => false,
        }
    }
    fn ns_parent(&self, i: usize) -> Option<usize> {
        match self.heap.get(i).and_then(|o| o.as_ref()) {
            Some(Object::Namespace(_, p)) => *p,
            _ => self.scope_parents.get(&i).copied(),
        }
    }
    fn find_nonlocal(&self, mut p: Option<usize>, name: &str) -> Option<usize> {
        while let Some(i) = p {
            if self.ns_get(i, name).is_some()
                || self
                    .scope_bindings
                    .get(&i)
                    .map(|v| v.iter().any(|s| s == name))
                    .unwrap_or(false)
            {
                return Some(i);
            }
            p = self.ns_parent(i);
        }
        None
    }
    fn load(&mut self, f: &Frame, name: &str) -> PyResult<Value> {
        if name.starts_with('$') || name.starts_with('\0') {
            return self
                .ns_get(f.temps, name)
                .ok_or_else(|| pyerr("RuntimeError", "unbound internal temporary"));
        }
        let global = self.codes[f.code].globals.iter().any(|s| s == name);
        let islocal = (self.codes[f.code].kind == ScopeKind::Function
            || self.codes[f.code].kind == ScopeKind::Comprehension)
            && self.codes[f.code].locals.iter().any(|s| s == name);
        if global {
            return self
                .ns_get(f.globals, name)
                .or_else(|| self.builtin_lookup(f.globals, name))
                .ok_or_else(|| pyerr("NameError", format!("name '{}' is not defined", name)));
        }
        if let Some(v) = self.mapping_get(f.locals, name)? {
            return Ok(v);
        }
        if islocal {
            return Err(pyerr(
                "UnboundLocalError",
                format!(
                    "cannot access local variable '{}' where it is not associated with a value",
                    name
                ),
            ));
        }
        let mut closure = f.closure;
        if self.codes[f.code].kind == ScopeKind::Annotation {
            if let Some(ns) = closure {
                if let Some(value) = self.mapping_get(ns, name)? {
                    return Ok(value);
                }
                closure = self.ns_parent(ns)
            }
        }
        if let Some(p) = self.find_nonlocal(closure, name) {
            return self.mapping_get(p, name)?.ok_or_else(|| {
                pyerr(
                    "NameError",
                    format!(
                        "cannot access free variable '{}' where it is not associated with a value",
                        name
                    ),
                )
            });
        }
        self.ns_get(f.globals, name)
            .or_else(|| self.builtin_lookup(f.globals, name))
            .ok_or_else(|| pyerr("NameError", format!("name '{}' is not defined", name)))
    }
    fn builtin_lookup(&self, g: usize, n: &str) -> Option<Value> {
        match self.ns_get(g, "__builtins__") {
            Some(Value::Obj(i)) => match self.heap.get(i).and_then(|o| o.as_ref()) {
                Some(Object::Module { attrs, .. }) => self.ns_get(*attrs, n),
                _ => self.ns_get(i, n),
            },
            _ => self.ns_get(self.builtins, n),
        }
    }
    fn store(&mut self, f: &Frame, name: String, v: Value) -> PyResult<()> {
        if name.starts_with('$') || name.starts_with('\0') {
            self.ns_set(f.temps, name, v);
            return Ok(());
        }
        if self.codes[f.code].globals.contains(&name) {
            self.ns_set(f.globals, name, v);
        } else if self.codes[f.code].nonlocals.contains(&name) {
            let i = self.find_nonlocal(f.closure, &name).ok_or_else(|| {
                pyerr(
                    "NameError",
                    format!("no binding for nonlocal '{}' found", name),
                )
            })?;
            self.ns_set(i, name, v);
        } else {
            self.mapping_set(f.locals, name, v)?;
        }
        Ok(())
    }
    fn run(&mut self) -> PyResult<Value> {
        let f = Frame {
            code: 0,
            pc: 0,
            locals: self.globals,
            temps: self.alloc(Object::Namespace(HashMap::new(), None)),
            globals: self.globals,
            closure: None,
            stack: Vec::new(),
            handlers: Vec::new(),
            pending: Vec::new(),
            exception: None,
            exception_stack: Vec::new(),
            next_call: None,
            resume_value: None,
            injected_exception: None,
            finally_regions: Vec::new(),
        };
        match self.execute(f)?.0 {
            FrameExit::Return(v) | FrameExit::Yield(v) => Ok(v),
        }
    }
    fn finish(&mut self) {
        let _ = std::io::stdout().write_all(self.output.as_bytes());
        let _ = std::io::stdout().flush();
        self.output.clear();
    }
    fn report_exception(&self, e: &PyException) {
        if !e.trace.is_empty() {
            eprintln!("Traceback (most recent call last):");
            for (file, line, name) in e.trace.iter().rev() {
                eprintln!("  File {:?}, line {}, in {}", file, line, name);
            }
        }
        eprintln!("{}: {}", e.kind, e.message);
    }
    fn pop(f: &mut Frame) -> PyResult<Value> {
        f.stack
            .pop()
            .ok_or_else(|| pyerr("RuntimeError", "operand stack underflow"))
    }
    fn pop_many(f: &mut Frame, n: usize) -> PyResult<Vec<Value>> {
        if f.stack.len() < n {
            return Err(pyerr("RuntimeError", "operand stack underflow"));
        }
        Ok(f.stack.split_off(f.stack.len() - n))
    }
    fn constant(&mut self, c: Const) -> PyResult<Value> {
        Ok(match c {
            Const::None => Value::None,
            Const::Bool(v) => Value::Bool(v),
            Const::Int(s) => Value::Int(Int::parse(&s, 0).map_err(int_error)?),
            Const::Float(v) => Value::Float(v),
            Const::Str(v) => Value::Str(v),
            Const::Bytes(v) => Value::Bytes(v),
        })
    }
    fn frame_roots(frame: &Frame, out: &mut Vec<Value>) {
        out.extend(frame.stack.iter().cloned());
        out.extend(frame.resume_value.iter().cloned());
        if let Some(e) = &frame.injected_exception {
            out.extend(e.value.iter().cloned());
        }
        out.push(Value::Obj(frame.locals));
        out.push(Value::Obj(frame.temps));
        out.push(Value::Obj(frame.globals));
        if let Some(i) = frame.closure {
            out.push(Value::Obj(i))
        }
        for p in &frame.pending {
            match p {
                Pending::Return(v) => out.push(v.clone()),
                Pending::Raise(e) => {
                    if let Some(v) = &e.value {
                        out.push(v.clone())
                    }
                }
                _ => {}
            }
        }
        for e in frame
            .exception
            .iter()
            .chain(frame.exception_stack.iter().filter_map(|e| e.as_ref()))
        {
            if let Some(v) = &e.value {
                out.push(v.clone())
            }
        }
    }
    fn execute(&mut self, mut f: Frame) -> PyResult<(FrameExit, Frame)> {
        if self.recursion >= self.recursion_limit {
            return Err(pyerr("RecursionError", "maximum recursion depth exceeded"));
        }
        let base_depth = self.recursion;
        let root = self.roots.len();
        self.roots.push(Vec::new());
        self.recursion += 1;
        let mut frames: Vec<Frame> = Vec::new();
        let result = (|| loop {
            let mut roots = Vec::new();
            Self::frame_roots(&f, &mut roots);
            let current = root + frames.len();
            self.roots.truncate(current + 1);
            if self.roots.len() == current {
                self.roots.push(roots)
            } else {
                self.roots[current] = roots;
            }
            if self.allocations > 10000 {
                self.collect();
                self.allocations = 0;
            }
            let result = if let Some(e) = f.injected_exception.take() {
                Err(e)
            } else if f.pc >= self.codes[f.code].ops.len() {
                Ok(Some(FrameExit::Return(Value::None)))
            } else {
                let ins = self.codes[f.code].ops[f.pc].clone();
                f.pc += 1;
                self.step(&mut f, ins.op)
            };
            match result {
                Ok(Some(FrameExit::Return(v))) => {
                    if let Some(mut parent) = frames.pop() {
                        parent.stack.push(v);
                        self.recursion -= 1;
                        f = parent;
                    } else {
                        return Ok((FrameExit::Return(v), f));
                    }
                }
                Ok(Some(exit @ FrameExit::Yield(_))) => return Ok((exit, f)),
                Ok(None) => {
                    if let Some(child) = f.next_call.take() {
                        if self.recursion >= self.recursion_limit {
                            return Err(pyerr(
                                "RecursionError",
                                "maximum recursion depth exceeded",
                            ));
                        }
                        frames.push(f);
                        self.recursion += 1;
                        f = *child;
                    }
                }
                Err(mut e) => loop {
                    if let Some(h) = f.handlers.pop() {
                        f.stack.truncate(h.depth);
                        Self::discard_finalizers(&mut f, h.pending_depth);
                        f.pc = h.target;
                        f.exception_stack.push(f.exception.take());
                        f.exception = Some(e.clone());
                        if h.finally {
                            f.pending.push(Pending::Raise(e));
                            f.finally_regions.push((h.target, h.finally_end, true));
                        }
                        break;
                    }
                    let line = self.codes[f.code]
                        .ops
                        .get(f.pc.saturating_sub(1))
                        .map(|i| i.line)
                        .unwrap_or(1);
                    e.trace.push((
                        self.codes[f.code].filename.clone(),
                        line,
                        self.codes[f.code].name.clone(),
                    ));
                    if let Some(parent) = frames.pop() {
                        self.recursion -= 1;
                        f = parent;
                    } else {
                        return Err(e);
                    }
                },
            }
        })();
        self.roots.truncate(root);
        self.recursion = base_depth;
        result
    }
    fn transfer(&mut self, f: &mut Frame, p: Pending) -> Option<FrameExit> {
        if matches!(p, Pending::Return(_)) {
            Self::discard_finalizers(f, 0);
        }
        if let Pending::Jump(t) = &p {
            let keep = f
                .finally_regions
                .iter()
                .rposition(|(a, b, _)| *t >= *a && *t <= *b)
                .map(|i| i + 1)
                .unwrap_or(0);
            Self::discard_finalizers(f, keep);
        }
        while let Some(h) = f.handlers.pop() {
            if let Pending::Jump(t) = &p {
                if *t >= h.start && *t < h.target {
                    f.handlers.push(h);
                    f.pc = *t;
                    return None;
                }
            }
            if h.finally {
                f.stack.truncate(h.depth);
                f.pc = h.target;
                f.pending.push(p);
                f.finally_regions.push((h.target, h.finally_end, false));
                return None;
            }
        }
        match p {
            Pending::Return(v) => Some(FrameExit::Return(v)),
            Pending::Jump(t) => {
                f.pc = t;
                None
            }
            Pending::Raise(_) | Pending::Normal => None,
        }
    }
    fn step(&mut self, f: &mut Frame, op: Op) -> PyResult<Option<FrameExit>> {
        match op {
            Op::Nop => {}
            Op::Match(p) => {
                let subject = Self::pop(f)?;
                let yes = self.match_pattern(f, subject, p)?;
                f.stack.push(Value::Bool(yes));
            }
            Op::PrintExpr => {
                let v = Self::pop(f)?;
                if !matches!(v, Value::None) {
                    let text = self.repr(&v)?;
                    self.output.push_str(&text);
                    self.output.push('\n');
                    self.ns_set(self.builtins, "_".into(), v)
                }
            }
            Op::Const(c) => {
                let v = self.constant(c)?;
                f.stack.push(v)
            }
            Op::Load(n) => {
                let v = self.load(f, &n)?;
                f.stack.push(v)
            }
            Op::Store(n) => {
                let v = Self::pop(f)?;
                self.store(f, n, v)?
            }
            Op::Delete(n) => {
                let ns = if n.starts_with('$') || n.starts_with('\0') {
                    f.temps
                } else if self.codes[f.code].globals.contains(&n) {
                    f.globals
                } else if self.codes[f.code].nonlocals.contains(&n) {
                    self.find_nonlocal(f.closure, &n)
                        .ok_or_else(|| pyerr("NameError", &n))?
                } else {
                    f.locals
                };
                if !self.mapping_del(ns, &n)? {
                    return Err(pyerr("NameError", format!("name '{}' is not defined", n)));
                }
            }
            Op::Pop => {
                Self::pop(f)?;
            }
            Op::Dup => {
                let v = f
                    .stack
                    .last()
                    .cloned()
                    .ok_or_else(|| pyerr("RuntimeError", "empty stack"))?;
                f.stack.push(v)
            }
            Op::Swap => {
                let n = f.stack.len();
                if n < 2 {
                    return Err(pyerr("RuntimeError", "empty stack"));
                }
                f.stack.swap(n - 1, n - 2)
            }
            Op::Rotate(n) => {
                let len = f.stack.len();
                if n > len {
                    return Err(pyerr("RuntimeError", "empty stack"));
                }
                f.stack[len - n..].rotate_right(1)
            }
            Op::Binary(op) => {
                let b = Self::pop(f)?;
                let a = Self::pop(f)?;
                let v = self.binary(&op, a, b)?;
                f.stack.push(v)
            }
            Op::Unary(op) => {
                let a = Self::pop(f)?;
                let v = self.unary(&op, a)?;
                f.stack.push(v)
            }
            Op::Compare(op) => {
                let b = Self::pop(f)?;
                let a = Self::pop(f)?;
                let v = self.compare_value(&op, &a, &b)?;
                f.stack.push(v)
            }
            Op::ExceptionMatch => {
                let b = Self::pop(f)?;
                let a = Self::pop(f)?;
                let v = self.exception_match(&a, &b)?;
                f.stack.push(Value::Bool(v))
            }
            Op::Jump(t) => f.pc = t,
            Op::JumpFalse(t) => {
                let v = Self::pop(f)?;
                if !self.truth(&v)? {
                    f.pc = t
                }
            }
            Op::JumpTrue(t) => {
                let v = Self::pop(f)?;
                if self.truth(&v)? {
                    f.pc = t
                }
            }
            Op::Break(t) | Op::Continue(t) => return Ok(self.transfer(f, Pending::Jump(t))),
            Op::BuildList(n) | Op::BuildTuple(n) | Op::BuildSet(n) => {
                let values = Self::pop_many(f, n)?;
                let obj = match op {
                    Op::BuildTuple(_) => Object::Tuple(values),
                    Op::BuildSet(_) => {
                        let mut unique = Vec::new();
                        for v in values {
                            if !self.contains_vec(&unique, &v)? {
                                unique.push(v)
                            }
                        }
                        Object::Set(unique)
                    }
                    _ => Object::List(values),
                };
                let v = self.obj_value(obj);
                f.stack.push(v)
            }
            Op::BuildDict(n) => {
                let v = Self::pop_many(f, n * 2)?;
                let d = self.obj_value(Object::Dict(Vec::new()));
                for p in v.chunks(2) {
                    self.setitem(d.clone(), p[0].clone(), p[1].clone())?
                }
                f.stack.push(d)
            }
            Op::BuildSlice(n) => {
                let v = Self::pop_many(f, n)?;
                let mut parts = Vec::new();
                for x in v {
                    parts.push(if matches!(x, Value::None) {
                        None
                    } else {
                        Some(self.as_int(&x)?)
                    })
                }
                while parts.len() < 3 {
                    parts.push(None)
                }
                let v = self.obj_value(Object::Slice(
                    parts[0].clone(),
                    parts[1].clone(),
                    parts[2].clone(),
                ));
                f.stack.push(v)
            }
            Op::GetItem => {
                let key = Self::pop(f)?;
                let obj = Self::pop(f)?;
                let v = self.getitem(obj, key)?;
                f.stack.push(v)
            }
            Op::SetItem => {
                let key = Self::pop(f)?;
                let obj = Self::pop(f)?;
                let v = Self::pop(f)?;
                self.setitem(obj, key, v)?
            }
            Op::DelItem => {
                let key = Self::pop(f)?;
                let obj = Self::pop(f)?;
                self.delitem(obj, key)?
            }
            Op::GetSpecialAttr(n) => {
                let obj = Self::pop(f)?;
                let value = self.special_method(obj, &n)?;
                f.stack.push(value)
            }
            Op::GetAttr(n) => {
                let obj = Self::pop(f)?;
                let v = self.getattr(obj, &n)?;
                f.stack.push(v)
            }
            Op::SetAttr(n) => {
                let obj = Self::pop(f)?;
                let v = Self::pop(f)?;
                self.setattr(obj, &n, v)?
            }
            Op::DelAttr(n) => {
                let obj = Self::pop(f)?;
                self.delattr(obj, &n)?
            }
            Op::GetIter | Op::GetYieldFromIter => {
                let v = Self::pop(f)?;
                let it = self.iter(v)?;
                f.stack.push(it)
            }
            Op::ForIter(t) => {
                let it = f
                    .stack
                    .last()
                    .cloned()
                    .ok_or_else(|| pyerr("RuntimeError", "missing iterator"))?;
                match self.next(it)? {
                    Some(v) => f.stack.push(v),
                    None => {
                        Self::pop(f)?;
                        f.pc = t
                    }
                }
            }
            Op::Call { pos, keywords } => {
                let vals = Self::pop_many(f, pos + keywords.len())?;
                let callable = Self::pop(f)?;
                let kwargs: Vec<_> = keywords
                    .into_iter()
                    .zip(vals[pos..].iter().cloned())
                    .collect();
                let args = vals[..pos].to_vec();
                if let Some(child) =
                    self.prepare_direct_call(callable.clone(), args.clone(), kwargs.clone())?
                {
                    f.next_call = Some(Box::new(child));
                } else {
                    let v = self.call(callable, args, kwargs, Some(f))?;
                    f.stack.push(v)
                }
            }
            Op::CallEx { kwargs } => {
                let kw = if kwargs {
                    let v = Self::pop(f)?;
                    self.keyword_items(v)?
                } else {
                    Vec::new()
                };
                let arg = Self::pop(f)?;
                let args = self.to_vec(arg)?;
                let fun = Self::pop(f)?;
                if let Some(child) =
                    self.prepare_direct_call(fun.clone(), args.clone(), kw.clone())?
                {
                    f.next_call = Some(Box::new(child));
                } else {
                    let v = self.call(fun, args, kw, Some(f))?;
                    f.stack.push(v)
                }
            }
            Op::MakeFunction {
                code,
                defaults,
                kwdefaults,
            } => {
                let kwvals = Self::pop_many(f, kwdefaults.len())?;
                let defs = Self::pop_many(f, defaults)?;
                let closure = if self.codes[code].kind == ScopeKind::Annotation {
                    Some(f.locals)
                } else {
                    match self.codes[f.code].kind {
                        ScopeKind::Class => f.closure,
                        ScopeKind::Module => None,
                        _ => Some(f.locals),
                    }
                };
                let attrs = self.alloc(Object::Dict(Vec::new()));
                let annotations = self.obj_value(Object::Dict(Vec::new()));
                let type_params = self.obj_value(Object::Tuple(Vec::new()));
                let name = self.codes[code].name.clone();
                let qualname = name.clone();
                let module = self.ns_get(f.globals, "__name__").unwrap_or(Value::None);
                let doc = match self.codes[code].ops.first().map(|i| &i.op) {
                    Some(Op::Const(Const::Str(s))) => Value::Str(s.clone()),
                    _ => Value::None,
                };
                let fun = self.obj_value(Object::Function(Function {
                    annotate: None,
                    annotations_evaluated: false,
                    attrs,
                    name,
                    qualname,
                    module,
                    doc,
                    annotations,
                    type_params,
                    code,
                    globals: f.globals,
                    closure,
                    defaults: defs,
                    kwdefaults: kwdefaults.into_iter().zip(kwvals).collect(),
                }));
                f.stack.push(fun)
            }
            Op::Return => {
                let v = if f.stack.is_empty() {
                    Value::None
                } else {
                    Self::pop(f)?
                };
                return Ok(self.transfer(f, Pending::Return(v)));
            }
            Op::Yield => {
                let v = Self::pop(f)?;
                return Ok(Some(FrameExit::Yield(v)));
            }
            Op::YieldFrom => {
                let it = f
                    .stack
                    .last()
                    .cloned()
                    .ok_or_else(|| pyerr("RuntimeError", "missing iterator"))?;
                if let Some(v) = self.next(it)? {
                    f.pc -= 1;
                    return Ok(Some(FrameExit::Yield(v)));
                } else {
                    Self::pop(f)?;
                    f.stack.push(Value::None)
                }
            }
            Op::Raise(n) => {
                if n == 0 {
                    return Err(f
                        .exception
                        .clone()
                        .ok_or_else(|| pyerr("RuntimeError", "No active exception to reraise"))?);
                }
                if n == 2 {
                    Self::pop(f)?;
                }
                let v = Self::pop(f)?;
                return Err(self.as_exception(v)?);
            }
            Op::SetupExcept(t) => f.handlers.push(Handler {
                target: t,
                finally_end: 0,
                depth: f.stack.len(),
                finally: false,
                start: f.pc,
                pending_depth: f.pending.len(),
            }),
            Op::SetupFinally(t) => f.handlers.push(Handler {
                target: t,
                finally_end: self.find_finally_end(f.code, t),
                depth: f.stack.len(),
                finally: true,
                start: f.pc,
                pending_depth: f.pending.len(),
            }),
            Op::PopHandler => {
                if let Some(h) = f.handlers.pop() {
                    if h.finally {
                        f.pending.push(Pending::Normal);
                        f.finally_regions.push((h.target, h.finally_end, false));
                    }
                }
            }
            Op::ClearException => f.exception = f.exception_stack.pop().flatten(),
            Op::LoadException => {
                let e = f
                    .exception
                    .clone()
                    .ok_or_else(|| pyerr("RuntimeError", "no active exception"))?;
                let v = self.obj_value(Object::Exception(e));
                f.stack.push(v)
            }
            Op::EndFinally => {
                f.finally_regions.pop();
                if let Some(p) = f.pending.pop() {
                    match p {
                        Pending::Normal => {}
                        Pending::Raise(e) => {
                            f.exception = f.exception_stack.pop().flatten();
                            return Err(e);
                        }
                        p => return Ok(self.transfer(f, p)),
                    }
                }
            }
            Op::MakeClass {
                name,
                code,
                bases,
                keywords,
            } => {
                let kv = Self::pop_many(f, keywords.len())?;
                let bases = Self::pop_many(f, bases)?;
                let kw: Vec<_> = keywords.into_iter().zip(kv).collect();
                let cls = self.make_class(f, name, code, bases, kw)?;
                f.stack.push(cls)
            }
            Op::Unpack(n) => {
                let v = Self::pop(f)?;
                let vs = self.to_vec(v)?;
                if vs.len() != n {
                    return Err(pyerr(
                        "ValueError",
                        format!("expected {} values to unpack, got {}", n, vs.len()),
                    ));
                }
                f.stack.extend(vs.into_iter().rev())
            }
            Op::UnpackEx { before, after } => {
                let v = Self::pop(f)?;
                let vs = self.to_vec(v)?;
                if vs.len() < before + after {
                    return Err(pyerr("ValueError", "not enough values to unpack"));
                }
                let mut out = vs[..before].to_vec();
                out.push(self.obj_value(Object::List(vs[before..vs.len() - after].to_vec())));
                out.extend_from_slice(&vs[vs.len() - after..]);
                f.stack.extend(out.into_iter().rev())
            }
            Op::BuildListUnpack(n) | Op::BuildTupleUnpack(n) => {
                let inputs = Self::pop_many(f, n)?;
                let mut all = Vec::new();
                for v in inputs {
                    all.extend(self.to_vec(v)?)
                }
                let out = self.obj_value(if matches!(op, Op::BuildTupleUnpack(_)) {
                    Object::Tuple(all)
                } else {
                    Object::List(all)
                });
                f.stack.push(out)
            }
            Op::ListAppend(depth) | Op::SetAdd(depth) => {
                let v = Self::pop(f)?;
                let obj =
                    f.stack
                        .get(
                            f.stack.len().checked_sub(depth).ok_or_else(|| {
                                pyerr("RuntimeError", "invalid comprehension depth")
                            })?,
                        )
                        .cloned()
                        .ok_or_else(|| pyerr("RuntimeError", "missing comprehension container"))?;
                self.container_add(obj, v, matches!(op, Op::SetAdd(_)))?
            }
            Op::MapAdd(depth) => {
                let v = Self::pop(f)?;
                let k = Self::pop(f)?;
                let obj =
                    f.stack
                        .get(
                            f.stack.len().checked_sub(depth).ok_or_else(|| {
                                pyerr("RuntimeError", "invalid comprehension depth")
                            })?,
                        )
                        .cloned()
                        .ok_or_else(|| pyerr("RuntimeError", "missing dict"))?;
                self.setitem(obj, k, v)?
            }
            Op::Import {
                module,
                names,
                level,
            } => {
                let name = if level > 0 {
                    self.resolve_relative(f, &module, level)?
                } else {
                    module
                };
                let v = self.import_module(&name)?;
                if names.is_empty() && name.contains('.') {
                    let top = name.split('.').next().unwrap();
                    f.stack.push(self.import_module(top)?)
                } else {
                    f.stack.push(v)
                }
            }
            Op::ImportFrom(n) => {
                let m = f
                    .stack
                    .last()
                    .cloned()
                    .ok_or_else(|| pyerr("RuntimeError", "missing module"))?;
                if n == "*" {
                    let names = self.attribute_items(&m)?;
                    for (name, v) in names {
                        if !name.starts_with('_') {
                            self.store(f, name, v)?
                        }
                    }
                } else {
                    let v = self.getattr(m, &n)?;
                    f.stack.push(v)
                }
            }
            Op::FormatValue { conversion, spec } => {
                let specification = if spec { Some(Self::pop(f)?) } else { None };
                let v = Self::pop(f)?;
                let text = if conversion == 114 || conversion == 97 {
                    self.repr(&v)?
                } else {
                    self.str_value(&v)?
                };
                let result = if let Some(s) = specification {
                    let s = self.str_value(&s)?;
                    self.format_value(v, &s)?
                } else {
                    text
                };
                f.stack.push(Value::Str(result))
            }
            Op::BuildString(n) => {
                let vs = Self::pop_many(f, n)?;
                let mut s = String::new();
                for v in vs {
                    s.push_str(&self.str_value(&v)?)
                }
                f.stack.push(Value::Str(s))
            }
        }
        Ok(None)
    }
}

impl Runtime {
    fn resolve_relative(&mut self, f: &Frame, module: &str, level: usize) -> PyResult<String> {
        let package = match self.ns_get(f.globals, "__package__") {
            Some(Value::Str(s)) => s,
            _ => String::new(),
        };
        let mut parts: Vec<_> = package.split('.').filter(|s| !s.is_empty()).collect();
        if parts.len() < level {
            return Err(pyerr(
                "ImportError",
                "attempted relative import beyond top-level package",
            ));
        }
        for _ in 1..level {
            parts.pop();
        }
        let mut name = parts.join(".");
        if !module.is_empty() {
            if !name.is_empty() {
                name.push('.')
            }
            name.push_str(module)
        }
        Ok(name)
    }
    fn import_module(&mut self, name: &str) -> PyResult<Value> {
        if let Some(v) = self.modules.get(name) {
            return Ok(v.clone());
        }
        if name.contains('.') {
            let parent = name.rsplit_once('.').unwrap().0;
            self.import_module(parent)?;
        }
        let attrs = self.alloc(Object::Namespace(HashMap::new(), None));
        let module = self.obj_value(Object::Module {
            name: name.into(),
            attrs,
        });
        self.ns_set(attrs, "__name__".into(), Value::Str(name.into()));
        self.ns_set(attrs, "__builtins__".into(), Value::Obj(self.builtins));
        self.ns_set(
            attrs,
            "__package__".into(),
            Value::Str(name.rsplit_once('.').map(|p| p.0).unwrap_or("").into()),
        );
        let functions: &[&str] = if self.module_codes.contains_key(name) {
            &[]
        } else {
            match name {
                "math" => &[
                    "acos",
                    "acosh",
                    "asin",
                    "asinh",
                    "atan",
                    "atan2",
                    "atanh",
                    "cbrt",
                    "ceil",
                    "comb",
                    "copysign",
                    "cos",
                    "cosh",
                    "degrees",
                    "dist",
                    "erf",
                    "erfc",
                    "exp",
                    "exp2",
                    "expm1",
                    "fabs",
                    "factorial",
                    "floor",
                    "fma",
                    "fmod",
                    "frexp",
                    "fsum",
                    "gamma",
                    "gcd",
                    "hypot",
                    "isclose",
                    "isfinite",
                    "isinf",
                    "isnan",
                    "isqrt",
                    "lcm",
                    "ldexp",
                    "lgamma",
                    "log",
                    "log10",
                    "log1p",
                    "log2",
                    "modf",
                    "nextafter",
                    "perm",
                    "pow",
                    "prod",
                    "radians",
                    "remainder",
                    "sin",
                    "sinh",
                    "sqrt",
                    "sumprod",
                    "tan",
                    "tanh",
                    "trunc",
                    "ulp",
                ],
                "bisect" => &[
                    "bisect_left",
                    "bisect_right",
                    "bisect",
                    "insort",
                    "insort_left",
                    "insort_right",
                ],
                "heapq" => &[
                    "heapify",
                    "heappush",
                    "heappop",
                    "heappushpop",
                    "heapreplace",
                    "nlargest",
                    "nsmallest",
                    "merge",
                ],
                "itertools" => &[
                    "accumulate",
                    "batched",
                    "chain",
                    "combinations",
                    "combinations_with_replacement",
                    "compress",
                    "count",
                    "cycle",
                    "dropwhile",
                    "filterfalse",
                    "groupby",
                    "islice",
                    "pairwise",
                    "permutations",
                    "product",
                    "repeat",
                    "starmap",
                    "takewhile",
                    "tee",
                    "zip_longest",
                ],
                "_py2fastrust_functools" => &["reduce", "cache", "lru_cache", "partial"],
                "functools" => &["reduce", "cache", "lru_cache", "partial"],
                "operator" => &[
                    "add",
                    "sub",
                    "mul",
                    "truediv",
                    "floordiv",
                    "mod",
                    "pow",
                    "and_",
                    "or_",
                    "xor",
                    "lshift",
                    "rshift",
                    "neg",
                    "pos",
                    "not_",
                    "eq",
                    "ne",
                    "lt",
                    "le",
                    "gt",
                    "ge",
                    "getitem",
                    "setitem",
                    "itemgetter",
                    "attrgetter",
                ],
                "collections" => &["deque", "Counter", "defaultdict", "namedtuple"],
                "sys" => &["setrecursionlimit", "getrecursionlimit", "exit"],
                "gc" => &["collect", "enable", "disable"],
                "time" => &["time", "perf_counter", "monotonic"],
                "builtins" => &[],
                _ => &[],
            }
        };
        if functions.is_empty() && name != "builtins" && !self.module_codes.contains_key(name) {
            return Err(pyerr(
                "ModuleNotFoundError",
                format!("No module named '{}'", name),
            ));
        }
        self.modules.insert(name.into(), module.clone());
        for fun in functions {
            self.ns_set(
                attrs,
                (*fun).into(),
                Value::Builtin(format!(
                    "module:{}:{}",
                    if name == "_py2fastrust_functools" {
                        "functools"
                    } else {
                        name
                    },
                    fun
                )),
            )
        }
        if name == "_py2fastrust_functools"
            || (name == "functools" && !self.module_codes.contains_key(name))
        {
            self.ns_set(
                attrs,
                "Placeholder".into(),
                Value::Builtin("functools.Placeholder".into()),
            );
        }
        if name == "math" && !self.module_codes.contains_key(name) {
            for (n, x) in [
                ("pi", std::f64::consts::PI),
                ("e", std::f64::consts::E),
                ("tau", std::f64::consts::TAU),
                ("inf", f64::INFINITY),
                ("nan", f64::NAN),
            ] {
                self.ns_set(attrs, n.into(), Value::Float(x))
            }
        }
        if name == "builtins" {
            let entries = self.keyword_items(Value::Obj(self.builtins))?;
            for (n, v) in entries {
                self.ns_set(attrs, n, v)
            }
        }
        if name == "sys" && !self.module_codes.contains_key(name) {
            self.ns_set(attrs, "stdin".into(), Value::Builtin("stream:stdin".into()));
            self.ns_set(
                attrs,
                "stdout".into(),
                Value::Builtin("stream:stdout".into()),
            );
            self.ns_set(
                attrs,
                "stderr".into(),
                Value::Builtin("stream:stderr".into()),
            );
            let mut values = vec![Value::Str(self.codes[0].filename.clone())];
            values.extend(std::env::args().skip(1).map(Value::Str));
            let argv = self.obj_value(Object::List(values));
            self.ns_set(attrs, "argv".into(), argv);
            self.ns_set(
                attrs,
                "maxsize".into(),
                Value::Int(Int::from_i128(i64::MAX as i128)),
            );
            self.ns_set(
                attrs,
                "version".into(),
                Value::Str("3.14 (py2fastrust)".into()),
            );
            let dict = self.obj_value(Object::Dict(
                self.modules
                    .iter()
                    .map(|(n, v)| (Value::Str(n.clone()), v.clone()))
                    .collect(),
            ));
            self.ns_set(attrs, "modules".into(), dict);
        }
        if let Some(code) = self.module_codes.get(name).copied() {
            let frame = Frame {
                code,
                pc: 0,
                locals: attrs,
                temps: self.alloc(Object::Namespace(HashMap::new(), None)),
                globals: attrs,
                closure: None,
                stack: Vec::new(),
                handlers: Vec::new(),
                pending: Vec::new(),
                exception: None,
                exception_stack: Vec::new(),
                next_call: None,
                resume_value: None,
                injected_exception: None,
                finally_regions: Vec::new(),
            };
            if let Err(e) = self.execute(frame) {
                self.modules.remove(name);
                return Err(e);
            }
        }
        if let Some((parent, child)) = name.rsplit_once('.') {
            if let Some(p) = self.modules.get(parent).cloned() {
                self.setattr(p, child, module.clone())?;
            }
        }
        Ok(module)
    }
    fn module_call(
        &mut self,
        fullname: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        let parts: Vec<_> = fullname.splitn(3, ':').collect();
        let module = parts.get(1).copied().unwrap_or("");
        let name = parts.get(2).copied().unwrap_or("");
        let arg = |i: usize| {
            args.get(i)
                .cloned()
                .ok_or_else(|| pyerr("TypeError", format!("{} missing argument", name)))
        };
        match module {
            "stream" | "streambuffer" => self.stream_call(name, args, module == "streambuffer"),
            "sys" => match name {
                "setrecursionlimit" => {
                    self.recursion_limit = self
                        .as_int(&arg(0)?)?
                        .to_usize()
                        .ok_or_else(|| pyerr("ValueError", "recursion limit must be positive"))?;
                    Ok(Value::None)
                }
                "getrecursionlimit" => Ok(Value::Int(Int::from_i128(self.recursion_limit as i128))),
                "exit" => Err(pyerr(
                    "SystemExit",
                    if args.is_empty() {
                        String::new()
                    } else {
                        self.str_value(&args[0])?
                    },
                )),
                _ => Err(pyerr("NotImplementedError", fullname)),
            },
            "gc" => {
                if name == "collect" {
                    let count = self.collect();
                    Ok(Value::Int(Int::from_i128(count as i128)))
                } else {
                    Ok(Value::None)
                }
            }
            "time" => {
                let d = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default();
                Ok(Value::Float(d.as_secs_f64()))
            }
            "math" => self.math_call(name, args, kwargs),
            "bisect" => {
                let values = self.to_vec(arg(0)?)?;
                let x = arg(1)?;
                let mut lo = if args.len() > 2 {
                    self.as_int(&args[2])?.to_usize().unwrap_or(0)
                } else {
                    0
                };
                let mut hi = if args.len() > 3 {
                    self.as_int(&args[3])?.to_usize().unwrap_or(values.len())
                } else {
                    values.len()
                };
                let left = name.ends_with("left");
                while lo < hi {
                    let mid = (lo + hi) / 2;
                    let less = if left {
                        self.compare("<", &values[mid], &x)?
                    } else {
                        !self.compare("<", &x, &values[mid])?
                    };
                    if less {
                        lo = mid + 1
                    } else {
                        hi = mid
                    }
                }
                if name.starts_with("insort") {
                    if let Value::Obj(i) = arg(0)? {
                        let mut values = values;
                        values.insert(lo, x);
                        self.heap[i] = Some(Object::List(values));
                        return Ok(Value::None);
                    }
                }
                Ok(Value::Int(Int::from_i128(lo as i128)))
            }
            "heapq" => {
                let i = if let Value::Obj(i) = arg(0)? {
                    i
                } else {
                    return Err(pyerr("TypeError", "heap must be a list"));
                };
                let mut xs = match self.object(i)? {
                    Object::List(xs) => xs,
                    _ => return Err(pyerr("TypeError", "heap must be a list")),
                };
                match name {
                    "heappush" => xs.push(arg(1)?),
                    "heappop" => {
                        if xs.is_empty() {
                            return Err(pyerr("IndexError", "index out of range"));
                        }
                        let mut best = 0;
                        for j in 1..xs.len() {
                            if self.compare("<", &xs[j], &xs[best])? {
                                best = j
                            }
                        }
                        let v = xs.swap_remove(best);
                        self.heap[i] = Some(Object::List(xs));
                        return Ok(v);
                    }
                    "heapreplace" | "heappushpop" => {
                        if name == "heappushpop" {
                            xs.push(arg(1)?)
                        } else if xs.is_empty() {
                            return Err(pyerr("IndexError", "index out of range"));
                        }
                        let mut best = 0;
                        for j in 1..xs.len() {
                            if self.compare("<", &xs[j], &xs[best])? {
                                best = j
                            }
                        }
                        let v = xs.swap_remove(best);
                        if name == "heapreplace" {
                            xs.push(arg(1)?)
                        }
                        self.heap[i] = Some(Object::List(xs));
                        return Ok(v);
                    }
                    "heapify" => {}
                    _ => return Err(pyerr("NotImplementedError", fullname)),
                }
                xs = self.sort_values(xs, None, false)?;
                self.heap[i] = Some(Object::List(xs));
                Ok(Value::None)
            }
            "collections" => match name {
                "deque" => {
                    let xs = if args.is_empty() {
                        Vec::new()
                    } else {
                        self.to_vec(args[0].clone())?
                    };
                    Ok(self.obj_value(Object::List(xs)))
                }
                "Counter" => {
                    let out = self.obj_value(Object::Dict(Vec::new()));
                    if let Some(v) = args.first() {
                        for x in self.to_vec(v.clone())? {
                            let old = self
                                .getitem(out.clone(), x.clone())
                                .unwrap_or(Value::Int(Int::from_i128(0)));
                            let n = self.binary("+", old, Value::Int(Int::from_i128(1)))?;
                            self.setitem(out.clone(), x, n)?
                        }
                    }
                    Ok(out)
                }
                _ => Err(pyerr("NotImplementedError", fullname)),
            },
            "functools" => match name {
                "partial" => {
                    if args.is_empty() {
                        return Err(pyerr(
                            "TypeError",
                            "type 'partial' takes at least one argument",
                        ));
                    }
                    if kwargs
                        .iter()
                        .any(|(_, v)| matches!(v,Value::Builtin(n)if n=="functools.Placeholder"))
                    {
                        return Err(pyerr(
                            "TypeError",
                            "Placeholder cannot be passed as a keyword argument",
                        ));
                    }
                    let mut function = args[0].clone();
                    let mut stored = args[1..].to_vec();
                    let mut kw = kwargs;
                    if let Value::Obj(i) = function.clone() {
                        if let Object::Partial {
                            function: base,
                            args: old,
                            keywords,
                            attrs,
                            ..
                        } = self.object(i)?
                        {
                            if self.dict_items(Value::Obj(attrs))?.is_empty() {
                                let mut incoming = stored.into_iter();
                                stored = old;
                                for value in &mut stored {
                                    if matches!(value,Value::Builtin(n)if n=="functools.Placeholder")
                                    {
                                        if let Some(next) = incoming.next() {
                                            *value = next
                                        }
                                    }
                                }
                                stored.extend(incoming);
                                let mut merged = self.keyword_items(Value::Obj(keywords))?;
                                for (n, v) in kw {
                                    if let Some((_, old)) =
                                        merged.iter_mut().find(|(key, _)| key == &n)
                                    {
                                        *old = v
                                    } else {
                                        merged.push((n, v))
                                    }
                                }
                                kw = merged;
                                function = base;
                            }
                        }
                    }
                    if matches!(stored.last(),Some(Value::Builtin(n))if n=="functools.Placeholder")
                    {
                        return Err(pyerr("TypeError", "trailing Placeholders are not allowed"));
                    }
                    let keywords = self.alloc(Object::Dict(
                        kw.into_iter().map(|(k, v)| (Value::Str(k), v)).collect(),
                    ));
                    let attrs = self.alloc(Object::Dict(Vec::new()));
                    let args_tuple = self.alloc(Object::Tuple(stored.clone()));
                    Ok(self.obj_value(Object::Partial {
                        function,
                        args: stored,
                        args_tuple,
                        keywords,
                        attrs,
                    }))
                }
                "reduce" => {
                    if args.len() < 2 || args.len() > 3 {
                        return Err(pyerr("TypeError", "reduce expected 2 or 3 arguments"));
                    }
                    if kwargs.iter().any(|(n, _)| n != "initial") {
                        return Err(pyerr(
                            "TypeError",
                            "reduce got an unexpected keyword argument",
                        ));
                    }
                    let initial = kwargs
                        .iter()
                        .find(|(n, _)| n == "initial")
                        .map(|(_, v)| v.clone());
                    if args.len() == 3 && initial.is_some() {
                        return Err(pyerr("TypeError", "reduce got multiple values for initial"));
                    }
                    let iterator = self.iter(args[1].clone())?;
                    let root = self.roots.len();
                    self.roots.push(vec![iterator.clone()]);
                    let result = (|| {
                        let mut out = if args.len() == 3 {
                            args[2].clone()
                        } else if let Some(v) = initial {
                            v
                        } else {
                            self.next(iterator.clone())?.ok_or_else(|| {
                                pyerr(
                                    "TypeError",
                                    "reduce() of empty iterable with no initial value",
                                )
                            })?
                        };
                        loop {
                            self.roots[root] = vec![iterator.clone(), out.clone()];
                            if let Some(value) = self.next(iterator.clone())? {
                                out =
                                    self.call(args[0].clone(), vec![out, value], Vec::new(), None)?
                            } else {
                                return Ok(out);
                            }
                        }
                    })();
                    self.roots.truncate(root);
                    result
                }
                "cache" => Ok(self.obj_value(Object::Cached(CachedFunction {
                    attrs: None,
                    function: arg(0)?,
                    entries: Vec::new(),
                    maxsize: None,
                    typed: false,
                    hits: 0,
                    misses: 0,
                }))),
                "lru_cache" => {
                    let typed = kwargs
                        .iter()
                        .find(|(n, _)| n == "typed")
                        .map(|(_, v)| self.truth(v))
                        .transpose()?
                        .unwrap_or(false);
                    if args.len() == 1
                        && matches!(args[0],Value::Obj(i)if matches!(self.heap.get(i).and_then(|o|o.as_ref()),Some(Object::Function(_))))
                    {
                        return Ok(self.obj_value(Object::Cached(CachedFunction {
                            attrs: None,
                            function: args[0].clone(),
                            entries: Vec::new(),
                            maxsize: Some(128),
                            typed,
                            hits: 0,
                            misses: 0,
                        })));
                    }
                    let size = args
                        .first()
                        .cloned()
                        .or_else(|| {
                            kwargs
                                .iter()
                                .find(|(n, _)| n == "maxsize")
                                .map(|(_, v)| v.clone())
                        })
                        .unwrap_or(Value::Int(Int::from_i128(128)));
                    let captures = self.obj_value(Object::Tuple(vec![size, Value::Bool(typed)]));
                    Ok(self.obj_value(Object::Bound(
                        Value::Builtin("module:functools:decorate_cache".into()),
                        captures,
                    )))
                }
                "decorate_cache" => {
                    let captures = self.to_vec(arg(0)?)?;
                    let maxsize = if matches!(captures[0], Value::None) {
                        None
                    } else {
                        Some(self.as_int(&captures[0])?.to_i128().unwrap_or(0).max(0) as usize)
                    };
                    let typed = self.truth(&captures[1])?;
                    Ok(self.obj_value(Object::Cached(CachedFunction {
                        attrs: None,
                        function: arg(1)?,
                        entries: Vec::new(),
                        maxsize,
                        typed,
                        hits: 0,
                        misses: 0,
                    })))
                }
                _ => Err(pyerr("NotImplementedError", fullname)),
            },
            "operator" => {
                let op = match name {
                    "add" => "+",
                    "sub" => "-",
                    "mul" => "*",
                    "truediv" => "/",
                    "floordiv" => "//",
                    "mod" => "%",
                    "pow" => "**",
                    "and_" => "&",
                    "or_" => "|",
                    "xor" => "^",
                    "lshift" => "<<",
                    "rshift" => ">>",
                    _ => "",
                };
                if !op.is_empty() {
                    return self.binary(op, arg(0)?, arg(1)?);
                }
                match name {
                    "neg" => self.unary("-", arg(0)?),
                    "pos" => self.unary("+", arg(0)?),
                    "not_" => self.unary("not", arg(0)?),
                    "getitem" => self.getitem(arg(0)?, arg(1)?),
                    "setitem" => {
                        self.setitem(arg(0)?, arg(1)?, arg(2)?)?;
                        Ok(Value::None)
                    }
                    "eq" | "ne" | "lt" | "le" | "gt" | "ge" => Ok(Value::Bool(self.compare(
                        match name {
                            "eq" => "==",
                            "ne" => "!=",
                            "lt" => "<",
                            "le" => "<=",
                            "gt" => ">",
                            _ => ">=",
                        },
                        &arg(0)?,
                        &arg(1)?,
                    )?)),
                    _ => Err(pyerr("NotImplementedError", fullname)),
                }
            }
            "itertools" => self.itertools_call(name, args, kwargs),
            _ => Err(pyerr("NotImplementedError", fullname)),
        }
    }
    fn gc_marks(&self, extra: &[Value]) -> Vec<bool> {
        let mut marked = vec![false; self.heap.len()];
        let mut pending = vec![Value::Obj(self.builtins), Value::Obj(self.globals)];
        pending.extend(self.modules.values().cloned());
        pending.extend(extra.iter().cloned());
        pending.extend(self.running_generators.iter().map(|i| Value::Obj(*i)));
        for group in &self.roots {
            pending.extend(group.iter().cloned())
        }
        while let Some(v) = pending.pop() {
            let i = if let Value::Obj(i) = v { i } else { continue };
            if i >= marked.len() || marked[i] {
                continue;
            }
            marked[i] = true;
            if let Some(parent) = self.scope_parents.get(&i) {
                pending.push(Value::Obj(*parent));
            }
            let obj = match self.heap[i].as_ref() {
                Some(o) => o,
                None => continue,
            };
            match obj {
                Object::List(v) | Object::Tuple(v) | Object::Set(v) => {
                    pending.extend(v.iter().cloned())
                }
                Object::Dict(v) => {
                    for (k, v) in v {
                        pending.push(k.clone());
                        pending.push(v.clone())
                    }
                }
                Object::Namespace(m, p) => {
                    pending.extend(m.values().cloned());
                    if let Some(i) = p {
                        pending.push(Value::Obj(*i))
                    }
                }
                Object::Function(f) => {
                    pending.push(Value::Obj(f.attrs));
                    pending.extend(f.annotate.iter().cloned());
                    pending.extend([
                        f.module.clone(),
                        f.doc.clone(),
                        f.annotations.clone(),
                        f.type_params.clone(),
                    ]);
                    pending.push(Value::Obj(f.globals));
                    if let Some(i) = f.closure {
                        pending.push(Value::Obj(i))
                    }
                    pending.extend(f.defaults.iter().cloned());
                    pending.extend(f.kwdefaults.values().cloned())
                }
                Object::Class(c) => {
                    pending.push(Value::Obj(c.attrs));
                    pending.extend(c.bases.iter().cloned());
                    pending.push(c.metaclass.clone())
                }
                Object::Instance { class, attrs }
                | Object::BuiltinInstance { class, attrs, .. } => {
                    pending.push(class.clone());
                    pending.push(Value::Obj(*attrs))
                }
                Object::Bound(a, b) => {
                    pending.push(a.clone());
                    pending.push(b.clone())
                }
                Object::Module { attrs, .. } => pending.push(Value::Obj(*attrs)),
                Object::Exception(e) => {
                    if let Some(v) = &e.value {
                        pending.push(v.clone())
                    }
                }
                Object::Partial {
                    function,
                    args,
                    args_tuple,
                    keywords,
                    attrs,
                } => {
                    pending.push(function.clone());
                    pending.push(Value::Obj(*args_tuple));
                    pending.extend(args.iter().cloned());
                    pending.push(Value::Obj(*keywords));
                    pending.push(Value::Obj(*attrs));
                }
                Object::Cached(c) => {
                    if let Some(i) = c.attrs {
                        pending.push(Value::Obj(i))
                    }
                    pending.push(c.function.clone());
                    for e in &c.entries {
                        pending.extend(e.args.iter().cloned());
                        pending.extend(e.kwargs.iter().map(|(_, v)| v.clone()));
                        pending.push(e.value.clone())
                    }
                }
                Object::Record { fields, .. } => {
                    pending.extend(fields.iter().map(|(_, v)| v.clone()))
                }
                Object::Cell(v) => pending.extend(v.iter().cloned()),
                Object::Static(v) | Object::ClassMethod(v) => pending.push(v.clone()),
                Object::Property { get, set, del } => {
                    pending.push(get.clone());
                    pending.extend(set.iter().cloned());
                    pending.extend(del.iter().cloned())
                }
                Object::Generator(f) => Self::frame_roots(f, &mut pending),
                Object::Iterator(it) => match it {
                    IteratorState::Tools(state) => pending.extend(state.roots()),
                    IteratorState::Values(v, _) => pending.extend(v.iter().cloned()),
                    IteratorState::List(i, _) => pending.push(Value::Obj(*i)),
                    IteratorState::Enumerate(v, _) | IteratorState::Reversed(v, _) => {
                        pending.push(v.clone())
                    }
                    IteratorState::Zip(v) => pending.extend(v.iter().cloned()),
                    IteratorState::Map(f, v) => {
                        pending.push(f.clone());
                        pending.extend(v.iter().cloned())
                    }
                    IteratorState::Filter(a, b) | IteratorState::Callable(a, b) => {
                        pending.push(a.clone());
                        pending.push(b.clone())
                    }
                    _ => {}
                },
                _ => {}
            }
        }
        marked
    }
    fn collect(&mut self) -> usize {
        if self.gc_running {
            return 0;
        }
        self.gc_running = true;
        let marked = self.gc_marks(&[]);
        let mut candidates = Vec::new();
        for (i, live) in marked.iter().enumerate() {
            if !*live && !self.finalized.contains(&i) && self.heap[i].is_some() {
                if matches!(self.heap[i], Some(Object::Generator(ref frame)) if frame.pc > 0 && frame.pc != usize::MAX)
                {
                    candidates.push(i);
                } else if let Some(class) = self.object_class(&Value::Obj(i)) {
                    if self.class_lookup(&class, "__del__", 0).is_some() {
                        candidates.push(i)
                    }
                }
            }
        }
        let root = self.roots.len();
        self.roots
            .push(candidates.iter().map(|i| Value::Obj(*i)).collect());
        for i in candidates {
            self.finalized.insert(i);
            let result = if matches!(self.heap[i], Some(Object::Generator(_))) {
                self.method("close", Value::Obj(i), Vec::new(), Vec::new())
            } else if let Ok(method) = self.special_method(Value::Obj(i), "__del__") {
                self.call(method, Vec::new(), Vec::new(), None)
            } else {
                Ok(Value::None)
            };
            if let Err(error) = result {
                eprintln!("Exception ignored during finalization:");
                self.report_exception(&error);
            }
        }
        self.roots.truncate(root);
        let marked = self.gc_marks(&[]);
        let mut count = 0;
        for (i, live) in marked.into_iter().enumerate() {
            if !live && self.heap[i].is_some() {
                self.heap[i] = None;
                self.scope_bindings.remove(&i);
                self.scope_parents.remove(&i);
                self.finalized.remove(&i);
                self.free.push(i);
                count += 1;
            }
        }
        self.gc_running = false;
        self.allocations = 0;
        count
    }
}

impl Runtime {
    fn method(
        &mut self,
        name: &str,
        receiver: Value,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        if let Value::Obj(i) = receiver.clone() {
            if matches!(
                self.heap.get(i).and_then(|o| o.as_ref()),
                Some(Object::List(_) | Object::Tuple(_))
            ) {
                match name {
                    "append" => {
                        let value = args
                            .first()
                            .cloned()
                            .ok_or_else(|| pyerr("TypeError", "append expected 1 argument"))?;
                        if let Some(Object::List(xs)) = self.heap[i].as_mut() {
                            xs.push(value)
                        }
                        return Ok(Value::None);
                    }
                    "clear" => {
                        if let Some(Object::List(xs)) = self.heap[i].as_mut() {
                            xs.clear()
                        }
                        return Ok(Value::None);
                    }
                    "reverse" => {
                        if let Some(Object::List(xs)) = self.heap[i].as_mut() {
                            xs.reverse()
                        }
                        return Ok(Value::None);
                    }
                    "pop" | "popleft" => {
                        let len = match self.heap[i].as_ref() {
                            Some(Object::List(xs)) => xs.len(),
                            _ => 0,
                        };
                        if len == 0 {
                            return Err(pyerr("IndexError", "pop from empty list"));
                        }
                        let at = if name == "popleft" {
                            0
                        } else if let Some(key) = args.first() {
                            self.index(key, len)?
                        } else {
                            len - 1
                        };
                        if let Some(Object::List(xs)) = self.heap[i].as_mut() {
                            return Ok(xs.remove(at));
                        }
                    }
                    "extend" => {
                        let source = args
                            .first()
                            .cloned()
                            .ok_or_else(|| pyerr("TypeError", "extend expected 1 argument"))?;
                        let more = self.to_vec(source)?;
                        if let Some(Object::List(xs)) = self.heap[i].as_mut() {
                            xs.extend(more)
                        }
                        return Ok(Value::None);
                    }
                    _ => {}
                }
            }
        }
        let arg = |i: usize| {
            args.get(i)
                .cloned()
                .ok_or_else(|| pyerr("TypeError", format!("{}() missing argument", name)))
        };
        let kw = |n: &str| kwargs.iter().find(|(k, _)| k == n).map(|(_, v)| v.clone());
        if name == "__iter__" {
            return self.iter(receiver);
        }
        if name == "__next__" {
            return self
                .next(receiver)?
                .ok_or_else(|| pyerr("StopIteration", ""));
        }
        if name == "__len__" {
            return self.builtin("len", vec![receiver], Vec::new(), None);
        }
        if name == "__getitem__" {
            return self.getitem(receiver, arg(0)?);
        }
        if name == "__contains__" {
            let values = self.to_vec(receiver)?;
            return Ok(Value::Bool(self.contains_vec(&values, &arg(0)?)?));
        }
        if let Value::Int(n) = &receiver {
            return match name {
                "bit_length" => Ok(Value::Int(Int::from_i128(n.bit_length() as i128))),
                "bit_count" => Ok(Value::Int(Int::from_i128(n.bit_count() as i128))),
                "__index__" | "__int__" | "conjugate" => Ok(receiver),
                _ => Err(pyerr("AttributeError", name)),
            };
        }
        if let Value::Bytes(b) = &receiver {
            if let Some(result) = self.bytes_method(b.clone(), name, args.clone(), kwargs.clone()) {
                return result;
            }
            match name {
                "decode" => {
                    return Ok(Value::Str(
                        String::from_utf8(b.clone())
                            .map_err(|_| pyerr("ValueError", "invalid UTF-8"))?,
                    ))
                }
                "hex" => return Ok(Value::Str(b.iter().map(|x| format!("{:02x}", x)).collect())),
                _ => {}
            }
        }
        if let Value::Str(s) = receiver.clone() {
            if let Some(result) = self.text_method(s.clone(), name, args.clone(), kwargs.clone()) {
                return result;
            }
            let strarg = |i: usize| match args.get(i) {
                Some(Value::Str(s)) => Ok(s.clone()),
                _ => Err(pyerr("TypeError", "expected str argument")),
            };
            let result = match name {
                "split" | "rsplit" => {
                    let sep = if args.is_empty() || matches!(args[0], Value::None) {
                        None
                    } else {
                        Some(strarg(0)?)
                    };
                    let limit = if args.len() > 1 {
                        self.as_int(&args[1])?.to_i128().unwrap_or(-1)
                    } else {
                        -1
                    };
                    let parts: Vec<String> = if let Some(sep) = sep {
                        if sep.is_empty() {
                            return Err(pyerr("ValueError", "empty separator"));
                        }
                        if limit < 0 {
                            s.split(&sep).map(String::from).collect()
                        } else if name == "rsplit" {
                            let mut p: Vec<_> = s
                                .rsplitn(limit as usize + 1, &sep)
                                .map(String::from)
                                .collect();
                            p.reverse();
                            p
                        } else {
                            s.splitn(limit as usize + 1, &sep)
                                .map(String::from)
                                .collect()
                        }
                    } else if limit < 0 {
                        s.split_whitespace().map(String::from).collect()
                    } else if limit == 0 {
                        vec![s.trim_start().to_string()]
                    } else {
                        let mut out = Vec::new();
                        let mut tail = s.trim_start();
                        for _ in 0..limit {
                            if tail.is_empty() {
                                break;
                            }
                            if let Some(p) = tail.find(char::is_whitespace) {
                                out.push(tail[..p].to_string());
                                tail = tail[p..].trim_start()
                            } else {
                                out.push(tail.to_string());
                                tail = "";
                                break;
                            }
                        }
                        if !tail.is_empty() {
                            out.push(tail.to_string())
                        }
                        out
                    };
                    return Ok(
                        self.obj_value(Object::List(parts.into_iter().map(Value::Str).collect()))
                    );
                }
                "splitlines" => {
                    return Ok(self.obj_value(Object::List(
                        s.lines().map(|s| Value::Str(s.into())).collect(),
                    )))
                }
                "strip" | "lstrip" | "rstrip" => {
                    let chars = if args.is_empty() || matches!(args[0], Value::None) {
                        None
                    } else {
                        Some(strarg(0)?)
                    };
                    let trim = |c: char| {
                        chars
                            .as_ref()
                            .map(|s| s.contains(c))
                            .unwrap_or_else(|| c.is_whitespace())
                    };
                    match name {
                        "lstrip" => s.trim_start_matches(trim),
                        "rstrip" => s.trim_end_matches(trim),
                        _ => s.trim_matches(trim),
                    }
                    .to_string()
                }
                "join" => {
                    let mut out = Vec::new();
                    for v in self.to_vec(arg(0)?)? {
                        if let Value::Str(s) = v {
                            out.push(s)
                        } else {
                            return Err(pyerr("TypeError", "sequence item expected str instance"));
                        }
                    }
                    out.join(&s)
                }
                "replace" => {
                    let a = strarg(0)?;
                    let b = strarg(1)?;
                    let limit = if args.len() > 2 {
                        self.as_int(&args[2])?.to_i128().unwrap_or(-1)
                    } else {
                        -1
                    };
                    if limit < 0 {
                        s.replace(&a, &b)
                    } else {
                        s.replacen(&a, &b, limit as usize)
                    }
                }
                "find" | "index" | "rfind" | "rindex" | "count" => {
                    let needle = strarg(0)?;
                    let chars: Vec<_> = s.chars().collect();
                    let norm = |n: i128| {
                        if n < 0 {
                            (n + chars.len() as i128).max(0).min(chars.len() as i128) as usize
                        } else {
                            n.min(chars.len() as i128) as usize
                        }
                    };
                    let start = if args.len() > 1 {
                        norm(self.as_int(&args[1])?.to_i128().unwrap_or(0))
                    } else {
                        0
                    };
                    let stop = if args.len() > 2 {
                        norm(
                            self.as_int(&args[2])?
                                .to_i128()
                                .unwrap_or(chars.len() as i128),
                        )
                    } else {
                        chars.len()
                    };
                    let segment: String = chars[start..stop.max(start)].iter().collect();
                    let n = if name == "count" {
                        if needle.is_empty() {
                            segment.chars().count() as i128 + 1
                        } else {
                            segment.matches(&needle).count() as i128
                        }
                    } else {
                        let p = if name.starts_with('r') {
                            segment.rfind(&needle)
                        } else {
                            segment.find(&needle)
                        };
                        match p {
                            Some(p) => (start + segment[..p].chars().count()) as i128,
                            None => -1,
                        }
                    };
                    if n < 0 && (name == "index" || name == "rindex") {
                        return Err(pyerr("ValueError", "substring not found"));
                    }
                    return Ok(Value::Int(Int::from_i128(n)));
                }
                "startswith" | "endswith" => {
                    let value = arg(0)?;
                    let values = if let Value::Obj(i) = &value {
                        if let Object::Tuple(v) = self.object(*i)? {
                            v
                        } else {
                            vec![value]
                        }
                    } else {
                        vec![value]
                    };
                    let mut yes = false;
                    for v in values {
                        let p = self.str_value(&v)?;
                        yes |= if name == "startswith" {
                            s.starts_with(&p)
                        } else {
                            s.ends_with(&p)
                        }
                    }
                    return Ok(Value::Bool(yes));
                }
                "upper" => s.to_uppercase(),
                "lower" | "casefold" => s.to_lowercase(),
                "capitalize" => {
                    let mut cs = s.chars();
                    match cs.next() {
                        Some(c) => format!("{}{}", c.to_uppercase(), cs.as_str().to_lowercase()),
                        None => s,
                    }
                }
                "swapcase" => s
                    .chars()
                    .flat_map(|c| {
                        if c.is_lowercase() {
                            c.to_uppercase().collect::<Vec<_>>()
                        } else {
                            c.to_lowercase().collect()
                        }
                    })
                    .collect(),
                "title" => {
                    let mut beginning = true;
                    let mut out = String::new();
                    for c in s.chars() {
                        if beginning {
                            out.extend(c.to_uppercase())
                        } else {
                            out.extend(c.to_lowercase())
                        }
                        beginning = !c.is_alphabetic()
                    }
                    out
                }
                "isdigit" | "isdecimal" | "isnumeric" => {
                    return Ok(Value::Bool(
                        !s.is_empty() && s.chars().all(|c| c.is_numeric()),
                    ))
                }
                "isalpha" => {
                    return Ok(Value::Bool(
                        !s.is_empty() && s.chars().all(char::is_alphabetic),
                    ))
                }
                "isalnum" => {
                    return Ok(Value::Bool(
                        !s.is_empty() && s.chars().all(char::is_alphanumeric),
                    ))
                }
                "isspace" => {
                    return Ok(Value::Bool(
                        !s.is_empty() && s.chars().all(char::is_whitespace),
                    ))
                }
                "islower" => {
                    return Ok(Value::Bool(
                        s.chars().any(char::is_lowercase) && s.chars().all(|c| !c.is_uppercase()),
                    ))
                }
                "isupper" => {
                    return Ok(Value::Bool(
                        s.chars().any(char::is_uppercase) && s.chars().all(|c| !c.is_lowercase()),
                    ))
                }
                "zfill" | "ljust" | "rjust" | "center" => {
                    let width = self.as_int(&arg(0)?)?.to_usize().unwrap_or(0);
                    let count = width.saturating_sub(s.chars().count());
                    let fill = if name == "zfill" {
                        '0'
                    } else if args.len() > 1 {
                        let fill = strarg(1)?;
                        if fill.chars().count() != 1 {
                            return Err(pyerr(
                                "TypeError",
                                "fill character must be exactly one character long",
                            ));
                        }
                        fill.chars().next().unwrap()
                    } else {
                        ' '
                    };
                    if name == "zfill" && (s.starts_with('-') || s.starts_with('+')) {
                        format!("{}{}{}", &s[..1], "0".repeat(count), &s[1..])
                    } else if name == "ljust" {
                        format!("{}{}", s, fill.to_string().repeat(count))
                    } else if name == "center" {
                        format!(
                            "{}{}{}",
                            fill.to_string().repeat(count / 2),
                            s,
                            fill.to_string().repeat(count - count / 2)
                        )
                    } else {
                        format!("{}{}", fill.to_string().repeat(count), s)
                    }
                }
                "removeprefix" => s.strip_prefix(&strarg(0)?).unwrap_or(&s).to_string(),
                "removesuffix" => s.strip_suffix(&strarg(0)?).unwrap_or(&s).to_string(),
                "partition" | "rpartition" => {
                    let sep = strarg(0)?;
                    if sep.is_empty() {
                        return Err(pyerr("ValueError", "empty separator"));
                    }
                    let p = if name == "partition" {
                        s.find(&sep)
                    } else {
                        s.rfind(&sep)
                    };
                    let out = if let Some(p) = p {
                        vec![
                            Value::Str(s[..p].into()),
                            Value::Str(sep.clone()),
                            Value::Str(s[p + sep.len()..].into()),
                        ]
                    } else if name == "partition" {
                        vec![Value::Str(s), Value::Str("".into()), Value::Str("".into())]
                    } else {
                        vec![Value::Str("".into()), Value::Str("".into()), Value::Str(s)]
                    };
                    return Ok(self.obj_value(Object::Tuple(out)));
                }
                "encode" => return Ok(Value::Bytes(s.into_bytes())),
                "format" => {
                    let mut out = String::new();
                    let mut it = s.chars().peekable();
                    let mut auto = 0;
                    while let Some(c) = it.next() {
                        if c == '{' {
                            if it.peek() == Some(&'{') {
                                it.next();
                                out.push('{');
                                continue;
                            }
                            let mut field = String::new();
                            while let Some(c) = it.next() {
                                if c == '}' {
                                    break;
                                }
                                field.push(c)
                            }
                            let (mut key, spec) = field.split_once(':').unwrap_or((&field, ""));
                            let repr = key.ends_with("!r");
                            if repr {
                                key = &key[..key.len() - 2]
                            }
                            let v = if key.is_empty() {
                                let v = arg(auto)?;
                                auto += 1;
                                v
                            } else if let Ok(i) = key.parse::<usize>() {
                                arg(i)?
                            } else {
                                kw(key).ok_or_else(|| pyerr("KeyError", key))?
                            };
                            out.push_str(&if repr {
                                self.repr(&v)?
                            } else {
                                self.format_value(v, spec)?
                            })
                        } else if c == '}' && it.peek() == Some(&'}') {
                            it.next();
                            out.push('}')
                        } else {
                            out.push(c)
                        }
                    }
                    out
                }
                _ => return Err(pyerr("AttributeError", name)),
            };
            return Ok(Value::Str(result));
        }
        if let Value::Obj(i) = receiver.clone() {
            match self.object(i)? {
                Object::List(mut xs) | Object::Tuple(mut xs) => {
                    let tuple = matches!(self.object(i)?, Object::Tuple(_));
                    match name {
                        "append" => xs.push(arg(0)?),
                        "appendleft" => xs.insert(0, arg(0)?),
                        "extend" => xs.extend(self.to_vec(arg(0)?)?),
                        "extendleft" => {
                            let mut more = self.to_vec(arg(0)?)?;
                            more.reverse();
                            more.extend(xs);
                            xs = more
                        }
                        "insert" => {
                            let n = self.as_int(&arg(0)?)?.to_i128().unwrap_or(0);
                            let at = if n < 0 {
                                (n + xs.len() as i128).max(0)
                            } else {
                                n.min(xs.len() as i128)
                            };
                            xs.insert(at as usize, arg(1)?)
                        }
                        "pop" | "popleft" => {
                            if xs.is_empty() {
                                return Err(pyerr("IndexError", "pop from empty list"));
                            }
                            let at = if name == "popleft" {
                                0
                            } else if args.is_empty() {
                                xs.len() - 1
                            } else {
                                self.index(&args[0], xs.len())?
                            };
                            let v = xs.remove(at);
                            self.heap[i] = Some(Object::List(xs));
                            return Ok(v);
                        }
                        "remove" => {
                            let v = arg(0)?;
                            let mut found = None;
                            for (j, x) in xs.iter().enumerate() {
                                if self.equal(x, &v)? {
                                    found = Some(j);
                                    break;
                                }
                            }
                            xs.remove(found.ok_or_else(|| {
                                pyerr("ValueError", "list.remove(x): x not in list")
                            })?);
                        }
                        "count" => {
                            let v = arg(0)?;
                            let mut n = 0;
                            for x in &xs {
                                if self.equal(x, &v)? {
                                    n += 1
                                }
                            }
                            return Ok(Value::Int(Int::from_i128(n)));
                        }
                        "index" => {
                            let v = arg(0)?;
                            let start = if args.len() > 1 {
                                self.as_int(&args[1])?.to_usize().unwrap_or(0)
                            } else {
                                0
                            };
                            let stop = if args.len() > 2 {
                                self.as_int(&args[2])?
                                    .to_usize()
                                    .unwrap_or(xs.len())
                                    .min(xs.len())
                            } else {
                                xs.len()
                            };
                            for j in start..stop {
                                if self.equal(&xs[j], &v)? {
                                    return Ok(Value::Int(Int::from_i128(j as i128)));
                                }
                            }
                            return Err(pyerr("ValueError", "value is not in sequence"));
                        }
                        "clear" => xs.clear(),
                        "reverse" => xs.reverse(),
                        "copy" => {
                            return Ok(self.obj_value(if tuple {
                                Object::Tuple(xs)
                            } else {
                                Object::List(xs)
                            }))
                        }
                        "rotate" => {
                            if !xs.is_empty() {
                                let n = if args.is_empty() {
                                    1
                                } else {
                                    self.as_int(&args[0])?.to_i128().unwrap_or(0)
                                };
                                let n = n.rem_euclid(xs.len() as i128) as usize;
                                xs.rotate_right(n)
                            }
                        }
                        "sort" => {
                            let reverse = kw("reverse")
                                .map(|v| self.truth(&v))
                                .transpose()?
                                .unwrap_or(false);
                            xs = self.sort_values(xs, kw("key"), reverse)?
                        }
                        _ => return Err(pyerr("AttributeError", name)),
                    }
                    self.heap[i] = Some(if tuple {
                        Object::Tuple(xs)
                    } else {
                        Object::List(xs)
                    });
                    return Ok(Value::None);
                }
                Object::Dict(mut xs) => {
                    match name {
                        "get" => {
                            return match self.getitem(receiver, arg(0)?) {
                                Ok(v) => Ok(v),
                                Err(e) if e.kind == "KeyError" => {
                                    Ok(args.get(1).cloned().unwrap_or(Value::None))
                                }
                                Err(e) => Err(e),
                            }
                        }
                        "keys" | "values" | "items" => {
                            let mut vs = Vec::new();
                            for (k, v) in xs {
                                vs.push(match name {
                                    "keys" => k,
                                    "values" => v,
                                    _ => self.obj_value(Object::Tuple(vec![k, v])),
                                })
                            }
                            return Ok(self.obj_value(Object::List(vs)));
                        }
                        "pop" => {
                            let k = arg(0)?;
                            if let Some(p) = self.find_key(&xs, &k)? {
                                let v = xs.remove(p).1;
                                self.heap[i] = Some(Object::Dict(xs));
                                return Ok(v);
                            }
                            return args
                                .get(1)
                                .cloned()
                                .ok_or_else(|| pyerr("KeyError", "key not found"));
                        }
                        "popitem" => {
                            let (k, v) = xs.pop().ok_or_else(|| {
                                pyerr("KeyError", "popitem(): dictionary is empty")
                            })?;
                            self.heap[i] = Some(Object::Dict(xs));
                            return Ok(self.obj_value(Object::Tuple(vec![k, v])));
                        }
                        "setdefault" => {
                            let k = arg(0)?;
                            if let Some(p) = self.find_key(&xs, &k)? {
                                return Ok(xs[p].1.clone());
                            }
                            let v = args.get(1).cloned().unwrap_or(Value::None);
                            xs.push((k, v.clone()));
                            self.heap[i] = Some(Object::Dict(xs));
                            return Ok(v);
                        }
                        "update" => {
                            if let Some(v) = args.first() {
                                for (k, v) in self.dict_items(v.clone())? {
                                    if let Some(p) = self.find_key(&xs, &k)? {
                                        xs[p].1 = v
                                    } else {
                                        xs.push((k, v))
                                    }
                                }
                            }
                            for (k, v) in kwargs {
                                let k = Value::Str(k);
                                if let Some(p) = self.find_key(&xs, &k)? {
                                    xs[p].1 = v
                                } else {
                                    xs.push((k, v))
                                }
                            }
                        }
                        "clear" => xs.clear(),
                        "copy" => return Ok(self.obj_value(Object::Dict(xs))),
                        _ => return Err(pyerr("AttributeError", name)),
                    }
                    self.heap[i] = Some(Object::Dict(xs));
                    return Ok(Value::None);
                }
                Object::Namespace(m, parent) => {
                    let mut xs: Vec<_> = m.into_iter().map(|(k, v)| (Value::Str(k), v)).collect();
                    self.heap[i] = Some(Object::Dict(xs));
                    let result = self.method(name, receiver.clone(), args, kwargs);
                    if let Some(Some(Object::Dict(entries))) = self.heap.get(i) {
                        xs = entries.clone();
                        let mut map = HashMap::new();
                        for (k, v) in xs {
                            if let Value::Str(k) = k {
                                map.insert(k, v);
                            }
                        }
                        self.heap[i] = Some(Object::Namespace(map, parent));
                    }
                    return result;
                }
                Object::Set(mut xs) => {
                    match name {
                        "add" => {
                            let v = arg(0)?;
                            if !self.contains_vec(&xs, &v)? {
                                xs.push(v)
                            }
                        }
                        "update" => {
                            for a in args {
                                for v in self.to_vec(a)? {
                                    if !self.contains_vec(&xs, &v)? {
                                        xs.push(v)
                                    }
                                }
                            }
                        }
                        "remove" | "discard" => {
                            let v = arg(0)?;
                            let mut at = None;
                            for (j, x) in xs.iter().enumerate() {
                                if self.equal(x, &v)? {
                                    at = Some(j);
                                    break;
                                }
                            }
                            if let Some(p) = at {
                                xs.remove(p);
                            } else if name == "remove" {
                                return Err(pyerr("KeyError", "value not found"));
                            }
                        }
                        "pop" => {
                            let v = xs
                                .pop()
                                .ok_or_else(|| pyerr("KeyError", "pop from empty set"))?;
                            self.heap[i] = Some(Object::Set(xs));
                            return Ok(v);
                        }
                        "clear" => xs.clear(),
                        "copy" => return Ok(self.obj_value(Object::Set(xs))),
                        "union" | "intersection" | "difference" | "symmetric_difference" => {
                            return self.binary(
                                match name {
                                    "union" => "|",
                                    "intersection" => "&",
                                    "difference" => "-",
                                    _ => "^",
                                },
                                receiver,
                                arg(0)?,
                            )
                        }
                        "issubset" | "issuperset" | "isdisjoint" => {
                            let ys = self.to_vec(arg(0)?)?;
                            let (a, b) = if name == "issuperset" {
                                (&ys, &xs)
                            } else {
                                (&xs, &ys)
                            };
                            for v in a {
                                let found = self.contains_vec(b, v)?;
                                if (name == "isdisjoint" && found)
                                    || (name != "isdisjoint" && !found)
                                {
                                    return Ok(Value::Bool(false));
                                }
                            }
                            return Ok(Value::Bool(true));
                        }
                        _ => return Err(pyerr("AttributeError", name)),
                    }
                    self.heap[i] = Some(Object::Set(xs));
                    return Ok(Value::None);
                }
                Object::Generator(mut frame) => match name {
                    "send" => {
                        let v = arg(0)?;
                        if frame.pc == 0 && !matches!(v, Value::None) {
                            return Err(pyerr(
                                "TypeError",
                                "can't send non-None value to a just-started generator",
                            ));
                        }
                        frame.resume_value = Some(v);
                        self.heap[i] = Some(Object::Generator(frame));
                        return self
                            .next(receiver)?
                            .ok_or_else(|| pyerr("StopIteration", ""));
                    }
                    "close" => {
                        if frame.pc == 0 || frame.pc == usize::MAX {
                            frame.pc = usize::MAX;
                            self.heap[i] = Some(Object::Generator(frame));
                            return Ok(Value::None);
                        }
                        frame.injected_exception = Some(pyerr("GeneratorExit", ""));
                        self.heap[i] = Some(Object::Generator(frame));
                        return match self.next(receiver) {
                            Ok(None) => Ok(Value::None),
                            Ok(Some(_)) => {
                                Err(pyerr("RuntimeError", "generator ignored GeneratorExit"))
                            }
                            Err(e) if e.kind == "GeneratorExit" || e.kind == "StopIteration" => {
                                Ok(Value::None)
                            }
                            Err(e) => Err(e),
                        };
                    }
                    "throw" => {
                        let value = arg(0)?;
                        let value = if matches!(value, Value::Type(_)) && args.len() > 1 {
                            self.call(value, vec![args[1].clone()], Vec::new(), None)?
                        } else {
                            value
                        };
                        let error = self.as_exception(value)?;
                        if frame.pc == usize::MAX {
                            return Err(error);
                        }
                        frame.injected_exception = Some(error);
                        self.heap[i] = Some(Object::Generator(frame));
                        return self
                            .next(receiver)?
                            .ok_or_else(|| pyerr("StopIteration", ""));
                    }
                    _ => {}
                },
                _ => {}
            }
        }
        Err(pyerr(
            "AttributeError",
            format!("method '{}' is not available", name),
        ))
    }
}

impl Runtime {
    fn builtin(
        &mut self,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
        caller: Option<&Frame>,
    ) -> PyResult<Value> {
        if name == "dict:fromkeys" {
            let iterable = args
                .first()
                .cloned()
                .ok_or_else(|| pyerr("TypeError", "fromkeys expected at least 1 argument"))?;
            let value = args.get(1).cloned().unwrap_or(Value::None);
            let dict = self.obj_value(Object::Dict(Vec::new()));
            let root = self.roots.len();
            self.roots.push(vec![dict.clone(), value.clone()]);
            let result = (|| {
                let iterator = self.iter(iterable)?;
                self.roots[root].push(iterator.clone());
                while let Some(key) = self.next(iterator.clone())? {
                    self.setitem(dict.clone(), key, value.clone())?
                }
                Ok(dict)
            })();
            self.roots.truncate(root);
            return result;
        }
        if let Some(method) = name.strip_prefix("unbound:") {
            let (owner, method) = method.split_once(':').unwrap_or(("", method));
            let mut args = args;
            if let Some(Value::Obj(i)) = args.first() {
                if let Object::BuiltinInstance { payload, .. } = self.object(*i)? {
                    if self.typename(&payload) == owner {
                        args[0] = payload
                    }
                }
            }
            if args.is_empty() {
                return Err(pyerr("TypeError", "unbound descriptor needs an instance"));
            }
            if method == "__setitem__" {
                self.setitem(
                    args[0].clone(),
                    args.get(1)
                        .cloned()
                        .ok_or_else(|| pyerr("TypeError", "missing key"))?,
                    args.get(2)
                        .cloned()
                        .ok_or_else(|| pyerr("TypeError", "missing value"))?,
                )?;
                return Ok(Value::None);
            }
            return self.method(method, args[0].clone(), args[1..].to_vec(), kwargs);
        }
        if name == "descriptor:get" {
            let descriptor = args
                .first()
                .cloned()
                .ok_or_else(|| pyerr("TypeError", "missing descriptor"))?;
            let instance = args.get(1).cloned().filter(|v| !matches!(v, Value::None));
            let class = if let Some(v) = args.get(2) {
                v.clone()
            } else if let Some(v) = &instance {
                self.getattr(v.clone(), "__class__")?
            } else {
                Value::None
            };
            return self.bind_descriptor(descriptor, instance, class);
        }
        if let Some(method) = name.strip_prefix("cache:") {
            let i = match args.first() {
                Some(Value::Obj(i)) => *i,
                _ => return Err(pyerr("TypeError", "invalid cache wrapper")),
            };
            let mut cache = match self.object(i)? {
                Object::Cached(c) => c,
                _ => return Err(pyerr("TypeError", "invalid cache wrapper")),
            };
            return match method {
                "cache_info" => Ok(self.obj_value(Object::Record {
                    name: "CacheInfo".into(),
                    fields: vec![
                        (
                            "hits".into(),
                            Value::Int(Int::from_i128(cache.hits as i128)),
                        ),
                        (
                            "misses".into(),
                            Value::Int(Int::from_i128(cache.misses as i128)),
                        ),
                        (
                            "maxsize".into(),
                            cache
                                .maxsize
                                .map(|n| Value::Int(Int::from_i128(n as i128)))
                                .unwrap_or(Value::None),
                        ),
                        (
                            "currsize".into(),
                            Value::Int(Int::from_i128(cache.entries.len() as i128)),
                        ),
                    ],
                })),
                "cache_clear" => {
                    cache.entries.clear();
                    cache.hits = 0;
                    cache.misses = 0;
                    self.heap[i] = Some(Object::Cached(cache));
                    Ok(Value::None)
                }
                "cache_parameters" => Ok(self.obj_value(Object::Dict(vec![
                    (
                        Value::Str("maxsize".into()),
                        cache
                            .maxsize
                            .map(|n| Value::Int(Int::from_i128(n as i128)))
                            .unwrap_or(Value::None),
                    ),
                    (Value::Str("typed".into()), Value::Bool(cache.typed)),
                ]))),
                _ => Err(pyerr("AttributeError", method)),
            };
        }
        if let Some(method) = name.strip_prefix("property:") {
            if args.len() < 2 {
                return Err(pyerr("TypeError", "missing property function"));
            }
            if let Value::Obj(i) = args[0] {
                if let Object::Property {
                    mut get,
                    mut set,
                    mut del,
                } = self.object(i)?
                {
                    match method {
                        "getter" => get = args[1].clone(),
                        "setter" => set = Some(args[1].clone()),
                        "deleter" => del = Some(args[1].clone()),
                        _ => {}
                    }
                    return Ok(self.obj_value(Object::Property { get, set, del }));
                }
            }
            return Err(pyerr("TypeError", "invalid property"));
        }
        if let Some(method) = name.strip_prefix("method:") {
            if args.is_empty() {
                return Err(pyerr("TypeError", "unbound method"));
            }
            return self.method(method, args[0].clone(), args[1..].to_vec(), kwargs);
        }
        if let Some(rest) = name.strip_prefix("type_method:") {
            let mut p = rest.split(':');
            let typ = p.next().unwrap_or("");
            let method = p.next().unwrap_or("");
            if typ == "object"
                && ["__getattribute__", "__setattr__", "__delattr__"].contains(&method)
            {
                let obj = args
                    .first()
                    .cloned()
                    .ok_or_else(|| pyerr("TypeError", "missing object"))?;
                let n = args
                    .get(1)
                    .cloned()
                    .ok_or_else(|| pyerr("TypeError", "missing attribute name"))?;
                let n = self.str_value(&n)?;
                return match method {
                    "__getattribute__" => self.getattr_default(obj, &n),
                    "__setattr__" => {
                        let value = args
                            .get(2)
                            .cloned()
                            .ok_or_else(|| pyerr("TypeError", "missing attribute value"))?;
                        self.setattr_default(obj, &n, value)?;
                        Ok(Value::None)
                    }
                    _ => {
                        self.delattr_default(obj, &n)?;
                        Ok(Value::None)
                    }
                };
            }
            if typ == "tuple" && method == "__new__" {
                let class = args
                    .first()
                    .cloned()
                    .ok_or_else(|| pyerr("TypeError", "tuple.__new__ needs class"))?;
                return self.builtin_instance_new("tuple", class, args[1..].to_vec(), kwargs);
            }
            if method == "__init__" {
                return Ok(Value::None);
            }
            if typ == "type" {
                if args.len() < 4 {
                    return Err(pyerr("TypeError", "type.__new__ needs arguments"));
                }
                return self.construct_class(args[0].clone(), args[1..].to_vec(), kwargs);
            }
            if typ == "object" {
                let attrs = self.alloc(Object::Namespace(HashMap::new(), None));
                return Ok(self.obj_value(Object::Instance {
                    class: args
                        .get(0)
                        .cloned()
                        .unwrap_or(Value::Builtin("object".into())),
                    attrs,
                }));
            }
        }
        if name.starts_with("module:") {
            return self.module_call(name, args, kwargs);
        }
        let arg = |i: usize| {
            args.get(i)
                .cloned()
                .ok_or_else(|| pyerr("TypeError", format!("{}() missing required argument", name)))
        };
        let kw = |n: &str| kwargs.iter().find(|(k, _)| k == n).map(|(_, v)| v.clone());
        match name {
            "print" => {
                let sep = match kw("sep") {
                    None | Some(Value::None) => " ".into(),
                    Some(v) => self.str_value(&v)?,
                };
                let end = match kw("end") {
                    None | Some(Value::None) => "\n".into(),
                    Some(v) => self.str_value(&v)?,
                };
                let mut ss = Vec::new();
                for v in args {
                    ss.push(self.str_value(&v)?)
                }
                let text = format!("{}{}", ss.join(&sep), end);
                if let Some(file) = kw("file").filter(|v| !matches!(v, Value::None)) {
                    let write = self.getattr(file, "write")?;
                    self.call(write, vec![Value::Str(text)], Vec::new(), None)?;
                } else {
                    self.output.push_str(&text)
                }
                if let Some(flush) = kw("flush") {
                    if self.truth(&flush)? {
                        self.finish()
                    }
                }
                Ok(Value::None)
            }
            "input" => {
                if let Some(v) = args.first() {
                    let s = self.str_value(v)?;
                    self.output.push_str(&s)
                }
                if self.input_pos >= self.input.len() {
                    return Err(pyerr("EOFError", "EOF when reading a line"));
                }
                let tail = &self.input[self.input_pos..];
                let end = tail.iter().position(|b| *b == b'\n').unwrap_or(tail.len());
                let stop = if end > 0 && tail[end - 1] == b'\r' {
                    end - 1
                } else {
                    end
                };
                let text = String::from_utf8(tail[..stop].to_vec())
                    .map_err(|_| pyerr("UnicodeDecodeError", "input is not valid UTF-8"))?;
                self.input_pos += (end + 1).min(tail.len());
                Ok(Value::Str(text))
            }
            "int" => {
                let v = args
                    .first()
                    .cloned()
                    .unwrap_or(Value::Int(Int::from_i128(0)));
                Ok(Value::Int(match v {
                    Value::Int(i) => i,
                    Value::Bool(b) => Int::from_i128(if b { 1 } else { 0 }),
                    Value::Float(f) => Int::from_f64(f).map_err(int_error)?,
                    Value::Str(s) => {
                        let base = if args.len() > 1 {
                            self.as_int(&args[1])?.to_usize().unwrap_or(10) as u32
                        } else {
                            10
                        };
                        Int::parse(s.trim(), base).map_err(int_error)?
                    }
                    Value::Bytes(b) => {
                        let s = String::from_utf8(b)
                            .map_err(|_| pyerr("ValueError", "invalid literal for int"))?;
                        Int::parse(s.trim(), 10).map_err(int_error)?
                    }
                    v => {
                        if let Ok(fun) = self.special_method(v.clone(), "__int__") {
                            let out = self.call(fun, Vec::new(), Vec::new(), None)?;
                            self.as_int(&out)?
                        } else {
                            self.as_int(&v)?
                        }
                    }
                }))
            }
            "float" => {
                let v = args.first().cloned().unwrap_or(Value::Float(0.0));
                Ok(Value::Float(match v {
                    Value::Str(s) => s.trim().parse().map_err(|_| {
                        pyerr(
                            "ValueError",
                            format!("could not convert string to float: {:?}", s),
                        )
                    })?,
                    v => self.as_float(&v)?,
                }))
            }
            "bool" => Ok(Value::Bool(if args.is_empty() {
                false
            } else {
                self.truth(&args[0])?
            })),
            "str" => Ok(Value::Str(if args.is_empty() {
                String::new()
            } else {
                self.str_value(&args[0])?
            })),
            "repr" | "ascii" => Ok(Value::Str(self.repr(&arg(0)?)?)),
            "list" | "tuple" | "set" | "frozenset" => {
                let mut vs = if args.is_empty() {
                    Vec::new()
                } else {
                    self.to_vec(args[0].clone())?
                };
                if name == "set" || name == "frozenset" {
                    let mut unique = Vec::new();
                    for v in vs {
                        if !self.contains_vec(&unique, &v)? {
                            unique.push(v)
                        }
                    }
                    vs = unique
                }
                Ok(self.obj_value(match name {
                    "tuple" => Object::Tuple(vs),
                    "set" | "frozenset" => Object::Set(vs),
                    _ => Object::List(vs),
                }))
            }
            "dict" => {
                let d = self.obj_value(Object::Dict(Vec::new()));
                if let Some(v) = args.first() {
                    for (k, v) in self.dict_items(v.clone())? {
                        self.setitem(d.clone(), k, v)?
                    }
                }
                for (k, v) in kwargs {
                    self.setitem(d.clone(), Value::Str(k), v)?
                }
                Ok(d)
            }
            "bytes" | "bytearray" => {
                let out = if args.is_empty() {
                    Vec::new()
                } else {
                    match &args[0] {
                        Value::Bytes(b) => b.clone(),
                        Value::Str(s) => s.as_bytes().to_vec(),
                        Value::Int(n) => {
                            vec![
                                0;
                                n.to_usize()
                                    .ok_or_else(|| pyerr("ValueError", "negative count"))?
                            ]
                        }
                        v => {
                            let mut xs = Vec::new();
                            for v in self.to_vec(v.clone())? {
                                let n = self.as_int(&v)?.to_usize().ok_or_else(|| {
                                    pyerr("ValueError", "bytes must be in range(0, 256)")
                                })?;
                                if n > 255 {
                                    return Err(pyerr(
                                        "ValueError",
                                        "bytes must be in range(0, 256)",
                                    ));
                                }
                                xs.push(n as u8)
                            }
                            xs
                        }
                    }
                };
                Ok(Value::Bytes(out))
            }
            "len" => {
                let v = arg(0)?;
                let fastlen = if let Value::Obj(i) = &v {
                    match self.heap.get(*i).and_then(|o| o.as_ref()) {
                        Some(Object::List(xs) | Object::Tuple(xs) | Object::Set(xs)) => {
                            Some(xs.len())
                        }
                        Some(Object::Dict(xs)) => Some(xs.len()),
                        Some(Object::Namespace(xs, _)) => Some(xs.len()),
                        Some(Object::Record { fields, .. }) => Some(fields.len()),
                        _ => None,
                    }
                } else {
                    None
                };
                if let Some(n) = fastlen {
                    return Ok(Value::Int(Int::from_i128(n as i128)));
                }
                let n = match &v {
                    Value::Str(s) => s.chars().count(),
                    Value::Bytes(b) => b.len(),
                    Value::Obj(i) => match self.object(*i)? {
                        Object::List(v) | Object::Tuple(v) | Object::Set(v) => v.len(),
                        Object::Dict(v) => v.len(),
                        Object::Namespace(m, _) => m.len(),
                        Object::Range(a, b, s) => {
                            let d = if s.is_negative() {
                                a.sub(&b)
                            } else {
                                b.sub(&a)
                            };
                            if d.is_negative() || d.is_zero() {
                                0
                            } else {
                                let n = d
                                    .sub(&Int::from_i128(1))
                                    .divmod(&s.abs())
                                    .map_err(int_error)?
                                    .0
                                    .add(&Int::from_i128(1));
                                n.to_usize().ok_or_else(|| {
                                    pyerr("OverflowError", "range length too large")
                                })?
                            }
                        }
                        _ => {
                            let fun = self.special_method(v, "__len__")?;
                            return self.call(fun, Vec::new(), Vec::new(), caller);
                        }
                    },
                    _ => return Err(pyerr("TypeError", "object has no len()")),
                };
                Ok(Value::Int(Int::from_i128(n as i128)))
            }
            "range" => {
                if args.is_empty() || args.len() > 3 {
                    return Err(pyerr("TypeError", "range expected 1 to 3 arguments"));
                }
                let (start, stop) = if args.len() == 1 {
                    (Int::from_i128(0), self.as_int(&args[0])?)
                } else {
                    (self.as_int(&args[0])?, self.as_int(&args[1])?)
                };
                let step = if args.len() == 3 {
                    self.as_int(&args[2])?
                } else {
                    Int::from_i128(1)
                };
                if step.is_zero() {
                    return Err(pyerr("ValueError", "range() arg 3 must not be zero"));
                }
                Ok(self.obj_value(Object::Range(start, stop, step)))
            }
            "iter" => {
                if args.len() == 2 {
                    Ok(self.obj_value(Object::Iterator(IteratorState::Callable(
                        args[0].clone(),
                        args[1].clone(),
                    ))))
                } else {
                    self.iter(arg(0)?)
                }
            }
            "next" => match self.next(arg(0)?)? {
                Some(v) => Ok(v),
                None => {
                    if let Some(v) = args.get(1) {
                        Ok(v.clone())
                    } else {
                        Err(pyerr("StopIteration", ""))
                    }
                }
            },
            "enumerate" => {
                let it = self.iter(arg(0)?)?;
                let start = if args.len() > 1 {
                    self.as_int(&args[1])?
                } else {
                    Int::from_i128(0)
                };
                Ok(self.obj_value(Object::Iterator(IteratorState::Enumerate(it, start))))
            }
            "zip" => {
                let mut its = Vec::new();
                for v in args {
                    its.push(self.iter(v)?)
                }
                Ok(self.obj_value(Object::Iterator(IteratorState::Zip(its))))
            }
            "map" => {
                let fun = arg(0)?;
                let mut its = Vec::new();
                for v in args.iter().skip(1) {
                    its.push(self.iter(v.clone())?)
                }
                Ok(self.obj_value(Object::Iterator(IteratorState::Map(fun, its))))
            }
            "filter" => {
                let it = self.iter(arg(1)?)?;
                Ok(self.obj_value(Object::Iterator(IteratorState::Filter(arg(0)?, it))))
            }
            "sum" => {
                let mut out = args
                    .get(1)
                    .cloned()
                    .unwrap_or(Value::Int(Int::from_i128(0)));
                let it = self.iter(arg(0)?)?;
                while let Some(v) = self.next(it.clone())? {
                    out = self.binary("+", out, v)?
                }
                Ok(out)
            }
            "all" | "any" => {
                let it = self.iter(arg(0)?)?;
                while let Some(v) = self.next(it.clone())? {
                    let b = self.truth(&v)?;
                    if (name == "all" && !b) || (name == "any" && b) {
                        return Ok(Value::Bool(b));
                    }
                }
                Ok(Value::Bool(name == "all"))
            }
            "min" | "max" => {
                let values = if args.len() == 1 {
                    self.to_vec(args[0].clone())?
                } else {
                    args.clone()
                };
                let key = kw("key");
                let mut best = None;
                let mut bestkey = Value::None;
                for v in values {
                    let k = if let Some(fun) = &key {
                        if matches!(fun, Value::None) {
                            v.clone()
                        } else {
                            self.call(fun.clone(), vec![v.clone()], Vec::new(), caller)?
                        }
                    } else {
                        v.clone()
                    };
                    if best.is_none()
                        || self.compare(if name == "min" { "<" } else { ">" }, &k, &bestkey)?
                    {
                        best = Some(v);
                        bestkey = k
                    }
                }
                best.or_else(|| kw("default")).ok_or_else(|| {
                    pyerr("ValueError", format!("{}() arg is an empty sequence", name))
                })
            }
            "sorted" => {
                let values = self.to_vec(arg(0)?)?;
                let reverse = kw("reverse")
                    .map(|v| self.truth(&v))
                    .transpose()?
                    .unwrap_or(false);
                let out = self.sort_values(values, kw("key"), reverse)?;
                Ok(self.obj_value(Object::List(out)))
            }
            "reversed" => {
                let mut xs = self.to_vec(arg(0)?)?;
                xs.reverse();
                Ok(self.obj_value(Object::Iterator(IteratorState::Values(xs, 0))))
            }
            "abs" => {
                let v = arg(0)?;
                match v {
                    Value::Int(n) => Ok(Value::Int(n.abs())),
                    Value::Float(n) => Ok(Value::Float(n.abs())),
                    v => {
                        let fun = self.special_method(v, "__abs__")?;
                        self.call(fun, Vec::new(), Vec::new(), caller)
                    }
                }
            }
            "pow" => {
                if args.len() == 3 {
                    let a = self.as_int(&args[0])?;
                    let b = self.as_int(&args[1])?;
                    let m = self.as_int(&args[2])?;
                    Ok(Value::Int(a.modpow(&b, &m).map_err(int_error)?))
                } else {
                    self.binary("**", arg(0)?, arg(1)?)
                }
            }
            "divmod" => {
                let a = self.binary("//", arg(0)?, arg(1)?)?;
                let b = self.binary("%", arg(0)?, arg(1)?)?;
                Ok(self.obj_value(Object::Tuple(vec![a, b])))
            }
            "round" => {
                let x = self.as_float(&arg(0)?)?;
                let n = if args.len() > 1 {
                    self.as_int(&args[1])?.to_i128().unwrap_or(0)
                } else {
                    0
                };
                let scale = 10f64.powf(n as f64);
                let y = x * scale;
                let rounded = if y.fract().abs() == 0.5 {
                    (y / 2.0).round() * 2.0
                } else {
                    y.round()
                } / scale;
                if args.len() > 1 {
                    Ok(Value::Float(rounded))
                } else {
                    Ok(Value::Int(Int::from_f64(rounded).map_err(int_error)?))
                }
            }
            "bin" | "oct" | "hex" => {
                let n = self
                    .as_int(&arg(0)?)?
                    .to_i128()
                    .ok_or_else(|| pyerr("OverflowError", "integer too large for formatting"))?;
                let sign = if n < 0 { "-" } else { "" };
                let mag = n.unsigned_abs();
                Ok(Value::Str(match name {
                    "bin" => format!("{}0b{:b}", sign, mag),
                    "oct" => format!("{}0o{:o}", sign, mag),
                    _ => format!("{}0x{:x}", sign, mag),
                }))
            }
            "chr" => {
                let n = self
                    .as_int(&arg(0)?)?
                    .to_usize()
                    .ok_or_else(|| pyerr("ValueError", "chr() arg not in range(0x110000)"))?;
                Ok(Value::Str(
                    char::from_u32(n as u32)
                        .ok_or_else(|| pyerr("ValueError", "chr() arg not in range(0x110000)"))?
                        .to_string(),
                ))
            }
            "ord" => match arg(0)? {
                Value::Str(s) => {
                    let cs: Vec<_> = s.chars().collect();
                    if cs.len() != 1 {
                        return Err(pyerr("TypeError", "ord() expected a character"));
                    }
                    Ok(Value::Int(Int::from_i128(cs[0] as i128)))
                }
                Value::Bytes(b) if b.len() == 1 => Ok(Value::Int(Int::from_i128(b[0] as i128))),
                _ => Err(pyerr("TypeError", "ord() expected a character")),
            },
            "format" => {
                let spec = if args.len() > 1 {
                    self.str_value(&args[1])?
                } else {
                    String::new()
                };
                Ok(Value::Str(self.format_value(arg(0)?, &spec)?))
            }
            "getattr" => {
                let n = self.str_value(&arg(1)?)?;
                match self.getattr(arg(0)?, &n) {
                    Err(e) if e.kind == "AttributeError" && args.len() > 2 => Ok(args[2].clone()),
                    v => v,
                }
            }
            "setattr" => {
                let n = self.str_value(&arg(1)?)?;
                self.setattr(arg(0)?, &n, arg(2)?)?;
                Ok(Value::None)
            }
            "delattr" => {
                let n = self.str_value(&arg(1)?)?;
                self.delattr(arg(0)?, &n)?;
                Ok(Value::None)
            }
            "hasattr" => {
                let n = self.str_value(&arg(1)?)?;
                match self.getattr(arg(0)?, &n) {
                    Ok(_) => Ok(Value::Bool(true)),
                    Err(e) if e.kind == "AttributeError" => Ok(Value::Bool(false)),
                    Err(e) => Err(e),
                }
            }
            "callable" => {
                let v = arg(0)?;
                Ok(Value::Bool(match &v {
                    Value::Builtin(_) | Value::Type(_) => true,
                    Value::Obj(i) => {
                        matches!(
                            self.object(*i)?,
                            Object::Function(_)
                                | Object::Bound(..)
                                | Object::Class(_)
                                | Object::Cached(_)
                        ) || self.getattr(v.clone(), "__call__").is_ok()
                    }
                    _ => false,
                }))
            }
            "type" => {
                if args.len() == 3 {
                    return self.construct_class(Value::Builtin("type".into()), args, kwargs);
                }
                let v = arg(0)?;
                self.getattr(v, "__class__")
            }
            "isinstance" | "issubclass" => {
                let v = arg(0)?;
                let cls = arg(1)?;
                let actual = if name == "isinstance" {
                    self.getattr(v.clone(), "__class__")?
                } else {
                    v.clone()
                };
                Ok(Value::Bool(self.is_subclass(&actual, &cls)?))
            }
            "object" => {
                let attrs = self.alloc(Object::Namespace(HashMap::new(), None));
                Ok(self.obj_value(Object::Instance {
                    class: Value::Builtin("object".into()),
                    attrs,
                }))
            }
            "id" => {
                let v = arg(0)?;
                let id = match v {
                    Value::Obj(i) => i as i128 + 1000,
                    Value::None => 1,
                    Value::Bool(false) => 2,
                    Value::Bool(true) => 3,
                    _ => {
                        use std::hash::{Hash, Hasher};
                        let mut h = std::collections::hash_map::DefaultHasher::new();
                        self.repr(&v)?.hash(&mut h);
                        (h.finish() & 0x7fffffffffffffff) as i128
                    }
                };
                Ok(Value::Int(Int::from_i128(id)))
            }
            "hash" => {
                use std::hash::{Hash, Hasher};
                let v = arg(0)?;
                if let Some(class) = self.object_class(&v) {
                    if let Some(method) = self.class_lookup(&class, "__hash__", 0) {
                        if matches!(method, Value::None) {
                            return Err(pyerr(
                                "TypeError",
                                format!("unhashable type: '{}'", self.typename(&v)),
                            ));
                        }
                        let method = self.obj_value(Object::Bound(method, v.clone()));
                        let result = self.call(method, Vec::new(), Vec::new(), None)?;
                        if !matches!(result, Value::Int(_) | Value::Bool(_)) {
                            return Err(pyerr(
                                "TypeError",
                                "__hash__ method should return an integer",
                            ));
                        }
                        return Ok(Value::Int(self.as_int(&result)?));
                    }
                }
                if let Some(payload) = self.native_payload(&v) {
                    return self.builtin("hash", vec![payload], Vec::new(), None);
                }
                if let Value::Obj(i) = v {
                    match self.heap.get(i).and_then(|o| o.as_ref()) {
                        Some(
                            Object::List(_)
                            | Object::Dict(_)
                            | Object::Set(_)
                            | Object::Namespace(_, _),
                        ) => {
                            return Err(pyerr(
                                "TypeError",
                                format!("unhashable type: '{}'", self.typename(&v)),
                            ));
                        }
                        Some(Object::Instance { .. }) => {
                            return Ok(Value::Int(Int::from_i128(i as i128)))
                        }
                        _ => {}
                    }
                }
                if let Value::Int(n) = v {
                    return Ok(Value::Int(n));
                }
                if let Value::Bool(b) = v {
                    return Ok(Value::Int(Int::from_i128(if b { 1 } else { 0 })));
                }
                let mut h = std::collections::hash_map::DefaultHasher::new();
                self.repr(&v)?.hash(&mut h);
                Ok(Value::Int(Int::from_i128(h.finish() as i64 as i128)))
            }
            "globals" => Ok(Value::Obj(
                caller.map(|f| f.globals).unwrap_or(self.globals),
            )),
            "locals" | "vars" => {
                if let Some(v) = args.first() {
                    let entries = self.attribute_items(v)?;
                    return Ok(self.obj_value(Object::Dict(
                        entries
                            .into_iter()
                            .map(|(n, v)| (Value::Str(n), v))
                            .collect(),
                    )));
                }
                let f = caller.ok_or_else(|| pyerr("RuntimeError", "no active frame"))?;
                if self.codes[f.code].kind == ScopeKind::Module
                    || self.codes[f.code].kind == ScopeKind::Class
                {
                    return Ok(Value::Obj(f.locals));
                }
                let mut entries = self.keyword_items(Value::Obj(f.locals))?;
                entries.retain(|(n, _)| !n.starts_with('$') && !n.starts_with('\0'));
                Ok(self.obj_value(Object::Dict(
                    entries
                        .into_iter()
                        .map(|(n, v)| (Value::Str(n), v))
                        .collect(),
                )))
            }
            "dir" => {
                let mut names = if let Some(v) = args.first() {
                    self.attribute_items(v)?
                        .into_iter()
                        .map(|(n, _)| n)
                        .collect::<Vec<_>>()
                } else if let Some(f) = caller {
                    self.keyword_items(Value::Obj(f.locals))?
                        .into_iter()
                        .map(|(n, _)| n)
                        .filter(|n| !n.starts_with('$') && !n.starts_with('\0'))
                        .collect()
                } else {
                    vec![]
                };
                names.sort();
                Ok(self.obj_value(Object::List(names.into_iter().map(Value::Str).collect())))
            }
            "compile" => {
                let src = self.str_value(&arg(0)?)?;
                let filename = self.str_value(&arg(1)?)?;
                let mode = self.str_value(&arg(2)?)?;
                let offset = self.codes.len();
                let codes = compile_dynamic(&src, &filename, &mode, offset).map_err(int_error)?;
                self.codes.extend(codes);
                Ok(self.obj_value(Object::Code(offset)))
            }
            "eval" | "exec" => {
                let source = arg(0)?;
                let code = if let Value::Obj(i) = source.clone() {
                    if let Object::Code(c) = self.object(i)? {
                        c
                    } else {
                        return Err(pyerr(
                            "TypeError",
                            "eval/exec source must be a string or code object",
                        ));
                    }
                } else {
                    let src = self.str_value(&source)?;
                    let src = if name == "eval" {
                        src.trim_matches([' ', '\t']).to_string()
                    } else {
                        src
                    };
                    let offset = self.codes.len();
                    let codes = compile_dynamic(
                        &src,
                        "<string>",
                        if name == "eval" { "eval" } else { "exec" },
                        offset,
                    )
                    .map_err(int_error)?;
                    self.codes.extend(codes);
                    offset
                };
                let globals = if let Some(Value::Obj(i)) =
                    args.get(1).filter(|v| !matches!(v, Value::None))
                {
                    *i
                } else {
                    caller.map(|f| f.globals).unwrap_or(self.globals)
                };
                let locals = if let Some(Value::Obj(i)) =
                    args.get(2).filter(|v| !matches!(v, Value::None))
                {
                    *i
                } else if args.len() > 1 && !matches!(args[1], Value::None) {
                    globals
                } else if let Some(f) = caller {
                    if self.codes[f.code].kind == ScopeKind::Function {
                        let m = self
                            .keyword_items(Value::Obj(f.locals))?
                            .into_iter()
                            .collect();
                        self.alloc(Object::Namespace(m, None))
                    } else {
                        f.locals
                    }
                } else {
                    globals
                };
                if self.ns_get(globals, "__builtins__").is_none() {
                    self.ns_set(globals, "__builtins__".into(), Value::Obj(self.builtins))
                }
                let frame = Frame {
                    code,
                    pc: 0,
                    locals,
                    temps: self.alloc(Object::Namespace(HashMap::new(), None)),
                    globals,
                    closure: None,
                    stack: Vec::new(),
                    handlers: Vec::new(),
                    pending: Vec::new(),
                    exception: None,
                    exception_stack: Vec::new(),
                    next_call: None,
                    resume_value: None,
                    injected_exception: None,
                    finally_regions: Vec::new(),
                };
                let v = match self.execute(frame)?.0 {
                    FrameExit::Return(v) | FrameExit::Yield(v) => v,
                };
                Ok(if name == "exec" { Value::None } else { v })
            }
            "__import__" => {
                let n = self.str_value(&arg(0)?)?;
                self.import_module(&n)
            }
            "slice" => {
                let (a, b, c) = if args.len() == 1 {
                    (None, Some(self.as_int(&args[0])?), None)
                } else {
                    let a = if matches!(args[0], Value::None) {
                        None
                    } else {
                        Some(self.as_int(&args[0])?)
                    };
                    let b = if matches!(args[1], Value::None) {
                        None
                    } else {
                        Some(self.as_int(&args[1])?)
                    };
                    let c = if args.len() > 2 && !matches!(args[2], Value::None) {
                        Some(self.as_int(&args[2])?)
                    } else {
                        None
                    };
                    (a, b, c)
                };
                Ok(self.obj_value(Object::Slice(a, b, c)))
            }
            "staticmethod" => Ok(self.obj_value(Object::Static(arg(0)?))),
            "classmethod" => Ok(self.obj_value(Object::ClassMethod(arg(0)?))),
            "property" => Ok(self.obj_value(Object::Property {
                get: arg(0)?,
                set: args.get(1).cloned(),
                del: args.get(2).cloned(),
            })),
            "super" => {
                let class = if let Some(c) = args.first() {
                    c.clone()
                } else if let Some(f) = caller {
                    self.load(f, "__class__")?
                } else {
                    return Err(pyerr("RuntimeError", "super(): no arguments"));
                };
                let receiver = if let Some(v) = args.get(1) {
                    v.clone()
                } else if let Some(f) = caller {
                    let n = self.codes[f.code]
                        .params
                        .positional
                        .first()
                        .cloned()
                        .ok_or_else(|| pyerr("RuntimeError", "super(): no arguments"))?;
                    self.load(f, &n)?
                } else {
                    Value::None
                };
                let attrs = self.alloc(Object::Namespace(HashMap::new(), None));
                self.ns_set(attrs, "$class".into(), class);
                self.ns_set(attrs, "$self".into(), receiver);
                Ok(self.obj_value(Object::Instance {
                    class: Value::Builtin("super".into()),
                    attrs,
                }))
            }
            _ => Err(pyerr(
                "NotImplementedError",
                format!("builtin '{}' is not implemented", name),
            )),
        }
    }
    fn is_subclass(&mut self, a: &Value, b: &Value) -> PyResult<bool> {
        if let Value::Obj(i) = b {
            if let Object::Tuple(xs) = self.object(*i)? {
                for x in xs {
                    if self.is_subclass(a, &x)? {
                        return Ok(true);
                    }
                }
                return Ok(false);
            }
        }
        if Self::same_type(a, b) {
            return Ok(true);
        }
        let an = match a {
            Value::Builtin(n) | Value::Type(n) => n.clone(),
            _ => String::new(),
        };
        let bn = match b {
            Value::Builtin(n) | Value::Type(n) => n.clone(),
            _ => String::new(),
        };
        if bn == "object" || an == "bool" && bn == "int" {
            return Ok(true);
        }
        if !an.is_empty() && !bn.is_empty() {
            let mut k = an.as_str();
            for _ in 0..30 {
                if k == bn {
                    return Ok(true);
                }
                if k == "" {
                    break;
                }
                k = Self::exception_parent(k)
            }
        }
        if let Value::Obj(i) = a {
            if let Object::Class(c) = self.object(*i)? {
                for base in c.bases {
                    if self.is_subclass(&base, b)? {
                        return Ok(true);
                    }
                }
            }
        }
        Ok(false)
    }
    fn sort_values(
        &mut self,
        values: Vec<Value>,
        key: Option<Value>,
        reverse: bool,
    ) -> PyResult<Vec<Value>> {
        let mut xs = Vec::new();
        for v in values {
            let k = if let Some(fun) = &key {
                if matches!(fun, Value::None) {
                    v.clone()
                } else {
                    self.call(fun.clone(), vec![v.clone()], Vec::new(), None)?
                }
            } else {
                v.clone()
            };
            xs.push((k, v))
        }
        for i in 1..xs.len() {
            let mut j = i;
            while j > 0 && self.compare(if reverse { ">" } else { "<" }, &xs[j].0, &xs[j - 1].0)? {
                xs.swap(j, j - 1);
                j -= 1
            }
        }
        Ok(xs.into_iter().map(|(_, v)| v).collect())
    }
}

impl Runtime {
    fn call(
        &mut self,
        fun: Value,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
        caller: Option<&Frame>,
    ) -> PyResult<Value> {
        let root = self.roots.len();
        let mut rv = args.clone();
        rv.push(fun.clone());
        rv.extend(kwargs.iter().map(|(_, v)| v.clone()));
        self.roots.push(rv);
        let result = (|| match fun.clone() {
            Value::Builtin(name) => self.builtin(&name, args, kwargs, caller),
            Value::Type(kind) => {
                let mut text = Vec::new();
                for v in &args {
                    text.push(self.str_value(v)?)
                }
                Ok(self.obj_value(Object::Exception(PyException {
                    kind,
                    message: text.join(", "),
                    value: None,
                    trace: Vec::new(),
                })))
            }
            Value::Obj(i) => match self.object(i)? {
                Object::Bound(f, receiver) => {
                    let mut a = vec![receiver];
                    a.extend(args);
                    self.call(f, a, kwargs, caller)
                }
                Object::Partial {
                    function,
                    args: mut stored,
                    keywords,
                    ..
                } => {
                    let mut incoming = args.into_iter();
                    for value in &mut stored {
                        if matches!(value,Value::Builtin(n)if n=="functools.Placeholder") {
                            *value = incoming.next().ok_or_else(|| {
                                pyerr("TypeError", "missing positional arguments in partial call")
                            })?
                        }
                    }
                    stored.extend(incoming);
                    let mut kw = self.keyword_items(Value::Obj(keywords))?;
                    for (n, v) in kwargs {
                        if let Some((_, old)) = kw.iter_mut().find(|(k, _)| k == &n) {
                            *old = v
                        } else {
                            kw.push((n, v))
                        }
                    }
                    self.call(function, stored, kw, caller)
                }
                Object::Cached(cache) => self.cached_call(i, cache, args, kwargs, caller),
                Object::Function(function) => {
                    let frame = self.bind_function(&function, args, kwargs)?;
                    if self.codes[function.code].is_generator {
                        return Ok(self.obj_value(Object::Generator(frame)));
                    }
                    match self.execute(frame)?.0 {
                        FrameExit::Return(v) | FrameExit::Yield(v) => Ok(v),
                    }
                }
                Object::Class(class) => {
                    let is_meta = self.is_subclass(&fun, &Value::Builtin("type".into()))?;
                    if is_meta {
                        if let Some(new) = self.class_lookup(&fun, "__new__", 0) {
                            let mut a = vec![fun.clone()];
                            a.extend(args.clone());
                            let obj = self.call(new, a, kwargs.clone(), caller)?;
                            if let Some(init) = self.class_lookup(&fun, "__init__", 0) {
                                let bound = self.obj_value(Object::Bound(init, obj.clone()));
                                self.call(bound, args, kwargs, caller)?;
                            }
                            return Ok(obj);
                        }
                        if args.len() >= 3 {
                            return self.construct_class(fun, args, kwargs);
                        }
                    }
                    let obj = if let Some(new) = self.class_lookup(&fun, "__new__", 0) {
                        let mut a = vec![fun.clone()];
                        a.extend(args.clone());
                        self.call(new, a, kwargs.clone(), caller)?
                    } else if self.is_subclass(&fun, &Value::Builtin("tuple".into()))? {
                        self.builtin_instance_new(
                            "tuple",
                            fun.clone(),
                            args.clone(),
                            kwargs.clone(),
                        )?
                    } else {
                        let attrs = self.alloc(Object::Namespace(HashMap::new(), None));
                        self.obj_value(Object::Instance {
                            class: fun.clone(),
                            attrs,
                        })
                    };
                    if let Ok(init) = self.special_method(obj.clone(), "__init__") {
                        let v = self.call(init, args, kwargs, caller)?;
                        if !matches!(v, Value::None) {
                            return Err(pyerr("TypeError", "__init__() should return None"));
                        }
                    } else if (!args.is_empty() || !kwargs.is_empty())
                        && !matches!(&obj,Value::Obj(i)if matches!(self.heap.get(*i).and_then(|o|o.as_ref()),Some(Object::BuiltinInstance{..})))
                    {
                        return Err(pyerr(
                            "TypeError",
                            format!("{}() takes no arguments", class.name),
                        ));
                    }
                    Ok(obj)
                }
                Object::Instance { class, .. } => {
                    if let Some(method) = self.class_lookup(&class, "__call__", 0) {
                        let bound = self.obj_value(Object::Bound(method, fun));
                        self.call(bound, args, kwargs, caller)
                    } else {
                        Err(pyerr("TypeError", "object is not callable"))
                    }
                }
                _ => Err(pyerr(
                    "TypeError",
                    format!("'{}' object is not callable", self.typename(&fun)),
                )),
            },
            _ => Err(pyerr(
                "TypeError",
                format!("'{}' object is not callable", self.typename(&fun)),
            )),
        })();
        self.roots.truncate(root);
        result
    }
    fn construct_class(
        &mut self,
        metaclass: Value,
        args: Vec<Value>,
        _kw: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        if args.len() < 3 {
            return Err(pyerr("TypeError", "type() takes 1 or 3 arguments"));
        }
        let name = self.str_value(&args[0])?;
        let mut bases = self.to_vec(args[1].clone())?;
        if bases.is_empty() {
            bases.push(Value::Builtin("object".into()))
        }
        for i in 0..bases.len() {
            for j in 0..i {
                if Self::same_type(&bases[i], &bases[j]) {
                    return Err(pyerr("TypeError", "duplicate base class"));
                }
            }
        }
        let ns = match args[2] {
            Value::Obj(i) => i,
            _ => return Err(pyerr("TypeError", "type namespace must be a dictionary")),
        };
        let mut items = self.dict_items(Value::Obj(ns))?;
        if items
            .iter()
            .any(|(key, _)| matches!(key, Value::Str(name) if name == "__eq__"))
            && !items
                .iter()
                .any(|(key, _)| matches!(key, Value::Str(name) if name == "__hash__"))
        {
            items.push((Value::Str("__hash__".into()), Value::None));
        }
        let classcell = items.iter().find_map(|(k, v)| {
            if matches!(k,Value::Str(s)if s=="__classcell__") {
                Some(v.clone())
            } else {
                None
            }
        });
        let dictcell = items.iter().find_map(|(k, v)| {
            if matches!(k,Value::Str(s)if s=="__classdictcell__") {
                Some(v.clone())
            } else {
                None
            }
        });
        items.retain(
            |(k, _)| !matches!(k,Value::Str(s)if s=="__classcell__"||s=="__classdictcell__"),
        );
        let ns = self.alloc(Object::Dict(items));
        let out = self.obj_value(Object::Class(Class {
            name,
            bases,
            attrs: ns,
            metaclass,
        }));
        for (cell, value) in [(classcell, out.clone()), (dictcell, Value::Obj(ns))] {
            if let Some(v) = cell {
                if let Value::Obj(i) = v {
                    if matches!(self.object(i)?, Object::Cell(_)) {
                        self.heap[i] = Some(Object::Cell(Some(value)));
                    } else {
                        return Err(pyerr("TypeError", "__classcell__ must be a cell"));
                    }
                } else {
                    return Err(pyerr("TypeError", "__classcell__ must be a cell"));
                }
            }
        }
        if self.class_mro(&out, 0).is_none() {
            return Err(pyerr(
                "TypeError",
                "Cannot create a consistent method resolution order (MRO)",
            ));
        }
        if let Ok(items) = self.attribute_items(&Value::Obj(ns)) {
            for (n, v) in items {
                if let Ok(setname) = self.getattr(v, "__set_name__") {
                    self.call(setname, vec![out.clone(), Value::Str(n)], Vec::new(), None)?;
                }
            }
        }
        Ok(out)
    }
    fn make_class(
        &mut self,
        f: &Frame,
        name: String,
        code: usize,
        bases: Vec<Value>,
        kw: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        let mut metaclass = kw
            .iter()
            .find(|(k, _)| k == "metaclass")
            .map(|(_, v)| v.clone())
            .unwrap_or(Value::Builtin("type".into()));
        if matches!(&metaclass,Value::Builtin(n)if n=="type") {
            if let Some(Value::Obj(i)) = bases.first() {
                if let Object::Class(c) = self.object(*i)? {
                    metaclass = c.metaclass
                }
            }
        }
        let keywords: Vec<_> = kw.into_iter().filter(|(k, _)| k != "metaclass").collect();
        let basesvalue = self.obj_value(Object::Tuple(bases.clone()));
        let namespace = if let Ok(prepare) = self.getattr(metaclass.clone(), "__prepare__") {
            let v = self.call(
                prepare,
                vec![Value::Str(name.clone()), basesvalue.clone()],
                keywords.clone(),
                Some(f),
            )?;
            match v {
                Value::Obj(i) => i,
                _ => return Err(pyerr("TypeError", "__prepare__ must return a mapping")),
            }
        } else {
            self.alloc(Object::Dict(Vec::new()))
        };
        self.mapping_set(
            namespace,
            "__module__".into(),
            self.ns_get(f.globals, "__name__")
                .unwrap_or(Value::Str("__main__".into())),
        )?;
        self.mapping_set(namespace, "__qualname__".into(), Value::Str(name.clone()))?;
        let parent = if self.codes[f.code].kind == ScopeKind::Class {
            f.closure
        } else {
            Some(f.locals)
        };
        let env = self.alloc(Object::Namespace(HashMap::new(), parent));
        self.scope_parents.insert(namespace, env);
        self.scope_bindings
            .insert(namespace, self.codes[code].locals.clone());
        let frame = Frame {
            code,
            pc: 0,
            locals: namespace,
            temps: self.alloc(Object::Namespace(HashMap::new(), None)),
            globals: f.globals,
            closure: Some(env),
            stack: Vec::new(),
            handlers: Vec::new(),
            pending: Vec::new(),
            exception: None,
            exception_stack: Vec::new(),
            next_call: None,
            resume_value: None,
            injected_exception: None,
            finally_regions: Vec::new(),
        };
        self.execute(frame)?;
        let methods = self.codes[code]
            .ops
            .iter()
            .filter_map(|ins| {
                if let Op::MakeFunction { code, .. } = &ins.op {
                    Some(*code)
                } else {
                    None
                }
            })
            .collect::<Vec<_>>();
        let has_method = methods.iter().any(|i| {
            self.codes[*i].kind == ScopeKind::Function && !self.codes[*i].name.starts_with('<')
        });
        if has_method {
            let cell = self.obj_value(Object::Cell(Some(Value::Obj(namespace))));
            self.mapping_set(namespace, "__classdictcell__".into(), cell)?;
        }
        let needs_cell = methods.iter().any(|i| self.code_needs_class_cell(*i, 0));
        let classcell = if needs_cell {
            let cell = self.alloc(Object::Cell(None));
            self.mapping_set(namespace, "__classcell__".into(), Value::Obj(cell))?;
            Some(cell)
        } else {
            None
        };
        let cls = self.call(
            metaclass,
            vec![Value::Str(name), basesvalue, Value::Obj(namespace)],
            keywords,
            Some(f),
        )?;
        if let Some(cell) = classcell {
            if !matches!(self.object(cell)?, Object::Cell(Some(_))) {
                return Err(pyerr(
                    "RuntimeError",
                    "__class__ not set; was __classcell__ propagated to type.__new__?",
                ));
            }
        }
        self.ns_set(env, "__class__".into(), cls.clone());
        Ok(cls)
    }
    fn as_exception(&mut self, v: Value) -> PyResult<PyException> {
        match v {
            Value::Type(kind) => Ok(pyerr(&kind, "")),
            Value::Obj(i) => match self.object(i)? {
                Object::Exception(e) => Ok(e),
                Object::Instance { class, .. } => {
                    let kind = self.typename(&Value::Obj(i));
                    let message = self.str_value(&Value::Obj(i))?;
                    let _ = class;
                    Ok(PyException {
                        kind,
                        message,
                        value: Some(Value::Obj(i)),
                        trace: Vec::new(),
                    })
                }
                _ => Err(pyerr(
                    "TypeError",
                    "exceptions must derive from BaseException",
                )),
            },
            _ => Err(pyerr(
                "TypeError",
                "exceptions must derive from BaseException",
            )),
        }
    }
    fn exception_parent(kind: &str) -> &str {
        match kind {
            "BaseException" => "",
            "Exception" | "GeneratorExit" | "SystemExit" => "BaseException",
            "ArithmeticError" | "AssertionError" | "AttributeError" | "EOFError"
            | "ImportError" | "LookupError" | "NameError" | "OSError" | "RuntimeError"
            | "StopIteration" | "SyntaxError" | "TypeError" | "ValueError" => "Exception",
            "ZeroDivisionError" | "OverflowError" => "ArithmeticError",
            "IndexError" | "KeyError" => "LookupError",
            "ModuleNotFoundError" => "ImportError",
            "UnboundLocalError" => "NameError",
            "RecursionError" | "NotImplementedError" => "RuntimeError",
            _ => "Exception",
        }
    }
    fn exception_match(&mut self, a: &Value, b: &Value) -> PyResult<bool> {
        if let Value::Obj(i) = b {
            if let Object::Tuple(v) = self.object(*i)? {
                for t in v {
                    if self.exception_match(a, &t)? {
                        return Ok(true);
                    }
                }
                return Ok(false);
            }
        }
        let kind = match a {
            Value::Obj(i) => match self.object(*i)? {
                Object::Exception(e) => e.kind,
                _ => self.typename(a),
            },
            Value::Type(n) => n.clone(),
            _ => self.typename(a),
        };
        let expected =
            match b {
                Value::Type(n) => n.clone(),
                Value::Obj(i) => match self.object(*i)? {
                    Object::Class(c) => c.name,
                    _ => return Err(pyerr(
                        "TypeError",
                        "catching classes that do not inherit from BaseException is not allowed",
                    )),
                },
                _ => {
                    return Err(pyerr(
                        "TypeError",
                        "catching classes that do not inherit from BaseException is not allowed",
                    ))
                }
            };
        let mut k = kind.as_str();
        for _ in 0..30 {
            if k == expected {
                return Ok(true);
            }
            if k.is_empty() {
                break;
            }
            k = Self::exception_parent(k)
        }
        Ok(false)
    }
    fn str_value(&mut self, v: &Value) -> PyResult<String> {
        match v {
            Value::Str(s) => Ok(s.clone()),
            Value::None => Ok("None".into()),
            Value::Bool(b) => Ok(if *b { "True" } else { "False" }.into()),
            Value::Int(n) => Ok(n.to_string()),
            Value::Float(n) => {
                if n.is_nan() {
                    return Ok("nan".into());
                }
                if n.is_infinite() {
                    return Ok(if n.is_sign_negative() { "-inf" } else { "inf" }.into());
                }
                let s = format!("{:?}", n);
                if let Some((mantissa, exponent)) = s.split_once('e') {
                    let exponent = exponent.parse::<i32>().unwrap_or(0);
                    Ok(format!("{}e{:+03}", mantissa, exponent))
                } else {
                    Ok(s)
                }
            }
            Value::Obj(i) => match self.object(*i)? {
                Object::Exception(e) => Ok(e.message),
                Object::Instance { .. } | Object::BuiltinInstance { .. } => {
                    if let Ok(fun) = self.special_method(v.clone(), "__str__") {
                        let r = self.call(fun, Vec::new(), Vec::new(), None)?;
                        if let Value::Str(s) = r {
                            return Ok(s);
                        }
                        return Err(pyerr("TypeError", "__str__ returned non-string"));
                    }
                    self.repr(v)
                }
                _ => self.repr(v),
            },
            _ => self.repr(v),
        }
    }
    fn repr(&mut self, v: &Value) -> PyResult<String> {
        self.repr_inner(v, &mut Vec::new())
    }
    fn repr_inner(&mut self, v: &Value, seen: &mut Vec<usize>) -> PyResult<String> {
        match v {
            Value::Str(s) => Ok(text_repr_str(s)),
            Value::Bytes(xs) => Ok(text_repr_bytes(xs)),
            Value::Obj(i) => {
                if seen.contains(i) {
                    return Ok("[...]".into());
                }
                seen.push(*i);
                let s = match self.object(*i)? {
                    Object::List(xs) | Object::Tuple(xs) | Object::Set(xs) => {
                        let mut ss = Vec::new();
                        for x in &xs {
                            ss.push(self.repr_inner(x, seen)?)
                        }
                        match self.object(*i)? {
                            Object::Tuple(_) => format!(
                                "({}{})",
                                ss.join(", "),
                                if xs.len() == 1 { "," } else { "" }
                            ),
                            Object::Set(_) if xs.is_empty() => "set()".into(),
                            Object::Set(_) => format!("{{{}}}", ss.join(", ")),
                            _ => format!("[{}]", ss.join(", ")),
                        }
                    }
                    Object::Dict(xs) => {
                        let mut ss = Vec::new();
                        for (k, v) in xs {
                            ss.push(format!(
                                "{}: {}",
                                self.repr_inner(&k, seen)?,
                                self.repr_inner(&v, seen)?
                            ))
                        }
                        format!("{{{}}}", ss.join(", "))
                    }
                    Object::Namespace(m, _) => {
                        let mut ss = Vec::new();
                        let mut entries: Vec<_> = m.into_iter().collect();
                        entries.sort_by(|a, b| a.0.cmp(&b.0));
                        for (k, v) in entries {
                            ss.push(format!(
                                "{}: {}",
                                self.repr(&Value::Str(k))?,
                                self.repr_inner(&v, seen)?
                            ))
                        }
                        format!("{{{}}}", ss.join(", "))
                    }
                    Object::Function(fun) => format!("<function {}>", fun.qualname),
                    Object::Class(c) => format!("<class '{}'>", c.name),
                    Object::Module { name, .. } => format!("<module '{}'>", name),
                    Object::Exception(e) => {
                        format!("{}({})", e.kind, self.repr(&Value::Str(e.message))?)
                    }
                    Object::BuiltinInstance { payload, .. } => {
                        if let Ok(fun) = self.special_method(v.clone(), "__repr__") {
                            let result = self.call(fun, Vec::new(), Vec::new(), None)?;
                            self.str_value(&result)?
                        } else {
                            self.repr_inner(&payload, seen)?
                        }
                    }
                    Object::Instance { .. } => {
                        if let Ok(fun) = self.special_method(v.clone(), "__repr__") {
                            let r = self.call(fun, Vec::new(), Vec::new(), None)?;
                            self.str_value(&r)?
                        } else {
                            format!("<{} object>", self.typename(v))
                        }
                    }
                    Object::Generator(_) => "<generator object>".into(),
                    Object::Iterator(_) => "<iterator object>".into(),
                    Object::Bound(..) => "<bound method>".into(),
                    Object::Slice(a, b, c) => format!("slice({:?}, {:?}, {:?})", a, b, c),
                    Object::Partial { function, args, .. } => {
                        let mut p = vec![self.repr_inner(&function, seen)?];
                        for v in args {
                            p.push(self.repr_inner(&v, seen)?)
                        }
                        format!("functools.partial({})", p.join(", "))
                    }
                    Object::Cached(_) => "<functools._lru_cache_wrapper>".into(),
                    Object::Record { name, fields } => {
                        let mut parts = Vec::new();
                        for (n, v) in fields {
                            parts.push(format!("{}={}", n, self.repr_inner(&v, seen)?));
                        }
                        format!("{}({})", name, parts.join(", "))
                    }
                    Object::Static(_) => "<staticmethod>".into(),
                    Object::ClassMethod(_) => "<classmethod>".into(),
                    Object::Property { .. } => "<property>".into(),
                    Object::Cell(_) => "<cell>".into(),
                    Object::Code(_) => "<code object>".into(),
                    Object::Range(a, b, c) => format!("range({}, {}, {})", a, b, c),
                };
                seen.pop();
                Ok(s)
            }
            Value::Builtin(n) => {
                if n == "Ellipsis" {
                    Ok("Ellipsis".into())
                } else if n == "functools.Placeholder" {
                    Ok("Placeholder".into())
                } else {
                    Ok(format!("<built-in function {}>", n))
                }
            }
            Value::Type(n) => Ok(format!("<class '{}'>", n)),
            _ => self.str_value(v),
        }
    }
    fn format_value(&mut self, v: Value, spec: &str) -> PyResult<String> {
        if spec.is_empty() {
            return self.str_value(&v);
        }
        let mut s = spec;
        let mut precision = None;
        if let Some(dot) = s.find('.') {
            let tail = &s[dot + 1..];
            let digits: String = tail.chars().take_while(|c| c.is_ascii_digit()).collect();
            precision = digits.parse::<usize>().ok();
        }
        let ty = s.chars().last().unwrap_or(' ');
        let mut text = match ty {
            'f' | 'F' => format!("{:.*}", precision.unwrap_or(6), self.as_float(&v)?),
            'e' | 'E' => format!("{:.*e}", precision.unwrap_or(6), self.as_float(&v)?),
            'b' | 'o' | 'x' | 'X' => {
                let n = self
                    .as_int(&v)?
                    .to_i128()
                    .ok_or_else(|| pyerr("OverflowError", "format value too large"))?;
                match ty {
                    'b' => format!("{:b}", n),
                    'o' => format!("{:o}", n),
                    'X' => format!("{:X}", n),
                    _ => format!("{:x}", n),
                }
            }
            'd' => self.as_int(&v)?.to_string(),
            _ => self.str_value(&v)?,
        };
        let widthdigits: String = s
            .chars()
            .skip_while(|c| !c.is_ascii_digit())
            .take_while(|c| c.is_ascii_digit())
            .collect();
        let width = widthdigits.parse::<usize>().unwrap_or(0);
        if width > text.chars().count() {
            let count = width - text.chars().count();
            let fill = if s.starts_with('0') {
                '0'
            } else if s.chars().nth(1).map(|c| "<>^".contains(c)).unwrap_or(false) {
                s.chars().next().unwrap()
            } else {
                ' '
            };
            let pad = fill.to_string().repeat(count);
            text = if s.contains('<') {
                format!("{}{}", text, pad)
            } else if s.contains('^') {
                let left = count / 2;
                format!(
                    "{}{}{}",
                    fill.to_string().repeat(left),
                    text,
                    fill.to_string().repeat(count - left)
                )
            } else {
                format!("{}{}", pad, text)
            }
        }
        if s.starts_with('+') && !text.starts_with('-') {
            text.insert(0, '+')
        }
        Ok(text)
    }
    fn percent_format(&mut self, fmt: &str, v: Value) -> PyResult<String> {
        let args = if let Value::Obj(i) = v.clone() {
            match self.object(i)? {
                Object::Tuple(xs) => xs,
                _ => vec![v],
            }
        } else {
            vec![v]
        };
        let mut a = 0;
        let mut out = String::new();
        let mut it = fmt.chars().peekable();
        while let Some(c) = it.next() {
            if c != '%' {
                out.push(c);
                continue;
            }
            if it.peek() == Some(&'%') {
                it.next();
                out.push('%');
                continue;
            }
            let mut spec = String::new();
            let kind = loop {
                let c = it
                    .next()
                    .ok_or_else(|| pyerr("ValueError", "incomplete format"))?;
                if "srdifegoxXc".contains(c) {
                    break c;
                }
                spec.push(c)
            };
            let v = args
                .get(a)
                .ok_or_else(|| pyerr("TypeError", "not enough arguments for format string"))?
                .clone();
            a += 1;
            out.push_str(&match kind {
                's' => self.str_value(&v)?,
                'r' => self.repr(&v)?,
                'd' | 'i' => self.as_int(&v)?.to_string(),
                'c' => char::from_u32(self.as_int(&v)?.to_usize().unwrap_or(0) as u32)
                    .ok_or_else(|| pyerr("ValueError", "invalid character"))?
                    .to_string(),
                _ => {
                    spec.push(kind);
                    self.format_value(v, &spec)?
                }
            })
        }
        Ok(out)
    }
}

impl Runtime {
    fn typename(&self, v: &Value) -> String {
        match v {
            Value::None => "NoneType".into(),
            Value::Bool(_) => "bool".into(),
            Value::Int(_) => "int".into(),
            Value::Float(_) => "float".into(),
            Value::Str(_) => "str".into(),
            Value::Bytes(_) => "bytes".into(),
            Value::Builtin(n) => {
                if n == "Ellipsis" {
                    return "ellipsis".into();
                }
                if n == "functools.Placeholder" {
                    return "_PlaceholderType".into();
                }
                if [
                    "int", "str", "list", "tuple", "dict", "set", "float", "bool", "type",
                    "object", "bytes",
                ]
                .contains(&n.as_str())
                {
                    "type".into()
                } else {
                    "builtin_function_or_method".into()
                }
            }
            Value::Type(_) => "type".into(),
            Value::Obj(i) => match self.heap.get(*i).and_then(|o| o.as_ref()) {
                Some(Object::List(_)) => "list".into(),
                Some(Object::Tuple(_)) => "tuple".into(),
                Some(Object::Dict(_)) | Some(Object::Namespace(..)) => "dict".into(),
                Some(Object::Set(_)) => "set".into(),
                Some(Object::Function(_)) => "function".into(),
                Some(Object::Class(_)) => "type".into(),
                Some(Object::Instance {
                    class: Value::Obj(c),
                    ..
                }) => match self.heap.get(*c).and_then(|o| o.as_ref()) {
                    Some(Object::Class(c)) => c.name.clone(),
                    _ => "object".into(),
                },
                Some(Object::BuiltinInstance {
                    class: Value::Obj(c),
                    ..
                }) => match self.heap.get(*c).and_then(|o| o.as_ref()) {
                    Some(Object::Class(c)) => c.name.clone(),
                    _ => "object".into(),
                },
                Some(Object::Exception(e)) => e.kind.clone(),
                Some(Object::Generator(_)) => "generator".into(),
                Some(Object::Module { .. }) => "module".into(),
                Some(Object::Iterator(_)) => "iterator".into(),
                Some(Object::Slice(..)) => "slice".into(),
                Some(Object::Cell(_)) => "cell".into(),
                _ => "object".into(),
            },
        }
    }
    fn as_int(&mut self, v: &Value) -> PyResult<Int> {
        match v {
            Value::Int(n) => Ok(n.clone()),
            Value::Bool(b) => Ok(Int::from_i128(if *b { 1 } else { 0 })),
            _ => {
                if let Ok(m) = self.special_method(v.clone(), "__index__") {
                    let x = self.call(m, Vec::new(), Vec::new(), None)?;
                    if let Value::Int(i) = x {
                        return Ok(i);
                    }
                }
                Err(pyerr(
                    "TypeError",
                    format!(
                        "'{}' object cannot be interpreted as an integer",
                        self.typename(v)
                    ),
                ))
            }
        }
    }
    fn as_float(&mut self, v: &Value) -> PyResult<f64> {
        let n = match v {
            Value::Float(f) => return Ok(*f),
            Value::Int(n) => n.to_f64(),
            Value::Bool(b) => {
                if *b {
                    1.0
                } else {
                    0.0
                }
            }
            _ => return Err(pyerr("TypeError", "a real number is required")),
        };
        if n.is_infinite() {
            Err(pyerr("OverflowError", "int too large to convert to float"))
        } else {
            Ok(n)
        }
    }
    fn truth(&mut self, v: &Value) -> PyResult<bool> {
        if matches!(v,Value::Builtin(n)if n=="NotImplemented") {
            return Err(pyerr(
                "TypeError",
                "NotImplemented should not be used in a boolean context",
            ));
        }
        if let Value::Obj(i) = v {
            match self.heap.get(*i).and_then(|o| o.as_ref()) {
                Some(Object::List(xs) | Object::Tuple(xs) | Object::Set(xs)) => {
                    return Ok(!xs.is_empty())
                }
                Some(Object::Dict(xs)) => return Ok(!xs.is_empty()),
                Some(Object::Namespace(xs, _)) => return Ok(!xs.is_empty()),
                _ => {}
            }
        }
        Ok(match v {
            Value::None => false,
            Value::Bool(b) => *b,
            Value::Int(n) => !n.is_zero(),
            Value::Float(n) => *n != 0.0,
            Value::Str(s) => !s.is_empty(),
            Value::Bytes(b) => !b.is_empty(),
            Value::Obj(i) => match self.object(*i)? {
                Object::List(v) | Object::Tuple(v) | Object::Set(v) => !v.is_empty(),
                Object::Dict(v) => !v.is_empty(),
                Object::Namespace(v, _) => !v.is_empty(),
                Object::Instance { .. } | Object::BuiltinInstance { .. } => {
                    if let Ok(fun) = self.special_method(v.clone(), "__bool__") {
                        let r = self.call(fun, Vec::new(), Vec::new(), None)?;
                        match r {
                            Value::Bool(b) => b,
                            _ => return Err(pyerr("TypeError", "__bool__ should return bool")),
                        }
                    } else if let Ok(fun) = self.special_method(v.clone(), "__len__") {
                        let r = self.call(fun, Vec::new(), Vec::new(), None)?;
                        !self.as_int(&r)?.is_zero()
                    } else {
                        true
                    }
                }
                _ => true,
            },
            _ => true,
        })
    }
    fn contains_vec(&mut self, vs: &[Value], v: &Value) -> PyResult<bool> {
        for x in vs {
            if self.equal(x, v)? {
                return Ok(true);
            }
        }
        Ok(false)
    }
    fn equal_default(&mut self, a: &Value, b: &Value) -> PyResult<bool> {
        let ap = if let Value::Obj(i) = a {
            match self.heap.get(*i).and_then(|o| o.as_ref()) {
                Some(Object::BuiltinInstance { payload, .. }) => Some(payload.clone()),
                _ => None,
            }
        } else {
            None
        };
        let bp = if let Value::Obj(i) = b {
            match self.heap.get(*i).and_then(|o| o.as_ref()) {
                Some(Object::BuiltinInstance { payload, .. }) => Some(payload.clone()),
                _ => None,
            }
        } else {
            None
        };
        if ap.is_some() || bp.is_some() {
            return self.equal_default(ap.as_ref().unwrap_or(a), bp.as_ref().unwrap_or(b));
        }
        if let (Value::Obj(x), Value::Obj(y)) = (a, b) {
            if x == y {
                return Ok(true);
            }
        }
        match (a, b) {
            (Value::None, Value::None) => Ok(true),
            (Value::Bool(a), Value::Bool(b)) => Ok(a == b),
            (Value::Int(a), Value::Int(b)) => Ok(a == b),
            (Value::Bool(a), Value::Int(b)) | (Value::Int(b), Value::Bool(a)) => {
                Ok(&Int::from_i128(if *a { 1 } else { 0 }) == b)
            }
            (Value::Float(a), Value::Float(b)) => Ok(a == b),
            (Value::Int(a), Value::Float(b)) | (Value::Float(b), Value::Int(a)) => {
                if !b.is_finite() || b.fract() != 0.0 {
                    return Ok(false);
                }
                Ok(a.cmp_f64(*b) == Some(std::cmp::Ordering::Equal))
            }
            (Value::Bool(a), Value::Float(b)) | (Value::Float(b), Value::Bool(a)) => {
                Ok((if *a { 1.0 } else { 0.0 }) == *b)
            }
            (Value::Str(a), Value::Str(b)) => Ok(a == b),
            (Value::Bytes(a), Value::Bytes(b)) => Ok(a == b),
            (Value::Builtin(a), Value::Builtin(b)) | (Value::Type(a), Value::Type(b)) => Ok(a == b),
            (Value::Obj(x), Value::Obj(y)) => match (self.object(*x)?, self.object(*y)?) {
                (Object::List(a), Object::List(b)) | (Object::Tuple(a), Object::Tuple(b)) => {
                    if a.len() != b.len() {
                        return Ok(false);
                    }
                    for (x, y) in a.iter().zip(&b) {
                        if !self.equal(x, y)? {
                            return Ok(false);
                        }
                    }
                    Ok(true)
                }
                (Object::Dict(a), Object::Dict(b)) => {
                    if a.len() != b.len() {
                        return Ok(false);
                    }
                    for (k, v) in a {
                        let mut matched = false;
                        for (k2, v2) in &b {
                            if self.equal(&k, k2)? {
                                if !self.equal(&v, v2)? {
                                    return Ok(false);
                                }
                                matched = true;
                                break;
                            }
                        }
                        if !matched {
                            return Ok(false);
                        }
                    }
                    Ok(true)
                }
                (Object::Set(a), Object::Set(b)) => {
                    if a.len() != b.len() {
                        return Ok(false);
                    }
                    for v in a {
                        if !self.contains_vec(&b, &v)? {
                            return Ok(false);
                        }
                    }
                    Ok(true)
                }
                _ => Ok(false),
            },
            _ => Ok(false),
        }
    }
    fn ordering(&mut self, a: &Value, b: &Value) -> PyResult<std::cmp::Ordering> {
        use std::cmp::Ordering;
        match (a, b) {
            (Value::Int(a), Value::Int(b)) => Ok(a.cmp(b)),
            (Value::Int(a), Value::Float(b)) => Ok(a.cmp_f64(*b).unwrap_or(Ordering::Equal)),
            (Value::Float(a), Value::Int(b)) => Ok(b
                .cmp_f64(*a)
                .map(|x| x.reverse())
                .unwrap_or(Ordering::Equal)),
            (Value::Str(a), Value::Str(b)) => Ok(a.cmp(b)),
            (Value::Bytes(a), Value::Bytes(b)) => Ok(a.cmp(b)),
            (
                Value::Int(_) | Value::Float(_) | Value::Bool(_),
                Value::Int(_) | Value::Float(_) | Value::Bool(_),
            ) => {
                let x = self.as_float(a)?;
                let y = self.as_float(b)?;
                Ok(x.partial_cmp(&y).unwrap_or(Ordering::Equal))
            }
            (Value::Obj(i), Value::Obj(j)) => match (self.object(*i)?, self.object(*j)?) {
                (Object::List(a), Object::List(b)) | (Object::Tuple(a), Object::Tuple(b)) => {
                    for (x, y) in a.iter().zip(&b) {
                        if !self.equal(x, y)? {
                            return self.ordering(x, y);
                        }
                    }
                    Ok(a.len().cmp(&b.len()))
                }
                _ => Err(pyerr("TypeError", "objects are not orderable")),
            },
            _ => Err(pyerr(
                "TypeError",
                format!(
                    "'<' not supported between instances of '{}' and '{}'",
                    self.typename(a),
                    self.typename(b)
                ),
            )),
        }
    }
    fn compare_default(&mut self, op: &str, a: &Value, b: &Value) -> PyResult<bool> {
        if ["<", "<=", ">", ">="].contains(&op) {
            let ap = self.native_payload(a);
            let bp = self.native_payload(b);
            if ap.is_some() || bp.is_some() {
                return self.compare_default(
                    op,
                    ap.as_ref().unwrap_or(a),
                    bp.as_ref().unwrap_or(b),
                );
            }
        }
        use std::cmp::Ordering::*;
        match op {
            "==" => self.equal_default(a, b),
            "!=" => Ok(!self.equal_default(a, b)?),
            "is" | "is not" => {
                let eq = match (a, b) {
                    (Value::Obj(x), Value::Obj(y)) => x == y,
                    (Value::None, Value::None) => true,
                    (Value::Bool(x), Value::Bool(y)) => x == y,
                    (Value::Builtin(x), Value::Builtin(y)) | (Value::Type(x), Value::Type(y)) => {
                        x == y
                    }
                    _ => false,
                };
                Ok(if op == "is" { eq } else { !eq })
            }
            "in" | "not in" => {
                let yes = match (a, b) {
                    (Value::Str(x), Value::Str(y)) => y.contains(x),
                    _ => {
                        if let Ok(fun) = self.special_method(b.clone(), "__contains__") {
                            let v = self.call(fun, vec![a.clone()], Vec::new(), None)?;
                            self.truth(&v)?
                        } else {
                            let xs = self.to_vec(b.clone())?;
                            self.contains_vec(&xs, a)?
                        }
                    }
                };
                Ok(if op == "in" { yes } else { !yes })
            }
            "exception_match" => self.exception_match(a, b),
            _ => {
                if matches!(a,Value::Float(x)if x.is_nan())
                    || matches!(b,Value::Float(x)if x.is_nan())
                {
                    return Ok(false);
                }
                let method = match op {
                    "<" => "__lt__",
                    "<=" => "__le__",
                    ">" => "__gt__",
                    ">=" => "__ge__",
                    _ => return Err(pyerr("RuntimeError", format!("unknown comparison {}", op))),
                };
                let c = self.ordering(a, b)?;
                Ok(match op {
                    "<" => c == Less,
                    "<=" => c != Greater,
                    ">" => c == Greater,
                    ">=" => c != Less,
                    _ => false,
                })
            }
        }
    }
    fn unary(&mut self, op: &str, a: Value) -> PyResult<Value> {
        if op == "not" {
            return Ok(Value::Bool(!self.truth(&a)?));
        }
        match &a {
            Value::Int(n) => Ok(Value::Int(match op {
                "+" => n.clone(),
                "-" => n.neg(),
                "~" => n.invert(),
                _ => return Err(pyerr("TypeError", "unsupported unary operator")),
            })),
            Value::Bool(_) => {
                let n = self.as_int(&a)?;
                self.unary(op, Value::Int(n))
            }
            Value::Float(x) => match op {
                "+" => Ok(a),
                "-" => Ok(Value::Float(-x)),
                _ => Err(pyerr("TypeError", "bad operand type")),
            },
            _ => {
                let name = match op {
                    "+" => "__pos__",
                    "-" => "__neg__",
                    "~" => "__invert__",
                    _ => "",
                };
                let fun = self.special_method(a, name)?;
                self.call(fun, Vec::new(), Vec::new(), None)
            }
        }
    }
    fn binary(&mut self, op: &str, a: Value, b: Value) -> PyResult<Value> {
        if let Some(base) = op.strip_prefix('i') {
            if !base.is_empty() {
                return self.binary(&format!("{}=", base), a, b);
            }
        }
        if let Some(base) = op.strip_suffix('=') {
            let method = match base {
                "+" => "__iadd__",
                "-" => "__isub__",
                "*" => "__imul__",
                "/" => "__itruediv__",
                "//" => "__ifloordiv__",
                "%" => "__imod__",
                "**" => "__ipow__",
                "<<" => "__ilshift__",
                ">>" => "__irshift__",
                "&" => "__iand__",
                "|" => "__ior__",
                "^" => "__ixor__",
                "@" => "__imatmul__",
                _ => "",
            };
            if let Some(class) = self.object_class(&a) {
                if let Some(fun) = self.class_lookup(&class, method, 0) {
                    let fun = self.bind_descriptor(fun, Some(a.clone()), class)?;
                    let result = self.call(fun, vec![b.clone()], Vec::new(), None)?;
                    if !matches!(&result,Value::Builtin(n)if n=="NotImplemented") {
                        return Ok(result);
                    }
                }
            }
        }
        if let Some(payload) = self.native_payload(&b) {
            if matches!(&a,Value::Obj(i)if matches!(self.heap.get(*i).and_then(|o|o.as_ref()),Some(Object::Tuple(_))))
                && ["+", "+="].contains(&op)
            {
                if let Some(class) = self.object_class(&b) {
                    if let Some(fun) = self.class_lookup(&class, "__radd__", 0) {
                        let fun = self.bind_descriptor(fun, Some(b.clone()), class)?;
                        let value = self.call(fun, vec![a.clone()], Vec::new(), None)?;
                        if !matches!(&value,Value::Builtin(n)if n=="NotImplemented") {
                            return Ok(value);
                        }
                    }
                }
                return self.binary(op, a, payload);
            }
        }
        let mut reflected_first = false;
        let stem = match op {
            "+" => "add",
            "-" => "sub",
            "*" => "mul",
            "/" => "truediv",
            "//" => "floordiv",
            "%" => "mod",
            "**" => "pow",
            "&" => "and",
            "|" => "or",
            "^" => "xor",
            "<<" => "lshift",
            ">>" => "rshift",
            "@" => "matmul",
            _ => "",
        };
        if !stem.is_empty() {
            if let Some(bc) = self.object_class(&b) {
                let ac = self
                    .object_class(&a)
                    .unwrap_or_else(|| Value::Builtin(self.typename(&a)));
                if !Self::same_type(&ac, &bc) && self.is_subclass(&bc, &ac)? {
                    if let Some(method) = self.class_lookup(&bc, &format!("__r{}__", stem), 0) {
                        reflected_first = true;
                        let fun = self.bind_descriptor(method, Some(b.clone()), bc)?;
                        let value = self.call(fun, vec![a.clone()], Vec::new(), None)?;
                        if !matches!(&value,Value::Builtin(n)if n=="NotImplemented") {
                            return Ok(value);
                        }
                    }
                }
            }
        }
        if op.ends_with('=') && op != "+=" && op != "*=" {
            return self.binary(&op[..op.len() - 1], a, b);
        }
        if op == "+=" {
            if let Value::Obj(i) = &a {
                if matches!(
                    self.heap.get(*i).and_then(|o| o.as_ref()),
                    Some(Object::List(_))
                ) {
                    let more = self.to_vec(b)?;
                    if let Some(Object::List(xs)) = self.heap[*i].as_mut() {
                        xs.extend(more);
                    }
                    return Ok(a);
                }
            }
        }
        if op == "dict_merge" || op == "kwargs_merge" {
            let out = self.obj_value(Object::Dict(Vec::new()));
            for (k, v) in self.dict_items(a)? {
                self.setitem(out.clone(), k, v)?
            }
            for (k, v) in self.dict_items(b)? {
                if op == "kwargs_merge" && self.getitem(out.clone(), k.clone()).is_ok() {
                    return Err(pyerr("TypeError", "multiple values for keyword argument"));
                }
                self.setitem(out.clone(), k, v)?
            }
            return Ok(out);
        }
        let integers = matches!(a, Value::Int(_) | Value::Bool(_))
            && matches!(b, Value::Int(_) | Value::Bool(_));
        if integers {
            let x = self.as_int(&a)?;
            let y = self.as_int(&b)?;
            let n = match op {
                "+" | "+=" => x.add(&y),
                "-" | "-=" => x.sub(&y),
                "*" | "*=" => x.mul(&y),
                "//" => x.divmod(&y).map_err(int_error)?.0,
                "%" => x.divmod(&y).map_err(int_error)?.1,
                "&" => x.bitand(&y),
                "|" => x.bitor(&y),
                "^" => x.bitxor(&y),
                "<<" => x.shl(&y).map_err(int_error)?,
                ">>" => x.shr(&y).map_err(int_error)?,
                "**" => {
                    if y.is_negative() {
                        return Ok(Value::Float(self.as_float(&a)?.powf(self.as_float(&b)?)));
                    }
                    x.pow(&y).map_err(int_error)?
                }
                "/" => return Ok(Value::Float(x.ratio(&y).map_err(int_error)?)),
                _ => return Err(pyerr("TypeError", "unsupported integer operation")),
            };
            return Ok(Value::Int(n));
        }
        if matches!(a, Value::Float(_) | Value::Int(_) | Value::Bool(_))
            && matches!(b, Value::Float(_) | Value::Int(_) | Value::Bool(_))
        {
            let x = self.as_float(&a)?;
            let y = self.as_float(&b)?;
            let z = match op {
                "+" => x + y,
                "-" => x - y,
                "*" => x * y,
                "/" => {
                    if y == 0.0 {
                        return Err(pyerr("ZeroDivisionError", "float division by zero"));
                    }
                    x / y
                }
                "//" => {
                    if y == 0.0 {
                        return Err(pyerr("ZeroDivisionError", "float floor division by zero"));
                    }
                    (x / y).floor()
                }
                "%" => {
                    if y == 0.0 {
                        return Err(pyerr("ZeroDivisionError", "float modulo"));
                    }
                    let r = x % y;
                    if r != 0.0 && r.signum() != y.signum() {
                        r + y
                    } else {
                        r
                    }
                }
                "**" => x.powf(y),
                _ => return Err(pyerr("TypeError", "unsupported float operation")),
            };
            return Ok(Value::Float(z));
        }
        match (&a, &b, op) {
            (Value::Str(x), Value::Str(y), "+" | "+=") => {
                return Ok(Value::Str(format!("{}{}", x, y)))
            }
            (Value::Bytes(x), Value::Bytes(y), "+") => {
                let mut z = x.clone();
                z.extend(y);
                return Ok(Value::Bytes(z));
            }
            (Value::Str(s), Value::Int(_) | Value::Bool(_), "*")
            | (Value::Int(_) | Value::Bool(_), Value::Str(s), "*") => {
                let v = if matches!(a, Value::Str(_)) { &b } else { &a };
                let n = self.as_int(v)?.to_i128().unwrap_or(i128::MAX).max(0);
                if n > 100_000_000 {
                    return Err(pyerr("OverflowError", "repeated string is too long"));
                }
                return Ok(Value::Str(s.repeat(n as usize)));
            }
            (Value::Str(fmt), _, "%") => {
                return Ok(Value::Str(self.percent_format(fmt, b.clone())?))
            }
            _ => {}
        }
        if let Value::Obj(i) = &a {
            match self.object(*i)? {
                Object::List(mut xs) | Object::Tuple(mut xs) => {
                    let tuple = matches!(self.object(*i)?, Object::Tuple(_));
                    if op == "+" || op == "+=" {
                        if let Value::Obj(j) = &b {
                            let ys = match self.object(*j)? {
                                Object::List(v) if !tuple => v,
                                Object::Tuple(v) if tuple => v,
                                _ => {
                                    return Err(pyerr(
                                        "TypeError",
                                        "can only concatenate matching sequences",
                                    ))
                                }
                            };
                            xs.extend(ys);
                            if op == "+=" && !tuple {
                                self.heap[*i] = Some(Object::List(xs));
                                return Ok(a);
                            }
                            return Ok(self.obj_value(if tuple {
                                Object::Tuple(xs)
                            } else {
                                Object::List(xs)
                            }));
                        }
                    }
                    if op == "*" || op == "*=" {
                        let n = self.as_int(&b)?.to_i128().unwrap_or(i128::MAX).max(0);
                        if n > 100_000_000 {
                            return Err(pyerr("OverflowError", "repeated sequence is too long"));
                        }
                        let mut out = Vec::new();
                        for _ in 0..n {
                            out.extend(xs.iter().cloned())
                        }
                        if op == "*=" && !tuple {
                            self.heap[*i] = Some(Object::List(out));
                            return Ok(a);
                        }
                        return Ok(self.obj_value(if tuple {
                            Object::Tuple(out)
                        } else {
                            Object::List(out)
                        }));
                    }
                }
                Object::Set(xs) => {
                    let ys = self.to_vec(b.clone())?;
                    let mut out = Vec::new();
                    match op {
                        "|" => {
                            out = xs.clone();
                            for v in ys {
                                if !self.contains_vec(&out, &v)? {
                                    out.push(v)
                                }
                            }
                        }
                        "&" => {
                            for v in xs {
                                if self.contains_vec(&ys, &v)? {
                                    out.push(v)
                                }
                            }
                        }
                        "-" => {
                            for v in xs {
                                if !self.contains_vec(&ys, &v)? {
                                    out.push(v)
                                }
                            }
                        }
                        "^" => {
                            for v in &xs {
                                if !self.contains_vec(&ys, v)? {
                                    out.push(v.clone())
                                }
                            }
                            for v in ys {
                                if !self.contains_vec(&xs, &v)? {
                                    out.push(v)
                                }
                            }
                        }
                        _ => return Err(pyerr("TypeError", "unsupported set operator")),
                    }
                    return Ok(self.obj_value(Object::Set(out)));
                }
                Object::Dict(mut xs) if op == "|" => {
                    for (k, v) in self.dict_items(b.clone())? {
                        if let Some(p) = self.find_key(&xs, &k)? {
                            xs[p].1 = v
                        } else {
                            xs.push((k, v))
                        }
                    }
                    return Ok(self.obj_value(Object::Dict(xs)));
                }
                _ => {}
            }
        }
        if op == "*" && matches!(a, Value::Int(_) | Value::Bool(_)) && matches!(b, Value::Obj(_)) {
            return self.binary(op, b, a);
        }
        let method = match op {
            "+" | "+=" => "add",
            "-" | "-=" => "sub",
            "*" | "*=" => "mul",
            "/" => "truediv",
            "//" => "floordiv",
            "%" => "mod",
            "**" => "pow",
            "&" => "and",
            "|" => "or",
            "^" => "xor",
            "<<" => "lshift",
            ">>" => "rshift",
            "@" => "matmul",
            _ => "",
        };
        for (index, (obj, arg, name)) in [
            (a.clone(), b.clone(), format!("__{}__", method)),
            (b.clone(), a.clone(), format!("__r{}__", method)),
        ]
        .into_iter()
        .enumerate()
        {
            if index == 1 && reflected_first {
                continue;
            }
            if let Ok(fun) = self.special_method(obj, &name) {
                let v = self.call(fun, vec![arg], Vec::new(), None)?;
                if !matches!(&v,Value::Builtin(n) if n=="NotImplemented") {
                    return Ok(v);
                }
            }
        }
        let ap = self.native_payload(&a);
        let bp = self.native_payload(&b);
        if ap.is_some() || bp.is_some() {
            return self.binary(op, ap.unwrap_or(a), bp.unwrap_or(b));
        }
        Err(pyerr(
            "TypeError",
            format!(
                "unsupported operand type(s) for {}: '{}' and '{}'",
                op,
                self.typename(&a),
                self.typename(&b)
            ),
        ))
    }
}

impl Runtime {
    fn index(&mut self, key: &Value, len: usize) -> PyResult<usize> {
        let n = self
            .as_int(key)?
            .to_i128()
            .ok_or_else(|| pyerr("IndexError", "cannot fit index into an index-sized integer"))?;
        let i = if n < 0 { n + len as i128 } else { n };
        if i < 0 || i >= len as i128 {
            return Err(pyerr("IndexError", "index out of range"));
        }
        Ok(i as usize)
    }
    fn slice_indices(
        &self,
        start: Option<Int>,
        stop: Option<Int>,
        step: Option<Int>,
        len: usize,
    ) -> PyResult<Vec<usize>> {
        let n = len as i128;
        let step = step.and_then(|x| x.to_i128()).unwrap_or(1);
        if step == 0 {
            return Err(pyerr("ValueError", "slice step cannot be zero"));
        }
        let norm = |v: i128, low: i128, high: i128| {
            let v = if v < 0 { v + n } else { v };
            v.max(low).min(high)
        };
        let (mut a, b) = if step > 0 {
            (
                start
                    .and_then(|x| x.to_i128())
                    .map(|x| norm(x, 0, n))
                    .unwrap_or(0),
                stop.and_then(|x| x.to_i128())
                    .map(|x| norm(x, 0, n))
                    .unwrap_or(n),
            )
        } else {
            (
                start
                    .and_then(|x| x.to_i128())
                    .map(|x| norm(x, -1, n - 1))
                    .unwrap_or(n - 1),
                stop.and_then(|x| x.to_i128())
                    .map(|x| norm(x, -1, n - 1))
                    .unwrap_or(-1),
            )
        };
        let mut out = Vec::new();
        while if step > 0 { a < b } else { a > b } {
            out.push(a as usize);
            a = a.saturating_add(step)
        }
        Ok(out)
    }
    fn find_key(&mut self, items: &[(Value, Value)], key: &Value) -> PyResult<Option<usize>> {
        for (i, (k, _)) in items.iter().enumerate() {
            if self.equal(k, key)? {
                return Ok(Some(i));
            }
        }
        Ok(None)
    }
    fn getitem(&mut self, obj: Value, key: Value) -> PyResult<Value> {
        if let Value::Obj(i) = &obj {
            if let Object::BuiltinInstance { class, payload, .. } = self.object(*i)? {
                if self.class_lookup(&class, "__getitem__", 0).is_some() {
                    let fun = self.special_method(obj, "__getitem__").map_err(|e| {
                        if e.kind == "AttributeError" {
                            pyerr("TypeError", "object is not subscriptable")
                        } else {
                            e
                        }
                    })?;
                    return self.call(fun, vec![key], Vec::new(), None);
                }
                return self.getitem(payload, key);
            }
        }
        if let Value::Obj(i) = &obj {
            if matches!(key, Value::Int(_) | Value::Bool(_)) {
                let len = match self.heap.get(*i).and_then(|o| o.as_ref()) {
                    Some(Object::List(xs) | Object::Tuple(xs)) => Some(xs.len()),
                    _ => None,
                };
                if let Some(len) = len {
                    let at = self.index(&key, len)?;
                    if let Some(Object::List(xs) | Object::Tuple(xs)) =
                        self.heap.get(*i).and_then(|o| o.as_ref())
                    {
                        return Ok(xs[at].clone());
                    }
                }
            }
        }
        let slice = if let Value::Obj(i) = key.clone() {
            match self.object(i)? {
                Object::Slice(a, b, c) => Some((a, b, c)),
                _ => None,
            }
        } else {
            None
        };
        match obj.clone() {
            Value::Str(s) => {
                let chars: Vec<char> = s.chars().collect();
                if let Some((a, b, c)) = slice {
                    let ids = self.slice_indices(a, b, c, chars.len())?;
                    Ok(Value::Str(ids.into_iter().map(|i| chars[i]).collect()))
                } else {
                    let i = self.index(&key, chars.len())?;
                    Ok(Value::Str(chars[i].to_string()))
                }
            }
            Value::Bytes(xs) => {
                if let Some((a, b, c)) = slice {
                    let ids = self.slice_indices(a, b, c, xs.len())?;
                    Ok(Value::Bytes(ids.into_iter().map(|i| xs[i]).collect()))
                } else {
                    let i = self.index(&key, xs.len())?;
                    Ok(Value::Int(Int::from_i128(xs[i] as i128)))
                }
            }
            Value::Obj(i) => match self.object(i)? {
                Object::List(xs) | Object::Tuple(xs) => {
                    if let Some((a, b, c)) = slice {
                        let ids = self.slice_indices(a, b, c, xs.len())?;
                        let ys = ids.into_iter().map(|i| xs[i].clone()).collect();
                        Ok(
                            self.obj_value(if matches!(self.object(i)?, Object::Tuple(_)) {
                                Object::Tuple(ys)
                            } else {
                                Object::List(ys)
                            }),
                        )
                    } else {
                        let i = self.index(&key, xs.len())?;
                        Ok(xs[i].clone())
                    }
                }
                Object::Dict(items) => {
                    if let Some(i) = self.find_key(&items, &key)? {
                        Ok(items[i].1.clone())
                    } else {
                        Err(pyerr("KeyError", self.repr(&key)?))
                    }
                }
                Object::Namespace(m, _) => {
                    if let Value::Str(k) = key {
                        m.get(&k).cloned().ok_or_else(|| pyerr("KeyError", k))
                    } else {
                        Err(pyerr("KeyError", "invalid key"))
                    }
                }
                Object::Instance { .. } => {
                    let fun = self.special_method(obj, "__getitem__").map_err(|e| {
                        if e.kind == "AttributeError" {
                            pyerr("TypeError", "object is not subscriptable")
                        } else {
                            e
                        }
                    })?;
                    self.call(fun, vec![key], Vec::new(), None)
                }
                _ => Err(pyerr("TypeError", "object is not subscriptable")),
            },
            _ => Err(pyerr(
                "TypeError",
                format!("'{}' object is not subscriptable", self.typename(&obj)),
            )),
        }
    }
    fn setitem(&mut self, obj: Value, key: Value, value: Value) -> PyResult<()> {
        if let Value::Obj(i) = &obj {
            if matches!(key, Value::Int(_) | Value::Bool(_)) {
                let len = match self.heap.get(*i).and_then(|o| o.as_ref()) {
                    Some(Object::List(xs)) => Some(xs.len()),
                    _ => None,
                };
                if let Some(len) = len {
                    let at = self.index(&key, len)?;
                    if let Some(Object::List(xs)) = self.heap.get_mut(*i).and_then(|o| o.as_mut()) {
                        xs[at] = value;
                        return Ok(());
                    }
                }
            }
        }
        if let Value::Obj(i) = obj.clone() {
            match self.object(i)? {
                Object::List(mut xs) => {
                    if let Value::Obj(si) = key.clone() {
                        if let Object::Slice(a, b, c) = self.object(si)? {
                            let stride = c.as_ref().and_then(|x| x.to_i128()).unwrap_or(1);
                            let ys = self.to_vec(value)?;
                            if stride == 1 {
                                let n = xs.len() as i128;
                                let norm = |v: Option<Int>, default: i128| {
                                    let x = v.and_then(|x| x.to_i128()).unwrap_or(default);
                                    (if x < 0 { x + n } else { x }).max(0).min(n) as usize
                                };
                                let a = norm(a, 0);
                                let b = norm(b, n).max(a);
                                xs.splice(a..b, ys);
                            } else {
                                let ids = self.slice_indices(a, b, c, xs.len())?;
                                if ids.len() != ys.len() {
                                    return Err(pyerr("ValueError","attempt to assign sequence of different size to extended slice"));
                                }
                                for (i, v) in ids.into_iter().zip(ys) {
                                    xs[i] = v
                                }
                            }
                            self.heap[i] = Some(Object::List(xs));
                            return Ok(());
                        }
                    }
                    let j = self.index(&key, xs.len())?;
                    xs[j] = value;
                    self.heap[i] = Some(Object::List(xs));
                    return Ok(());
                }
                Object::Dict(mut items) => {
                    if matches!(key,Value::Obj(j) if matches!(self.heap.get(j).and_then(|o|o.as_ref()),Some(Object::List(_)|Object::Dict(_)|Object::Set(_))))
                    {
                        return Err(pyerr("TypeError", "unhashable type"));
                    }
                    if let Some(j) = self.find_key(&items, &key)? {
                        items[j].1 = value
                    } else {
                        items.push((key, value))
                    }
                    self.heap[i] = Some(Object::Dict(items));
                    return Ok(());
                }
                Object::Namespace(_, _) => {
                    if let Value::Str(s) = key {
                        self.ns_set(i, s, value);
                        return Ok(());
                    }
                }
                Object::Instance { .. } => {
                    let fun = self.special_method(obj, "__setitem__").map_err(|e| {
                        if e.kind == "AttributeError" {
                            pyerr("TypeError", "object does not support item assignment")
                        } else {
                            e
                        }
                    })?;
                    self.call(fun, vec![key, value], Vec::new(), None)?;
                    return Ok(());
                }
                _ => {}
            }
        }
        Err(pyerr(
            "TypeError",
            "object does not support item assignment",
        ))
    }
    fn delitem(&mut self, obj: Value, key: Value) -> PyResult<()> {
        if let Value::Obj(i) = obj.clone() {
            match self.object(i)? {
                Object::List(mut xs) => {
                    if let Value::Obj(s) = &key {
                        if let Object::Slice(a, b, c) = self.object(*s)? {
                            let mut ids = self.slice_indices(a, b, c, xs.len())?;
                            ids.sort_unstable_by(|a, b| b.cmp(a));
                            for j in ids {
                                xs.remove(j);
                            }
                            self.heap[i] = Some(Object::List(xs));
                            return Ok(());
                        }
                    }
                    let j = self.index(&key, xs.len())?;
                    xs.remove(j);
                    self.heap[i] = Some(Object::List(xs));
                    return Ok(());
                }
                Object::Dict(mut items) => {
                    let j = self
                        .find_key(&items, &key)?
                        .ok_or_else(|| pyerr("KeyError", "key not found"))?;
                    items.remove(j);
                    self.heap[i] = Some(Object::Dict(items));
                    return Ok(());
                }
                Object::Namespace(_, _) => {
                    if let Value::Str(s) = key {
                        if self.ns_del(i, &s) {
                            return Ok(());
                        }
                        return Err(pyerr("KeyError", s));
                    }
                }
                Object::Instance { .. } => {
                    let fun = self.special_method(obj, "__delitem__").map_err(|e| {
                        if e.kind == "AttributeError" {
                            pyerr("TypeError", "object does not support item deletion")
                        } else {
                            e
                        }
                    })?;
                    self.call(fun, vec![key], Vec::new(), None)?;
                    return Ok(());
                }
                _ => {}
            }
        }
        Err(pyerr("TypeError", "object does not support item deletion"))
    }
    fn container_add(&mut self, obj: Value, v: Value, set: bool) -> PyResult<()> {
        if let Value::Obj(i) = obj {
            match self.object(i)? {
                Object::List(mut xs) if !set => {
                    xs.push(v);
                    self.heap[i] = Some(Object::List(xs));
                    return Ok(());
                }
                Object::Set(mut xs) => {
                    if !self.contains_vec(&xs, &v)? {
                        xs.push(v)
                    }
                    self.heap[i] = Some(Object::Set(xs));
                    return Ok(());
                }
                _ => {}
            }
        }
        Err(pyerr("TypeError", "invalid container"))
    }
    fn dict_items(&mut self, v: Value) -> PyResult<Vec<(Value, Value)>> {
        if let Value::Obj(i) = v.clone() {
            match self.object(i)? {
                Object::Dict(xs) => return Ok(xs),
                Object::Namespace(m, _) => {
                    return Ok(m.into_iter().map(|(k, v)| (Value::Str(k), v)).collect())
                }
                Object::Module { attrs, .. } => return self.dict_items(Value::Obj(attrs)),
                _ => {}
            }
        }
        if let Ok(keys) = self.getattr(v.clone(), "keys") {
            let keys = self.call(keys, Vec::new(), Vec::new(), None)?;
            let mut out = Vec::new();
            for k in self.to_vec(keys)? {
                let value = self.getitem(v.clone(), k.clone())?;
                out.push((k, value));
            }
            return Ok(out);
        }
        let mut out = Vec::new();
        for p in self.to_vec(v)? {
            let pair = self.to_vec(p)?;
            if pair.len() != 2 {
                return Err(pyerr(
                    "ValueError",
                    "dictionary update sequence element has length other than 2",
                ));
            }
            out.push((pair[0].clone(), pair[1].clone()))
        }
        Ok(out)
    }
    fn keyword_items(&mut self, v: Value) -> PyResult<Vec<(String, Value)>> {
        let mut out = Vec::new();
        for (k, v) in self.dict_items(v)? {
            if let Value::Str(k) = k {
                out.push((k, v))
            } else {
                return Err(pyerr("TypeError", "keywords must be strings"));
            }
        }
        Ok(out)
    }
    fn to_vec(&mut self, v: Value) -> PyResult<Vec<Value>> {
        let it = self.iter(v)?;
        let mut out = Vec::new();
        while let Some(v) = self.next(it.clone())? {
            out.push(v)
        }
        Ok(out)
    }
    fn iter(&mut self, v: Value) -> PyResult<Value> {
        if let Value::Obj(i) = &v {
            if let Object::BuiltinInstance { class, payload, .. } = self.object(*i)? {
                if self.class_lookup(&class, "__iter__", 0).is_some() {
                    let fun = self.special_method(v, "__iter__")?;
                    return self.call(fun, Vec::new(), Vec::new(), None);
                }
                return self.iter(payload);
            }
        }
        if let Value::Obj(i) = &v {
            if matches!(
                self.heap.get(*i).and_then(|o| o.as_ref()),
                Some(Object::List(_) | Object::Tuple(_))
            ) {
                return Ok(self.obj_value(Object::Iterator(IteratorState::List(*i, 0))));
            }
        }
        let state = match v.clone() {
            Value::Str(s) => {
                IteratorState::Values(s.chars().map(|c| Value::Str(c.to_string())).collect(), 0)
            }
            Value::Bytes(s) => IteratorState::Values(
                s.into_iter()
                    .map(|x| Value::Int(Int::from_i128(x as i128)))
                    .collect(),
                0,
            ),
            Value::Obj(i) => match self.object(i)? {
                Object::Record { fields, .. } => {
                    IteratorState::Values(fields.into_iter().map(|(_, v)| v).collect(), 0)
                }
                Object::List(_) => IteratorState::List(i, 0),
                Object::Range(a, b, c) => IteratorState::Range(a, b, c),
                Object::Tuple(v) | Object::Set(v) => IteratorState::Values(v, 0),
                Object::Dict(v) => {
                    IteratorState::Values(v.into_iter().map(|(k, _)| k).collect(), 0)
                }
                Object::Namespace(v, _) => {
                    IteratorState::Values(v.keys().map(|s| Value::Str(s.clone())).collect(), 0)
                }
                Object::Iterator(_) | Object::Generator(_) => return Ok(v),
                Object::Instance { .. } => {
                    if let Ok(fun) = self.special_method(v.clone(), "__iter__") {
                        return self.call(fun, Vec::new(), Vec::new(), None);
                    }
                    return Ok(self.obj_value(Object::Iterator(IteratorState::Reversed(v, -2))));
                }
                _ => return Err(pyerr("TypeError", "object is not iterable")),
            },
            _ => {
                return Err(pyerr(
                    "TypeError",
                    format!("'{}' object is not iterable", self.typename(&v)),
                ))
            }
        };
        Ok(self.obj_value(Object::Iterator(state)))
    }
    fn next(&mut self, it: Value) -> PyResult<Option<Value>> {
        if let Value::Obj(i) = it.clone() {
            match self.object(i)? {
                Object::Iterator(state) => match state {
                    IteratorState::Tools(mut state) => {
                        let result = self.tool_next(&mut state);
                        self.heap[i] = Some(Object::Iterator(IteratorState::Tools(state)));
                        return result;
                    }
                    IteratorState::Values(v, p) => {
                        if p >= v.len() {
                            return Ok(None);
                        }
                        self.heap[i] =
                            Some(Object::Iterator(IteratorState::Values(v.clone(), p + 1)));
                        return Ok(Some(v[p].clone()));
                    }
                    IteratorState::List(j, p) => {
                        let value = match self.heap.get(j).and_then(|o| o.as_ref()) {
                            Some(Object::List(v) | Object::Tuple(v)) => v.get(p).cloned(),
                            _ => None,
                        };
                        if let Some(value) = value {
                            self.heap[i] = Some(Object::Iterator(IteratorState::List(j, p + 1)));
                            return Ok(Some(value));
                        }
                        return Ok(None);
                    }
                    IteratorState::Range(cur, stop, step) => {
                        if if step.is_negative() {
                            cur <= stop
                        } else {
                            cur >= stop
                        } {
                            return Ok(None);
                        }
                        let value = cur.clone();
                        self.heap[i] = Some(Object::Iterator(IteratorState::Range(
                            cur.add(&step),
                            stop,
                            step,
                        )));
                        return Ok(Some(Value::Int(value)));
                    }
                    IteratorState::Enumerate(inner, n) => {
                        if let Some(v) = self.next(inner.clone())? {
                            self.heap[i] = Some(Object::Iterator(IteratorState::Enumerate(
                                inner,
                                n.add(&Int::from_i128(1)),
                            )));
                            return Ok(Some(self.obj_value(Object::Tuple(vec![Value::Int(n), v]))));
                        }
                        return Ok(None);
                    }
                    IteratorState::Zip(its) => {
                        if its.is_empty() {
                            return Ok(None);
                        }
                        let mut out = Vec::new();
                        for it in its {
                            if let Some(v) = self.next(it)? {
                                out.push(v)
                            } else {
                                return Ok(None);
                            }
                        }
                        return Ok(Some(self.obj_value(Object::Tuple(out))));
                    }
                    IteratorState::Map(fun, its) => {
                        let mut args = Vec::new();
                        for it in its {
                            if let Some(v) = self.next(it)? {
                                args.push(v)
                            } else {
                                return Ok(None);
                            }
                        }
                        return Ok(Some(self.call(fun, args, Vec::new(), None)?));
                    }
                    IteratorState::Filter(fun, inner) => {
                        while let Some(v) = self.next(inner.clone())? {
                            let b = if matches!(fun, Value::None) {
                                self.truth(&v)?
                            } else {
                                let r =
                                    self.call(fun.clone(), vec![v.clone()], Vec::new(), None)?;
                                self.truth(&r)?
                            };
                            if b {
                                return Ok(Some(v));
                            }
                        }
                        return Ok(None);
                    }
                    IteratorState::Callable(fun, sentinel) => {
                        let v = self.call(fun, Vec::new(), Vec::new(), None)?;
                        return if self.equal(&v, &sentinel)? {
                            Ok(None)
                        } else {
                            Ok(Some(v))
                        };
                    }
                    IteratorState::Reversed(obj, p) => {
                        let k = if p <= -2 { -p - 2 } else { p };
                        let result =
                            self.getitem(obj.clone(), Value::Int(Int::from_i128(k as i128)));
                        match result {
                            Ok(v) => {
                                let np = if p <= -2 { p - 1 } else { p - 1 };
                                self.heap[i] =
                                    Some(Object::Iterator(IteratorState::Reversed(obj, np)));
                                return Ok(Some(v));
                            }
                            Err(e) if e.kind == "IndexError" => return Ok(None),
                            Err(e) => return Err(e),
                        }
                    }
                },
                Object::Generator(mut frame) => {
                    if frame.pc == usize::MAX {
                        return Ok(None);
                    }
                    if frame.pc > 0
                        && matches!(
                            self.codes[frame.code].ops.get(frame.pc - 1).map(|x| &x.op),
                            Some(Op::Yield)
                        )
                    {
                        frame
                            .stack
                            .push(frame.resume_value.take().unwrap_or(Value::None))
                    }
                    if self.running_generators.contains(&i) {
                        return Err(pyerr("ValueError", "generator already executing"));
                    }
                    self.running_generators.push(i);
                    let executed = self.execute(frame);
                    self.running_generators.pop();
                    let (exit, mut f) = match executed {
                        Ok(result) => result,
                        Err(e) => {
                            if let Some(Object::Generator(frame)) =
                                self.heap.get_mut(i).and_then(|o| o.as_mut())
                            {
                                frame.pc = usize::MAX;
                            }
                            return Err(e);
                        }
                    };
                    match exit {
                        FrameExit::Yield(v) => {
                            self.heap[i] = Some(Object::Generator(f));
                            return Ok(Some(v));
                        }
                        FrameExit::Return(value) => {
                            self.ns_set(f.temps, "$generator_return".into(), value);
                            f.pc = usize::MAX;
                            self.heap[i] = Some(Object::Generator(f));
                            return Ok(None);
                        }
                    }
                }
                Object::Instance { .. } => {
                    let fun = self.special_method(it, "__next__")?;
                    match self.call(fun, Vec::new(), Vec::new(), None) {
                        Ok(v) => return Ok(Some(v)),
                        Err(e) if e.kind == "StopIteration" => return Ok(None),
                        Err(e) => return Err(e),
                    }
                }
                _ => {}
            }
        }
        Err(pyerr("TypeError", "object is not an iterator"))
    }
    fn same_type(a: &Value, b: &Value) -> bool {
        match (a, b) {
            (Value::Obj(a), Value::Obj(b)) => a == b,
            (Value::Builtin(a), Value::Builtin(b)) | (Value::Type(a), Value::Type(b)) => a == b,
            _ => false,
        }
    }
    fn class_mro(&self, class: &Value, depth: usize) -> Option<Vec<Value>> {
        if depth > 100 {
            return None;
        }
        let bases = match class {
            Value::Obj(i) => match self.heap.get(*i).and_then(|o| o.as_ref()) {
                Some(Object::Class(c)) => {
                    if c.bases.is_empty() {
                        vec![Value::Builtin("object".into())]
                    } else {
                        c.bases.clone()
                    }
                }
                _ => return None,
            },
            Value::Builtin(n) if n == "object" => return Some(vec![class.clone()]),
            Value::Builtin(n) if n == "bool" => vec![Value::Builtin("int".into())],
            Value::Builtin(_) => vec![Value::Builtin("object".into())],
            Value::Type(n) => {
                let p = Self::exception_parent(n);
                if p.is_empty() {
                    vec![Value::Builtin("object".into())]
                } else {
                    vec![Value::Type(p.into())]
                }
            }
            _ => return None,
        };
        let mut seqs = Vec::new();
        for b in &bases {
            seqs.push(self.class_mro(b, depth + 1)?)
        }
        seqs.push(bases);
        let mut out = vec![class.clone()];
        loop {
            seqs.retain(|s| !s.is_empty());
            if seqs.is_empty() {
                return Some(out);
            }
            let mut candidate = None;
            for s in &seqs {
                let head = &s[0];
                if !seqs
                    .iter()
                    .any(|other| other.iter().skip(1).any(|v| Self::same_type(v, head)))
                {
                    candidate = Some(head.clone());
                    break;
                }
            }
            let head = candidate?;
            out.push(head.clone());
            for s in &mut seqs {
                if Self::same_type(&s[0], &head) {
                    s.remove(0);
                }
            }
        }
    }
    fn class_lookup(&self, class: &Value, name: &str, depth: usize) -> Option<Value> {
        for base in self.class_mro(class, depth)? {
            if let Value::Obj(i) = base {
                if let Some(Object::Class(c)) = self.heap.get(i).and_then(|o| o.as_ref()) {
                    if let Some(v) = self.ns_get(c.attrs, name) {
                        return Some(v);
                    }
                }
            }
        }
        None
    }
    fn bind_descriptor(
        &mut self,
        v: Value,
        instance: Option<Value>,
        class: Value,
    ) -> PyResult<Value> {
        if let Value::Obj(i) = v.clone() {
            match self.object(i)? {
                Object::Static(v) => return Ok(v),
                Object::ClassMethod(v) => return Ok(self.obj_value(Object::Bound(v, class))),
                Object::Property { get, .. } => {
                    if let Some(o) = instance {
                        return self.call(get, vec![o], Vec::new(), None);
                    }
                }
                Object::Function(_) => {
                    if let Some(o) = instance {
                        return Ok(self.obj_value(Object::Bound(v, o)));
                    }
                }
                Object::Instance { class: c, .. } => {
                    if let Some(fun) = self.class_lookup(&c, "__get__", 0) {
                        let fun = self.obj_value(Object::Bound(fun, v));
                        return self.call(
                            fun,
                            vec![instance.unwrap_or(Value::None), class],
                            Vec::new(),
                            None,
                        );
                    }
                }
                _ => {}
            }
        }
        Ok(v)
    }
    fn getattr_default(&mut self, v: Value, name: &str) -> PyResult<Value> {
        if name == "fromkeys"
            && (matches!(&v,Value::Builtin(n)if n=="dict")
                || matches!(&v,Value::Obj(i)if matches!(self.heap.get(*i).and_then(|o|o.as_ref()),Some(Object::Dict(_)|Object::Namespace(..)))))
        {
            return Ok(Value::Builtin("dict:fromkeys".into()));
        }
        if name == "__get__" {
            if let Value::Obj(i) = &v {
                if matches!(
                    self.heap.get(*i).and_then(|o| o.as_ref()),
                    Some(
                        Object::Function(_)
                            | Object::Static(_)
                            | Object::ClassMethod(_)
                            | Object::Property { .. }
                    )
                ) {
                    return Ok(
                        self.obj_value(Object::Bound(Value::Builtin("descriptor:get".into()), v))
                    );
                }
            }
        }
        if matches!(&v,Value::Builtin(n)if n=="module:itertools:chain") && name == "from_iterable" {
            return Ok(Value::Builtin(
                "module:itertools:chain.from_iterable".into(),
            ));
        }
        if let Value::Obj(i) = &v {
            let methods: Option<&[&str]> = match self.heap.get(*i).and_then(|o| o.as_ref()) {
                Some(Object::List(_)) => Some(&[
                    "append",
                    "extend",
                    "insert",
                    "pop",
                    "remove",
                    "clear",
                    "index",
                    "count",
                    "sort",
                    "reverse",
                    "copy",
                    "__iter__",
                    "__len__",
                    "__getitem__",
                ]),
                Some(Object::Tuple(_)) => {
                    Some(&["index", "count", "__iter__", "__len__", "__getitem__"])
                }
                Some(Object::Dict(_) | Object::Namespace(..)) => Some(&[
                    "get",
                    "keys",
                    "values",
                    "items",
                    "pop",
                    "popitem",
                    "setdefault",
                    "update",
                    "clear",
                    "copy",
                    "__iter__",
                    "__len__",
                    "__getitem__",
                    "__contains__",
                ]),
                Some(Object::Set(_)) => Some(&[
                    "add",
                    "update",
                    "discard",
                    "remove",
                    "pop",
                    "clear",
                    "copy",
                    "union",
                    "intersection",
                    "difference",
                    "symmetric_difference",
                    "issubset",
                    "issuperset",
                    "isdisjoint",
                    "__iter__",
                    "__len__",
                    "__contains__",
                ]),
                _ => None,
            };
            if let Some(methods) = methods {
                if methods.contains(&name) {
                    return Ok(self
                        .obj_value(Object::Bound(Value::Builtin(format!("method:{}", name)), v)));
                }
                if name != "__class__" {
                    return Err(pyerr(
                        "AttributeError",
                        format!("'{}' object has no attribute '{}'", self.typename(&v), name),
                    ));
                }
            }
        }
        if name == "__class__" {
            return Ok(match &v {
                Value::Obj(i) => match self.object(*i)? {
                    Object::Instance { class, .. } | Object::BuiltinInstance { class, .. } => class,
                    Object::Class(c) => c.metaclass,
                    Object::Exception(e) => Value::Type(e.kind),
                    _ => Value::Builtin(self.typename(&v)),
                },
                _ => Value::Builtin(self.typename(&v)),
            });
        }
        if let Value::Obj(i) = v.clone() {
            match self.object(i)? {
                Object::Cell(value) => {
                    if name == "cell_contents" {
                        return value.ok_or_else(|| pyerr("ValueError", "Cell is empty"));
                    }
                }
                Object::Bound(function, receiver) => {
                    if name == "__self__" {
                        return Ok(receiver);
                    }
                    if name == "__func__" {
                        return Ok(function);
                    }
                    if name == "__name__" || name == "__qualname__" {
                        return self.getattr(function, name);
                    }
                }
                Object::Partial {
                    function,
                    args,
                    args_tuple,
                    keywords,
                    attrs,
                } => match name {
                    "func" => return Ok(function),
                    "args" => return Ok(Value::Obj(args_tuple)),
                    "keywords" => return Ok(Value::Obj(keywords)),
                    "__dict__" => return Ok(Value::Obj(attrs)),
                    _ => {
                        if let Some(value) = self.ns_get(attrs, name) {
                            return Ok(value);
                        }
                    }
                },
                Object::Cached(mut cache) => {
                    if name == "__dict__" {
                        let attrs = if let Some(i) = cache.attrs {
                            i
                        } else {
                            let attrs = self.alloc(Object::Dict(Vec::new()));
                            cache.attrs = Some(attrs);
                            self.heap[i] = Some(Object::Cached(cache));
                            attrs
                        };
                        return Ok(Value::Obj(attrs));
                    }
                    if let Some(attrs) = cache.attrs {
                        if let Some(value) = self.ns_get(attrs, name) {
                            return Ok(value);
                        }
                    }
                    if name == "__wrapped__" {
                        return Ok(cache.function);
                    }
                    if ["cache_info", "cache_clear", "cache_parameters"].contains(&name) {
                        return Ok(self.obj_value(Object::Bound(
                            Value::Builtin(format!("cache:{}", name)),
                            v,
                        )));
                    }
                    return self.getattr(cache.function, name);
                }
                Object::Record { fields, .. } => {
                    if let Some((_, value)) = fields.iter().find(|(n, _)| n == name) {
                        return Ok(value.clone());
                    }
                }
                Object::Property { .. } => {
                    if ["getter", "setter", "deleter"].contains(&name) {
                        return Ok(self.obj_value(Object::Bound(
                            Value::Builtin(format!("property:{}", name)),
                            v,
                        )));
                    }
                }
                Object::Module { attrs, .. } => {
                    if let Some(x) = self.ns_get(attrs, name) {
                        return Ok(x);
                    }
                }
                Object::Instance { class, attrs }
                | Object::BuiltinInstance { class, attrs, .. } => {
                    if matches!(&class,Value::Builtin(n)if n=="super") {
                        let c = self.ns_get(attrs, "$class").unwrap_or(Value::None);
                        let recv = self.ns_get(attrs, "$self").unwrap_or(Value::None);
                        let actual = match &recv {
                            Value::Obj(i) => match self.object(*i)? {
                                Object::Instance { class, .. }
                                | Object::BuiltinInstance { class, .. } => class,
                                Object::Class(_) => recv.clone(),
                                _ => recv.clone(),
                            },
                            _ => recv.clone(),
                        };
                        let mro = self
                            .class_mro(&actual, 0)
                            .ok_or_else(|| pyerr("TypeError", "invalid super object"))?;
                        if let Some(pos) = mro.iter().position(|v| Self::same_type(v, &c)) {
                            for base in mro.into_iter().skip(pos + 1) {
                                if let Value::Obj(bi) = base {
                                    if let Object::Class(bc) = self.object(bi)? {
                                        if let Some(value) = self.ns_get(bc.attrs, name) {
                                            return self.bind_descriptor(value, Some(recv), actual);
                                        }
                                    }
                                }
                            }
                        }
                        return Err(pyerr("AttributeError", name));
                    }
                    if name == "__dict__" {
                        if matches!(
                            self.heap.get(i).and_then(|o| o.as_ref()),
                            Some(Object::BuiltinInstance { .. })
                        ) && !self.instance_allows_dict(i)
                        {
                            return Err(pyerr("AttributeError", "object has no __dict__"));
                        }
                        return Ok(Value::Obj(attrs));
                    }
                    if let Some(d) = self.class_lookup(&class, name, 0) {
                        if let Value::Obj(di) = &d {
                            if matches!(self.object(*di)?, Object::Property { .. }) {
                                return self.bind_descriptor(d, Some(v), class);
                            }
                            if let Object::Instance { class: dc, .. } = self.object(*di)? {
                                if self.class_lookup(&dc, "__set__", 0).is_some() {
                                    return self.bind_descriptor(d, Some(v), class);
                                }
                            }
                        }
                    }
                    if let Some(x) = self.ns_get(attrs, name) {
                        return Ok(x);
                    }
                    if let Some(x) = self.class_lookup(&class, name, 0) {
                        return self.bind_descriptor(x, Some(v), class);
                    }
                    if let Object::BuiltinInstance { payload, .. } = self.object(i)? {
                        if let Ok(value) = self.getattr_default(payload, name) {
                            return Ok(value);
                        }
                    }
                    if let Some(x) = self.class_lookup(&class, "__getattr__", 0) {
                        let fun = self.obj_value(Object::Bound(x, v));
                        return self.call(fun, vec![Value::Str(name.into())], Vec::new(), None);
                    }
                }
                Object::Class(c) => {
                    if name == "__mro__" {
                        let mro = self
                            .class_mro(&v, 0)
                            .ok_or_else(|| pyerr("TypeError", "invalid method resolution order"))?;
                        return Ok(self.obj_value(Object::Tuple(mro)));
                    }
                    if name == "__name__" {
                        return Ok(Value::Str(c.name));
                    }
                    if name == "__qualname__" {
                        return Ok(self
                            .ns_get(c.attrs, "__qualname__")
                            .unwrap_or(Value::Str(c.name)));
                    }
                    if name == "__dict__" {
                        return Ok(Value::Obj(c.attrs));
                    }
                    if name == "__bases__" {
                        return Ok(self.obj_value(Object::Tuple(c.bases)));
                    }
                    if let Some(x) = self.class_lookup(&v, name, 0) {
                        return self.bind_descriptor(x, None, v);
                    }
                    if let Some(x) = self.class_lookup(&c.metaclass, name, 0) {
                        return self.bind_descriptor(x, Some(v.clone()), c.metaclass);
                    }
                }
                Object::Function(fun) => match name {
                    "__name__" => return Ok(Value::Str(fun.name)),
                    "__qualname__" => return Ok(Value::Str(fun.qualname)),
                    "__module__" => return Ok(fun.module),
                    "__doc__" => return Ok(fun.doc),
                    "__annotations__" => {
                        if !fun.annotations_evaluated {
                            let annotations = if let Some(annotate) = fun.annotate.clone() {
                                self.call(
                                    annotate,
                                    vec![Value::Int(Int::from_i128(1))],
                                    Vec::new(),
                                    None,
                                )?
                            } else {
                                fun.annotations.clone()
                            };
                            if !matches!(annotations,Value::Obj(ai)if matches!(self.heap.get(ai).and_then(|o|o.as_ref()),Some(Object::Dict(_)|Object::Namespace(..))))
                            {
                                return Err(pyerr(
                                    "TypeError",
                                    "__annotate__ must return a dictionary",
                                ));
                            }
                            if let Some(Object::Function(function)) = self.heap[i].as_mut() {
                                function.annotations = annotations.clone();
                                function.annotations_evaluated = true;
                            }
                            return Ok(annotations);
                        }
                        return Ok(fun.annotations);
                    }
                    "__annotate__" => return Ok(fun.annotate.unwrap_or(Value::None)),
                    "__type_params__" => return Ok(fun.type_params),
                    "__dict__" => return Ok(Value::Obj(fun.attrs)),
                    "__globals__" => return Ok(Value::Obj(fun.globals)),
                    "__code__" => return Ok(self.obj_value(Object::Code(fun.code))),
                    "__defaults__" => {
                        return Ok(if fun.defaults.is_empty() {
                            Value::None
                        } else {
                            self.obj_value(Object::Tuple(fun.defaults))
                        })
                    }
                    "__kwdefaults__" => {
                        return Ok(if fun.kwdefaults.is_empty() {
                            Value::None
                        } else {
                            self.obj_value(Object::Dict(
                                fun.kwdefaults
                                    .into_iter()
                                    .map(|(n, v)| (Value::Str(n), v))
                                    .collect(),
                            ))
                        })
                    }
                    _ => {
                        if let Some(value) = self.ns_get(fun.attrs, name) {
                            return Ok(value);
                        }
                    }
                },
                Object::Exception(e) => {
                    if name == "args" {
                        let xs = if e.message.is_empty() {
                            vec![]
                        } else {
                            vec![Value::Str(e.message)]
                        };
                        return Ok(self.obj_value(Object::Tuple(xs)));
                    }
                    if name == "__traceback__" || name == "__cause__" || name == "__context__" {
                        return Ok(Value::None);
                    }
                }
                Object::List(_)
                | Object::Tuple(_)
                | Object::Dict(_)
                | Object::Set(_)
                | Object::Namespace(..)
                | Object::Generator(_)
                | Object::Iterator(_) => {
                    let supported = match self.object(i)? {
                        Object::List(_) => [
                            "append",
                            "extend",
                            "insert",
                            "pop",
                            "remove",
                            "clear",
                            "index",
                            "count",
                            "sort",
                            "reverse",
                            "copy",
                            "__iter__",
                            "__len__",
                            "__getitem__",
                        ]
                        .contains(&name),
                        Object::Tuple(_) => {
                            ["index", "count", "__iter__", "__len__", "__getitem__"].contains(&name)
                        }
                        Object::Dict(_) | Object::Namespace(..) => [
                            "get",
                            "keys",
                            "values",
                            "items",
                            "pop",
                            "popitem",
                            "setdefault",
                            "update",
                            "clear",
                            "copy",
                            "__iter__",
                            "__len__",
                            "__getitem__",
                            "__contains__",
                        ]
                        .contains(&name),
                        Object::Set(_) => [
                            "add",
                            "update",
                            "discard",
                            "remove",
                            "pop",
                            "clear",
                            "copy",
                            "union",
                            "intersection",
                            "difference",
                            "symmetric_difference",
                            "issubset",
                            "issuperset",
                            "isdisjoint",
                            "__iter__",
                            "__len__",
                            "__contains__",
                        ]
                        .contains(&name),
                        Object::Generator(_) => {
                            ["__iter__", "__next__", "send", "close", "throw"].contains(&name)
                        }
                        _ => ["__iter__", "__next__"].contains(&name),
                    };
                    if supported {
                        return Ok(self.obj_value(Object::Bound(
                            Value::Builtin(format!("method:{}", name)),
                            v,
                        )));
                    }
                }
                _ => {}
            }
        }
        match &v {
            Value::Str(_) => {
                if [
                    "split",
                    "rsplit",
                    "splitlines",
                    "strip",
                    "lstrip",
                    "rstrip",
                    "join",
                    "replace",
                    "find",
                    "rfind",
                    "index",
                    "rindex",
                    "count",
                    "startswith",
                    "endswith",
                    "upper",
                    "lower",
                    "capitalize",
                    "title",
                    "swapcase",
                    "casefold",
                    "isdigit",
                    "isdecimal",
                    "isnumeric",
                    "isalpha",
                    "isalnum",
                    "isspace",
                    "islower",
                    "isupper",
                    "zfill",
                    "ljust",
                    "rjust",
                    "center",
                    "format",
                    "encode",
                    "removeprefix",
                    "removesuffix",
                    "partition",
                    "rpartition",
                    "__len__",
                    "__getitem__",
                    "__iter__",
                ]
                .contains(&name)
                {
                    return Ok(self
                        .obj_value(Object::Bound(Value::Builtin(format!("method:{}", name)), v)));
                }
            }
            Value::Bytes(_) => {
                if [
                    "decode",
                    "split",
                    "rsplit",
                    "strip",
                    "lstrip",
                    "rstrip",
                    "join",
                    "replace",
                    "startswith",
                    "endswith",
                    "find",
                    "rfind",
                    "index",
                    "rindex",
                    "count",
                    "hex",
                    "__len__",
                    "__getitem__",
                    "__iter__",
                ]
                .contains(&name)
                {
                    return Ok(self
                        .obj_value(Object::Bound(Value::Builtin(format!("method:{}", name)), v)));
                }
            }
            Value::Int(_) => {
                if [
                    "bit_length",
                    "bit_count",
                    "__index__",
                    "__int__",
                    "conjugate",
                ]
                .contains(&name)
                {
                    return Ok(self
                        .obj_value(Object::Bound(Value::Builtin(format!("method:{}", name)), v)));
                }
            }
            Value::Builtin(n) | Value::Type(n) => {
                if (n.starts_with("stream:") || n.starts_with("streambuffer:"))
                    && [
                        "read",
                        "readline",
                        "readlines",
                        "write",
                        "flush",
                        "isatty",
                        "readable",
                        "writable",
                    ]
                    .contains(&name)
                {
                    let (kind, target) = n.split_once(':').unwrap();
                    return Ok(Value::Builtin(format!(
                        "module:{}:{}:{}",
                        kind, target, name
                    )));
                }
                if name == "buffer" && n.starts_with("stream:") {
                    return Ok(Value::Builtin(n.replacen("stream:", "streambuffer:", 1)));
                }
                if name == "encoding" && n.starts_with("stream:") {
                    return Ok(Value::Str("utf-8".into()));
                }
                if name == "__name__" {
                    return Ok(Value::Str(n.clone()));
                }
                if name == "__mro__" {
                    if let Some(mro) = self.class_mro(&v, 0) {
                        return Ok(self.obj_value(Object::Tuple(mro)));
                    }
                }
                if n == "object"
                    && ["__getattribute__", "__setattr__", "__delattr__"].contains(&name)
                {
                    return Ok(Value::Builtin(format!("type_method:object:{}", name)));
                }
                if ["int", "str", "bytes", "list", "tuple", "dict", "set"].contains(&n.as_str())
                    && [
                        "__getitem__",
                        "__setitem__",
                        "__iter__",
                        "__len__",
                        "get",
                        "keys",
                        "values",
                        "items",
                        "update",
                        "append",
                        "extend",
                        "join",
                        "split",
                    ]
                    .contains(&name)
                {
                    return Ok(Value::Builtin(format!("unbound:{}:{}", n, name)));
                }
                if name == "__new__" || name == "__init__" {
                    return Ok(Value::Builtin(format!("type_method:{}:{}", n, name)));
                }
            }
            _ => {}
        }
        Err(pyerr(
            "AttributeError",
            format!("'{}' object has no attribute '{}'", self.typename(&v), name),
        ))
    }
    fn setattr_default(&mut self, obj: Value, name: &str, value: Value) -> PyResult<()> {
        if let Value::Obj(i) = obj.clone() {
            match self.object(i)? {
                Object::Cached(mut cache) => {
                    let attrs = if let Some(i) = cache.attrs {
                        i
                    } else {
                        let attrs = self.alloc(Object::Dict(Vec::new()));
                        cache.attrs = Some(attrs);
                        attrs
                    };
                    if name == "__dict__" {
                        if let Value::Obj(i) = value {
                            cache.attrs = Some(i)
                        } else {
                            return Err(pyerr("TypeError", "__dict__ must be a dictionary"));
                        }
                    } else {
                        self.ns_set(attrs, name.into(), value)
                    }
                    self.heap[i] = Some(Object::Cached(cache));
                    return Ok(());
                }
                Object::Function(mut fun) => {
                    match name {
                        "__name__" | "__qualname__" => {
                            let text = if let Value::Str(s) = value {
                                s
                            } else {
                                return Err(pyerr("TypeError", "function name must be a string"));
                            };
                            if name == "__name__" {
                                fun.name = text
                            } else {
                                fun.qualname = text
                            }
                        }
                        "__module__" => fun.module = value,
                        "__doc__" => fun.doc = value,
                        "__annotate__" => {
                            let callable =
                                self.builtin("callable", vec![value.clone()], Vec::new(), None)?;
                            if !matches!(value, Value::None)
                                && !matches!(callable, Value::Bool(true))
                            {
                                return Err(pyerr(
                                    "TypeError",
                                    "__annotate__ must be callable or None",
                                ));
                            }
                            fun.annotate = if matches!(value, Value::None) {
                                None
                            } else {
                                Some(value)
                            };
                            fun.annotations_evaluated = false;
                        }
                        "__annotations__" => {
                            fun.annotations_evaluated = true;
                            fun.annotations = if matches!(value, Value::None) {
                                self.obj_value(Object::Dict(Vec::new()))
                            } else {
                                value
                            }
                        }
                        "__type_params__" => fun.type_params = value,
                        "__defaults__" => {
                            fun.defaults = if matches!(value, Value::None) {
                                Vec::new()
                            } else {
                                self.to_vec(value)?
                            }
                        }
                        "__kwdefaults__" => {
                            fun.kwdefaults = if matches!(value, Value::None) {
                                HashMap::new()
                            } else {
                                self.keyword_items(value)?.into_iter().collect()
                            }
                        }
                        "__code__" => {
                            if let Value::Obj(ci) = value {
                                if let Object::Code(code) = self.object(ci)? {
                                    fun.code = code
                                } else {
                                    return Err(pyerr(
                                        "TypeError",
                                        "__code__ must be set to a code object",
                                    ));
                                }
                            } else {
                                return Err(pyerr(
                                    "TypeError",
                                    "__code__ must be set to a code object",
                                ));
                            }
                        }
                        "__dict__" => {
                            if let Value::Obj(attrs) = value {
                                if matches!(
                                    self.object(attrs)?,
                                    Object::Dict(_) | Object::Namespace(..)
                                ) {
                                    fun.attrs = attrs
                                } else {
                                    return Err(pyerr(
                                        "TypeError",
                                        "__dict__ must be set to a dictionary",
                                    ));
                                }
                            } else {
                                return Err(pyerr(
                                    "TypeError",
                                    "__dict__ must be set to a dictionary",
                                ));
                            }
                        }
                        _ => self.ns_set(fun.attrs, name.into(), value),
                    }
                    self.heap[i] = Some(Object::Function(fun));
                    return Ok(());
                }
                Object::Partial { attrs, .. } => {
                    if ["func", "args", "keywords"].contains(&name) {
                        return Err(pyerr("AttributeError", "readonly attribute"));
                    }
                    if matches!(
                        self.heap.get(i).and_then(|o| o.as_ref()),
                        Some(Object::BuiltinInstance { .. })
                    ) && !self.instance_allows_dict(i)
                    {
                        return Err(pyerr(
                            "AttributeError",
                            format!(
                                "'{}' object has no attribute '{}'",
                                self.typename(&obj),
                                name
                            ),
                        ));
                    }
                    self.ns_set(attrs, name.into(), value);
                    return Ok(());
                }
                Object::Cell(_) => {
                    if name == "cell_contents" {
                        self.heap[i] = Some(Object::Cell(Some(value)));
                        return Ok(());
                    }
                }
                Object::Instance { class, attrs }
                | Object::BuiltinInstance { class, attrs, .. } => {
                    if let Some(d) = self.class_lookup(&class, name, 0) {
                        if let Value::Obj(di) = d.clone() {
                            if let Object::Property { set, .. } = self.object(di)? {
                                let setter = set.ok_or_else(|| {
                                    pyerr("AttributeError", "property has no setter")
                                })?;
                                self.call(setter, vec![obj, value], Vec::new(), None)?;
                                return Ok(());
                            }
                        }
                        if let Ok(setter) = self.getattr(d, "__set__") {
                            self.call(setter, vec![obj, value], Vec::new(), None)?;
                            return Ok(());
                        }
                    }
                    if matches!(
                        self.heap.get(i).and_then(|o| o.as_ref()),
                        Some(Object::BuiltinInstance { .. })
                    ) && !self.instance_allows_dict(i)
                    {
                        return Err(pyerr(
                            "AttributeError",
                            format!(
                                "'{}' object has no attribute '{}'",
                                self.typename(&obj),
                                name
                            ),
                        ));
                    }
                    self.ns_set(attrs, name.into(), value);
                    return Ok(());
                }
                Object::Class(mut c) => {
                    if name == "__name__" {
                        if let Value::Str(text) = value {
                            c.name = text;
                            self.heap[i] = Some(Object::Class(c));
                            return Ok(());
                        }
                        return Err(pyerr("TypeError", "can only assign string to __name__"));
                    }
                    if name == "__qualname__" && !matches!(value, Value::Str(_)) {
                        return Err(pyerr("TypeError", "can only assign string to __qualname__"));
                    }
                    self.ns_set(c.attrs, name.into(), value);
                    return Ok(());
                }
                Object::Module { attrs, .. } => {
                    if matches!(
                        self.heap.get(i).and_then(|o| o.as_ref()),
                        Some(Object::BuiltinInstance { .. })
                    ) && !self.instance_allows_dict(i)
                    {
                        return Err(pyerr(
                            "AttributeError",
                            format!(
                                "'{}' object has no attribute '{}'",
                                self.typename(&obj),
                                name
                            ),
                        ));
                    }
                    self.ns_set(attrs, name.into(), value);
                    return Ok(());
                }
                _ => {}
            }
        }
        Err(pyerr(
            "AttributeError",
            format!("cannot set attribute '{}'", name),
        ))
    }
    fn delattr_default(&mut self, obj: Value, name: &str) -> PyResult<()> {
        if let Value::Obj(i) = obj {
            let attrs = match self.object(i)? {
                Object::Instance { attrs, .. } | Object::Module { attrs, .. } => Some(attrs),
                Object::Class(c) => Some(c.attrs),
                _ => None,
            };
            if let Some(a) = attrs {
                if self.ns_del(a, name) {
                    return Ok(());
                }
            }
        }
        Err(pyerr("AttributeError", name))
    }
    fn attribute_items(&mut self, obj: &Value) -> PyResult<Vec<(String, Value)>> {
        if let Value::Obj(i) = obj {
            let a = match self.object(*i)? {
                Object::Instance { attrs, .. } | Object::Module { attrs, .. } => attrs,
                Object::Class(c) => c.attrs,
                _ => *i,
            };
            return self.keyword_items(Value::Obj(a));
        }
        Err(pyerr("TypeError", "object has no attribute dictionary"))
    }
}

impl Runtime {
    fn bind_function(
        &mut self,
        function: &Function,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Frame> {
        let code_name = self.codes[function.code].name.clone();
        let code_locals = self.codes[function.code].locals.clone();
        let params = self.codes[function.code].params.clone();
        let ns = self.alloc(Object::Namespace(HashMap::new(), function.closure));
        self.scope_bindings.insert(ns, code_locals);

        let mut kw: Vec<(String, Value)> = Vec::new();
        for (k, v) in kwargs {
            if kw.iter().any(|(n, _)| n == &k) {
                return Err(pyerr(
                    "TypeError",
                    format!("multiple values for argument '{}'", k),
                ));
            }
            kw.push((k, v));
        }
        if args.len() > params.positional.len() && params.vararg.is_none() {
            return Err(pyerr(
                "TypeError",
                format!(
                    "{}() takes {} positional arguments but {} were given",
                    code_name,
                    params.positional.len(),
                    args.len()
                ),
            ));
        }
        for (j, n) in params.positional.iter().enumerate() {
            let v = if j < args.len() {
                if kw.iter().any(|(key, _)| key == n) && j >= params.posonly {
                    return Err(pyerr(
                        "TypeError",
                        format!("multiple values for argument '{}'", n),
                    ));
                }
                Some(args[j].clone())
            } else if j >= params.posonly {
                Self::take_keyword(&mut kw, n)
            } else {
                None
            };
            let v = if let Some(v) = v {
                v
            } else if j + function.defaults.len() >= params.positional.len() {
                function.defaults[j + function.defaults.len() - params.positional.len()].clone()
            } else {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "{}() missing required positional argument: '{}'",
                        code_name, n
                    ),
                ));
            };
            self.ns_set(ns, n.clone(), v)
        }
        if let Some(n) = &params.vararg {
            let rest = args[args.len().min(params.positional.len())..].to_vec();
            let v = self.obj_value(Object::Tuple(rest));
            self.ns_set(ns, n.clone(), v)
        }
        for n in &params.kwonly {
            let v = Self::take_keyword(&mut kw, n)
                .or_else(|| function.kwdefaults.get(n).cloned())
                .ok_or_else(|| {
                    pyerr(
                        "TypeError",
                        format!("missing keyword-only argument: '{}'", n),
                    )
                })?;
            self.ns_set(ns, n.clone(), v)
        }
        if let Some(n) = &params.kwarg {
            let v = self.obj_value(Object::Dict(
                kw.into_iter().map(|(k, v)| (Value::Str(k), v)).collect(),
            ));
            self.ns_set(ns, n.clone(), v)
        } else if let Some(n) = kw.first().map(|(n, _)| n) {
            return Err(pyerr(
                "TypeError",
                format!("{}() got an unexpected keyword argument '{}'", code_name, n),
            ));
        }
        let frame = Frame {
            code: function.code,
            pc: 0,
            locals: ns,
            temps: self.alloc(Object::Namespace(HashMap::new(), None)),
            globals: function.globals,
            closure: function.closure,
            stack: Vec::new(),
            handlers: Vec::new(),
            pending: Vec::new(),
            exception: None,
            exception_stack: Vec::new(),
            next_call: None,
            resume_value: None,
            injected_exception: None,
            finally_regions: Vec::new(),
        };
        Ok(frame)
    }
    fn prepare_direct_call(
        &mut self,
        fun: Value,
        mut args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Option<Frame>> {
        if let Value::Obj(i) = fun {
            match self.object(i)? {
                Object::Function(function) if !self.codes[function.code].is_generator => {
                    return Ok(Some(self.bind_function(&function, args, kwargs)?))
                }
                Object::Bound(inner, receiver) => {
                    args.insert(0, receiver);
                    return self.prepare_direct_call(inner, args, kwargs);
                }
                _ => {}
            }
        }
        Ok(None)
    }
}
