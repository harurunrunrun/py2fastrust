// Live dictionary views and iterators. Logical entry slots preserve deletion
// holes independently of the shared Vec used for current mapping contents.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum DictViewKind {
    Keys,
    Values,
    Items,
}
#[derive(Clone, Debug)]
struct AssocLayout {
    slots: Vec<Option<Value>>,
    table_size: usize,
    usable: usize,
    is_set: bool,
    retired: Vec<(usize, u64)>,
}
#[derive(Clone, Debug)]
struct AssocIterator {
    owner: Option<usize>,
    keeper:Option<Value>,
    kind: DictViewKind,
    is_set: bool,
    reversed: bool,
    position: isize,
    expected_size: usize,
    remaining: isize,
    size_error: bool,
}
impl DictViewKind {
    fn name(self) -> &'static str {
        match self {
            Self::Keys => "dict_keys",
            Self::Values => "dict_values",
            Self::Items => "dict_items",
        }
    }
}
impl AssocLayout {
    fn seeded(keys: Vec<Value>, is_set: bool) -> Self {
        let mut table_size = if keys.is_empty() && !is_set {
            1usize
        } else {
            8usize
        };
        while table_size.saturating_mul(2) / 3 < keys.len() {
            table_size = table_size.saturating_mul(2);
        }
        let usable = (table_size.saturating_mul(2) / 3).saturating_sub(keys.len());
        Self {
            slots: keys.into_iter().map(Some).collect(),
            table_size,
            usable,
            is_set,
            retired: Vec::new(),
        }
    }
}
impl Runtime {
    fn view_rooted<T>(
        &mut self,
        values: Vec<Value>,
        operation: impl FnOnce(&mut Self, usize) -> PyResult<T>,
    ) -> PyResult<T> {
        let root = self.roots.len();
        self.roots.push(values);
        let result = operation(self, root);
        self.roots.truncate(root);
        result
    }

