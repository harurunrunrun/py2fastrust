// Shared instruction contract: the Python and dynamic compilers emit these types.
#[derive(Clone, Debug, PartialEq)]
enum ScopeKind {
    Module,
    Function,
    Class,
    Comprehension,
    Annotation,
    TypeParameters,
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
    qualname: String,
    filename: String,
    kind: ScopeKind,
    locals: Vec<String>,
    comp_locals: Vec<String>,
    globals: Vec<String>,
    nonlocals: Vec<String>,
    frees: Vec<String>,
    params: Params,
    ops: Vec<Instr>,
    is_generator: bool,
    future_flags: u32,
    docstring: Option<String>,
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
    Complex(f64, f64),
    Str(String),
    Bytes(Vec<u8>),
}
#[derive(Clone, Debug)]
enum Op {
    Const(Const),
    Keyword(String),
    BeginComprehension(usize),
    EndComprehension,
    Load(String),
    Store(String),
    StoreCell(String),
    LoadCell(String),
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
    PrepareClass(usize),
    MakeFunction {
        code: usize,
        defaults: usize,
        kwdefaults: Vec<String>,
    },
    MakeTypeParam { name: String, kind: String },
    MakeTypeAlias { name: String },
    GenericBase,
    TypeUnpack,
    Return,
    Yield,
    Raise(usize),
    SetupExcept(usize),
    PopHandler,
    ClearException,
    LoadException,
    LoadExceptionType,
    LoadExceptionTraceback,
    SetupFinally(usize),
    EndFinally,
    MakeClass {
        name: String,
        code: usize,
        bases: usize,
        keywords: Vec<String>,
    },
    MakeClassEx { name: String, code: usize },
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
    SetupAnnotations,
    Match(MatchPattern),
    ExceptionMatch,
    BeginExceptStar,
    SplitExceptStar,
    RecordExceptStar(bool),
    EndExceptStar,
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
    MakeInterpolation { expression: Option<String>, conversion: i32, spec: bool },
    BuildTemplate(usize),
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
    Int(Ident<Int>),
    Float(Ident<f64>),
    Complex(Ident<Complex>),
    Str(Ident<String>),
    Bytes(Ident<Vec<u8>>),
    Obj(usize),
    Builtin(String),
    Type(String),
}
// Error metadata is cold. Keeping it boxed makes normal Result temporaries
// small, including Rust callbacks that re-enter the instruction executor.
#[derive(Clone, Debug)]
struct PyException(Box<PyExceptionData>);
impl std::ops::Deref for PyException {
    type Target=PyExceptionData;
    fn deref(&self)->&PyExceptionData{&self.0}
}
impl std::ops::DerefMut for PyException {
    fn deref_mut(&mut self)->&mut PyExceptionData{&mut self.0}
}
#[derive(Clone, Debug)]
struct PyExceptionData {
    class: Option<Value>,
    group: Option<Box<ExceptionGroupData>>,
    dict: Option<usize>,
    kind: String,
    message: String,
    args: Vec<Value>,
    args_tuple: Option<Value>,
    attributes: HashMap<String, Value>,
    value: Option<Value>,
    cause: Option<Value>,
    context: Option<Value>,
    suppress_context: bool,
    skip_trace: bool,
    trace: Vec<(String, usize, String)>,
}
type PyResult<T> = Result<T, PyException>;
fn standard_input_exception(error:StandardInputError)->PyException {
    match error {
        StandardInputError::Io(error)=>pyerr("OSError",error.to_string()),
        StandardInputError::Memory=>pyerr("MemoryError","cannot allocate input buffer"),
        StandardInputError::Decode{object,start,end,reason}=>codec_error(TextCodec::Utf8,Value::Bytes(object.into()),start,end,reason,true),
    }
}

