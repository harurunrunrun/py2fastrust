// Incremental text decoding sits above the shared binary layer. Decoded
// characters remember their physical byte boundary so seek/tell can restore a
// logical text position even while the binary reader has prefetched a chunk.
#[derive(Debug)]
struct FileText {
    buffer:Option<FileBufferRef>,encoding:String,errors:String,newline:Option<String>,
    line_buffering:bool,write_through:bool,newline_flags:u8,telling:bool,
    decoded:std::collections::VecDeque<(char,u64)>,pending:Vec<u8>,pending_start:u64,
    pending_cr:Option<u64>,eof:bool,logical:u64,physical:u64,output:Vec<u8>,read_started:bool,
}
impl FileText {
    fn new(buffer:FileBufferRef,encoding:String,errors:String,newline:Option<String>,line_buffering:bool,write_through:bool)->PyResult<Self> {
        let encoding=if encoding=="locale"{"UTF-8".into()}else{encoding};
        TextCodec::lookup(&encoding)?;
        let logical=buffer.borrow_mut().tell().unwrap_or(0);
        Ok(Self{buffer:Some(buffer),encoding,errors,newline,line_buffering,write_through,newline_flags:0,telling:true,
            decoded:std::collections::VecDeque::new(),pending:Vec::new(),pending_start:logical,pending_cr:None,eof:false,
            logical,physical:logical,output:Vec::new(),read_started:false})
    }
    fn buffer(&self)->PyResult<FileBufferRef> {self.buffer.clone().ok_or_else(||pyerr("ValueError","underlying buffer has been detached"))}
    fn flush_output(&mut self)->PyResult<()> {
        let buffer=self.buffer()?;
        buffer.borrow().check()?;
        if !self.output.is_empty(){buffer.borrow_mut().write(&self.output)?;self.output.clear();}
        Ok(())
    }
    fn flush(&mut self)->PyResult<()> {self.flush_output()?;self.buffer()?.borrow_mut().flush()}
    fn close(&mut self)->PyResult<()> {
        let buffer=self.buffer()?;
        if buffer.borrow().raw()?.borrow().handle.is_none(){return Ok(());}
        let flushed=self.flush();let closed=buffer.borrow_mut().close();flushed.and(closed)
    }
    fn emit(&mut self,character:char,end:u64) {
        let universal=self.newline.as_ref().is_none_or(|value|value.is_empty());
        if !universal{self.decoded.push_back((character,end));return;}
        if let Some(cr_end)=self.pending_cr.take() {
            if character=='\n' {
                self.newline_flags|=4;
                if self.newline.is_none(){self.decoded.push_back(('\n',end));}
                else {self.decoded.push_back(('\r',cr_end));self.decoded.push_back(('\n',end));}
                return;
            }
            self.newline_flags|=1;
            self.decoded.push_back((if self.newline.is_none(){'\n'}else{'\r'},cr_end));
        }
        if character=='\r'{self.pending_cr=Some(end);}
        else {if character=='\n'{self.newline_flags|=2;}self.decoded.push_back((character,end));}
    }
    fn decode(&mut self,bytes:Vec<u8>,start:u64,final_:bool)->PyResult<()> {
        let codec=TextCodec::lookup(&self.encoding)?;
        let mut at=0;
        while at<bytes.len() {
            if matches!(codec,TextCodec::Latin1) || matches!(codec,TextCodec::Ascii)&&bytes[at]<128 {
                self.emit(bytes[at] as char,start+at as u64+1);at+=1;continue;
            }
            let (bad,end,reason)=if matches!(codec,TextCodec::Ascii) {(at,at+1,"ordinal not in range(128)")}
            else {
                match std::str::from_utf8(&bytes[at..]) {
                    Ok(text)=>{for(index,character)in text.char_indices(){self.emit(character,start+(at+index+character.len_utf8())as u64);}at=bytes.len();continue;},
                    Err(error)=>{
                        let bad=at+error.valid_up_to();
                        for(index,character)in std::str::from_utf8(&bytes[at..bad]).unwrap().char_indices(){self.emit(character,start+(at+index+character.len_utf8())as u64);}
                        if error.error_len().is_none()&&!final_ {self.pending.extend_from_slice(&bytes[bad..]);self.pending_start=start+bad as u64;return Ok(());}
                        let end=bad+error.error_len().unwrap_or(bytes.len()-bad);
                        (bad,end,if !(0xc2..=0xf4).contains(&bytes[bad]){"invalid start byte"}else if error.error_len().is_none(){"unexpected end of data"}else{"invalid continuation byte"})
                    },
                }
            };
            match self.errors.as_str() {
                "strict"=>{self.decoded.clear();return Err(codec_error(codec,Value::Bytes(bytes.clone().into()),bad,end,reason,true));},
                "ignore"=>(),"replace"=>self.emit('\u{fffd}',start+end as u64),
                "backslashreplace"=>for byte in &bytes[bad..end] {for character in format!("\\x{byte:02x}").chars(){self.emit(character,start+end as u64);}},
                _=>return Err(codec_unknown_handler(&self.errors,true)),
            }
            at=end;
        }
        if final_ {if let Some(end)=self.pending_cr.take(){self.newline_flags|=1;self.decoded.push_back((if self.newline.is_none(){'\n'}else{'\r'},end));}}
        Ok(())
    }
    fn fill(&mut self,all:bool)->PyResult<bool> {
        self.flush_output()?;
        let buffer=self.buffer()?;
        buffer.borrow().readable()?;
        if self.eof{return Ok(false);}
        self.read_started=true;
        let start=buffer.borrow_mut().tell().unwrap_or(self.physical);
        let bytes=buffer.borrow_mut().read(if all{None}else{Some(8192)},false,!all)?;
        self.physical=start+bytes.len()as u64;
        let final_=all||bytes.is_empty();self.eof=final_;
        let (data,start)=if self.pending.is_empty(){(bytes,start)}else{let mut pending=std::mem::take(&mut self.pending);pending.extend(bytes);(pending,self.pending_start)};
        self.decode(data,start,final_)?;
        Ok(!self.decoded.is_empty()||!self.eof)
    }
    fn read(&mut self,count:Option<usize>,line:bool)->PyResult<String> {
        self.buffer()?.borrow().readable()?;
        self.flush_output()?;
        if count==Some(0){if line&&self.decoded.is_empty(){self.fill(false)?;}return Ok(String::new());}
        let mut output=String::new();let mut length=0;
        loop {
            if self.decoded.is_empty(){
                if !self.fill(count.is_none()&&!line)?{return Ok(output);}
                if self.decoded.is_empty(){continue;}
            }
            let (character,end)=self.decoded.pop_front().unwrap();self.logical=end;output.push(character);length+=1;
            let line_end=if self.newline.is_none(){character=='\n'}else {
                match self.newline.as_deref().unwrap(){
                    ""=>character=='\n'||character=='\r'&&self.decoded.front().is_none_or(|(next,_)|*next!='\n'),
                    newline=>output.ends_with(newline),
                }
            };
            if count==Some(length)||line&&line_end{return Ok(output);}
        }
    }
    fn write(&mut self,text:&str)->PyResult<usize> {
        self.buffer()?.borrow().writable()?;
        let translated=match self.newline.as_deref(){Some("\r")=>text.replace('\n',"\r"),Some("\r\n")=>text.replace('\n',"\r\n"),_=>text.to_owned()};
        let bytes=file_encode_text(&translated,&self.encoding,&self.errors)?;
        self.output.try_reserve(bytes.len()).map_err(|_|file_memory())?;self.output.extend(bytes);
        self.decoded.clear();self.pending.clear();self.pending_cr=None;self.eof=false;self.read_started=false;
        if self.output.len()>=8192||self.write_through{self.flush_output()?;}
        if self.line_buffering&&(text.contains('\n')||text.contains('\r')){self.flush()?;}
        Ok(text.chars().count())
    }
    fn tell(&mut self)->PyResult<u64> {
        if !self.telling{return Err(pyerr("OSError","telling position disabled by next() call"));}
        self.flush()?;
        let physical=self.buffer()?.borrow_mut().tell().map_err(|error|if error.kind=="OSError"{file_unsupported("underlying stream is not seekable")}else{error})?;
        if self.read_started {Ok(self.logical)}else{Ok(physical)}
    }
    fn seek(&mut self,offset:i64,whence:i32)->PyResult<u64> {
        self.buffer()?.borrow().check()?;
        self.buffer()?.borrow_mut().tell().map_err(|error|if error.kind=="OSError"{file_unsupported("underlying stream is not seekable")}else{error})?;
        let offset=match whence {
            0=>{if offset<0{return Err(pyerr("ValueError","negative seek position"));}offset},
            1=>{if offset!=0{return Err(file_unsupported("can't do nonzero cur-relative seeks"));}self.tell()? as i64},
            2=>{if offset!=0{return Err(file_unsupported("can't do nonzero end-relative seeks"));}0},
            _=>return Err(pyerr("ValueError","invalid whence")),
        };
        self.flush()?;
        let position=self.buffer()?.borrow_mut().seek(offset,if whence==2{2}else{0})?;
        self.decoded.clear();self.pending.clear();self.pending_cr=None;self.eof=false;
        self.logical=position;self.physical=position;self.read_started=false;self.telling=true;
        if position==0{self.newline_flags=0;}
        Ok(position)
    }
}
impl Drop for FileText {fn drop(&mut self){if self.buffer.is_some(){let _=self.flush_output();}}}