    fn assoc_entries(&self, owner: usize) -> PyResult<Vec<(Value, Value)>> {
        match self.heap.get(owner).and_then(Option::as_ref) {
            Some(Object::Dict(entries)) => Ok(entries.clone()),
            Some(Object::Namespace(mapping, _)) => Ok(mapping.ident_items()),
            Some(Object::Set(values) | Object::FrozenSet{items:values,..}) => Ok(values
                .iter()
                .cloned()
                .map(|value| (value, Value::None))
                .collect()),
            _ => Err(pyerr("RuntimeError", "live mapping is no longer available")),
        }
    }
    fn assoc_size(&self, owner: usize) -> usize {
        match self.heap.get(owner).and_then(Option::as_ref) {
            Some(Object::Dict(entries)) => entries.len(),
            Some(Object::Namespace(mapping, _)) => mapping.len(),
            Some(Object::Set(values) | Object::FrozenSet{items:values,..}) => values.len(),
            _ => 0,
        }
    }
    fn assoc_seed(&mut self, owner: usize) {
        let (keys, is_set) = match self.heap.get(owner).and_then(Option::as_ref) {
            Some(Object::Dict(entries)) => {
                (entries.iter().map(|(key, _)| key.clone()).collect(), false)
            }
            Some(Object::Namespace(mapping, _)) => (mapping.ident_keys(), false),
            Some(Object::Set(values) | Object::FrozenSet{items:values,..}) => (values.clone(), true),
            _ => {
                self.assoc_layouts.remove(&owner);
                return;
            }
        };
        self.assoc_layouts
            .insert(owner, AssocLayout::seeded(keys, is_set));
    }
    fn assoc_inserted(&mut self, owner: usize, key: Value) {
        let identity = self.identity_number(&key);
        let Some(layout) = self.assoc_layouts.get_mut(&owner) else {
            self.assoc_seed(owner);
            return;
        };
        if layout.is_set {
            if let Some(retired) = layout.retired.iter().position(|(_, old)| *old == identity) {
                let (slot, _) = layout.retired.remove(retired);
                layout.slots[slot] = Some(key);
                return;
            }
            let active = layout.slots.iter().filter(|slot| slot.is_some()).count();
            if layout.slots.len() > active.saturating_add(1).saturating_mul(4).max(8) {
                layout.slots.retain(Option::is_some);
                layout.retired.clear();
            }
        } else if layout.usable == 0 {
            layout.slots.retain(Option::is_some);
            let requested = layout.slots.len().saturating_mul(3);
            let mut size = 8usize;
            while size <= requested {
                size = size.saturating_mul(2);
            }
            layout.table_size = size;
            layout.usable = (size.saturating_mul(2) / 3).saturating_sub(layout.slots.len());
        }
        layout.slots.push(Some(key));
        layout.usable = layout.usable.saturating_sub(1);
    }
    fn assoc_dictionary_removed(&mut self,owner:usize,index:usize){
        if let Some(layout)=self.assoc_layouts.get_mut(&owner){
            if let Some(position)=layout.slots.iter().enumerate().filter(|(_,slot)|slot.is_some()).nth(index).map(|(position,_)|position){layout.slots[position]=None;}
        }
    }
    fn assoc_removed(&mut self, owner: usize, key: &Value) {
        let identity = self.identity_number(key);
        if let Some(hashes)=self.set_member_hashes.get_mut(&owner){hashes.remove(&identity);}
        if let Some(layout) = self.assoc_layouts.get_mut(&owner) {
            if let Some(position) = layout.slots.iter().position(|slot| {
                slot.as_ref()
                    .map(|value| value.same_identity(key))
                    .unwrap_or(false)
            }) {
                layout.slots[position] = None;
                if layout.is_set {
                    layout.retired.push((position, identity));
                }
            }
        }
    }
    fn assoc_cleared(&mut self, owner: usize) {
        self.set_member_hashes.remove(&owner);
        self.dictionary_hashes.remove(&owner);
        let is_set = self
            .assoc_layouts
            .get(&owner)
            .map(|layout| layout.is_set)
            .unwrap_or(false);
        self.assoc_layouts
            .insert(owner, AssocLayout::seeded(Vec::new(), is_set));
    }
    // Catch replacements performed by a native helper while preserving every
    // unaffected logical slot. Ordinary mutations use the precise hooks above.
    fn assoc_sync(&mut self, owner: usize) -> PyResult<()> {
        let current = self.assoc_entries(owner)?;
        if !self.assoc_layouts.contains_key(&owner) {
            self.assoc_seed(owner);
            return Ok(());
        }
        let old = self.assoc_layouts[&owner]
            .slots
            .iter()
            .flatten()
            .cloned()
            .collect::<Vec<_>>();
        for key in old {
            if !current
                .iter()
                .any(|(candidate, _)| candidate.same_identity(&key))
            {
                self.assoc_removed(owner, &key);
            }
        }
        for (key, _) in current {
            if !self.assoc_layouts[&owner]
                .slots
                .iter()
                .flatten()
                .any(|candidate| candidate.same_identity(&key))
            {
                self.assoc_inserted(owner, key);
            }
        }
        Ok(())
    }
    fn assoc_iterator(
        &mut self,
        owner: usize,
        kind: DictViewKind,
        reversed: bool,
    ) -> PyResult<Value> {
        if !matches!(self.heap.get(owner).and_then(Option::as_ref),Some(Object::FrozenSet{..})){self.assoc_sync(owner)?;}
        let layout = &self.assoc_layouts[&owner];
        let expected_size = self.assoc_size(owner);
        let state = AssocIterator {
            owner: Some(owner),
            keeper:None,
            kind,
            is_set: layout.is_set,
            reversed,
            position: if reversed {
                layout.slots.len() as isize - 1
            } else {
                0
            },
            expected_size,
            remaining: expected_size as isize,
            size_error: false,
        };
        Ok(self.obj_value(Object::Iterator(IteratorState::Associative(state))))
    }
    fn assoc_next(&mut self, state: &mut AssocIterator) -> PyResult<Option<Value>> {
        let Some(owner) = state.owner else {
            return Ok(None);
        };
        if state.size_error || self.assoc_size(owner) != state.expected_size {
            state.size_error = true;
            return Err(pyerr(
                "RuntimeError",
                if state.is_set {
                    "Set changed size during iteration"
                } else {
                    "dictionary changed size during iteration"
                },
            ));
        }
        if !matches!(self.heap.get(owner).and_then(Option::as_ref),Some(Object::FrozenSet{..})){self.assoc_sync(owner)?;}
        let slots = &self.assoc_layouts[&owner].slots;
        let mut key = None;let mut entry_index=0;
        while state.position >= 0 && (state.position as usize) < slots.len() {
            let position = state.position as usize;
            state.position += if state.reversed { -1 } else { 1 };
            if let Some(value) = &slots[position] {
                key = Some(value.clone());entry_index=slots[..position].iter().filter(|slot|slot.is_some()).count();
                break;
            }
        }
        let Some(key) = key else {
            state.owner = None;
            state.keeper = None;
            return Ok(None);
        };
        if !state.is_set && !state.reversed && state.remaining == 0 {
            state.owner = None;
            state.keeper = None;
            return Err(pyerr(
                "RuntimeError",
                "dictionary keys changed during iteration",
            ));
        }
        state.remaining -= 1;
        if state.is_set || state.kind == DictViewKind::Keys {
            return Ok(Some(key));
        }
        let value = self
            .assoc_entries(owner)?
            .into_iter().nth(entry_index)
            .map(|(_, value)| value)
            .ok_or_else(|| pyerr("RuntimeError", "dictionary keys changed during iteration"))?;
        Ok(Some(if state.kind == DictViewKind::Values {
            value
        } else {
            self.obj_value(Object::Tuple(vec![key, value]))
        }))
    }
    fn assoc_hint(&self, state: &AssocIterator) -> isize {
        match state.owner {
            Some(owner) if !state.size_error && self.assoc_size(owner) == state.expected_size => {
                state.remaining
            }
            _ => 0,
        }
    }
    fn view_contains(
        &mut self,
        owner: usize,
        kind: DictViewKind,
        candidate: Value,
    ) -> PyResult<bool> {
        self.view_rooted(
            vec![Value::Obj(owner), candidate.clone()],
            |runtime, root| runtime.view_contains_inner(owner, kind, candidate, root),
        )
    }
    fn view_contains_inner(
        &mut self,
        owner: usize,
        kind: DictViewKind,
        candidate: Value,
        root: usize,
    ) -> PyResult<bool> {
        if kind == DictViewKind::Values {
            let iterator = self.assoc_iterator(owner, kind, false)?;
            self.roots[root].push(iterator.clone());
            while let Some(value) = self.next(iterator.clone())? {
                if self.identical_or_equal(&value, &candidate)? {
                    return Ok(true);
                }
            }
            return Ok(false);
        }
        let (key, wanted) = if kind == DictViewKind::Items {
            let payload = self.native_payload(&candidate).unwrap_or(candidate);
            let pair = match payload {
                Value::Obj(index) => match self.object(index)? {
                    Object::Tuple(pair) if pair.len() == 2 => pair,
                    _ => return Ok(false),
                },
                _ => return Ok(false),
            };
            (pair[0].clone(), Some(pair[1].clone()))
        } else {
            (candidate, None)
        };
        let hash=self.frozen_member_hash(&key)?;
        let entries = self.assoc_entries(owner)?;
        self.roots[root].extend(
            entries
                .iter()
                .flat_map(|(key, value)| [key.clone(), value.clone()]),
        );
        if let Some(position) = self.dictionary_find_known(owner,&entries,&key,hash)? {
            if let Some(wanted) = wanted {
                let current=self.assoc_entries(owner)?;
                return self.identical_or_equal(&current[position].1, &wanted);
            }
            return Ok(true);
        }
        Ok(false)
    }
    fn view_kind(&self, value: &Value) -> Option<(usize, DictViewKind)> {
        if let Value::Obj(index) = value {
            if let Some(Object::DictView { owner, kind }) =
                self.heap.get(*index).and_then(Option::as_ref)
            {
                return Some((*owner, *kind));
            }
        }
        None
    }
    fn view_is_setlike(&self, value: &Value) -> bool {
        self.view_kind(value)
            .map(|(_, kind)| kind != DictViewKind::Values)
            .unwrap_or(false)
            || matches!(value,Value::Obj(index) if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Set(_) | Object::FrozenSet{..})))
            || matches!(self.native_payload(value),Some(Value::Obj(index)) if matches!(self.heap.get(index).and_then(Option::as_ref),Some(Object::Set(_) | Object::FrozenSet{..})))
    }
    fn view_compare(&mut self, op: &str, a: &Value, b: &Value) -> Option<PyResult<bool>> {
        if self.view_kind(a).is_none() && self.view_kind(b).is_none() {
            return None;
        }
        if !["==", "!=", "<", "<=", ">", ">="].contains(&op) {
            return None;
        }
        if self
            .view_kind(a)
            .map(|(_, kind)| kind == DictViewKind::Values)
            .unwrap_or(false)
            || self
                .view_kind(b)
                .map(|(_, kind)| kind == DictViewKind::Values)
                .unwrap_or(false)
        {
            if ["==", "!="].contains(&op) {
                return Some(Ok(a.same_identity(b) == (op == "==")));
            }
            return Some(Err(pyerr(
                "TypeError",
                "dict_values does not support ordering",
            )));
        }
        if !self.view_is_setlike(a) || !self.view_is_setlike(b) {
            return if ["==", "!="].contains(&op) {
                Some(Ok(op == "!="))
            } else {
                Some(Err(pyerr(
                    "TypeError",
                    "dictionary view ordering requires a set-like operand",
                )))
            };
        }
        Some(
            self.view_rooted(vec![a.clone(), b.clone()], |runtime, root| {
                let left = runtime.to_vec(a.clone())?;
                runtime.roots[root].extend(left.iter().cloned());
                let right = runtime.to_vec(b.clone())?;
                runtime.roots[root].extend(right.iter().cloned());
                let (subset, strict) = match op {
                    ">" | ">=" => (false, op == ">"),
                    _ => (true, op == "<"),
                };
                let (first, second) = if subset {
                    (&left, &right)
                } else {
                    (&right, &left)
                };
                let result = match op {
                    "==" | "!=" => left.len() == right.len(),
                    _ => first.len() <= second.len() && (!strict || first.len() < second.len()),
                };
                if !result {
                    return Ok(op == "!=");
                }
                for value in first {
                    if !runtime.contains_vec(second, value)? {
                        return Ok(op == "!=");
                    }
                }
                Ok(op != "!=")
            }),
        )
    }
    fn view_binary(&mut self, op: &str, a: Value, b: Value) -> Option<PyResult<Value>> {
        let has_view = [&a, &b].iter().any(|value| {
            self.view_kind(value)
                .map(|(_, kind)| kind != DictViewKind::Values)
                .unwrap_or(false)
        });
        if !has_view || !["|", "&", "-", "^"].contains(&op) {
            return None;
        }
        let item_xor = op == "^"
            && self
                .view_kind(&a)
                .map(|(_, kind)| kind == DictViewKind::Items)
                .unwrap_or(false)
            && self
                .view_kind(&b)
                .map(|(_, kind)| kind == DictViewKind::Items)
                .unwrap_or(false);
        Some(
            self.view_rooted(vec![a.clone(), b.clone()], |runtime, root| {
                let left = runtime.to_vec(a)?;
                runtime.roots[root].extend(left.iter().cloned());
                let right = runtime.to_vec(b)?;
                runtime.roots[root].extend(right.iter().cloned());
                let mut result = Vec::new();
                let mut hashes=HashMap::new();
                if op == "-" || (op == "^" && !item_xor) {
                    for value in &left {
                        let hash=runtime.frozen_member_hash(value)?;let identity=runtime.identity_number(value);hashes.insert(identity,hash);
                    }
                }
                for value in &left {
                    let found = runtime.contains_vec(&right, value)?;
                    if op == "|" || (op == "&" && found) || ((op == "-" || op == "^") && !found) {
                        let hash=runtime.frozen_member_hash(value)?;let identity=runtime.identity_number(value);hashes.insert(identity,hash);
                        if !runtime.contains_vec(&result, value)? {
                            result.push(value.clone());
                        }
                    }
                }
                if op == "|" || op == "^" {
                    for value in right {
                        if op == "|" || !runtime.contains_vec(&left, &value)? {
                            let hash=runtime.frozen_member_hash(&value)?;let identity=runtime.identity_number(&value);hashes.insert(identity,hash);
                            if !runtime.contains_vec(&result, &value)? {
                                result.push(value);
                            }
                        }
                    }
                }
                let entries=result.into_iter().map(|value|{let hash=hashes[&runtime.identity_number(&value)];(value,hash)}).collect();
                Ok(runtime.frozen_make(entries,false))
            }),
        )
    }
    fn dictview_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        let Value::Obj(index) = &value else {
            return None;
        };
        let object = self.heap.get(*index).and_then(Option::as_ref)?.clone();
        let supported = match object {
            Object::DictView { owner, kind } => {
                if name == "mapping" {
                    return Some(Ok(self.obj_value(Object::MappingProxy { owner })));
                }
                [
                    "__iter__",
                    "__reversed__",
                    "__len__",
                    "__contains__",
                    "__repr__",
                    "__str__",
                ]
                .contains(&name)
                    || ["__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"].contains(&name)
                    || (kind != DictViewKind::Values
                        && [
                            "isdisjoint",
                            "__and__",
                            "__or__",
                            "__sub__",
                            "__xor__",
                            "__rand__",
                            "__ror__",
                            "__rsub__",
                            "__rxor__",
                        ]
                        .contains(&name))
            }
            Object::MappingProxy { .. } => [
                "__iter__",
                "__reversed__",
                "__len__",
                "__contains__",
                "__getitem__",
                "__repr__",
                "__str__",
                "keys",
                "values",
                "items",
                "get",
                "copy",
                "__or__",
                "__ror__",
            ]
            .contains(&name),
            Object::Iterator(IteratorState::Associative(_)) => {
                ["__iter__", "__next__", "__length_hint__"].contains(&name)
            }
            _ => return None,
        };
        if name == "__class__" {
            return None;
        }
        Some(if supported {
            Ok(self.obj_value(Object::Bound(
                Value::Builtin(format!("method:{name}")),
                value,
            )))
        } else {
            Err(pyerr(
                "AttributeError",
                format!(
                    "'{}' object has no attribute '{}'",
                    self.typename(&value),
                    name
                ),
            ))
        })
    }
    fn dictview_method(
        &mut self,
        value: Value,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> Option<PyResult<Value>> {
        let Value::Obj(index) = &value else {
            return None;
        };
        let object = self.heap.get(*index).and_then(Option::as_ref)?.clone();
        if matches!(object, Object::Dict(_) | Object::Namespace(..)) && name == "__contains__" {
            return Some(if args.len() != 1 || !kwargs.is_empty() {
                Err(pyerr("TypeError", "__contains__ expected one argument"))
            } else {
                self.view_contains(*index, DictViewKind::Keys, args[0].clone())
                    .map(Value::Bool)
            });
        }
        if matches!(object, Object::Dict(_) | Object::Namespace(..))
            && ["keys", "values", "items", "__reversed__"].contains(&name)
        {
            return Some(if !args.is_empty() || !kwargs.is_empty() {
                Err(pyerr("TypeError", format!("{name}() takes no arguments")))
            } else if name == "__reversed__" {
                self.assoc_iterator(*index, DictViewKind::Keys, true)
            } else {
                Ok(self.obj_value(Object::DictView {
                    owner: *index,
                    kind: match name {
                        "keys" => DictViewKind::Keys,
                        "values" => DictViewKind::Values,
                        _ => DictViewKind::Items,
                    },
                }))
            });
        }
        if !matches!(
            object,
            Object::DictView { .. }
                | Object::MappingProxy { .. }
                | Object::Iterator(IteratorState::Associative(_))
        ) {
            return None;
        }
        Some((|| {
            if !kwargs.is_empty() {
                return Err(pyerr(
                    "TypeError",
                    format!("{name}() takes no keyword arguments"),
                ));
            }
            let arg = || {
                args.first()
                    .cloned()
                    .ok_or_else(|| pyerr("TypeError", format!("{name}() requires an argument")))
            };
            match object {
                Object::Iterator(IteratorState::Associative(state)) => match name {
                    "__iter__" if args.is_empty() => Ok(value),
                    "__next__" if args.is_empty() => self.iterator_next(value),
                    "__length_hint__" if args.is_empty() => Ok(Value::Int(
                        Int::from_i128(self.assoc_hint(&state) as i128).into(),
                    )),
                    _ => Err(pyerr("TypeError", "invalid iterator method arguments")),
                },
                Object::DictView { owner, kind } => match name {
                    "__iter__" if args.is_empty() => self.assoc_iterator(owner, kind, false),
                    "__reversed__" if args.is_empty() => self.assoc_iterator(owner, kind, true),
                    "__len__" if args.is_empty() => Ok(Value::Int(
                        Int::from_i128(self.assoc_size(owner) as i128).into(),
                    )),
                    "__contains__" if args.len() == 1 => {
                        Ok(Value::Bool(self.view_contains(owner, kind, arg()?)?))
                    }
                    "__repr__" if args.is_empty() => Ok(Value::Str(self.repr(&value)?.into())),
                    "__str__" if args.is_empty() => Ok(Value::Str(self.str_value(&value)?.into())),
                    "isdisjoint" if args.len() == 1 && kind != DictViewKind::Values => self
                        .view_rooted(vec![value.clone(), arg()?], |runtime, root| {
                            let iterator = runtime.iter(args[0].clone())?;
                            runtime.roots[root].push(iterator.clone());
                            while let Some(candidate) = runtime.next(iterator.clone())? {
                                if runtime.view_contains(owner, kind, candidate)? {
                                    return Ok(Value::Bool(false));
                                }
                            }
                            Ok(Value::Bool(true))
                        }),
                    "__and__" | "__or__" | "__sub__" | "__xor__" | "__rand__" | "__ror__"
                    | "__rsub__" | "__rxor__"
                        if args.len() == 1 && kind != DictViewKind::Values =>
                    {
                        let op = if name.contains("and") {
                            "&"
                        } else if name.contains("xor") {
                            "^"
                        } else if name.contains("sub") {
                            "-"
                        } else {
                            "|"
                        };
                        let (a, b) = if name.starts_with("__r") {
                            (arg()?, value)
                        } else {
                            (value, arg()?)
                        };
                        self.view_binary(op, a, b).unwrap()
                    }
                    "__eq__" | "__ne__" | "__lt__" | "__le__" | "__gt__" | "__ge__"
                        if args.len() == 1 =>
                    {
                        let op = match name {
                            "__eq__" => "==",
                            "__ne__" => "!=",
                            "__lt__" => "<",
                            "__le__" => "<=",
                            "__gt__" => ">",
                            _ => ">=",
                        };
                        let other = arg()?;
                        if kind == DictViewKind::Values {
                            if ["==", "!="].contains(&op) && value.same_identity(&other) {
                                return Ok(Value::Bool(op == "=="));
                            }
                            return Ok(Value::Builtin("NotImplemented".into()));
                        }
                        if !self.view_is_setlike(&other) {
                            return Ok(Value::Builtin("NotImplemented".into()));
                        }
                        Ok(Value::Bool(self.view_compare(op, &value, &other).unwrap()?))
                    }
                    _ => Err(pyerr("TypeError", format!("invalid {name} arguments"))),
                },
                Object::MappingProxy { owner } => match name {
                    "__iter__" if args.is_empty() => {
                        self.assoc_iterator(owner, DictViewKind::Keys, false)
                    }
                    "__reversed__" if args.is_empty() => {
                        self.assoc_iterator(owner, DictViewKind::Keys, true)
                    }
                    "__len__" if args.is_empty() => Ok(Value::Int(
                        Int::from_i128(self.assoc_size(owner) as i128).into(),
                    )),
                    "__contains__" if args.len() == 1 => Ok(Value::Bool(self.view_contains(
                        owner,
                        DictViewKind::Keys,
                        arg()?,
                    )?)),
                    "__getitem__" if args.len() == 1 => self.getitem(Value::Obj(owner), arg()?),
                    "__repr__" if args.is_empty() => Ok(Value::Str(self.repr(&value)?.into())),
                    "__str__" if args.is_empty() => Ok(Value::Str(self.str_value(&value)?.into())),
                    "get" if (1..=2).contains(&args.len()) => {
                        self.method(name, Value::Obj(owner), args, Vec::new())
                    }
                    "copy" | "keys" | "values" | "items" if args.is_empty() => {
                        self.method(name, Value::Obj(owner), Vec::new(), Vec::new())
                    }
                    "__or__" | "__ror__" if args.len() == 1 => {
                        let (a, b) = if name == "__ror__" {
                            (arg()?, Value::Obj(owner))
                        } else {
                            (Value::Obj(owner), arg()?)
                        };
                        self.binary("|", a, b)
                    }
                    _ => Err(pyerr(
                        "TypeError",
                        format!("invalid mappingproxy {name} arguments"),
                    )),
                },
                _ => unreachable!(),
            }
        })())
    }
    fn dictview_repr(
        &mut self,
        owner: usize,
        kind: Option<DictViewKind>,
        seen: &mut Vec<usize>,
    ) -> PyResult<String> {
        let Some(kind) = kind else {
            return Ok(format!(
                "mappingproxy({})",
                self.repr_inner(&Value::Obj(owner), seen)?
            ));
        };
        let mut parts = Vec::new();
        for (key, value) in self.assoc_entries(owner)? {
            parts.push(match kind {
                DictViewKind::Keys => self.repr_inner(&key, seen)?,
                DictViewKind::Values => self.repr_inner(&value, seen)?,
                DictViewKind::Items => format!(
                    "({}, {})",
                    self.repr_inner(&key, seen)?,
                    self.repr_inner(&value, seen)?
                ),
            });
        }
        Ok(format!("{}([{}])", kind.name(), parts.join(", ")))
    }
}
impl Runtime {
    fn proxy_payload(&self, value: &Value) -> Option<Value> {
        if let Value::Obj(index) = value {
            if let Some(Object::MappingProxy { owner }) =
                self.heap.get(*index).and_then(Option::as_ref)
            {
                return Some(Value::Obj(*owner));
            }
        }
        None
    }
}
impl Runtime {
    fn live_set_update(
        &mut self,
        owner: usize,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        if !kwargs.is_empty() || (name == "symmetric_difference_update" && args.len() != 1) {
            return Err(pyerr("TypeError", "invalid set update arguments"));
        }
        self.view_rooted(vec![Value::Obj(owner)], |runtime, root| {
            runtime.roots[root].extend(args.iter().cloned());
            if name == "intersection_update" || name == "symmetric_difference_update" {
                let entries=runtime.frozen_entries(&Value::Obj(owner))?;
                let mut result=runtime.frozen_make(entries,false);
                runtime.roots[root].push(result.clone());
                for source in args {
                    let unique = runtime.builtin("set", vec![source], Vec::new(), None)?;
                    runtime.roots[root].push(unique.clone());
                    result = runtime.binary(
                        if name == "intersection_update" {
                            "&"
                        } else {
                            "^"
                        },
                        result,
                        unique,
                    )?;
                    runtime.roots[root].push(result.clone());
                }
                if let Value::Obj(result) = result {
                    runtime.heap[owner] = Some(runtime.object(result)?);
                    runtime.frozen_transfer_hashes(result,owner);
                    runtime.assoc_sync(owner)?;
                }
                return Ok(Value::None);
            }
            for source in args {
                if name == "difference_update" && source.same_identity(&Value::Obj(owner)) {
                    runtime.heap[owner] = Some(Object::Set(Vec::new()));
                    runtime.assoc_cleared(owner);
                    continue;
                }
                if runtime.frozen_owner(&source).is_some(){
                    let entries=runtime.frozen_entries(&source)?;runtime.roots[root].extend(entries.iter().map(|(item,_)|item.clone()));
                    for (value,hash) in entries {if name=="update"{runtime.set_insert_value(owner,value,Some(hash))?;}else{runtime.set_discard_hashed(owner,value,false,Some(hash))?;}}
                    continue;
                }
                let iterator = runtime.iter(source)?;
                runtime.roots[root].push(iterator.clone());
                while let Some(value) = runtime.next(iterator.clone())? {
                    if name == "update" {
                        runtime.container_add(Value::Obj(owner), value, true)?;
                    } else {
                        runtime.method("discard", Value::Obj(owner), vec![value], Vec::new())?;
                    }
                }
            }
            Ok(Value::None)
        })
    }
}
impl Runtime {
    fn assoc_length_hint(
        &mut self,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        if !(1..=2).contains(&args.len()) || !kwargs.is_empty() {
            return Err(pyerr(
                "TypeError",
                "length_hint() takes 1 or 2 positional arguments",
            ));
        }
        let default = args
            .get(1)
            .map(|value| self.as_int(value))
            .transpose()?
            .unwrap_or_else(|| Int::from_i128(0));
        let default = default
            .to_i128()
            .filter(|value| *value >= isize::MIN as i128 && *value <= isize::MAX as i128)
            .ok_or_else(|| {
                pyerr(
                    "OverflowError",
                    "Python int too large to convert to C ssize_t",
                )
            })?;
        let result = match self.builtin("len", vec![args[0].clone()], Vec::new(), None) {
            Ok(length) => length,
            Err(error) if self.exception_has_native_class(&error, "TypeError") => {
                match self.special_method(args[0].clone(), "__length_hint__") {
                    Ok(method) => {
                        let hint = self.call(method, Vec::new(), Vec::new(), None)?;
                        if matches!(&hint,Value::Builtin(name)if name=="NotImplemented") {
                            return Ok(Value::Int(Int::from_i128(default).into()));
                        }
                        hint
                    }
                    Err(error) if self.missing_special_method(&args[0],"__length_hint__",&error) => {
                        return Ok(Value::Int(Int::from_i128(default).into()))
                    }
                    Err(error) => return Err(error),
                }
            }
            Err(error) => return Err(error),
        };
        let value = match &result {
            Value::Int(value) => value.inner().clone(),
            Value::Bool(value) => Int::from_i128(if *value { 1 } else { 0 }),
            _ => return Err(pyerr("TypeError", "__length_hint__ must be an integer")),
        };
        let size = value
            .to_i128()
            .filter(|value| *value <= isize::MAX as i128)
            .ok_or_else(|| {
                pyerr(
                    "OverflowError",
                    "Python int too large to convert to C ssize_t",
                )
            })?;
        if size < 0 {
            return Err(pyerr("ValueError", "__length_hint__() should return >= 0"));
        }
        Ok(Value::Int(value.into()))
    }
}
impl Runtime {
    fn assoc_mapping_equal(&mut self, left: usize, right: usize) -> PyResult<bool> {
        self.view_rooted(
            vec![Value::Obj(left), Value::Obj(right)],
            |runtime, root| {
                let a = runtime.assoc_entries(left)?;
                let b = runtime.assoc_entries(right)?;
                if a.len() != b.len() {
                    return Ok(false);
                }
                runtime.roots[root].extend(
                    a.iter()
                        .chain(&b)
                        .flat_map(|(key, value)| [key.clone(), value.clone()]),
                );
                for(index,(key,value))in a.into_iter().enumerate(){
                    let hash=runtime.dictionary_entry_hash(left,index,&key)?;
                    let Some(position)=runtime.dictionary_find_known(right,&b,&key,hash)? else {
                        return Ok(false);
                    };
                    let current=runtime.assoc_entries(right)?;
                    if !runtime.identical_or_equal(&value, &current[position].1)? {
                        return Ok(false);
                    }
                }
                Ok(true)
            },
        )
    }
}
