// Immutable Python text with cached character metadata and shared storage.
// All indexing is by Unicode scalar value, matching Python str indices.
#[derive(Clone)]
struct NativeText {
    repr: NativeTextRepr,
}

#[derive(Clone)]
enum NativeTextRepr {
    Inline {
        bytes: [u8; 4],
        length: u8,
        ascii: bool,
    },
    Shared(std::rc::Rc<NativeTextData>),
    Static(&'static NativeTextLiteral),
}

struct NativeTextLiteral {
    text:&'static str,
    ascii:std::sync::OnceLock<bool>,
    characters:std::sync::OnceLock<usize>,
    offsets:std::sync::OnceLock<Vec<usize>>,
}
impl NativeTextLiteral {
    const fn new(text:&'static str)->Self {
        Self{text,ascii:std::sync::OnceLock::new(),characters:std::sync::OnceLock::new(),offsets:std::sync::OnceLock::new()}
    }
}

struct NativeTextData {
    text: Box<str>,
    ascii: bool,
    characters: usize,
    offsets: std::cell::OnceCell<Vec<usize>>,
}

impl NativeText {
    fn inline(text: &str, ascii: bool) -> Option<Self> {
        if text.len() > 4 || !ascii && text.chars().next().map_or(0, char::len_utf8) != text.len() {
            return None;
        }
        let mut bytes = [0; 4];
        bytes[..text.len()].copy_from_slice(text.as_bytes());
        Some(Self { repr: NativeTextRepr::Inline { bytes, length: text.len() as u8, ascii } })
    }

    fn shared(text: Box<str>, ascii: bool) -> Self {
        let characters = if !NATIVE_TEXT_UNICODE || ascii { text.len() } else { text.chars().count() };
        Self { repr: NativeTextRepr::Shared(std::rc::Rc::new(NativeTextData {
            text, ascii, characters, offsets: std::cell::OnceCell::new(),
        })) }
    }

    fn new() -> Self { Self::default() }

