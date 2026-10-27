// Public closure cells share the binding used by every captured function.
// Namespace ownership supplies GC edges; neither cache is a global GC root.
// https://docs.python.org/3.14/reference/datamodel.html#function.__closure__
impl Runtime {
    fn closure_names(&self, code: usize) -> Vec<String> {
        let mut names = self.codes[code].frees.clone();
        names.sort();
        names.dedup();
        names
    }

    fn closure_cell(&mut self, namespace: Option<usize>, name: &str) -> PyResult<usize> {
        if name=="__classdict__" {
            let mut current=namespace;
            while let Some(owner)=current {
                if let Some(cell)=self.closure_bindings.get(&owner).and_then(|cells|cells.get(name)) {return Ok(*cell);}
                if self.scope_parents.contains_key(&owner) {
                    // The compiler's cell is independent of arbitrary keys in
                    // __prepare__'s mapping; observing it must not call user
                    // __getitem__ or read a user-supplied __classdictcell__.
                    let dictionary=self.annotation_namespaces.get(&owner).copied().unwrap_or(owner);
                    let cell=self.alloc(Object::Cell(Some(Value::Obj(dictionary))));
                    self.closure_bindings.entry(owner).or_default().insert(name.to_owned(),cell);
                    return Ok(cell);
                }
                current=self.ns_parent(owner);
            }
        }
        let mut private_owner=None;
        let mut current=namespace;
        while let Some(owner)=current {
            if self.scope_cells.get(&owner).is_some_and(|cells|cells.contains_key(name)) {
                private_owner=Some(owner);break;
            }
            current=self.ns_parent(owner);
        }
        let owner = private_owner.or_else(||self.find_nonlocal(namespace, name)).or_else(|| {
            if name == "__class__" { namespace } else { None }
        }).ok_or_else(|| pyerr("NameError", format!("no binding for free variable '{name}'")))?;
        if let Some(cell) = self.closure_bindings.get(&owner).and_then(|cells| cells.get(name)) {
            return Ok(*cell);
        }
        let private=self.scope_cells.get_mut(&owner).and_then(|cells|cells.remove(name));
        let contents = if private.is_some(){private}else{
            let value=self.ns_get(owner,name);
            // Private annotation cells coexist with arbitrary class mapping
            // entries of the same spelling; do not remove those entries.
            self.ns_del(owner,name);value
        };
        // Promoted bindings live only in cells, so an overwritten captured
        // value is not retained by an obsolete namespace entry.
        let cell = self.alloc(Object::Cell(contents));
        self.closure_bindings.entry(owner).or_default().insert(name.to_owned(), cell);
        Ok(cell)
    }

    fn function_closure(&mut self, owner: usize, function: &Function) -> PyResult<Value> {
        if let Some(tuple) = self.function_closures.get(&owner) {
            return Ok(Value::Obj(*tuple));
        }
        let names = self.closure_names(function.code);
        if names.is_empty() { return Ok(Value::None); }
        let mut cells = Vec::with_capacity(names.len());
        for name in names {
            cells.push(Value::Obj(self.closure_cell(function.closure, &name)?));
        }
        let tuple = self.alloc(Object::Tuple(cells));
        self.function_closures.insert(owner, tuple);
        Ok(Value::Obj(tuple))
    }

