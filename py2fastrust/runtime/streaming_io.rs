// Buffered standard input shared by the VM and native AOT backend. Text has
// its own decoded look-ahead, while binary operations use the same raw reader.
// UTF-8 decoding is independent; standard-input lines retain CR bytes and
// end at LF, as CPython standard streams do on the submission platform.
struct StandardInput {
    reader: std::io::StdinLock<'static>,
    decoded: String,
    position: usize,
    pending: Vec<u8>,
    eof: bool,
}
enum StandardInputError {
    Io(std::io::Error),
    Decode { object: Vec<u8>, start: usize, end: usize, reason: &'static str },
    Memory,
}
impl StandardInputError {
    fn native_message(self) -> String {
        match self {
            Self::Io(error)=>format!("OSError: {error}"),
            Self::Memory=>"MemoryError: cannot allocate input buffer".into(),
            Self::Decode{..}=>"UnicodeDecodeError: input is not valid UTF-8".into(),
        }
    }
}
impl StandardInput {
    fn new() -> Self {
        Self { reader:std::io::stdin().lock(), decoded:String::new(), position:0,
            pending:Vec::with_capacity(8196), eof:false }
    }
    fn decode_pending(&mut self, final_:bool) -> Result<(),StandardInputError> {
        let valid=match std::str::from_utf8(&self.pending) {
            Ok(_)=>self.pending.len(),
            Err(error) if error.error_len().is_none() && !final_=>error.valid_up_to(),
            Err(error)=>{
                let start=error.valid_up_to();
                let end=error.error_len().map(|length|start+length).unwrap_or(self.pending.len());
                let first=self.pending[start];
                let reason=if error.error_len().is_none(){"unexpected end of data"}
                    else if !(0xc2..=0xf4).contains(&first){"invalid start byte"}
                    else{"invalid continuation byte"};
                return Err(StandardInputError::Decode{object:self.pending.clone(),start,end,reason});
            }
        };
        self.decoded.push_str(std::str::from_utf8(&self.pending[..valid]).unwrap());
        let remaining=self.pending.len()-valid;
        self.pending.copy_within(valid..,0);self.pending.truncate(remaining);
        Ok(())
    }
    fn fill_text(&mut self) -> Result<bool,StandardInputError> {
        self.decoded.clear();self.position=0;
        while !self.eof {
            let mut bytes=[0;8192];
            let size=loop {match std::io::Read::read(&mut self.reader,&mut bytes) {
                Err(error) if error.kind()==std::io::ErrorKind::Interrupted=>continue,
                result=>break result.map_err(StandardInputError::Io)?,
            }};
            self.eof=size==0;
            let previous=self.pending.len();self.pending.extend_from_slice(&bytes[..size]);
            if let Err(error)=self.decode_pending(self.eof){self.pending.truncate(previous);return Err(error);}
            if !self.decoded.is_empty(){return Ok(true);}
        }
        // A final decoder error may be retried without new raw bytes.
        if !self.pending.is_empty() {self.decode_pending(true)?;}
        Ok(!self.decoded.is_empty())
    }
    fn read_text_into(&mut self,out:&mut String,count:Option<usize>,line:bool)->Result<(),StandardInputError> {
        out.clear();
        if count==Some(0) {
            // TextIOWrapper.readline(0) still obtains a decoded chunk when
            // its text buffer is empty; read(0) and binary readline(0) do not.
            if line && self.position==self.decoded.len(){self.fill_text()?;}
            return Ok(());
        }
        if count.is_none() && !line {
            let previous=self.pending.len();
            std::io::Read::read_to_end(&mut self.reader,&mut self.pending).map_err(StandardInputError::Io)?;
            self.eof=true;
            if let Err(error)=self.decode_pending(true){self.pending.truncate(previous);return Err(error);}
            out.push_str(&self.decoded[self.position..]);self.decoded.clear();self.position=0;
            return Ok(());
        }
        let mut length=0;
        loop {
            if self.position==self.decoded.len() && !self.fill_text()? {return Ok(());}
            let available=&self.decoded[self.position..];
            let mut end=if let Some(count)=count {
                let remaining=count-length;
                if available.is_ascii(){available.len().min(remaining)}
                else{available.char_indices().nth(remaining).map(|(index,_)|index).unwrap_or(available.len())}
            } else {available.len()};
            if line {if let Some(index)=available[..end].find('\n'){end=index+1;}}
            let selected=&available[..end];
            let newline=selected.ends_with('\n');
            length+=if selected.is_ascii(){selected.len()}else{selected.chars().count()};
            out.push_str(selected);self.position+=end;
            if (line&&newline) || count==Some(length){return Ok(());}
        }
    }
    fn read_binary(&mut self,count:Option<usize>,line:bool)->Result<Vec<u8>,StandardInputError> {
        use std::io::{BufRead,Read};
        let mut out=Vec::new();if count==Some(0){return Ok(out);}
        if count.is_none() && !line {
            self.reader.read_to_end(&mut out).map_err(StandardInputError::Io)?;
            return Ok(out);
        }
        loop {
            let available=match self.reader.fill_buf() {
                Err(error) if error.kind()==std::io::ErrorKind::Interrupted=>continue,
                result=>result.map_err(StandardInputError::Io)?,
            };
            if available.is_empty(){return Ok(out);}
            let mut end=available.len();
            if let Some(count)=count{end=end.min(count-out.len());}
            if line {if let Some(index)=available[..end].iter().position(|byte|*byte==b'\n'){end=index+1;}}
            out.try_reserve(end).map_err(|_|StandardInputError::Memory)?;
            out.extend_from_slice(&available[..end]);
            let newline=out.last()==Some(&b'\n');
            self.reader.consume(end);
            if (line&&newline) || count==Some(out.len()){return Ok(out);}
        }
    }
}
