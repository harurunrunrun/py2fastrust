// Bulk set operations share the queued lookup machinery. Native set inputs
// retain their stored hashes; arbitrary iterables are consumed in Python order.
#[derive(Clone, Debug)]
struct ProtocolSetBulk {
    name: String, receiver: Value, working: Value, sources: Vec<Value>,
    sources_root: Value, index: usize, update: bool, frozen: bool, waiting: bool,
}
#[derive(Clone, Debug)]
struct ProtocolSetSource {
    name: String, working: Value, source: Value, lookup: Value, matching: Value,
    iterator: Option<Value>, entries: Vec<(Value, i64)>, entries_root: Value,
    index: usize, current: Option<Value>, hash: i64, phase: u8,
    native: bool, copy_difference: bool, own_size: usize, update: bool,
}
#[derive(Clone, Debug)]
enum ProtocolSetWork { Bulk(ProtocolSetBulk), Source(ProtocolSetSource) }
impl ProtocolSetWork {
    fn roots(&self, roots: &mut Vec<Value>) {
        match self {
            Self::Bulk(record) => roots.extend([record.receiver.clone(), record.working.clone(), record.sources_root.clone()]),
            Self::Source(record) => {
                roots.extend([record.working.clone(), record.source.clone(), record.lookup.clone(), record.matching.clone(), record.entries_root.clone()]);
                roots.extend(record.iterator.iter().cloned());
                roots.extend(record.current.iter().cloned());
            }
        }
    }
}
impl Runtime {
    fn protocol_set_plain_value(value: &Value) -> bool {
        matches!(value, Value::None | Value::Bool(_) | Value::Int(_) | Value::Float(_) | Value::Complex(_) | Value::Str(_) | Value::Bytes(_))
    }
    fn protocol_set_native_input(&self, source: &Value) -> bool {
        match source {
            Value::Str(_) | Value::Bytes(_) => true,
            Value::Obj(owner) => match self.heap.get(*owner).and_then(Option::as_ref) {
                Some(Object::Range(..)) => true,
                Some(Object::List(values) | Object::Tuple(values) | Object::Set(values) | Object::FrozenSet { items: values, .. }) => values.iter().all(Self::protocol_set_plain_value),
                _ => false,
            },
            _ => false,
        }
    }
    fn protocol_set_bulk_builtin(&mut self, state: &mut ProtocolState, plan: &ProtocolPlan) -> PyResult<bool> {
        let Value::Builtin(function) = &plan.function else { return Ok(false) };
        let name = function.strip_prefix("method:")
            .or_else(|| native_attribute_parts(&plan.function).map(|(_, _, name)| name))
            .or_else(|| operand_descriptor(&plan.function).map(|(_, name)| name))
            .or_else(|| function.strip_prefix("unbound:").and_then(|name| name.split_once(':').map(|(_, name)| name)));
        let Some(name) = name else { return Ok(false) };
        let Some(receiver) = plan.args.first() else { return Ok(false) };
        let Some((owner, frozen)) = self.frozen_owner(receiver) else { return Ok(false) };
        if let Some((_, owner, _)) = native_attribute_parts(&plan.function) {
            if owner == "set" && frozen || owner == "frozenset" && !frozen { return Ok(false) }
        }
        if let Some((base, reflected, inplace)) = match name {
            "__or__" => Some(("union", false, false)), "__ror__" => Some(("union", true, false)),
            "__and__" => Some(("intersection", false, false)), "__rand__" => Some(("intersection", true, false)),
            "__sub__" => Some(("difference", false, false)), "__rsub__" => Some(("difference", true, false)),
            "__xor__" => Some(("symmetric_difference", false, false)), "__rxor__" => Some(("symmetric_difference", true, false)),
            "__ior__" => Some(("update", false, true)), "__iand__" => Some(("intersection_update", false, true)),
            "__isub__" => Some(("difference_update", false, true)), "__ixor__" => Some(("symmetric_difference_update", false, true)),
            _ => None,
        } {
            if plan.args.len() != 2 || !plan.kwargs.is_empty() { return Err(pyerr("TypeError", "invalid set operator arguments")); }
            if self.frozen_owner(&plan.args[1]).is_none() {
                state.value = Some(Value::Builtin("NotImplemented".into()));
                return Ok(true);
            }
            if inplace { state.actions.push_front(ProtocolAction::Return(receiver.clone())); }
            let args = if reflected { vec![plan.args[1].clone(), receiver.clone()] } else { plan.args.clone() };
            state.plan = Some(ProtocolPlan { function: Value::Builtin(format!("method:{base}")), args, kwargs: Vec::new() });
            return Ok(true);
        }
        let update = name.ends_with("_update");
        let base = name.strip_suffix("_update").unwrap_or(name);
        if !["union", "intersection", "difference", "symmetric_difference", "issubset", "issuperset", "isdisjoint"].contains(&base) || (update && frozen) { return Ok(false) }
        if !plan.kwargs.is_empty() || (["symmetric_difference", "issubset", "issuperset", "isdisjoint"].contains(&base) && plan.args.len() != 2) {
            return Err(pyerr("TypeError", "invalid set method arguments"));
        }
        let sources = plan.args[1..].to_vec();
        // Keep indexed native algorithms when no submitted callback can run.
        // Checking once costs O(n); queued lookup snapshots otherwise cost O(n)
        // per primitive key and would regress large competitive-programming sets.
        if self.protocol_set_native_input(&Value::Obj(owner)) && sources.iter().all(|source| self.protocol_set_native_input(source)) {
            state.value = Some(self.method(name, receiver.clone(), sources, plan.kwargs.clone())?);
            return Ok(true);
        }
        let working = if update && base != "intersection" || base == "intersection" && !sources.is_empty() || ["issubset", "issuperset", "isdisjoint"].contains(&base) {
            Value::Obj(owner)
        } else {
            let entries = self.frozen_entries(receiver)?;
            self.frozen_make(entries, false)
        };
        if base == "union" {
            self.protocol_set_input(state, working, sources, frozen, true)?;
            return Ok(true);
        }
        let sources_root = self.obj_value(Object::Tuple(sources.clone()));
        state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Bulk(ProtocolSetBulk {
            name: base.into(), receiver: receiver.clone(), working, sources, sources_root,
            index: 0, update, frozen, waiting: false,
        }))));
        state.value = Some(Value::None);
        Ok(true)
    }
    fn protocol_set_bulk_result(&mut self, state: &mut ProtocolState, mut record: ProtocolSetBulk, value: Value) -> PyResult<()> {
        if record.waiting {
            if ["issubset", "issuperset", "isdisjoint"].contains(&record.name.as_str()) {
                state.value = Some(value);
                return Ok(());
            }
            record.working = value;
            record.index += 1;
        }
        if record.index == record.sources.len() {
            if record.update {
                if record.name == "intersection" {
                    let owner = self.frozen_owner(&record.receiver).unwrap().0;
                    let result = self.frozen_owner(&record.working).unwrap().0;
                    self.heap[owner] = Some(self.object(result)?);
                    self.frozen_transfer_hashes(result, owner);
                    self.assoc_sync(owner)?;
                }
                state.value = Some(Value::None);
            } else if record.frozen {
                let entries = self.frozen_entries(&record.working)?;
                state.value = Some(self.frozen_make(entries, true));
            } else { state.value = Some(record.working); }
            return Ok(());
        }
        let source = record.sources[record.index].clone();
        let work = ProtocolSetSource {
            name: record.name.clone(), working: record.working.clone(), source,
            lookup: Value::None, matching: Value::None, iterator: None, entries: Vec::new(),
            entries_root: Value::None, index: 0, current: None, hash: 0, phase: 0,
            native: false, copy_difference: false, own_size: 0, update: record.update,
        };
        record.waiting = true;
        state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Bulk(record))));
        state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Source(work))));
        state.value = Some(Value::None);
        Ok(())
    }
    fn protocol_set_source_entries(&mut self, record: &mut ProtocolSetSource, entries: Vec<(Value, i64)>) {
        record.entries_root = self.obj_value(Object::Tuple(entries.iter().map(|(key, _)| key.clone()).collect()));
        record.entries = entries;
        record.native = true;
        record.index = 0;
    }
    fn protocol_set_source_finish(&mut self, state: &mut ProtocolState, record: ProtocolSetSource) -> PyResult<()> {
        let result = match record.name.as_str() {
            "intersection" => record.matching,
            "difference" if record.copy_difference => record.matching,
            "issubset" if !record.native => {
                let owner = self.frozen_owner(&record.matching).unwrap().0;
                let current = self.frozen_owner(&record.working).unwrap().0;
                Value::Bool(self.assoc_size(owner) == self.assoc_size(current))
            }
            "issubset" | "issuperset" | "isdisjoint" => Value::Bool(true),
            _ => record.working,
        };
        state.value = Some(result);
        Ok(())
    }
    fn protocol_set_source_next(&mut self, state: &mut ProtocolState, mut record: ProtocolSetSource) -> PyResult<()> {
        record.current = None;
        if record.native {
            if record.index == record.entries.len() { return self.protocol_set_source_finish(state, record) }
            let (value, hash) = record.entries[record.index].clone();
            record.index += 1;
            record.current = Some(value);
            record.hash = hash;
            self.protocol_set_source_lookup(state, record)
        } else {
            record.phase = 2;
            let iterator = record.iterator.clone().unwrap();
            state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Source(record))));
            state.plan = Some(ProtocolPlan { function: Value::Builtin("next".into()), args: vec![iterator, Value::Builtin("$setbulk:end".into())], kwargs: Vec::new() });
            Ok(())
        }
    }
    fn protocol_set_source_lookup(&mut self, state: &mut ProtocolState, mut record: ProtocolSetSource) -> PyResult<()> {
        let value = record.current.clone().unwrap();
        let hash = record.hash;
        let discard = record.name == "difference" && !record.copy_difference;
        let toggle = record.name == "symmetric_difference";
        let target = if discard || toggle { record.working.clone() } else { record.lookup.clone() };
        record.phase = if discard || toggle { 6 } else { 4 };
        state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Source(record))));
        self.protocol_collection_lookup(state, target, value, if discard { ProtocolLookupOp::Discard(false) } else if toggle { ProtocolLookupOp::Toggle } else { ProtocolLookupOp::Contains }, Some(hash))?;
        Ok(())
    }
    fn protocol_set_source_start(&mut self, state: &mut ProtocolState, mut record: ProtocolSetSource) -> PyResult<()> {
        let own = self.frozen_entries(&record.working)?;
        record.own_size = own.len();
        record.lookup = record.working.clone();
        if ["intersection", "issubset"].contains(&record.name.as_str()) {
            record.matching = self.obj_value(Object::Set(Vec::new()));
        }
        if record.name == "symmetric_difference" {
            record.phase = 7;
            let source = record.source.clone();
            state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Source(record))));
            state.plan = Some(ProtocolPlan { function: Value::Builtin("set".into()), args: vec![source], kwargs: Vec::new() });
            return Ok(());
        }
        let native = self.frozen_owner(&record.source).is_some() &&
            (record.name != "isdisjoint" || self.frozen_native(&record.source));
        if native {
            let other = self.frozen_entries(&record.source)?;
            let name = record.name.as_str();
            if name == "issubset" && own.len() > other.len() || name == "issuperset" && own.len() < other.len() {
                state.value = Some(Value::Bool(false));
                return Ok(());
            }
            if name == "difference" && !record.update {
                record.copy_difference = true;
                record.matching = self.obj_value(Object::Set(Vec::new()));
                record.lookup = record.source.clone();
                self.protocol_set_source_entries(&mut record, own);
            } else if name == "issubset" || ["intersection", "isdisjoint"].contains(&name) && own.len() < other.len() {
                record.lookup = record.source.clone();
                self.protocol_set_source_entries(&mut record, own);
            } else { self.protocol_set_source_entries(&mut record, other); }
            return self.protocol_set_source_next(state, record);
        }
        record.phase = 1;
        let source = record.source.clone();
        state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Source(record))));
        state.plan = Some(ProtocolPlan { function: Value::Builtin("iter".into()), args: vec![source], kwargs: Vec::new() });
        Ok(())
    }
    fn protocol_set_source_result(&mut self, state: &mut ProtocolState, mut record: ProtocolSetSource, value: Value) -> PyResult<()> {
        match record.phase {
            0 => return self.protocol_set_source_start(state, record),
            1 => { record.iterator = Some(value); return self.protocol_set_source_next(state, record) }
            2 => {
                if matches!(&value, Value::Builtin(name) if name == "$setbulk:end") { return self.protocol_set_source_finish(state, record) }
                record.current = Some(value.clone());
                record.phase = 3;
                state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Source(record))));
                state.plan = Some(ProtocolPlan { function: Value::Builtin("hash".into()), args: vec![value], kwargs: Vec::new() });
            }
            3 => {
                record.hash = self.as_int(&value)?.to_i128().unwrap_or(0) as i64;
                return self.protocol_set_source_lookup(state, record);
            }
            4 => {
                let found = self.truth(&value)?;
                if record.name == "isdisjoint" && found || ["issubset", "issuperset"].contains(&record.name.as_str()) && record.native && !found || record.name == "issuperset" && !found {
                    state.value = Some(Value::Bool(false));
                    return Ok(());
                }
                let add = (record.name == "intersection" || record.name == "issubset" && !record.native) && found || record.name == "difference" && record.copy_difference && !found;
                if add {
                    let target = record.matching.clone();
                    let key = record.current.clone().unwrap();
                    let hash = record.hash;
                    record.phase = 5;
                    state.actions.push_front(ProtocolAction::SetWork(Box::new(ProtocolSetWork::Source(record))));
                    self.protocol_collection_lookup(state, target, key, ProtocolLookupOp::Add, Some(hash))?;
                } else { return self.protocol_set_source_next(state, record) }
            }
            5 => {
                if !record.native && ["intersection", "issubset"].contains(&record.name.as_str()) {
                    let owner = self.frozen_owner(&record.matching).unwrap().0;
                    let current = self.frozen_owner(&record.working).unwrap().0;
                    if self.assoc_size(owner) == self.assoc_size(current) {
                        if record.name == "issubset" { state.value = Some(Value::Bool(true)); return Ok(()) }
                        return self.protocol_set_source_finish(state, record);
                    }
                }
                return self.protocol_set_source_next(state, record);
            }
            6 => return self.protocol_set_source_next(state, record),
            7 => {
                let entries = if record.update { self.frozen_entries(&value)? } else { self.frozen_entries(&record.working)? };
                if !record.update { record.working = value; }
                record.lookup = record.working.clone();
                self.protocol_set_source_entries(&mut record, entries);
                return self.protocol_set_source_next(state, record);
            }
            _ => unreachable!(),
        }
        Ok(())
    }
    fn protocol_set_work_result(&mut self, state: &mut ProtocolState, record: ProtocolSetWork, value: Value) -> PyResult<()> {
        match record {
            ProtocolSetWork::Bulk(record) => self.protocol_set_bulk_result(state, record, value),
            ProtocolSetWork::Source(record) => self.protocol_set_source_result(state, record, value),
        }
    }
}
