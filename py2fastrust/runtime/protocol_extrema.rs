// Extrema and reduce consume lazily and retain accumulators across callbacks.
#[derive(Clone, Debug)]
enum ProtocolFoldPhase { Iterator, Item, Key, Compare, Truth, Reduce }
#[derive(Clone, Debug)]
struct ProtocolFold {
    mode: String,
    source: Value,
    iterator: Option<Value>,
    function: Option<Value>,
    default: Option<Value>,
    best: Option<Value>,
    best_key: Option<Value>,
    current: Option<Value>,
    current_key: Option<Value>,
    phase: ProtocolFoldPhase,
}
impl ProtocolFold {
    fn roots(&self, roots: &mut Vec<Value>) {
        roots.push(self.source.clone());
        for values in [&self.iterator, &self.function, &self.default, &self.best,
            &self.best_key, &self.current, &self.current_key] {
            roots.extend(values.iter().cloned());
        }
    }
}
impl Runtime {
    fn protocol_fold_builtin(&mut self, state: &mut ProtocolState, plan: &ProtocolPlan) -> PyResult<bool> {
        let Value::Builtin(name) = &plan.function else { return Ok(false) };
        let (mode, source, function, default, best) = if name == "min" || name == "max" {
            if plan.args.is_empty() { return Err(pyerr("TypeError", format!("{name} expected at least 1 argument, got 0"))); }
            let mut key = None;
            let mut default = None;
            for (keyword, value) in &plan.kwargs {
                if keyword == "key" { key = (!matches!(value, Value::None)).then(|| value.clone()); }
                else if keyword == "default" { default = Some(value.clone()); }
                else { return Err(pyerr("TypeError", format!("{name}() got an unexpected keyword argument '{}'", keyword.as_str()))); }
            }
            if plan.args.len() > 1 && default.is_some() {
                return Err(pyerr("TypeError", format!("Cannot specify a default for {name}() with multiple positional arguments")));
            }
            let source = if plan.args.len() == 1 { plan.args[0].clone() }
                else { self.obj_value(Object::Tuple(plan.args.clone())) };
            (name.clone(), source, key, default, None)
        } else if name == "module:functools:reduce" {
            if plan.args.len() < 2 { return Err(pyerr("TypeError", format!("reduce expected at least 2 arguments, got {}", plan.args.len()))); }
            if plan.args.len() > 3 || (plan.args.len() == 3 && !plan.kwargs.is_empty()) {
                return Err(pyerr("TypeError", format!("reduce() takes at most 3 arguments ({} given)", plan.args.len() + plan.kwargs.len())));
            }
            let mut initial = plan.args.get(2).cloned();
            for (keyword, value) in &plan.kwargs {
                if keyword != "initial" { return Err(pyerr("TypeError", format!("reduce() got an unexpected keyword argument '{}'", keyword.as_str()))); }
                initial = Some(value.clone());
            }
            ("reduce".to_owned(), plan.args[1].clone(), Some(plan.args[0].clone()), None, initial)
        } else { return Ok(false) };
        state.actions.push_front(ProtocolAction::Fold(Box::new(ProtocolFold {
            mode, source: source.clone(), iterator: None, function, default, best,
            best_key: None, current: None, current_key: None, phase: ProtocolFoldPhase::Iterator,
        })));
        state.plan = Some(ProtocolPlan { function: Value::Builtin("iter".into()), args: vec![source], kwargs: Vec::new() });
        Ok(true)
    }
    fn protocol_fold_next(&mut self, state: &mut ProtocolState, mut record: ProtocolFold) {
        record.phase = ProtocolFoldPhase::Item;
        let iterator = record.iterator.clone().unwrap();
        state.actions.push_front(ProtocolAction::Fold(Box::new(record)));
        state.plan = Some(ProtocolPlan { function: Value::Builtin("next".into()), args: vec![iterator, Value::Builtin("$fold:end".into())], kwargs: Vec::new() });
    }
    fn protocol_fold_key(&mut self, state: &mut ProtocolState, mut record: ProtocolFold, value: Value) -> PyResult<()> {
        if record.best.is_none() {
            record.best = record.current.take();
            record.best_key = Some(value);
            self.protocol_fold_next(state, record);
        } else {
            record.current_key = Some(value.clone());
            record.phase = ProtocolFoldPhase::Compare;
            let best_key = record.best_key.clone().unwrap();
            let op = if record.mode == "min" { "<" } else { ">" };
            state.actions.push_front(ProtocolAction::Fold(Box::new(record)));
            self.protocol_compare_into(state, op.into(), value, best_key)?;
        }
        Ok(())
    }
    fn protocol_fold_result(&mut self, state: &mut ProtocolState, mut record: ProtocolFold, value: Value) -> PyResult<()> {
        match record.phase {
            ProtocolFoldPhase::Iterator => {
                record.iterator = Some(value);
                self.protocol_fold_next(state, record);
            }
            ProtocolFoldPhase::Item => {
                if matches!(&value, Value::Builtin(name) if name == "$fold:end") {
                    state.value = Some(record.best.or(record.default).ok_or_else(|| {
                        if record.mode == "reduce" { pyerr("TypeError", "reduce() of empty iterable with no initial value") }
                        else { pyerr("ValueError", format!("{}() iterable argument is empty", record.mode)) }
                    })?);
                } else if record.mode == "reduce" {
                    if let Some(best) = record.best.take() {
                        record.phase = ProtocolFoldPhase::Reduce;
                        let function = record.function.clone().unwrap();
                        state.actions.push_front(ProtocolAction::Fold(Box::new(record)));
                        state.plan = Some(ProtocolPlan { function, args: vec![best, value], kwargs: Vec::new() });
                    } else { record.best = Some(value); self.protocol_fold_next(state, record); }
                } else {
                    record.current = Some(value.clone());
                    if let Some(function) = record.function.clone() {
                        record.phase = ProtocolFoldPhase::Key;
                        state.actions.push_front(ProtocolAction::Fold(Box::new(record)));
                        state.plan = Some(ProtocolPlan { function, args: vec![value], kwargs: Vec::new() });
                    } else { self.protocol_fold_key(state, record, value)?; }
                }
            }
            ProtocolFoldPhase::Key => self.protocol_fold_key(state, record, value)?,
            ProtocolFoldPhase::Compare => {
                record.phase = ProtocolFoldPhase::Truth;
                state.actions.push_front(ProtocolAction::Fold(Box::new(record)));
                state.plan = Some(ProtocolPlan { function: Value::Builtin("bool".into()), args: vec![value], kwargs: Vec::new() });
            }
            ProtocolFoldPhase::Truth => {
                let Value::Bool(replace) = value else { return Err(pyerr("RuntimeError", "extrema comparison truth was not bool")) };
                if replace { record.best = record.current.take(); record.best_key = record.current_key.take(); }
                record.current = None;
                record.current_key = None;
                self.protocol_fold_next(state, record);
            }
            ProtocolFoldPhase::Reduce => { record.best = Some(value); self.protocol_fold_next(state, record); }
        }
        Ok(())
    }
}
