// A keyword retains its actual Python string object across call boundaries.
// spelling is only for built-in argument parsing and diagnostics. Python
// function binding and dictionary operations use original instead.
#[derive(Clone, Debug)]
struct KeywordName {
    spelling: String,
    original: Value,
    hash: Option<i64>,
}
type KeywordArgs = Vec<(KeywordName, Value)>;
impl KeywordName {
    fn new(spelling: String, original: Value) -> Self {
        Self {
            spelling,
            original,
            hash: None,
        }
    }
    fn as_str(&self) -> &str {
        &self.spelling
    }
}
impl std::ops::Deref for KeywordName {
    type Target = str;
    fn deref(&self) -> &str {
        &self.spelling
    }
}
impl std::fmt::Display for KeywordName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.spelling.fmt(f)
    }
}
impl From<String> for KeywordName {
    fn from(spelling: String) -> Self {
        let original = Value::Str(spelling.clone().into());
        Self::new(spelling, original)
    }
}
impl From<&str> for KeywordName {
    fn from(value: &str) -> Self {
        value.to_owned().into()
    }
}
impl PartialEq for KeywordName {
    fn eq(&self, other: &Self) -> bool {
        self.spelling == other.spelling
    }
}
impl PartialEq<str> for KeywordName {
    fn eq(&self, other: &str) -> bool {
        self.spelling == other
    }
}
impl PartialEq<&str> for KeywordName {
    fn eq(&self, other: &&str) -> bool {
        self.spelling == *other
    }
}
impl PartialEq<String> for KeywordName {
    fn eq(&self, other: &String) -> bool {
        self.spelling == *other
    }
}
impl PartialEq<KeywordName> for str {
    fn eq(&self, other: &KeywordName) -> bool {
        self == other.spelling
    }
}
impl PartialEq<KeywordName> for &str {
    fn eq(&self, other: &KeywordName) -> bool {
        *self == other.spelling
    }
}
impl PartialEq<KeywordName> for String {
    fn eq(&self, other: &KeywordName) -> bool {
        *self == other.spelling
    }
}
impl From<KeywordName> for String {
    fn from(value: KeywordName) -> Self {
        value.spelling
    }
}
impl Runtime {
    fn intern_keyword(&mut self,name:&str)->Ident<String>{
        self.keyword_intern_pool.entry(name.to_owned()).or_insert_with(||name.to_owned().into()).clone()
    }
    fn static_keyword(&mut self,name:String)->KeywordName{
        let original=Value::Str(self.intern_keyword(&name));KeywordName::new(name,original)
    }
}
impl Runtime {
    fn keyword_matches(&mut self, name: &KeywordName, parameter: &str) -> PyResult<bool> {
        if let Value::Str(_) = &name.original {
            return Ok(name.spelling == parameter);
        }
        self.equal(&name.original, &Value::Str(parameter.into()))
    }
}

