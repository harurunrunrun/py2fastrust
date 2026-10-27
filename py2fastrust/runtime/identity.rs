// Python object identity lives at the Value boundary, independently of the
// internal numeric representation and of the native compiler's scalar values.
#[derive(Clone)]
struct Ident<T> {
    value: T,
    id: u64,
}
thread_local! {
    static IDENTITY_NEXT: std::cell::Cell<u64> = std::cell::Cell::new(1);
    static IDENTITY_SMALL_INTS: Vec<Ident<Int>> = (-5..=256)
        .map(|value| Ident::fresh(Int::from_i128(value)))
        .collect();
}
impl<T> Ident<T> {
    fn fresh(value: T) -> Self {
        let id = IDENTITY_NEXT.with(|next| {
            let id = next.get();
            assert!(
                id <= (i64::MAX as u64 >> 3),
                "object identity space exhausted"
            );
            next.set(id + 1);
            id << 3
        });
        Self { value, id }
    }
    fn into_inner(self) -> T {
        self.value
    }
    fn inner(&self) -> &T {
        &self.value
    }
}
impl<T> std::ops::Deref for Ident<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.value
    }
}
impl<T: std::fmt::Debug> std::fmt::Debug for Ident<T> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.value.fmt(formatter)
    }
}
impl<T: std::fmt::Display> std::fmt::Display for Ident<T> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.value.fmt(formatter)
    }
}
impl<T: PartialEq> PartialEq for Ident<T> {
    fn eq(&self, other: &Self) -> bool {
        self.value == other.value
    }
}
impl<T: Eq> Eq for Ident<T> {}
impl<T: PartialOrd> PartialOrd for Ident<T> {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        self.value.partial_cmp(&other.value)
    }
}
impl<T: Ord> Ord for Ident<T> {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.value.cmp(&other.value)
    }
}
impl<T: PartialEq> PartialEq<T> for Ident<T> {
    fn eq(&self, other: &T) -> bool {
        &self.value == other
    }
}
impl<T: PartialEq> PartialEq<&T> for Ident<T> {
    fn eq(&self, other: &&T) -> bool {
        &self.value == *other
    }
}
impl PartialEq<str> for Ident<String> {
    fn eq(&self, other: &str) -> bool {
        self.value == other
    }
}
impl PartialEq<&str> for Ident<String> {
    fn eq(&self, other: &&str) -> bool {
        self.value == *other
    }
}
impl From<Int> for Ident<Int> {
    fn from(value: Int) -> Self {
        if let Some(number) = value.to_i128().filter(|number| (-5..=256).contains(number)) {
            return IDENTITY_SMALL_INTS.with(|values| values[(number + 5) as usize].clone());
        }
        Self::fresh(value)
    }
}
impl From<Complex> for Ident<Complex>{fn from(value:Complex)->Self{Self::fresh(value)}}
impl From<f64> for Ident<f64> {
    fn from(value: f64) -> Self {
        Self::fresh(value)
    }
}
impl From<String> for Ident<String> {
    fn from(value: String) -> Self {
        Self::fresh(value)
    }
}
impl From<&str> for Ident<String> {
    fn from(value: &str) -> Self {
        Self::fresh(value.to_owned())
    }
}
impl From<Vec<u8>> for Ident<Vec<u8>> {
    fn from(value: Vec<u8>) -> Self {
        Self::fresh(value)
    }
}
impl<A> FromIterator<A> for Ident<String>
where
    String: FromIterator<A>,
{
    fn from_iter<I: IntoIterator<Item = A>>(values: I) -> Self {
        String::from_iter(values).into()
    }
}
impl<A> FromIterator<A> for Ident<Vec<u8>>
where
    Vec<u8>: FromIterator<A>,
{
    fn from_iter<I: IntoIterator<Item = A>>(values: I) -> Self {
        Vec::from_iter(values).into()
    }
}
impl std::str::FromStr for Ident<f64> {
    type Err = std::num::ParseFloatError;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        value.parse::<f64>().map(Into::into)
    }
}
impl std::borrow::Borrow<str> for Ident<String> {
    fn borrow(&self) -> &str {
        self.value.as_str()
    }
}
impl IntoIterator for Ident<Vec<u8>> {
    type Item = u8;
    type IntoIter = std::vec::IntoIter<u8>;
    fn into_iter(self) -> Self::IntoIter {
        self.value.into_iter()
    }
}
impl<'a> IntoIterator for &'a Ident<Vec<u8>> {
    type Item = &'a u8;
    type IntoIter = std::slice::Iter<'a, u8>;
    fn into_iter(self) -> Self::IntoIter {
        self.value.iter()
    }
}

