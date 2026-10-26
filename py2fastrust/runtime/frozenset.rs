// Immutable sets share Python's set protocols and retain member hashes.
// frozen_hash_combine adapts CPython 3.14.4 Objects/setobject.c
// _shuffle_bits / frozenset_hash_impl, under the PSF license bundled in
// THIRD_PARTY_LICENSES. https://github.com/python/cpython/blob/v3.14.4/Objects/setobject.c
fn frozen_hash_combine(hashes: &[i64]) -> i64 {
    let mut result = 0u64;
    for hash in hashes {
        let hash = *hash as u64;
        result ^= ((hash ^ 89_869_747) ^ (hash << 16)).wrapping_mul(3_644_798_167);
    }
    result ^= (hashes.len() as u64)
        .wrapping_add(1)
        .wrapping_mul(1_927_868_237);
    result ^= (result >> 11) ^ (result >> 25);
    result = result.wrapping_mul(69_069).wrapping_add(907_133_923);
    if result == u64::MAX {
        590_923_713
    } else {
        result as i64
    }
}
fn frozen_buckets(entries: &[(Value, i64)]) -> HashMap<i64, Vec<usize>> {
    let mut buckets = HashMap::<i64, Vec<usize>>::new();
    for (index, (_, hash)) in entries.iter().enumerate() {
        buckets.entry(*hash).or_default().push(index);
    }
    buckets
}
impl Runtime {
    fn frozen_owner(&self, value: &Value) -> Option<(usize, bool)> {
        match value {
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::Set(_)) => Some((*index, false)),
                Some(Object::FrozenSet { .. }) => Some((*index, true)),
                Some(Object::BuiltinInstance { payload, .. }) => self.frozen_owner(payload),
                _ => None,
            },
            _ => None,
        }
    }
    fn frozen_native(&self, value: &Value) -> bool {
        matches!(value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Set(_)|Object::FrozenSet{..})))
    }
    fn frozen_member_hash(&mut self, value: &Value) -> PyResult<i64> {
        let hash = self.builtin("hash", vec![value.clone()], Vec::new(), None)?;
        let number = self.as_int(&hash)?;
        Ok(number
            .to_i128()
            .map(|value| value as i64)
            .unwrap_or_else(|| numeric_int_hash(&number)))
    }
    fn frozen_entries(&mut self, value: &Value) -> PyResult<Vec<(Value, i64)>> {
        let (owner, frozen) = self
            .frozen_owner(value)
            .ok_or_else(|| pyerr("TypeError", "expected a set or frozenset"))?;
        if frozen {
            let Some(Object::FrozenSet { items, hashes, .. }) =
                self.heap.get(owner).and_then(Option::as_ref)
            else {
                unreachable!()
            };
            return Ok(items.iter().cloned().zip(hashes.iter().copied()).collect());
        }
        let Some(Object::Set(items)) = self.heap.get(owner).and_then(Option::as_ref) else {
            unreachable!()
        };
        let items = items.clone();
        self.view_rooted(vec![value.clone()], |runtime, root| {
            runtime.roots[root].extend(items.iter().cloned());
            let mut result = Vec::new();
            for item in items {
                let identity = runtime.identity_number(&item);
                let hash = if let Some(hash) = runtime
                    .set_member_hashes
                    .get(&owner)
                    .and_then(|map| map.get(&identity))
                {
                    *hash
                } else {
                    let hash = runtime.frozen_member_hash(&item)?;
                    runtime
                        .set_member_hashes
                        .entry(owner)
                        .or_default()
                        .insert(identity, hash);
                    hash
                };
                result.push((item, hash));
            }
            Ok(result)
        })
    }
    fn frozen_find(
        &mut self,
        items: &[(Value, i64)],
        value: &Value,
        hash: i64,
    ) -> PyResult<Option<usize>> {
        let mut roots = items
            .iter()
            .map(|(item, _)| item.clone())
            .collect::<Vec<_>>();
        roots.push(value.clone());
        self.view_rooted(roots, |runtime, _| {
            for (index, (candidate, candidate_hash)) in items.iter().enumerate() {
                if *candidate_hash == hash && runtime.identical_or_equal(candidate, value)? {
                    return Ok(Some(index));
                }
            }
            Ok(None)
        })
    }
    fn frozen_bucket_find(
        &mut self,
        items: &[(Value, i64)],
        buckets: &HashMap<i64, Vec<usize>>,
        value: &Value,
        hash: i64,
    ) -> PyResult<Option<usize>> {
        let Some(positions) = buckets.get(&hash) else {
            return Ok(None);
        };
        let candidates = positions
            .iter()
            .map(|index| items[*index].clone())
            .collect::<Vec<_>>();
        Ok(self
            .frozen_find(&candidates, value, hash)?
            .map(|index| positions[index]))
    }
    fn frozen_lookup(&mut self, owner: &Value, value: &Value, hash: i64) -> PyResult<bool> {
        self.view_rooted(vec![owner.clone(),value.clone()],|runtime,_|{
            let (index,frozen)=runtime.frozen_owner(owner).unwrap();
            if frozen {
                let Some(Object::FrozenSet{items,hashes,buckets,..})=runtime.heap.get(index).and_then(Option::as_ref) else{unreachable!()};
                let candidates=buckets.get(&hash).map(|positions|positions.iter().map(|position|(items[*position].clone(),hashes[*position])).collect::<Vec<_>>()).unwrap_or_default();
                return runtime.frozen_find(&candidates,value,hash).map(|found|found.is_some());
            }
            loop {let entries=runtime.frozen_entries(owner)?;let result=runtime.frozen_find(&entries,value,hash)?;
                let unchanged=matches!(runtime.heap.get(index).and_then(Option::as_ref),Some(Object::Set(items))if items.len()==entries.len()&&items.iter().zip(&entries).all(|(a,(b,_))|a.same_identity(b)));
                if unchanged{return Ok(result.is_some());}
            }
        })
    }
    fn frozen_collect(&mut self, value: Value) -> PyResult<Vec<(Value, i64)>> {
        if self.frozen_owner(&value).is_some() {
            return self.frozen_entries(&value);
        }
        self.view_rooted(vec![value.clone()], |runtime, root| {
            let iterator = runtime.iter(value)?;
            runtime.roots[root].push(iterator.clone());
            let mut result = Vec::new();
            let mut buckets = HashMap::<i64, Vec<usize>>::new();
            while let Some(item) = runtime.next(iterator.clone())? {
                runtime.roots[root].push(item.clone());
                let hash = runtime.frozen_member_hash(&item)?;
                if runtime
                    .frozen_bucket_find(&result, &buckets, &item, hash)?
                    .is_none()
                {
                    buckets.entry(hash).or_default().push(result.len());
                    result.push((item, hash));
                }
            }
            Ok(result)
        })
    }
    fn frozen_make(&mut self, entries: Vec<(Value, i64)>, frozen: bool) -> Value {
        let buckets = if frozen {
            frozen_buckets(&entries)
        } else {
            HashMap::new()
        };
        let (items, hashes): (Vec<_>, Vec<_>) = entries.into_iter().unzip();
        if frozen {
            self.obj_value(Object::FrozenSet {
                items,
                hashes,
                hash: None,
                buckets,
            })
        } else {
            let value = self.obj_value(Object::Set(items.clone()));
            let Value::Obj(owner) = value else {
                unreachable!()
            };
            let mut stored = HashMap::new();
            for (item, hash) in items.iter().zip(hashes) {
                stored.insert(self.identity_number(item), hash);
            }
            self.set_member_hashes.insert(owner, stored);
            value
        }
    }
    fn frozen_constructor(
        &mut self,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        if args.len() > 1 || !kwargs.is_empty() {
            return Err(pyerr(
                "TypeError",
                "frozenset expected at most one positional argument",
            ));
        }
        if let Some(value) = args.first() {
            if matches!(value,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::FrozenSet{..})))
            {
                return Ok(value.clone());
            }
        }
        let entries = if let Some(value) = args.first() {
            self.frozen_collect(value.clone())?
        } else {
            Vec::new()
        };
        Ok(self.frozen_make(entries, true))
    }
    fn set_constructor_value(
        &mut self,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        if args.len() > 1 || !kwargs.is_empty() {
            return Err(pyerr(
                "TypeError",
                "set expected at most one positional argument",
            ));
        }
        let entries = if let Some(value) = args.first() {
            self.frozen_collect(value.clone())?
        } else {
            Vec::new()
        };
        Ok(self.frozen_make(entries, false))
    }
    fn set_insert_value(&mut self, owner: usize, value: Value, known: Option<i64>) -> PyResult<()> {
        self.view_rooted(vec![Value::Obj(owner), value.clone()], |runtime, _| {
            let hash = match known {
                Some(hash) => hash,
                None => runtime.frozen_member_hash(&value)?,
            };
            loop {
                let entries = runtime.frozen_entries(&Value::Obj(owner))?;
                let found=runtime.frozen_find(&entries,&value,hash)?;
                let unchanged=matches!(runtime.heap.get(owner).and_then(Option::as_ref),Some(Object::Set(items))if items.len()==entries.len()&&items.iter().zip(&entries).all(|(a,(b,_))|a.same_identity(b)));
                if !unchanged {continue;}
                if found.is_some(){return Ok(());}
                if let Some(Object::Set(items)) =
                    runtime.heap.get_mut(owner).and_then(Option::as_mut)
                {
                    items.push(value.clone());
                }
                let identity = runtime.identity_number(&value);
                runtime
                    .set_member_hashes
                    .entry(owner)
                    .or_default()
                    .insert(identity, hash);
                runtime.assoc_inserted(owner, value);
                break;
            }
            Ok(())
        })
    }
    fn set_discard_value(&mut self, owner: usize, value: Value, required: bool) -> PyResult<Value> {
        self.set_discard_hashed(owner, value, required, None)
    }
    fn set_discard_hashed(
        &mut self,
        owner: usize,
        value: Value,
        required: bool,
        known: Option<i64>,
    ) -> PyResult<Value> {
        self.view_rooted(vec![Value::Obj(owner),value.clone()],|runtime,root| {
            let key=if runtime.frozen_owner(&value).is_some_and(|(_,frozen)|!frozen){let entries=runtime.frozen_entries(&value)?;let key=runtime.frozen_make(entries,true);runtime.roots[root].push(key.clone());key}else{value.clone()};
            let hash=match known {Some(hash)=>hash,None=>runtime.frozen_member_hash(&key)?};
            loop {
                let entries=runtime.frozen_entries(&Value::Obj(owner))?;
                let found=runtime.frozen_find(&entries,&key,hash)?;
                let unchanged=matches!(runtime.heap.get(owner).and_then(Option::as_ref),Some(Object::Set(items))if items.len()==entries.len()&&items.iter().zip(&entries).all(|(a,(b,_))|a.same_identity(b)));
                if !unchanged {continue;}
                if let Some(position)=found {
                    if let Some(Object::Set(items))=runtime.heap.get_mut(owner).and_then(Option::as_mut){let removed=items.remove(position);runtime.assoc_removed(owner,&removed);}
                    return Ok(Value::None);
                }
                return if required{Err(runtime.new_exception("KeyError",vec![value])?)}else{Ok(Value::None)};
            }
        })
    }
    fn frozen_transfer_hashes(&mut self, source: usize, target: usize) {
        if let Some(hashes) = self.set_member_hashes.get(&source).cloned() {
            self.set_member_hashes.insert(target, hashes);
        } else {
            self.set_member_hashes.remove(&target);
        }
    }
    fn frozen_hash(&mut self, value: &Value) -> PyResult<Value> {
        let (owner, frozen) = self
            .frozen_owner(value)
            .ok_or_else(|| pyerr("TypeError", "expected frozenset"))?;
        if !frozen {
            return Err(pyerr("TypeError", "unhashable type: 'set'"));
        }
        let Some(Object::FrozenSet { hashes, hash, .. }) =
            self.heap.get(owner).and_then(Option::as_ref)
        else {
            unreachable!()
        };
        let hash = hash.unwrap_or_else(|| frozen_hash_combine(hashes));
        if let Some(Object::FrozenSet { hash: stored, .. }) =
            self.heap.get_mut(owner).and_then(Option::as_mut)
        {
            *stored = Some(hash);
        }
        Ok(Value::Int(Int::from_i128(hash as i128).into()))
    }
    fn frozen_contains(&mut self, value: &Value, candidate: Value) -> PyResult<bool> {
        self.view_rooted(vec![value.clone(), candidate.clone()], |runtime, root| {
            let candidate = if runtime
                .frozen_owner(&candidate)
                .is_some_and(|(_, frozen)| !frozen)
            {
                let entries = runtime.frozen_entries(&candidate)?;
                let copy = runtime.frozen_make(entries, true);
                runtime.roots[root].push(copy.clone());
                copy
            } else {
                candidate
            };
            let hash = runtime.frozen_member_hash(&candidate)?;
            runtime.frozen_lookup(value, &candidate, hash)
        })
    }
    fn frozen_compare(&mut self, op: &str, left: &Value, right: &Value) -> Option<PyResult<bool>> {
        if !["==", "!=", "<", "<=", ">", ">="].contains(&op)
            || self.frozen_owner(left).is_none() && self.frozen_owner(right).is_none()
        {
            return None;
        }
        if self.frozen_owner(left).is_none() || self.frozen_owner(right).is_none() {
            return if op == "==" || op == "!=" {
                Some(Ok(op == "!="))
            } else {
                None
            };
        }
        Some(
            self.view_rooted(vec![left.clone(), right.clone()], |runtime, _| {
                let mut a = runtime.frozen_entries(left)?;
                let mut b = runtime.frozen_entries(right)?;
                if op == ">" || op == ">=" {
                    std::mem::swap(&mut a, &mut b);
                }
                let possible = if op == "==" || op == "!=" {
                    a.len() == b.len()
                } else {
                    a.len() <= b.len() && (!["<", ">"].contains(&op) || a.len() < b.len())
                };
                if !possible {
                    return Ok(op == "!=");
                }
                let target = if op == ">" || op == ">=" { left } else { right };
                for (item, hash) in a {
                    if !runtime.frozen_lookup(target, &item, hash)? {
                        return Ok(op == "!=");
                    }
                }
                Ok(op != "!=")
            }),
        )
    }
    fn frozen_operate(&mut self, op: &str, left: Value, right: Value) -> PyResult<Value> {
        self.view_rooted(vec![left.clone(), right.clone()], |runtime, root| {
            let a = runtime.frozen_entries(&left)?;
            let b = runtime.frozen_entries(&right)?;
            runtime.roots[root].extend(a.iter().chain(b.iter()).map(|(item, _)| item.clone()));
            let mut result = Vec::new();
            if op == "&" {
                let (first, second) = if a.len() < b.len() {
                    (&a, &right)
                } else {
                    (&b, &left)
                };
                for (item, hash) in first {
                    if runtime.frozen_lookup(second, item, *hash)? {
                        result.push((item.clone(), *hash));
                    }
                }
                return Ok(runtime.frozen_make(result, runtime.frozen_owner(&left).unwrap().1));
            }
            if op == "|" || op == "^" {
                let incoming = if op == "^" {
                    result = b;
                    a
                } else {
                    result = a;
                    b
                };
                let mut buckets = frozen_buckets(&result);
                let mut removed = std::collections::HashSet::new();
                for (item, hash) in incoming {
                    let found = runtime.frozen_bucket_find(&result, &buckets, &item, hash)?;
                    if let Some(index) = found {
                        if op == "^" {
                            removed.insert(index);
                            if let Some(positions) = buckets.get_mut(&hash) {
                                positions.retain(|position| *position != index);
                            }
                        }
                    } else {
                        buckets.entry(hash).or_default().push(result.len());
                        result.push((item, hash));
                    }
                }
                if !removed.is_empty() {
                    result = result
                        .into_iter()
                        .enumerate()
                        .filter_map(|(index, entry)| {
                            if removed.contains(&index) {
                                None
                            } else {
                                Some(entry)
                            }
                        })
                        .collect();
                }
            } else {
                for (item, hash) in &a {
                    if !runtime.frozen_lookup(&right, item, *hash)? {
                        result.push((item.clone(), *hash));
                    }
                }
            }
            let frozen = runtime.frozen_owner(&left).unwrap().1;
            Ok(runtime.frozen_make(result, frozen))
        })
    }
    fn frozen_stream(&mut self, receiver: Value, name: &str, source: Value) -> PyResult<Value> {
        self.view_rooted(vec![receiver.clone(), source.clone()], |runtime, root| {
            let own = runtime.frozen_entries(&receiver)?;
            runtime.roots[root].extend(own.iter().map(|(value, _)| value.clone()));
            let iterator = runtime.iter(source)?;
            runtime.roots[root].push(iterator.clone());
            let mut matching = Vec::new();
            let mut buckets = HashMap::<i64, Vec<usize>>::new();
            while let Some(item) = runtime.next(iterator.clone())? {
                runtime.roots[root].push(item.clone());
                let hash = runtime.frozen_member_hash(&item)?;
                let found = runtime.frozen_lookup(&receiver, &item, hash)?;
                if name == "isdisjoint" && found || name == "issuperset" && !found {
                    return Ok(Value::Bool(false));
                }
                if ["intersection", "issubset"].contains(&name)
                    && found
                    && runtime
                        .frozen_bucket_find(&matching, &buckets, &item, hash)?
                        .is_none()
                {
                    buckets.entry(hash).or_default().push(matching.len());
                    matching.push((item, hash));
                    if matching.len() == own.len() {
                        break;
                    }
                }
            }
            if name == "intersection" {
                Ok(runtime.frozen_make(matching, runtime.frozen_owner(&receiver).unwrap().1))
            } else {
                Ok(Value::Bool(
                    name != "issubset" || matching.len() == own.len(),
                ))
            }
        })
    }
    fn frozen_binary(&mut self, op: &str, left: &Value, right: &Value) -> Option<PyResult<Value>> {
        if !["|", "&", "-", "^"].contains(&op)
            || !self.frozen_native(left)
            || self.frozen_owner(right).is_none()
        {
            return None;
        }
        Some(self.frozen_operate(op, left.clone(), right.clone()))
    }
    fn frozen_iterator(&mut self, receiver: Value) -> PyResult<Value> {
        let (owner, _) = self
            .frozen_owner(&receiver)
            .ok_or_else(|| pyerr("TypeError", "expected set or frozenset"))?;
        let iterator = self.assoc_iterator(owner, DictViewKind::Keys, false)?;
        if !receiver.same_identity(&Value::Obj(owner)) {
            if let Value::Obj(index) = &iterator {
                if let Some(Object::Iterator(IteratorState::Associative(state))) =
                    self.heap.get_mut(*index).and_then(Option::as_mut)
                {
                    state.keeper = Some(receiver);
                }
            }
        }
        Ok(iterator)
    }
    fn frozen_method(
        &mut self,
        receiver: Value,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        let (owner, frozen) = self.frozen_owner(&receiver)?;
        if ![
            "copy",
            "union",
            "intersection",
            "difference",
            "symmetric_difference",
            "issubset",
            "issuperset",
            "isdisjoint",
            "__contains__",
            "__repr__",
            "__str__",
            "__hash__",
            "__eq__",
            "__ne__",
            "__lt__",
            "__le__",
            "__gt__",
            "__ge__",
            "__or__",
            "__ror__",
            "__and__",
            "__rand__",
            "__sub__",
            "__rsub__",
            "__xor__",
            "__rxor__",
            "__iter__",
            "__len__",
            "__reduce__",
            "__reduce_ex__",
        ]
        .contains(&name)
        {
            return None;
        }
        Some(self.view_rooted(vec![receiver.clone()], |runtime, root| {
            runtime.roots[root].extend(args.iter().cloned());
            if !kwargs.is_empty() {
                return Err(pyerr("TypeError", "set methods take no keyword arguments"));
            }
            let noargs = [
                "copy",
                "__repr__",
                "__str__",
                "__hash__",
                "__iter__",
                "__len__",
                "__reduce__",
            ]
            .contains(&name);
            if noargs && !args.is_empty()
                || !noargs
                    && !["union", "intersection", "difference"].contains(&name)
                    && args.len() != 1
            {
                return Err(pyerr("TypeError", "invalid set method arguments"));
            }
            match name {
                "copy" => {
                    if frozen && runtime.frozen_native(&receiver) {
                        Ok(receiver)
                    } else {
                        let entries = runtime.frozen_entries(&receiver)?;
                        Ok(runtime.frozen_make(entries, frozen))
                    }
                }
                "__iter__" => runtime.frozen_iterator(receiver),
                "__len__" => Ok(Value::Int(
                    Int::from_i128(runtime.assoc_size(owner) as i128).into(),
                )),
                "__hash__" => runtime.frozen_hash(&receiver),
                "__contains__" => runtime
                    .frozen_contains(&receiver, args[0].clone())
                    .map(Value::Bool),
                "__str__" => runtime.repr(&receiver).map(|text| Value::Str(text.into())),
                "__repr__" => runtime
                    .frozen_repr(&receiver, &mut Vec::new())
                    .map(|text| Value::Str(text.into())),
                "__reduce__" | "__reduce_ex__" => {
                    if name == "__reduce_ex__" {
                        runtime.as_int(&args[0])?;
                    }
                    let entries = runtime.frozen_entries(&receiver)?;
                    let items = runtime.obj_value(Object::List(
                        entries.into_iter().map(|(item, _)| item).collect(),
                    ));
                    runtime.roots[root].push(items.clone());
                    let args = runtime.obj_value(Object::Tuple(vec![items]));
                    runtime.roots[root].push(args.clone());
                    let class = runtime.getattr(receiver.clone(), "__class__")?;
                    let state = runtime
                        .native_payload(&receiver)
                        .and_then(|_| runtime.getattr(receiver.clone(), "__dict__").ok())
                        .unwrap_or(Value::None);
                    Ok(runtime.obj_value(Object::Tuple(vec![class, args, state])))
                }
                "__eq__" | "__ne__" | "__lt__" | "__le__" | "__gt__" | "__ge__" => {
                    let op = match name {
                        "__eq__" => "==",
                        "__ne__" => "!=",
                        "__lt__" => "<",
                        "__le__" => "<=",
                        "__gt__" => ">",
                        _ => ">=",
                    };
                    if runtime.frozen_owner(&args[0]).is_none() {
                        Ok(Value::Builtin("NotImplemented".into()))
                    } else {
                        runtime
                            .frozen_compare(op, &receiver, &args[0])
                            .unwrap()
                            .map(Value::Bool)
                    }
                }
                "__or__" | "__ror__" | "__and__" | "__rand__" | "__sub__" | "__rsub__"
                | "__xor__" | "__rxor__" => {
                    if runtime.frozen_owner(&args[0]).is_none() {
                        return Ok(Value::Builtin("NotImplemented".into()));
                    }
                    let op = if name.contains("or") && !name.contains("xor") {
                        "|"
                    } else if name.contains("and") {
                        "&"
                    } else if name.contains("sub") {
                        "-"
                    } else {
                        "^"
                    };
                    if name.starts_with("__r") {
                        runtime.frozen_operate(op, args[0].clone(), receiver)
                    } else {
                        runtime.frozen_operate(op, receiver, args[0].clone())
                    }
                }
                "issubset" | "issuperset" | "isdisjoint" => {
                    if runtime.frozen_owner(&args[0]).is_none()
                        || name == "isdisjoint" && !runtime.frozen_native(&args[0])
                    {
                        return runtime.frozen_stream(receiver, name, args[0].clone());
                    }
                    let mut a = runtime.frozen_entries(&receiver)?;
                    let mut b = runtime.frozen_collect(args[0].clone())?;
                    runtime.roots[root].extend(b.iter().map(|(item, _)| item.clone()));
                    if name == "issuperset" {
                        std::mem::swap(&mut a, &mut b);
                    }
                    let target = if name == "issuperset" {
                        receiver.clone()
                    } else {
                        args[0].clone()
                    };
                    for (item, hash) in a {
                        let found = runtime.frozen_lookup(&target, &item, hash)?;
                        if name == "isdisjoint" && found || name != "isdisjoint" && !found {
                            return Ok(Value::Bool(false));
                        }
                    }
                    Ok(Value::Bool(true))
                }
                _ => {
                    let op = match name {
                        "union" => "|",
                        "intersection" => "&",
                        "difference" => "-",
                        _ => "^",
                    };
                    let entries = runtime.frozen_entries(&receiver)?;
                    let mut result = runtime.frozen_make(entries, frozen);
                    runtime.roots[root].push(result.clone());
                    for source in args {
                        if name == "intersection" && runtime.frozen_owner(&source).is_none() {
                            result = runtime.frozen_stream(result, "intersection", source)?;
                            runtime.roots[root].push(result.clone());
                            continue;
                        }
                        let entries = runtime.frozen_collect(source)?;
                        let other = runtime.frozen_make(entries, frozen);
                        runtime.roots[root].push(other.clone());
                        result = runtime.frozen_operate(op, result, other)?;
                        runtime.roots[root].push(result.clone());
                    }
                    Ok(result)
                }
            }
        }))
    }
    fn frozen_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        if matches!(&value,Value::Builtin(class)if class=="frozenset") {
            if [
                "copy",
                "union",
                "intersection",
                "difference",
                "symmetric_difference",
                "issubset",
                "issuperset",
                "isdisjoint",
                "__contains__",
                "__repr__",
                "__str__",
                "__hash__",
                "__eq__",
                "__ne__",
                "__lt__",
                "__le__",
                "__gt__",
                "__ge__",
                "__or__",
                "__ror__",
                "__and__",
                "__rand__",
                "__sub__",
                "__rsub__",
                "__xor__",
                "__rxor__",
                "__iter__",
                "__len__",
                "__reduce__",
                "__reduce_ex__",
            ]
            .contains(&name)
            {
                return Some(Ok(Value::Builtin(format!("unbound:frozenset:{}", name))));
            }
            return None;
        }
        let (_, frozen) = self.frozen_owner(&value)?;
        if !frozen {
            return None;
        }
        if [
            "copy",
            "union",
            "intersection",
            "difference",
            "symmetric_difference",
            "issubset",
            "issuperset",
            "isdisjoint",
            "__contains__",
            "__repr__",
            "__str__",
            "__hash__",
            "__eq__",
            "__ne__",
            "__lt__",
            "__le__",
            "__gt__",
            "__ge__",
            "__or__",
            "__ror__",
            "__and__",
            "__rand__",
            "__sub__",
            "__rsub__",
            "__xor__",
            "__rxor__",
            "__iter__",
            "__len__",
            "__reduce__",
            "__reduce_ex__",
        ]
        .contains(&name)
        {
            return Some(Ok(self.obj_value(Object::Bound(
                Value::Builtin(format!("method:{}", name)),
                value,
            ))));
        }
        None
    }
    fn frozen_repr(&mut self, value: &Value, seen: &mut Vec<usize>) -> PyResult<String> {
        let (owner, _) = self
            .frozen_owner(value)
            .ok_or_else(|| pyerr("TypeError", "expected set or frozenset"))?;
        if !self.frozen_reprs.insert(owner) {
            return Ok(format!("{}(...)", self.typename(value)));
        }
        let outcome = self.view_rooted(vec![value.clone()], |runtime, _| {
            let entries = runtime.frozen_entries(value)?;
            let (_, frozen) = runtime.frozen_owner(value).unwrap();
            let class = if frozen {
                runtime.typename(value)
            } else {
                "set".into()
            };
            if entries.is_empty() {
                return Ok(format!("{}()", class));
            }
            let mut parts = Vec::new();
            for (item, _) in entries {
                parts.push(runtime.repr_inner(&item, seen)?);
            }
            let body = format!("{{{}}}", parts.join(", "));
            Ok(if frozen {
                format!("{}({})", class, body)
            } else {
                body
            })
        });
        self.frozen_reprs.remove(&owner);
        outcome
    }
}