impl Runtime {
    fn dictionary_owner(&self, value: &Value) -> Option<usize> {
        match value {
            Value::Obj(owner) => match self.heap.get(*owner).and_then(Option::as_ref) {
                Some(Object::Dict(_) | Object::Namespace(..)) => Some(*owner),
                Some(Object::BuiltinInstance { payload, .. }) => self.dictionary_owner(payload),
                Some(Object::MappingProxy { owner }) => Some(*owner),
                _ => None,
            },
            _ => None,
        }
    }
    // As with Python dictionaries, a stored hash belongs to an entry, not to
    // an object forever. A fresh lookup hashes again; copying an entry reuses it.
    fn dictionary_entry_hash(&mut self, owner: usize, index: usize, key: &Value) -> PyResult<i64> {
        if let Some(hash) = self
            .dictionary_hashes
            .get(&owner)
            .and_then(|hashes| hashes.get(index))
            .and_then(|hash| *hash)
        {
            return Ok(hash);
        }
        let hash = self.frozen_member_hash(key)?;
        let hashes = self.dictionary_hashes.entry(owner).or_default();
        if hashes.len() <= index {
            hashes.resize(index + 1, None);
        }
        hashes[index] = Some(hash);
        Ok(hash)
    }
    fn dictionary_remove_entry_hash(&mut self, owner: usize, index: usize) {
        if let Some(hashes) = self.dictionary_hashes.get_mut(&owner) {
            if index < hashes.len() {
                hashes.remove(index);
            }
        }
    }
    fn dictionary_find_known(
        &mut self,
        owner: usize,
        _items: &[(Value, Value)],
        key: &Value,
        hash: i64,
    ) -> PyResult<Option<usize>> {
        self.view_rooted(vec![Value::Obj(owner), key.clone()], |runtime, root| {
            'restart: loop {
                let entries = runtime.assoc_entries(owner)?;
                runtime.roots[root].extend(
                    entries
                        .iter()
                        .flat_map(|(key, value)| [key.clone(), value.clone()]),
                );
                for (index, (stored, _)) in entries.iter().enumerate() {
                    let stored_hash = runtime.dictionary_entry_hash(owner, index, stored)?;
                    if stored_hash != hash {
                        continue;
                    }
                    let matched = runtime.identical_or_equal(stored, key)?;
                    let current = runtime.assoc_entries(owner)?;
                    if current.len() != entries.len()
                        || current
                            .iter()
                            .zip(&entries)
                            .any(|((a, _), (b, _))| !a.same_identity(b))
                    {
                        continue 'restart;
                    }
                    if matched {
                        return Ok(Some(index));
                    }
                }
                return Ok(None);
            }
        })
    }
    fn dictionary_find(
        &mut self,
        owner: usize,
        items: &[(Value, Value)],
        key: &Value,
    ) -> PyResult<Option<usize>> {
        let hash = self.frozen_member_hash(key)?;
        self.dictionary_find_known(owner, items, key, hash)
    }
    fn dictionary_set_known(
        &mut self,
        owner: usize,
        key: Value,
        value: Value,
        hash: i64,
    ) -> PyResult<()> {
        self.dictionary_insert_known(owner, key, value, hash, false)
    }
    fn dictionary_insert_known(
        &mut self,
        owner: usize,
        key: Value,
        value: Value,
        hash: i64,
        reject_duplicate: bool,
    ) -> PyResult<()> {
        self.view_rooted(
            vec![Value::Obj(owner), key.clone(), value.clone()],
            |runtime, _| {
                let existing = runtime.dictionary_find_known(owner, &[], &key, hash)?;
                let Object::Dict(mut items) = runtime.object(owner)? else {
                    return Err(pyerr("TypeError", "expected dictionary"));
                };
                if let Some(index) = existing {
                    if reject_duplicate {
                        return Err(pyerr("TypeError", "multiple values for keyword argument"));
                    }
                    items[index].1 = value;
                } else {
                    let hashes = runtime.dictionary_hashes.entry(owner).or_default();
                    hashes.resize(items.len(), None);
                    hashes.push(Some(hash));
                    items.push((key.clone(), value));
                    runtime.assoc_inserted(owner, key);
                }
                runtime.heap[owner] = Some(Object::Dict(items));
                Ok(())
            },
        )
    }
    fn dictionary_copy(&mut self, value: Value) -> PyResult<Value> {
        self.view_rooted(vec![value.clone()], |runtime, root| {
            let result = runtime.obj_value(Object::Dict(Vec::new()));
            runtime.roots[root].push(result.clone());
            let Value::Obj(owner) = result else {
                unreachable!()
            };
            if let Some(source) = runtime
                .dictionary_direct_source(&value)
                .filter(|source| runtime.dictionary_can_clone(*source, true))
            {
                runtime.dictionary_clone_into(owner, source)?;
            } else {
                runtime.dictionary_update_value(owner, value)?;
            }
            Ok(Value::Obj(owner))
        })
    }
    fn dictionary_from_keywords(&mut self, keywords: KeywordArgs) -> PyResult<Value> {
        let roots = keywords
            .iter()
            .flat_map(|(name, value)| [name.original.clone(), value.clone()])
            .collect();
        self.view_rooted(roots, |runtime, root| {
            let entries = keywords
                .iter()
                .map(|(name, value)| (name.original.clone(), value.clone()))
                .collect();
            let result = runtime.obj_value(Object::Dict(entries));
            runtime.roots[root].push(result.clone());
            let Value::Obj(owner) = result else {
                unreachable!()
            };
            for (name, _) in keywords {
                let hash = if let Some(hash) = name.hash {
                    hash
                } else {
                    runtime.frozen_member_hash(&name.original)?
                };
                runtime
                    .dictionary_hashes
                    .entry(owner)
                    .or_default()
                    .push(Some(hash));
            }
            Ok(Value::Obj(owner))
        })
    }
    fn keyword_merge(
        &mut self,
        stored: KeywordArgs,
        incoming: KeywordArgs,
    ) -> PyResult<KeywordArgs> {
        // partial's keyword dictionaries use ordinary update semantics, retaining
        // the earlier key object when a later equal key replaces its value.
        let roots = stored
            .iter()
            .chain(&incoming)
            .flat_map(|(name, value)| [name.original.clone(), value.clone()])
            .collect();
        self.view_rooted(roots, |runtime, root| {
            let result = runtime.dictionary_from_keywords(stored)?;
            runtime.roots[root].push(result.clone());
            let Value::Obj(owner) = result else {
                unreachable!()
            };
            for (name, value) in incoming {
                let hash = if let Some(hash) = name.hash {
                    hash
                } else {
                    runtime.frozen_member_hash(&name.original)?
                };
                runtime.dictionary_set_known(owner, name.original, value, hash)?;
            }
            runtime.keyword_items(Value::Obj(owner))
        })
    }
}