#[derive(Clone, PartialEq, Eq, Hash)]
enum LiteralKey {
    None,
    Bool(bool),
    Int(String),
    Float(u64),
    Complex(u64,u64),
    Str(String),
    Bytes(Vec<u8>),
    ImportNames(Vec<String>),
}
impl Const {
    fn literal_key(&self) -> LiteralKey {
        match self {
            Self::None => LiteralKey::None,
            Self::Bool(value) => LiteralKey::Bool(*value),
            Self::Int(value) => LiteralKey::Int(value.clone()),
            Self::Float(value) => LiteralKey::Float(value.to_bits()),
            Self::Complex(real,imag)=>LiteralKey::Complex(real.to_bits(),imag.to_bits()),
            Self::Str(value) => LiteralKey::Str(value.clone()),
            Self::Bytes(value) => LiteralKey::Bytes(value.clone()),
        }
    }
}
impl Value {
    fn fresh_primitive(&self) -> Self {
        match self {
            Self::Int(value) => Self::Int(value.inner().clone().into()),
            Self::Float(value) => Self::Float((**value).into()),
            Self::Complex(value)=>Self::Complex((**value).into()),
            Self::Str(value) => Self::Str(value.inner().clone().into()),
            Self::Bytes(value) => Self::Bytes(value.inner().clone().into()),
            value => value.clone(),
        }
    }
    fn same_identity(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::None, Self::None) => true,
            (Self::Bool(a), Self::Bool(b)) => a == b,
            (Self::Int(a), Self::Int(b)) => a.id == b.id,
            (Self::Float(a), Self::Float(b)) => a.id == b.id,
            (Self::Complex(a),Self::Complex(b))=>a.id==b.id,
            (Self::Str(a), Self::Str(b)) => a.id == b.id,
            (Self::Bytes(a), Self::Bytes(b)) => a.id == b.id,
            (Self::Obj(a), Self::Obj(b)) => a == b,
            (Self::Builtin(a), Self::Builtin(b)) | (Self::Type(a), Self::Type(b)) => a == b,
            _ => false,
        }
    }
}
impl Runtime {
    // Weak canonical handles: live functions/frames/code constants provide
    // ownership, and the collector evicts entries before arena-slot reuse.
    fn code_object_index(&mut self,code:usize)->usize {
        if let Some(index)=self.code_objects.get(&code).copied() {
            if matches!(self.heap.get(index).and_then(Option::as_ref),Some(Object::Code(found))if *found==code){return index;}
        }
        let index=self.alloc(Object::Code(code));self.code_objects.insert(code,index);index
    }
    fn code_object(&mut self,code:usize)->Value {Value::Obj(self.code_object_index(code))}
    fn code_roots(&self,code:usize,seen:&mut std::collections::HashSet<usize>,roots:&mut Vec<Value>) {
        let mut pending=vec![code];
        while let Some(code)=pending.pop() {
            if !seen.insert(code){continue;}
            if let Some(index)=self.code_objects.get(&code){roots.push(Value::Obj(*index));}
            pending.extend(self.codes[code].child_codes());
        }
    }

    fn index_identity(&mut self, value: &Value) -> PyResult<Ident<Int>> {
        if matches!(value,Value::Obj(_)) {
            if let Some(Value::Int(number))=self.native_capability_payload(value,"int") {
                let Value::Int(number)=Value::Int(number).fresh_primitive()else{unreachable!()};return Ok(number);
            }
        }
        match value {
            Value::Int(number) => Ok(number.clone()),
            Value::Bool(value) => Ok(Int::from_i128(if *value { 1 } else { 0 }).into()),
            _ => match self.special_method(value.clone(), "__index__") {
                Ok(method) => {
                    let result = self.call(method, Vec::new(), Vec::new(), None)?;
                    if let Value::Int(number) = result {
                        return Ok(number);
                    }
                    Ok(self.as_int(&result)?.into())
                }
                Err(error) if self.missing_special_method(value,"__index__",&error) => Ok(self.as_int(value)?.into()),
                Err(error) => Err(error),
            },
        }
    }
    fn identity_number(&mut self, value: &Value) -> u64 {
        match value {
            Value::None => 4,
            Value::Bool(false) => 12,
            Value::Bool(true) => 20,
            Value::Int(value) => value.id,
            Value::Float(value) => value.id,
            Value::Complex(value)=>value.id,
            Value::Str(value) => value.id,
            Value::Bytes(value) => value.id,
            Value::Obj(index) => (*index as u64) << 3 | 1,
            Value::Builtin(name) => {
                let next = self.identity_builtins.len() as u64;
                *self.identity_builtins.entry(name.clone()).or_insert(next) << 3 | 2
            }
            Value::Type(name) => {
                let next = self.identity_types.len() as u64;
                *self.identity_types.entry(name.clone()).or_insert(next) << 3 | 3
            }
        }
    }
    fn identical_or_equal(&mut self, a: &Value, b: &Value) -> PyResult<bool> {
        if a.same_identity(b) {
            Ok(true)
        } else {
            self.equal(a, b)
        }
    }
    fn code_constant(&mut self, code: usize, constant: Const) -> PyResult<Value> {
        if let Const::Str(text)=&constant {
            // CPython interns ASCII identifier-shaped string constants as well
            // as keyword identifiers. Runtime-created mapping keys are separate.
            if text.bytes().all(|byte|byte.is_ascii_alphanumeric()||byte==b'_'){return Ok(Value::Str(self.intern_keyword(text)));}
        }
        let key = constant.literal_key();
        if let Some(value) = self
            .literal_pools
            .get(&code)
            .and_then(|pool| pool.get(&key))
        {
            return Ok(value.clone());
        }
        let value = self.constant(constant)?;
        self.literal_pools
            .entry(code)
            .or_default()
            .insert(key, value.clone());
        Ok(value)
    }
}