fn file_encode_text(text:&str,encoding:&str,errors:&str)->PyResult<Vec<u8>> {
    let codec=TextCodec::lookup(encoding)?;
    if matches!(codec,TextCodec::Utf8){return Ok(text.as_bytes().to_vec());}
    let maximum=if matches!(codec,TextCodec::Ascii){127}else{255};
    let characters:Vec<char>=text.chars().collect();let mut output=Vec::new();let mut at=0;
    while at<characters.len() {
        if characters[at]as u32<=maximum{output.push(characters[at]as u8);at+=1;continue;}
        let start=at;while at<characters.len()&&characters[at]as u32>maximum{at+=1;}
        match errors {
            "strict"=>return Err(codec_error(codec,Value::Str(text.into()),start,at,if maximum==127{"ordinal not in range(128)"}else{"ordinal not in range(256)"},false)),
            "ignore"=>(),"replace"=>output.extend(std::iter::repeat(b'?').take(at-start)),
            "backslashreplace"=>{let text:String=characters[start..at].iter().collect();output.extend_from_slice(text_ascii_escape(&text).as_bytes());},
            "xmlcharrefreplace"=>for character in &characters[start..at]{output.extend_from_slice(format!("&#{};",*character as u32).as_bytes());},
            _=>return Err(codec_unknown_handler(errors,false)),
        }
    }
    Ok(output)
}
