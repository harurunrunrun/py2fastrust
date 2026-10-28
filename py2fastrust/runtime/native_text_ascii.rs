// Immutable ASCII-profile text. Cloning preserves shared string snapshots.
#[derive(Clone)]
struct NativeText { repr:NativeTextRepr }

#[derive(Clone)]
enum NativeTextRepr {
    Inline {bytes:[u8;4],length:u8},
    Shared(std::rc::Rc<NativeTextData>),
    Static(&'static NativeTextLiteral),
}

struct NativeTextLiteral {text:&'static str}
struct NativeTextData {text:Box<str>}
impl NativeTextLiteral {
    const fn new(text:&'static str)->Self {Self{text}}
}

impl NativeText {
    fn inline(text:&str)->Option<Self> {
        if text.len()>4{return None;}
        let mut bytes=[0;4];bytes[..text.len()].copy_from_slice(text.as_bytes());
        Some(Self{repr:NativeTextRepr::Inline{bytes,length:text.len()as u8}})
    }
    fn new()->Self {Self::default()}
    fn literal(value:&'static NativeTextLiteral)->Self {Self{repr:NativeTextRepr::Static(value)}}
    fn as_str(&self)->&str {
        match &self.repr {
            // Constructors only copy complete, valid Rust strings.
            NativeTextRepr::Inline{bytes,length}=>std::str::from_utf8(&bytes[..*length as usize]).unwrap(),
            NativeTextRepr::Shared(data)=>&data.text,
            NativeTextRepr::Static(value)=>value.text,
        }
    }
    fn byte_len(&self)->usize {self.as_str().len()}
    // ASCII is the selected input-domain assumption, not a repeated scan.
    fn is_ascii_cached(&self)->bool {true}
    fn is_ascii(&self)->bool {true}
    fn into_string(self)->String {
        match self.repr {
            NativeTextRepr::Inline{bytes,length}=>String::from_utf8(bytes[..length as usize].to_vec()).unwrap(),
            NativeTextRepr::Shared(data)=>match std::rc::Rc::try_unwrap(data){
                Ok(data)=>data.text.into_string(),Err(data)=>data.text.to_string(),
            },
            NativeTextRepr::Static(value)=>value.text.to_string(),
        }
    }
}
impl Default for NativeText {
    fn default()->Self {Self{repr:NativeTextRepr::Inline{bytes:[0;4],length:0}}}
}
impl From<String> for NativeText {
    fn from(text:String)->Self {
        Self::inline(&text).unwrap_or_else(||Self{repr:NativeTextRepr::Shared(std::rc::Rc::new(NativeTextData{text:text.into_boxed_str()}))})
    }
}
impl From<&str> for NativeText {
    fn from(text:&str)->Self {
        Self::inline(text).unwrap_or_else(||Self{repr:NativeTextRepr::Shared(std::rc::Rc::new(NativeTextData{text:Box::<str>::from(text)}))})
    }
}
impl From<&String> for NativeText {
    fn from(text:&String)->Self {Self::from(text.as_str())}
}
impl From<char> for NativeText {
    fn from(character:char)->Self {
        let mut bytes=[0;4];let length=character.encode_utf8(&mut bytes).len()as u8;
        Self{repr:NativeTextRepr::Inline{bytes,length}}
    }
}
