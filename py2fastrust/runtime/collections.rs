// Original support for the bundled Python collections. Native dict payloads
// remain the only value storage; OrderedDict retains its independent node order.
#[derive(Clone, Debug, Default)]
struct OrderedCollectionState {
    order: Vec<(Value, i64)>,
    version: u64,
}
impl Runtime {
    fn collection_dict_owner(&self, value: &Value) -> PyResult<usize> {
        let payload = self.native_payload(value).unwrap_or_else(|| value.clone());
        match payload {
            Value::Obj(index)
                if matches!(
                    self.heap.get(index).and_then(Option::as_ref),
                    Some(Object::Dict(_) | Object::Namespace(..))
                ) =>
            {
                Ok(index)
            }
            _ => Err(pyerr("TypeError", "descriptor requires a dict instance")),
        }
    }
    fn collection_keep(&mut self, value: Value, keeper: Value) -> Value {
        if let Value::Obj(index) = value {
            if matches!(
                self.heap.get(index).and_then(Option::as_ref),
                Some(Object::Iterator(_) | Object::DictView { .. } | Object::MappingProxy { .. })
            ) && !value.same_identity(&keeper)
            {
                self.collection_keepers.insert(index, keeper);
            }
        }
        value
    }
    fn collection_inherit_keeper(&mut self, value: Value, source: &Value) -> Value {
        if let Value::Obj(index) = source {
            if let Some(keeper) = self.collection_keepers.get(index).cloned() {
                return self.collection_keep(value, keeper);
            }
        }
        value
    }
    fn collection_dict_getitem(&mut self, receiver: Value, key: Value) -> PyResult<Value> {
        self.view_rooted(vec![receiver.clone(), key.clone()], |runtime, _| {
            let owner = runtime.collection_dict_owner(&receiver)?;
            let items = runtime.assoc_entries(owner)?;
            if let Some(index) = runtime.dictionary_find(owner, &items, &key)? {
                return Ok(runtime.assoc_entries(owner)?[index].1.clone());
            }
            if let Some(class) = runtime.object_class(&receiver) {
                if let Some(method) = runtime.slot_override(&class, "__missing__", 0) {
                    let method = runtime.bind_descriptor(method, Some(receiver), class)?;
                    return runtime.call(method, vec![key], Vec::new(), None);
                }
            }
            Err(runtime.new_exception("KeyError", vec![key])?)
        })
    }
    fn collection_remove_known(
        &mut self,
        owner: usize,
        key: &Value,
        hash: i64,
    ) -> PyResult<(Value, Value)> {
        let index = self
            .dictionary_find_known(owner, &[], key, hash)?
            .ok_or_else(|| pyerr("KeyError", "missing mapping entry"))?;
        let Object::Dict(mut items) = self.object(owner)? else {
            return Err(pyerr("TypeError", "expected dict"));
        };
        let pair = items.remove(index);
        self.dictionary_remove_entry_hash(owner, index);
        self.heap[owner] = Some(Object::Dict(items));
        self.assoc_dictionary_removed(owner, index);
        Ok(pair)
    }
    fn collection_ordered(&mut self, args: Vec<Value>, kwargs: KeywordArgs) -> PyResult<Value> {
        if !kwargs.is_empty() || args.len() < 2 {
            return Err(pyerr("TypeError", "invalid internal collection arguments"));
        }
        let action = match &args[0] {
            Value::Str(name) => name.to_string(),
            _ => return Err(pyerr("TypeError", "invalid collection action")),
        };
        let receiver = args[1].clone();
        let Value::Obj(instance) = receiver else {
            return Err(pyerr("TypeError", "expected collection instance"));
        };
        let owner = self.collection_dict_owner(&receiver)?;
        let count = args.len() - 2;
        self.ordered_collections.entry(instance).or_default();
        self.view_rooted(args.clone(), |runtime, root| {
            let key = || {
                args.get(2)
                    .cloned()
                    .ok_or_else(|| pyerr("TypeError", "missing key"))
            };
            match action.as_str() {
                "version" if count == 0 => Ok(Value::Int(
                    Int::from_i128(runtime.ordered_collections[&instance].version as i128).into(),
                )),
                "iteration" if count == 0 => {
                    let state = runtime.ordered_collections[&instance].clone();
                    let keys = runtime.obj_value(Object::List(
                        state.order.into_iter().map(|(key, _)| key).collect(),
                    ));
                    runtime.roots[root].push(keys.clone());
                    Ok(runtime.obj_value(Object::Tuple(vec![
                        Value::Int(Int::from_i128(state.version as i128).into()),
                        keys,
                        Value::Int(Int::from_i128(runtime.assoc_size(owner) as i128).into()),
                    ])))
                }
                "set" if count == 2 => {
                    let key = key()?;
                    let hash = runtime.frozen_member_hash(&key)?;
                    runtime.dictionary_set_known(owner, key.clone(), args[3].clone(), hash)?;
                    let index = runtime
                        .dictionary_find_known(owner, &[], &key, hash)?
                        .ok_or_else(|| pyerr("KeyError", "mapping changed during insertion"))?;
                    let stored = runtime.assoc_entries(owner)?[index].0.clone();
                    let state = runtime.ordered_collections.entry(instance).or_default();
                    if !state
                        .order
                        .iter()
                        .any(|(old, _)| old.same_identity(&stored))
                    {
                        state.order.push((stored, hash));
                        state.version = state.version.wrapping_add(1);
                    }
                    Ok(Value::None)
                }
                "delete" if count == 1 => {
                    let key = key()?;
                    let hash = runtime.frozen_member_hash(&key)?;
                    let index = runtime.dictionary_find_known(owner, &[], &key, hash)?;
                    if index.is_none() {
                        return Err(runtime.new_exception("KeyError", vec![key])?);
                    }
                    let (stored, _) = runtime.collection_remove_known(owner, &key, hash)?;
                    let state = runtime.ordered_collections.entry(instance).or_default();
                    if let Some(index) = state
                        .order
                        .iter()
                        .position(|(old, _)| old.same_identity(&stored))
                    {
                        state.order.remove(index);
                        state.version = state.version.wrapping_add(1);
                    }
                    Ok(Value::None)
                }
                "clear" if count == 0 => {
                    runtime.method("clear", Value::Obj(owner), Vec::new(), Vec::new())?;
                    let state = runtime.ordered_collections.entry(instance).or_default();
                    if !state.order.is_empty() {
                        state.order.clear();
                        state.version = state.version.wrapping_add(1);
                    }
                    Ok(Value::None)
                }
                "move" if count == 2 => {
                    let last = runtime.truth(&args[3])?;
                    let key = key()?;
                    let hash = runtime.frozen_member_hash(&key)?;
                    let index = runtime.dictionary_find_known(owner, &[], &key, hash)?;
                    let Some(index) = index else {
                        return Err(runtime.new_exception("KeyError", vec![key])?);
                    };
                    let stored = runtime.assoc_entries(owner)?[index].0.clone();
                    let state = runtime.ordered_collections.entry(instance).or_default();
                    let Some(index) = state
                        .order
                        .iter()
                        .position(|(old, _)| old.same_identity(&stored))
                    else {
                        return Err(pyerr("KeyError", "key is not in OrderedDict order"));
                    };
                    if index != if last { state.order.len() - 1 } else { 0 } {
                        let pair = state.order.remove(index);
                        if last {
                            state.order.push(pair);
                        } else {
                            state.order.insert(0, pair);
                        }
                        state.version = state.version.wrapping_add(1);
                    }
                    Ok(Value::None)
                }
                "setdefault" if count == 2 => {
                    let key = key()?;
                    let hash = runtime.frozen_member_hash(&key)?;
                    if let Some(index) = runtime.dictionary_find_known(owner, &[], &key, hash)? {
                        return Ok(runtime.assoc_entries(owner)?[index].1.clone());
                    }
                    runtime.dictionary_set_known(owner, key.clone(), args[3].clone(), hash)?;
                    let index = runtime
                        .dictionary_find_known(owner, &[], &key, hash)?
                        .ok_or_else(|| pyerr("KeyError", "mapping changed during insertion"))?;
                    let stored = runtime.assoc_entries(owner)?[index].0.clone();
                    let state = runtime.ordered_collections.entry(instance).or_default();
                    if !state
                        .order
                        .iter()
                        .any(|(old, _)| old.same_identity(&stored))
                    {
                        state.order.push((stored, hash));
                        state.version = state.version.wrapping_add(1);
                    }
                    Ok(args[3].clone())
                }
                "pop" if count == 1 || count == 2 => {
                    let key = key()?;
                    let hash = runtime.frozen_member_hash(&key)?;
                    let index = runtime.dictionary_find_known(owner, &[], &key, hash)?;
                    let Some(index) = index else {
                        return if count == 2 {
                            Ok(args[3].clone())
                        } else {
                            Err(runtime.new_exception("KeyError", vec![key])?)
                        };
                    };
                    let stored = runtime.assoc_entries(owner)?[index].0.clone();
                    if !runtime.ordered_collections[&instance]
                        .order
                        .iter()
                        .any(|(old, _)| old.same_identity(&stored))
                    {
                        return Err(runtime.new_exception("KeyError", vec![key])?);
                    }
                    runtime.dictionary_find_known(owner, &[], &key, hash)?;
                    let (stored, value) = runtime.collection_remove_known(owner, &key, hash)?;
                    let state = runtime.ordered_collections.entry(instance).or_default();
                    if let Some(index) = state
                        .order
                        .iter()
                        .position(|(old, _)| old.same_identity(&stored))
                    {
                        state.order.remove(index);
                        state.version = state.version.wrapping_add(1);
                    }
                    Ok(value)
                }
                "popitem" if count == 1 => {
                    let last = runtime.truth(&args[2])?;
                    let state = runtime.ordered_collections[&instance].clone();
                    let pair = if last {
                        state.order.last()
                    } else {
                        state.order.first()
                    };
                    let Some((key, hash)) = pair.cloned() else {
                        return Err(pyerr("KeyError", "dictionary is empty"));
                    };
                    if runtime.assoc_size(owner) == 0 {
                        return Err(pyerr("KeyError", "dictionary is empty"));
                    }
                    runtime.roots[root].push(key.clone());
                    runtime.dictionary_find_known(owner, &[], &key, hash)?;
                    runtime.dictionary_find_known(owner, &[], &key, hash)?;
                    let (stored, value) = runtime.collection_remove_known(owner, &key, hash)?;
                    let state = runtime.ordered_collections.entry(instance).or_default();
                    if let Some(index) = state
                        .order
                        .iter()
                        .position(|(old, _)| old.same_identity(&stored))
                    {
                        state.order.remove(index);
                        state.version = state.version.wrapping_add(1);
                    }
                    Ok(runtime.obj_value(Object::Tuple(vec![stored, value])))
                }
                _ => Err(pyerr("TypeError", "invalid internal OrderedDict action")),
            }
        })
    }
}
