// Slot lookup distinguishes Python overrides from native definitions. Proof
// predicates only receive a Python value, and stop at an earlier native owner.
#[derive(Clone, Debug)]
enum SlotDefinition {
    Python(Value),
    Native(Value),
}
impl Runtime {
    fn slot_definition(&self, class: &Value, name: &str, depth: usize) -> Option<SlotDefinition> {
        for base in self.class_mro(class, depth)? {
            if let Some(value) = self.class_own_attribute(&base, name) {
                return Some(if matches!(base, Value::Obj(_)) {
                    SlotDefinition::Python(value)
                } else {
                    SlotDefinition::Native(value)
                });
            }
        }
        None
    }
    fn slot_override(&self, class: &Value, name: &str, depth: usize) -> Option<Value> {
        match self.slot_definition(class, name, depth)? {
            SlotDefinition::Python(value) => Some(value),
            SlotDefinition::Native(_) => None,
        }
    }
    fn list_collect(&mut self, value: Value) -> PyResult<Vec<Value>> {
        let iterator = self.iter(value.clone())?;
        self.view_rooted(vec![value.clone(), iterator.clone()], |runtime, root| {
            // list() asks the original iterable for its length hint only after
            // obtaining the iterator; this is observable in Python overrides.
            runtime.assoc_length_hint(vec![value], Vec::new())?;
            let mut out = Vec::new();
            while let Some(value) = runtime.next(iterator.clone())? {
                runtime.roots[root].push(value.clone());
                out.push(value);
            }
            Ok(out)
        })
    }
    fn protocol_length(&mut self, value: &Value) -> PyResult<usize> {
        let number = self.as_int(value)?;
        if number.is_negative() {
            return Err(pyerr("ValueError", "__len__() should return >= 0"));
        }
        number
            .to_usize()
            .filter(|value| *value <= isize::MAX as usize)
            .ok_or_else(|| {
                pyerr(
                    "OverflowError",
                    "cannot fit length into an index-sized integer",
                )
            })
    }
    fn implicit_native_call(
        &mut self,
        name: &str,
        args: Vec<Value>,
        kwargs: KeywordArgs,
    ) -> PyResult<Value> {
        let receiver = args
            .first()
            .cloned()
            .ok_or_else(|| pyerr("TypeError", "missing native slot receiver"))?;
        let payload = self
            .native_payload(&receiver)
            .unwrap_or_else(|| receiver.clone());
        match name {
            "__str__" if args.len() == 1 && kwargs.is_empty() => {
                self.str_value(&payload).map(|text| Value::Str(text.into()))
            }
            "__bool__" if args.len() == 1 && kwargs.is_empty() => {
                self.truth(&payload).map(Value::Bool)
            }
            "__contains__" if args.len() == 2 && kwargs.is_empty() => {
                let needle = args[1].clone();
                if let Value::Str(haystack) = &payload {
                    let value = self.native_payload(&needle).unwrap_or(needle);
                    return if let Value::Str(needle) = value {
                        Ok(Value::Bool(haystack.contains(needle.as_str())))
                    } else {
                        Err(pyerr(
                            "TypeError",
                            "'in <string>' requires a string as left operand",
                        ))
                    };
                }
                if self.frozen_owner(&payload).is_some() {
                    return self.frozen_contains(&payload, needle).map(Value::Bool);
                }
                if matches!(&payload,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::List(_)|Object::Tuple(_))))
                {
                    return self.view_rooted(vec![receiver, needle.clone()], |runtime, root| {
                        let iterator = runtime.iter(payload)?;
                        runtime.roots[root].push(iterator.clone());
                        while let Some(value) = runtime.next(iterator.clone())? {
                            runtime.roots[root].push(value.clone());
                            let found = runtime.identical_or_equal(&value, &needle)?;
                            runtime.roots[root].pop();
                            if found {
                                return Ok(Value::Bool(true));
                            }
                        }
                        Ok(Value::Bool(false))
                    });
                }
                self.compare_default("in", &needle, &payload)
                    .map(Value::Bool)
            }
            "__reversed__" if args.len() == 1 && kwargs.is_empty() => {
                let result = self.builtin("reversed", vec![payload], Vec::new(), None)?;
                Ok(self.collection_keep(result, receiver))
            }
            _ => Err(pyerr("TypeError", "invalid native slot arguments")),
        }
    }
}
