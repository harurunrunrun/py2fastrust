// Structural patterns shared by the official-AST and runtime Python compilers.
#[derive(Clone, Debug)]
enum MatchPattern {
    Literal(Const),
    ComplexNumber { real: Const, imag: f64 },
    ValuePath(Vec<String>),
    Sequence(Vec<MatchPattern>),
    Mapping { keys: Vec<MatchPattern>, patterns: Vec<MatchPattern>, rest: Option<String> },
    Class { path: Vec<String>, positional: Vec<MatchPattern>, keyword_names: Vec<String>, keyword_patterns: Vec<MatchPattern> },
    As { pattern: Option<Box<MatchPattern>>, name: Option<String> },
    Or(Vec<MatchPattern>),
    Star(Option<String>),
}

impl Runtime {
    fn pattern_path(&mut self, frame: &Frame, path: &[String], root: usize) -> PyResult<Value> {
        let first = path.first().ok_or_else(|| pyerr("SyntaxError", "empty pattern value path"))?;
        let mut value = self.load(frame, first)?;
        self.roots[root].push(value.clone());
        for name in &path[1..] {
            value = self.getattr(value, name)?;
            self.roots[root].push(value.clone());
        }
        Ok(value)
    }
    fn pattern_bind(&mut self, captures: &mut Vec<(String, Value)>, name: &str, value: Value, root: usize) -> PyResult<()> {
        self.roots[root].push(value.clone());
        // Source-level duplicate captures are rejected by both compilers.
        // Distinct legal spellings can still coincide after class mangling:
        // `case [__x, _Class__x]` assigns the second value to the shared name.
        if let Some((_, previous)) = captures.iter_mut().find(|(bound, _)| bound == name) {
            *previous = value;
        } else {
            captures.push((name.to_owned(), value));
        }
        Ok(())
    }
    fn pattern_sequence(&mut self, subject: &Value) -> PyResult<bool> {
        match subject {
            Value::Obj(index) => match self.object(*index)? {
                Object::List(_) | Object::Tuple(_) | Object::Range(..) => Ok(true),
                Object::Instance { class, .. } => {
                    for name in ["list", "tuple", "range", "Sequence"] {
                        if self.is_subclass(&class, &Value::Builtin(name.to_owned()))? { return Ok(true); }
                    }
                    Ok(false)
                }
                _ => Ok(false),
            },
            _ => Ok(false),
        }
    }
    fn pattern_mapping(&mut self, subject: &Value) -> PyResult<bool> {
        match subject {
            Value::Obj(index) => match self.object(*index)? {
                Object::Dict(_) | Object::Namespace(..) => Ok(true),
                Object::Instance { class, .. } => {
                    for name in ["dict", "Mapping"] {
                        if self.is_subclass(&class, &Value::Builtin(name.to_owned()))? { return Ok(true); }
                    }
                    Ok(false)
                }
                _ => Ok(false),
            },
            _ => Ok(false),
        }
    }
    fn pattern_key(&mut self, frame: &Frame, pattern: &MatchPattern, root: usize) -> PyResult<Value> {
        match pattern {
            MatchPattern::Literal(constant) => self.constant(constant.clone()),
            MatchPattern::ComplexNumber{real,imag} => {
                let value=self.constant(real.clone())?;
                Ok(Value::Complex(Complex{real:self.as_float(&value)?,imag:*imag}.into()))
            },
            MatchPattern::ValuePath(path) => self.pattern_path(frame, path, root),
            _ => Err(pyerr("SyntaxError", "mapping pattern keys must be literals or attribute paths")),
        }
    }
    fn pattern_inner(&mut self, frame: &Frame, subject: Value, pattern: &MatchPattern, captures: &mut Vec<(String, Value)>, root: usize) -> PyResult<bool> {
        self.roots[root].push(subject.clone());
        match pattern {
            MatchPattern::Literal(constant) => {
                let value = self.constant(constant.clone())?;
                if matches!(constant, Const::None | Const::Bool(_)) { self.compare("is", &subject, &value) }
                else { self.equal(&subject, &value) }
            }
            MatchPattern::ComplexNumber{..} => {
                let value=self.pattern_key(frame,pattern,root)?;
                self.equal(&subject,&value)
            }
            MatchPattern::ValuePath(path) => {
                let value = self.pattern_path(frame, path, root)?;
                self.equal(&subject, &value)
            }
            MatchPattern::As { pattern, name } => {
                if let Some(pattern) = pattern {
                    if !self.pattern_inner(frame, subject.clone(), pattern, captures, root)? { return Ok(false); }
                }
                if let Some(name) = name { self.pattern_bind(captures, name, subject, root)?; }
                Ok(true)
            }
            MatchPattern::Or(patterns) => {
                let original = captures.len();
                for pattern in patterns {
                    captures.truncate(original);
                    if self.pattern_inner(frame, subject.clone(), pattern, captures, root)? { return Ok(true); }
                }
                captures.truncate(original);
                Ok(false)
            }
            MatchPattern::Star(_) => Err(pyerr("SyntaxError", "star pattern is only valid inside a sequence")),
            MatchPattern::Sequence(patterns) => {
                if !self.pattern_sequence(&subject)? { return Ok(false); }
                let star = patterns.iter().position(|pattern| matches!(pattern, MatchPattern::Star(_)));
                if patterns.iter().filter(|pattern| matches!(pattern, MatchPattern::Star(_))).count() > 1 { return Err(pyerr("SyntaxError", "multiple starred names in sequence pattern")); }
                let length = self.call(Value::Builtin("len".to_owned()), vec![subject.clone()], Vec::new(), Some(frame))?;
                let length = self.as_int(&length)?.to_i128().ok_or_else(|| pyerr("OverflowError", "sequence length is too large"))?;
                if length < 0 { return Err(pyerr("ValueError", "__len__() should return >= 0")); }
                if (star.is_none() && length != patterns.len() as i128) || (star.is_some() && length < patterns.len() as i128 - 1) { return Ok(false); }
                let values = self.to_vec(subject)?;
                if values.len() as i128 != length { return Err(pyerr("ValueError", "sequence changed length while matching")); }
                for (index, pattern) in patterns.iter().enumerate() {
                    if let MatchPattern::Star(name) = pattern {
                        if let Some(name) = name {
                            let tail = patterns.len() - index - 1;
                            let value = self.obj_value(Object::List(values[index..values.len()-tail].to_vec()));
                            self.pattern_bind(captures, name, value, root)?;
                        }
                    } else {
                        let value_index = if star.is_some_and(|star| index > star) { values.len() - (patterns.len() - index) } else { index };
                        if !self.pattern_inner(frame, values[value_index].clone(), pattern, captures, root)? { return Ok(false); }
                    }
                }
                Ok(true)
            }
            MatchPattern::Mapping { keys, patterns, rest } => {
                if keys.len() != patterns.len() { return Err(pyerr("SyntaxError", "invalid mapping pattern")); }
                if !self.pattern_mapping(&subject)? { return Ok(false); }
                let length = self.call(Value::Builtin("len".to_owned()), vec![subject.clone()], Vec::new(), Some(frame))?;
                if self.as_int(&length)?.to_i128().unwrap_or(i128::MAX) < keys.len() as i128 { return Ok(false); }
                let mut matched_keys = Vec::new();
                let missing = self.obj_value(Object::Namespace(OrderedNamespace::new(), None));
                self.roots[root].push(missing.clone());
                for (key, pattern) in keys.iter().zip(patterns) {
                    let key = self.pattern_key(frame, key, root)?;
                    self.roots[root].push(key.clone());
                    for prior in &matched_keys { if self.identical_or_equal(prior, &key)? { return Err(pyerr("ValueError", "mapping pattern checks duplicate key")); } }
                    let get = self.getattr(subject.clone(), "get")?;
                    let value = self.call(get, vec![key.clone(), missing.clone()], Vec::new(), Some(frame))?;
                    if self.compare("is", &value, &missing)? { return Ok(false); }
                    if !self.pattern_inner(frame, value, pattern, captures, root)? { return Ok(false); }
                    matched_keys.push(key);
                }
                if let Some(rest) = rest {
                    let mut remaining = Vec::new();
                    for (key, value) in self.dict_items(subject)? {
                        let mut consumed = false;
                        for matched in &matched_keys { if self.identical_or_equal(&key, matched)? { consumed = true; break; } }
                        if !consumed { remaining.push((key, value)); }
                    }
                    let value = self.obj_value(Object::Dict(remaining));
                    self.pattern_bind(captures, rest, value, root)?;
                }
                Ok(true)
            }
            MatchPattern::Class { path, positional, keyword_names, keyword_patterns } => {
                if keyword_names.len() != keyword_patterns.len() { return Err(pyerr("SyntaxError", "invalid class pattern")); }
                let class = self.pattern_path(frame, path, root)?;
                let type_valid = match &class {
                    Value::Builtin(name) => template_type_name(name) || ["bool","bytearray","bytes","complex","dict","float","frozenset","int","list","object","range","set","slice","str","tuple","type","NoneType"].contains(&name.as_str()),
                    Value::Type(_) => true,
                    Value::Obj(index) => matches!(self.object(*index)?, Object::Class(_)),
                    _ => false,
                };
                if !type_valid { return Err(pyerr("TypeError", "called match pattern must be a type")); }
                let instance = self.call(Value::Builtin("isinstance".to_owned()), vec![subject.clone(), class.clone()], Vec::new(), Some(frame))?;
                if !self.truth(&instance)? { return Ok(false); }
                let builtin_self = matches!(&class, Value::Builtin(name) if ["bool","bytearray","bytes","dict","float","frozenset","int","list","set","str","tuple"].contains(&name.as_str()));
                let mut attributes = Vec::new();
                if builtin_self {
                    if positional.len() > 1 { return Err(pyerr("TypeError", "builtin class pattern accepts one positional subpattern")); }
                    if let Some(pattern) = positional.first() {
                        if !self.pattern_inner(frame, subject.clone(), pattern, captures, root)? { return Ok(false); }
                    }
                } else if !positional.is_empty() {
                    let names = match self.getattr(class, "__match_args__") {
                        Ok(Value::Obj(index)) => match self.object(index)? { Object::Tuple(names) => names, _ => return Err(pyerr("TypeError", "__match_args__ must be a tuple")) },
                        Ok(_) => return Err(pyerr("TypeError", "__match_args__ must be a tuple")),
                        Err(error) if error.kind == "AttributeError" => Vec::new(),
                        Err(error) => return Err(error),
                    };
                    if positional.len() > names.len() { return Err(pyerr("TypeError", "too many positional subpatterns")); }
                    for name in names.into_iter().take(positional.len()) {
                        match name { Value::Str(name) => attributes.push(name.into_inner()), _ => return Err(pyerr("TypeError", "__match_args__ elements must be strings")) }
                    }
                }
                let mut seen = Vec::new();
                for name in attributes.iter().chain(keyword_names) {
                    if seen.contains(name) { return Err(pyerr("TypeError", format!("class pattern got multiple subpatterns for attribute '{name}'"))); }
                    seen.push(name.clone());
                }
                let position_patterns: &[MatchPattern] = if builtin_self { &[] } else { positional };
                for (name, pattern) in attributes.iter().chain(keyword_names).zip(position_patterns.iter().chain(keyword_patterns)) {
                    let value = match self.getattr(subject.clone(), name) { Ok(value) => value, Err(error) if error.kind == "AttributeError" => return Ok(false), Err(error) => return Err(error) };
                    if !self.pattern_inner(frame, value, pattern, captures, root)? { return Ok(false); }
                }
                Ok(true)
            }
        }
    }
    fn match_pattern(&mut self, frame: &Frame, subject: Value, pattern: MatchPattern) -> PyResult<bool> {
        let root = self.roots.len();
        self.roots.push(vec![subject.clone()]);
        let result = (|| {
            let mut captures = Vec::new();
            let matched = self.pattern_inner(frame, subject, &pattern, &mut captures, root)?;
            if matched { for (name, value) in captures { self.store(frame, name, value)?; } }
            Ok(matched)
        })();
        self.roots.truncate(root);
        result
    }
}