    fn execution_closure_cells(&self, code: usize, value: &Value) -> PyResult<Option<Vec<Value>>> {
        let names = self.closure_names(code);
        if names.is_empty() {
            return if matches!(value, Value::None) { Ok(None) }
                else { Err(pyerr("TypeError", "cannot use a closure with this code object")) };
        }
        if let Value::Obj(tuple) = value {
            if let Some(Object::Tuple(cells)) = self.heap.get(*tuple).and_then(Option::as_ref) {
                if cells.len() == names.len() && cells.iter().all(|value|
                    matches!(value, Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref), Some(Object::Cell(_))))) {
                    return Ok(Some(cells.clone()));
                }
            }
        }
        Err(pyerr("TypeError", format!("code object requires a closure of exactly length {}", names.len())))
    }

    fn closure_namespace(&mut self, code: usize, cells: &[Value]) -> usize {
        let namespace = self.alloc(Object::Namespace(OrderedNamespace::new(), None));
        let names = self.closure_names(code);
        self.scope_bindings.insert(namespace, names.clone());
        let bindings = names.into_iter().zip(cells).map(|(name, value)| {
            let Value::Obj(index) = value else { unreachable!("validated cell") };
            (name, *index)
        }).collect();
        self.closure_bindings.insert(namespace, bindings);
        namespace
    }

    fn set_function_code(&mut self, owner: usize, function: &mut Function, code: usize) -> PyResult<()> {
        let count = self.closure_names(function.code).len();
        let required = self.closure_names(code).len();
        if count != required {
            return Err(pyerr("ValueError", format!("function requires a code object with {count} free vars, not {required}")));
        }
        if count != 0 {
            let closure = self.function_closure(owner, function)?;
            let Value::Obj(tuple) = closure else { unreachable!() };
            let payload=self.native_payload(&Value::Obj(tuple)).unwrap_or(Value::Obj(tuple));
            let Value::Obj(tuple)=payload else {unreachable!()};
            let Object::Tuple(cells) = self.object(tuple)? else { unreachable!() };
            function.closure = Some(self.closure_namespace(code, &cells));
        }
        function.code = code;
        Ok(())
    }

    fn annotation_cell_lookup(&mut self, namespace: Option<usize>, name: &str) -> PyResult<Option<Option<Value>>> {
        let Some(owner)=self.find_nonlocal(namespace,"__classdict__") else{return Ok(None)};
        let dictionary=self.ns_get(owner,"__classdict__").ok_or_else(||pyerr("NameError","cannot access free variable '__classdict__' where it is not associated with a value"))?;
        let Value::Obj(index)=dictionary else{return Err(pyerr("TypeError","class annotation namespace must be a mapping"))};
        self.mapping_get(index,name).map(Some)
    }

    fn cell_constructor(&mut self, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        if !kwargs.is_empty() {return Err(pyerr("TypeError","cell() takes no keyword arguments"));}
        if args.len()>1 {return Err(pyerr("TypeError",format!("cell expected at most 1 argument, got {}",args.len())));}
        Ok(self.obj_value(Object::Cell(args.into_iter().next())))
    }

    fn function_constructor(&mut self, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        let mut values=codec_bind("function",args,kwargs,&["code","globals","name","argdefs","closure"])?;
        let code=match values[0].take() {
            Some(Value::Obj(index))=>match self.object(index)? {Object::Code(code)=>code,_=>return Err(pyerr("TypeError","function() argument 'code' must be code"))},
            _=>return Err(pyerr("TypeError","function() argument 'code' must be code")),
        };
        let globals=values[1].take().ok_or_else(||pyerr("TypeError","function() missing globals"))?;
        let globals=match &globals {
            Value::Obj(index) if matches!(self.native_payload(&globals).unwrap_or_else(||globals.clone()),Value::Obj(owner) if matches!(self.heap.get(owner).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..))))=>*index,
            _=>return Err(pyerr("TypeError","function() argument 'globals' must be dict")),
        };
        let name=values[2].take().unwrap_or(Value::None);
        let name=if matches!(name,Value::None){self.code_constant(code,Const::Str(self.codes[code].name.clone()))?}
            else if matches!(self.native_payload(&name).unwrap_or_else(||name.clone()),Value::Str(_)){name}
            else{return Err(pyerr("TypeError","arg 3 (name) must be None or string"));};
        let defaults=values[3].take().unwrap_or(Value::None);
        let defaults_set=!matches!(defaults,Value::None);
        let defaults=if defaults_set {match self.native_payload(&defaults).unwrap_or(defaults) {
            Value::Obj(index)=>match self.object(index)? {Object::Tuple(values)=>values,_=>return Err(pyerr("TypeError","arg 4 (defaults) must be None or tuple"))},
            _=>return Err(pyerr("TypeError","arg 4 (defaults) must be None or tuple")),
        }}else{Vec::new()};
        let tuple=values[4].take().unwrap_or(Value::None);
        let required=self.closure_names(code).len();
        let cells=if matches!(tuple,Value::None) {
            if required!=0 {return Err(pyerr("TypeError","arg 5 (closure) must be tuple"));}
            None
        }else{
            let payload=self.native_payload(&tuple).unwrap_or_else(||tuple.clone());
            let cells=match payload {
                Value::Obj(index)=>match self.object(index)? {Object::Tuple(cells)=>cells,_=>return Err(pyerr("TypeError","arg 5 (closure) must be None or tuple"))},
                _=>return Err(pyerr("TypeError","arg 5 (closure) must be None or tuple")),
            };
            if cells.len()!=required {return Err(pyerr("ValueError",format!("function requires closure of length {required}, not {}",cells.len())));}
            if !cells.iter().all(|value|matches!(value,Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Cell(_))))) {
                return Err(pyerr("TypeError","arg 5 (closure) expected cell"));
            }
            Some(cells)
        };
        let mut roots=vec![Value::Obj(globals),name.clone(),tuple.clone()];roots.extend(defaults.iter().cloned());
        self.view_rooted(roots,|runtime,root|{
            let module=runtime.global_name_get(globals,"__name__")?.unwrap_or(Value::None);
            runtime.roots[root].push(module.clone());
            let builtins=runtime.capture_builtins(globals,runtime.active_builtins.clone())?;
            runtime.roots[root].push(builtins.clone());
            let closure=cells.as_ref().map(|cells|runtime.closure_namespace(code,cells));
            let function=Function {
                annotate:None,annotations_evaluated:false,
                attrs:runtime.alloc(Object::Dict(Vec::new())),name,
                qualname:runtime.code_constant(code,Const::Str(runtime.codes[code].qualname.clone()))?,
                module,doc:match runtime.codes[code].docstring.clone(){Some(doc)=>Value::Str(doc.into()),None=>Value::None},
                annotations:runtime.obj_value(Object::Dict(Vec::new())),type_params:runtime.obj_value(Object::Tuple(Vec::new())),
                code,globals,builtins,closure,defaults,defaults_set,kwdefaults:HashMap::new(),
            };
            let owner=runtime.alloc(Object::Function(function));
            if let Value::Obj(tuple)=tuple {runtime.function_closures.insert(owner,tuple);}
            Ok(Value::Obj(owner))
        })
    }
}