impl Runtime {
    fn keyword_str_protocol(
        &mut self,
        receiver: Value,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        if !["__hash__", "__eq__", "__ne__", "__str__", "__repr__"].contains(&name) {
            return None;
        }
        Some((|| {
            let expected = usize::from(matches!(name, "__eq__" | "__ne__"));
            if args.len() != expected || !kwargs.is_empty() {
                return Err(pyerr(
                    "TypeError",
                    format!("{name}() requires {expected} arguments"),
                ));
            }
            let Value::Str(text) = &receiver else {
                return Err(pyerr("TypeError", "str descriptor requires a str object"));
            };
            match name {
                "__hash__" => self.builtin("hash", vec![receiver], Vec::new(), None),
                "__str__" => Ok(receiver),
                "__repr__" => Ok(Value::Str(text_repr_str(text).into())),
                _ => {
                    let other = self
                        .native_payload(&args[0])
                        .unwrap_or_else(|| args[0].clone());
                    if let Value::Str(other) = other {
                        Ok(Value::Bool((text == &other) == (name == "__eq__")))
                    } else {
                        Ok(Value::Builtin("NotImplemented".into()))
                    }
                }
            }
        })())
    }
}

impl Runtime {
    fn dictionary_direct_source(&self, value: &Value) -> Option<usize> {
        let payload = if let Some(payload) = self.native_payload(value) {
            if self
                .object_class(value)
                .and_then(|class| self.class_lookup(&class, "__iter__", 0))
                .is_some()
            {
                return None;
            }
            payload
        } else {
            value.clone()
        };
        if let Value::Obj(owner) = payload {
            if matches!(
                self.heap.get(owner).and_then(Option::as_ref),
                Some(Object::Dict(_) | Object::Namespace(..))
            ) {
                return Some(owner);
            }
        }
        None
    }
    fn dictionary_update_value(&mut self, owner: usize, source: Value) -> PyResult<()> {
        self.view_rooted(vec![Value::Obj(owner), source.clone()], |runtime, root| {
            if let Some(source) = runtime.dictionary_direct_source(&source) {
                if owner == source {
                    return Ok(());
                }
                if runtime.assoc_size(owner) == 0 && runtime.dictionary_can_clone(source, false) {
                    return runtime.dictionary_clone_into(owner, source);
                }
                let entries = runtime.assoc_entries(source)?;
                runtime.roots[root].extend(
                    entries
                        .iter()
                        .flat_map(|(key, value)| [key.clone(), value.clone()]),
                );
                for (index, (key, value)) in entries.into_iter().enumerate() {
                    let hash = runtime.dictionary_entry_hash(source, index, &key)?;
                    runtime.dictionary_set_known(owner, key, value, hash)?;
                }
                return Ok(());
            }
            let keys = match runtime.getattr(source.clone(), "keys") {
                Ok(keys) => Some(keys),
                Err(error) if runtime.exception_has_native_class(&error, "AttributeError") => None,
                Err(error) => return Err(error),
            };
            if let Some(keys) = keys {
                let keys = runtime.call(keys, Vec::new(), Vec::new(), None)?;
                runtime.roots[root].push(keys.clone());
                let keys = runtime.to_vec(keys)?;
                runtime.roots[root].extend(keys.iter().cloned());
                for key in keys {
                    let value = runtime.getitem(source.clone(), key.clone())?;
                    runtime.setitem(Value::Obj(owner), key, value)?;
                }
            } else {
                let iterator = runtime.iter(source)?;
                runtime.roots[root].push(iterator.clone());
                while let Some(pair) = runtime.next(iterator.clone())? {
                    runtime.roots[root].push(pair.clone());
                    let pair = runtime.to_vec(pair)?;
                    if pair.len() != 2 {
                        return Err(pyerr(
                            "ValueError",
                            "dictionary update sequence element has length other than 2",
                        ));
                    }
                    runtime.roots[root].extend(pair.iter().cloned());
                    runtime.setitem(Value::Obj(owner), pair[0].clone(), pair[1].clone())?;
                }
            }
            Ok(())
        })
    }
}

