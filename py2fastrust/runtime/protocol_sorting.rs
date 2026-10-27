// Sorting owns its values and keys until completion. All Python callbacks use
// the caller's continuation queue, including source iteration and reverse truth.
#[derive(Clone, Debug)]
enum ProtocolSortPhase { Source, Options, Reverse, Key, Comparison, Truth }
#[derive(Clone, Debug)]
struct ProtocolSort {
    source: Value,
    owner: Option<usize>,
    method: bool,
    kwargs: KeywordArgs,
    key: Option<Value>,
    reverse: bool,
    phase: ProtocolSortPhase,
    values: Vec<Value>,
    keys: Vec<Value>,
    values_root: Value,
    keys_root: Value,
    order: Vec<usize>,
    scratch: Vec<usize>,
    width: usize,
    start: usize,
    left: usize,
    right: usize,
    middle: usize,
    end: usize,
    cursor: usize,
    merging: bool,
    epoch: Option<u64>,
}
impl ProtocolSort {
    fn roots(&self, roots: &mut Vec<Value>) {
        roots.push(self.source.clone());
        roots.extend(self.owner.map(Value::Obj));
        roots.extend(self.key.iter().cloned());
        // Root these arrays through private containers. Rescanning every element
        // before every comparator callback would make sorting quadratic.
        roots.extend([self.values_root.clone(), self.keys_root.clone()]);
        roots.extend(self.kwargs.iter().flat_map(|(key, value)| [key.original.clone(), value.clone()]));
    }
}
enum ProtocolSortTurn { Call(Value, Vec<Value>), Compare(Value, Value), Done }
impl Runtime {
    fn protocol_sort_note(&mut self, owner: usize) {
        if let Some((_, epoch)) = self.active_sort_lists.get_mut(&owner) {
            *epoch = epoch.wrapping_add(1);
        }
    }
    fn protocol_sort_nonempty(&mut self, owner: usize) {
        if matches!(self.heap.get(owner).and_then(Option::as_ref), Some(Object::List(values)) if !values.is_empty()) {
            self.protocol_sort_note(owner);
        }
    }
    fn protocol_sort_builtin(&mut self, state: &mut ProtocolState, plan: &ProtocolPlan) -> PyResult<bool> {
        let Value::Builtin(function) = &plan.function else { return Ok(false) };
        let method = function.strip_prefix("method:")
            .or_else(|| native_attribute_parts(&plan.function).map(|(_, _, name)| name))
            .or_else(|| function.strip_prefix("unbound:").and_then(|name| name.split_once(':').map(|(_, name)| name)));
        let (source, owner, method) = if method == Some("sort") {
            let Some(source) = plan.args.first() else { return Ok(false) };
            let payload = self.native_payload(source).unwrap_or_else(|| source.clone());
            let Value::Obj(owner) = payload else { return Ok(false) };
            if !matches!(self.heap.get(owner).and_then(Option::as_ref), Some(Object::List(_))) { return Ok(false) }
            if plan.args.len() != 1 { return Err(pyerr("TypeError", "sort() takes no positional arguments")); }
            (source.clone(), Some(owner), true)
        } else if function == "sorted" {
            if plan.args.len() != 1 { return Err(pyerr("TypeError", "sorted() takes exactly one positional argument")); }
            (plan.args[0].clone(), None, false)
        } else { return Ok(false) };
        let record = ProtocolSort {
            source: source.clone(), owner, method, kwargs: plan.kwargs.clone(),
            key: None, reverse: false,
            phase: if method { ProtocolSortPhase::Options } else { ProtocolSortPhase::Source },
            values: Vec::new(), keys: Vec::new(), values_root: Value::None, keys_root: Value::None,
            order: Vec::new(), scratch: Vec::new(),
            width: 1, start: 0, left: 0, right: 0, middle: 0, end: 0, cursor: 0,
            merging: false, epoch: None,
        };
        state.actions.push_front(ProtocolAction::Sort(Box::new(record)));
        if method { state.value = Some(Value::None); }
        else { state.plan = Some(ProtocolPlan { function: Value::Builtin("list".into()), args: vec![source], kwargs: Vec::new() }); }
        Ok(true)
    }
    fn protocol_sort_restore(&mut self, record: &mut ProtocolSort, success: bool) -> PyResult<()> {
        let Some(epoch) = record.epoch.take() else { return Ok(()) };
        let owner = record.owner.unwrap();
        let modified = self.active_sort_lists.get(&owner).is_some_and(|(_, current)| *current != epoch);
        let values = if record.order.len() == record.values.len() {
            record.order.iter().map(|index| record.values[*index].clone()).collect()
        } else { record.values.clone() };
        self.heap[owner] = Some(Object::List(values));
        if let Some((depth, _)) = self.active_sort_lists.get_mut(&owner) {
            *depth -= 1;
            if *depth == 0 { self.active_sort_lists.remove(&owner); }
        }
        if success && modified { return Err(pyerr("ValueError", "list modified during sort")); }
        Ok(())
    }
    fn protocol_sort_abandon(&mut self, state: &mut ProtocolState) {
        for action in state.actions.iter_mut() {
            if let ProtocolAction::Sort(record) = action { let _ = self.protocol_sort_restore(record, false); }
        }
    }
    fn protocol_discard_actions(&mut self, state: &mut ProtocolState, count: usize) -> Vec<ProtocolAction> {
        let mut removed = state.actions.drain(..count).collect::<Vec<_>>();
        for action in &mut removed {
            if let ProtocolAction::Mro(record)=action {self.protocol_mro_discard(record);}
            if let ProtocolAction::Sort(record) = action { let _ = self.protocol_sort_restore(record, false); }
        }
        removed
    }
    fn protocol_sort_advance(&mut self, record: &mut ProtocolSort) -> ProtocolSortTurn {
        let size = record.order.len();
        while record.width < size {
            if record.start >= size {
                std::mem::swap(&mut record.order, &mut record.scratch);
                record.width = record.width.saturating_mul(2);
                record.start = 0;
                record.merging = false;
                continue;
            }
            if !record.merging {
                record.middle = record.start.saturating_add(record.width).min(size);
                record.end = record.middle.saturating_add(record.width).min(size);
                record.left = record.start;
                record.right = record.middle;
                record.cursor = record.start;
                record.merging = true;
            }
            if record.left < record.middle && record.right < record.end {
                let left = record.keys[record.order[record.left]].clone();
                let right = record.keys[record.order[record.right]].clone();
                record.phase = ProtocolSortPhase::Comparison;
                // Reverse changes the argument order of __lt__, preserving ties.
                return if record.reverse { ProtocolSortTurn::Compare(left, right) }
                    else { ProtocolSortTurn::Compare(right, left) };
            }
            while record.left < record.middle {
                record.scratch[record.cursor] = record.order[record.left];
                record.cursor += 1;
                record.left += 1;
            }
            while record.right < record.end {
                record.scratch[record.cursor] = record.order[record.right];
                record.cursor += 1;
                record.right += 1;
            }
            record.start = record.end;
            record.merging = false;
        }
        ProtocolSortTurn::Done
    }
    fn protocol_sort_step(&mut self, record: &mut ProtocolSort, value: Value) -> PyResult<ProtocolSortTurn> {
        match record.phase {
            ProtocolSortPhase::Source => {
                let Value::Obj(owner) = value else { return Err(pyerr("RuntimeError", "sorted source was not materialized")) };
                if !matches!(self.heap.get(owner).and_then(Option::as_ref), Some(Object::List(_))) {
                    return Err(pyerr("RuntimeError", "sorted source was not a list"));
                }
                record.owner = Some(owner);
                record.phase = ProtocolSortPhase::Options;
                self.protocol_sort_step(record, Value::None)
            }
            ProtocolSortPhase::Options => {
                let mut reverse = Value::Bool(false);
                for (name, value) in &record.kwargs {
                    if name == "key" { record.key = (!matches!(value, Value::None)).then(|| value.clone()); }
                    else if name == "reverse" { reverse = value.clone(); }
                    else { return Err(pyerr("TypeError", format!("sort() got an unexpected keyword argument '{}'", name.as_str()))); }
                }
                record.kwargs.clear();
                record.phase = ProtocolSortPhase::Reverse;
                Ok(ProtocolSortTurn::Call(Value::Builtin("bool".into()), vec![reverse]))
            }
            ProtocolSortPhase::Reverse => {
                let Value::Bool(reverse) = value else { return Err(pyerr("RuntimeError", "sort reverse truth was not bool")) };
                record.reverse = reverse;
                let owner = record.owner.unwrap();
                let Some(Object::List(values)) = self.heap[owner].as_mut() else { return Err(pyerr("RuntimeError", "sort lost its list")) };
                record.values = std::mem::take(values);
                record.values_root = self.obj_value(Object::Tuple(record.values.clone()));
                if record.key.is_some() { record.keys_root = self.obj_value(Object::List(Vec::new())); }
                let (depth, epoch) = self.active_sort_lists.entry(owner).or_insert((0, 0));
                *depth += 1;
                record.epoch = Some(*epoch);
                record.order = (0..record.values.len()).collect();
                record.scratch = record.order.clone();
                if let Some(key) = &record.key {
                    if let Some(value) = record.values.first() {
                        record.phase = ProtocolSortPhase::Key;
                        return Ok(ProtocolSortTurn::Call(key.clone(), vec![value.clone()]));
                    }
                } else { record.keys = record.values.clone(); }
                Ok(self.protocol_sort_advance(record))
            }
            ProtocolSortPhase::Key => {
                if let Value::Obj(owner) = record.keys_root {
                    let Some(Object::List(values)) = self.heap[owner].as_mut() else { unreachable!() };
                    values.push(value.clone());
                }
                record.keys.push(value);
                if record.keys.len() < record.values.len() {
                    return Ok(ProtocolSortTurn::Call(record.key.clone().unwrap(), vec![record.values[record.keys.len()].clone()]));
                }
                Ok(self.protocol_sort_advance(record))
            }
            ProtocolSortPhase::Comparison => {
                record.phase = ProtocolSortPhase::Truth;
                Ok(ProtocolSortTurn::Call(Value::Builtin("bool".into()), vec![value]))
            }
            ProtocolSortPhase::Truth => {
                let Value::Bool(take_right) = value else { return Err(pyerr("RuntimeError", "sort comparison truth was not bool")) };
                let index = if take_right { let index = record.right; record.right += 1; index }
                    else { let index = record.left; record.left += 1; index };
                record.scratch[record.cursor] = record.order[index];
                record.cursor += 1;
                Ok(self.protocol_sort_advance(record))
            }
        }
    }
    fn protocol_sort_result(&mut self, state: &mut ProtocolState, mut record: ProtocolSort, value: Value) -> PyResult<()> {
        let turn = match self.protocol_sort_step(&mut record, value) {
            Ok(turn) => turn,
            Err(error) => { self.protocol_sort_restore(&mut record, false)?; return Err(error); }
        };
        match turn {
            ProtocolSortTurn::Done => {
                self.protocol_sort_restore(&mut record, true)?;
                state.value = Some(if record.method { Value::None } else { Value::Obj(record.owner.unwrap()) });
            }
            ProtocolSortTurn::Call(function, args) => {
                state.actions.push_front(ProtocolAction::Sort(Box::new(record)));
                state.plan = Some(ProtocolPlan { function, args, kwargs: Vec::new() });
            }
            ProtocolSortTurn::Compare(left, right) => {
                state.actions.push_front(ProtocolAction::Sort(Box::new(record)));
                self.protocol_compare_into(state, "<".into(), left, right)?;
            }
        }
        Ok(())
    }
}
