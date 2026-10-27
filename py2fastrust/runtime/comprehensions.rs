// PEP 709 subscopes execute in the owner's frame. Their independent namespace
// retains captured iteration cells without mutating cells in the owner.
#[derive(Clone, Debug)]
struct InlineComprehension {
    code: usize,
    namespace: usize,
}

impl Runtime {

    fn begin_comprehension(&mut self, frame: &mut Frame, code: usize) {
        let parent = frame.comprehensions.last().map(|scope|scope.namespace)
            .or_else(||match self.codes[frame.code].kind {
                ScopeKind::Module=>None,
                ScopeKind::Class=>frame.closure,
                _=>Some(frame.locals),
            });
        let namespace=self.alloc(Object::Namespace(OrderedNamespace::new(),parent));
        let locals=self.codes[code].locals.iter().filter(|name|name.as_str()!=".0" && !name.starts_with(['$', '\0'])).cloned().collect();
        self.scope_bindings.insert(namespace,locals);
        self.scope_comprehension_bindings.insert(namespace,self.codes[code].comp_locals.clone());
        frame.comprehensions.push(InlineComprehension{code,namespace});
    }
    fn end_comprehension(&mut self, frame:&mut Frame)->PyResult<()> {
        let scope=frame.comprehensions.pop().ok_or_else(||pyerr("RuntimeError","missing inlined comprehension scope"))?;
        for name in self.codes[scope.code].locals.clone() {
            if name.starts_with(['$', '\0']){self.ns_del(frame.temps,&name);}
        }
        Ok(())
    }
    fn comprehension_load(&mut self, frame:&Frame, name:&str)->PyResult<Value> {
        let scope=frame.comprehensions.last().unwrap();
        let code=&self.codes[scope.code];
        if code.locals.iter().any(|local|local==name) {
            return self.ns_get(scope.namespace,name).ok_or_else(||pyerr("UnboundLocalError",format!("cannot access local variable '{}' where it is not associated with a value",name)));
        }
        if !code.globals.iter().any(|global|global==name) && (code.frees.iter().chain(&code.nonlocals).any(|free|free==name) || name=="__class__" && self.code_needs_class_cell(scope.code,0)) {
            if let Some(namespace)=self.find_nonlocal(self.ns_parent(scope.namespace),name) {
                let inline_local=self.scope_comprehension_bindings.get(&namespace).is_some_and(|names|names.iter().any(|value|value==name))
                    && (namespace==frame.locals || frame.comprehensions.iter().any(|scope|scope.namespace==namespace));
                return self.mapping_get(namespace,name)?.ok_or_else(||if inline_local {
                    pyerr("UnboundLocalError",format!("cannot access local variable '{}' where it is not associated with a value",name))
                } else {pyerr("NameError",format!("cannot access free variable '{}' where it is not associated with a value",name))});
            }
        }
        if self.codes[frame.code].kind==ScopeKind::Module && !code.globals.iter().any(|global|global==name) {
            if let Some(value)=self.mapping_get(frame.locals,name)? {return Ok(value);}
        }
        if let Some(value)=self.global_name_get(frame.globals,name)?{return Ok(value);}
        self.builtin_lookup(frame.builtins.clone(),name)?.ok_or_else(||pyerr("NameError",format!("name '{}' is not defined",name)))
    }
    fn comprehension_store(&mut self, frame:&Frame, name:String, value:Value)->PyResult<()> {
        let scope=frame.comprehensions.last().unwrap();
        let code=&self.codes[scope.code];
        if code.globals.contains(&name) { self.global_name_set(frame.globals,name,value)?; }
        else if code.nonlocals.contains(&name) {
            let namespace=self.find_nonlocal(self.ns_parent(scope.namespace),&name).ok_or_else(||pyerr("NameError",format!("no binding for nonlocal '{}' found",name)))?;
            self.ns_set(namespace,name,value);
        } else { self.ns_set(scope.namespace,name,value); }
        Ok(())
    }
    fn comprehension_locals(&mut self, frame:&Frame)->PyResult<Value> {
        let code=&self.codes[frame.code];
        let optimized=!matches!(code.kind,ScopeKind::Module|ScopeKind::Class);
        let mut names=Vec::new();
        if optimized {
            names.extend(code.params.positional.iter().chain(&code.params.kwonly).chain(code.params.vararg.iter()).chain(code.params.kwarg.iter()).cloned());
            names.extend(self.comprehension_local_names(frame.code));
        }
        for scope in &frame.comprehensions { names.extend(self.codes[scope.code].locals.iter().cloned().filter(|name|name!=".0")); }
        let mut frees=if optimized {code.frees.clone()}else{Vec::new()};frees.sort();names.extend(frees.iter().cloned());
        let mut seen=std::collections::HashSet::new();
        let mut entries=Vec::new();
        for name in names {
            if name.starts_with(['$', '\0']) || !seen.insert(name.clone()) {continue;}
            let isolated=frame.comprehensions.iter().rev().find(|scope|self.codes[scope.code].locals.contains(&name));
            let value=if let Some(scope)=isolated { self.ns_get(scope.namespace,&name) }
                else if frees.contains(&name) {
                    // Snapshot the owner's free cell, irrespective of a global
                    // lookup decision in the currently executing inner scope.
                    self.find_nonlocal(frame.closure,&name).and_then(|namespace|self.ns_get(namespace,&name))
                } else {self.mapping_get(frame.locals,&name)?};
            if let Some(value)=value {entries.push((Value::Str(self.intern_keyword(&name)),value));}
        }
        Ok(self.obj_value(Object::Dict(entries)))
    }
}

fn comprehension_rebase(op:Op, offset:usize)->Op {
    match op {
        Op::Jump(target)=>Op::Jump(target+offset),
        Op::JumpTrue(target)=>Op::JumpTrue(target+offset),
        Op::JumpFalse(target)=>Op::JumpFalse(target+offset),
        Op::ForIter(target)=>Op::ForIter(target+offset),
        Op::SetupExcept(target)=>Op::SetupExcept(target+offset),
        Op::SetupFinally(target)=>Op::SetupFinally(target+offset),
        Op::Break(target)=>Op::Break(target+offset),
        Op::Continue(target)=>Op::Continue(target+offset),
        op=>op,
    }
}
