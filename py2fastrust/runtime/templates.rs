// PEP 750 template objects. Static text is normalized without invoking user
// formatting/conversion hooks; interpolation values remain ordinary objects.
fn template_type_name(name: &str) -> bool {
    matches!(
        name,
        "string.templatelib.Template" | "string.templatelib.Interpolation"
    )
}
impl Runtime {
    fn is_template_value(&self, value: &Value) -> bool {
        match value {
            Value::Builtin(name) => template_type_name(name),
            Value::Obj(index) => matches!(
                self.heap.get(*index).and_then(Option::as_ref),
                Some(
                    Object::Template { .. }
                        | Object::Interpolation { .. }
                        | Object::Iterator(IteratorState::Template(..))
                )
            ),
            _ => false,
        }
    }
    fn template_raw_str<'a>(&'a self, value: &'a Value) -> Option<&'a str> {
        match value {
            Value::Str(text) => Some(text.as_ref()),
            Value::Obj(index) => match self.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::BuiltinInstance {
                    payload: Value::Str(text),
                    ..
                }) => Some(text.as_ref()),
                _ => None,
            },
            _ => None,
        }
    }
    fn template_text(&self, value: &Value) -> Option<String> {
        self.template_raw_str(value).map(str::to_owned)
    }
    fn make_interpolation(
        &mut self,
        value: Value,
        expression: Value,
        conversion: Value,
        format_spec: Value,
    ) -> Value {
        self.obj_value(Object::Interpolation {
            value,
            expression,
            conversion,
            format_spec,
        })
    }
    fn template_build(&mut self, parts: Vec<Value>) -> PyResult<Value> {
        let root = self.roots.len();
        self.roots.push(parts.clone());
        let result = (|| {
            let mut strings = Vec::new();
            let mut interpolations = Vec::new();
            let mut pending: Option<Value> = None;
            for part in parts {
                if let Some(text) = self.template_text(&part) {
                    pending = Some(if let Some(previous) = pending.take() {
                        Value::Str(
                            format!("{}{}", self.template_text(&previous).unwrap(), text).into(),
                        )
                    } else {
                        part
                    });
                } else if matches!(&part,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Interpolation{..})))
                {
                    strings.push(pending.take().unwrap_or_else(|| Value::Str("".into())));
                    interpolations.push(part);
                } else {
                    return Err(pyerr("TypeError",format!("Template.__new__ *args need to be of type 'str' or 'Interpolation', got {}",self.typename(&part))));
                }
            }
            strings.push(pending.unwrap_or_else(|| Value::Str("".into())));
            let strings = self.alloc(Object::Tuple(strings));
            self.roots[root].push(Value::Obj(strings));
            let interpolations = self.alloc(Object::Tuple(interpolations));
            self.roots[root].push(Value::Obj(interpolations));
            Ok(self.obj_value(Object::Template {
                strings,
                interpolations,
            }))
        })();
        self.roots.truncate(root);
        result
    }
    fn template_constructor(
        &mut self,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> Option<PyResult<Value>> {
        if !template_type_name(name) {
            return None;
        }
        Some((|| {
            if name.ends_with(".Template") {
                if !kwargs.is_empty() {
                    return Err(pyerr(
                        "TypeError",
                        "Template.__new__ only accepts *args arguments",
                    ));
                }
                return self.template_build(args);
            }
            let fields = codec_bind(
                "Interpolation",
                args,
                kwargs,
                &["value", "expression", "conversion", "format_spec"],
            )?;
            let value = fields[0].clone().ok_or_else(|| {
                pyerr(
                    "TypeError",
                    "Interpolation() missing required argument 'value'",
                )
            })?;
            let expression = fields[1].clone().unwrap_or_else(|| Value::Str("".into()));
            let conversion = fields[2].clone().unwrap_or(Value::None);
            let format_spec = fields[3].clone().unwrap_or_else(|| Value::Str("".into()));
            if self.template_raw_str(&expression).is_none() {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "Interpolation() argument 'expression' must be str, not {}",
                        if matches!(expression, Value::None) {
                            "None".into()
                        } else {
                            self.typename(&expression)
                        }
                    ),
                ));
            }
            if !matches!(conversion, Value::None) {
                let text = self.template_text(&conversion).ok_or_else(|| {
                    pyerr(
                        "TypeError",
                        format!(
                            "Interpolation() argument 'conversion' must be str, not {}",
                            self.typename(&conversion)
                        ),
                    )
                })?;
                if !["r", "s", "a"].contains(&text.as_str()) {
                    return Err(pyerr(
                        "ValueError",
                        "Interpolation() argument 'conversion' must be one of 's', 'a' or 'r'",
                    ));
                }
            }
            if self.template_raw_str(&format_spec).is_none() {
                return Err(pyerr(
                    "TypeError",
                    format!(
                        "Interpolation() argument 'format_spec' must be str, not {}",
                        if matches!(format_spec, Value::None) {
                            "None".into()
                        } else {
                            self.typename(&format_spec)
                        }
                    ),
                ));
            }
            Ok(self.make_interpolation(value, expression, conversion, format_spec))
        })())
    }
    fn template_class_metadata(&mut self, class: &str, name: &str) -> Option<Value> {
        let key = if name == "__module__" {
            "__module__".to_owned()
        } else {
            format!("{}:{}", class, name)
        };
        if let Some(value) = self.template_metadata.get(&key) {
            return Some(value.clone());
        }
        let value = match name {
            "__module__" => Value::Str("string.templatelib".into()),
            "__bases__" => self.obj_value(Object::Tuple(vec![Value::Builtin("object".into())])),
            "__mro__" => self.obj_value(Object::Tuple(vec![
                Value::Builtin(class.into()),
                Value::Builtin("object".into()),
            ])),
            "__match_args__" if class.ends_with(".Interpolation") => self.obj_value(Object::Tuple(
                ["value", "expression", "conversion", "format_spec"]
                    .iter()
                    .map(|name| Value::Str((*name).into()))
                    .collect(),
            )),
            _ => return None,
        };
        self.template_metadata.insert(key, value.clone());
        Some(value)
    }
    fn template_attr(&mut self, value: Value, name: &str) -> Option<PyResult<Value>> {
        if let Value::Builtin(class) = &value {
            if !template_type_name(class) {
                return None;
            }
            if let Some(value) = self.template_class_metadata(class, name) {
                return Some(Ok(value));
            }
            return Some(match name {
                "__class__" => Ok(Value::Builtin("type".into())),
                "__name__" | "__qualname__" => {
                    Ok(Value::Str(class.rsplit('.').next().unwrap().into()))
                }
                "__class_getitem__" => Ok(self.obj_value(Object::Bound(
                    Value::Builtin("method:__class_getitem__".into()),
                    value,
                ))),
                _ => return None,
            });
        }
        let Value::Obj(index) = &value else {
            return None;
        };
        let object = self.heap.get(*index)?.as_ref()?;
        if !matches!(
            object,
            Object::Template { .. }
                | Object::Interpolation { .. }
                | Object::Iterator(IteratorState::Template(..))
        ) {
            return None;
        }
        let object = object.clone();
        if let Object::Iterator(IteratorState::Template(..)) = &object {
            if name == "__length_hint__" {
                return Some(Err(pyerr("AttributeError", name)));
            }
            return None;
        }
        Some(match object {
            Object::Template {
                strings,
                interpolations,
            } => match name {
                "__class__" => Ok(Value::Builtin("string.templatelib.Template".into())),
                "strings" => Ok(Value::Obj(strings)),
                "interpolations" => Ok(Value::Obj(interpolations)),
                "values" => (|| {
                    let Object::Tuple(items) = self.object(interpolations)? else {
                        unreachable!()
                    };
                    let mut values = Vec::new();
                    for item in items {
                        let Value::Obj(index) = item else {
                            unreachable!()
                        };
                        let Object::Interpolation { value, .. } = self.object(index)? else {
                            unreachable!()
                        };
                        values.push(value);
                    }
                    Ok(self.obj_value(Object::Tuple(values)))
                })(),
                "__iter__" | "__add__" | "__repr__" | "__str__" => Ok(self.obj_value(
                    Object::Bound(Value::Builtin(format!("method:{}", name)), value),
                )),
                _ => return None,
            },
            Object::Interpolation {
                value: inner,
                expression,
                conversion,
                format_spec,
            } => match name {
                "__class__" => Ok(Value::Builtin("string.templatelib.Interpolation".into())),
                "value" => Ok(inner),
                "expression" => Ok(expression),
                "conversion" => Ok(conversion),
                "format_spec" => Ok(format_spec),
                "__repr__" | "__str__" => Ok(self.obj_value(Object::Bound(
                    Value::Builtin(format!("method:{}", name)),
                    value,
                ))),
                _ => return None,
            },
            _ => return None,
        })
    }
    fn template_method(
        &mut self,
        value: Value,
        name: &str,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> Option<PyResult<Value>> {
        if matches!(&value,Value::Builtin(class)if template_type_name(class))
            && name == "__class_getitem__"
        {
            return Some(if args.len() == 1 && kwargs.is_empty() {
                self.generic_alias(value, args[0].clone())
            } else {
                Err(pyerr("TypeError", "__class_getitem__() takes one argument"))
            });
        }
        let Value::Obj(index) = &value else {
            return None;
        };
        if !matches!(
            self.heap.get(*index).and_then(Option::as_ref),
            Some(Object::Template { .. } | Object::Interpolation { .. })
        ) {
            return None;
        }
        if !["__iter__", "__add__", "__repr__", "__str__"].contains(&name) {
            return None;
        }
        Some((|| {
            let expected = if name == "__add__" { 1 } else { 0 };
            if args.len() != expected || !kwargs.is_empty() {
                return Err(pyerr("TypeError", "invalid template method arguments"));
            }
            match name {
                "__iter__" => self.iter(value),
                "__add__" => self.template_concat(value, args[0].clone()).unwrap(),
                _ => Ok(Value::Str(self.repr(&value)?.into())),
            }
        })())
    }
    fn template_concat(&mut self, a: Value, b: Value) -> Option<PyResult<Value>> {
        let parts = |runtime: &Self, value: &Value| match value {
            Value::Obj(index) => match runtime.heap.get(*index).and_then(Option::as_ref) {
                Some(Object::Template {
                    strings,
                    interpolations,
                }) => Some((*strings, *interpolations)),
                _ => None,
            },
            _ => None,
        };
        let left = parts(self, &a);
        let right = parts(self, &b);
        if left.is_none() && right.is_none() {
            return None;
        }
        Some((|| {
            let (Some((ls, li)), Some((rs, ri))) = (left, right) else {
                return Err(pyerr("TypeError",format!("can only concatenate string.templatelib.Template (not \"{}\") to string.templatelib.Template",if left.is_none(){self.typename(&a)}else{self.typename(&b)})));
            };
            let Object::Tuple(mut strings) = self.object(ls)? else {
                unreachable!()
            };
            let Object::Tuple(other) = self.object(rs)? else {
                unreachable!()
            };
            let end = strings.pop().unwrap();
            strings.push(Value::Str(
                format!(
                    "{}{}",
                    self.template_text(&end).unwrap(),
                    self.template_text(&other[0]).unwrap()
                )
                .into(),
            ));
            strings.extend(other.into_iter().skip(1));
            let strings = self.alloc(Object::Tuple(strings));
            let Object::Tuple(mut items) = self.object(li)? else {
                unreachable!()
            };
            let Object::Tuple(other) = self.object(ri)? else {
                unreachable!()
            };
            let interpolations = if other.is_empty() {
                li
            } else if items.is_empty() {
                ri
            } else {
                items.extend(other);
                self.alloc(Object::Tuple(items))
            };
            Ok(self.obj_value(Object::Template {
                strings,
                interpolations,
            }))
        })())
    }
    fn template_next(&mut self, owner: usize, position: &mut usize) -> PyResult<Option<Value>> {
        let Some(Object::Template {
            strings,
            interpolations,
        }) = self.heap.get(owner).and_then(Option::as_ref)
        else {
            unreachable!()
        };
        let Some(Object::Tuple(strings)) = self.heap.get(*strings).and_then(Option::as_ref) else {
            unreachable!()
        };
        let Some(Object::Tuple(items)) = self.heap.get(*interpolations).and_then(Option::as_ref)
        else {
            unreachable!()
        };
        loop {
            let index = *position / 2;
            if index >= strings.len() {
                return Ok(None);
            }
            let string = *position % 2 == 0;
            *position += 1;
            if string {
                if !self.template_raw_str(&strings[index]).unwrap().is_empty() {
                    return Ok(Some(strings[index].clone()));
                }
            } else if let Some(item) = items.get(index) {
                return Ok(Some(item.clone()));
            }
        }
    }
    fn template_repr(&mut self, value: &Value, seen: &mut Vec<usize>) -> Option<PyResult<String>> {
        let Value::Obj(index) = value else {
            return None;
        };
        let object = self.heap.get(*index)?.as_ref()?;
        if !matches!(
            object,
            Object::Template { .. } | Object::Interpolation { .. }
        ) {
            return None;
        }
        let object = object.clone();
        let root = self.roots.len();
        self.roots.push(vec![value.clone()]);
        let result = (|| match object {
            Object::Template {
                strings,
                interpolations,
            } => Ok(format!(
                "Template(strings={}, interpolations={})",
                self.repr_inner(&Value::Obj(strings), seen)?,
                self.repr_inner(&Value::Obj(interpolations), seen)?
            )),
            Object::Interpolation {
                value,
                expression,
                conversion,
                format_spec,
            } => Ok(format!(
                "Interpolation({}, {}, {}, {})",
                self.repr_inner(&value, seen)?,
                self.repr_inner(&expression, seen)?,
                self.repr_inner(&conversion, seen)?,
                self.repr_inner(&format_spec, seen)?
            )),
            _ => unreachable!(),
        })();
        self.roots.truncate(root);
        Some(result)
    }
    fn template_convert(
        &mut self,
        args: Vec<Value>,
        kwargs: Vec<(String, Value)>,
    ) -> PyResult<Value> {
        if kwargs.iter().any(|(name, _)| name == "obj") {
            return Err(pyerr(
                "TypeError",
                "convert() got some positional-only arguments passed as keyword arguments: 'obj'",
            ));
        }
        let fields = codec_bind("convert", args, kwargs, &["obj", "conversion"])?;
        let obj = fields[0]
            .clone()
            .ok_or_else(|| pyerr("TypeError", "convert() missing argument 'obj'"))?;
        let conversion = fields[1]
            .clone()
            .ok_or_else(|| pyerr("TypeError", "convert() missing argument 'conversion'"))?;
        if matches!(conversion, Value::None) {
            return Ok(obj);
        }
        for (name, function) in [("r", "repr"), ("s", "str"), ("a", "ascii")] {
            if self.compare("==", &conversion, &Value::Str(name.into()))? {
                return self.builtin(function, vec![obj], Vec::new(), None);
            }
        }
        Err(pyerr(
            "ValueError",
            format!(
                "invalid conversion specifier: {}",
                self.str_value(&conversion)?
            ),
        ))
    }
}