impl Runtime {
    // Clone conditions follow CPython 3.14.4 dict_dict_merge/copy_lock_held,
    // Objects/dictobject.c (PSF license, bundled in stdlib/PYTHON_LICENSE.txt).
    // https://github.com/python/cpython/blob/v3.14.4/Objects/dictobject.c
    fn dictionary_can_clone(&self, source: usize, copy_method: bool) -> bool {
        let used = self.assoc_size(source);
        let Some(layout) = self.assoc_layouts.get(&source) else {
            return used == 0;
        };
        if copy_method {
            return used.saturating_mul(3) >= layout.slots.len().saturating_mul(2);
        }
        used == layout.slots.len()
            && (layout.table_size <= 8 || (layout.table_size / 2).saturating_mul(2) / 3 < used)
    }
    fn dictionary_clone_into(&mut self, owner: usize, source: usize) -> PyResult<()> {
        self.view_rooted(
            vec![Value::Obj(owner), Value::Obj(source)],
            |runtime, root| {
                let entries = runtime.assoc_entries(source)?;
                runtime.roots[root].extend(
                    entries
                        .iter()
                        .flat_map(|(key, value)| [key.clone(), value.clone()]),
                );
                let mut hashes = Vec::new();
                for (index, (key, _)) in entries.iter().enumerate() {
                    let hash = runtime.dictionary_entry_hash(source, index, key)?;
                    hashes.push(Some(hash));
                }
                runtime.heap[owner] = Some(Object::Dict(entries));
                runtime.dictionary_hashes.insert(owner, hashes);
                if let Some(layout) = runtime.assoc_layouts.get(&source).cloned() {
                    runtime.assoc_layouts.insert(owner, layout);
                } else {
                    runtime.assoc_seed(owner);
                }
                Ok(())
            },
        )
    }
}
