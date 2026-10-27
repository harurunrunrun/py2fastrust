// Operand dispatch preserves native acceptance before trying unrelated Python
// reflected methods. Slot values remain separate from payload proof predicates.
fn operand_method(op: &str) -> Option<&'static str> {
    Some(match op {
        "+" => "add",
        "-" => "sub",
        "*" => "mul",
        "/" => "truediv",
        "//" => "floordiv",
        "divmod" => "divmod",
        "%" => "mod",
        "**" => "pow",
        "<<" => "lshift",
        ">>" => "rshift",
        "&" => "and",
        "|" => "or",
        "^" => "xor",
        "@" => "matmul",
        _ => return None,
    })
}
fn operand_descriptor(value: &Value) -> Option<(&str, &str)> {
    if let Some((_, owner, name)) = native_attribute_parts(value) {
        return Some((owner, name));
    }
    let Value::Builtin(value) = value else {
        return None;
    };
    let value = value.strip_prefix("operand_native:")?;
    value.split_once(':')
}
impl SlotDefinition {
    fn value(&self) -> &Value {
        match self {
            Self::Python(value) | Self::Native(value) => value,
        }
    }
}
impl Runtime {
    fn operand_attribute(
        &mut self,
        descriptor: &Value,
        receiver: &Value,
        args: &[Value],
        kwargs: &KeywordArgs,
    ) -> Option<PyResult<Value>> {
        let (owner, name) = operand_descriptor(descriptor)?;
        let comparison =
            ["__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"].contains(&name);
        let stem = name
            .strip_prefix("__")
            .and_then(|name| name.strip_suffix("__"))?;
        let ordinary = [
            "add", "sub", "mul", "truediv", "floordiv", "divmod", "mod", "pow", "lshift", "rshift", "and",
            "or", "xor", "matmul",
        ];
        let binary = ordinary.contains(&stem)
            || stem
                .strip_prefix('r')
                .is_some_and(|stem| ordinary.contains(&stem));
        let inplace = stem
            .strip_prefix('i')
            .is_some_and(|stem| ordinary.contains(&stem));
        if !comparison && !binary && !inplace {
            return None;
        }
        Some((|| {
            if args.len() != 1 || !kwargs.is_empty() {
                return Err(pyerr("TypeError", "operator descriptor takes one argument"));
            }
            let slot = SlotDefinition::Native(descriptor.clone());
            let result = if comparison {
                self.operand_compare_slot(&slot, receiver, &args[0])
            } else if inplace {
                self.operand_inplace(&slot, receiver, &args[0])
            } else {
                self.operand_native_binary(owner, name, receiver, &args[0])
            }?;
            if let Some(value) = result {
                return Ok(value);
            }
            if ["list", "tuple", "str", "bytes", "bytearray"].contains(&owner) && name == "__add__" {
                return Err(pyerr(
                    "TypeError",
                    "can only concatenate matching sequences",
                ));
            }
            if ["list", "tuple", "str", "bytes", "bytearray"].contains(&owner) && ["__mul__", "__rmul__"].contains(&name)
            {
                let count = self.as_int(&args[0])?;
                let payload = self
                    .native_payload(receiver)
                    .unwrap_or_else(|| receiver.clone());
                return self.binary_default("*", payload, Value::Int(count.into()));
            }
            Ok(Value::Builtin("NotImplemented".into()))
        })())
    }
    fn operand_class(&self, value: &Value) -> Value {
        self.object_class(value)
            .unwrap_or_else(|| Value::Builtin(self.typename(value)))
    }
    fn operand_slot(&self, value: &Value, name: &str) -> Option<SlotDefinition> {
        // Float/bytes have no subclass payload layout here, but their primitive
        // slots must still precede an unrelated Python right operand.
        let owner = match value {
            Value::Float(_) => Some("float"),
            Value::Bytes(_) => Some("bytes"),
            _ => None,
        };
        if let Some(owner) = owner {
            let comparison =
                ["__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"].contains(&name);
            let arithmetic = owner == "float"
                && [
                    "__add__",
                    "__radd__",
                    "__sub__",
                    "__rsub__",
                    "__mul__",
                    "__rmul__",
                    "__truediv__",
                    "__rtruediv__",
                    "__floordiv__",
                    "__rfloordiv__",
                    "__mod__",
                    "__rmod__",
                    "__pow__",
                    "__rpow__",
                ]
                .contains(&name);
            if comparison || arithmetic {
                return Some(SlotDefinition::Native(Value::Builtin(format!(
                    "operand_native:{owner}:{name}"
                ))));
            }
        }
        self.slot_definition(&self.operand_class(value), name, 0)
    }
    fn operand_kind(&self, value: &Value) -> &'static str {
        match value {
            Value::Int(_) | Value::Bool(_) => "int",
            Value::Float(_) => "float",
            Value::Complex(_) => "complex",
            Value::Str(_) => "str",
            Value::Bytes(_) => "bytes",
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::ByteArray(_)) => "bytearray",
            Some(Object::MemoryView(_)) => "memoryview",
            Some(Object::List(_)) => "list",
                Some(Object::Tuple(_)) => "tuple",
                Some(Object::Dict(_)) => "dict",
                Some(Object::Set(_)) => "set",
                Some(Object::FrozenSet { .. }) => "frozenset",
                _ => "object",
            },
            _ => "object",
        }
    }
    fn operand_same_slot(left: Option<&SlotDefinition>, right: Option<&SlotDefinition>) -> bool {
        match (left, right) {
            (Some(left), Some(right)) => left.value().same_identity(right.value()),
            (None, None) => true,
            _ => false,
        }
    }
    fn operand_python_call(
        &mut self,
        slot: Value,
        receiver: Value,
        argument: Value,
    ) -> PyResult<Option<Value>> {
        let class = self.operand_class(&receiver);
        let callable = match self.bind_descriptor(slot, Some(receiver), class) {
            Ok(value) => value,
            Err(error) if self.exception_has_native_class(&error, "AttributeError") => {
                return Ok(None)
            }
            Err(error) => return Err(error),
        };
        let result = self.call(callable, vec![argument], Vec::new(), None)?;
        Ok(
            if matches!(&result,Value::Builtin(name)if name=="NotImplemented") {
                None
            } else {
                Some(result)
            },
        )
    }
    fn operand_compare_slot(
        &mut self,
        slot: &SlotDefinition,
        receiver: &Value,
        argument: &Value,
    ) -> PyResult<Option<Value>> {
        self.operand_compare_slot_depth(slot, receiver, argument, 0)
    }
    fn operand_compare_slot_depth(
        &mut self,
        slot: &SlotDefinition,
        receiver: &Value,
        argument: &Value,
        depth: usize,
    ) -> PyResult<Option<Value>> {
        if depth.saturating_add(self.recursion) >= self.recursion_limit {
            return Err(pyerr(
                "RecursionError",
                "maximum recursion depth exceeded in comparison",
            ));
        }
        let Some((owner, name)) = operand_descriptor(slot.value()) else {
            return self.operand_python_call(
                slot.value().clone(),
                receiver.clone(),
                argument.clone(),
            );
        };
        let op = match name {
            "__eq__" => "==",
            "__ne__" => "!=",
            "__lt__" => "<",
            "__le__" => "<=",
            "__gt__" => ">",
            "__ge__" => ">=",
            _ => return Ok(None),
        };
        if ["bytearray","memoryview"].contains(&owner){return self.buffer_compare_native(owner,op,receiver,argument);}
        if owner == "object" {
            if op == "==" {
                return Ok(receiver
                    .same_identity(argument)
                    .then_some(Value::Bool(true)));
            }
            if op == "!=" {
                if let Some(eq) = self.operand_slot(receiver, "__eq__") {
                    if let Some(result) =
                        self.operand_compare_slot_depth(&eq, receiver, argument, depth + 1)?
                    {
                        return Ok(Some(Value::Bool(!self.truth(&result)?)));
                    }
                }
            }
            return Ok(None);
        }
        let left = self
            .native_payload(receiver)
            .unwrap_or_else(|| receiver.clone());
        let right = self
            .native_payload(argument)
            .unwrap_or_else(|| argument.clone());
        let lk = self.operand_kind(&left);
        let rk = self.operand_kind(&right);
        let equal = op == "==" || op == "!=";
        let accepted = match owner {
            "int" => lk == "int" && rk == "int",
            "float" => ["int", "float"].contains(&lk) && ["int", "float"].contains(&rk),
            "complex" => equal && ["int", "float", "complex"].contains(&rk),
            "str" | "bytes" | "list" | "tuple" => lk == owner && rk == owner,
            "dict" => equal && rk == "dict",
            "set" | "frozenset" => ["set", "frozenset"].contains(&rk),
            _ => false,
        };
        if !accepted {
            return Ok(None);
        }
        if owner == "list" || owner == "tuple" {
            return self.operand_sequence_compare(op, &left, &right).map(Some);
        }
        self.compare_default(op, &left, &right)
            .map(|value| Some(Value::Bool(value)))
    }
    fn operand_sequence_compare(
        &mut self,
        op: &str,
        left: &Value,
        right: &Value,
    ) -> PyResult<Value> {
        let (Value::Obj(left), Value::Obj(right)) = (left, right) else {
            return Err(pyerr("TypeError", "expected native sequences"));
        };
        let (left, right) = (*left, *right);
        self.view_rooted(
            vec![Value::Obj(left), Value::Obj(right)],
            |runtime, root| {
                let lengths = |runtime: &Runtime| -> (usize, usize) {
                    let size = |index: usize| match runtime.heap.get(index).and_then(Option::as_ref)
                    {
                        Some(Object::List(values) | Object::Tuple(values)) => values.len(),
                        _ => 0,
                    };
                    (size(left), size(right))
                };
                let (a, b) = lengths(runtime);
                let list = matches!(
                    runtime.heap.get(left).and_then(Option::as_ref),
                    Some(Object::List(_))
                );
                if list && (op == "==" || op == "!=") && a != b {
                    return Ok(Value::Bool(op == "!="));
                }
                let mut index = 0;
                loop {
                    let item = |runtime: &Runtime, owner: usize| match runtime
                        .heap
                        .get(owner)
                        .and_then(Option::as_ref)
                    {
                        Some(Object::List(values) | Object::Tuple(values)) => {
                            values.get(index).cloned()
                        }
                        _ => None,
                    };
                    let (Some(a), Some(b)) = (item(runtime, left), item(runtime, right)) else {
                        break;
                    };
                    runtime.roots[root].extend([a.clone(), b.clone()]);
                    let equal = runtime.identical_or_equal(&a, &b)?;
                    if !equal {
                        let result = match op {
                            "==" => Ok(Value::Bool(false)),
                            "!=" => Ok(Value::Bool(true)),
                            _ => runtime.compare_value(op, &a, &b),
                        };
                        runtime.roots[root].truncate(2);
                        return result;
                    }
                    runtime.roots[root].truncate(2);
                    index += 1;
                }
                let (a, b) = lengths(runtime);
                Ok(Value::Bool(match op {
                    "==" => a == b,
                    "!=" => a != b,
                    "<" => a < b,
                    "<=" => a <= b,
                    ">" => a > b,
                    _ => a >= b,
                }))
            },
        )
    }
    fn operand_rich_comparison(
        &mut self,
        op: &str,
        left: &Value,
        right: &Value,
    ) -> PyResult<Option<Value>> {
        let (forward, reflected) = match op {
            "==" => ("__eq__", "__eq__"),
            "!=" => ("__ne__", "__ne__"),
            "<" => ("__lt__", "__gt__"),
            "<=" => ("__le__", "__ge__"),
            ">" => ("__gt__", "__lt__"),
            ">=" => ("__ge__", "__le__"),
            _ => return Ok(None),
        };
        if self.object_class(left).is_none() && self.object_class(right).is_none() {
            return Ok(None);
        }
        let lc = self.operand_class(left);
        let rc = self.operand_class(right);
        let reverse = !Self::same_type(&lc, &rc) && self.is_subclass(&rc, &lc)?;
        self.view_rooted(vec![left.clone(), right.clone()], |runtime, _| {
            let mut pairs = vec![(left, right, forward), (right, left, reflected)];
            if reverse {
                pairs.reverse();
            }
            for (receiver, argument, name) in pairs {
                if let Some(slot) = runtime.operand_slot(receiver, name) {
                    if let Some(value) = runtime.operand_compare_slot(&slot, receiver, argument)? {
                        return Ok(Some(value));
                    }
                }
            }
            if op == "==" || op == "!=" {
                let same = left.same_identity(right);
                Ok(Some(Value::Bool(if op == "==" { same } else { !same })))
            } else {
                Err(pyerr(
                    "TypeError",
                    format!(
                        "'{op}' not supported between instances of '{}' and '{}'",
                        runtime.typename(left),
                        runtime.typename(right)
                    ),
                ))
            }
        })
    }
    fn operand_native_binary(
        &mut self,
        owner: &str,
        name: &str,
        receiver: &Value,
        argument: &Value,
    ) -> PyResult<Option<Value>> {
        let Some(stem) = name
            .strip_prefix("__")
            .and_then(|name| name.strip_suffix("__"))
        else {
            return Ok(None);
        };
        let ordinary = [
            "add", "sub", "mul", "truediv", "floordiv", "divmod", "mod", "pow", "lshift", "rshift", "and",
            "or", "xor",
        ];
        let (reflected, stem) = if ordinary.contains(&stem) {
            (false, stem)
        } else if let Some(stem) = stem.strip_prefix('r') {
            (true, stem)
        } else {
            return Ok(None);
        };
        let op = match stem {
            "add" => "+",
            "sub" => "-",
            "mul" => "*",
            "truediv" => "/",
            "floordiv" => "//",
            "divmod" => "divmod",
            "mod" => "%",
            "pow" => "**",
            "lshift" => "<<",
            "rshift" => ">>",
            "and" => "&",
            "or" => "|",
            "xor" => "^",
            _ => return Ok(None),
        };
        if ["str","bytes","bytearray"].contains(&owner) && op == "%" {
            let format = if reflected { argument } else { receiver };
            let value = if reflected { receiver } else { argument };
            let format = self
                .native_payload(format)
                .unwrap_or_else(|| format.clone());
            if !(match owner {"str"=>matches!(&format,Value::Str(_)),"bytes"=>matches!(&format,Value::Bytes(_)),_=>self.buffer_kind(&format)==Some("bytearray")}) {
                return Ok(None);
            }
            let payload = self.native_payload(value);
            let value = if matches!(&payload,Some(Value::Obj(index))if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Tuple(_))))
            {
                payload.unwrap()
            } else {
                value.clone()
            };
            return self.binary_default(op, format, value).map(Some);
        }
        let receiver = self
            .native_payload(receiver)
            .unwrap_or_else(|| receiver.clone());
        let arg = self
            .native_payload(argument)
            .unwrap_or_else(|| argument.clone());
        let kind = self.operand_kind(&arg);
        let accepted = match owner {
            "int" | "bool" => kind == "int",
            "float" => ["int", "float"].contains(&kind),
            "complex" => {
                ["int", "float", "complex"].contains(&kind)
                    && ["+", "-", "*", "/", "**"].contains(&op)
            }
            "str" | "bytes" => {
                if op == "%" {
                    true
                } else if op == "+" {
                    kind == owner
                } else {
                    op == "*" && kind == "int"
                }
            }
            "bytearray"=>op=="+"||(op=="*"&&kind=="int"),
            "list" | "tuple" => {
                if op == "+" {
                    kind == owner
                } else {
                    op == "*" && kind == "int"
                }
            }
            "dict" => op == "|" && kind == "dict",
            "set" | "frozenset" => {
                ["|", "&", "-", "^"].contains(&op) && ["set", "frozenset"].contains(&kind)
            }
            _ => false,
        };
        if !accepted {
            return Ok(None);
        }
        let (mut left, mut right) = if reflected {
            (arg, receiver)
        } else {
            (receiver, arg)
        };
        // int's descriptors return integers even with two bool arguments.
        // bool owns distinct bitwise slots which preserve bool/bool results.
        if owner == "int" && ["&", "|", "^"].contains(&op) {
            if let Value::Bool(value)=left {left=Value::Int(Int::from_i128(value as i128).into());}
            if let Value::Bool(value)=right {right=Value::Int(Int::from_i128(value as i128).into());}
        }
        if op=="divmod" {
            if let Some(result)=self.float_divmod_values(&left,&right){return result.map(Some);}
            let quotient=self.binary_default("//",left.clone(),right.clone())?;
            let remainder=self.binary_default("%",left,right)?;
            return Ok(Some(self.obj_value(Object::Tuple(vec![quotient,remainder]))));
        }
        self.binary_default(op, left, right).map(Some)
    }
    fn operand_binary_slot(
        &mut self,
        slot: &SlotDefinition,
        receiver: &Value,
        argument: &Value,
    ) -> PyResult<Option<Value>> {
        if let Some((owner, name)) = operand_descriptor(slot.value()) {
            self.operand_native_binary(owner, name, receiver, argument)
        } else {
            self.operand_python_call(slot.value().clone(), receiver.clone(), argument.clone())
        }
    }
    fn operand_sequence_fallback(slot: Option<&SlotDefinition>) -> bool {
        slot.and_then(|slot| operand_descriptor(slot.value()))
            .is_some_and(|(owner, name)| {
                ["str", "bytes", "bytearray", "list", "tuple"].contains(&owner)
                    && ["__add__", "__mul__", "__rmul__"].contains(&name)
            })
    }
    fn operand_inplace(
        &mut self,
        slot: &SlotDefinition,
        receiver: &Value,
        argument: &Value,
    ) -> PyResult<Option<Value>> {
        let Some((owner, name)) = operand_descriptor(slot.value()) else {
            return self.operand_python_call(
                slot.value().clone(),
                receiver.clone(),
                argument.clone(),
            );
        };
        let payload = self
            .native_payload(receiver)
            .unwrap_or_else(|| receiver.clone());
        match (owner, name) {
            ("bytearray","__iadd__"|"__imul__")=>{
                self.buffer_binary(if name=="__iadd__"{"+="}else{"*="},payload,argument.clone()).unwrap()?;
                Ok(Some(receiver.clone()))
            },
            ("list", "__iadd__") => {
                let Value::Obj(index) = payload else {
                    return Ok(None);
                };
                let other = self
                    .native_payload(argument)
                    .unwrap_or_else(|| argument.clone());
                if matches!(&other,Value::Obj(other)if *other==index) {
                    let Object::List(values) = self.object(index)? else {
                        return Ok(None);
                    };
                    if let Some(Object::List(target)) = self.heap[index].as_mut() {
                        target.extend(values);
                    }
                } else {
                    let iterator = self.iter(argument.clone())?;
                    self.view_rooted(
                        vec![receiver.clone(), argument.clone(), iterator.clone()],
                        |runtime, _| {
                            runtime.assoc_length_hint(vec![argument.clone()], Vec::new())?;
                            while let Some(value) = runtime.next(iterator.clone())? {
                                if let Some(Object::List(target)) = runtime.heap[index].as_mut() {
                                    target.push(value);
                                }
                            }
                            Ok(())
                        },
                    )?;
                }
                Ok(Some(receiver.clone()))
            }
            ("list", "__imul__") => {
                let count = self.as_int(argument)?;
                self.binary_default("*=", payload, Value::Int(count.into()))?;
                Ok(Some(receiver.clone()))
            }
            ("dict", "__ior__") => {
                self.method("update", payload, vec![argument.clone()], Vec::new())?;
                Ok(Some(receiver.clone()))
            }
            ("set", name) if ["__ior__", "__iand__", "__isub__", "__ixor__"].contains(&name) => {
                let other = self
                    .native_payload(argument)
                    .unwrap_or_else(|| argument.clone());
                if !self.frozen_native(&other) {
                    return Ok(None);
                }
                let op = match name {
                    "__ior__" => "|=",
                    "__iand__" => "&=",
                    "__isub__" => "-=",
                    _ => "^=",
                };
                self.binary_default(op, payload, other)?;
                Ok(Some(receiver.clone()))
            }
            _ => Ok(None),
        }
    }
    fn operand_binary(&mut self, op: &str, left: &Value, right: &Value) -> Option<PyResult<Value>> {
        let base = op.strip_suffix('=').unwrap_or(op);
        let stem = operand_method(base)?;
        if self.object_class(left).is_none() && self.object_class(right).is_none() {
            return None;
        }
        let result = self.view_rooted(vec![left.clone(), right.clone()], |runtime, _| {
            if op.ends_with('=') {
                if let Some(slot) = runtime.operand_slot(left, &format!("__i{stem}__")) {
                    if let Some(value) = runtime.operand_inplace(&slot, left, right)? {
                        return Ok(value);
                    }
                }
            }
            let reflected = runtime.operand_slot(right, &format!("__r{stem}__"));
            let same = Self::same_type(&runtime.operand_class(left), &runtime.operand_class(right));
            let right_first = !same
                && runtime
                    .is_subclass(&runtime.operand_class(right), &runtime.operand_class(left))?
                && !Self::operand_same_slot(
                    reflected.as_ref(),
                    runtime.operand_slot(left, &format!("__r{stem}__")).as_ref(),
                );
            if right_first {
                if let Some(slot) = &reflected {
                    if let Some(value) = runtime.operand_binary_slot(slot, right, left)? {
                        return Ok(value);
                    }
                }
            }
            let forward = runtime.operand_slot(left, &format!("__{stem}__"));
            let sequence = Self::operand_sequence_fallback(forward.as_ref());
            if !sequence {
                if let Some(slot) = &forward {
                    if let Some(value) = runtime.operand_binary_slot(slot, left, right)? {
                        return Ok(value);
                    }
                }
            }
            if !same && !right_first {
                if reflected.is_some() {
                    if let Some(slot) = runtime.operand_slot(right, &format!("__r{stem}__")) {
                        if let Some(value) = runtime.operand_binary_slot(&slot, right, left)? {
                            return Ok(value);
                        }
                    }
                }
            }
            if sequence {
                if let Some(slot) = runtime.operand_slot(left, &format!("__{stem}__")) {
                    if let Some(value) = runtime.operand_binary_slot(&slot, left, right)? {
                        return Ok(value);
                    }
                }
            }
            // Sequence repeat accepts the index protocol after reflected
            // numeric slots have declined, without coercing arbitrary numbers.
            let lp = runtime.native_payload(left).unwrap_or_else(|| left.clone());
            let rp = runtime
                .native_payload(right)
                .unwrap_or_else(|| right.clone());
            if base == "*" {
                if ["str", "bytes", "bytearray", "list", "tuple"].contains(&runtime.operand_kind(&lp))
                    && Self::operand_sequence_fallback(
                        runtime.operand_slot(left, "__mul__").as_ref(),
                    )
                {
                    let count = runtime.as_int(right)?;
                    return runtime.binary_default(base, lp, Value::Int(count.into()));
                }
                if ["str", "bytes", "bytearray", "list", "tuple"].contains(&runtime.operand_kind(&rp))
                    && Self::operand_sequence_fallback(
                        runtime.operand_slot(right, "__rmul__").as_ref(),
                    )
                {
                    let count = runtime.as_int(left)?;
                    return runtime.binary_default(base, rp, Value::Int(count.into()));
                }
            }
            Err(pyerr(
                "TypeError",
                format!(
                    "unsupported operand type(s) for {op}: '{}' and '{}'",
                    runtime.typename(left),
                    runtime.typename(right)
                ),
            ))
        });
        Some(result)
    }
}
