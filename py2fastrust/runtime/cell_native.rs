// Cell type attributes follow Python 3.14 behavioral probes. Comparisons keep
// their contents alive in the caller's protocol queue across Python callbacks.
const CELL_OWN_NAMES: &[&str] = &["__new__", "__repr__", "__lt__", "__le__", "__eq__", "__ne__", "__gt__", "__ge__", "cell_contents", "__doc__", "__hash__"];
const CELL_DIR_NAMES: &[&str] = &["__class__", "__delattr__", "__dir__", "__doc__", "__eq__", "__format__", "__ge__", "__getattribute__", "__getstate__", "__gt__", "__hash__", "__init__", "__init_subclass__", "__le__", "__lt__", "__ne__", "__new__", "__reduce__", "__reduce_ex__", "__repr__", "__setattr__", "__sizeof__", "__str__", "__subclasshook__", "cell_contents"];
const CELL_DOC: &str = "Create a new cell object.\n\n  contents\n    the contents of the cell. If not specified, the cell will be empty,\n    and \n further attempts to access its cell_contents attribute will\n    raise a ValueError.";
fn cell_comparison_op(name: &str) -> Option<&'static str> {
    Some(match name {"__eq__"=>"==", "__ne__"=>"!=", "__lt__"=>"<", "__le__"=>"<=", "__gt__"=>">", "__ge__"=>">=", _=>return None})
}
fn native_descriptor_class_name(name: &str) -> bool {
    matches!(name,"wrapper_descriptor"|"getset_descriptor"|"method_descriptor"|"method-wrapper"|"builtin_function_or_method")
}
impl Runtime {
    fn is_cell(&self, value: &Value) -> bool {
        matches!(value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Cell(_))))
    }
    fn is_cell_type(&self, value: &Value) -> bool {matches!(value,Value::Builtin(name)if name=="cell")}
    fn cell_cached_metadata(&mut self, name: &str) -> Value {
        match name {
            "__name__"|"__qualname__"=>return Value::Str("cell".into()),
            "__doc__"=>return Value::Str(CELL_DOC.into()),
            "__text_signature__"=>return Value::Str("([contents])".into()),
            _=>{},
        }
        if let Some(value)=self.cell_metadata.get(name) {return value.clone();}
        let value=match name {
            "__bases__"=>self.obj_value(Object::Tuple(vec![Value::Builtin("object".into())])),
            "__mro__"=>self.obj_value(Object::Tuple(vec![Value::Builtin("cell".into()),Value::Builtin("object".into())])),
            "__type_params__"=>self.obj_value(Object::Tuple(Vec::new())),
            "__module__"=>Value::Str("builtins".into()),
            _=>unreachable!(),
        };
        self.cell_metadata.insert(name.into(),value.clone());value
    }
    fn cell_descriptor_metadata(&mut self, method: &str, name: &str) -> Value {
        let key=format!("descriptor:{method}:{name}");
        if let Some(value)=self.cell_metadata.get(&key) {return value.clone();}
        let value=Value::Str(if name=="__name__" {method.to_owned()}else{format!("cell.{method}")}.into());
        self.cell_metadata.insert(key,value.clone());value
    }
    fn cell_native_attribute(&mut self, value: &Value, name: &str) -> Option<PyResult<Value>> {
        if let Value::Obj(index)=value {
            if let Some(Object::Bound(function,_))=self.heap.get(*index).and_then(Option::as_ref) {
                if let Some(("wrapper","cell",method))=native_attribute_parts(function) {
                    if ["__doc__","__text_signature__","__qualname__"].contains(&name) {return self.native_attribute_meta(function.clone(),name);}
                    if name=="__name__" {return Some(Ok(Value::Str(method.to_owned().into())));}
                }
            }
        }
        if self.is_cell_type(value) {
            return Some((|| match name {
                "__class__"=>Ok(Value::Builtin("type".into())),
                "__name__"|"__qualname__"|"__module__"|"__doc__"|"__text_signature__"|"__bases__"|"__mro__"|"__type_params__"=>Ok(self.cell_cached_metadata(name)),
                "__base__"=>Ok(Value::Builtin("object".into())),
                "__basicsize__"=>Ok(Value::Int(Int::from_i128(24).into())),
                "__flags__"=>Ok(Value::Int(Int::from_i128(20738).into())),
                "__itemsize__"|"__dictoffset__"|"__weakrefoffset__"=>Ok(Value::Int(Int::from_i128(0).into())),
                "__dict__"=>{
                    let owner=if let Some(Value::Obj(owner))=self.cell_metadata.get("dictionary") {*owner} else {
                        let entries=CELL_OWN_NAMES.iter().map(|name|(Value::Str((*name).into()),if *name=="__doc__" {self.cell_cached_metadata(name)}else{self.native_own_attribute(value,name).unwrap()})).collect();
                        let owner=self.alloc(Object::Dict(entries));self.cell_metadata.insert("dictionary".into(),Value::Obj(owner));owner
                    };
                    Ok(self.obj_value(Object::MappingProxy{owner}))
                },
                "__annotations__"|"__annotate__"=>Err(pyerr("AttributeError",format!("type object 'cell' has no attribute '{name}'"))),
                _=>{
                    if let Some(member)=self.class_attribute_lookup(value,name) {return self.bind_descriptor(member,None,value.clone());}
                    if let Some(member)=self.class_attribute_lookup(&Value::Builtin("type".into()),name) {return self.bind_descriptor(member,Some(value.clone()),Value::Builtin("type".into()));}
                    Err(pyerr("AttributeError",format!("type object 'cell' has no attribute '{name}'")))
                },
            })());
        }
        if self.is_cell(value) {
            if name=="__class__" {return Some(Ok(Value::Builtin("cell".into())));}
            if name=="__doc__" {return Some(Ok(self.cell_cached_metadata(name)));}
            if let Some(member)=self.class_attribute_lookup(&Value::Builtin("cell".into()),name) {return Some(self.bind_descriptor(member,Some(value.clone()),Value::Builtin("cell".into())));}
        }
        None
    }
    fn cell_contents_get(&self, receiver: &Value) -> PyResult<Value> {
        if let Value::Obj(index)=receiver {if let Some(Object::Cell(value))=self.heap.get(*index).and_then(Option::as_ref) {return value.clone().ok_or_else(||pyerr("ValueError","Cell is empty"));}}
        Err(self.cell_binding_error("cell_contents",receiver))
    }
    fn cell_binding_error(&self, name: &str, receiver: &Value) -> PyException {
        pyerr("TypeError",format!("descriptor '{name}' for 'cell' objects doesn't apply to a '{}' object",self.typename(receiver)))
    }
    fn cell_contents_mutate(&mut self, args: Vec<Value>, kwargs: KeywordArgs, delete: bool) -> PyResult<Value> {
        let name=if delete {"__delete__"}else{"__set__"};
        if !kwargs.is_empty() {return Err(pyerr("TypeError",format!("wrapper {name}() takes no keyword arguments")));}
        let expected=if delete {1}else{2};let given=args.len().saturating_sub(1);
        if given!=expected {return Err(pyerr("TypeError",if delete {format!("expected 1 argument, got {given}")}else{format!("__set__ expected 2 arguments, got {given}")}));}
        if !self.is_cell(&args[1]) {return Err(self.cell_binding_error("cell_contents",&args[1]));}
        let Value::Obj(index)=args[1] else {unreachable!()};
        self.heap[index]=Some(Object::Cell(if delete {None}else{Some(args[2].clone())}));Ok(Value::None)
    }
    fn cell_wrapper_arguments(&self, name: &str, args: &[Value], kwargs: &KeywordArgs) -> PyResult<Value> {
        let receiver=args.first().cloned().ok_or_else(||pyerr("TypeError",format!("descriptor '{name}' of 'cell' object needs an argument")))?;
        if !self.is_cell(&receiver) {return Err(pyerr("TypeError",format!("descriptor '{name}' requires a 'cell' object but received a '{}'",self.typename(&receiver))));}
        if !kwargs.is_empty() {return Err(pyerr("TypeError",format!("wrapper {name}() takes no keyword arguments")));}
        let expected=if name=="__repr__" {0}else{1};
        if args.len()!=expected+1 {return Err(pyerr("TypeError",format!("expected {expected} argument{}, got {}",if expected==1 {""}else{"s"},args.len()-1)));}
        Ok(receiver)
    }
    fn protocol_cell_descriptor(&mut self, state: &mut ProtocolState, plan: &ProtocolPlan) -> PyResult<bool> {
        let Some((_,"cell",name))=native_attribute_parts(&plan.function) else {return Ok(false)};
        let Some(op)=cell_comparison_op(name) else {return Ok(false)};
        let left=self.cell_wrapper_arguments(name,&plan.args,&plan.kwargs)?;
        if !self.protocol_cell_compare(state,op,&left,&plan.args[1])? {state.value=Some(Value::Builtin("NotImplemented".into()));}
        Ok(true)
    }
    fn cell_descriptor_compare_sync(&mut self, value: Value, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        let mut state=Self::protocol_empty(ProtocolSink::Stack);
        self.protocol_cell_descriptor(&mut state,&ProtocolPlan{function:value,args,kwargs})?;
        // Internal consumers may call descriptors without a suspended caller.
        // Python callbacks still run through execute's heap-frame trampoline.
        loop {
            state.actions.check_budget()?;
            let mut roots=Vec::new();state.roots(&mut roots);
            match self.view_rooted(roots,|runtime,_|runtime.protocol_turn(None,&mut state))? {
                ProtocolTurn::Continue=>{},
                ProtocolTurn::Schedule(child)=>{
                    let mut roots=Vec::new();state.roots(&mut roots);
                    let value=self.view_rooted(roots,|runtime,_|runtime.execute(child))?.0;
                    state.value=Some(match value {FrameExit::Return(value)|FrameExit::Yield(value)=>value});
                },
                ProtocolTurn::Done(value)=>return Ok(value),
            }
        }
    }
    fn cell_repr(&mut self, value: &Value) -> PyResult<String> {
        let Value::Obj(index)=value else {unreachable!()};
        let Object::Cell(contents)=self.object(*index)? else {unreachable!()};
        let address=self.identity_number(value);
        Ok(match contents {Some(contents)=>format!("<cell at 0x{address:x}: {} object at 0x{:x}>",self.cell_contents_typename(&contents),self.identity_number(&contents)),None=>format!("<cell at 0x{address:x}: empty>")})
    }
    fn cell_contents_typename(&self, value: &Value) -> String {
        if let Some(class)=self.stdlib_instance_class(value) {return self.class_name(&class);}
        if let Value::Obj(index)=value {
            match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::Code(_))=>return "code".into(),
                Some(Object::GenericAlias{typing:false,..}|Object::UnpackedAlias(_))=>return "types.GenericAlias".into(),
                Some(Object::TypeUnion{..})=>return "typing.Union".into(),
                Some(Object::TypeParameter(parameter))=>return format!("typing.{}",match parameter.kind.as_str(){"paramspec"=>"ParamSpec","typevartuple"=>"TypeVarTuple",_=>"TypeVar"}),
                Some(Object::TypeAlias{..})=>return "typing.TypeAliasType".into(),
                Some(Object::ParamSpecMarker{kind,..})=>return format!("typing.ParamSpec{}",if kind=="args" {"Args"}else{"Kwargs"}),
                Some(Object::Bound(function,_))=>return match native_attribute_parts(function) {
                    Some(("wrapper",_,_))=>"method-wrapper",
                    Some(_)=>"builtin_function_or_method",
                    None if matches!(function,Value::Builtin(_))=>"builtin_function_or_method",
                    _=>"method",
                }.into(),
                _=>{},
            }
        }
        self.typename(value)
    }
}
