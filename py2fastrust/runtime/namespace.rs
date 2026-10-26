// Fast name lookup with Python's insertion order. Namespace order is visible
// through globals(), vars(), module dictionaries and keyword expansion.
#[derive(Clone, Debug, Default)]
struct OrderedNamespace {
    data: HashMap<String, Value>,
    order: Vec<String>,
    identities: HashMap<String, Ident<String>>,
}
impl OrderedNamespace {
    fn new() -> Self { Self::default() }
    fn len(&self) -> usize { self.data.len() }
    fn is_empty(&self) -> bool { self.data.is_empty() }
    fn contains_key(&self, key: &str) -> bool { self.data.contains_key(key) }
    fn get(&self, key: &str) -> Option<&Value> { self.data.get(key) }
    fn get_mut(&mut self, key: &str) -> Option<&mut Value> { self.data.get_mut(key) }
    fn insert(&mut self, key: String, value: Value) -> Option<Value> {
        if !self.data.contains_key(&key) {
            self.order.push(key.clone());
            self.identities.insert(key.clone(), key.clone().into());
        }
        self.data.insert(key, value)
    }
    fn insert_ident(&mut self, key: Ident<String>, value: Value) -> Option<Value> {
        if !self.data.contains_key(key.as_str()) {
            self.order.push(key.to_string());
            self.identities.insert(key.to_string(), key.clone());
        }
        self.data.insert(key.into_inner(), value)
    }
    fn ident_items(&self) -> Vec<(Value, Value)> {
        self.order.iter().map(|key| (
            Value::Str(self.identities.get(key).expect("namespace identity invariant").clone()),
            self.data.get(key).expect("namespace order invariant").clone(),
        )).collect()
    }
    fn ident_keys(&self) -> Vec<Value> {
        self.order.iter().map(|key| Value::Str(self.identities.get(key).expect("namespace identity invariant").clone())).collect()
    }
    fn remove(&mut self, key: &str) -> Option<Value> {
        let value = self.data.remove(key)?;
        self.order.retain(|name| name != key);
        self.identities.remove(key);
        Some(value)
    }
    fn clear(&mut self) { self.data.clear(); self.order.clear(); self.identities.clear(); }
    fn keys(&self) -> impl DoubleEndedIterator<Item = &String> + ExactSizeIterator {
        self.order.iter()
    }
    fn values(&self) -> impl DoubleEndedIterator<Item = &Value> + ExactSizeIterator {
        self.order.iter().map(|name| self.data.get(name).expect("namespace order invariant"))
    }
    fn iter(&self) -> impl DoubleEndedIterator<Item = (&String, &Value)> + ExactSizeIterator {
        self.order.iter().map(|name| (name, self.data.get(name).expect("namespace order invariant")))
    }
    fn retain(&mut self, mut keep: impl FnMut(&String, &mut Value) -> bool) {
        self.data.retain(|name, value| keep(name, value));
        self.order.retain(|name| self.data.contains_key(name));
        self.identities.retain(|name, _| self.data.contains_key(name));
    }
}
impl FromIterator<(String, Value)> for OrderedNamespace {
    fn from_iter<T: IntoIterator<Item = (String, Value)>>(values: T) -> Self {
        let mut result = Self::new();
        result.extend(values);
        result
    }
}
impl Extend<(String, Value)> for OrderedNamespace {
    fn extend<T: IntoIterator<Item = (String, Value)>>(&mut self, values: T) {
        for (name, value) in values { self.insert(name, value); }
    }
}
impl IntoIterator for OrderedNamespace {
    type Item = (String, Value);
    type IntoIter = std::vec::IntoIter<Self::Item>;
    fn into_iter(self) -> Self::IntoIter {
        let Self { mut data, order, .. } = self;
        order.into_iter().map(|name| {
            let value = data.remove(&name).expect("namespace order invariant");
            (name, value)
        }).collect::<Vec<_>>().into_iter()
    }
}