fn pyerr(kind: &str, message: impl Into<String>) -> PyException {
    let message = message.into();
    PyException(Box::new(PyExceptionData {
        class: None,
        group: None,
        dict: None,
        kind: kind.into(),
        args: if message.is_empty() {
            Vec::new()
        } else {
            vec![Value::Str(message.clone().into())]
        },
        args_tuple: None,
        attributes: HashMap::new(),
        message,
        value: None,
        cause: None,
        context: None,
        suppress_context: false,
        skip_trace: false,
        trace: Vec::new(),
    }))
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
    name: Value,
    qualname: Value,
    module: Value,
    doc: Value,
    annotations: Value,
    type_params: Value,
    code: usize,
    globals: usize,
    builtins: Value,
    closure: Option<usize>,
    defaults: Vec<Value>,
    defaults_set: bool,
    kwdefaults: HashMap<String, Value>,
}
#[derive(Clone, Debug)]
struct Class {
    name: Ident<String>,
    name_value: Value,
    bases: Vec<Value>,
    attrs: usize,
    metaclass: Value,
    dict_allowed: bool,
    weakref_allowed: bool,
}
#[derive(Clone, Debug)]
struct CacheEntry {
    hashes: Vec<i64>,
    args: Vec<Value>,
    kwargs: KeywordArgs,
    value: Value,
}
#[derive(Clone, Debug)]
struct CacheReturn {
    owner: Value,
    entry: CacheEntry,
}
enum CachedLookup {
    Hit(Value),
    Miss { function: Value, entry: CacheEntry },
}
enum PreparedCall {
    Fallback,
    Value(Value),
    Frame(Frame),
}
#[derive(Clone, Debug)]
struct CachedFunction {
    revision: u64,
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
    Template(usize, usize),
    Associative(AssocIterator),
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
    FrozenSet {items:Vec<Value>,hashes:Vec<i64>,hash:Option<i64>,buckets:HashMap<i64,Vec<usize>>},
    ExceptStarState(Box<ExceptStarState>),
    Template { strings: usize, interpolations: usize },
    Interpolation { value: Value, expression: Value, conversion: Value, format_spec: Value },
    GenericAlias { origin: Value, args: Vec<Value>, args_tuple: usize, parameters: Option<usize>, typing: bool },
    TypeParameter(TypeParameter),
    TypeAlias { name: String, module: Value, params: Value, value: TypeLazy },
    TypeUnpack(Value),
    UnpackedAlias(Value),
    ParamSpecMarker { parameter: Value, kind: String },
    TypeEvaluator(Value),
    ForwardRef { arg: String, module: Value },
    TypeUnion { args: Vec<Value>, parameters: Option<usize> },
    DictView { owner: usize, kind: DictViewKind },
    MappingProxy { owner: usize },
    Slot {
        owner: Value,
        name: String,
        slot: usize,
    },
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
    Namespace(OrderedNamespace, Option<usize>),
    Function(Function),
    Class(Class),
    Instance {
        class: Value,
        attrs: usize,
    },
    Bound(Value, Value),
    Iterator(IteratorState),
    Generator(Box<Frame>),
    Module {
        name: String,
        attrs: usize,
    },
    Exception(PyException),
    Slice(Option<Int>, Option<Int>, Option<Int>),
    Cell(Option<Value>),
    ExecutionLocals(Value),
    Code(usize),
    Range(Ident<Int>, Ident<Int>, Ident<Int>),
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
    function: Option<Value>,
    generator_names: Option<usize>,
    code_handle: usize,
    code: usize,
    pc: usize,
    locals: usize,
    temps: usize,
    globals: usize,
    builtins: Value,
    closure: Option<usize>,
    stack: Vec<Value>,
    handlers: Vec<Handler>,
    pending: Vec<Pending>,
    exception: Option<PyException>,
    exception_stack: Vec<Option<PyException>>,
    inherited_exception: Option<PyException>,
    except_star: Vec<Value>,
    next_call: Option<Box<Frame>>,
    cache_returns: Vec<CacheReturn>,
    comprehensions: Vec<InlineComprehension>,
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
    annotation_namespaces: HashMap<usize, usize>,
    scope_cells: HashMap<usize, HashMap<String, Value>>,
    typing_alias_cache: Vec<TypingAliasCacheEntry>,
    template_metadata: HashMap<String, Value>,
    assoc_layouts: HashMap<usize, AssocLayout>,
    dictionary_hashes: HashMap<usize,Vec<Option<i64>>>,
    set_member_hashes: HashMap<usize,HashMap<u64,i64>>,
    frozen_reprs:std::collections::HashSet<usize>,
    keyword_intern_pool: HashMap<String,Ident<String>>,
    literal_pools: HashMap<usize, HashMap<LiteralKey, Value>>,
    code_objects: HashMap<usize,usize>,
    identity_builtins: HashMap<String, u64>,
    identity_types: HashMap<String, u64>,
    codes: Vec<Code>,
    heap: Vec<Option<Object>>,
    free: Vec<usize>,
    roots: Vec<Vec<Value>>,
    modules: HashMap<String, Value>,
    module_codes: HashMap<String, usize>,
    builtins: usize,
    globals: usize,
    output: OutputBuffer,
    input: StandardInput,
    recursion: usize,
    recursion_limit: usize,
    allocations: usize,
    scope_bindings: HashMap<usize, Vec<String>>,
    scope_comprehension_bindings: HashMap<usize,Vec<String>>,
    running_generators: Vec<usize>,
    scope_parents: HashMap<usize, usize>,
    gc_running: bool,
    gc_enabled: bool,
    finalized: std::collections::HashSet<usize>,
    instance_slots: HashMap<usize, HashMap<usize, Value>>,
    next_slot: usize,
    active_future_flags: u32,
    active_builtins: Value,
    handled_exception: Option<PyException>,
    collection_callers: Vec<usize>,
    collection_nullable_slots: std::collections::HashSet<usize>,
    ordered_collections: HashMap<usize,OrderedCollectionState>,
    collection_keepers: HashMap<usize,Value>,
}
impl Runtime {
    fn new_exception(&mut self, kind: &str, args: Vec<Value>) -> PyResult<PyException> {
        let mut error = pyerr(kind, "");
        error.args = args;
        error.message=self.exception_cached_message(&error)?;
        if kind == "StopIteration" {
            error.0.attributes.insert(
                "value".into(),
                error.0.args.first().cloned().unwrap_or(Value::None),
            );
        } else if kind == "SystemExit" {
            let code = match error.args.as_slice() {
                [] => Value::None,
                [value] => value.clone(),
                values => self.obj_value(Object::Tuple(values.to_vec())),
            };
            error.attributes.insert("code".into(), code);
        }
        Ok(error)
    }
    fn exception_message(&mut self, kind: &str, args: &[Value]) -> PyResult<String> {
        if let Some(message) = codec_exception_message(kind, args) {
            return Ok(message);
        }
        match args.len() {
            0 => Ok(String::new()),
            1 if kind == "KeyError" => self.repr(&args[0]),
            1 => self.str_value(&args[0]),
            _ => {
                let tuple = self.obj_value(Object::Tuple(args.to_vec()));
                self.repr(&tuple)
            }
        }
    }
    fn sync_exception(&mut self, error: &PyException) {
        if let Some(Value::Obj(index)) = error.value {
            if matches!(
                self.heap.get(index).and_then(Option::as_ref),
                Some(Object::Exception(_))
            ) {
                self.heap[index] = Some(Object::Exception(error.clone()));
            }
        }
    }
    fn exception_value(&mut self, error: &mut PyException) -> Value {
        if let Some(value) = &error.value {
            return value.clone();
        }
        self.exception_initialize_fields(error,false);
        let value = self.obj_value(Object::Exception(error.clone()));
        error.value = Some(value.clone());
        self.sync_exception(error);
        value
    }
    fn exception_roots(error: &PyException, roots: &mut Vec<Value>) {
        roots.extend(error.args.iter().cloned());
        roots.extend(error.args_tuple.iter().cloned());
        roots.extend(error.dict.iter().map(|index|Value::Obj(*index)));
        roots.extend(error.class.iter().cloned());
        if let Some(group)=&error.group {roots.extend([group.message.clone(),group.exceptions.clone(),group.original.clone()]);}
        roots.extend(error.attributes.values().cloned());
        roots.extend(error.value.iter().cloned());
        roots.extend(error.cause.iter().cloned());
        roots.extend(error.context.iter().cloned());
    }
    fn locals_snapshot(&mut self, frame: &Frame) -> PyResult<Value> {
        if !frame.comprehensions.is_empty() { return self.comprehension_locals(frame); }
        let code = self.codes[frame.code].clone();
        let mut names = code.params.positional;
        names.extend(code.params.kwonly);
        names.extend(code.params.vararg);
        names.extend(code.params.kwarg);
        names.extend(self.comprehension_local_names(frame.code));
        let mut frees = code.frees;
        frees.sort();
        names.extend(frees.clone());
        let root = self.roots.len();
        self.roots.push(Vec::new());
        let result = (|| {
            let mut seen = std::collections::HashSet::new();
            let mut entries = Vec::new();
            for name in names {
                if name.starts_with('$') || name.starts_with('\0') || !seen.insert(name.clone()) {
                    continue;
                }
                let value = if frees.contains(&name) {
                    match self.load(frame, &name) {
                        Ok(value) => Some(value),
                        Err(error)
                            if error.kind == "NameError" || error.kind == "UnboundLocalError" =>
                        {
                            None
                        }
                        Err(error) => return Err(error),
                    }
                } else {
                    self.mapping_get(frame.locals, &name)?
                };
                if let Some(value) = value {
                    self.roots[root].push(value.clone());
                    entries.push((Value::Str(self.intern_keyword(&name)), value));
                }
            }
            Ok(self.obj_value(Object::Dict(entries)))
        })();
        self.roots.truncate(root);
        result
    }
    fn system_exit_status(&mut self, error: &PyException) -> i32 {
        let value =
            error
                .attributes
                .get("code")
                .cloned()
                .unwrap_or_else(|| match error.args.as_slice() {
                    [] => Value::None,
                    [value] => value.clone(),
                    values => self.obj_value(Object::Tuple(values.to_vec())),
                });
        match value {
            Value::None => 0,
            Value::Bool(value) => {
                if value {
                    1
                } else {
                    0
                }
            }
            Value::Int(value) => value.to_i128().map(|n| n as i32).unwrap_or(-1),
            value => {
                let message = self
                    .str_value(&value)
                    .unwrap_or_else(|_| error.message.clone());
                eprintln!("{}", message);
                1
            }
        }
    }
    fn take_keyword(kw: &mut KeywordArgs, name: &str) -> Option<Value> {
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
            Some(Object::Instance { class, .. } | Object::BuiltinInstance { class, .. }) => {
                self.class_allows_dict(class)
            }
            _ => true,
        }
    }
    fn class_name(&self, class: &Value) -> String {
        match class {
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::Class(class)) => class.name.to_string(),
                _ => "object".into(),
            },
            Value::Builtin(name) | Value::Type(name) => name.clone(),
            _ => "object".into(),
        }
    }
    fn class_allows_dict(&self, class: &Value) -> bool {
        match class {
            Value::Obj(index) => {
                matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Class(class)) if class.dict_allowed)
            }
            Value::Builtin(name) if name == "super" => true,
            Value::Type(_) => true,
            _ => false,
        }
    }
    fn class_allows_weakref(&self, class: &Value) -> bool {
        match class {
            Value::Obj(index) => {
                matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Class(class)) if class.weakref_allowed)
            }
            Value::Builtin(name) if name == "set" => true,
            _ => false,
        }
    }
    fn slot_mangle(class: &str, name: &str) -> String {
        let class = class.trim_start_matches('_');
        if !class.is_empty()
            && name.starts_with("__")
            && !name.ends_with("__")
            && !name.contains('.')
        {
            format!("_{}{}", class, name)
        } else {
            name.into()
        }
    }
    fn solid_layout(&self, class: &Value) -> Option<Value> {
        for base in self.class_mro(class, 0)? {
            match &base {
                Value::Builtin(name)
                    if ["tuple", "list", "dict", "set", "str", "int", "complex", "frozenset"].contains(&name.as_str()) =>
                {
                    return Some(base)
                }
                Value::Obj(index) => {
                    if let Some(Object::Class(class)) =
                        self.heap.get(*index).and_then(Option::as_ref)
                    {
                        if let Some(Object::Dict(items)) =
                            self.heap.get(class.attrs).and_then(Option::as_ref)
                        {
                            if items.iter().any(|(_, value)| matches!(value, Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Slot { owner, name, .. }) if Self::same_type(owner, &base) && name != "__dict__" && name != "__weakref__"))) { return Some(base); }
                        }
                    }
                }
                _ => {}
            }
        }
        None
    }
    fn slot_access(
        &mut self,
        descriptor: Value,
        instance: Value,
        value: Option<Value>,
        delete: bool,
    ) -> PyResult<Value> {
        let nullable=matches!(&descriptor,Value::Obj(index)if self.collection_nullable_slots.contains(index));
        let (owner, name, slot) = match &descriptor {
            Value::Obj(index) => match self.object(*index)? {
                Object::Slot { owner, name, slot } => (owner, name, slot),
                _ => return Err(pyerr("TypeError", "not a slot descriptor")),
            },
            _ => return Err(pyerr("TypeError", "not a slot descriptor")),
        };
        let (index, class, attrs) = match &instance {
            Value::Obj(index) => match self.object(*index)? {
                Object::Instance { class, attrs }
                | Object::BuiltinInstance { class, attrs, .. } => (*index, class, attrs),
                Object::Exception(mut error) => {let attrs=self.exception_dict(&mut error);self.sync_exception(&error);(*index,error.class.clone().unwrap_or_else(||Value::Type(error.kind.clone())),attrs)},
                _ => return Err(pyerr("TypeError", "descriptor requires an instance")),
            },
            _ => return Err(pyerr("TypeError", "descriptor requires an instance")),
        };
        if !self.is_subclass(&class, &owner)? {
            return Err(pyerr(
                "TypeError",
                "descriptor does not apply to this object",
            ));
        }
        if name == "__dict__" {
            if delete {
                let replacement = self.alloc(Object::Dict(Vec::new()));
                match self.heap[index].as_mut().unwrap() {
                    Object::Instance { attrs, .. } | Object::BuiltinInstance { attrs, .. } => {
                        *attrs = replacement
                    }
                    Object::Exception(error) => error.dict=Some(replacement),
                    _ => {}
                }
                return Ok(Value::None);
            }
            if let Some(value) = value {
                let replacement = match value {
                    Value::Obj(index)
                        if matches!(
                            self.heap.get(index).and_then(Option::as_ref),
                            Some(Object::Dict(_) | Object::Namespace(..))
                        ) =>
                    {
                        index
                    }
                    _ => return Err(pyerr("TypeError", "__dict__ must be set to a dictionary")),
                };
                match self.heap[index].as_mut().unwrap() {
                    Object::Instance { attrs, .. } | Object::BuiltinInstance { attrs, .. } => {
                        *attrs = replacement
                    }
                    Object::Exception(error) => error.dict=Some(replacement),
                    _ => {}
                }
                return Ok(Value::None);
            }
            return Ok(Value::Obj(attrs));
        }
        if name == "__weakref__" {
            return if delete || value.is_some() {
                Err(pyerr(
                    "AttributeError",
                    "attribute '__weakref__' is not writable",
                ))
            } else {
                Ok(Value::None)
            };
        }
        if let Some(value) = value {
            self.instance_slots
                .entry(index)
                .or_default()
                .insert(slot, value);
            return Ok(Value::None);
        }
        if delete && nullable {
            if let Some(slots)=self.instance_slots.get_mut(&index){slots.remove(&slot);}
            return Ok(Value::None);
        }
        if delete {
            return if self
                .instance_slots
                .get_mut(&index)
                .and_then(|slots| slots.remove(&slot))
                .is_some()
            {
                Ok(Value::None)
            } else {
                Err(pyerr("AttributeError", name))
            };
        }
        self.instance_slots
            .get(&index)
            .and_then(|slots| slots.get(&slot))
            .cloned()
            .or_else(||nullable.then_some(Value::None))
            .ok_or_else(|| pyerr("AttributeError", name))
    }
    fn rich_comparison(&mut self, op: &str, a: &Value, b: &Value) -> PyResult<Option<Value>> {
        self.operand_rich_comparison(op,a,b)
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
        if op=="==" || op=="!=" {if let Some(result)=self.typing_equal(a,b) {return result.map(|equal|Value::Bool(if op=="=="{equal}else{!equal}));}}
        if let Some(result)=self.generic_compare_value(op,a,b) {return result;}
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
                Some(Object::Exception(error)) => error.class.clone(),
                _ => None,
            }
        } else {
            None
        }
    }
    fn special_method(&mut self, v: Value, name: &str) -> PyResult<Value> {
        if let Some(class) = self.object_class(&v) {
            if let Some(method) = self.slot_override(&class, name, 0) {
                return self.bind_descriptor(method, Some(v), class);
            }
            let native=self.slot_definition(&class,name,0);
            let native_bridge=matches!(&native,Some(SlotDefinition::Native(value))if ["__bool__","__contains__","__reversed__"].contains(&name)||(name=="__str__"&&matches!(native_attribute_parts(value),Some((_,"str",_)))));
            if self.native_payload(&v).is_some()&&native_bridge {
                return Ok(self.obj_value(Object::Bound(Value::Builtin(format!("implicit_native:{name}")),v)));
            }
            if let Some(payload) = self.native_payload(&v) {
                if ["__repr__","__str__"].contains(&name) && self.frozen_owner(&payload).is_some_and(|(_,frozen)|frozen) {if let Some(result)=self.frozen_attr(v.clone(),name){return result;}}
                let payload = if matches!(name, "__int__" | "__index__" | "__complex__" | "__pos__" | "conjugate") {
                    payload.fresh_primitive()
                } else { payload };
                return self.getattr_default(payload, name);
            }
            return Err(pyerr("AttributeError", name));
        }
        self.getattr_default(v, name)
    }
    fn missing_special_method(&self,value:&Value,name:&str,error:&PyException)->bool{
        self.exception_has_native_class(error,"AttributeError")
            && self.object_class(value).and_then(|class|self.slot_override(&class,name,0)).is_none()
    }
    fn getattr(&mut self, v: Value, name: &str) -> PyResult<Value> {
        if let Some(class) = self.object_class(&v) {
            if let Some(method) = self.slot_override(&class, "__getattribute__", 0) {
                let bound = self.obj_value(Object::Bound(method, v.clone()));
                match self.call(bound, vec![Value::Str(name.into())], Vec::new(), None) {
                    Ok(value) => return Ok(value),
                    Err(e) if self.exception_has_native_class(&e, "AttributeError") => {
                        if let Some(method) = self.slot_override(&class, "__getattr__", 0) {
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
            if let Some(method) = self.slot_override(&class, "__setattr__", 0) {
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
            if let Some(method) = self.slot_override(&class, "__delattr__", 0) {
                let bound = self.obj_value(Object::Bound(method, obj));
                self.call(bound, vec![Value::Str(name.into())], Vec::new(), None)?;
                return Ok(());
            }
        }
        self.delattr_default(obj, name)
    }
    fn stream_call(&mut self, name: &str, args: Vec<Value>, kwargs:KeywordArgs, binary: bool) -> PyResult<Value> {
        let (target, method) = name.split_once(':').unwrap_or(("stdin", name));
        if !kwargs.is_empty(){return Err(pyerr("TypeError",format!("{method}() takes no keyword arguments")));}
        if ["read","readline","readlines"].contains(&method) {
            if args.len()>1{return Err(pyerr("TypeError",format!("{method}() takes at most 1 argument")));}
        } else if args.len()!=usize::from(method=="write") {
            return Err(pyerr("TypeError",format!("invalid arguments for {method}()")));
        }
        match method {
            "isatty" => return Ok(Value::Bool(false)),
            "readable" => return Ok(Value::Bool(target == "stdin")),
            "writable" => return Ok(Value::Bool(target != "stdin")),
            "flush" => {
                if target=="stdout" {self.flush_stdout()?;}
                else if target=="stderr" {std::io::stderr().flush().map_err(|error|pyerr("OSError",error.to_string()))?;}
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
                        Value::Bytes(xs) => (xs.inner().clone(), xs.len()),
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
                return Ok(Value::Int(Int::from_i128(count as i128).into()));
            }
            _ => {}
        }
        if target != "stdin" {
            return Err(pyerr("OSError", "not readable"));
        }
        let count=if let Some(value)=args.first() {
            if matches!(value,Value::None) && method!="readline" {None}else{self.stream_size(value)?}
        } else {None};
        if method == "readlines" {
            let mut lines = Vec::new();
            let mut total = 0;
            loop {
                let line = self.stream_call(&format!("{}:readline", target), Vec::new(),Vec::new(), binary)?;
                let size = match &line {
                    Value::Str(line) => line.chars().count(),
                    Value::Bytes(line) => line.len(),
                    _ => 0,
                };
                if size == 0 {
                    break;
                }
                total += size;
                lines.push(line);
                if count.is_some_and(|count|count>0 && total>count) {
                    break;
                }
            }
            return Ok(self.obj_value(Object::List(lines)));
        }
        if method!="read" && method!="readline" {return Err(pyerr("AttributeError",method));}
        let value=if binary {
            Value::Bytes(self.input.read_binary(count,method=="readline").map_err(standard_input_exception)?.into())
        } else {
            let mut text=String::new();
            self.input.read_text_into(&mut text,count,method=="readline").map_err(standard_input_exception)?;
            Value::Str(text.into())
        };
        Ok(value)
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
        if self.codes[code]
            .frees
            .iter()
            .any(|name| name == "__class__")
        {
            return true;
        }
        self.codes[code].ops.iter().any(|ins| match &ins.op {
            Op::Load(n) if n == "__class__" || n == "super" => true,
            Op::MakeFunction { code, .. } => self.code_needs_class_cell(*code, depth + 1),
            _ => false,
        })
    }
    fn code_needs_class_dict(&self,code:usize,depth:usize)->bool {
        if depth>100{return false;}
        self.codes[code].frees.iter().any(|name|name=="__classdict__") || self.codes[code].ops.iter().any(|instruction|matches!(&instruction.op,Op::MakeFunction{code,..} if self.code_needs_class_dict(*code,depth+1)))
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
    fn cached_entry_roots(entry:&CacheEntry,out:&mut Vec<Value>){
        out.extend(entry.args.iter().cloned());
        out.extend(entry.kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        out.push(entry.value.clone());
    }
    fn cached_entry_equal(&mut self,cache:&CachedFunction,a:&CacheEntry,b:&CacheEntry)->PyResult<bool>{
        let mut roots=Vec::new();Self::cached_entry_roots(a,&mut roots);Self::cached_entry_roots(b,&mut roots);
        self.view_rooted(roots,|runtime,_|runtime.cached_entry_equal_inner(cache,a,b))
    }
    fn cached_entry_equal_inner(&mut self, cache: &CachedFunction, a: &CacheEntry, b: &CacheEntry) -> PyResult<bool> {
        if a.args.len()!=b.args.len() || a.kwargs.len()!=b.kwargs.len() || a.hashes!=b.hashes {return Ok(false);}
        for (a,b) in a.args.iter().zip(&b.args) {
            if (cache.typed && self.typename(a)!=self.typename(b)) || !self.identical_or_equal(a,b)? {return Ok(false);}
        }
        for ((an,a),(bn,b)) in a.kwargs.iter().zip(&b.kwargs) {
            if !self.identical_or_equal(&an.original,&bn.original)? || (cache.typed && self.typename(a)!=self.typename(b)) || !self.identical_or_equal(a,b)? {return Ok(false);}
        }
        Ok(true)
    }
    fn cached_revision(&self,i:usize)->Option<u64> {
        match self.heap.get(i).and_then(Option::as_ref) {Some(Object::Cached(cache))=>Some(cache.revision),_=>None}
    }
    fn cached_lookup(&mut self, i: usize, mut cache: CachedFunction, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<CachedLookup> {
        let mut hashes=Vec::new();
        if cache.maxsize!=Some(0){
            for value in &args{hashes.push(self.frozen_member_hash(value)?);}
            for(name,value)in &kwargs{hashes.push(self.frozen_member_hash(&name.original)?);hashes.push(self.frozen_member_hash(value)?);}
        }
        // Hash callbacks can clear or re-enter this wrapper. Read its current
        // state after the one-time key construction instead of reviving a copy.
        let mut cache=match self.object(i)?{Object::Cached(cache)=>cache,_=>unreachable!()};
        let entry=CacheEntry{args,kwargs,hashes,value:Value::None};
        'retry: loop {
            if cache.maxsize!=Some(0) {
                for j in 0..cache.entries.len() {
                    let equal=self.cached_entry_equal(&cache,&cache.entries[j],&entry)?;
                    if self.cached_revision(i)!=Some(cache.revision) {
                        cache=match self.object(i)? {Object::Cached(cache)=>cache,_=>unreachable!()};
                        continue 'retry;
                    }
                    if equal {
                        let mut current=match self.object(i)? {Object::Cached(cache)=>cache,_=>unreachable!()};
                        let found=current.entries.remove(j);
                        let value=found.value.clone();
                        current.entries.push(found);
                        current.hits+=1;
                        current.revision=current.revision.wrapping_add(1);
                        self.heap[i]=Some(Object::Cached(current));
                        return Ok(CachedLookup::Hit(value));
                    }
                }
            }
            let mut current=match self.object(i)? {Object::Cached(cache)=>cache,_=>unreachable!()};
            current.misses+=1;
            let function=current.function.clone();
            self.heap[i]=Some(Object::Cached(current));
            return Ok(CachedLookup::Miss{function,entry});
        }
    }
    fn cached_finish(&mut self,i:usize,entry:CacheEntry,value:Value)->PyResult<Value>{
        let mut roots=vec![Value::Obj(i),value.clone()];Self::cached_entry_roots(&entry,&mut roots);
        self.view_rooted(roots,|runtime,_|runtime.cached_finish_inner(i,entry,value))
    }
    fn cached_finish_inner(&mut self, i: usize, mut entry: CacheEntry, value: Value) -> PyResult<Value> {
        // Re-read the wrapper after the body: cache_clear() and recursive calls
        // may have replaced its entries and reset its statistics. Equality can
        // itself re-enter Python, so restart if the entries change during it.
        entry.value=value.clone();
        'retry: loop {
            let cache=match self.object(i)? {Object::Cached(cache)=>cache,_=>return Ok(value)};
            if cache.maxsize==Some(0) {return Ok(value);}
            let mut existing=None;
            for j in 0..cache.entries.len() {
                let equal=self.cached_entry_equal(&cache,&cache.entries[j],&entry)?;
                if self.cached_revision(i)!=Some(cache.revision) {continue 'retry;}
                if equal {existing=Some(j);break;}
            }
            if existing.is_none(){
                if let Some(max)=cache.maxsize{
                    // Bounded wrappers first check for reentrant insertion,
                    // then insert a new link. Dictionary insertion compares
                    // colliding keys again after an optional oldest eviction.
                    let start=usize::from(cache.entries.len()>=max);
                    for stored in cache.entries.iter().skip(start){
                        self.cached_entry_equal(&cache,stored,&entry)?;
                        if self.cached_revision(i)!=Some(cache.revision){continue 'retry;}
                    }
                }
            }
            let mut current=match self.object(i)? {Object::Cached(cache)=>cache,_=>return Ok(value)};
            if let Some(j)=existing {
                if current.maxsize.is_none() {current.entries[j].value=value.clone();}
            } else {
                current.entries.push(entry);
                if let Some(max)=current.maxsize {if current.entries.len()>max {current.entries.remove(0);}}
            }
            current.revision=current.revision.wrapping_add(1);
            self.heap[i]=Some(Object::Cached(current));
            return Ok(value);
        }
    }
    fn cached_call(&mut self, i:usize, cache:CachedFunction,args:Vec<Value>,kwargs:KeywordArgs,caller:Option<&Frame>) -> PyResult<Value> {
        match self.cached_lookup(i,cache,args,kwargs)? {
            CachedLookup::Hit(value)=>Ok(value),
            CachedLookup::Miss{function,entry}=>{
                let value=self.call(function,entry.args.clone(),entry.kwargs.clone(),caller)?;
                self.cached_finish(i,entry,value)
            }
        }
    }
    fn mapping_get(&mut self, index: usize, name: &str) -> PyResult<Option<Value>> {
        match self.heap.get(index).and_then(Option::as_ref) {
            Some(Object::Namespace(..)) => return Ok(self.ns_get(index, name)),
            Some(Object::Dict(_)) => return self.global_name_get(index, name),
            _ => (),
        }
        let mapping = self.execution_locals_value(index);
        let key = Value::Str(self.intern_keyword(name));
        match self.getitem(mapping, key) {
            Ok(value) => Ok(Some(value)),
            Err(error) if self.exception_has_native_class(&error, "KeyError") => Ok(None),
            Err(error) => Err(error),
        }
    }
    fn mapping_set(&mut self, index: usize, name: String, value: Value) -> PyResult<()> {
        match self.heap.get(index).and_then(Option::as_ref) {
            Some(Object::Namespace(..)) => { self.ns_set(index, name, value); return Ok(()); }
            Some(Object::Dict(_)) => return self.global_name_set(index, name, value),
            _ => (),
        }
        let mapping = self.execution_locals_value(index);
        let key = Value::Str(self.intern_keyword(&name));
        self.setitem(mapping, key, value)
    }
    fn mapping_del(&mut self, index: usize, name: &str) -> PyResult<bool> {
        match self.heap.get(index).and_then(Option::as_ref) {
            Some(Object::Namespace(..)) => return Ok(self.ns_del(index, name)),
            Some(Object::Dict(_)) => return self.global_name_del(index, name),
            _ => (),
        }
        let mapping = self.execution_locals_value(index);
        let key = Value::Str(self.intern_keyword(name));
        match self.delitem(mapping, key) {
            Ok(()) => Ok(true),
            Err(error) if self.exception_has_native_class(&error, "KeyError") => Ok(false),
            Err(error) => Err(error),
        }
    }
    fn new(codes: Vec<Code>, modules: Vec<(String, usize)>) -> Self {
        let mut rt = Self {
            annotation_namespaces: HashMap::new(),
            scope_cells: HashMap::new(),
            typing_alias_cache: Vec::new(),
            template_metadata: HashMap::new(),
            assoc_layouts: HashMap::new(),
            dictionary_hashes: HashMap::new(),
            set_member_hashes: HashMap::new(),
            frozen_reprs:std::collections::HashSet::new(),
            keyword_intern_pool: HashMap::new(),
            literal_pools: HashMap::new(),
            code_objects: HashMap::new(),
            identity_builtins: HashMap::new(),
            identity_types: HashMap::new(),
            codes,
            heap: Vec::new(),
            free: Vec::new(),
            roots: Vec::new(),
            modules: HashMap::new(),
            module_codes: modules.into_iter().collect(),
            builtins: 0,
            globals: 0,
            output: OutputBuffer::new(),
            input: StandardInput::new(),
            recursion: 0,
            recursion_limit: 1000,
            allocations: 0,
            scope_bindings: HashMap::new(),
            scope_comprehension_bindings: HashMap::new(),
            running_generators: Vec::new(),
            scope_parents: HashMap::new(),
            gc_running: false,
            gc_enabled: true,
            finalized: std::collections::HashSet::new(),
            instance_slots: HashMap::new(),
            next_slot: 0,
            active_future_flags: 0,
            active_builtins: Value::None,
            handled_exception: None,
            collection_callers: Vec::new(),
            collection_nullable_slots: std::collections::HashSet::new(),
            ordered_collections: HashMap::new(),
            collection_keepers: HashMap::new(),
        };
        rt.builtins = rt.alloc(Object::Dict(Vec::new()));
        rt.active_builtins = Value::Obj(rt.builtins);
        rt.globals = rt.alloc(Object::Dict(Vec::new()));
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
            "complex",
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
            "memoryview",
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
            "_py2fastrust_dict_payload",
            "_py2fastrust_nullable_slot",
            "_py2fastrust_namedtuple_module",
            "_py2fastrust_ordered",
            "__build_class__",
        ] {
            rt.ns_set(rt.builtins, name.into(), Value::Builtin(name.into()));
        }
        for name in [
            "BaseException",
            "BaseExceptionGroup",
            "ExceptionGroup",
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
            "IndentationError",
            "TabError",
            "TypeError",
            "UnboundLocalError",
            "ValueError",
            "UnicodeError",
            "UnicodeEncodeError",
            "UnicodeDecodeError",
            "UnicodeTranslateError",
            "ZeroDivisionError",
            "GeneratorExit",
            "SystemExit",
            "KeyboardInterrupt",
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
        rt.ns_set(rt.builtins, "__name__".into(), Value::Str("builtins".into()));
        let builtin_module = rt.obj_value(Object::Module { name: "builtins".into(), attrs: rt.builtins });
        rt.modules.insert("builtins".into(), builtin_module.clone());
        rt.ns_set(rt.globals, "__name__".into(), Value::Str("__main__".into()));
        rt.ns_set(rt.globals, "__builtins__".into(), builtin_module);
        let main = rt.alloc(Object::Module {
            name: "__main__".into(),
            attrs: rt.globals,
        });
        rt.modules.insert("__main__".into(), Value::Obj(main));
        rt
    }
    fn alloc(&mut self, obj: Object) -> usize {
        self.allocations += 1;
        let index=if let Some(i)=self.free.pop() {
            self.assoc_layouts.remove(&i);
            self.set_member_hashes.remove(&i);
            self.dictionary_hashes.remove(&i);
            self.annotation_namespaces.remove(&i);
            self.scope_cells.remove(&i);
            self.scope_bindings.remove(&i);
            self.scope_comprehension_bindings.remove(&i);
            self.scope_parents.remove(&i);
            self.ordered_collections.remove(&i);
            self.collection_keepers.remove(&i);
            self.collection_nullable_slots.remove(&i);
            self.finalized.remove(&i);
            self.heap[i]=Some(obj);
            i
        } else {
            let i=self.heap.len();self.heap.push(Some(obj));i
        };
        self.assoc_seed(index);
        index
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
            Some(Object::BuiltinInstance {payload:Value::Obj(index),..})=>self.ns_get(*index,name),
            Some(Object::Namespace(m, _)) => m.get(name).cloned(),
            Some(Object::Dict(m)) => m.iter().find_map(|(k, v)| match k {
                Value::Str(s) if s == name => Some(v.clone()),
                _ => None,
            }),
            _ => None,
        }
    }
    fn ns_set(&mut self, i: usize, name: String, v: Value) {
        let interned = self.intern_keyword(&name);
        if let Some(Object::BuiltinInstance{payload:Value::Obj(index),..})=self.heap.get(i).and_then(Option::as_ref){let index=*index;self.ns_set(index,name,v);return;}
        let mut inserted=None;
        if let Some(Some(o))=self.heap.get_mut(i) {
            match o {
                Object::Namespace(m,_)=>{
                    let new=!m.contains_key(&name);m.insert_ident(interned.clone(),v);
                    if new {inserted=m.ident_items().into_iter().find(|(key,_)|matches!(key,Value::Str(key)if key==&name)).map(|(key,_)|key);}
                },
                Object::Dict(m)=>{
                    if let Some((_,old))=m.iter_mut().find(|(key,_)|matches!(key,Value::Str(key)if key==&name)) {*old=v;}
                    else {let key=Value::Str(interned);inserted=Some(key.clone());m.push((key,v));}
                },
                _=>{},
            }
        }
        if let Some(key)=inserted {self.assoc_inserted(i,key);}
    }
    fn ns_del(&mut self,i:usize,name:&str)->bool{
        if let Some(Object::BuiltinInstance{payload:Value::Obj(index),..})=self.heap.get(i).and_then(Option::as_ref){let index=*index;return self.ns_del(index,name);}
        let mut removed=None;let mut removed_position=None;
        match self.heap.get_mut(i).and_then(Option::as_mut){
            Some(Object::Namespace(mapping,_))=>{
                if let Some(position)=mapping.order.iter().position(|key|key==name){
                    removed=mapping.ident_items().get(position).map(|(key,_)|key.clone());removed_position=Some(position);mapping.remove(name);
                }
            },
            Some(Object::Dict(items))=>{
                if let Some(position)=items.iter().position(|(key,_)|matches!(key,Value::Str(key)if key==name)){
                    removed=Some(items.remove(position).0);removed_position=Some(position);
                }
            },_=>{},
        }
        if let Some(position)=removed_position{self.dictionary_remove_entry_hash(i,position);}
        if removed.is_some(){if let Some(position)=removed_position{self.assoc_dictionary_removed(i,position);}true}else{false}
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
        if !f.comprehensions.is_empty() { return self.comprehension_load(f,name); }
        let global = self.codes[f.code].globals.iter().any(|s| s == name);
        let islocal = (self.codes[f.code].kind == ScopeKind::Function
            || self.codes[f.code].kind == ScopeKind::Comprehension
            || self.codes[f.code].kind == ScopeKind::TypeParameters)
            && self.codes[f.code].locals.iter().any(|s| s == name)
            && !self.codes[f.code].frees.iter().chain(&self.codes[f.code].nonlocals).any(|s|s==name);
        if global {
            if let Some(value) = self.mapping_get(f.globals, name)? { return Ok(value); }
            return self.builtin_lookup(f.builtins.clone(), name)?
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
        let closure = f.closure;
        let code = &self.codes[f.code];
        if matches!(code.kind,ScopeKind::Annotation|ScopeKind::TypeParameters) && code.frees.iter().any(|free|free=="__classdict__") {
            let mut namespace=closure;
            while let Some(index)=namespace {
                if self.scope_parents.contains_key(&index) {
                    let namespace=self.annotation_namespaces.get(&index).copied().unwrap_or(index);
                    if let Some(value)=self.mapping_get(namespace,name)? {return Ok(value);}
                    break;
                }
                namespace=self.ns_parent(index);
            }
        }
        let code = &self.codes[f.code];
        let class_local = code.kind == ScopeKind::Class
            && code.locals.iter().any(|local| local == name)
            && !code.nonlocals.iter().any(|nonlocal| nonlocal == name);
        let use_closure = !class_local
            && (code.frees.iter().any(|free| free == name)
                || code.nonlocals.iter().any(|free| free == name)
                || name == "__class__"
                    && code.kind != ScopeKind::Class
                    && self.code_needs_class_cell(f.code, 0));
        if let Some(p) = self.find_nonlocal(if use_closure { closure } else { None }, name) {
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
        let global_value = if matches!(self.codes[f.code].kind, ScopeKind::Function | ScopeKind::Comprehension | ScopeKind::Annotation | ScopeKind::TypeParameters) {
            self.mapping_get(f.globals, name)?
        } else {
            self.global_name_get(f.globals, name)?
        };
        if let Some(value) = global_value { return Ok(value); }
        self.builtin_lookup(f.builtins.clone(), name)?
            .ok_or_else(|| pyerr("NameError", format!("name '{}' is not defined", name)))
    }
    fn store(&mut self, f: &Frame, name: String, v: Value) -> PyResult<()> {
        if name.starts_with('$') || name.starts_with('\0') {
            self.ns_set(f.temps, name, v);
            return Ok(());
        }
        if !f.comprehensions.is_empty() { return self.comprehension_store(f,name,v); }
        if self.codes[f.code].globals.contains(&name) {
            self.global_name_set(f.globals, name, v)?;
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
            function: None,
            generator_names: None,
            code_handle: self.code_object_index(0),
            code: 0,
            pc: 0,
            locals: self.globals,
            temps: self.alloc(Object::Namespace(OrderedNamespace::new(), None)),
            globals: self.globals,
            builtins: Value::Obj(self.builtins),
            closure: None,
            stack: Vec::new(),
            handlers: Vec::new(),
            pending: Vec::new(),
            exception: None,
            exception_stack: Vec::new(),
                inherited_exception: None,
                except_star: Vec::new(),
            next_call: None,
            cache_returns: Vec::new(),
            comprehensions: Vec::new(),
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
    fn report_exception(&mut self, e: &PyException) {
        let root=self.roots.len();let mut values=Vec::new();Self::exception_roots(e,&mut values);self.roots.push(values);
        self.report_exception_chain(e, &mut std::collections::HashSet::new());
        self.roots.truncate(root);
    }
    fn report_exception_chain(&mut self, e: &PyException, seen: &mut std::collections::HashSet<usize>) {
        if let Some(Value::Obj(index)) = e.value {
            if !seen.insert(index) {
                return;
            }
        }
        let linked = if let Some(cause) = &e.cause {
            Some((cause, true))
        } else if !e.suppress_context {
            e.context.as_ref().map(|context| (context, false))
        } else {
            None
        };
        if let Some((Value::Obj(index), direct)) = linked {
            if !seen.contains(index) {
                if let Some(Object::Exception(previous)) =
                    self.heap.get(*index).and_then(Option::as_ref).cloned()
                {
                    self.report_exception_chain(&previous, seen);
                    eprintln!(
                        "\n{}\n",
                        if direct {
                            "The above exception was the direct cause of the following exception:"
                        } else {
                            "During handling of the above exception, another exception occurred:"
                        }
                    );
                }
            }
        }
        if !e.trace.is_empty() {
            eprintln!("Traceback (most recent call last):");
            for (file, line, name) in e.trace.iter().rev() {
                eprintln!("  File {:?}, line {}, in {}", file, line, name);
            }
        }
        let message=if let Some(value)=&e.value{self.str_value(value)}else{self.exception_object_message(e)}.unwrap_or_else(|_|"<exception str() failed>".into());
        if message.is_empty() {
            eprintln!("{}", self.exception_header_name(e));
        } else {
            eprintln!("{}: {}", self.exception_header_name(e), message);
        }
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
            Const::Int(s) => Value::Int(Int::parse(&s, 0).map_err(int_error)?.into()),
            Const::Float(v) => Value::Float(v.into()),
            Const::Complex(real,imag) => Value::Complex(Complex::new(real,imag).into()),
            Const::Str(v) => Value::Str(v.into()),
            Const::Bytes(v) => Value::Bytes(v.into()),
        })
    }
    fn frame_roots(frame: &Frame, out: &mut Vec<Value>) {
        out.push(Value::Obj(frame.code_handle));
        out.extend(frame.function.iter().cloned());
        if let Some(names)=frame.generator_names {out.push(Value::Obj(names));}
        out.extend(frame.stack.iter().cloned());
        out.extend(frame.comprehensions.iter().map(|scope|Value::Obj(scope.namespace)));
        for pending in &frame.cache_returns {
            out.push(pending.owner.clone());
            out.extend(pending.entry.args.iter().cloned());
            out.extend(pending.entry.kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        }
        out.extend(frame.resume_value.iter().cloned());
        if let Some(e) = &frame.injected_exception {
            Self::exception_roots(e, out);
        }
        if let Some(error)=&frame.inherited_exception{Self::exception_roots(error,out);}
        out.extend(frame.except_star.iter().cloned());
        out.push(Value::Obj(frame.locals));
        out.push(Value::Obj(frame.temps));
        out.push(Value::Obj(frame.globals));
        out.push(frame.builtins.clone());
        if let Some(i) = frame.closure {
            out.push(Value::Obj(i))
        }
        for p in &frame.pending {
            match p {
                Pending::Return(v) => out.push(v.clone()),
                Pending::Raise(e) => {
                    Self::exception_roots(e, out);
                }
                _ => {}
            }
        }
        for e in frame
            .exception
            .iter()
            .chain(frame.exception_stack.iter().filter_map(|e| e.as_ref()))
        {
            Self::exception_roots(e, out);
        }
    }
    fn execute(&mut self, mut f: Frame) -> PyResult<(FrameExit, Frame)> {
        if self.recursion >= self.recursion_limit {
            return Err(pyerr("RecursionError", "maximum recursion depth exceeded"));
        }
        let previous_exception=self.handled_exception.clone();
        f.inherited_exception=previous_exception.clone();
        let previous_flags=self.active_future_flags;
        let previous_builtins=self.active_builtins.clone();
        let collection_depth=self.collection_callers.len();
        self.collection_callers.push(f.globals);
        let base_depth = self.recursion;
        let root = self.roots.len();
        self.roots.push(Vec::new());
        self.recursion += 1;
        let mut frames: Vec<Frame> = Vec::new();
        let result = (|| loop {
            self.active_future_flags=self.codes[f.code].future_flags;
            self.active_builtins=f.builtins.clone();
            self.handled_exception=f.exception.clone().or_else(||f.inherited_exception.clone());
            let mut roots = Vec::new();
            Self::frame_roots(&f, &mut roots);
            let current = root + frames.len();
            self.roots.truncate(current + 1);
            if self.roots.len() == current {
                self.roots.push(roots)
            } else {
                self.roots[current] = roots;
            }
            if self.gc_enabled && self.allocations > 10000 {
                self.collect();
                self.allocations = 0;
            }
            let delegated = matches!(
                self.codes[f.code]
                    .ops
                    .get(f.pc)
                    .map(|instruction| &instruction.op),
                Some(Op::YieldFrom)
            );
            let result = if f.injected_exception.is_some() && !delegated {
                Err(f.injected_exception.take().unwrap())
            } else if f.pc >= self.codes[f.code].ops.len() {
                Ok(Some(FrameExit::Return(Value::None)))
            } else {
                let ins = self.codes[f.code].ops[f.pc].clone();
                f.pc += 1;
                self.step(&mut f, ins.op)
            };
            let result=match result {
                Ok(Some(FrameExit::Return(mut value)))=>{
                    let mut failure=None;
                    for pending in std::mem::take(&mut f.cache_returns) {
                        let owner=match pending.owner {Value::Obj(owner)=>owner,_=>unreachable!()};
                        match self.cached_finish(owner,pending.entry,value.clone()) {
                            Ok(result)=>value=result,
                            Err(mut error)=>{error.skip_trace=true;failure=Some(error);break;}
                        }
                    }
                    match failure {Some(error)=>Err(error),None=>Ok(Some(FrameExit::Return(value)))}
                }
                other=>other,
            };
            match result {
                Ok(Some(FrameExit::Return(v))) => {
                    if let Some(mut parent) = frames.pop() {
                        self.collection_callers.pop();
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
                        let inherited=f.exception.clone().or_else(||f.inherited_exception.clone());
                        self.collection_callers.push(child.globals);
                        frames.push(f);
                        self.recursion += 1;
                        f = *child;
                        f.inherited_exception=inherited;
                    }
                }
                Err(mut e) => loop {
                    self.active_future_flags=self.codes[f.code].future_flags;
                    self.active_builtins=f.builtins.clone();
                    if e.context.is_none() {
                        if let Some(mut previous) = f.exception.clone().or_else(||f.inherited_exception.clone()) {
                            let previous = self.exception_value(&mut previous);
                            if !matches!((&e.value, &previous), (Some(Value::Obj(a)), Value::Obj(b)) if a == b)
                            {
                                e.context = Some(previous);
                            }
                        }
                    }
                    self.exception_value(&mut e);
                    self.sync_exception(&e);
                    if !e.skip_trace {
                        let line = self.codes[f.code]
                            .ops
                            .get(f.pc.saturating_sub(1))
                            .map(|instruction| instruction.line)
                            .unwrap_or(1);
                        let name = if self.codes[f.code].kind == ScopeKind::Module {
                            "<module>".into()
                        } else {
                            self.codes[f.code].name.clone()
                        };
                        e.trace
                            .push((self.codes[f.code].filename.clone(), line, name));
                        e.attributes.remove("__traceback__");
                    }
                    e.skip_trace = false;
                    self.sync_exception(&e);
                    self.exception_star_unwind(&mut f);
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
                    if let Some(parent) = frames.pop() {
                        self.collection_callers.pop();
                        self.recursion -= 1;
                        f = parent;
                    } else {
                        return Err(e);
                    }
                },
            }
        })();
        self.roots.truncate(root);
        self.collection_callers.truncate(collection_depth);
        self.active_future_flags=previous_flags;
        self.active_builtins=previous_builtins;
        self.handled_exception=previous_exception;
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
        if f.pc==1 {
            if let Some(value)=self.try_native_leaf(f){return Ok(Some(FrameExit::Return(value)));}
        }
        match op {
            Op::SetupAnnotations => {
                if self.mapping_get(f.locals, "__annotations__")?.is_none() {
                    let annotations=self.obj_value(Object::Dict(Vec::new()));
                    self.mapping_set(f.locals,"__annotations__".into(),annotations)?;
                }
            }
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
            Op::BeginComprehension(code)=>self.begin_comprehension(f,code),
            Op::EndComprehension=>self.end_comprehension(f)?,
            Op::Keyword(name)=>{let key=self.intern_keyword(&name);f.stack.push(Value::Str(key));}
            Op::Const(c) => {
                let v = self.code_constant(f.code,c)?;
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
            Op::StoreCell(name) => {
                let value=Self::pop(f)?;
                self.scope_cells.entry(f.locals).or_default().insert(name,value);
            }
            Op::LoadCell(name) => {
                let mut namespace=Some(f.locals);let mut value=None;
                while let Some(index)=namespace {
                    if let Some(found)=self.scope_cells.get(&index).and_then(|cells|cells.get(&name)){value=Some(found.clone());break;}
                    namespace=if index==f.locals{f.closure}else{self.ns_parent(index)};
                }
                f.stack.push(value.ok_or_else(||pyerr("NameError",format!("unbound annotation cell '{}'",name)))?);
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
                let global=self.codes[f.code].globals.contains(&n);
                let deleted=if global{self.global_name_del(ns,&n)}else{self.mapping_del(ns,&n)};
                // DELETE_NAME replaces mapping errors; DELETE_GLOBAL keeps
                // them even when its enclosing code is a class body.
                let deleted=if !global && matches!(self.codes[f.code].kind,ScopeKind::Module|ScopeKind::Class){deleted.unwrap_or(false)}else{deleted?};
                if !deleted {
                    if !global && !self.codes[f.code].nonlocals.contains(&n)
                        && !matches!(self.codes[f.code].kind,ScopeKind::Module|ScopeKind::Class)
                        && self.codes[f.code].locals.contains(&n) {
                        return Err(pyerr("UnboundLocalError",format!("cannot access local variable '{}' where it is not associated with a value",n)));
                    }
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
            Op::BeginExceptStar => {let state=self.exception_star_begin(f)?;f.stack.push(state);}
            Op::SplitExceptStar => {let condition=Self::pop(f)?;let state=Self::pop(f)?;let matched=self.exception_star_split(f,state,condition)?;f.stack.push(Value::Bool(matched));}
            Op::RecordExceptStar(raised) => {let state=Self::pop(f)?;self.exception_star_record(f,state,raised)?;}
            Op::EndExceptStar => {let state=Self::pop(f)?;self.exception_star_end(f,state)?;}
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
                    Op::BuildSet(_)=>{let values=self.obj_value(Object::List(values));let result=self.set_constructor_value(vec![values],Vec::new())?;f.stack.push(result);return Ok(None);}
                    _ => Object::List(values),
                };
                let v = self.obj_value(obj);
                f.stack.push(v)
            }
            Op::BuildDict(n) => {
                let v = Self::pop_many(f, n * 2)?;
                let d=self.view_rooted(v.clone(),|runtime,root|{
                    let d=runtime.obj_value(Object::Dict(Vec::new()));runtime.roots[root].push(d.clone());
                    for p in v.chunks(2){runtime.setitem(d.clone(),p[0].clone(),p[1].clone())?;}
                    Ok(d)
                })?;
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
                let kwargs: KeywordArgs = keywords
                    .into_iter().map(|name|self.static_keyword(name))
                    .collect::<Vec<_>>().into_iter().zip(vals[pos..].iter().cloned())
                    .collect();
                let args = vals[..pos].to_vec();
                match self.prepare_direct_call(callable.clone(),args.clone(),kwargs.clone())? {
                    PreparedCall::Frame(child)=>f.next_call=Some(Box::new(child)),
                    PreparedCall::Value(value)=>f.stack.push(value),
                    PreparedCall::Fallback=>{let value=self.call(callable,args,kwargs,Some(f))?;f.stack.push(value);}
                }
            }
            Op::CallEx { kwargs } => {
                let kw = if kwargs {
                    let v = Self::pop(f)?;
                    self.keyword_items(v)?
                } else {
                    Vec::new()
                };
                let arg=Self::pop(f)?;let fun=Self::pop(f)?;
                let mut roots=vec![arg.clone(),fun.clone()];
                roots.extend(kw.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
                self.view_rooted(roots,|runtime,_|{
                    let args=runtime.to_vec(arg)?;
                    match runtime.prepare_direct_call(fun.clone(),args.clone(),kw.clone())?{
                        PreparedCall::Frame(child)=>f.next_call=Some(Box::new(child)),
                        PreparedCall::Value(value)=>f.stack.push(value),
                        PreparedCall::Fallback=>{let value=runtime.call(fun,args,kw,Some(f))?;f.stack.push(value);}
                    }
                    Ok(())
                })?;
            }
            Op::PrepareClass(code) => {
                let builder=self.builtin_lookup(f.builtins.clone(),"__build_class__")?.ok_or_else(||pyerr("NameError","__build_class__ not found"))?;
                let function=self.view_rooted(vec![builder.clone()],|runtime,_|runtime.make_function_value(f,code,Vec::new(),Vec::new(),Vec::new()))?;
                f.stack.push(builder);f.stack.push(function);
            }
            Op::MakeFunction {code,defaults,kwdefaults} => {
                let kwvals=Self::pop_many(f,kwdefaults.len())?;
                let defs=Self::pop_many(f,defaults)?;
                let function=self.make_function_value(f,code,defs,kwdefaults,kwvals)?;
                f.stack.push(function);
            }
            Op::MakeTypeParam { name, kind } => {
                let default = Self::pop(f)?;
                let constraints = Self::pop(f)?;
                let bound = Self::pop(f)?;
                let value = self.make_type_parameter(name, kind, bound, constraints, default)?;
                f.stack.push(value);
            }
            Op::MakeTypeAlias { name } => {
                let thunk = Self::pop(f)?;
                let params = Self::pop(f)?;
                let module = self.ns_get(f.globals, "__name__").unwrap_or(Value::None);
                let value = self.obj_value(Object::TypeAlias {
                    name, module, params, value: TypeLazy::lazy(thunk),
                });
                f.stack.push(value);
            }
            Op::GenericBase => {
                let params = Self::pop(f)?;
                let mut values=Vec::new();for parameter in self.to_vec(params)? {
                    values.push(if self.type_parameter_kind(&parameter)==Some("typevartuple"){self.obj_value(Object::TypeUnpack(parameter))}else{parameter});
                }
                let params=self.obj_value(Object::Tuple(values));
                f.stack.push(self.typing_generic_alias(Value::Builtin("typing.Generic".into()), params)?);
            }
            Op::TypeUnpack => {
                let inner=Self::pop(f)?;
                let root=self.roots.len();self.roots.push(vec![inner.clone()]);
                let result=(||{
                    let iterator=self.iter(inner)?;self.roots[root].push(iterator.clone());
                    let unpack=self.next(iterator.clone())?.ok_or_else(||pyerr("ValueError","not enough values to unpack (expected 1, got 0)"))?;
                    self.roots[root].push(unpack.clone());
                    if self.next(iterator)?.is_some(){return Err(pyerr("ValueError","too many values to unpack (expected 1)"));}
                    f.stack.push(unpack);Ok(())
                })();
                self.roots.truncate(root);result?;
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
                let result = if let Some(mut error) = f.injected_exception.take() {
                    if self.exception_has_native_class(&error, "GeneratorExit") {
                        match self.getattr(it.clone(), "close") {
                            Ok(method) => {
                                self.call(method, Vec::new(), Vec::new(), None)?;
                            }
                            Err(missing) if self.exception_has_native_class(&missing, "AttributeError") => {}
                            Err(error) => return Err(error),
                        }
                        return Err(error);
                    }
                    match self.getattr(it.clone(), "throw") {
                        Ok(method) => {
                            let exception = self.exception_value(&mut error);
                            self.call(method, vec![exception], Vec::new(), None)
                        }
                        Err(missing) if self.exception_has_native_class(&missing, "AttributeError") => return Err(error),
                        Err(error) => return Err(error),
                    }
                } else {
                    let sent = f.resume_value.take().unwrap_or(Value::None);
                    if matches!(sent, Value::None) {
                        self.iterator_next(it)
                    } else {
                        let send = self.getattr(it, "send")?;
                        self.call(send, vec![sent], Vec::new(), None)
                    }
                };
                match result {
                    Ok(value) => {
                        f.pc -= 1;
                        return Ok(Some(FrameExit::Yield(value)));
                    }
                    Err(error) if self.exception_has_native_class(&error, "StopIteration") => {
                        Self::pop(f)?;
                        f.stack.push(Self::stop_value(&error));
                    }
                    Err(error) => return Err(error),
                }
            }
            Op::Raise(n) => {
                if n == 0 {
                    let error = f
                        .exception
                        .clone().or_else(||f.inherited_exception.clone())
                        .ok_or_else(|| pyerr("RuntimeError", "No active exception to reraise"))?;
                    let mut error = if let Some(value) = error.value.clone() {
                        self.as_exception(value)?
                    } else {
                        error
                    };
                    error.skip_trace = true;
                    return Err(error);
                }
                let cause = if n == 2 { Some(Self::pop(f)?) } else { None };
                let v = Self::pop(f)?;
                let mut error = self.as_exception(v)?;
                if let Some(mut previous) = f.exception.clone().or_else(||f.inherited_exception.clone()) {
                    let previous = self.exception_value(&mut previous);
                    if !matches!((&error.value, &previous), (Some(Value::Obj(a)), Value::Obj(b)) if a == b)
                    {
                        error.context = Some(previous);
                    }
                }
                if let Some(cause) = cause {
                    error.cause = if matches!(cause, Value::None) {
                        None
                    } else {
                        let mut cause = self.as_exception(cause)?;
                        Some(self.exception_value(&mut cause))
                    };
                    error.suppress_context = true;
                }
                self.sync_exception(&error);
                return Err(error);
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
                let mut e = f
                    .exception
                    .clone()
                    .ok_or_else(|| pyerr("RuntimeError", "no active exception"))?;
                let v = self.exception_value(&mut e);
                f.exception = Some(e);
                f.stack.push(v)
            }
            Op::LoadExceptionType => {
                let error=f.exception.as_ref().ok_or_else(||pyerr("RuntimeError","no active exception"))?;
                f.stack.push(error.class.clone().unwrap_or_else(||Value::Type(error.kind.clone())));
            }
            Op::LoadExceptionTraceback => {
                let mut error=f.exception.clone().ok_or_else(||pyerr("RuntimeError","no active exception"))?;
                let trace=self.exception_native_traceback(&mut error);
                f.exception=Some(error);
                f.stack.push(trace);
            }
            Op::EndFinally => {
                f.finally_regions.pop();
                if let Some(p) = f.pending.pop() {
                    match p {
                        Pending::Normal => {}
                        Pending::Raise(mut e) => {
                            f.exception = f.exception_stack.pop().flatten();
                            e.skip_trace = true;
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
                let mut kw=Vec::new();for(name,value)in keywords.into_iter().zip(kv){kw.push((self.static_keyword(name),value));}
                let function=Self::pop(f)?;let builder=Self::pop(f)?;
                let mut args=vec![function,Value::Str(name.into())];args.extend(bases);
                let cls=self.call(builder,args,kw,Some(f))?;
                f.stack.push(cls)
            }
            Op::MakeClassEx { name, code } => {
                let keywords=Self::pop(f)?;
                let bases=Self::pop(f)?;
                let function=Self::pop(f)?;let builder=Self::pop(f)?;
                let root=self.roots.len();
                self.roots.push(vec![bases.clone(),keywords.clone(),function.clone(),builder.clone()]);
                let result=(||{
                    let bases=self.to_vec(bases)?;
                    let keywords=self.keyword_items(keywords)?;
                    let mut args=vec![function,Value::Str(name.into())];args.extend(bases);
                    self.call(builder,args,keywords,Some(f))
                })();
                self.roots.truncate(root);
                f.stack.push(result?);
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
            Op::Import {module,names,level} => {
                f.stack.push(self.import_statement(f,&module,&names,level)?);
            }
            Op::ImportFrom(name) => {
                let module=f.stack.last().cloned().ok_or_else(||pyerr("RuntimeError","missing module"))?;
                if name=="*" {self.import_star(f,module)?;}
                else {f.stack.push(self.import_from(module,&name)?);}
            }
            Op::FormatValue { conversion, spec } => {
                let specification = if spec { Some(Self::pop(f)?) } else { None };
                let value = Self::pop(f)?;
                let value = match conversion {
                    114 => Value::Str(self.repr(&value)?.into()),
                    97 => Value::Str(text_ascii_escape(&self.repr(&value)?).into()),
                    115 => Value::Str(self.str_value(&value)?.into()),
                    _ => value,
                };
                let specification = match specification {
                    Some(value) => self.str_value(&value)?,
                    None => String::new(),
                };
                let result = self.format_value(value, &specification)?;
                f.stack.push(Value::Str(result.into()))
            }
            Op::BuildString(n) => {
                let vs = Self::pop_many(f, n)?;
                let mut s = String::new();
                for v in vs {
                    s.push_str(&self.str_value(&v)?)
                }
                f.stack.push(Value::Str(s.into()))
            }
            Op::MakeInterpolation { expression, conversion, spec } => {
                let format_spec=if spec {Self::pop(f)?}else{self.code_constant(f.code,Const::Str(String::new()))?};
                let value=Self::pop(f)?;
                let expression=match expression {Some(text)=>self.code_constant(f.code,Const::Str(text))?,None=>Value::None};
                let conversion=match conversion {97|114|115=>self.code_constant(f.code,Const::Str(char::from_u32(conversion as u32).unwrap().to_string()))?,_=>Value::None};
                let value=self.make_interpolation(value,expression,conversion,format_spec);
                f.stack.push(value);
            }
            Op::BuildTemplate(count) => {
                let parts=Self::pop_many(f,count)?;
                let value=self.template_build(parts)?;f.stack.push(value);
            }
        }
        Ok(None)
    }
}

impl Runtime {
    fn import_module(&mut self, name: &str) -> PyResult<Value> {
        if let Some(v) = self.modules.get(name) {
            return Ok(v.clone());
        }
        if name.contains('.') {
            let parent = name.rsplit_once('.').unwrap().0;
            self.import_module(parent)?;
            // Initializing the package can import this child before we resume.
            if let Some(module)=self.modules.get(name){return Ok(module.clone());}
        }
        let attrs = self.alloc(Object::Dict(Vec::new()));
        let module = self.obj_value(Object::Module {
            name: name.into(),
            attrs,
        });
        self.ns_set(attrs, "__name__".into(), Value::Str(name.into()));
        self.ns_set(attrs, "__builtins__".into(), Value::Obj(self.builtins));
        let package=self.module_codes.get(name).is_some_and(|index|std::path::Path::new(&self.codes[*index].filename).file_name().is_some_and(|name|name=="__init__.py")) || name=="string";
        self.ns_set(attrs,"__package__".into(),Value::Str(if package{name}else{name.rsplit_once('.').map(|p|p.0).unwrap_or("")}.into()));
        if package {let path=self.obj_value(Object::List(Vec::new()));self.ns_set(attrs,"__path__".into(),path);}
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
                "types" => &["GenericAlias"],
                "string" => &[],
                "string.templatelib" => &["Template","Interpolation","convert"],
                "typing" => &["TypeVar", "ParamSpec", "TypeVarTuple", "TypeAliasType", "Generic", "Unpack", "Union", "ForwardRef", "ParamSpecArgs", "ParamSpecKwargs", "get_args", "get_origin"],
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
                    "length_hint",
                ],
                "collections" => &["deque", "Counter", "defaultdict", "namedtuple"],
                "sys" => &["setrecursionlimit", "getrecursionlimit", "exit", "exception", "exc_info"],
                "gc" => &["collect", "enable", "disable", "isenabled"],
                "time" => &["time", "perf_counter", "monotonic"],
                "builtins" => &[],
                _ => &[],
            }
        };
        if functions.is_empty() && name != "builtins" && name != "string" && !self.module_codes.contains_key(name) {
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
        if name=="string.templatelib" {
            for kind in ["Template","Interpolation"] {self.ns_set(attrs,kind.into(),Value::Builtin(format!("string.templatelib.{}",kind)));}
        }
        if name=="types" {
            self.ns_set(attrs,"GenericAlias".into(),Value::Builtin("GenericAlias".into()));
            self.ns_set(attrs,"UnionType".into(),Value::Builtin("typing.Union".into()));
        }
        if name=="typing" {
            for name in ["TypeVar","ParamSpec","TypeVarTuple","TypeAliasType","Generic","Unpack","Union","ForwardRef","ParamSpecArgs","ParamSpecKwargs"] {self.ns_set(attrs,name.into(),Value::Builtin(format!("typing.{}",name)));}
            self.ns_set(attrs,"NoDefault".into(),Value::Builtin("typing.NoDefault".into()));
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
                self.ns_set(attrs, n.into(), Value::Float(x.into()))
            }
        }
        if name == "builtins" {
            let entries = self.keyword_items(Value::Obj(self.builtins))?;
            for (n, v) in entries {
                self.ns_set(attrs, n.spelling, v)
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
            let mut values = vec![Value::Str(self.codes[0].filename.clone().into())];
            values.extend(std::env::args().skip(1).map(|value| Value::Str(value.into())));
            let argv = self.obj_value(Object::List(values));
            self.ns_set(attrs, "argv".into(), argv);
            self.ns_set(
                attrs,
                "maxsize".into(),
                Value::Int(Int::from_i128(i64::MAX as i128).into()),
            );
            self.ns_set(
                attrs,
                "version".into(),
                Value::Str("3.14 (py2fastrust)".into()),
            );
            let dict = self.obj_value(Object::Dict(
                self.modules
                    .iter()
                    .map(|(n, v)| (Value::Str(n.clone().into()), v.clone()))
                    .collect(),
            ));
            self.ns_set(attrs, "modules".into(), dict);
        }
        if let Some(code) = self.module_codes.get(name).copied() {
            let builtins=self.capture_builtins(attrs,self.active_builtins.clone())?;
            let frame = Frame {
                function: None,
            generator_names: None,
                code_handle: self.code_object_index(code),
                code,
                pc: 0,
                locals: attrs,
                temps: self.alloc(Object::Namespace(OrderedNamespace::new(), None)),
                globals: attrs,
                builtins,
                closure: None,
                stack: Vec::new(),
                handlers: Vec::new(),
                pending: Vec::new(),
                exception: None,
                exception_stack: Vec::new(),
                inherited_exception: None,
                except_star: Vec::new(),
                next_call: None,
            cache_returns: Vec::new(),
            comprehensions: Vec::new(),
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
        kwargs: KeywordArgs,
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
            "typing" => self.typing_module_call(name,args,kwargs),
            "stream" | "streambuffer" => self.stream_call(name, args, kwargs, module == "streambuffer"),
            "sys" => match name {
                "setrecursionlimit" => {
                    self.recursion_limit = self
                        .as_int(&arg(0)?)?
                        .to_usize()
                        .ok_or_else(|| pyerr("ValueError", "recursion limit must be positive"))?;
                    Ok(Value::None)
                }
                "exception" | "exc_info" => {
                    if !args.is_empty() || !kwargs.is_empty(){return Err(pyerr("TypeError",format!("sys.{}() takes no arguments",name)));}
                    let value=if let Some(mut error)=self.handled_exception.clone(){self.exception_value(&mut error)}else{Value::None};
                    if name=="exception"{Ok(value)}else if matches!(value,Value::None){Ok(self.obj_value(Object::Tuple(vec![Value::None;3])))}else{let class=self.exception_actual_class(&value).unwrap_or(Value::None);let mut error=self.exception_data(&value).ok_or_else(||pyerr("RuntimeError","invalid handled exception"))?;let trace=self.exception_native_traceback(&mut error);Ok(self.obj_value(Object::Tuple(vec![class,value,trace])))}
                }
                "getrecursionlimit" => Ok(Value::Int(Int::from_i128(self.recursion_limit as i128).into())),
                "exit" => {
                    if args.len() > 1 || !kwargs.is_empty() {
                        return Err(pyerr("TypeError", "sys.exit() takes at most 1 argument"));
                    }
                    Err(self.new_exception("SystemExit", args)?)
                }
                _ => Err(pyerr("NotImplementedError", fullname)),
            },
            "gc" => {
                if name == "collect" {
                    let count = self.collect();
                    Ok(Value::Int(Int::from_i128(count as i128).into()))
                } else if name == "isenabled" {
                    Ok(Value::Bool(self.gc_enabled))
                } else {
                    self.gc_enabled = name == "enable";
                    Ok(Value::None)
                }
            }
            "time" => {
                let d = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default();
                Ok(Value::Float(d.as_secs_f64().into()))
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
                Ok(Value::Int(Int::from_i128(lo as i128).into()))
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
                                .unwrap_or(Value::Int(Int::from_i128(0).into()));
                            let n = self.binary("+", old, Value::Int(Int::from_i128(1).into()))?;
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
                                let previous=self.keyword_items(Value::Obj(keywords))?;
                                kw=self.keyword_merge(previous,kw)?;
                                function = base;
                            }
                        }
                    }
                    if matches!(stored.last(),Some(Value::Builtin(n))if n=="functools.Placeholder")
                    {
                        return Err(pyerr("TypeError", "trailing Placeholders are not allowed"));
                    }
                    let keyword_dictionary=self.dictionary_from_keywords(kw)?;
                    let Value::Obj(keywords)=keyword_dictionary else{unreachable!()};
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
                    revision: 0,
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
                    revision: 0,
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
                        .unwrap_or(Value::Int(Int::from_i128(128).into()));
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
                    revision: 0,
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
                if name=="length_hint" {return self.assoc_length_hint(args,kwargs);}
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
        let mut code_seen=std::collections::HashSet::new();
        let mut pending = vec![Value::Obj(self.builtins), Value::Obj(self.globals)];
        pending.push(self.active_builtins.clone());
        pending.extend(self.literal_pools.values().flat_map(|pool|pool.values().cloned()));
        pending.extend(self.modules.values().cloned());
        pending.extend(self.template_metadata.values().cloned());
        for entry in &self.typing_alias_cache {pending.extend([entry.owner.clone(),entry.key.clone(),entry.value.clone()]);}
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
            if let Some(state)=self.ordered_collections.get(&i){pending.extend(state.order.iter().map(|(key,_)|key.clone()));}
            if let Some(keeper)=self.collection_keepers.get(&i){pending.push(keeper.clone());}
            if let Some(slots) = self.instance_slots.get(&i) {
                pending.extend(slots.values().cloned());
            }
            if let Some(parent) = self.scope_parents.get(&i) {
                pending.push(Value::Obj(*parent));
            }
            if let Some(namespace)=self.annotation_namespaces.get(&i){pending.push(Value::Obj(*namespace));}
            if let Some(cells)=self.scope_cells.get(&i){pending.extend(cells.values().cloned());}
            let obj = match self.heap[i].as_ref() {
                Some(o) => o,
                None => continue,
            };
            match obj {
                Object::Template { strings, interpolations } => pending.extend([Value::Obj(*strings),Value::Obj(*interpolations)]),
                Object::Interpolation { value, expression, conversion, format_spec } => pending.extend([value.clone(),expression.clone(),conversion.clone(),format_spec.clone()]),
                Object::GenericAlias { origin, args, args_tuple, parameters, .. } => {
                    pending.push(origin.clone());pending.extend(args.iter().cloned());
                    pending.push(Value::Obj(*args_tuple));pending.extend(parameters.iter().map(|index|Value::Obj(*index)));
                }
                Object::TypeParameter(parameter) => {
                    pending.push(parameter.module.clone());pending.push(Value::Obj(parameter.attrs));
                    for lazy in [&parameter.bound, &parameter.constraints, &parameter.default] {
                        pending.extend(lazy.value.iter().cloned());pending.extend(lazy.thunk.iter().cloned());
                    }
                }
                Object::TypeAlias { module, params, value, .. } => {
                    pending.extend([module.clone(), params.clone()]);
                    pending.extend(value.value.iter().cloned());pending.extend(value.thunk.iter().cloned());
                }
                Object::TypeUnpack(value) | Object::UnpackedAlias(value) | Object::TypeEvaluator(value) => pending.push(value.clone()),
                Object::ParamSpecMarker { parameter, .. } => pending.push(parameter.clone()),
                Object::ForwardRef { module, .. } => pending.push(module.clone()),
                Object::TypeUnion { args, parameters } => {pending.extend(args.iter().cloned());pending.extend(parameters.iter().map(|index|Value::Obj(*index)));}
                Object::DictView { owner, .. } | Object::MappingProxy { owner } => pending.push(Value::Obj(*owner)),
                Object::Slot { owner, .. } => pending.push(owner.clone()),
                Object::List(v) | Object::Tuple(v) | Object::Set(v) | Object::FrozenSet{items:v,..} => {
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
                    self.code_roots(f.code,&mut code_seen,&mut pending);
                    pending.extend([f.name.clone(),f.qualname.clone()]);
                    pending.push(Value::Obj(f.attrs));
                    pending.extend(f.annotate.iter().cloned());
                    pending.extend([
                        f.module.clone(),
                        f.doc.clone(),
                        f.annotations.clone(),
                        f.type_params.clone(),
                    ]);
                    pending.push(Value::Obj(f.globals));
                    pending.push(f.builtins.clone());
                    if let Some(i) = f.closure {
                        pending.push(Value::Obj(i))
                    }
                    pending.extend(f.defaults.iter().cloned());
                    pending.extend(f.kwdefaults.values().cloned())
                }
                Object::Class(c) => {
                    pending.push(c.name_value.clone());
                    pending.push(Value::Obj(c.attrs));
                    pending.extend(c.bases.iter().cloned());
                    pending.push(c.metaclass.clone())
                }
                Object::Instance { class, attrs } => {
                    pending.push(class.clone());
                    pending.push(Value::Obj(*attrs))
                }
                Object::BuiltinInstance { class, attrs, payload } => {
                    pending.push(class.clone());
                    pending.push(Value::Obj(*attrs));
                    pending.push(payload.clone());
                }
                Object::Bound(a, b) => {
                    pending.push(a.clone());
                    pending.push(b.clone())
                }
                Object::Module { attrs, .. } => pending.push(Value::Obj(*attrs)),
                Object::Exception(e) => {
                    Self::exception_roots(e, &mut pending);
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
                        pending.extend(e.kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
                        pending.push(e.value.clone())
                    }
                }
                Object::Record { fields, .. } => {
                    pending.extend(fields.iter().map(|(_, v)| v.clone()))
                }
                Object::ExceptStarState(state) => state.roots(&mut pending),
                Object::ExecutionLocals(value)=>pending.push(value.clone()),
                Object::Cell(v) => pending.extend(v.iter().cloned()),
                Object::Static(v) | Object::ClassMethod(v) => pending.push(v.clone()),
                Object::Property { get, set, del } => {
                    pending.push(get.clone());
                    pending.extend(set.iter().cloned());
                    pending.extend(del.iter().cloned())
                }
                Object::Generator(f) => Self::frame_roots(f, &mut pending),
                Object::Code(code)=>self.code_roots(*code,&mut code_seen,&mut pending),
                Object::Iterator(it) => match it {
                    IteratorState::Template(owner,_) => pending.push(Value::Obj(*owner)),
                    IteratorState::Associative(state) => {if let Some(owner)=state.owner {pending.push(Value::Obj(owner));}if let Some(keeper)=&state.keeper{pending.push(keeper.clone());}},
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
                    if self.slot_override(&class, "__del__", 0).is_some() {
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
                if let Some(Object::Code(code))=&self.heap[i]{self.code_objects.remove(code);}
                self.heap[i] = None;
                self.scope_bindings.remove(&i);
            self.scope_comprehension_bindings.remove(&i);
                self.scope_parents.remove(&i);
                self.ordered_collections.remove(&i);
                self.collection_keepers.remove(&i);
                self.collection_nullable_slots.remove(&i);
                self.finalized.remove(&i);
                self.instance_slots.remove(&i);
                self.assoc_layouts.remove(&i);
                self.set_member_hashes.remove(&i);
            self.dictionary_hashes.remove(&i);
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
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        if self.frozen_owner(&receiver).is_some(){if let Some(result)=self.frozen_method(receiver.clone(),name,args.clone(),kwargs.clone()){return result;}}
        if matches!(&receiver,Value::Complex(_)){return self.complex_method(receiver,name,args,kwargs).unwrap();}
        if self.is_exception_value(&receiver){if let Some(result)=self.exception_group_method(receiver.clone(),name,args.clone(),kwargs.clone()){return result;}}
        if self.is_template_value(&receiver){if let Some(result)=self.template_method(receiver.clone(),name,args.clone(),kwargs.clone()){return result;}}
        if self.is_typing_value(&receiver){if let Some(result)=self.typing_method(receiver.clone(),name,args.clone(),kwargs.clone()){return result;}}
        if let Some(result)=self.dictview_method(receiver.clone(),name,args.clone(),kwargs.clone()) {return result.map(|value|self.collection_inherit_keeper(value,&receiver));}
        if let Some(result)=self.generic_method(receiver.clone(),name,args.clone(),kwargs.clone()) {return result;}
        if name=="__class_getitem__" && (matches!(&receiver,Value::Builtin(name)if ["list","dict","tuple","set","frozenset","type"].contains(&name.as_str())) || matches!(&receiver,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))))) {
            if args.len()!=1 || !kwargs.is_empty() {return Err(pyerr("TypeError","__class_getitem__() takes exactly one argument"));}
            if self.typing_class_uses_typing(&receiver) {
                return self.typing_class_subscript(receiver,args[0].clone());
            }
            return self.generic_alias(receiver,args[0].clone());
        }
        if let Value::Obj(index) = &receiver {
            if let Object::Range(start, stop, step) = self.object(*index)? {
                if name == "__contains__" {
                    let value = args
                        .first()
                        .cloned()
                        .ok_or_else(|| pyerr("TypeError", "missing value"))?;
                    return Ok(Value::Bool(self.range_contains(start.into_inner(), stop.into_inner(), step.into_inner(), value)?));
                }
                if name == "__reversed__" {
                    let (start, stop, step) = range_reversed(&start, &stop, &step);
                    return Ok(
                        self.obj_value(Object::Iterator(IteratorState::Range(start, stop, step)))
                    );
                }
            }
        }
        if let Some(payload) = self.native_payload(&receiver) {
            if name=="copy" && matches!(&payload,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Dict(_)))) {return self.dictionary_copy(receiver);}
            if matches!(name,"__int__" | "__index__" | "__complex__" | "__pos__" | "conjugate") && matches!(payload,Value::Int(_)) {
                return self.method(name,payload.fresh_primitive(),args,kwargs);
            }
            let result=self.method(name,payload,args,kwargs)?;
            return Ok(self.collection_keep(result,receiver));
        }
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
            return self.iterator_next(receiver);
        }
        if name == "__len__" {
            return self.builtin("len", vec![receiver], Vec::new(), None);
        }
        if name == "__format__" {
            let spec = match args.first() {
                Some(Value::Str(spec)) => spec,
                _ => return Err(pyerr("TypeError", "format specifier must be a string")),
            };
            return Ok(Value::Str(self.format_value(receiver, spec)?.into()));
        }
        if name == "__getitem__" {
            return self.getitem(receiver, arg(0)?);
        }
        if name == "__setitem__" {
            if args.len()!=2||!kwargs.is_empty(){return Err(pyerr("TypeError","__setitem__ expected two arguments"));}
            self.setitem(receiver,args[0].clone(),args[1].clone())?;return Ok(Value::None);
        }
        if name == "__delitem__" {
            if args.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError","__delitem__ expected one argument"));}
            self.delitem(receiver,args[0].clone())?;return Ok(Value::None);
        }
        if name == "__contains__" {
            let values = self.to_vec(receiver)?;
            return Ok(Value::Bool(self.contains_vec(&values, &arg(0)?)?));
        }
        if let Value::Int(n) = &receiver {
            return match name {
                "bit_length" => Ok(Value::Int(Int::from_i128(n.bit_length() as i128).into())),
                "bit_count" => Ok(Value::Int(Int::from_i128(n.bit_count() as i128).into())),
                "__index__" | "__int__" | "conjugate" => Ok(receiver),
                _ => Err(pyerr("AttributeError", name)),
            };
        }
        if let Value::Bytes(b) = &receiver {
            if let Some(result) = self.bytes_method(b.to_vec(), name, args.clone(), kwargs.clone()) {
                return result;
            }
            match name {
                "decode" => {
                    return self.codec_decode(receiver, args, kwargs);
                }
                "hex" => return Ok(Value::Str(b.iter().map(|x| format!("{:02x}", x)).collect())),
                _ => {}
            }
        }
        if let Value::Str(s) = receiver.clone() {
            if let Some(result)=self.keyword_str_protocol(receiver.clone(),name,args.clone(),kwargs.clone()){return result;}
            let s=s.into_inner();
            if let Some(result) = self.text_method(s.to_string(), name, args.clone(), kwargs.clone()) {
                return result;
            }
            let strarg = |i: usize| match args.get(i) {
                Some(Value::Str(s)) => Ok(s.inner().clone()),
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
                            s.split(&*sep).map(String::from).collect()
                        } else if name == "rsplit" {
                            let mut p: Vec<_> = s
                                .rsplitn(limit as usize + 1, &*sep)
                                .map(String::from)
                                .collect();
                            p.reverse();
                            p
                        } else {
                            s.splitn(limit as usize + 1, &*sep)
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
                        self.obj_value(Object::List(parts.into_iter().map(|value| Value::Str(value.into())).collect()))
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
                        s.replace(&*a, &b)
                    } else {
                        s.replacen(&*a, &b, limit as usize)
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
                            segment.matches(&*needle).count() as i128
                        }
                    } else {
                        let p = if name.starts_with('r') {
                            segment.rfind(&*needle)
                        } else {
                            segment.find(&*needle)
                        };
                        match p {
                            Some(p) => (start + segment[..p].chars().count()) as i128,
                            None => -1,
                        }
                    };
                    if n < 0 && (name == "index" || name == "rindex") {
                        return Err(pyerr("ValueError", "substring not found"));
                    }
                    return Ok(Value::Int(Int::from_i128(n).into()));
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
                        None => s.to_string(),
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
                "removeprefix" => s.strip_prefix(&*strarg(0)?).unwrap_or(&s).to_string(),
                "removesuffix" => s.strip_suffix(&*strarg(0)?).unwrap_or(&s).to_string(),
                "partition" | "rpartition" => {
                    let sep = strarg(0)?;
                    if sep.is_empty() {
                        return Err(pyerr("ValueError", "empty separator"));
                    }
                    let p = if name == "partition" {
                        s.find(&*sep)
                    } else {
                        s.rfind(&*sep)
                    };
                    let out = if let Some(p) = p {
                        vec![
                            Value::Str(s[..p].into()),
                            Value::Str(sep.clone().into()),
                            Value::Str(s[p + sep.len()..].into()),
                        ]
                    } else if name == "partition" {
                        vec![Value::Str(s.into()), Value::Str("".into()), Value::Str("".into())]
                    } else {
                        vec![Value::Str("".into()), Value::Str("".into()), Value::Str(s.into())]
                    };
                    return Ok(self.obj_value(Object::Tuple(out)));
                }
                "encode" => return self.codec_encode(receiver, args, kwargs),
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
                            let (key, spec) = field.split_once(':').unwrap_or((&field, ""));
                            let (key, conversion) = key.split_once('!').unwrap_or((key, ""));
                            let value = if key.is_empty() {
                                let v = arg(auto)?;
                                auto += 1;
                                v
                            } else if let Ok(i) = key.parse::<usize>() {
                                arg(i)?
                            } else {
                                kw(key).ok_or_else(|| pyerr("KeyError", key))?
                            };
                            let value = match conversion {
                                "r" => Value::Str(self.repr(&value)?.into()),
                                "a" => Value::Str(text_ascii_escape(&self.repr(&value)?).into()),
                                "s" => Value::Str(self.str_value(&value)?.into()),
                                "" => value,
                                _ => {
                                    return Err(pyerr("ValueError", "Unknown conversion specifier"))
                                }
                            };
                            out.push_str(&self.format_value(value, spec)?)
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
            return Ok(Value::Str(result.into()));
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
                                if self.identical_or_equal(x, &v)? {
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
                                if self.identical_or_equal(x, &v)? {
                                    n += 1
                                }
                            }
                            return Ok(Value::Int(Int::from_i128(n).into()));
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
                                if self.identical_or_equal(&xs[j], &v)? {
                                    return Ok(Value::Int(Int::from_i128(j as i128).into()));
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
                            let key=arg(0)?;
                            return Ok(match self.dictionary_find(i,&xs,&key)?{
                                Some(index)=>{let Object::Dict(current)=self.object(i)? else{unreachable!()};current[index].1.clone()},
                                None=>args.get(1).cloned().unwrap_or(Value::None),
                            });
                        },
                        "pop"=>{
                            let key=arg(0)?;
                            if let Some(position)=self.dictionary_find(i,&xs,&key)? {
                                let Object::Dict(mut xs)=self.object(i)? else{unreachable!()};
                                let (key,value)=xs.remove(position);self.dictionary_remove_entry_hash(i,position);
                                self.heap[i]=Some(Object::Dict(xs));self.assoc_dictionary_removed(i,position);return Ok(value);
                            }
                            return if let Some(default)=args.get(1){Ok(default.clone())}else{Err(self.new_exception("KeyError",vec![key])?)};
                        },
                        "popitem"=>{
                            let (key,value)=xs.pop().ok_or_else(||pyerr("KeyError","popitem(): dictionary is empty"))?;self.dictionary_remove_entry_hash(i,xs.len());
                            let position=xs.len();self.heap[i]=Some(Object::Dict(xs));self.assoc_dictionary_removed(i,position);
                            if let Some(layout)=self.assoc_layouts.get_mut(&i){while layout.slots.last().is_some_and(Option::is_none){layout.slots.pop();}}
                            return Ok(self.obj_value(Object::Tuple(vec![key,value])));
                        },
                        "setdefault"=>{
                            let key=arg(0)?;
                            let hash=self.frozen_member_hash(&key)?;
                            if let Some(position)=self.dictionary_find_known(i,&xs,&key,hash)? {let Object::Dict(current)=self.object(i)? else{unreachable!()};return Ok(current[position].1.clone());}
                            let value=args.get(1).cloned().unwrap_or(Value::None);
                            self.dictionary_set_known(i,key,value.clone(),hash)?;return Ok(value);
                        },
                        "update"=>{
                            if args.len()>1 {return Err(pyerr("TypeError","update expected at most 1 argument"));}
                            if let Some(source)=args.first(){self.dictionary_update_value(i,source.clone())?;}
                            for(key,value)in kwargs{let hash=if let Some(hash)=key.hash{hash}else{self.frozen_member_hash(&key.original)?};self.dictionary_set_known(i,key.original,value,hash)?;}
                            return Ok(Value::None);
                        },
                        "clear"=>{xs.clear();self.assoc_cleared(i);},
                        "copy"=>return self.dictionary_copy(receiver),
                        _=>return Err(pyerr("AttributeError",name)),
                    }
                    self.heap[i]=Some(Object::Dict(xs));return Ok(Value::None);
                }
                Object::Range(a, b, step) => {
                    return self.range_method(a.into_inner(), b.into_inner(), step.into_inner(), name, args, kwargs)
                }
                Object::Namespace(m, parent) => {
                    let mut xs = m.ident_items();
                    self.heap[i] = Some(Object::Dict(xs));
                    let result = self.method(name, receiver.clone(), args, kwargs);
                    if let Some(Some(Object::Dict(entries))) = self.heap.get(i) {
                        xs = entries.clone();
                        let mut map = OrderedNamespace::new();
                        for (k, v) in xs {
                            if let Value::Str(k) = k {
                                map.insert_ident(k, v);
                            }
                        }
                        self.heap[i] = Some(Object::Namespace(map, parent));
                    }
                    return result;
                }
                Object::Set(mut xs) => {
                    if ["update","difference_update","intersection_update","symmetric_difference_update"].contains(&name) {
                        return self.live_set_update(i,name,args,kwargs);
                    }
                    match name {
                        "add"=>{if args.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError","set.add() takes one argument"));}self.set_insert_value(i,arg(0)?,None)?;return Ok(Value::None);}
                        "update" => {
                            for a in args {
                                for v in self.to_vec(a)? {
                                    if !self.contains_vec(&xs, &v)? {
                                        xs.push(v)
                                    }
                                }
                            }
                        }
                        "remove"|"discard"=>{if args.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError","set deletion takes one argument"));}return self.set_discard_value(i,arg(0)?,name=="remove");}
                        "pop" => {
                            if !args.is_empty()||!kwargs.is_empty(){return Err(pyerr("TypeError","set.pop() takes no arguments"));}
                            let v = xs
                                .pop()
                                .ok_or_else(|| pyerr("KeyError", "pop from empty set"))?;
                            self.heap[i] = Some(Object::Set(xs));
                            self.assoc_removed(i,&v);
                            return Ok(v);
                        }
                        "clear" => {if !args.is_empty()||!kwargs.is_empty(){return Err(pyerr("TypeError","set.clear() takes no arguments"));}xs.clear();self.assoc_cleared(i);},
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
                    self.assoc_sync(i)?;
                    return Ok(Value::None);
                }
                Object::Generator(mut frame) => {
                    if self.running_generators.contains(&i) {
                        return Err(pyerr("ValueError", "generator already executing"));
                    }
                    if !kwargs.is_empty()
                        || (name == "close" && !args.is_empty())
                        || (name == "send" && args.len() != 1)
                        || (name == "throw" && !(1..=3).contains(&args.len()))
                    {
                        return Err(pyerr("TypeError", "invalid generator method arguments"));
                    }
                    match name {
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
                            return self.iterator_next(receiver);
                        }
                        "close" => {
                            if frame.pc == 0 || frame.pc == usize::MAX {
                                frame.pc = usize::MAX;
                                self.heap[i] = Some(Object::Generator(frame));
                                return Ok(Value::None);
                            }
                            frame.injected_exception = Some(pyerr("GeneratorExit", ""));
                            self.heap[i] = Some(Object::Generator(frame));
                            return match self.next_raw(receiver.clone()) {
                                Ok(None) => {
                                    let error = self.iterator_stop(&receiver)?;
                                    Ok(Self::stop_value(&error))
                                }
                                Ok(Some(_)) => {
                                    Err(pyerr("RuntimeError", "generator ignored GeneratorExit"))
                                }
                                Err(e)
                                    if self.exception_has_native_class(&e, "GeneratorExit") || self.exception_has_native_class(&e, "StopIteration") =>
                                {
                                    Ok(Value::None)
                                }
                                Err(e) => Err(e),
                            };
                        }
                        "throw" => {
                            let value = arg(0)?;
                            let value = if matches!(value, Value::Type(_)) {
                                let arguments = match args.get(1) {
                                    None | Some(Value::None) => Vec::new(),
                                    Some(Value::Obj(index))
                                        if matches!(
                                            self.heap.get(*index).and_then(Option::as_ref),
                                            Some(Object::Tuple(_))
                                        ) =>
                                    {
                                        self.to_vec(args[1].clone())?
                                    }
                                    Some(argument) => vec![argument.clone()],
                                };
                                self.call(value, arguments, Vec::new(), None)?
                            } else {
                                if args
                                    .get(1)
                                    .map(|value| !matches!(value, Value::None))
                                    .unwrap_or(false)
                                {
                                    return Err(pyerr(
                                        "TypeError",
                                        "instance exception may not have a separate value",
                                    ));
                                }
                                value
                            };
                            if let Some(traceback) = args.get(2) {
                                if !matches!(traceback, Value::None)
                                    && !matches!(traceback, Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Record { name, .. }) if name == "traceback"))
                                {
                                    return Err(pyerr(
                                        "TypeError",
                                        "throw() third argument must be a traceback object",
                                    ));
                                }
                            }
                            let error = self.as_exception(value)?;
                            if frame.pc == usize::MAX {
                                return Err(error);
                            }
                            frame.injected_exception = Some(error);
                            self.heap[i] = Some(Object::Generator(frame));
                            return self.iterator_next(receiver);
                        }
                        _ => {}
                    }
                }
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
        kwargs: KeywordArgs,
        caller: Option<&Frame>,
    ) -> PyResult<Value> {
        if let Some(slot)=name.strip_prefix("implicit_native:"){return self.implicit_native_call(slot,args,kwargs);}
        if name.starts_with("native_attr:") {return self.native_attribute_call(Value::Builtin(name.into()),args,kwargs);}
        if name=="native_attr_bind" {
            if !(2..=3).contains(&args.len())||!kwargs.is_empty(){return Err(pyerr("TypeError","descriptor __get__ takes one or two arguments"));}
            let descriptor=args[0].clone();let instance=args[1].clone();
            let class=args.get(2).cloned().filter(|value|!matches!(value,Value::None)).unwrap_or_else(||self.native_receiver_class(&instance));
            return self.bind_native_attribute(descriptor,if matches!(instance,Value::None){None}else{Some(instance)},class).unwrap();
        }
        if name=="native_attr_readonly" {
            if args.len()<2||!kwargs.is_empty(){return Err(pyerr("TypeError","missing descriptor instance"));}
            let (_,owner,_)=native_attribute_parts(&args[0]).ok_or_else(||pyerr("TypeError","expected native descriptor"))?;
            self.native_validate_receiver(owner,&args[1])?;
            return Err(pyerr("AttributeError","readonly native attribute"));
        }
        if name=="_py2fastrust_nullable_slot" {
            if args.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError","invalid internal slot arguments"));}
            if let Value::Obj(index)=&args[0] {if matches!(self.object(*index)?,Object::Slot{..}) {self.collection_nullable_slots.insert(*index);return Ok(Value::None);}}
            return Err(pyerr("TypeError","expected a slot descriptor"));
        }
        if name=="_py2fastrust_ordered" {return self.collection_ordered(args,kwargs);}
        if name=="_py2fastrust_dict_payload" {
            if args.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError","invalid internal dictionary arguments"));}
            return Ok(Value::Obj(self.collection_dict_owner(&args[0])?));
        }
        if name=="_py2fastrust_namedtuple_module" {
            if !args.is_empty()||!kwargs.is_empty(){return Err(pyerr("TypeError","invalid internal caller arguments"));}
            // Original frame bookkeeping supplies the caller's module namespace;
            // generated programs never call CPython's internal frame API.
            let module=if let Some(index)=self.collection_callers.len().checked_sub(2){self.global_name_get(self.collection_callers[index],"__name__")?}else{None};
            return Ok(match module {Some(value) if self.truth(&value)?=>value,_=>Value::Str("__main__".into())});
        }
        if name=="complex:from_number"{return self.complex_from_number(args,kwargs);}
        if name=="complex"{return self.complex_constructor(args,kwargs);}
        if template_type_name(name){return self.template_constructor(name,args,kwargs).unwrap();}
        if name=="module:string.templatelib:convert" {return self.template_convert(args,kwargs);}
        if typing_constructor_name(name){return self.typing_constructor(name,args,kwargs,caller).unwrap();}
        if let Some(action) = name.strip_prefix("slot:") {
            let descriptor = args
                .first()
                .cloned()
                .ok_or_else(|| pyerr("TypeError", "missing descriptor"))?;
            let instance = args
                .get(1)
                .cloned()
                .ok_or_else(|| pyerr("TypeError", "missing instance"))?;
            if action == "get" && matches!(instance, Value::None) {
                return Ok(descriptor);
            }
            let value = if action == "set" {
                Some(
                    args.get(2)
                        .cloned()
                        .ok_or_else(|| pyerr("TypeError", "missing value"))?,
                )
            } else {
                None
            };
            return self.slot_access(descriptor, instance, value, action == "delete");
        }
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
            let original=args.first().cloned();
            if owner=="dict" && method=="copy" {
                if args.len()!=1||!kwargs.is_empty(){return Err(pyerr("TypeError","copy() takes no arguments"));}
                self.collection_dict_owner(&args[0])?;
                return self.dictionary_copy(args[0].clone());
            }
            if owner=="dict" && method=="__getitem__" {
                if args.len()!=2||!kwargs.is_empty(){return Err(pyerr("TypeError","__getitem__ expected one argument"));}
                return self.collection_dict_getitem(args[0].clone(),args[1].clone());
            }
            let mut args = args;
            if let Some(Value::Obj(i)) = args.first() {
                if let Object::BuiltinInstance { payload, .. } = self.object(*i)? {
                    if self.typename(&payload) == owner && owner!="frozenset" {
                        args[0] = if matches!(method, "__int__" | "__index__" | "__complex__" | "__pos__" | "conjugate") || (owner=="str"&&method=="__str__") {
                            payload.fresh_primitive()
                        } else { payload }
                    }
                }
            }
            if args.is_empty() {
                return Err(pyerr("TypeError", "unbound descriptor needs an instance"));
            }
            if owner=="dict" {self.collection_dict_owner(&args[0])?;}
            if owner=="str" && !matches!(&args[0],Value::Str(_)){return Err(pyerr("TypeError",format!("descriptor '{method}' requires a 'str' object")));}
            if owner=="set" && !self.frozen_owner(&args[0]).is_some_and(|(_,frozen)|!frozen){return Err(pyerr("TypeError",format!("descriptor '{}' requires a 'set' object",method)));}
            if owner=="frozenset" && !self.frozen_owner(&args[0]).is_some_and(|(_,frozen)|frozen){return Err(pyerr("TypeError",format!("descriptor '{}' requires a 'frozenset' object",method)));}
            if owner=="complex" && !matches!(&args[0],Value::Complex(_)){return Err(pyerr("TypeError",format!("descriptor '{}' requires a 'complex' object",method)));}
            if method == "__delitem__" {
                if args.len()!=2 || !kwargs.is_empty(){return Err(pyerr("TypeError","__delitem__() takes exactly one argument"));}
                self.delitem(args[0].clone(),args[1].clone())?;return Ok(Value::None);
            }
            if method == "__setitem__" {
                if args.len()!=3||!kwargs.is_empty(){return Err(pyerr("TypeError","__setitem__() takes exactly two arguments"));}
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
            let result=self.method(method, args[0].clone(), args[1..].to_vec(), kwargs)?;
            return Ok(if let Some(original)=original{self.collection_keep(result,original)}else{result});
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
                            Value::Int(Int::from_i128(cache.hits as i128).into()),
                        ),
                        (
                            "misses".into(),
                            Value::Int(Int::from_i128(cache.misses as i128).into()),
                        ),
                        (
                            "maxsize".into(),
                            cache
                                .maxsize
                                .map(|n| Value::Int(Int::from_i128(n as i128).into()))
                                .unwrap_or(Value::None),
                        ),
                        (
                            "currsize".into(),
                            Value::Int(Int::from_i128(cache.entries.len() as i128).into()),
                        ),
                    ],
                })),
                "cache_clear" => {
                    cache.revision=cache.revision.wrapping_add(1);
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
                            .map(|n| Value::Int(Int::from_i128(n as i128).into()))
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
        if let Some(rest) = name.strip_prefix("exception_type:") {return self.exception_type_method(rest,args,kwargs,caller);}
        if let Some(rest) = name.strip_prefix("type_method:") {
            let mut p = rest.split(':');
            let typ = p.next().unwrap_or("");
            let method = p.next().unwrap_or("");
            if typ=="object" && method=="__init_subclass__"{
                if args.len()!=1 || !kwargs.is_empty(){return Err(pyerr("TypeError","__init_subclass__() takes no keyword arguments"));}
                return Ok(Value::None);
            }
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
            if ["tuple", "list", "dict", "set", "str", "int", "complex", "frozenset"].contains(&typ) && method == "__new__"
            {
                let class = args
                    .first()
                    .cloned()
                    .ok_or_else(|| pyerr("TypeError", "tuple.__new__ needs class"))?;
                return self.builtin_instance_new(typ, class, args[1..].to_vec(), kwargs);
            }
            if method == "__init__" {
                if ["list", "dict", "set"].contains(&typ) {
                    let receiver = args
                        .first()
                        .cloned()
                        .ok_or_else(|| pyerr("TypeError", "missing instance"))?;
                    if typ=="set" {
                        let payload=self.native_payload(&receiver).unwrap_or_else(||receiver.clone());
                        if let Value::Obj(owner)=payload {self.assoc_cleared(owner);}
                    }
                    return self.builtin_instance_init(typ, receiver, args[1..].to_vec(), kwargs);
                }
                return Ok(Value::None);
            }
            if typ == "type" {
                if args.len() < 4 {
                    return Err(pyerr("TypeError", "type.__new__ needs arguments"));
                }
                return self.construct_class(args[0].clone(), args[1..].to_vec(), kwargs);
            }
            if typ == "object" {
                let attrs = self.alloc(Object::Namespace(OrderedNamespace::new(), None));
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
            "print" => self.print_values(args,kwargs),
            "input" => self.input_value(args,kwargs),
            "int" => {
                if args.len()>2 || kwargs.iter().any(|(name,_)|name!="base") { return Err(pyerr("TypeError","invalid arguments for int()")); }
                let mut arguments=args;
                if let Some((_,base))=kwargs.first() {
                    if arguments.is_empty() || arguments.len()>1 || kwargs.len()>1 { return Err(pyerr("TypeError","invalid or repeated base argument")); }
                    arguments.push(base.clone());
                }
                let base=if arguments.len()==2 {
                    let base=self.as_int(&arguments[1])?.to_i128().unwrap_or(-1);
                    if base!=0 && !(2..=36).contains(&base) { return Err(pyerr("ValueError","int() base must be >= 2 and <= 36, or 0")); }
                    Some(base as u32)
                } else { None };
                let v=arguments.first().cloned().unwrap_or(Value::Int(Int::from_i128(0).into()));
                if base.is_some() && !matches!(v,Value::Str(_) | Value::Bytes(_)) { return Err(pyerr("TypeError","int() can't convert non-string with explicit base")); }
                Ok(Value::Int(match v {
                    Value::Int(i) => i,
                    Value::Bool(b) => Int::from_i128(if b { 1 } else { 0 }).into(),
                    Value::Float(f) => Int::from_f64(*f).map_err(int_error)?.into(),
                    Value::Str(s) => {
                        Int::parse(s.trim(), base.unwrap_or(10)).map_err(int_error)?.into()
                    }
                    Value::Bytes(b) => {
                        let s = String::from_utf8(b.to_vec())
                            .map_err(|_| pyerr("ValueError", "invalid literal for int"))?;
                        Int::parse(s.trim(), base.unwrap_or(10)).map_err(int_error)?.into()
                    }
                    v => {
                        for method in ["__int__","__index__"] {
                            match self.special_method(v.clone(),method) {
                                Ok(fun)=>{
                                    let out=self.call(fun,Vec::new(),Vec::new(),None)?;
                                    match out {
                                        Value::Int(value)=>return Ok(Value::Int(value)),
                                        Value::Bool(value)=>return Ok(Value::Int(Int::from_i128(if value{1}else{0}).into())),
                                        value=>if let Some(Value::Int(value))=self.native_payload(&value) {return Ok(Value::Int(value.into_inner().into()));},
                                    }
                                    return Err(pyerr("TypeError",format!("{method} returned non-int")));
                                },
                                Err(error) if self.missing_special_method(&v,method,&error)=>(),
                                Err(error)=>return Err(error),
                            }
                        }
                        return Err(pyerr("TypeError","int() argument must be a string or a real number"));
                    }
                }))
            }
            "float" => {
                if args.len()>1 || !kwargs.is_empty(){return Err(pyerr("TypeError","float() takes at most one positional argument"));}
                let v = args.first().cloned().unwrap_or(Value::Float(0.0.into()));
                Ok(Value::Float(match v {
                    Value::Float(value) => value,
                    Value::Str(s) => s.trim().parse().map_err(|_| {
                        pyerr(
                            "ValueError",
                            format!("could not convert string to float: {:?}", s),
                        )
                    })?,
                    v => {
                        match self.special_method(v.clone(),"__float__") {
                            Ok(fun)=>{
                                let out=self.call(fun,Vec::new(),Vec::new(),None)?;
                                match out { Value::Float(value)=>return Ok(Value::Float(value)),value=>if let Some(Value::Float(value))=self.native_payload(&value){return Ok(Value::Float(value.into_inner().into()));} }
                                return Err(pyerr("TypeError","__float__ returned non-float"));
                            },
                            Err(error) if self.missing_special_method(&v,"__float__",&error)=>(),
                            Err(error)=>return Err(error),
                        }
                        self.as_float(&v)?.into()
                    },
                }))
            }
            "bool" => Ok(Value::Bool(if args.is_empty() {
                false
            } else {
                self.truth(&args[0])?
            })),
            "str" => self.str_constructor(args, kwargs),
            "repr" => Ok(Value::Str(self.repr(&arg(0)?)?.into())),
            "ascii" => Ok(Value::Str(text_ascii_escape(&self.repr(&arg(0)?)?).into())),
            "frozenset" => self.frozen_constructor(args,kwargs),
            "set" => self.set_constructor_value(args,kwargs),
            "memoryview" => Err(pyerr(
                "NotImplementedError",
                "memoryview values are not implemented",
            )),
            "list" | "tuple" => {
                if args.len() > 1 || !kwargs.is_empty() {
                    return Err(pyerr("TypeError", format!("{}() takes at most one argument", name)));
                }
                if name == "tuple" {
                    if let Some(Value::Obj(index)) = args.first() {
                        if matches!(self.object(*index)?, Object::Tuple(_)) {
                            return Ok(args[0].clone());
                        }
                    }
                }
                let mut vs = if args.is_empty() {
                    Vec::new()
                } else {
                    if name=="list"{self.list_collect(args[0].clone())?}else{self.to_vec(args[0].clone())?}
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
                    "set" => Object::Set(vs),
                    _ => Object::List(vs),
                }))
            }
            "GenericAlias" => {
                if args.len()!=2 || !kwargs.is_empty() {return Err(pyerr("TypeError","GenericAlias expected 2 arguments"));}
                self.generic_alias(args[0].clone(),args[1].clone())
            }
            "NoneType" => {
                if !args.is_empty() || !kwargs.is_empty(){return Err(pyerr("TypeError","NoneType takes no arguments"));}
                Ok(Value::None)
            }
            "dict_keys" | "dict_values" | "dict_items" => Err(pyerr("TypeError",format!("cannot create '{}' instances",name))),
            "mappingproxy" => {
                if args.len()!=1 || !kwargs.is_empty() {return Err(pyerr("TypeError","mappingproxy() takes exactly one argument"));}
                let mut source=args[0].clone();if let Some(payload)=self.native_payload(&source) {source=payload;}
                if let Some(payload)=self.proxy_payload(&source) {source=payload;}
                if let Value::Obj(owner)=source {if matches!(self.object(owner)?,Object::Dict(_)|Object::Namespace(..)){return Ok(self.obj_value(Object::MappingProxy{owner}));}}
                Err(pyerr("TypeError","mappingproxy() argument must be a mapping"))
            }
            "dict" => {
                let d=self.obj_value(Object::Dict(Vec::new()));
                if let (Value::Obj(owner),Some(source))=(&d,args.first()){self.dictionary_update_value(*owner,source.clone())?;}
                for (k, v) in kwargs {
                    self.setitem(d.clone(), k.original, v)?
                }
                Ok(d)
            }
            "bytes" => self.bytes_constructor(args, kwargs),
            "bytearray" => Err(pyerr(
                "NotImplementedError",
                "bytearray values are not implemented",
            )),
            "len" => {
                let v = arg(0)?;
                if let Value::Obj(index)=&v {if matches!(self.object(*index)?,Object::MappingProxy{..}) {if let Some(keeper)=self.collection_keepers.get(index).cloned(){return self.builtin("len",vec![keeper],Vec::new(),None);}}if let Object::DictView { owner, .. } | Object::MappingProxy { owner }=self.object(*index)? {return Ok(Value::Int(Int::from_i128(self.assoc_size(owner) as i128).into()));}}
                let fastlen = if let Value::Obj(i) = &v {
                    match self.heap.get(*i).and_then(|o| o.as_ref()) {
                        Some(Object::List(xs) | Object::Tuple(xs) | Object::Set(xs) | Object::FrozenSet{items:xs,..}) => {
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
                    return Ok(Value::Int(Int::from_i128(n as i128).into()));
                }
                let n = match &v {
                    Value::Str(s) => s.chars().count(),
                    Value::Bytes(b) => b.len(),
                    Value::Obj(i) => match self.object(*i)? {
                        Object::List(v) | Object::Tuple(v) | Object::Set(v) | Object::FrozenSet{items:v,..} => v.len(),
                        Object::Dict(v) => v.len(),
                        Object::Namespace(m, _) => m.len(),
                        Object::Range(a, b, s) => range_length(&a, &b, &s).map_err(int_error)?,
                        _ => {
                            let fun = self.special_method(v.clone(), "__len__").map_err(|error| {
                                if error.kind=="AttributeError" && self.object_class(&v).and_then(|class|self.slot_override(&class,"__len__",0)).is_none() {pyerr("TypeError",format!("object of type '{}' has no len()",self.typename(&v)))}else{error}
                            })?;
                            let value=self.call(fun,Vec::new(),Vec::new(),caller)?;
                            return Ok(Value::Int(Int::from_i128(self.protocol_length(&value)? as i128).into()));
                        }
                    },
                    _ => return Err(pyerr("TypeError", "object has no len()")),
                };
                Ok(Value::Int(Int::from_i128(n as i128).into()))
            }
            "range" => {
                if args.is_empty() || args.len() > 3 || !kwargs.is_empty() {
                    return Err(pyerr("TypeError", "range expected 1 to 3 arguments"));
                }
                let (start, stop) = if args.len() == 1 {
                    (Int::from_i128(0).into(), self.index_identity(&args[0])?)
                } else {
                    (self.index_identity(&args[0])?, self.index_identity(&args[1])?)
                };
                let step = if args.len() == 3 {
                    self.index_identity(&args[2])?
                } else {
                    Int::from_i128(1).into()
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
            "next" => match self.iterator_next(arg(0)?) {
                Ok(v) => Ok(v),
                Err(error) if self.exception_has_native_class(&error, "StopIteration") => {
                    if let Some(v) = args.get(1) {
                        Ok(v.clone())
                    } else {
                        Err(error)
                    }
                }
                Err(error) => Err(error),
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
                    .unwrap_or(Value::Int(Int::from_i128(0).into()));
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
                let values = self.list_collect(arg(0)?)?;
                let reverse = kw("reverse")
                    .map(|v| self.truth(&v))
                    .transpose()?
                    .unwrap_or(false);
                let out = self.sort_values(values, kw("key"), reverse)?;
                Ok(self.obj_value(Object::List(out)))
            }
            "reversed" => {
                if args.len()!=1 || !kwargs.is_empty() {return Err(pyerr("TypeError","reversed() takes exactly one argument"));}
                let value=arg(0)?;
                if let Some(class)=self.object_class(&value) {
                    if self.slot_definition(&class,"__reversed__",0).is_some(){
                        let method=self.special_method(value,"__reversed__")?;
                        return self.call(method,Vec::new(),Vec::new(),caller);
                    }
                }
                if let Value::Obj(index) = &value {
                    let index=*index;
                    match self.object(index)? {
                        Object::Dict(_) | Object::Namespace(..)=>return self.assoc_iterator(index,DictViewKind::Keys,true),
                        Object::DictView { owner, kind }=>{let result=self.assoc_iterator(owner,kind,true)?;return Ok(self.collection_inherit_keeper(result,&value));},
                        Object::MappingProxy { owner }=>{if let Some(keeper)=self.collection_keepers.get(&index).cloned(){return self.builtin("reversed",vec![keeper],Vec::new(),None);}return self.assoc_iterator(owner,DictViewKind::Keys,true)},
                        Object::Set(_) | Object::FrozenSet{..}=>return Err(pyerr("TypeError","set objects are not reversible")),
                        _=>{},
                    }
                    if let Object::Range(start, stop, step) = self.object(index)? {
                        let (start, stop, step) = range_reversed(&start, &stop, &step);
                        return Ok(self
                            .obj_value(Object::Iterator(IteratorState::Range(start, stop, step))));
                    }
                }
                let length=self.builtin("len",vec![value.clone()],Vec::new(),caller)?;
                let length=self.as_int(&length)?.to_usize().filter(|size|*size<=isize::MAX as usize).ok_or_else(||pyerr("OverflowError","sequence is too large to reverse"))?;
                if !matches!(&value,Value::Str(_)|Value::Bytes(_)) && !matches!(&value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::List(_)|Object::Tuple(_)))) && self.object_class(&value).and_then(|class|self.slot_definition(&class,"__getitem__",0)).is_none(){
                    return Err(pyerr("TypeError",format!("'{}' object is not reversible",self.typename(&value))));
                }
                Ok(self.obj_value(Object::Iterator(IteratorState::Reversed(value,length as isize-1))))
            }
            "abs" => {
                let v = arg(0)?;
                match v {
                    Value::Int(n) if !n.is_negative() => Ok(Value::Int(n)),
                    Value::Int(n) => Ok(Value::Int(n.abs().into())),
                    Value::Bool(value) => Ok(Value::Int(Int::from_i128(if value{1}else{0}).into())),
                    Value::Float(n) => Ok(Value::Float(n.abs().into())),
                    Value::Complex(_)=>self.complex_method(v,"__abs__",Vec::new(),Vec::new()).unwrap(),
                    v => {
                        match self.special_method(v.clone(),"__abs__") {
                            Ok(fun)=>self.call(fun,Vec::new(),Vec::new(),caller),
                            Err(error) if self.missing_special_method(&v,"__abs__",&error)=>if let Some(payload)=self.native_payload(&v){self.builtin("abs",vec![payload.fresh_primitive()],Vec::new(),caller)}else{Err(error)},
                            Err(error)=>Err(error),
                        }
                    }
                }
            }
            "pow" => {
                let fields=codec_bind("pow",args,kwargs,&["base","exp","mod"])?;
                let base=fields[0].clone().ok_or_else(||pyerr("TypeError","pow() missing required argument 'base'"))?;
                let exponent=fields[1].clone().ok_or_else(||pyerr("TypeError","pow() missing required argument 'exp'"))?;
                if let Some(modulus)=fields[2].clone().filter(|value|!matches!(value,Value::None)) {
                    if [&base,&exponent,&modulus].iter().any(|value|matches!(self.native_payload(value).unwrap_or_else(||(*value).clone()),Value::Complex(_))){return Err(pyerr("ValueError","complex modulo"));}
                    let a=self.as_int(&base)?;let b=self.as_int(&exponent)?;let m=self.as_int(&modulus)?;
                    Ok(Value::Int(a.modpow(&b,&m).map_err(int_error)?.into()))
                }else{self.binary("**",base,exponent)}
            }
            "divmod" => {
                let a = self.binary("//", arg(0)?, arg(1)?)?;
                let b = self.binary("%", arg(0)?, arg(1)?)?;
                Ok(self.obj_value(Object::Tuple(vec![a, b])))
            }
            "round" => {
                let mut values=codec_bind("round",args,kwargs,&["number","ndigits"])?;
                let value=values[0].take().ok_or_else(||pyerr("TypeError","round() missing required argument 'number'"))?;
                let digits=values[1].take().filter(|value|!matches!(value,Value::None));
                match value {
                    Value::Int(number)=>{
                        let digits=digits.as_ref().map(|value|self.as_int(value)).transpose()?;
                        if digits.as_ref().map(|value|!value.is_negative()).unwrap_or(true){return Ok(Value::Int(number));}
                        Ok(Value::Int(number.round_decimal(digits.as_ref().unwrap()).into()))
                    },
                    Value::Bool(number)=>{
                        let number=Int::from_i128(if number{1}else{0});
                        let digits=digits.as_ref().map(|value|self.as_int(value)).transpose()?;
                        Ok(Value::Int(if let Some(digits)=digits{number.round_decimal(&digits)}else{number}.into()))
                    },
                    Value::Float(number)=>if let Some(digits)=digits {
                        let digits=self.as_int(&digits)?;
                        Ok(Value::Float(Int::round_float_decimal(*number,&digits).map_err(int_error)?.into()))
                    }else{Ok(Value::Int(Int::from_f64(number.round_ties_even()).map_err(int_error)?.into()))},
                    value=>match self.special_method(value.clone(),"__round__") {
                        Ok(fun)=>self.call(fun,digits.into_iter().collect(),Vec::new(),caller),
                        Err(error) if self.exception_has_native_class(&error,"AttributeError")=>if self.slot_override(&self.native_receiver_class(&value),"__round__",0).is_some(){
                            Err(pyerr("TypeError","type doesn't define __round__ method"))
                        }else if let Some(payload)=self.native_payload(&value){
                            let mut arguments=vec![payload.fresh_primitive()];arguments.extend(digits);self.builtin("round",arguments,Vec::new(),caller)
                        }else{Err(pyerr("TypeError","type doesn't define __round__ method"))},
                        Err(error)=>Err(error),
                    },
                }
            }
            "bin" | "oct" | "hex" => {
                let number = self.as_int(&arg(0)?)?;
                let spec = match name {
                    "bin" => "#b",
                    "oct" => "#o",
                    _ => "#x",
                };
                Ok(Value::Str(
                    number.format_integer(spec).map_err(int_error)?.unwrap().into(),
                ))
            }
            "chr" => {
                let n = self
                    .as_int(&arg(0)?)?
                    .to_usize()
                    .ok_or_else(|| pyerr("ValueError", "chr() arg not in range(0x110000)"))?;
                Ok(Value::Str(
                    char::from_u32(n as u32)
                        .ok_or_else(|| pyerr("ValueError", "chr() arg not in range(0x110000)"))?
                        .to_string().into(),
                ))
            }
            "ord" => match arg(0)? {
                Value::Str(s) => {
                    let cs: Vec<_> = s.chars().collect();
                    if cs.len() != 1 {
                        return Err(pyerr("TypeError", "ord() expected a character"));
                    }
                    Ok(Value::Int(Int::from_i128(cs[0] as i128).into()))
                }
                Value::Bytes(b) if b.len() == 1 => Ok(Value::Int(Int::from_i128(b[0] as i128).into())),
                _ => Err(pyerr("TypeError", "ord() expected a character")),
            },
            "format" => {
                let spec = if args.len() > 1 {
                    self.str_value(&args[1])?
                } else {
                    String::new()
                };
                Ok(Value::Str(self.format_value(arg(0)?, &spec)?.into()))
            }
            "getattr" => {
                let n = self.str_value(&arg(1)?)?;
                match self.getattr(arg(0)?, &n) {
                    Err(e) if self.exception_has_native_class(&e, "AttributeError") && args.len() > 2 => Ok(args[2].clone()),
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
                    Err(e) if self.exception_has_native_class(&e, "AttributeError") => Ok(Value::Bool(false)),
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
                let attrs = self.alloc(Object::Namespace(OrderedNamespace::new(), None));
                Ok(self.obj_value(Object::Instance {
                    class: Value::Builtin("object".into()),
                    attrs,
                }))
            }
            "id" => {
                let v = arg(0)?;
                let id=self.identity_number(&v);
                Ok(Value::Int(Int::from_i128(id as i128).into()))
            }
            "hash" => {
                use std::hash::{Hash, Hasher};
                let v = arg(0)?;
                if matches!(&v,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Template{..}|Object::Interpolation{..}))) {let id=self.identity_number(&v);return Ok(Value::Int(Int::from_i128(id as i128).into()));}
                if matches!(&v,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::FrozenSet{..}))){return self.frozen_hash(&v);}
                if matches!(&v,Value::Complex(_)){return self.complex_hash(&v);}
                if let Value::Int(value)=&v{return Ok(Value::Int(Int::from_i128(numeric_int_hash(value) as i128).into()));}
                if let Value::Bool(value)=&v{return Ok(Value::Int(Int::from_i128(if *value{1}else{0}).into()));}
                if let Value::Float(value)=&v{let id=self.identity_number(&v);return Ok(Value::Int(Int::from_i128(numeric_float_hash(**value,id) as i128).into()));}
                if let Value::Obj(index) = &v {
                    if matches!(self.object(*index)?,Object::Tuple(_)) {
                        let hash=self.generic_component_hash(&v)? as i64;
                        return Ok(Value::Int(Int::from_i128(if hash==-1{-2}else{hash as i128}).into()));
                    }
                    if matches!(self.object(*index)?,Object::GenericAlias { .. }) {return self.generic_value_hash(&v);}
                    if self.is_typing_value(&v){if let Some(result)=self.typing_hash(&v){return result;}}
                    if let Object::DictView { kind, .. }=self.object(*index)? {
                        if kind!=DictViewKind::Values {return Err(pyerr("TypeError",format!("unhashable type: '{}'",kind.name())));}
                        return Ok(Value::Int(Int::from_i128(*index as i128).into()));
                    }
                    if self.proxy_payload(&v).is_some() {return Err(pyerr("TypeError","unhashable type: 'mappingproxy'"));}
                    if let Object::Range(start, stop, step) = self.object(*index)? {
                        return self.range_hash(start.into_inner(), stop.into_inner(), step.into_inner());
                    }
                }
                if let Some(class) = self.object_class(&v) {
                    if let Some(method) = self.slot_override(&class, "__hash__", 0) {
                        if matches!(method, Value::None) {
                            return Err(pyerr(
                                "TypeError",
                                format!("unhashable type: '{}'", self.typename(&v)),
                            ));
                        }
                        let method = self.bind_descriptor(method,Some(v.clone()),class).map_err(|error|if self.exception_has_native_class(&error,"AttributeError"){pyerr("TypeError",format!("unhashable type: '{}'",self.typename(&v)))}else{error})?;
                        let result = self.call(method, Vec::new(), Vec::new(), None)?;
                        let number=match result {
                            Value::Int(number)=>number.into_inner(),Value::Bool(value)=>Int::from_i128(if value{1}else{0}),
                            value=>match self.native_payload(&value){Some(Value::Int(number))=>number.into_inner(),_=>return Err(pyerr("TypeError","__hash__ method should return an integer"))},
                        };
                        let hash=number.to_i128().filter(|value|*value>=i64::MIN as i128&&*value<=i64::MAX as i128).map(|value|value as i64).unwrap_or_else(||numeric_int_hash(&number));
                        return Ok(Value::Int(Int::from_i128(if hash == -1{-2}else{hash as i128}).into()));
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
                        Some(Object::Instance{..}|Object::Class(_)|Object::Function(_)|Object::Cached(_)|Object::Partial{..}|Object::Module{..}|Object::Generator(_)|Object::Iterator(_))=>{
                            return Ok(Value::Int(Int::from_i128(i as i128).into()))
                        }
                        _ => {}
                    }
                }
                if let Value::Int(n) = v {
                    return Ok(Value::Int(n));
                }
                if let Value::Bool(b) = v {
                    return Ok(Value::Int(Int::from_i128(if b { 1 } else { 0 }).into()));
                }
                let mut h = std::collections::hash_map::DefaultHasher::new();
                self.repr(&v)?.hash(&mut h);
                Ok(Value::Int(Int::from_i128(h.finish() as i64 as i128).into()))
            }
            "globals" => Ok(Value::Obj(
                caller.map(|f| f.globals).unwrap_or(self.globals),
            )),
            "locals" | "vars" => {
                if let Some(v) = args.first() {
                    return self.getattr(v.clone(), "__dict__").map_err(|error| {
                        if self.exception_has_native_class(&error,"AttributeError") {
                            pyerr("TypeError", "vars() argument must have __dict__ attribute")
                        } else {
                            error
                        }
                    });
                }
                let f = caller.ok_or_else(|| pyerr("RuntimeError", "no active frame"))?;
                if f.comprehensions.is_empty() && (self.codes[f.code].kind == ScopeKind::Module
                    || self.codes[f.code].kind == ScopeKind::Class)
                {
                    return Ok(self.execution_locals_value(f.locals));
                }
                self.locals_snapshot(f)
            }
            "dir" => {
                let mut names = if let Some(v) = args.first() {
                    self.attribute_items(v)?
                        .into_iter()
                        .map(|(n, _)| n)
                        .collect::<Vec<_>>()
                } else if let Some(f) = caller {
                    let namespace=if f.comprehensions.is_empty(){Value::Obj(f.locals)}else{self.locals_snapshot(f)?};
                    self.keyword_items(namespace)?
                        .into_iter()
                        .map(|(n, _)| n.spelling)
                        .filter(|n| !n.starts_with('$') && !n.starts_with('\0'))
                        .collect()
                } else {
                    vec![]
                };
                names.sort();
                Ok(self.obj_value(Object::List(names.into_iter().map(|value| Value::Str(value.into())).collect())))
            }
            "compile" => {
                if args.len()>6 {return Err(pyerr("TypeError",format!("compile() takes at most 6 positional arguments ({} given)",args.len())));}
                let mut arguments=self.execution_compile_parameters(args,kwargs)?;
                let source=arguments[0].take().ok_or_else(||pyerr("TypeError","compile() missing source"))?;
                let filename=arguments[1].take().ok_or_else(||pyerr("TypeError","compile() missing filename"))?;
                let mode=arguments[2].take().ok_or_else(||pyerr("TypeError","compile() missing mode"))?;
                // Argument conversions run in signature order, before semantic checks.
                let filename=self.execution_filename(filename)?;
                let mode=self.execution_mode(mode)?;
                let flags=arguments[3].as_ref().map(|value|self.execution_c_int(value)).transpose()?.unwrap_or(0) as u32;
                let dont_inherit=arguments[4].as_ref().map(|value|self.truth(value)).transpose()?.unwrap_or(false);
                let optimize=arguments[5].as_ref().map(|value|self.execution_c_int(value)).transpose()?.unwrap_or(-1);
                if let Some(feature_version)=&arguments[6] {self.execution_c_int(feature_version)?;}
                const FUTURE_MASK:u32=0x1fe0010;
                const PYCF_MASK:u32=0xf600;
                if flags & !(FUTURE_MASK|PYCF_MASK)!=0 {return Err(pyerr("ValueError","compile(): unrecognised flags"));}
                if flags & PYCF_MASK!=0 {return Err(pyerr("NotImplementedError","compile() PyCF AST, incomplete input and top-level await modes are not implemented"));}
                if !(-1..=2).contains(&optimize) {return Err(pyerr("ValueError","compile(): invalid optimize value"));}
                if !matches!(mode.as_str(),"exec"|"eval"|"single") {return Err(pyerr("ValueError","compile() mode must be 'exec', 'eval' or 'single'"));}
                let flags=(flags & FUTURE_MASK & !0x10) | if dont_inherit {0}else{caller.map(|frame|self.codes[frame.code].future_flags).unwrap_or(self.active_future_flags)};
                let src=self.execution_text(source,"compile")?;
                let offset=self.codes.len();
                let codes=compile_dynamic_optimized(&src,&filename,&mode,offset,flags,optimize.max(0) as u8).map_err(int_error)?;
                self.codes.extend(codes);
                Ok(self.code_object(offset))
            }
            "eval" | "exec" => {
                let parameters=self.execution_parameters(name,&args,&kwargs)?;
                let args=parameters[..3].to_vec();
                let source=args[0].clone();
                let globals=self.execution_globals(&args[1],caller,name)?;
                let locals=if !matches!(args[2],Value::None){self.execution_locals(args[2].clone())?}
                else if !matches!(args[1],Value::None){globals}
                else if let Some(frame)=caller{
                    if !frame.comprehensions.is_empty() || matches!(self.codes[frame.code].kind,ScopeKind::Function|ScopeKind::Comprehension|ScopeKind::Annotation|ScopeKind::TypeParameters){match self.locals_snapshot(frame)?{Value::Obj(index)=>index,_=>unreachable!()}}
                    else{frame.locals}
                }else{globals};
                let root=self.roots.len();
                self.roots.push(vec![source.clone(),Value::Obj(globals),Value::Obj(locals)]);
                let result=(||{
                self.execution_ensure_builtins(globals)?;
                if !matches!(parameters[3],Value::None){
                    return Err(pyerr("TypeError",if matches!(&source,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Code(_)))){"cannot use a closure with this code object"}else{"closure can only be used when source is a code object"}));
                }
                let precompiled=match &source{Value::Obj(index)=>match self.heap.get(*index).and_then(Option::as_ref){Some(Object::Code(code))=>Some(*code),_=>None},_=>None};
                if let Some(code)=precompiled {
                    if !self.codes[code].frees.is_empty() {
                        return Err(pyerr("TypeError",if name=="eval" {"code object passed to eval() may not contain free variables".to_owned()} else {format!("code object requires a closure of exactly length {}",self.codes[code].frees.len())}));
                    }
                }
                let code = if let Some(code)=precompiled { code
                } else {
                    let src = self.execution_text(source.clone(),name)?;
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
                        caller.map(|frame|self.codes[frame.code].future_flags).unwrap_or(self.active_future_flags),
                    )
                    .map_err(int_error)?;
                    self.codes.extend(codes);
                    offset
                };
                if precompiled.is_none() {self.execution_ensure_builtins(globals)?;}
                self.execution_run_code(code,globals,locals,name=="exec")
                })();
                self.roots.truncate(root);
                result
            }
            "__build_class__" => self.builtin_build_class(args,kwargs,caller),
            "__import__" => self.builtin_import(args,kwargs),
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
                    let isolated=f.comprehensions.iter().rev().find(|scope|self.codes[scope.code].locals.contains(&n));
                    if let Some(scope)=isolated {self.ns_get(scope.namespace,&n).ok_or_else(||pyerr("RuntimeError","super(): arg[0] deleted"))?}
                    else {self.mapping_get(f.locals,&n)?.ok_or_else(||pyerr("RuntimeError","super(): arg[0] deleted"))?}
                } else {
                    Value::None
                };
                let attrs = self.alloc(Object::Namespace(OrderedNamespace::new(), None));
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
        if self.type_parameter_kind(b).is_some() || matches!(b,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::TypeAlias{..}|Object::ParamSpecMarker{..}|Object::ForwardRef{..}|Object::TypeUnpack(_)))) {
            return Err(pyerr("TypeError","isinstance() arg 2 must be a type, a tuple of types, or a union"));
        }
        if let Value::Obj(index)=b {if let Object::TypeUnion{args,..}=self.object(*index)?{for value in args{if self.is_subclass(a,&value)?{return Ok(true);}}return Ok(false);}}
        if self.generic_parts(b).is_some() {return Err(pyerr("TypeError","isinstance() argument 2 cannot be a parameterized generic"));}
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
        if an=="ExceptionGroup" && bn=="BaseExceptionGroup" {return Ok(true);}
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
        kwargs: KeywordArgs,
        caller: Option<&Frame>,
    ) -> PyResult<Value> {
        let root = self.roots.len();
        let mut rv = args.clone();
        rv.push(fun.clone());
        rv.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        self.roots.push(rv);
        let result = (|| match fun.clone() {
            Value::Builtin(name) => self.builtin(&name, args, kwargs, caller),
            Value::Type(kind) => {
                if group_type_name(&kind) {return self.exception_group_construct(Value::Type(kind),args,kwargs);}
                if !kwargs.is_empty() {
                    return Err(pyerr(
                        "TypeError",
                        "exception does not take keyword arguments",
                    ));
                }
                let mut error = self.new_exception(&kind, args)?;
                Ok(self.exception_value(&mut error))
            }
            Value::Obj(i) => match self.object(i)? {
                Object::TypeEvaluator(value) => {
                    if args.len()>1 || kwargs.len()>1 {return Err(pyerr("TypeError","evaluator() takes at most one argument"));}
                    let format=args.first().cloned().or_else(||kwargs.iter().find(|(name,_)|name=="format").map(|(_,value)|value.clone()));
                    if kwargs.iter().any(|(name,_)|name!="format") || (!args.is_empty()&&!kwargs.is_empty()){return Err(pyerr("TypeError","invalid evaluator arguments"));}
                    if let Some(format)=format {if self.as_int(&format)?.to_usize()!=Some(1){return Err(pyerr("NotImplementedError","unsupported annotation format"));}}
                    Ok(value)
                }
                Object::GenericAlias { origin, .. } => {
                    let result=self.call(origin,args,kwargs,caller)?;
                    self.generic_finish_call(result,&Value::Obj(i))
                }
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
                    let previous=self.keyword_items(Value::Obj(keywords))?;
                    let kw=self.keyword_merge(previous,kwargs)?;
                    self.call(function, stored, kw, caller)
                }
                Object::Cached(cache) => self.cached_call(i, cache, args, kwargs, caller),
                Object::Function(function) => {
                    let frame = self.bind_function(&function, Value::Obj(i), args, kwargs)?;
                    if self.codes[function.code].is_generator {
                        return Ok(self.obj_value(Object::Generator(Box::new(frame))));
                    }
                    match self.execute(frame)?.0 {
                        FrameExit::Return(v) | FrameExit::Yield(v) => Ok(v),
                    }
                }
                Object::Class(class) => {
                    if self.is_subclass(&fun,&Value::Type("BaseException".into()))? {return self.exception_subclass_call(fun,args,kwargs,caller);}
                    let obj=if let Some(new)=self.class_attribute_lookup(&fun,"__new__") {
                        let new=self.bind_descriptor(new,None,fun.clone())?;
                        let mut incoming=vec![fun.clone()];incoming.extend(args.clone());
                        self.call(new,incoming,kwargs.clone(),caller)?
                    }else {
                        let attrs=self.alloc(Object::Dict(Vec::new()));
                        self.obj_value(Object::Instance{class:fun.clone(),attrs})
                    };
                    // type.__call__ only initializes a result of the requested
                    // type (or a subtype); an unrelated return value is final.
                    let actual=self.native_receiver_class(&obj);
                    if self.is_subclass(&actual,&fun)? {
                        if let Some(init)=self.class_attribute_lookup(&actual,"__init__") {
                            let init=self.bind_descriptor(init,Some(obj.clone()),actual)?;
                            let result=self.call(init,args,kwargs,caller)?;
                            if !matches!(result,Value::None){return Err(pyerr("TypeError","__init__() should return None"));}
                        }
                    }
                    Ok(obj)
                }
                Object::Instance { class, .. } => {
                    if let Some(method) = self.slot_override(&class, "__call__", 0) {
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
        kw: KeywordArgs,
    ) -> PyResult<Value> {
        if args.len() < 3 {
            return Err(pyerr("TypeError", "type() takes 1 or 3 arguments"));
        }
        let name_value=args[0].clone();
        let name = match self.native_payload(&name_value).unwrap_or_else(||name_value.clone()) {
            Value::Str(name) => name,
            _ => return Err(pyerr("TypeError", "type() argument 1 must be str")),
        };
        if name.contains('\0'){return Err(pyerr("ValueError","type name must not contain null characters"));}
        let mut bases = self.to_vec(args[1].clone())?;
        if bases.iter().any(|base|!matches!(base,Value::Builtin(_)|Value::Type(_)) && !matches!(base,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))))){return Err(pyerr("TypeError","bases must be types"));}
        for base in &bases {if matches!(base,Value::Builtin(name)if template_type_name(name)){return Err(pyerr("TypeError",format!("type '{}' is not an acceptable base type",self.class_name(base))));}}
        if bases.is_empty() {
            bases.push(Value::Builtin("object".into()))
        }
        let mut solid = None;
        for base in &bases {
            if let Some(layout) = self.solid_layout(base) {
                if let Some(previous) = &solid {
                    if !self.is_subclass(&layout, previous)?
                        && !self.is_subclass(previous, &layout)?
                    {
                        return Err(pyerr(
                            "TypeError",
                            "multiple bases have instance lay-out conflict",
                        ));
                    }
                }
                solid = Some(layout);
            }
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
        for (key,value) in &mut items {
            if matches!(key,Value::Str(name)if name=="__new__")&&matches!(value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Function(_)))) {
                *value=self.obj_value(Object::Static(value.clone()));
            }
            if matches!(key,Value::Str(name)if name=="__class_getitem__"||name=="__init_subclass__") && matches!(value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Function(_)))) {
                *value=self.obj_value(Object::ClassMethod(value.clone()));
            }
        }
        if items
            .iter()
            .any(|(key, _)| matches!(key, Value::Str(name) if name == "__eq__"))
            && !items
                .iter()
                .any(|(key, _)| matches!(key, Value::Str(name) if name == "__hash__"))
        {
            items.push((Value::Str("__hash__".into()), Value::None));
        }
        if !items.iter().any(|(key,_)|matches!(key,Value::Str(name)if name=="__qualname__")) {
            items.push((Value::Str("__qualname__".into()),name_value.clone()));
        }
        if let Some((_,qualname))=items.iter().find(|(key,_)|matches!(key,Value::Str(name)if name=="__qualname__")) {
            if !matches!(self.native_payload(qualname).unwrap_or_else(||qualname.clone()),Value::Str(_)) {
                return Err(pyerr("TypeError",format!("type __qualname__ must be a str, not {}",self.typename(qualname))));
            }
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
        let declared_slots = items.iter().find_map(|(key, value)| {
            if matches!(key, Value::Str(key) if key == "__slots__") {
                Some(value.clone())
            } else {
                None
            }
        });
        let inherited_dict = bases.iter().any(|base| self.class_allows_dict(base));
        let inherited_weakref = bases.iter().any(|base| self.class_allows_weakref(base));
        let mut slot_names = Vec::new();
        if let Some(slots) = declared_slots.clone() {
            let slots = match slots {
                Value::Str(name) => vec![Value::Str(name)],
                value => self.to_vec(value)?,
            };
            let mut dictionary_slot = inherited_dict;
            let mut weakref_slot = inherited_weakref;
            for value in slots {
                let slot = match value {
                    Value::Str(name) => name,
                    _ => return Err(pyerr("TypeError", "__slots__ items must be strings")),
                };
                if !text_is_identifier(&slot) {
                    return Err(pyerr("TypeError", "__slots__ must be identifiers"));
                }
                let slot = Self::slot_mangle(&name, &slot);
                if slot == "__dict__" {
                    if dictionary_slot {
                        return Err(pyerr(
                            "TypeError",
                            "__dict__ slot disallowed: we already got one",
                        ));
                    }
                    dictionary_slot = true;
                } else if slot == "__weakref__" {
                    if weakref_slot {
                        return Err(pyerr("TypeError", "__weakref__ slot disallowed"));
                    }
                    weakref_slot = true;
                }
                if items
                    .iter()
                    .any(|(key, _)| matches!(key, Value::Str(key) if key == &slot))
                {
                    return Err(pyerr(
                        "ValueError",
                        format!("'{}' in __slots__ conflicts with class variable", slot),
                    ));
                }
                slot_names.push(slot);
            }
            if !slot_names.is_empty() {
                for base in &bases {
                    if self.is_subclass(base, &Value::Builtin("tuple".into()))?
                        || self.is_subclass(base, &Value::Builtin("int".into()))?
                    {
                        return Err(pyerr(
                            "TypeError",
                            "nonempty __slots__ not supported for this subtype",
                        ));
                    }
                }
            }
        }
        let dict_allowed = inherited_dict
            || declared_slots.is_none()
            || slot_names.iter().any(|name| name == "__dict__");
        let weakref_allowed = inherited_weakref
            || declared_slots.is_none()
            || slot_names.iter().any(|name| name == "__weakref__");
        if declared_slots.is_none() {
            if !inherited_dict && !items.iter().any(|(key,_)|matches!(key,Value::Str(name)if name=="__dict__")) {
                slot_names.push("__dict__".into());
            }
            if !inherited_weakref && !items.iter().any(|(key,_)|matches!(key,Value::Str(name)if name=="__weakref__")) {
                slot_names.push("__weakref__".into());
            }
        }
        if !items.iter().any(|(key,_)|matches!(key,Value::Str(name)if name=="__doc__")){
            items.push((Value::Str("__doc__".into()),Value::None));
        }
        let ns = self.alloc(Object::Dict(items));
        let out = self.obj_value(Object::Class(Class {
            name,
            name_value,
            bases,
            attrs: ns,
            metaclass,
            dict_allowed,
            weakref_allowed,
        }));
        let root = self.roots.len();
        self.roots.push(vec![out.clone()]);
        let result = (|| {
            self.initialize_generic_class(&out)?;
            for name in slot_names {
                let slot = self.next_slot;
                self.next_slot += 1;
                let descriptor = self.obj_value(Object::Slot {
                    owner: out.clone(),
                    name: name.clone(),
                    slot,
                });
                self.ns_set(ns, name, descriptor);
            }
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
            let named_items=self.dict_items(Value::Obj(ns))?;
            let named_roots=named_items.iter().flat_map(|(name,value)|[name.clone(),value.clone()]).collect();
            self.view_rooted(named_roots,|runtime,_|{
                for (name,value) in named_items {
                    // __set_name__ is looked up on the descriptor's type;
                    // instance __getattr__ and instance attributes are ignored.
                    if let Some(class)=runtime.object_class(&value) {
                        if let Some(method)=runtime.class_lookup(&class,"__set_name__",0) {
                            let setname=runtime.bind_descriptor(method,Some(value),class)?;
                            runtime.call(setname,vec![out.clone(),name],Vec::new(),None)?;
                        }
                    }
                }
                Ok(())
            })?;
            let mro=self.class_mro(&out,0).ok_or_else(||pyerr("TypeError","invalid class MRO"))?;
            let mut hook=None;
            for base in mro.into_iter().skip(1){
                if let Value::Obj(index)=base{
                    if let Object::Class(class)=self.object(index)?{
                        if let Some(method)=self.ns_get(class.attrs,"__init_subclass__"){
                            hook=Some(self.bind_descriptor(method,None,out.clone())?);
                            break;
                        }
                    }
                }
            }
            if let Some(hook)=hook{self.call(hook,Vec::new(),kw.clone(),None)?;}
            else if !kw.is_empty(){return Err(pyerr("TypeError","__init_subclass__() takes no keyword arguments"));}
            Ok(out)
        })();
        self.roots.truncate(root);
        result
    }
    fn merge_keyword_arguments(&mut self,left:Value,right:Value)->PyResult<Value>{self.merge_mapping_arguments(left,right,true)}
    fn merge_mapping_arguments(&mut self,left:Value,right:Value,reject_duplicates:bool)->PyResult<Value>{
        self.view_rooted(vec![left.clone(),right.clone()],|runtime,root|{
            let out=left;runtime.roots[root].push(out.clone());
            let Value::Obj(owner)=out else{unreachable!()};
            let payload=if let Some(payload)=runtime.native_payload(&right){
                if runtime.object_class(&right).and_then(|class|runtime.slot_override(&class,"__iter__",0)).is_none(){payload}else{right.clone()}
            }else{right.clone()};
            let direct=if let Value::Obj(index)=payload{
                match runtime.object(index)?{Object::Dict(items)=>Some((index,items)),Object::Namespace(items,_)=>Some((index,items.ident_items())),_=>None}
            }else{None};
            if let Some((source,items))=direct{
                if runtime.assoc_size(owner)==0 && runtime.dictionary_can_clone(source,false){runtime.dictionary_clone_into(owner,source)?;return Ok(Value::Obj(owner));}
                let check_duplicates=reject_duplicates&&runtime.assoc_size(owner)!=0;
                for(index,(key,value))in items.into_iter().enumerate(){
                    let hash=runtime.dictionary_entry_hash(source,index,&key)?;
                    if check_duplicates{
                        if runtime.dictionary_find_known(owner,&[],&key,hash)?.is_some(){return Err(pyerr("TypeError","multiple values for keyword argument"));}
                    }
                    runtime.dictionary_set_known(owner,key,value,hash)?;
                }
            }else{
                let keys=match runtime.getattr(right.clone(),"keys"){
                    Ok(keys)=>keys,
                    Err(error) if runtime.exception_has_native_class(&error,"AttributeError")=>return Err(pyerr("TypeError",format!("argument after ** must be a mapping, not {}",runtime.typename(&right)))),
                    Err(error)=>return Err(error),
                };
                let keys=runtime.call(keys,Vec::new(),Vec::new(),None)?;
                runtime.roots[root].push(keys.clone());
                let keys=runtime.to_vec(keys)?;runtime.roots[root].extend(keys.iter().cloned());
                for key in keys{
                    let hash=if reject_duplicates{Some(runtime.frozen_member_hash(&key)?)}else{None};
                    let previous=runtime.dict_items(Value::Obj(owner))?;
                    if let Some(hash)=hash{if runtime.dictionary_find_known(owner,&previous,&key,hash)?.is_some(){return Err(pyerr("TypeError","multiple values for keyword argument"));}}
                    let value=runtime.getitem(right.clone(),key.clone())?;runtime.roots[root].push(value.clone());
                    let hash=runtime.frozen_member_hash(&key)?;
                    runtime.dictionary_set_known(owner,key,value,hash)?;
                }
            }
            Ok(Value::Obj(owner))
        })
    }
    fn make_class(&mut self,owner:Value,name:Value,bases:Vec<Value>,mut kw:KeywordArgs,caller:Option<&Frame>)->PyResult<Value> {
        let root=self.roots.len();let mut roots=bases.clone();roots.extend([owner.clone(),name.clone()]);
        roots.extend(kw.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        if let Some(frame)=caller {Self::frame_roots(frame,&mut roots);}
        self.roots.push(roots);
        let result=(||{
        let original_bases=self.obj_value(Object::Tuple(bases.clone()));
        self.roots[root].push(original_bases.clone());
        let mut resolved_bases=Vec::new();let mut bases_changed=false;
        for base in bases {
            let is_type=matches!(&base,Value::Builtin(_) | Value::Type(_)) || matches!(&base,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))));
            if is_type {resolved_bases.push(base);continue;}
            let entries=match self.getattr(base.clone(),"__mro_entries__"){
                Ok(entries)=>entries,
                Err(error) if self.exception_has_native_class(&error,"AttributeError")=>{resolved_bases.push(base);continue;},
                Err(error)=>return Err(error),
            };
            let entries=self.call(entries,vec![original_bases.clone()],Vec::new(),caller)?;
            let payload=self.native_payload(&entries).unwrap_or(entries);
            if let Value::Obj(index)=payload {if let Object::Tuple(values)=self.object(index)? {self.roots[root].extend(values.iter().cloned());resolved_bases.extend(values);bases_changed=true;continue;}}
            return Err(pyerr("TypeError","__mro_entries__ must return a tuple"));
        }
        let bases=resolved_bases;
        let lookup=Value::Str("metaclass".into());let lookup_hash=self.frozen_member_hash(&lookup)?;
        let mut meta_index=None;
        for(index,(key,_))in kw.iter().enumerate(){
            let hash=if let Some(hash)=key.hash{hash}else{self.frozen_member_hash(&key.original)?};
            if hash==lookup_hash&&self.identical_or_equal(&key.original,&lookup)?{meta_index=Some(index);break;}
        }
        let mut metaclass=meta_index.map(|index|kw.remove(index).1).unwrap_or(Value::Builtin("type".into()));
        let metaclass_is_type=matches!(&metaclass,Value::Type(_))||matches!(&metaclass,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))))||matches!(&metaclass,Value::Builtin(name)if ["type","object","int","bool","float","str","bytes","list","tuple","dict","set","complex"].contains(&name.as_str()));
        if metaclass_is_type{
            for base in &bases{
                let base_meta=self.object_class(base).filter(|_|matches!(base,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))))).unwrap_or(Value::Builtin("type".into()));
                if self.is_subclass(&metaclass,&base_meta)?{continue;}
                if self.is_subclass(&base_meta,&metaclass)?{metaclass=base_meta;continue;}
                return Err(pyerr("TypeError","metaclass conflict: the metaclass of a derived class must be a subclass of the metaclasses of all its bases"));
            }
        }
        let keywords=kw;
        let basesvalue = self.obj_value(Object::Tuple(bases.clone()));
        self.roots[root].push(basesvalue.clone());
        let prepare=match self.getattr(metaclass.clone(), "__prepare__"){
            Ok(prepare)=>Some(prepare),
            Err(error) if self.exception_has_native_class(&error,"AttributeError")=>None,
            Err(error)=>return Err(error),
        };
        let namespace = if let Some(prepare) = prepare {
            let v = self.call(
                prepare,
                vec![name.clone(), basesvalue.clone()],
                keywords.clone(),
                caller,
            )?;
            match v {
                Value::Obj(i) => i,
                _ => return Err(pyerr("TypeError", "__prepare__ must return a mapping")),
            }
        } else {
            self.alloc(Object::Dict(Vec::new()))
        };
        self.roots[root].push(Value::Obj(namespace));
        // __mro_entries__ and __prepare__ can replace the body function's code
        // or defaults. Read its current state immediately before execution.
        let function=match owner {Value::Obj(index)=>match self.object(index)? {Object::Function(function)=>function,_=>unreachable!()},_=>unreachable!()};
        let code=function.code;
        let parent=function.closure;
        let env = self.alloc(Object::Namespace(OrderedNamespace::new(), parent));
        self.scope_parents.insert(namespace, env);
        self.scope_bindings
            .insert(namespace, self.codes[code].locals.clone());
        if self.codes[code].kind!=ScopeKind::Class {
            // Public __build_class__ accepts any function. Ordinary calls retain
            // binding, defaults, and unstarted-generator semantics.
            self.call(owner,Vec::new(),Vec::new(),caller)?;
        }else{
        let frame = Frame {
            function: Some(owner),
            generator_names: None,
            code_handle: self.code_object_index(code),
            code,
            pc: 0,
            locals: namespace,
            temps: self.alloc(Object::Namespace(OrderedNamespace::new(), None)),
            globals: function.globals,
            builtins: function.builtins.clone(),
            closure: Some(env),
            stack: Vec::new(),
            handlers: Vec::new(),
            pending: Vec::new(),
            exception: None,
            exception_stack: Vec::new(),
                inherited_exception: None,
                except_star: Vec::new(),
            next_call: None,
            cache_returns: Vec::new(),
            comprehensions: Vec::new(),
            resume_value: None,
            injected_exception: None,
            finally_regions: Vec::new(),
        };
        self.execute(frame)?;
        }
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
        if self.codes[code].kind==ScopeKind::Class && (self.code_needs_class_dict(code,0) || (has_method && self.codes[code].future_flags & 0x1000000 == 0)) {
            let cell = self.obj_value(Object::Cell(Some(Value::Obj(namespace))));
            self.mapping_set(namespace, "__classdictcell__".into(), cell)?;
        }
        let needs_cell = self.codes[code].kind==ScopeKind::Class && methods.iter().any(|i| self.code_needs_class_cell(*i, 0));
        let classcell = if needs_cell {
            let cell = self.alloc(Object::Cell(None));
            self.mapping_set(namespace, "__classcell__".into(), Value::Obj(cell))?;
            Some(cell)
        } else {
            None
        };
        if bases_changed {self.mapping_set(namespace,"__orig_bases__".into(),original_bases)?;}
        let cls = self.call(
            metaclass,
            vec![name, basesvalue, Value::Obj(namespace)],
            keywords,
            caller,
        )?;
        if let Some(cell) = classcell.filter(|_|matches!(&cls,Value::Type(_))||matches!(&cls,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))))||matches!(&cls,Value::Builtin(name)if ["type","object","int","bool","float","str","bytes","list","tuple","dict","set","frozenset","complex","typing.Generic","string.templatelib.Template","string.templatelib.Interpolation"].contains(&name.as_str()))) {
            match self.object(cell)?{
                Object::Cell(Some(value)) if value.same_identity(&cls)=>{},
                Object::Cell(Some(_))=>return Err(pyerr("TypeError","__class__ set to a different object when defining class")),
                _=>{
                return Err(pyerr(
                    "RuntimeError",
                    "__class__ not set; was __classcell__ propagated to type.__new__?",
                ));
                }
            }
        }
        let class_binding=if let Some(cell)=classcell{match self.object(cell)?{Object::Cell(value)=>value,_=>None}}else{Some(cls.clone())};
        if let Some(value)=class_binding{self.ns_set(env,"__class__".into(),value);}
        if let Value::Obj(index)=&cls {if let Object::Class(class)=self.object(*index)?{self.annotation_namespaces.insert(namespace,class.attrs);}}
        Ok(cls)
        })();self.roots.truncate(root);result
    }
    fn as_exception(&mut self, v: Value) -> PyResult<PyException> {
        match v {
            Value::Type(kind) => {
                let mut error = self.new_exception(&kind, Vec::new())?;
                self.exception_value(&mut error);
                Ok(error)
            }
            Value::Obj(i) => match self.object(i)? {
                Object::Exception(mut e) => {
                    e.value = Some(Value::Obj(i));
                    e.message = self.exception_cached_message(&e)?;
                    Ok(e)
                }
                Object::Instance { class, .. } => {
                    if !self.is_subclass(&class, &Value::Type("BaseException".into()))? {
                        return Err(pyerr(
                            "TypeError",
                            "exceptions must derive from BaseException",
                        ));
                    }
                    let kind = self.typename(&Value::Obj(i));
                    let message = self.str_value(&Value::Obj(i))?;
                    let _ = class;
                    let mut error = pyerr(&kind, message);
                    error.value = Some(Value::Obj(i));
                    Ok(error)
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
            "Exception" | "BaseExceptionGroup" | "GeneratorExit" | "SystemExit" | "KeyboardInterrupt" => "BaseException",
            "ExceptionGroup" => "Exception",
            "ArithmeticError" | "AssertionError" | "AttributeError" | "EOFError"
            | "ImportError" | "LookupError" | "NameError" | "OSError" | "RuntimeError"
            | "StopIteration" | "SyntaxError" | "TypeError" | "ValueError" => "Exception",
            "ZeroDivisionError" | "OverflowError" => "ArithmeticError",
            "IndexError" | "KeyError" => "LookupError",
            "ModuleNotFoundError" => "ImportError",
            "UnboundLocalError" => "NameError",
            "RecursionError" | "NotImplementedError" => "RuntimeError",
            "UnicodeEncodeError" | "UnicodeDecodeError" | "UnicodeTranslateError" => "UnicodeError",
            "UnicodeError" => "ValueError",
            "IndentationError"=>"SyntaxError",
            "TabError"=>"IndentationError",
            _ => "",
        }
    }
    fn exception_match(&mut self,a:&Value,b:&Value)->PyResult<bool> {
        if let Value::Obj(index)=b {if let Some(Object::Tuple(items))=self.heap.get(*index).and_then(Option::as_ref) {let items=items.clone();for item in items {if self.exception_match(a,&item)?{return Ok(true);}}return Ok(false);}}
        let valid=matches!(b,Value::Type(_))||matches!(b,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_))));
        if !valid || !self.is_subclass(b,&Value::Type("BaseException".into()))? {return Err(pyerr("TypeError","catching classes that do not inherit from BaseException is not allowed"));}
        let actual=if matches!(a,Value::Type(_)){a.clone()}else if let Some(class)=self.exception_actual_class(a).or_else(||self.object_class(a)){class}else{self.getattr(a.clone(),"__class__")?};
        self.is_subclass(&actual,b)
    }
    fn str_value(&mut self, v: &Value) -> PyResult<String> {
        if let Some(payload)=self.proxy_payload(v) {return self.str_value(&payload);}
        match v {
            Value::Str(s) => Ok(s.to_string()),
            Value::None => Ok("None".into()),
            Value::Bool(b) => Ok(if *b { "True" } else { "False" }.into()),
            Value::Int(n) => Ok(n.to_string()),
            Value::Complex(number) => Ok(complex_repr(**number)),
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
                Object::Exception(e) => {
                    if let Some(class)=&e.class {if let Some(method)=self.slot_override(class,"__str__",0){let method=self.bind_descriptor(method,Some(v.clone()),class.clone())?;let result=self.call(method,Vec::new(),Vec::new(),None)?;if let Value::Str(text)=result{return Ok(text.to_string());}return Err(pyerr("TypeError","__str__ returned non-string"));}}
                    self.exception_object_message(&e)
                },
                Object::Instance { .. } | Object::BuiltinInstance { .. } => {
                    if let Ok(fun) = self.special_method(v.clone(), "__str__") {
                        let r = self.call(fun, Vec::new(), Vec::new(), None)?;
                        if let Value::Str(s) = r {
                            return Ok(s.to_string());
                        }
                        return Err(pyerr("TypeError", "__str__ returned non-string"));
                    }
                    if let Some(payload) = self.native_payload(v) {
                        if let Some(class) = self.object_class(v) {
                            if self.slot_override(&class, "__repr__", 0).is_some() {
                                return self.repr(v);
                            }
                        }
                        if matches!(&payload, Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Set(_) | Object::FrozenSet{..})))
                        {
                            return self.repr(v);
                        }
                        return self.str_value(&payload);
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
        if let Some(result)=self.template_repr(v,seen){return result;}
        match v {
            Value::Str(s) => Ok(text_repr_str(s)),
            Value::Bytes(xs) => Ok(text_repr_bytes(xs)),
            Value::Obj(i) => {
                if seen.contains(i) {
                    return Ok(match self.heap.get(*i).and_then(Option::as_ref) {
                        Some(Object::DictView { .. })=>"...",
                        Some(Object::Dict(_) | Object::Namespace(..))=>"{...}",
                        Some(Object::Tuple(_))=>"(...)",
                        Some(Object::MappingProxy { .. })=>"mappingproxy({...})",
                        _=>"[...]",
                    }.into());
                }
                seen.push(*i);
                let s = match self.object(*i)? {
                    Object::Template{..}|Object::Interpolation{..}=>unreachable!(),
                    Object::TypeParameter(_) | Object::TypeAlias{..} | Object::TypeUnpack(_) | Object::UnpackedAlias(_) | Object::ParamSpecMarker{..} | Object::TypeEvaluator(_) | Object::ForwardRef{..} | Object::TypeUnion{..} => self.typing_repr(v).unwrap()?,
                    Object::GenericAlias { origin, args, .. } => self.generic_repr(&origin,&args)?,
                    Object::DictView { owner, kind } => self.dictview_repr(owner,Some(kind),seen)?,
                    Object::MappingProxy { owner } => if let Some(keeper)=self.collection_keepers.get(i).cloned(){format!("mappingproxy({})",self.repr_inner(&keeper,seen)?)}else{self.dictview_repr(owner,None,seen)?},
                    Object::FrozenSet{..}=>self.frozen_repr(v,seen)?,
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
                        let entries: Vec<_> = m.into_iter().collect();
                        for (k, v) in entries {
                            ss.push(format!(
                                "{}: {}",
                                self.repr(&Value::Str(k.into()))?,
                                self.repr_inner(&v, seen)?
                            ))
                        }
                        format!("{{{}}}", ss.join(", "))
                    }
                    Object::Function(fun) => {
                        let name=match self.native_payload(&fun.qualname).unwrap_or(fun.qualname){Value::Str(name)=>name,_=>unreachable!("validated function qualname")};
                        format!("<function {}>",name)
                    },
                    Object::Class(c) => format!("<class '{}'>", c.name),
                    Object::Module { name, .. } => format!("<module '{}'>", name),
                    Object::Exception(e) => {
                        if let Some(class)=&e.class {if let Some(method)=self.slot_override(class,"__repr__",0){let method=self.bind_descriptor(method,Some(v.clone()),class.clone())?;let result=self.call(method,Vec::new(),Vec::new(),None)?;if let Value::Str(text)=result{return Ok(text.to_string());}return Err(pyerr("TypeError","__repr__ returned non-string"));}}
                        if e.group.is_some() {self.exception_group_repr(&e,seen)?}else{
                        let mut args = Vec::new();
                        for argument in &e.args {
                            args.push(self.repr_inner(argument, seen)?);
                        }
                        format!("{}({})", self.exception_type_name(&e), args.join(", "))
                        }
                    }
                    Object::BuiltinInstance { payload, .. } => {
                        if self.frozen_owner(&payload).is_some_and(|(_,frozen)|frozen) && self.object_class(v).and_then(|class|self.slot_override(&class,"__repr__",0)).is_none(){self.frozen_repr(v,seen)?}else{
                        if let Ok(fun) = self.special_method(v.clone(), "__repr__") {
                            let result = self.call(fun, Vec::new(), Vec::new(), None)?;
                            self.str_value(&result)?
                        } else {
                            let text = self.repr_inner(&payload, seen)?;
                            if let Value::Obj(index) = &payload {
                                if let Some(Object::Set(values)) =
                                    self.heap.get(*index).and_then(Option::as_ref)
                                {
                                    format!(
                                        "{}({})",
                                        self.typename(v),
                                        if values.is_empty() { "" } else { &text }
                                    )
                                } else {
                                    text
                                }
                            } else {
                                text
                            }
                        }
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
                    Object::Slice(a, b, c) => format!("slice({}, {}, {})", a.map(|value|value.to_string()).unwrap_or_else(||"None".into()), b.map(|value|value.to_string()).unwrap_or_else(||"None".into()), c.map(|value|value.to_string()).unwrap_or_else(||"None".into())),
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
                    Object::ExceptStarState(_) => "<except* state>".into(),
                    Object::ExecutionLocals(value)=>self.repr_inner(&value,seen)?,
                    Object::Cell(_) => "<cell>".into(),
                    Object::Code(_) => "<code object>".into(),
                    Object::Slot { owner, name, .. } => format!(
                        "<member '{}' of '{}' objects>",
                        name,
                        self.class_name(&owner)
                    ),
                    Object::Range(a, b, c) => {
                        if c == Int::exact_small(1) {
                            format!("range({}, {})", a, b)
                        } else {
                            format!("range({}, {}, {})", a, b, c)
                        }
                    }
                };
                seen.pop();
                Ok(s)
            }
            Value::Builtin(n) => {
                if template_type_name(n){return Ok(format!("<class '{}'>",n));}
                if n=="typing.NoDefault" {return Ok("typing.NoDefault".into());}
                if n=="typing.Unpack" {return Ok("typing.Unpack".into());}
                if n=="NoneType" {return Ok("<class 'NoneType'>".into());}
                if typing_type_name(n) {return Ok(format!("<class '{}'>",n));}
                if n=="GenericAlias" {return Ok("<class 'types.GenericAlias'>".into());}
                if n == "Ellipsis" || n == "NotImplemented" {
                    Ok(n.clone())
                } else if n == "functools.Placeholder" {
                    Ok("Placeholder".into())
                } else if [
                    "bool",
                    "int",
                    "float",
                    "complex",                    "str",
                    "bytes",
                    "bytearray",
                    "list",
                    "tuple",
                    "dict",
                    "set",
                    "frozenset",
                    "dict_keys", "dict_values", "dict_items", "mappingproxy", "GenericAlias",
                    "slice",
                    "range",
                    "type",
                    "object",
                    "property",
                    "staticmethod",
                    "classmethod",
                    "enumerate",
                    "map",
                    "filter",
                    "zip",
                    "reversed",
                    "super",
                ]
                .contains(&n.as_str())
                {
                    Ok(format!("<class '{}'>", n))
                } else {
                    Ok(format!("<built-in function {}>", n))
                }
            }
            Value::Type(n) => Ok(format!("<class '{}'>", n)),
            _ => self.str_value(v),
        }
    }
    fn format_value(&mut self, v: Value, spec: &str) -> PyResult<String> {
        if let Value::Complex(number)=&v{return self.complex_format(**number,spec);}
        if matches!(v, Value::Int(_) | Value::Bool(_)) {
            let number = self.as_int(&v)?;
            if let Some(result) = number.format_integer(spec).map_err(int_error)? {
                if spec.is_empty() && matches!(v, Value::Bool(_)) {
                    return self.str_value(&v);
                }
                return Ok(result);
            }
            let value = Value::Float(self.as_float(&v)?.into());
            return self.text_format_value(value, spec).unwrap();
        }
        if let Some(result) = self.text_format_value(v.clone(), spec) {
            return result;
        }
        if let Ok(method) = self.special_method(v.clone(), "__format__") {
            let result = self.call(method, vec![Value::Str(spec.into())], Vec::new(), None)?;
            return match result {
                Value::Str(text) => Ok(text.to_string()),
                _ => Err(pyerr("TypeError", "__format__ must return a str")),
            };
        }
        if let Some(payload) = self.native_payload(&v) {
            return self.format_value(payload, spec);
        }
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
            Value::Complex(_) => "complex".into(),
            Value::Str(_) => "str".into(),
            Value::Bytes(_) => "bytes".into(),
            Value::Builtin(n) => {
                if template_type_name(n){return "type".into();}
                if n=="typing.NoDefault" {return "NoDefaultType".into();}
                if typing_type_name(n) || n=="NoneType" {return "type".into();}
                if n == "Ellipsis" {
                    return "ellipsis".into();
                }
                if n == "functools.Placeholder" {
                    return "_PlaceholderType".into();
                }
                if [
                    "int", "str", "list", "tuple", "dict", "set", "float", "complex", "bool", "type",
                    "object", "bytes", "dict_keys", "dict_values", "dict_items", "mappingproxy", "GenericAlias", "staticmethod", "classmethod", "property",
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
                Some(Object::Static(_))=>"staticmethod".into(),
                Some(Object::ClassMethod(_))=>"classmethod".into(),
                Some(Object::Property{..})=>"property".into(),
                Some(Object::Template{..})=>"string.templatelib.Template".into(),
                Some(Object::Interpolation{..})=>"string.templatelib.Interpolation".into(),
                Some(Object::Iterator(IteratorState::Template(..)))=>"TemplateIter".into(),
                Some(Object::TypeParameter(parameter)) => match parameter.kind.as_str(){"paramspec"=>"ParamSpec","typevartuple"=>"TypeVarTuple",_=>"TypeVar"}.into(),
                Some(Object::TypeAlias{..})=>"TypeAliasType".into(),
                Some(Object::TypeUnpack(_))=>"_UnpackGenericAlias".into(),
                Some(Object::UnpackedAlias(_))=>"GenericAlias".into(),
                Some(Object::ParamSpecMarker{kind,..})=>if kind=="args"{"ParamSpecArgs"}else{"ParamSpecKwargs"}.into(),
                Some(Object::TypeEvaluator(_))=>"constevaluator".into(),
                Some(Object::ForwardRef{..})=>"ForwardRef".into(),
                Some(Object::TypeUnion{..})=>"Union".into(),
                Some(Object::List(_)) => "list".into(),
                Some(Object::Tuple(_)) => "tuple".into(),
                Some(Object::GenericAlias { typing, .. }) => if *typing{"_GenericAlias"}else{"GenericAlias"}.into(),
                Some(Object::DictView { kind, .. }) => kind.name().into(),
                Some(Object::MappingProxy { .. }) => "mappingproxy".into(),
                Some(Object::Iterator(IteratorState::Associative(state))) => if state.is_set {"set_iterator".into()}else{format!("dict_{}{}iterator",if state.reversed {"reverse"}else{""},match state.kind{DictViewKind::Keys=>"key",DictViewKind::Values=>"value",DictViewKind::Items=>"item"})},
                Some(Object::Dict(_)) | Some(Object::Namespace(..)) => "dict".into(),
                Some(Object::Set(_)) => "set".into(),
                Some(Object::FrozenSet{..})=>"frozenset".into(),
                Some(Object::Function(_)) => "function".into(),
                Some(Object::Class(_)) => "type".into(),
                Some(Object::Instance {
                    class: Value::Obj(c),
                    ..
                }) => match self.heap.get(*c).and_then(|o| o.as_ref()) {
                    Some(Object::Class(c)) => c.name.to_string(),
                    _ => "object".into(),
                },
                Some(Object::BuiltinInstance {
                    class: Value::Obj(c),
                    ..
                }) => match self.heap.get(*c).and_then(|o| o.as_ref()) {
                    Some(Object::Class(c)) => c.name.to_string(),
                    _ => "object".into(),
                },
                Some(Object::Exception(e)) => self.exception_type_name(e),
                Some(Object::Generator(_)) => "generator".into(),
                Some(Object::Module { .. }) => "module".into(),
                Some(Object::Iterator(_)) => "iterator".into(),
                Some(Object::Slice(..)) => "slice".into(),
                Some(Object::ExceptStarState(_)) => "except* state".into(),
                Some(Object::ExecutionLocals(value))=>self.typename(value),
                Some(Object::Cell(_)) => "cell".into(),
                Some(Object::Range(..)) => "range".into(),
                Some(Object::Record { name, .. }) => name.clone(),
                Some(Object::Slot { .. }) => "member_descriptor".into(),
                _ => "object".into(),
            },
        }
    }
    fn as_int(&mut self, v: &Value) -> PyResult<Int> {
        // PyLong subclasses already provide their integer value for structural
        // __index__ conversions; a Python __index__ does not replace it.
        if let Some(Value::Int(number))=self.native_payload(v){return Ok(number.into_inner());}
        match v {
            Value::Int(n) => Ok(n.inner().clone()),
            Value::Bool(b) => Ok(Int::from_i128(if *b { 1 } else { 0 })),
            _ => {
                match self.special_method(v.clone(), "__index__") {
                    Ok(method)=>{
                        let result=self.call(method,Vec::new(),Vec::new(),None)?;
                        if let Value::Int(number)=result {return Ok(number.into_inner());}
                    }
                    Err(error) if self.missing_special_method(v,"__index__",&error)=>{},
                    Err(error)=>return Err(error),
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
        if let Some(payload) = self.native_payload(v) {
            return self.as_float(&payload);
        }
        let n = match v {
            Value::Float(f) => return Ok(**f),
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
                Some(Object::List(xs) | Object::Tuple(xs) | Object::Set(xs) | Object::FrozenSet{items:xs,..}) => {
                    return Ok(!xs.is_empty())
                }
                Some(Object::MappingProxy { owner }) => {if let Some(keeper)=self.collection_keepers.get(i).cloned(){return self.truth(&keeper);}return Ok(self.assoc_size(*owner)!=0);},
                Some(Object::DictView { owner, .. }) => return Ok(self.assoc_size(*owner)!=0),
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
            Value::Complex(n) => n.real!=0.0 || n.imag!=0.0,
            Value::Str(s) => !s.is_empty(),
            Value::Bytes(b) => !b.is_empty(),
            Value::Obj(i) => match self.object(*i)? {
                Object::List(v) | Object::Tuple(v) | Object::Set(v) | Object::FrozenSet{items:v,..} => !v.is_empty(),
                Object::Dict(v) => !v.is_empty(),
                Object::Namespace(v, _) => !v.is_empty(),
                Object::Range(a, b, step) => range_nonempty(&a, &b, &step),
                Object::Instance { .. } | Object::BuiltinInstance { .. } => {
                    match self.special_method(v.clone(),"__bool__") {
                        Ok(fun)=>match self.call(fun,Vec::new(),Vec::new(),None)? {Value::Bool(value)=>value,_=>return Err(pyerr("TypeError","__bool__ should return bool"))},
                        Err(error) if self.exception_has_native_class(&error,"AttributeError")=>match self.special_method(v.clone(),"__len__") {
                            Ok(fun)=>{let value=self.call(fun,Vec::new(),Vec::new(),None)?;self.protocol_length(&value)?!=0},
                            Err(error) if self.missing_special_method(v,"__len__",&error)=>true,
                            Err(error)=>return Err(error),
                        },
                        Err(error)=>return Err(error),
                    }
                }
                _ => true,
            },
            _ => true,
        })
    }
    fn contains_vec(&mut self, vs: &[Value], v: &Value) -> PyResult<bool> {
        for x in vs {
            if self.identical_or_equal(x, v)? {
                return Ok(true);
            }
        }
        Ok(false)
    }
    fn equal_default(&mut self, a: &Value, b: &Value) -> PyResult<bool> {
        if let Some(result)=self.typing_equal(a,b){return result;}
        if let Some(result)=self.view_compare("==",a,b) {return result;}
        if let Some(result)=self.generic_equal(a,b) {return result;}
        if let Some(result)=self.frozen_compare("==",a,b){return result;}
        let ap=self.proxy_payload(a);let bp=self.proxy_payload(b);
        if ap.is_some() || bp.is_some() {return self.equal_default(ap.as_ref().unwrap_or(a),bp.as_ref().unwrap_or(b));}
        if let (Value::Obj(left),Value::Obj(right))=(a,b) {
            if matches!(self.heap.get(*left).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..))) && matches!(self.heap.get(*right).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..))) {return self.assoc_mapping_equal(*left,*right);}
        }
        if let (Value::Obj(left), Value::Obj(right)) = (a, b) {
            if let (Object::Range(a, b, s), Object::Range(c, d, t)) =
                (self.object(*left)?, self.object(*right)?)
            {
                return Ok(range_equal((&a, &b, &s), (&c, &d, &t)));
            }
        }
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
        if let Some(equal)=self.complex_equal(a,b){return Ok(equal);}
        match (a, b) {
            (Value::None, Value::None) => Ok(true),
            (Value::Bool(a), Value::Bool(b)) => Ok(a == b),
            (Value::Int(a), Value::Int(b)) => Ok(a == b),
            (Value::Bool(a), Value::Int(b)) | (Value::Int(b), Value::Bool(a)) => {
                Ok(Int::from_i128(if *a { 1 } else { 0 }) == **b)
            }
            (Value::Float(a), Value::Float(b)) => Ok(a == b),
            (Value::Int(a), Value::Float(b)) | (Value::Float(b), Value::Int(a)) => {
                if !b.is_finite() || b.fract() != 0.0 {
                    return Ok(false);
                }
                Ok(a.cmp_f64(**b) == Some(std::cmp::Ordering::Equal))
            }
            (Value::Bool(a), Value::Float(b)) | (Value::Float(b), Value::Bool(a)) => {
                Ok((if *a { 1.0 } else { 0.0 }) == **b)
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
                        if !self.identical_or_equal(x, y)? {
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
                            if self.identical_or_equal(&k, k2)? {
                                if !self.identical_or_equal(&v, v2)? {
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
            (Value::Int(a), Value::Float(b)) => Ok(a.cmp_f64(**b).unwrap_or(Ordering::Equal)),
            (Value::Float(a), Value::Int(b)) => Ok(b
                .cmp_f64(**a)
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
                        if !self.identical_or_equal(x, y)? {
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
        if let Some(result)=self.view_compare(op,a,b) {return result;}
        if let Some(result)=self.frozen_compare(op,a,b){return result;}
        let ap=self.proxy_payload(a);let bp=self.proxy_payload(b);
        if ["==","!=","<","<=",">",">="].contains(&op) && (ap.is_some() || bp.is_some()) {return self.compare_default(op,ap.as_ref().unwrap_or(a),bp.as_ref().unwrap_or(b));}
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
            if let (Value::Obj(a),Value::Obj(b))=(a,b) {
                let sequences=match (self.object(*a)?,self.object(*b)?) {
                    (Object::List(a),Object::List(b)) | (Object::Tuple(a),Object::Tuple(b))=>Some((a,b)),_=>None,
                };
                if let Some((a,b))=sequences {
                    for (a,b) in a.iter().zip(&b) { if !self.identical_or_equal(a,b)? {return self.compare(op,a,b);} }
                    return Ok(match op {"<"=>a.len()<b.len(),"<="=>a.len()<=b.len(),">"=>a.len()>b.len(),_=>a.len()>=b.len()});
                }
            }
        }
        use std::cmp::Ordering::*;
        match op {
            "==" => self.equal_default(a, b),
            "!=" => Ok(!self.equal_default(a, b)?),
            "is" | "is not" => {
                let eq = a.same_identity(b);
                Ok(if op == "is" { eq } else { !eq })
            }
            "in" | "not in" => {
                if let Value::Obj(index) = b {
                    if let Object::Range(start, stop, step) = self.object(*index)? {
                        let found = self.range_contains(start.into_inner(), stop.into_inner(), step.into_inner(), a.clone())?;
                        return Ok(if op == "in" { found } else { !found });
                    }
                }
                let yes = match (a, b) {
                    (Value::Str(x), Value::Str(y)) => y.contains(x.as_str()),
                    _ => {
                        match self.special_method(b.clone(),"__contains__") {
                            Ok(fun)=>{let value=self.call(fun,vec![a.clone()],Vec::new(),None)?;self.truth(&value)?},
                            Err(error) if self.exception_has_native_class(&error,"AttributeError")=>{let values=self.to_vec(b.clone())?;self.contains_vec(&values,a)?},
                            Err(error)=>return Err(error),
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
            Value::Complex(number)=>match op {"+"=>Ok(a),"-"=>Ok(Value::Complex(Complex::new(-number.real,-number.imag).into())),_=>Err(pyerr("TypeError","bad operand type for complex"))},
            Value::Int(n) => Ok(Value::Int(match op {
                "+" => n.clone(),
                "-" => n.neg().into(),
                "~" => n.invert().into(),
                _ => return Err(pyerr("TypeError", "unsupported unary operator")),
            })),
            Value::Bool(_) => {
                let n = self.as_int(&a)?;
                self.unary(op, Value::Int(n.into()))
            }
            Value::Float(x) => match op {
                "+" => Ok(a),
                "-" => Ok(Value::Float((-**x).into())),
                _ => Err(pyerr("TypeError", "bad operand type")),
            },
            _ => {
                let name = match op {
                    "+" => "__pos__",
                    "-" => "__neg__",
                    "~" => "__invert__",
                    _ => "",
                };
                match self.special_method(a.clone(), name) {
                    Ok(fun) => self.call(fun, Vec::new(), Vec::new(), None),
                    Err(error) if self.missing_special_method(&a,name,&error)=>{
                        if let Some(payload)=self.native_payload(&a){self.unary(op,if op=="+"{payload.fresh_primitive()}else{payload})}else{Err(error)}
                    },
                    Err(error)=>Err(error),
                }
            }
        }
    }
    fn binary(&mut self, op: &str, a: Value, b: Value) -> PyResult<Value> {
        if (op=="+" || op=="+=") && (self.is_template_value(&a) || self.is_template_value(&b)) {if let Some(result)=self.template_concat(a.clone(),b.clone()){return result;}}
        if let Some(result)=self.typing_binary(op,&a,&b){return result;}
        if let Some(result)=self.view_binary(op,a.clone(),b.clone()) {return result;}
        if let Some(result)=self.operand_binary(op,&a,&b){return result;}
        self.binary_default(op,a,b)
    }
    fn binary_default(&mut self, op: &str, a: Value, b: Value) -> PyResult<Value> {
        if (op=="+" || op=="+=") && (self.is_template_value(&a) || self.is_template_value(&b)) {if let Some(result)=self.template_concat(a.clone(),b.clone()){return result;}}
        if let Some(result)=self.typing_binary(op,&a,&b){return result;}
        if let Some(result)=self.view_binary(op,a.clone(),b.clone()) {return result;}
        let ap=self.proxy_payload(&a);let bp=self.proxy_payload(&b);
        if ap.is_some() || bp.is_some() {
            if op=="|=" && ap.is_some() {return Err(pyerr("TypeError","mappingproxy does not support in-place union"));}
            return self.binary(op,ap.unwrap_or(a),bp.unwrap_or(b));
        }
        if let Value::Obj(index)=&a {
            if op=="|=" && matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..))) {
                self.method("update",a.clone(),vec![b],Vec::new())?;return Ok(a);
            }
            if ["|=","&=","-=","^="].contains(&op) && matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Set(_))) {
                let result=self.binary(&op[..op.len()-1],a.clone(),b)?;
                if let Value::Obj(result)=result {self.heap[*index]=Some(self.object(result)?);self.frozen_transfer_hashes(result,*index);self.assoc_sync(*index)?;}
                return Ok(a);
            }
        }
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
                if let Some(fun) = self.slot_override(&class, method, 0) {
                    let fun = self.bind_descriptor(fun, Some(a.clone()), class)?;
                    let result = self.call(fun, vec![b.clone()], Vec::new(), None)?;
                    if !matches!(&result,Value::Builtin(n)if n=="NotImplemented") {
                        return Ok(result);
                    }
                }
            }
            if let Some(Value::Obj(index)) = self.native_payload(&a) {
                if matches!(
                    self.heap.get(index).and_then(Option::as_ref),
                    Some(Object::List(_) | Object::Dict(_) | Object::Set(_))
                ) {
                    if op == "|=" && matches!(self.heap[index], Some(Object::Dict(_))) {
                        self.method("update", Value::Obj(index), vec![b], Vec::new())?;
                    } else {
                        let result = self.binary(op, Value::Obj(index), b)?;
                        if let Value::Obj(result) = result {
                            self.heap[index] = Some(self.object(result)?);
                        }
                    }
                    return Ok(a);
                }
            }
        }
        if let Some(payload) = self.native_payload(&b) {
            if matches!(&a,Value::Obj(i)if matches!(self.heap.get(*i).and_then(|o|o.as_ref()),Some(Object::Tuple(_) | Object::List(_))))
                && ["+", "+="].contains(&op)
            {
                if let Some(class) = self.object_class(&b) {
                    if let Some(fun) = self.slot_override(&class, "__radd__", 0) {
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
                    if let Some(method) = self.slot_override(&bc, &format!("__r{}__", stem), 0) {
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
        if op == "kwargs_merge" {return self.merge_keyword_arguments(a,b);}
        if op=="dict_merge"{let copy=self.dictionary_copy(a)?;return self.merge_mapping_arguments(copy,b,false);}
        if let Some(result)=self.complex_binary(op,&a,&b){return result;}
        if let Some(result)=self.frozen_binary(op,&a,&b){return result;}
        if let (Value::Bool(left),Value::Bool(right))=(&a,&b) {
            let result=match op {"&"=>Some(*left & *right),"|"=>Some(*left | *right),"^"=>Some(*left ^ *right),_=>None};
            if let Some(result)=result{return Ok(Value::Bool(result));}
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
                        return Ok(Value::Float(self.as_float(&a)?.powf(self.as_float(&b)?).into()));
                    }
                    x.pow(&y).map_err(int_error)?
                }
                "/" => return Ok(Value::Float(x.ratio(&y).map_err(int_error)?.into())),
                _ => return Err(pyerr("TypeError", "unsupported integer operation")),
            };
            return Ok(Value::Int(n.into()));
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
                "**" => {if x<0.0 && x.is_finite() && y.is_finite() && y.fract()!=0.0 {return Ok(Value::Complex(Complex::new(x,0.0).pow(Complex::new(y,0.0))?.into()));}x.powf(y)},
                _ => return Err(pyerr("TypeError", "unsupported float operation")),
            };
            return Ok(Value::Float(z.into()));
        }
        match (&a, &b, op) {
            (Value::Str(x), Value::Str(y), "+" | "+=") => {
                return Ok(Value::Str(format!("{}{}", x, y).into()))
            }
            (Value::Bytes(x), Value::Bytes(y), "+") => {
                let mut z = x.inner().clone();
                z.extend(y);
                return Ok(Value::Bytes(z.into()));
            }
            (Value::Str(s), Value::Int(_) | Value::Bool(_), "*")
            | (Value::Int(_) | Value::Bool(_), Value::Str(s), "*") => {
                let v = if matches!(a, Value::Str(_)) { &b } else { &a };
                let n = self.as_int(v)?.to_i128().unwrap_or(i128::MAX).max(0);
                if n > 100_000_000 {
                    return Err(pyerr("OverflowError", "repeated string is too long"));
                }
                return Ok(Value::Str(s.repeat(n as usize).into()));
            }
            (Value::Str(fmt), _, "%") => {
                return Ok(Value::Str(self.percent_format(fmt, b.clone())?.into()))
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
                Object::Set(xs) if self.frozen_owner(&b).is_some() => {
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
                Object::Dict(_) if op=="|"=>{
                    let payload=self.native_payload(&b).unwrap_or_else(||b.clone());
                    if matches!(payload,Value::Obj(index)if matches!(self.heap.get(index).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..)))){let copy=self.dictionary_copy(a)?;return self.merge_mapping_arguments(copy,b,false);}
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
            match self.special_method(obj.clone(),&name) {
                Ok(fun)=>{let value=self.call(fun,vec![arg],Vec::new(),None)?;if !matches!(&value,Value::Builtin(name)if name=="NotImplemented"){return Ok(value);}},
                Err(error) if self.exception_has_native_class(&error,"AttributeError")=>{},
                Err(error)=>return Err(error),
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
            if self.identical_or_equal(k, key)? {
                return Ok(Some(i));
            }
        }
        Ok(None)
    }
    fn getitem(&mut self, obj: Value, key: Value) -> PyResult<Value> {
        self.view_rooted(vec![obj.clone(),key.clone()],|runtime,_|runtime.getitem_inner(obj,key))
    }
    fn getitem_inner(&mut self, obj: Value, key: Value) -> PyResult<Value> {
        if matches!(&obj,Value::Builtin(name)if template_type_name(name)){return self.generic_alias(obj,key);}
        if self.is_typing_value(&obj){if let Some(result)=self.typing_getitem(obj.clone(),key.clone()){return result;}}
        if self.generic_parts(&obj).is_some() {return self.generic_method(obj,"__getitem__",vec![key],Vec::new()).unwrap();}
        if matches!(&obj,Value::Builtin(name)if ["list","dict","tuple","set","frozenset","type"].contains(&name.as_str())) {return self.generic_alias(obj,key);}
        if let Value::Obj(index)=&obj {
            if let Object::Class(class)=self.object(*index)? {
                if self.slot_override(&class.metaclass,"__getitem__",0).is_some() {
                    let method=self.special_method(obj,"__getitem__")?;return self.call(method,vec![key],Vec::new(),None);
                }
                match self.getattr(obj.clone(),"__class_getitem__") {
                    Ok(method)=>return self.call(method,vec![key],Vec::new(),None),
                    Err(error) if error.kind=="AttributeError"=>{},Err(error)=>return Err(error),
                }
            }
        }
        if let Some(payload)=self.proxy_payload(&obj) {return self.getitem(payload,key);}
        if let Value::Obj(index) = &obj {
            if let Object::Range(start, stop, step) = self.object(*index)? {
                return self.range_getitem(start.into_inner(), stop.into_inner(), step.into_inner(), key);
            }
        }
        if let Value::Obj(i) = &obj {
            if let Object::BuiltinInstance { class, payload, .. } = self.object(*i)? {
                if self.slot_override(&class, "__getitem__", 0).is_some() {
                    let fun = self.special_method(obj, "__getitem__").map_err(|e| {
                        if e.kind == "AttributeError" {
                            pyerr("TypeError", "object is not subscriptable")
                        } else {
                            e
                        }
                    })?;
                    return self.call(fun, vec![key], Vec::new(), None);
                }
                if matches!(&payload,Value::Obj(owner)if matches!(self.heap.get(*owner).and_then(Option::as_ref),Some(Object::Dict(_)))) {return self.collection_dict_getitem(obj,key);}
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
                    Ok(Value::Str(chars[i].to_string().into()))
                }
            }
            Value::Bytes(xs) => {
                if let Some((a, b, c)) = slice {
                    let ids = self.slice_indices(a, b, c, xs.len())?;
                    Ok(Value::Bytes(ids.into_iter().map(|i| xs[i]).collect()))
                } else {
                    let i = self.index(&key, xs.len())?;
                    Ok(Value::Int(Int::from_i128(xs[i] as i128).into()))
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
                    if let Some(position) = self.dictionary_find(i,&items, &key)? {
                        let Object::Dict(current)=self.object(i)? else{unreachable!()};Ok(current[position].1.clone())
                    } else {
                        Err(self.new_exception("KeyError", vec![key])?)
                    }
                }
                Object::Namespace(m, _) => {
                    if let Value::Str(k) = &key {
                        if let Some(value) = m.get(k) {
                            return Ok(value.clone());
                        }
                    }
                    Err(self.new_exception("KeyError", vec![key])?)
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
        self.view_rooted(vec![obj.clone(),key.clone(),value.clone()],|runtime,_|runtime.setitem_inner(obj,key,value))
    }
    fn setitem_inner(&mut self, obj: Value, key: Value, value: Value) -> PyResult<()> {
        if let Value::Obj(index) = &obj {
            if let Object::BuiltinInstance { class, payload, .. } = self.object(*index)? {
                if let Some(method) = self.slot_override(&class, "__setitem__", 0) {
                    let method = self.bind_descriptor(method, Some(obj), class)?;
                    self.call(method, vec![key, value], Vec::new(), None)?;
                    return Ok(());
                }
                return self.setitem(payload, key, value);
            }
        }
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
                Object::Dict(_) => {
                    let hash=self.frozen_member_hash(&key)?;
                    return self.dictionary_set_known(i,key,value,hash);
                }
                Object::Namespace(_, _) => {
                    if let Value::Str(s) = key {
                        let mut inserted=false;
                        if let Some(Some(Object::Namespace(map, _))) = self.heap.get_mut(i) {
                            inserted=!map.contains_key(&s);map.insert_ident(s.clone(), value);
                        }
                        if inserted {self.assoc_inserted(i,Value::Str(s));}
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
        self.view_rooted(vec![obj.clone(),key.clone()],|runtime,_|runtime.delitem_inner(obj,key))
    }
    fn delitem_inner(&mut self, obj: Value, key: Value) -> PyResult<()> {
        if let Value::Obj(index) = &obj {
            if let Object::BuiltinInstance { class, payload, .. } = self.object(*index)? {
                if let Some(method) = self.slot_override(&class, "__delitem__", 0) {
                    let method = self.bind_descriptor(method, Some(obj), class)?;
                    self.call(method, vec![key], Vec::new(), None)?;
                    return Ok(());
                }
                return self.delitem(payload, key);
            }
        }
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
                        .dictionary_find(i,&items, &key)?
                        .ok_or_else(|| pyerr("KeyError", "key not found"))?;
                    let Object::Dict(mut items)=self.object(i)? else{unreachable!()};
                    let key=items.remove(j).0;self.dictionary_remove_entry_hash(i,j);
                    self.heap[i] = Some(Object::Dict(items));
                    self.assoc_dictionary_removed(i,j);
                    return Ok(());
                }
                Object::Namespace(_, _) => {
                    if let Value::Str(s) = key {
                        if self.ns_del(i, &s) {
                            return Ok(());
                        }
                        return Err(pyerr("KeyError", s.into_inner()));
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
                Object::Set(_)=>{self.set_insert_value(i,v,None)?;return Ok(());}
                _ => {}
            }
        }
        Err(pyerr("TypeError", "invalid container"))
    }
    fn dict_items(&mut self, v: Value) -> PyResult<Vec<(Value, Value)>> {
        if let Value::Obj(index)=&v {
            if let Object::BuiltinInstance { class, payload, .. }=self.object(*index)? {
                if self.slot_override(&class,"__iter__",0).is_none() && matches!(&payload,Value::Obj(owner)if matches!(self.heap.get(*owner).and_then(Option::as_ref),Some(Object::Dict(_)))) {return self.dict_items(payload);}
            }
        }
        if let Value::Obj(i) = v.clone() {
            match self.object(i)? {
                Object::MappingProxy { owner } => return self.dict_items(self.collection_keepers.get(&i).cloned().unwrap_or(Value::Obj(owner))),
                Object::Dict(xs) => return Ok(xs),
                Object::Namespace(m, _) => {
                    return Ok(m.ident_items())
                }
                Object::Module { attrs, .. } => return self.dict_items(Value::Obj(attrs)),
                _ => {}
            }
        }
        let keys=match self.getattr(v.clone(), "keys"){
            Ok(keys)=>Some(keys),
            Err(error) if self.exception_has_native_class(&error,"AttributeError")=>None,
            Err(error)=>return Err(error),
        };
        if let Some(keys)=keys{
            return self.view_rooted(vec![v.clone(),keys.clone()],|runtime,root|{
                let keys=runtime.call(keys,Vec::new(),Vec::new(),None)?;runtime.roots[root].push(keys.clone());
                let keys=runtime.to_vec(keys)?;runtime.roots[root].extend(keys.iter().cloned());let mut out=Vec::new();
                for key in keys{let value=runtime.getitem(v.clone(),key.clone())?;runtime.roots[root].push(value.clone());out.push((key,value));}
                Ok(out)
            });
        }
        self.view_rooted(vec![v.clone()],|runtime,root|{
            let pairs=runtime.to_vec(v)?;runtime.roots[root].extend(pairs.iter().cloned());let mut out=Vec::new();
            for pair in pairs{
                let pair=runtime.to_vec(pair)?;
                if pair.len()!=2{return Err(pyerr("ValueError","dictionary update sequence element has length other than 2"));}
                runtime.roots[root].extend(pair.iter().cloned());out.push((pair[0].clone(),pair[1].clone()));
            }
            Ok(out)
        })
    }
    fn keyword_items(&mut self, source: Value) -> PyResult<KeywordArgs> {
        self.view_rooted(vec![source.clone()],|runtime,root|{
            let owner=runtime.dictionary_owner(&source);
            let entries=runtime.dict_items(source)?;
            runtime.roots[root].extend(entries.iter().flat_map(|(key,value)|[key.clone(),value.clone()]));
            let mut out=Vec::new();
            for(index,(key,value))in entries.into_iter().enumerate(){
                if let Value::Str(text)=runtime.native_payload(&key).unwrap_or_else(||key.clone()){
                    let hash=if let Some(owner)=owner{Some(runtime.dictionary_entry_hash(owner,index,&key)?)}else{None};
                    out.push((KeywordName{spelling:text.into_inner(),original:key,hash},value));
                }else{return Err(pyerr("TypeError","keywords must be strings"));}
            }
            Ok(out)
        })
    }
    fn to_vec(&mut self, v: Value) -> PyResult<Vec<Value>> {
        let it = self.iter(v)?;
        let root = self.roots.len();
        self.roots.push(vec![it.clone()]);
        let result = (|| {
            let mut out = Vec::new();
            while let Some(v) = self.next(it.clone())? {
                self.roots[root].push(v.clone());
                out.push(v)
            }
            Ok(out)
        })();
        self.roots.truncate(root);
        result
    }
    fn iter(&mut self, v: Value) -> PyResult<Value> {
        if let Value::Obj(index)=&v {if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Template{..})){return Ok(self.obj_value(Object::Iterator(IteratorState::Template(*index,0))));}}
        if self.type_parameter_kind(&v)==Some("typevartuple") || matches!(&v,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::GenericAlias{..}))) {
            let unpack=if self.type_parameter_kind(&v)==Some("typevartuple") || self.generic_is_typing_alias(&v){self.obj_value(Object::TypeUnpack(v))}else{self.unpack_alias(v)?};return Ok(self.obj_value(Object::Iterator(IteratorState::Values(vec![unpack],0))));
        }
        if matches!(&v, Value::Builtin(name) if name.starts_with("stream:") || name.starts_with("streambuffer:"))
        {
            return Ok(v);
        }
        if let Value::Obj(i) = &v {
            if let Object::BuiltinInstance { class, payload, .. } = self.object(*i)? {
                if self.slot_override(&class,"__iter__",0).is_some() {
                    match self.special_method(v.clone(),"__iter__") {
                        Ok(fun)=>return self.call(fun,Vec::new(),Vec::new(),None),
                        Err(error) if self.exception_has_native_class(&error,"AttributeError")=>{
                            if self.slot_definition(&class,"__getitem__",0).is_some(){return Ok(self.obj_value(Object::Iterator(IteratorState::Reversed(v,-2))));}
                            return Err(pyerr("TypeError","object is not iterable"));
                        },
                        Err(error)=>return Err(error),
                    }
                }
                if self.frozen_owner(&payload).is_some_and(|(_,frozen)|frozen){return self.frozen_iterator(v);}
                let result=self.iter(payload)?;return Ok(self.collection_keep(result,v));
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
                IteratorState::Values(s.chars().map(|c| Value::Str(c.to_string().into())).collect(), 0)
            }
            Value::Bytes(s) => IteratorState::Values(
                s.into_iter()
                    .map(|x| Value::Int(Int::from_i128(x as i128).into()))
                    .collect(),
                0,
            ),
            Value::Obj(i) => match self.object(i)? {
                Object::Record { fields, .. } => {
                    IteratorState::Values(fields.into_iter().map(|(_, v)| v).collect(), 0)
                }
                Object::List(_) => IteratorState::List(i, 0),
                Object::Range(a, b, c) => IteratorState::Range(a.into_inner(), b.into_inner(), c.into_inner()),
                Object::Tuple(v) => IteratorState::Values(v, 0),
                Object::Dict(_) | Object::Namespace(..) | Object::Set(_) | Object::FrozenSet{..} => return self.assoc_iterator(i,DictViewKind::Keys,false),
                Object::DictView { owner, kind } => {let result=self.assoc_iterator(owner,kind,false)?;return Ok(self.collection_inherit_keeper(result,&v));},
                Object::MappingProxy { owner } => {if let Some(keeper)=self.collection_keepers.get(&i).cloned(){return self.iter(keeper);}let result=self.assoc_iterator(owner,DictViewKind::Keys,false)?;return Ok(self.collection_inherit_keeper(result,&v));},
                Object::Iterator(_) | Object::Generator(_) => return Ok(v),
                Object::Instance { .. } => {
                    match self.special_method(v.clone(),"__iter__") {
                        Ok(fun)=>return self.call(fun,Vec::new(),Vec::new(),None),
                        Err(error) if self.exception_has_native_class(&error,"AttributeError")=>{},
                        Err(error)=>return Err(error),
                    }
                    if self.object_class(&v).and_then(|class|self.slot_definition(&class,"__getitem__",0)).is_none(){return Err(pyerr("TypeError","object is not iterable"));}
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
    fn iterator_stop(&mut self, iterator: &Value) -> PyResult<PyException> {
        let mut value = None;
        if let Value::Obj(index) = iterator {
            if let Some(Object::Generator(frame)) = self.heap.get(*index).and_then(Option::as_ref) {
                let temps = frame.temps;
                value = self.ns_get(temps, "$generator_return");
                self.ns_del(temps, "$generator_return");
            }
        }
        let args = value
            .filter(|value| !matches!(value, Value::None))
            .into_iter()
            .collect();
        self.new_exception("StopIteration", args)
    }
    fn stop_value(error: &PyException) -> Value {
        error
            .attributes
            .get("value")
            .cloned()
            .unwrap_or_else(|| error.args.first().cloned().unwrap_or(Value::None))
    }
    fn iterator_next(&mut self, iterator: Value) -> PyResult<Value> {
        if let Value::Obj(index) = &iterator {
            if matches!(
                self.heap.get(*index).and_then(Option::as_ref),
                Some(Object::Instance { .. })
            ) {
                let method = self.special_method(iterator, "__next__")?;
                return self.call(method, Vec::new(), Vec::new(), None);
            }
        }
        match self.next_raw(iterator.clone())? {
            Some(value) => Ok(value),
            None => Err(self.iterator_stop(&iterator)?),
        }
    }
    fn next(&mut self, it: Value) -> PyResult<Option<Value>> {
        let result = match self.next_raw(it.clone()) {
            Ok(value)=>value,
            Err(error) if self.exception_has_native_class(&error,"StopIteration")=>None,
            Err(error)=>return Err(error),
        };
        if result.is_none() {
            self.iterator_stop(&it)?;
        }
        Ok(result)
    }
    fn next_raw(&mut self, it: Value) -> PyResult<Option<Value>> {
        if let Value::Builtin(name) = &it {
            if let Some((kind, target)) = name.split_once(':') {
                if kind == "stream" || kind == "streambuffer" {
                    let line = self.stream_call(
                        &format!("{}:readline", target),
                        Vec::new(),Vec::new(),
                        kind == "streambuffer",
                    )?;
                    return Ok(match &line {
                        Value::Str(value) if value.is_empty() => None,
                        Value::Bytes(value) if value.is_empty() => None,
                        _ => Some(line),
                    });
                }
            }
        }
        if let Value::Obj(i) = it.clone() {
            match self.object(i)? {
                Object::Iterator(state) => match state {
                    IteratorState::Template(owner,mut position) => {
                        let result=self.template_next(owner,&mut position);
                        self.heap[i]=Some(Object::Iterator(IteratorState::Template(owner,position)));return result;
                    }
                    IteratorState::Associative(mut state) => {
                        let result=self.assoc_next(&mut state);
                        self.heap[i]=Some(Object::Iterator(IteratorState::Associative(state)));
                        return result;
                    }
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
                        if !range_nonempty(&cur, &stop, &step) {
                            return Ok(None);
                        }
                        let value = cur.clone();
                        self.heap[i] = Some(Object::Iterator(IteratorState::Range(
                            range_cursor_next(&cur, &stop, &step),
                            stop,
                            step,
                        )));
                        return Ok(Some(Value::Int(value.into())));
                    }
                    IteratorState::Enumerate(inner, n) => {
                        if let Some(v) = self.next(inner.clone())? {
                            self.heap[i] = Some(Object::Iterator(IteratorState::Enumerate(
                                inner,
                                n.add(&Int::from_i128(1)),
                            )));
                            return Ok(Some(self.obj_value(Object::Tuple(vec![Value::Int(n.into()), v]))));
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
                        return if self.identical_or_equal(&v, &sentinel)? {
                            Ok(None)
                        } else {
                            Ok(Some(v))
                        };
                    }
                    IteratorState::Reversed(obj, p) => {
                        if p == -1 {return Ok(None);}
                        let k = if p <= -2 { -p - 2 } else { p };
                        let result =
                            self.getitem(obj.clone(), Value::Int(Int::from_i128(k as i128).into()));
                        match result {
                            Ok(v) => {
                                let np = if p <= -2 { p - 1 } else { p - 1 };
                                self.heap[i] =
                                    Some(Object::Iterator(IteratorState::Reversed(obj, np)));
                                return Ok(Some(v));
                            }
                            Err(e) if self.exception_has_native_class(&e, "IndexError") || self.exception_has_native_class(&e, "StopIteration") => {
                                self.heap[i]=Some(Object::Iterator(IteratorState::Reversed(Value::None,-1)));
                                return Ok(None);
                            },
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
                    let executed = self.execute(*frame);
                    self.running_generators.pop();
                    let (exit, mut f) = match executed {
                        Ok(result) => result,
                        Err(e) => {
                            if let Some(Object::Generator(frame)) =
                                self.heap.get_mut(i).and_then(|o| o.as_mut())
                            {
                                frame.pc = usize::MAX;
                            }
                            if self.exception_has_native_class(&e, "StopIteration") {
                                let mut original = e;
                                let value = self.exception_value(&mut original);
                                let mut error =
                                    pyerr("RuntimeError", "generator raised StopIteration");
                                error.cause = Some(value.clone());
                                error.context = Some(value);
                                error.suppress_context = true;
                                return Err(error);
                            }
                            return Err(e);
                        }
                    };
                    match exit {
                        FrameExit::Yield(v) => {
                            self.heap[i] = Some(Object::Generator(Box::new(f)));
                            return Ok(Some(v));
                        }
                        FrameExit::Return(value) => {
                            self.ns_set(f.temps, "$generator_return".into(), value);
                            f.pc = usize::MAX;
                            self.heap[i] = Some(Object::Generator(Box::new(f)));
                            return Ok(None);
                        }
                    }
                }
                Object::Instance { .. } => {
                    let fun = self.special_method(it, "__next__")?;
                    match self.call(fun, Vec::new(), Vec::new(), None) {
                        Ok(v) => return Ok(Some(v)),
                        Err(e) if self.exception_has_native_class(&e, "StopIteration") => return Ok(None),
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
            Value::Type(n) if n=="ExceptionGroup" => vec![Value::Type("BaseExceptionGroup".into()),Value::Type("Exception".into())],
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
        if let Some(result)=self.bind_native_attribute(v.clone(),instance.clone(),class.clone()){return result;}
        if matches!(&v,Value::Builtin(name)if name.starts_with("exception_type:")&&!name.ends_with(":__new__")) {
            return Ok(if let Some(instance)=instance{self.obj_value(Object::Bound(v,instance))}else{v});
        }
        if matches!(&v,Value::Builtin(name)if name.starts_with("unbound:str:")){
            if let Some(instance)=instance{return Ok(self.obj_value(Object::Bound(v,instance)));}
            return Ok(v);
        }
        if let Value::Obj(i) = v.clone() {
            match self.object(i)? {
                Object::Slot { .. } => {
                    if let Some(instance) = instance {
                        return self.slot_access(v, instance, None, false);
                    }
                }
                Object::Static(v) => return Ok(v),
                Object::ClassMethod(v) => return Ok(self.obj_value(Object::Bound(v, class))),
                Object::Property { get, .. } => {
                    if let Some(o) = instance {
                        return self.call(get, vec![o], Vec::new(), None);
                    }
                }
                Object::Function(_) | Object::Cached(_) => {
                    if let Some(o) = instance {
                        return Ok(self.obj_value(Object::Bound(v, o)));
                    }
                }
                Object::Instance { class: c, .. } => {
                    if let Some(fun) = self.slot_override(&c, "__get__", 0) {
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
        if let Some(result)=self.native_attribute_meta(v.clone(),name){return result;}
        if ["__and__","__rand__","__or__","__ror__","__xor__","__rxor__"].contains(&name)
            && (matches!(&v,Value::Bool(_)|Value::Int(_)) || matches!(&v,Value::Builtin(owner)if owner=="bool")) {
            let class=Value::Builtin(if matches!(&v,Value::Int(_)){"int"}else{"bool"}.into());
            if let Some(descriptor)=self.class_attribute_lookup(&class,name) {
                let instance=if matches!(&v,Value::Builtin(_)){None}else{Some(v)};
                return self.bind_descriptor(descriptor,instance,class);
            }
        }
        if matches!(&v,Value::Builtin(owner)if ["dict","list","tuple","set","frozenset","str","int","complex","object","type"].contains(&owner.as_str())) && !["__class__","__dict__","__name__","__qualname__","__mro__","__bases__","__module__","__annotations__","__annotate__","__type_params__"].contains(&name) {
            if let Some(value)=self.class_attribute_lookup(&v,name){return self.bind_descriptor(value,None,v);}
            return Err(pyerr("AttributeError",format!("type has no attribute '{name}'")));
        }
        if matches!(&v,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::FrozenSet{..}))) || matches!(&v,Value::Builtin(class)if class=="frozenset"){if let Some(result)=self.frozen_attr(v.clone(),name){return result;}}
        if name=="from_number" || matches!(&v,Value::Complex(_)) || matches!(&v,Value::Builtin(class)if class=="complex"){if let Some(result)=self.complex_attr(v.clone(),name){return result;}}
        if self.is_exception_value(&v) || matches!(&v,Value::Type(_)){if let Some(result)=self.exception_group_attr(v.clone(),name){return result;}}
        if self.is_template_value(&v){if let Some(result)=self.template_attr(v.clone(),name){return result;}}
        if name=="__class__" && matches!(&v,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::GenericAlias{typing:true,..}))) {return Ok(Value::Builtin("typing._GenericAlias".into()));}
        if self.is_typing_value(&v){if let Some(result)=self.typing_attr(v.clone(),name){return result;}}
        if name=="__class_getitem__" && matches!(&v,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_)))) && self.slot_override(&v,name,0).is_none() && self.typing_class_uses_typing(&v) {
            return Ok(self.obj_value(Object::Bound(Value::Builtin("method:__class_getitem__".into()),v)));
        }
        if matches!(&v,Value::Builtin(value)if value=="GenericAlias") && name=="__module__" {return Ok(Value::Str("types".into()));}
        if let Some(result)=self.dictview_attr(v.clone(),name) {return result;}
        if let Some(result)=self.generic_attr(v.clone(),name) {return result;}
        if name=="__class_getitem__" && (matches!(&v,Value::Builtin(name)if ["list","dict","tuple","set","frozenset","type"].contains(&name.as_str())) || (matches!(&v,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_)))) && self.slot_override(&v,name,0).is_none() && self.class_mro(&v,0).unwrap_or_default().iter().any(|base|matches!(base,Value::Builtin(name)if ["list","dict","tuple","set","frozenset","type"].contains(&name.as_str()))))) {
            return Ok(self.obj_value(Object::Bound(Value::Builtin("method:__class_getitem__".into()),v)));
        }
        if name == "__len__" && matches!(v, Value::Str(_) | Value::Bytes(_)) {
            return Ok(self.obj_value(Object::Bound(Value::Builtin("method:__len__".into()), v)));
        }
        if name == "__format__"
            && matches!(
                v,
                Value::Int(_) | Value::Bool(_) | Value::Float(_) | Value::Complex(_) | Value::Str(_)
            )
        {
            return Ok(self.obj_value(Object::Bound(Value::Builtin("method:__format__".into()), v)));
        }
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
                            | Object::Cached(_)
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
                    "__setitem__", "__delitem__",
                    "get",
                    "keys",
                    "values",
                    "items",
                    "pop",
                    "popitem",
                    "__reversed__",
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
                    "difference_update", "intersection_update", "symmetric_difference_update",
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
                    Object::Exception(e) => e.class.clone().unwrap_or_else(||Value::Type(e.kind.clone())),
                    _ => Value::Builtin(self.typename(&v)),
                },
                _ => Value::Builtin(self.typename(&v)),
            });
        }
        if let Value::Obj(i) = v.clone() {
            match self.object(i)? {
                Object::Code(code) => match name {
                    "co_name" => return self.code_constant(code,Const::Str(self.codes[code].name.clone())),
                    "co_qualname" => return self.code_constant(code,Const::Str(self.codes[code].qualname.clone())),
                    "co_flags" => return Ok(Value::Int(Int::from_i128(self.codes[code].future_flags as i128).into())),
                    _ => {},
                },
                Object::Range(start, stop, step) => match name {
                    "start" => return Ok(Value::Int(start.into())),
                    "stop" => return Ok(Value::Int(stop.into())),
                    "step" => return Ok(Value::Int(step.into())),
                    "count" | "index" | "__iter__" | "__len__" | "__getitem__" | "__contains__"
                    | "__reversed__" => {
                        return Ok(self.obj_value(Object::Bound(
                            Value::Builtin(format!("method:{}", name)),
                            v,
                        )))
                    }
                    _ => {}
                },
                Object::Slot {
                    owner,
                    name: slot_name,
                    ..
                } => {
                    if name == "__name__" {
                        return Ok(Value::Str(slot_name.into()));
                    }
                    if name == "__objclass__" {
                        return Ok(owner);
                    }
                    if name == "__doc__" {
                        return Ok(Value::None);
                    }
                    let action = match name {
                        "__get__" => Some("get"),
                        "__set__" => Some("set"),
                        "__delete__" => Some("delete"),
                        _ => None,
                    };
                    if let Some(action) = action {
                        return Ok(self.obj_value(Object::Bound(
                            Value::Builtin(format!("slot:{}", action)),
                            v,
                        )));
                    }
                }
                Object::Cell(value) => {
                    if name == "cell_contents" {
                        return value.ok_or_else(|| pyerr("ValueError", "Cell is empty"));
                    }
                }
                Object::Bound(function, receiver) => {
                    if let Some((kind,owner,method))=native_attribute_parts(&function) {
                        let (kind,owner,method)=(kind.to_owned(),owner.to_owned(),method.to_owned());
                        if name=="__func__" {return Err(pyerr("AttributeError","built-in method has no __func__"));}
                        if name=="__objclass__"&&kind=="wrapper" {return Ok(Value::Builtin(owner));}
                        if name=="__qualname__"&&["method","class"].contains(&kind.as_str()) {
                            let class=if kind=="class"{receiver.clone()}else{self.native_receiver_class(&receiver)};
                            let qualname=self.getattr_default(class,"__qualname__")?;
                            return Ok(Value::Str(format!("{}.{}",self.str_value(&qualname)?,method).into()));
                        }
                    }
                    if name == "__self__" {
                        return Ok(receiver);
                    }
                    if name == "__func__" {
                        return Ok(function);
                    }
                    if name == "__name__" || name == "__qualname__"
                        || matches!(&function,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Cached(_))))
                    {
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
                    if name == "__dict__" { return Ok(Value::Obj(attrs)); }
                    if name=="__annotations__" {
                        if let Some(value)=self.global_name_get(attrs,name)?{return Ok(value);}
                        let annotations=if let Some(annotate)=self.global_name_get(attrs,"__annotate__")?.filter(|value|!matches!(value,Value::None)) {
                            self.call(annotate,vec![Value::Int(Int::from_i128(1).into())],Vec::new(),None)?
                        }else{self.obj_value(Object::Dict(Vec::new()))};
                        if !matches!(&annotations,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..)))){return Err(pyerr("TypeError","__annotate__ must return a dictionary"));}
                        self.global_name_set(attrs,name.into(),annotations.clone())?;return Ok(annotations);
                    }
                    if let Some(x) = self.global_name_get(attrs, name)? {
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
                                Object::Exception(error) => error.class.clone().unwrap_or_else(||Value::Type(error.kind.clone())),
                                Object::Class(_) => if self.is_subclass(&recv,&c)?{recv.clone()}else{self.native_receiver_class(&recv)},
                                _ => recv.clone(),
                            },
                            _ => recv.clone(),
                        };
                        let mro = self
                            .class_mro(&actual, 0)
                            .ok_or_else(|| pyerr("TypeError", "invalid super object"))?;
                        if let Some(pos) = mro.iter().position(|v| Self::same_type(v, &c)) {
                            for base in mro.into_iter().skip(pos + 1) {
                                if let Some(value)=self.class_own_attribute(&base,name) {
                                    return self.bind_descriptor(value,Some(recv),actual);
                                }
                            }
                        }
                        return Err(pyerr("AttributeError", name));
                    }
                    if name == "__dict__" && self.slot_override(&class,name,0).is_none() {
                        if !self.instance_allows_dict(i) {
                            return Err(pyerr("AttributeError", "object has no __dict__"));
                        }
                        return Ok(Value::Obj(attrs));
                    }
                    let descriptor=self.class_attribute_lookup(&class,name);
                    if let Some(value)=descriptor.as_ref().filter(|value|self.attribute_is_data(value)) {
                        return self.bind_descriptor(value.clone(),Some(v),class);
                    }
                    if let Some(value)=self.ns_get(attrs,name){return Ok(value);}
                    if let Some(value)=descriptor{return self.bind_descriptor(value,Some(v),class);}
                    if name == "__init__" {
                        if let Some(payload) = self.native_payload(&v) {
                            let owner = self.typename(&payload);
                            return Ok(self.obj_value(Object::Bound(
                                Value::Builtin(format!("type_method:{}:__init__", owner)),
                                v,
                            )));
                        }
                    }
                    if let Object::BuiltinInstance { payload, .. } = self.object(i)? {
                        if let Ok(value) = self.getattr_default(payload, name) {
                            return Ok(match value {
                                Value::Obj(index) => match self.object(index)? {
                                    Object::Bound(function, _) => {
                                        self.obj_value(Object::Bound(function, v.clone()))
                                    }
                                    _ => Value::Obj(index),
                                },
                                value => value,
                            });
                        }
                    }
                    if let Some(x) = self.slot_override(&class, "__getattr__", 0) {
                        let fun = self.obj_value(Object::Bound(x, v));
                        return self.call(fun, vec![Value::Str(name.into())], Vec::new(), None);
                    }
                }
                Object::Class(c) => {
                    let meta_attribute=self.class_attribute_lookup(&c.metaclass,name);
                    if let Some(value)=meta_attribute.as_ref().filter(|value|self.attribute_is_data(value)&&!matches!(native_attribute_parts(value),Some((_,"type",_)))) {
                        return self.bind_descriptor(value.clone(),Some(v),c.metaclass);
                    }
                    if name=="__annotate__" {
                        return Ok(self.ns_get(c.attrs,"__annotate_func__").or_else(||self.ns_get(c.attrs,name)).unwrap_or(Value::None));
                    }
                    if name=="__annotations__" {
                        if let Some(annotations)=self.ns_get(c.attrs,name) {return Ok(annotations);}
                        let annotations=if let Some(annotate)=self.ns_get(c.attrs,"__annotate_func__").or_else(||self.ns_get(c.attrs,"__annotate__")).filter(|value|!matches!(value,Value::None)) {
                            self.call(annotate,vec![Value::Int(Int::from_i128(1).into())],Vec::new(),None)?
                        }else{self.obj_value(Object::Dict(Vec::new()))};
                        self.ns_set(c.attrs,name.into(),annotations.clone());return Ok(annotations);
                    }
                    if name == "__mro__" {
                        let mro = self
                            .class_mro(&v, 0)
                            .ok_or_else(|| pyerr("TypeError", "invalid method resolution order"))?;
                        return Ok(self.obj_value(Object::Tuple(mro)));
                    }
                    if name == "__name__" {
                        return Ok(c.name_value.clone());
                    }
                    if name == "__qualname__" {
                        return Ok(self
                            .ns_get(c.attrs, "__qualname__")
                            .unwrap_or(c.name_value));
                    }
                    if name == "__dict__" {
                        return Ok(self.obj_value(Object::MappingProxy { owner: c.attrs }));
                    }
                    if name == "__bases__" {
                        return Ok(self.obj_value(Object::Tuple(c.bases)));
                    }
                    if let Some(value)=self.class_attribute_lookup(&v,name){return self.bind_descriptor(value,None,v);}
                    if let Some(value)=meta_attribute{return self.bind_descriptor(value,Some(v.clone()),c.metaclass);}
                    if name=="__annotate__" {return Ok(Value::None);}
                }
                Object::Function(fun) => match name {
                    "__name__" => return Ok(fun.name),
                    "__qualname__" => return Ok(fun.qualname),
                    "__module__" => return Ok(fun.module),
                    "__doc__" => return Ok(fun.doc),
                    "__annotations__" => {
                        if !fun.annotations_evaluated {
                            let annotations = if let Some(annotate) = fun.annotate.clone() {
                                self.call(
                                    annotate,
                                    vec![Value::Int(Int::from_i128(1).into())],
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
                    "__builtins__" => return Ok(fun.builtins),
                    "__code__" => return Ok(self.code_object(fun.code)),
                    "__defaults__" => {
                        return Ok(if !fun.defaults_set {
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
                                    .map(|(n, v)| (Value::Str(n.into()), v))
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
                Object::Exception(mut e) => {
                    if name=="__dict__"{let attrs=self.exception_dict(&mut e);self.sync_exception(&e);return Ok(Value::Obj(attrs));}
                    if name == "args" {
                        if let Some(value) = e.0.args_tuple {
                            return Ok(value);
                        }
                        let value = self.obj_value(Object::Tuple(e.args.clone()));
                        e.args_tuple = Some(value.clone());
                        self.heap[i] = Some(Object::Exception(e));
                        return Ok(value);
                    }
                    if self.exception_native_attribute(&e,name){return Ok(e.attributes.get(name).cloned().unwrap_or(Value::None));}
                    if !["__cause__","__context__","__suppress_context__","__traceback__"].contains(&name){if let Some(value)=e.dict.and_then(|index|self.ns_get(index,name)){return Ok(value);}}
                    if let Some(value) = e.attributes.get(name) {
                        return Ok(value.clone());
                    }
                    match name {
                        "__cause__" => return Ok(e.0.cause.unwrap_or(Value::None)),
                        "__context__" => return Ok(e.0.context.unwrap_or(Value::None)),
                        "__suppress_context__" => return Ok(Value::Bool(e.suppress_context)),
                        "__traceback__" => {
                            let traceback = self.exception_traceback(&e);
                            e.attributes
                                .insert("__traceback__".into(), traceback.clone());
                            self.heap[i] = Some(Object::Exception(e));
                            return Ok(traceback);
                        }
                        _ => {}
                    }
                }
                Object::Generator(frame) if matches!(name,"__name__"|"__qualname__"|"gi_code") => {
                    if name=="gi_code" {return Ok(self.code_object(frame.code));}
                    let names=match self.object(frame.generator_names.expect("generator names"))?{Object::Tuple(names)=>names,_=>unreachable!()};
                    return Ok(names[usize::from(name=="__qualname__")].clone());
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
                            "difference_update", "intersection_update", "symmetric_difference_update",
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
                    "isidentifier",
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
                    && ["__iter__", "__next__"].contains(&name)
                {
                    return Ok(self
                        .obj_value(Object::Bound(Value::Builtin(format!("method:{}", name)), v)));
                }
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
                if name == "__name__" || name=="__qualname__" {
                    return Ok(Value::Str(n.rsplit(':').next().unwrap_or(n).to_owned().into()));
                }
                if name=="__module__" {
                    return Ok(Value::Str(if n=="GenericAlias" {"types".into()}else if let Some(rest)=n.strip_prefix("module:"){rest.split(':').next().unwrap_or("builtins").into()}else{"builtins".into()}));
                }
                if name == "__mro__" {
                    if let Some(mro) = self.class_mro(&v, 0) {
                        return Ok(self.obj_value(Object::Tuple(mro)));
                    }
                }
                if n == "object"
                    && name=="__init_subclass__"{
                    return Ok(self.obj_value(Object::Bound(Value::Builtin("type_method:object:__init_subclass__".into()),v)));
                }
                if n == "object"
                    && ["__getattribute__", "__setattr__", "__delattr__"].contains(&name)
                {
                    return Ok(Value::Builtin(format!("type_method:object:{}", name)));
                }
                if n=="str" && ["__hash__","__eq__","__ne__","__str__","__repr__"].contains(&name){return Ok(Value::Builtin(format!("unbound:str:{name}")));}
                if n=="dict" && ["copy","pop","popitem","clear","setdefault","__contains__","__reversed__"].contains(&name){
                    return Ok(Value::Builtin(format!("unbound:dict:{}",name)));
                }
                if ["int", "str", "bytes", "list", "tuple", "dict", "set"].contains(&n.as_str())
                    && [
                        "__getitem__",
                        "__setitem__",
                        "__delitem__",
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
        if self.is_exception_value(&v){if let Some(class)=self.object_class(&v){if let Some(method)=self.slot_override(&class,"__getattr__",0){let bound=self.bind_descriptor(method,Some(v),class)?;return self.call(bound,vec![Value::Str(name.into())],Vec::new(),None);}}}
        Err(pyerr(
            "AttributeError",
            format!("'{}' object has no attribute '{}'", self.typename(&v), name),
        ))
    }
    fn setattr_default(&mut self, obj: Value, name: &str, value: Value) -> PyResult<()> {
        if matches!(&obj,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Class(_)))) {
            if let Some(meta)=self.object_class(&obj) {if let Some(descriptor)=self.class_attribute_lookup(&meta,name) {
                if self.attribute_is_data(&descriptor)&&!matches!(native_attribute_parts(&descriptor),Some((_,"type",_))) {
                    let setter=self.getattr(descriptor,"__set__")?;
                    self.call(setter,vec![obj,value],Vec::new(),None)?;return Ok(());
                }
            }}
        }
        if self.is_exception_value(&obj) {
            if let Some(class)=self.object_class(&obj) {
                if let Some(descriptor)=self.slot_override(&class,name,0) {
                    if let Value::Obj(index)=&descriptor {
                        match self.object(*index)? {
                            Object::Slot{..}=>{self.slot_access(descriptor,obj,Some(value),false)?;return Ok(());}
                            Object::Property{set,..}=>{let set=set.ok_or_else(||pyerr("AttributeError","property has no setter"))?;self.call(set,vec![obj,value],Vec::new(),None)?;return Ok(());}
                            _=>{}
                        }
                    }
                    if let Ok(set)=self.getattr(descriptor,"__set__"){self.call(set,vec![obj,value],Vec::new(),None)?;return Ok(());}
                }
            }
        }
        if let Value::Obj(index)=&obj {
            if let Object::TypeParameter(mut parameter)=self.object(*index)? {
                let protected=["__name__","__default__"].contains(&name) || (parameter.kind!="typevartuple" && ["__bound__","__constraints__","__infer_variance__","__covariant__","__contravariant__"].contains(&name));
                if protected{return Err(pyerr("AttributeError",format!("attribute '{}' is not writable",name)));}
                if name=="__module__" {parameter.module=value;self.heap[*index]=Some(Object::TypeParameter(parameter));}else{self.ns_set(parameter.attrs,name.into(),value);}
                return Ok(());
            }
        }
        if let Value::Obj(i) = obj.clone() {
            match self.object(i)? {
                Object::Exception(mut error) => {
                    if error.group.is_some() && ["message","exceptions"].contains(&name){return Err(pyerr("AttributeError",format!("readonly attribute: {}",name)));}
                    match name {
                        "value"|"code" if self.exception_native_attribute(&error,name)=>{error.attributes.insert(name.into(),value);}
                        "__dict__"=>{let Value::Obj(index)=value else{return Err(pyerr("TypeError","__dict__ must be set to a dictionary"));};if !matches!(self.heap.get(index).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..))){return Err(pyerr("TypeError","__dict__ must be set to a dictionary"));}error.dict=Some(index);}
                        "args" => {
                            error.args = self.to_vec(value.clone())?;
                            error.args_tuple = Some(match value {
                                Value::Obj(index)
                                    if matches!(
                                        self.heap.get(index).and_then(Option::as_ref),
                                        Some(Object::Tuple(_))
                                    ) =>
                                {
                                    Value::Obj(index)
                                }
                                _ => self.obj_value(Object::Tuple(error.args.clone())),
                            });
                            error.message = self.exception_cached_message(&error)?;
                        }
                        "__cause__" | "__context__" => {
                            let value = if matches!(value, Value::None) {
                                None
                            } else {
                                if matches!(&value, Value::Type(_) | Value::Builtin(_))
                                    || matches!(&value, Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Class(_))))
                                {
                                    return Err(pyerr(
                                        "TypeError",
                                        "exception attribute must be an exception instance or None",
                                    ));
                                }
                                let mut linked = self.as_exception(value)?;
                                Some(self.exception_value(&mut linked))
                            };
                            if name == "__cause__" {
                                error.cause = value;
                                error.suppress_context = true;
                            } else {
                                error.context = value;
                            }
                        }
                        "__traceback__" => {
                            if matches!(value,Value::None){error.trace.clear();}else if !matches!(&value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Record{name,..})if name=="traceback")){return Err(pyerr("TypeError","__traceback__ must be a traceback or None"));}
                            error.attributes.insert(name.into(),value);
                        }
                        "__suppress_context__" => {
                            if let Value::Bool(value) = value {
                                error.suppress_context = value;
                            } else {
                                return Err(pyerr(
                                    "TypeError",
                                    "attribute value type must be bool",
                                ));
                            }
                        }
                        _ => {
                            let attrs=self.exception_dict(&mut error);self.ns_set(attrs,name.into(),value);
                        }
                    }
                    self.heap[i] = Some(Object::Exception(error));
                    return Ok(());
                }
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
                Object::Generator(frame) => {
                    if matches!(name,"__name__"|"__qualname__") {
                        if !matches!(self.native_payload(&value).unwrap_or_else(||value.clone()),Value::Str(_)) {
                            return Err(pyerr("TypeError",format!("{} must be set to a string object",name)));
                        }
                        let metadata=frame.generator_names.expect("generator names");
                        match self.heap[metadata].as_mut().expect("live generator names") {
                            Object::Tuple(names)=>names[usize::from(name=="__qualname__")]=value,
                            _=>unreachable!(),
                        }
                        return Ok(());
                    }
                    return Err(pyerr("AttributeError",if name=="gi_code"{"attribute 'gi_code' of 'generator' objects is not writable".to_owned()}else{format!("'generator' object has no attribute '{}'",name)}));
                }
                Object::Function(mut fun) => {
                    match name {
                        "__builtins__" => return Err(pyerr("AttributeError","readonly attribute")),
                        "__name__" | "__qualname__" => {
                            if !matches!(self.native_payload(&value).unwrap_or_else(||value.clone()),Value::Str(_)) {
                                return Err(pyerr("TypeError",format!("{} must be set to a string object",name)));
                            }
                            if name == "__name__" {
                                fun.name = value
                            } else {
                                fun.qualname = value
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
                            fun.defaults_set = !matches!(value, Value::None);
                            fun.defaults = if matches!(value, Value::None) {
                                Vec::new()
                            } else {
                                match self.native_payload(&value).unwrap_or(value) {
                                    Value::Obj(index)=>match self.object(index)? {Object::Tuple(values)=>values,_=>return Err(pyerr("TypeError","__defaults__ must be set to a tuple object"))},
                                    _=>return Err(pyerr("TypeError","__defaults__ must be set to a tuple object")),
                                }
                            }
                        }
                        "__kwdefaults__" => {
                            fun.kwdefaults = if matches!(value, Value::None) {
                                HashMap::new()
                            } else {
                                self.keyword_items(value)?.into_iter().map(|(name,value)|(name.spelling,value)).collect()
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
                    if !self.instance_allows_dict(i) {
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
                    if let Some(d) = self.class_attribute_lookup(&class,name) {
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
                    if !self.instance_allows_dict(i) {
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
                    if name=="__annotate__" {
                        if !matches!(value,Value::None) {
                            let callable=self.builtin("callable",vec![value.clone()],Vec::new(),None)?;
                            if !self.truth(&callable)? {return Err(pyerr("TypeError","__annotate__ must be callable or None"));}
                            self.ns_del(c.attrs,"__annotations__");
                        }
                        self.ns_set(c.attrs,"__annotate_func__".into(),value);return Ok(());
                    }
                    if name == "__name__" {
                        if let Value::Str(text) = self.native_payload(&value).unwrap_or_else(||value.clone()) {
                            c.name = text;
                            c.name_value = value;
                            self.heap[i] = Some(Object::Class(c));
                            return Ok(());
                        }
                        return Err(pyerr("TypeError", "can only assign string to __name__"));
                    }
                    if name == "__qualname__" && !matches!(self.native_payload(&value).unwrap_or_else(||value.clone()), Value::Str(_)) {
                        return Err(pyerr("TypeError", "can only assign string to __qualname__"));
                    }
                    self.ns_set(c.attrs, name.into(), value);
                    return Ok(());
                }
                Object::Module { attrs, .. } => {
                    if name=="__dict__" {return Err(pyerr("AttributeError","readonly attribute"));}
                    if name=="__annotate__" && !matches!(value,Value::None) {
                        let callable=self.builtin("callable",vec![value.clone()],Vec::new(),None)?;
                        if !self.truth(&callable)? {return Err(pyerr("TypeError","__annotate__ must be callable or None"));}
                        // Assignment precedes invalidation. If a cached-key
                        // comparison raises, the new annotation function stays.
                        self.global_name_set(attrs,name.into(),value)?;
                        self.global_name_del(attrs,"__annotations__")?;
                        return Ok(());
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
                    return self.global_name_set(attrs, name.into(), value);
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
        if let Some(class) = self.object_class(&obj) {
            let descriptor=if matches!(&obj,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Instance{..}|Object::BuiltinInstance{..}))){self.class_attribute_lookup(&class,name)}else{self.slot_override(&class,name,0)};
            if let Some(descriptor) = descriptor {
                if let Value::Obj(index) = &descriptor {
                    if let Object::Property { del, .. } = self.object(*index)? {
                        let delete =
                            del.ok_or_else(|| pyerr("AttributeError", "property has no deleter"))?;
                        self.call(delete, vec![obj], Vec::new(), None)?;
                        return Ok(());
                    }
                }
                if let Ok(delete) = self.getattr(descriptor, "__delete__") {
                    self.call(delete, vec![obj], Vec::new(), None)?;
                    return Ok(());
                }
            }
        }
        if let Value::Obj(i) = obj {
            let attrs = match self.object(i)? {
                Object::Module { attrs, .. } => {
                    if name=="__dict__" {return Err(pyerr("AttributeError","readonly attribute"));}
                    match self.global_name_del(attrs,name) {
                        Ok(true)=>return Ok(()),
                        Err(error) if self.exception_has_native_class(&error,"KeyError")=>(),
                        Err(error)=>return Err(error),
                        Ok(false)=>(),
                    }
                    return Err(pyerr("AttributeError",name));
                }
                Object::Exception(mut error) => {
                    if name=="__dict__"{return Err(pyerr("TypeError","cannot delete __dict__"));}
                    if self.exception_native_attribute(&error,name){error.attributes.insert(name.into(),Value::None);self.heap[i]=Some(Object::Exception(error));return Ok(());}
                    if error.dict.is_some_and(|attrs|self.ns_del(attrs,name)){self.heap[i]=Some(Object::Exception(error));return Ok(());}
                    return Err(pyerr("AttributeError",name));
                }
                Object::Generator(_) => {
                    if matches!(name,"__name__"|"__qualname__"){return Err(pyerr("TypeError",format!("{} must be set to a string object",name)));}
                    return Err(pyerr("AttributeError",if name=="gi_code"{"attribute 'gi_code' of 'generator' objects is not writable".to_owned()}else{format!("'generator' object has no attribute '{}'",name)}));
                }
                Object::Function(fun) => {
                    if name=="__builtins__" {return Err(pyerr("AttributeError","readonly attribute"));}
                    if matches!(name,"__name__"|"__qualname__"){return Err(pyerr("TypeError",format!("{} must be set to a string object",name)));}
                    Some(fun.attrs)
                }
                Object::Instance { attrs, .. }
                | Object::BuiltinInstance { attrs, .. } => Some(attrs),
                Object::Class(c) => {
                    if matches!(name,"__name__"|"__qualname__"){return Err(pyerr("TypeError",format!("cannot delete '{}' attribute of immutable type '{}'",name,c.name)));}
                    Some(c.attrs)
                },
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
            return Ok(self.keyword_items(Value::Obj(a))?.into_iter().map(|(name,value)|(name.spelling,value)).collect());
        }
        Err(pyerr("TypeError", "object has no attribute dictionary"))
    }
}

impl Runtime {
    fn bind_function(
        &mut self,
        function: &Function,
        owner: Value,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Frame> {
        let code_handle=self.code_object_index(function.code);
        let mut roots=args.clone();roots.extend([owner.clone(),Value::Obj(code_handle)]);
        roots.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        roots.extend(function.defaults.iter().cloned());
        roots.extend(function.kwdefaults.values().cloned());
        roots.extend([Value::Obj(function.globals),Value::Obj(function.attrs),function.builtins.clone(),function.name.clone(),function.qualname.clone()]);
        roots.extend(function.closure.map(Value::Obj));
        self.view_rooted(roots,|runtime,root|{
            let code=&runtime.codes[function.code];
            let comp_locals=code.comp_locals.clone();let code_name=code.name.clone();let code_locals=code.locals.iter().filter(|name|!code.globals.contains(name) && !code.frees.contains(name) && !code.nonlocals.contains(name)).cloned().collect();let params=code.params.clone();
            let class_body=code.kind==ScopeKind::Class;
            let ns=if class_body {function.globals}else{runtime.alloc(Object::Namespace(OrderedNamespace::new(),function.closure))};
            runtime.roots[root].push(Value::Obj(ns));
            if !class_body {
            runtime.scope_bindings.insert(ns,code_locals);
            runtime.scope_comprehension_bindings.insert(ns,comp_locals);
            }
            let count=params.positional.len();
            for(name,value)in params.positional.iter().zip(&args){runtime.ns_set(ns,name.clone(),value.clone());}
            if let Some(name)=&params.vararg{
                let rest=runtime.obj_value(Object::Tuple(args[args.len().min(count)..].to_vec()));
                runtime.ns_set(ns,name.clone(),rest);
            }
            let rest=if let Some(name)=&params.kwarg{
                let value=runtime.obj_value(Object::Dict(Vec::new()));runtime.ns_set(ns,name.clone(),value.clone());Some(value)
            }else{None};
            for(name,value)in kwargs{
                let mut matched=None;
                // CPython checks keywords in call order, comparing the actual
                // string subclass against each non-positional-only parameter.
                for parameter in params.positional.iter().skip(params.posonly).chain(&params.kwonly){
                    if runtime.keyword_matches(&name,parameter)? {matched=Some(parameter.clone());break;}
                }
                if let Some(parameter)=matched{
                    if runtime.ns_get(ns,&parameter).is_some(){return Err(pyerr("TypeError",format!("{}() got multiple values for argument '{}'",code_name,parameter)));}
                    runtime.ns_set(ns,parameter,value);
                }else if let Some(rest)=&rest{
                    runtime.setitem(rest.clone(),name.original,value)?;
                }else{
                    let mut positional_only=Vec::new();
                    for parameter in params.positional.iter().take(params.posonly){if runtime.keyword_matches(&name,parameter)?{positional_only.push(parameter.clone());}}
                    if !positional_only.is_empty(){return Err(pyerr("TypeError",format!("{}() got some positional-only arguments passed as keyword arguments: '{}'",code_name,positional_only.join(", "))));}
                    return Err(pyerr("TypeError",format!("{}() got an unexpected keyword argument '{}'",code_name,name)));
                }
            }
            if args.len()>count&&params.vararg.is_none(){return Err(pyerr("TypeError",format!("{}() takes {} positional arguments but {} were given",code_name,count,args.len())));}
            for(index,name)in params.positional.iter().enumerate(){
                if runtime.ns_get(ns,name).is_some(){continue;}
                if index+function.defaults.len()>=count{runtime.ns_set(ns,name.clone(),function.defaults[index+function.defaults.len()-count].clone());}
                else{return Err(pyerr("TypeError",format!("{}() missing required positional argument: '{}'",code_name,name)));}
            }
            for name in &params.kwonly{
                if runtime.ns_get(ns,name).is_some(){continue;}
                let value=function.kwdefaults.get(name).cloned().ok_or_else(||pyerr("TypeError",format!("missing keyword-only argument: '{}'",name)))?;
                runtime.ns_set(ns,name.clone(),value);
            }
            // Keyword comparisons may rename the function during binding.
            // A generator snapshots the current names after those callbacks.
            let generator_names=if runtime.codes[function.code].is_generator {
                let current=match &owner {Value::Obj(index)=>runtime.heap.get(*index).and_then(Option::as_ref),_=>None};
                let (name,qualname)=match current {Some(Object::Function(current))=>(current.name.clone(),current.qualname.clone()),_=>(function.name.clone(),function.qualname.clone())};
                Some(runtime.alloc(Object::Tuple(vec![name,qualname])))
            }else{None};
            Ok(Frame{
                function:Some(owner),generator_names,code_handle,
                code:function.code,pc:0,locals:ns,
                temps:runtime.alloc(Object::Namespace(OrderedNamespace::new(),None)),
                globals:function.globals,builtins:function.builtins.clone(),closure:function.closure,stack:Vec::new(),handlers:Vec::new(),pending:Vec::new(),
                exception:None,exception_stack:Vec::new(),inherited_exception:None,except_star:Vec::new(),next_call:None,cache_returns:Vec::new(),comprehensions:Vec::new(),
                resume_value:None,injected_exception:None,finally_regions:Vec::new(),
            })
        })
    }
    fn direct_call_candidate(&self, mut fun:Value) -> bool {
        // Only unwrap shapes with no user callbacks. Unknown callables retain
        // their ordinary call path, without an extra cache lookup or miss.
        for _ in 0..1000 {
            let object=match fun {Value::Obj(i)=>self.heap.get(i).and_then(Option::as_ref),_=>None};
            match object {
                Some(Object::Function(function))=>return !self.codes[function.code].is_generator,
                Some(Object::Bound(inner,_))=>fun=inner.clone(),
                Some(Object::Cached(cache))=>fun=cache.function.clone(),
                _=>return false,
            }
        }
        false
    }
    fn prepare_direct_call(&mut self,fun:Value,args:Vec<Value>,kwargs:KeywordArgs) -> PyResult<PreparedCall> {
        if !self.direct_call_candidate(fun.clone()) {return Ok(PreparedCall::Fallback);}
        let root=self.roots.len();
        let mut values=args.clone();values.push(fun.clone());values.extend(kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
        self.roots.push(values);
        let result=self.prepare_direct_call_inner(fun,args,kwargs);
        self.roots.truncate(root);
        result
    }
    fn prepare_direct_call_inner(&mut self,fun:Value,mut args:Vec<Value>,kwargs:KeywordArgs) -> PyResult<PreparedCall> {
        let i=match fun {Value::Obj(i)=>i,_=>return Ok(PreparedCall::Fallback)};
        match self.object(i)? {
            Object::Function(function)=>{
                if self.recursion>=self.recursion_limit {return Err(pyerr("RecursionError","maximum recursion depth exceeded"));}
                Ok(PreparedCall::Frame(self.bind_function(&function,Value::Obj(i),args,kwargs)?))
            }
            Object::Bound(inner,receiver)=>{args.insert(0,receiver);self.prepare_direct_call_inner(inner,args,kwargs)}
            Object::Cached(cache)=>match self.cached_lookup(i,cache,args,kwargs)? {
                CachedLookup::Hit(value)=>Ok(PreparedCall::Value(value)),
                CachedLookup::Miss{function,entry}=>{
                    let root=self.roots.len();
                    let mut values=entry.args.clone();values.push(Value::Obj(i));values.extend(entry.kwargs.iter().flat_map(|(name,value)|[name.original.clone(),value.clone()]));
                    self.roots.push(values);
                    let prepared=self.prepare_direct_call_inner(function,entry.args.clone(),entry.kwargs.clone());
                    self.roots.truncate(root);
                    match prepared? {
                        PreparedCall::Frame(mut frame)=>{frame.cache_returns.push(CacheReturn{owner:Value::Obj(i),entry});Ok(PreparedCall::Frame(frame))}
                        PreparedCall::Value(value)=>Ok(PreparedCall::Value(self.cached_finish(i,entry,value)?)),
                        PreparedCall::Fallback=>unreachable!("candidate changed without a callback"),
                    }
                }
            },
            _=>Ok(PreparedCall::Fallback),
        }
    }
}
