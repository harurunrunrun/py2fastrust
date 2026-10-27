// Module dictionaries use ordinary dictionary entries. Internal fast-local
// namespaces remain separate so a user key can never name an IR temporary.
impl Runtime {
    fn namespace_dictionary_owner(&self, index: usize) -> usize {
        match self.heap.get(index).and_then(Option::as_ref) {
            Some(Object::BuiltinInstance { payload: Value::Obj(owner), .. }) => {
                self.namespace_dictionary_owner(*owner)
            }
            _ => index,
        }
    }
    fn global_name_get(&mut self, index: usize, name: &str) -> PyResult<Option<Value>> {
        let owner = self.namespace_dictionary_owner(index);
        if matches!(self.heap.get(owner).and_then(Option::as_ref), Some(Object::Dict(_))) {
            let key = Value::Str(self.intern_keyword(name));
            if let Some(position) = self.dictionary_find(owner, &[], &key)? {
                let Object::Dict(entries) = self.object(owner)? else { unreachable!() };
                return Ok(Some(entries[position].1.clone()));
            }
            Ok(None)
        } else {
            Ok(self.ns_get(owner, name))
        }
    }
    fn global_name_set(&mut self, index: usize, name: String, value: Value) -> PyResult<()> {
        let owner = self.namespace_dictionary_owner(index);
        if matches!(self.heap.get(owner).and_then(Option::as_ref), Some(Object::Dict(_))) {
            let key = Value::Str(self.intern_keyword(&name));
            self.setitem(Value::Obj(owner), key, value)
        } else {
            self.ns_set(owner, name, value);
            Ok(())
        }
    }
    fn global_name_del(&mut self, index: usize, name: &str) -> PyResult<bool> {
        let owner = self.namespace_dictionary_owner(index);
        if matches!(self.heap.get(owner).and_then(Option::as_ref), Some(Object::Dict(_))) {
            let key = Value::Str(self.intern_keyword(name));
            self.view_rooted(vec![Value::Obj(owner), key.clone()], |runtime, _| {
                // A missing entry differs from KeyError raised by key.__eq__.
                // DELETE_GLOBAL preserves callback errors, including KeyError.
                let Some(position) = runtime.dictionary_find(owner, &[], &key)? else {
                    return Ok(false);
                };
                let Object::Dict(mut items) = runtime.object(owner)? else { unreachable!() };
                items.remove(position);
                runtime.dictionary_remove_entry_hash(owner, position);
                runtime.heap[owner] = Some(Object::Dict(items));
                runtime.assoc_dictionary_removed(owner, position);
                Ok(true)
            })
        } else {
            Ok(self.ns_del(owner, name))
        }
    }
    fn capture_builtins(&mut self, globals:usize, fallback:Value)->PyResult<Value>{
        let value=self.global_name_get(globals,"__builtins__")?.unwrap_or(fallback);
        if let Value::Obj(index)=&value {
            if let Some(Object::Module{attrs,..})=self.heap.get(*index).and_then(Option::as_ref){return Ok(Value::Obj(*attrs));}
        }
        Ok(value)
    }
    fn builtin_lookup(&mut self, namespace: Value, name: &str) -> PyResult<Option<Value>> {
        match namespace {
            Value::Obj(index) => {
                if let Some(Object::Module { attrs, .. }) = self.heap.get(index).and_then(Option::as_ref) {
                    return self.mapping_get(*attrs, name);
                }
                self.mapping_get(index, name)
            }
            value => {
                let key = Value::Str(self.intern_keyword(name));
                match self.getitem(value, key) {
                    Ok(value) => Ok(Some(value)),
                    Err(error) if self.exception_has_native_class(&error, "KeyError") => Ok(None),
                    Err(error) => Err(error),
                }
            }
        }
    }
}
