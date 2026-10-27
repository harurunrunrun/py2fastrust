// A cell delegates rich comparison directly to its contents. The result may be
// an arbitrary Python value; truth conversion belongs to the eventual caller.
#[derive(Clone, Debug)]
struct ProtocolCellComparison {
    op: String,
    left: usize,
    right: usize,
    pending: bool,
    cycle_candidate: bool,
}
impl ProtocolCellComparison {
    fn roots(&self, roots: &mut Vec<Value>) {
        roots.extend([Value::Obj(self.left), Value::Obj(self.right)]);
    }
}
impl Runtime {
    fn protocol_cell_compare(&mut self, state: &mut ProtocolState, op: &str, left: &Value, right: &Value) -> PyResult<bool> {
        let (Value::Obj(left), Value::Obj(right)) = (left, right) else { return Ok(false) };
        if !matches!(self.heap.get(*left).and_then(Option::as_ref), Some(Object::Cell(_))) ||
            !matches!(self.heap.get(*right).and_then(Option::as_ref), Some(Object::Cell(_))) {
            return Ok(false);
        }
        if state.actions.iter().any(|action| matches!(action, ProtocolAction::Cell(record) if record.cycle_candidate && record.left == *left && record.right == *right && record.op == op)) {
            return Err(pyerr("RecursionError", "maximum recursion depth exceeded in cell comparison"));
        }
        state.actions.push_front(ProtocolAction::Cell(Box::new(ProtocolCellComparison {
            op: op.into(), left: *left, right: *right, pending: false, cycle_candidate: true,
        })));
        state.value = Some(Value::None);
        Ok(true)
    }
    fn protocol_cell_result(&mut self, state: &mut ProtocolState, mut record: ProtocolCellComparison, value: Value) -> PyResult<()> {
        if record.pending {
            state.value = Some(value);
            return Ok(());
        }
        let (Object::Cell(left), Object::Cell(right)) = (self.object(record.left)?, self.object(record.right)?) else {
            return Err(pyerr("RuntimeError", "cell comparison lost its owner"));
        };
        if let (Some(left), Some(right)) = (&left, &right) {
            let op = record.op.clone();
            record.pending = true;
            state.actions.push_front(ProtocolAction::Cell(Box::new(record)));
            if self.protocol_sequence_comparison_callback(&op, left, right) {
                self.protocol_sequence_callback_boundary(state);
            }
            self.protocol_compare_into(state, op, left.clone(), right.clone())?;
        } else {
            let ordering = left.is_some().cmp(&right.is_some());
            state.value = Some(Value::Bool(match record.op.as_str() {
                "==" => ordering.is_eq(), "!=" => !ordering.is_eq(),
                "<" => ordering.is_lt(), "<=" => !ordering.is_gt(),
                ">" => ordering.is_gt(), _ => !ordering.is_lt(),
            }));
        }
        Ok(())
    }
}