    fn literal(value:&'static NativeTextLiteral)->Self {Self{repr:NativeTextRepr::Static(value)}}

    fn as_str(&self) -> &str {
        match &self.repr {
            NativeTextRepr::Inline { bytes, length, .. } => {
                // Inline buffers are populated exclusively from valid UTF-8.
                std::str::from_utf8(&bytes[..*length as usize]).unwrap()
            }
            NativeTextRepr::Shared(data) => &data.text,
            NativeTextRepr::Static(data) => data.text,
        }
    }

    fn is_ascii_cached(&self) -> bool {
        match &self.repr {
            NativeTextRepr::Inline { ascii, .. } => *ascii,
            NativeTextRepr::Shared(data) => data.ascii,
            NativeTextRepr::Static(data) => !NATIVE_TEXT_UNICODE||*data.ascii.get_or_init(||data.text.is_ascii()),
        }
    }

    // Deliberately shadows str::is_ascii: this never scans text again.
    fn is_ascii(&self) -> bool { self.is_ascii_cached() }

    fn byte_len(&self) -> usize { self.as_str().len() }

    fn codepoint_len(&self) -> usize {
        match &self.repr {
            NativeTextRepr::Inline { length, ascii, .. } => {
                if *ascii { *length as usize } else { 1 }
            }
            NativeTextRepr::Shared(data) => data.characters,
            NativeTextRepr::Static(data) => if self.is_ascii_cached(){data.text.len()}else{*data.characters.get_or_init(||data.text.chars().count())},
        }
    }

    // Return a byte boundary for a nonnegative codepoint boundary, including
    // the terminal boundary. Out-of-range boundaries are None.
    fn byte_offset(&self, boundary: usize) -> Result<Option<usize>, String> {
        if boundary > self.codepoint_len() { return Ok(None); }
        if self.is_ascii_cached() { return Ok(Some(boundary)); }
        match &self.repr {
            NativeTextRepr::Inline { length, .. } => {
                Ok(Some(if boundary == 0 { 0 } else { *length as usize }))
            }
            NativeTextRepr::Static(data) => {
                if data.offsets.get().is_none(){
                    let capacity=self.codepoint_len().checked_add(1).ok_or("MemoryError")?;
                    let mut offsets=Vec::new();offsets.try_reserve_exact(capacity).map_err(|_|"MemoryError".to_string())?;
                    offsets.extend(data.text.char_indices().map(|(offset,_)|offset));offsets.push(data.text.len());
                    let _=data.offsets.set(offsets);
                }
                Ok(Some(data.offsets.get().unwrap()[boundary]))
            },
            NativeTextRepr::Shared(data) => {
                if data.offsets.get().is_none() {
                    let capacity = data.characters.checked_add(1).ok_or("MemoryError")?;
                    let mut offsets = Vec::new();
                    offsets.try_reserve_exact(capacity).map_err(|_| "MemoryError".to_owned())?;
                    offsets.extend(data.text.char_indices().map(|(offset, _)| offset));
                    offsets.push(data.text.len());
                    // Rc/OnceCell deliberately keep this single-threaded.
                    // No user callback runs while building the offset table.
                    let _ = data.offsets.set(offsets);
                }
                Ok(Some(data.offsets.get().unwrap()[boundary]))
            }
        }
    }

    fn byte_range(&self, start: usize, stop: usize) -> Result<Option<std::ops::Range<usize>>, String> {
        if start > stop { return Ok(None); }
        match (self.byte_offset(start)?, self.byte_offset(stop)?) {
            (Some(start), Some(stop)) => Ok(Some(start..stop)),
            _ => Ok(None),
        }
    }

    fn codepoint_at(&self,index:i128)->Result<u32,String> {
        let length=self.codepoint_len()as i128;
        let index=if index<0{index+length}else{index};
        if index<0||index>=length{return Err("IndexError: string index out of range".to_string());}
        let index=index as usize;
        if self.is_ascii_cached(){return Ok(self.as_bytes()[index]as u32);}
        let start=self.byte_offset(index)?.unwrap();
        Ok(self.as_str()[start..].chars().next().unwrap()as u32)
    }

    fn char_at(&self, index: i128) -> Result<Self, String> {
        let length = self.codepoint_len() as i128;
        let normalized = if index < 0 { index + length } else { index };
        if normalized < 0 || normalized >= length {
            return Err("IndexError: string index out of range".to_owned());
        }
        let index = normalized as usize;
        let start = self.byte_offset(index)?.unwrap();
        let stop = self.byte_offset(index + 1)?.unwrap();
        let text = &self.as_str()[start..stop];
        // One indexed character always fits inline, without any allocation.
        Ok(Self::inline(text, stop - start == 1).unwrap())
    }

    // Reuse unique owned storage where possible; shared text is copied only
    // when an operation genuinely needs a mutable String builder.
    fn into_string(self) -> String {
        match self.repr {
            NativeTextRepr::Shared(data) => match std::rc::Rc::try_unwrap(data) {
                Ok(data) => data.text.into_string(),
                Err(data) => data.text.to_string(),
            },
            NativeTextRepr::Inline { bytes, length, .. } => {
                String::from_utf8(bytes[..length as usize].to_vec()).unwrap()
            }
            NativeTextRepr::Static(data) => data.text.to_string(),
        }
    }
}

impl Default for NativeText {
    fn default() -> Self {
        Self { repr: NativeTextRepr::Inline { bytes: [0; 4], length: 0, ascii: true } }
    }
}
impl From<String> for NativeText {
    fn from(text: String) -> Self {
        let ascii = !NATIVE_TEXT_UNICODE || text.is_ascii();
        if let Some(inline) = Self::inline(&text, ascii) { return inline; }
        Self::shared(text.into_boxed_str(), ascii)
    }
}
impl From<&str> for NativeText {
    fn from(text: &str) -> Self {
        let ascii = !NATIVE_TEXT_UNICODE || text.is_ascii();
        if let Some(inline) = Self::inline(text, ascii) { return inline; }
        Self::shared(Box::<str>::from(text), ascii)
    }
}
impl From<&String> for NativeText {
    fn from(text: &String) -> Self { Self::from(text.as_str()) }
}
impl From<char> for NativeText {
    fn from(character: char) -> Self {
        let mut bytes = [0; 4];
        let length = character.encode_utf8(&mut bytes).len() as u8;
        Self { repr: NativeTextRepr::Inline { bytes, length, ascii: character.is_ascii() } }
    }
}
impl From<NativeText> for String {
    fn from(text: NativeText) -> Self { text.into_string() }
}
impl std::ops::Deref for NativeText {
    type Target = str;
    fn deref(&self) -> &str { self.as_str() }
}
impl AsRef<str> for NativeText {
    fn as_ref(&self) -> &str { self.as_str() }
}
impl std::borrow::Borrow<str> for NativeText {
    fn borrow(&self) -> &str { self.as_str() }
}
impl std::fmt::Display for NativeText {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}
impl std::fmt::Debug for NativeText {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Debug::fmt(self.as_str(), formatter)
    }
}
impl PartialEq for NativeText {
    fn eq(&self, other: &Self) -> bool { self.as_str() == other.as_str() }
}
impl Eq for NativeText {}
impl PartialOrd for NativeText {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> { Some(self.cmp(other)) }
}
impl Ord for NativeText {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering { self.as_str().cmp(other.as_str()) }
}
impl std::hash::Hash for NativeText {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) { self.as_str().hash(state); }
}
impl PartialEq<str> for NativeText {
    fn eq(&self, other: &str) -> bool { self.as_str() == other }
}
impl PartialEq<&str> for NativeText {
    fn eq(&self, other: &&str) -> bool { self.as_str() == *other }
}
impl PartialEq<String> for NativeText {
    fn eq(&self, other: &String) -> bool { self.as_str() == other.as_str() }
}
impl PartialEq<NativeText> for str {
    fn eq(&self, other: &NativeText) -> bool { self == other.as_str() }
}
impl PartialEq<NativeText> for &str {
    fn eq(&self, other: &NativeText) -> bool { *self == other.as_str() }
}
impl PartialEq<NativeText> for String {
    fn eq(&self, other: &NativeText) -> bool { self.as_str() == other.as_str() }
}

impl PartialEq<&NativeText> for NativeText {
    fn eq(&self,other:&&NativeText)->bool {self.as_str()==other.as_str()}
}
impl PartialEq<NativeText> for &NativeText {
    fn eq(&self,other:&NativeText)->bool {self.as_str()==other.as_str()}
}
impl PartialOrd<&NativeText> for NativeText {
    fn partial_cmp(&self,other:&&NativeText)->Option<std::cmp::Ordering> {Some(self.as_str().cmp(other.as_str()))}
}
impl PartialOrd<NativeText> for &NativeText {
    fn partial_cmp(&self,other:&NativeText)->Option<std::cmp::Ordering> {Some(self.as_str().cmp(other.as_str()))}
}
