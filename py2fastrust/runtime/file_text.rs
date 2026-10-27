// Incremental text decoding sits above the shared binary layer. Decoded
// characters remember their physical byte boundary so seek/tell can restore a
// logical text position even while the binary reader has prefetched a chunk.
#[derive(Clone,Debug)]
struct FileTextSnapshot {bytes:Vec<u8>,flags:u32,used:usize}
#[derive(Debug)]
struct FileText {
    buffer:Option<FileBufferRef>,encoding:String,errors:String,newline:Option<String>,
    line_buffering:bool,write_through:bool,newline_flags:u8,telling:bool,
    decoded:std::collections::VecDeque<(char,u64)>,pending:Vec<u8>,pending_start:u64,
    pending_cr:Option<u64>,eof:bool,logical:u64,physical:u64,output:Vec<u8>,read_started:bool,
    snapshot:Option<FileTextSnapshot>,b2cratio:f64,decoded_length:usize,
}
impl FileText {
    fn new(buffer:FileBufferRef,encoding:String,errors:String,newline:Option<String>,line_buffering:bool,write_through:bool)->PyResult<Self> {
        let encoding=if encoding=="locale"{"UTF-8".into()}else{encoding};
        TextCodec::lookup(&encoding)?;
        let logical=buffer.borrow_mut().tell().unwrap_or(0);
        Ok(Self{buffer:Some(buffer),encoding,errors,newline,line_buffering,write_through,newline_flags:0,telling:true,
            decoded:std::collections::VecDeque::new(),pending:Vec::new(),pending_start:logical,pending_cr:None,eof:false,
            logical,physical:logical,output:Vec::new(),read_started:false,snapshot:None,b2cratio:0.0,decoded_length:0})
    }
    fn buffer(&self)->PyResult<FileBufferRef> {self.buffer.clone().ok_or_else(||pyerr("ValueError","underlying buffer has been detached"))}
    fn flush_output(&mut self)->PyResult<()> {
        let buffer=self.buffer()?;
        buffer.borrow().check()?;
        if !self.output.is_empty(){buffer.borrow_mut().write(&self.output)?;self.output.clear();}
        Ok(())
    }
    fn flush(&mut self)->PyResult<()> {self.flush_output()?;self.buffer()?.borrow_mut().flush()?;self.telling=true;Ok(())}
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
        self.read_started=true;
        let start=buffer.borrow_mut().tell().unwrap_or(self.physical);
        let bytes=buffer.borrow_mut().read(if all{None}else{Some(8192)},false,!all)?;
        let byte_count=bytes.len();let flags=if self.pending_cr.is_some(){1}else{0};
        self.physical=start+bytes.len()as u64;
        let final_=all||bytes.is_empty();self.eof=final_;
        let (data,start)=if self.pending.is_empty(){(bytes,start)}else{let mut pending=std::mem::take(&mut self.pending);pending.extend(bytes);(pending,self.pending_start)};
        if all{self.snapshot=None;}
        else if self.telling{self.snapshot=Some(FileTextSnapshot{bytes:data.clone(),flags,used:0});}
        else if let Some(snapshot)=&mut self.snapshot{snapshot.used=0;}
        self.decode(data,start,final_)?;
        self.decoded_length=self.decoded.len();
        self.b2cratio=if self.decoded.is_empty(){0.0}else{byte_count as f64/self.decoded.len()as f64};
        Ok(!self.decoded.is_empty()||!self.eof)
    }
    fn read(&mut self,count:Option<usize>,line:bool)->PyResult<String> {
        self.buffer()?.borrow().readable()?;
        self.flush_output()?;
        if count==Some(0){if line&&self.decoded_length==0{self.fill(false)?;}return Ok(String::new());}
        let all=count.is_none()&&!line;
        let after_all_length=if self.snapshot.is_some(){0}else{self.decoded_length};
        let mut output=String::new();let mut length=0;
        let result=(||{loop {
            if self.decoded.is_empty(){
                if !self.fill(all)?{if line{self.snapshot=None;self.decoded_length=0;}return Ok(output);}
                if self.decoded.is_empty(){continue;}
            }
            let (character,end)=self.decoded.pop_front().unwrap();self.logical=end;output.push(character);length+=1;
            if let Some(snapshot)=&mut self.snapshot{snapshot.used+=1;}
            let line_end=if self.newline.is_none(){character=='\n'}else {
                match self.newline.as_deref().unwrap(){
                    ""=>character=='\n'||character=='\r'&&self.decoded.front().is_none_or(|(next,_)|*next!='\n'),
                    newline=>output.ends_with(newline),
                }
            };
            if count==Some(length)||line&&line_end{return Ok(output);}
        }})();
        if all&&result.is_ok(){self.snapshot=None;self.decoded_length=after_all_length;}
        result
    }
    fn write(&mut self,text:&str)->PyResult<usize> {
        self.buffer()?.borrow().writable()?;
        let translated=match self.newline.as_deref(){Some("\r")=>text.replace('\n',"\r"),Some("\r\n")=>text.replace('\n',"\r\n"),_=>text.to_owned()};
        let bytes=file_encode_text(&translated,&self.encoding,&self.errors)?;
        self.output.try_reserve(bytes.len()).map_err(|_|file_memory())?;self.output.extend(bytes);
        self.decoded.clear();self.pending.clear();self.pending_cr=None;self.eof=false;self.read_started=false;self.snapshot=None;self.decoded_length=0;
        if self.output.len()>=8192||self.write_through{self.flush_output()?;}
        if self.line_buffering&&(text.contains('\n')||text.contains('\r')){self.flush()?;}
        Ok(text.chars().count())
    }
    // The cookie packing and safe decoder replay follow CPython 3.14.4's
    // Modules/_io/textio.c (PSF license; attribution in runtime/NOTICE.txt).
    // Cookies are structural positions, not fixed-width arithmetic results.
    fn tell(&mut self)->PyResult<Int> {
        if !self.telling{return Err(pyerr("OSError","telling position disabled by next() call"));}
        self.flush()?;
        let physical=self.buffer()?.borrow_mut().tell().map_err(|error|if error.kind=="OSError"{file_unsupported("underlying stream is not seekable")}else{error})?;
        let Some(snapshot)=self.snapshot.clone() else{return Ok(Int::exact_small(physical as i128));};
        let mut start=physical.checked_sub(snapshot.bytes.len()as u64).ok_or_else(||pyerr("OSError","can't reconstruct logical file position"))?;
        let mut flags=snapshot.flags;
        let mut remaining=snapshot.used;
        if remaining==0{return Ok(text_cookie(start,flags,0,0,false));}
        let mut skip=(self.b2cratio*remaining as f64)as usize;
        skip=skip.min(snapshot.bytes.len());let mut back=1usize;
        let mut decoder=self.cookie_decoder(flags);
        while skip>0 {
            decoder=self.cookie_decoder(flags);
            let count=decoder.decode_fragment(&snapshot.bytes[..skip],false)?;
            if count<=remaining {
                if decoder.pending.is_empty(){flags=if decoder.pending_cr.is_some(){1}else{0};remaining-=count;break;}
                skip=skip.saturating_sub(decoder.pending.len());back=1;
            } else {skip=skip.saturating_sub(back);back=back.saturating_mul(2);}
        }
        if skip==0{decoder=self.cookie_decoder(flags);}
        start=start.checked_add(skip as u64).ok_or_else(||pyerr("OverflowError","file position overflow"))?;
        if remaining==0{return Ok(text_cookie(start,flags,0,0,false));}
        decoder.decoded.clear();
        let mut fed=0usize;let mut decoded=0usize;let mut at=skip;
        while at<snapshot.bytes.len() {
            decoded+=decoder.decode_fragment(&snapshot.bytes[at..at+1],false)?;fed+=1;at+=1;
            if decoder.pending.is_empty()&&decoded<=remaining {
                start=start.checked_add(fed as u64).ok_or_else(||pyerr("OverflowError","file position overflow"))?;
                remaining-=decoded;flags=if decoder.pending_cr.is_some(){1}else{0};fed=0;decoded=0;
            }
            if decoded>=remaining{break;}
        }
        let mut need_eof=false;
        if at==snapshot.bytes.len()&&decoded<remaining {
            decoded+=decoder.decode_fragment(&[],true)?;need_eof=true;
            if decoded<remaining{return Err(pyerr("OSError","can't reconstruct logical file position"));}
        }
        Ok(text_cookie(start,flags,u32::try_from(fed).map_err(|_|pyerr("OverflowError","cookie is too large"))?,u32::try_from(remaining).map_err(|_|pyerr("OverflowError","cookie is too large"))?,need_eof))
    }
    fn cookie_decoder(&self,flags:u32)->Self {
        Self{buffer:None,encoding:self.encoding.clone(),errors:self.errors.clone(),newline:self.newline.clone(),line_buffering:false,
            write_through:false,newline_flags:0,telling:true,decoded:std::collections::VecDeque::new(),pending:Vec::new(),pending_start:0,
            pending_cr:if flags&1!=0{Some(0)}else{None},eof:false,logical:0,physical:0,output:Vec::new(),read_started:false,snapshot:None,b2cratio:0.0,decoded_length:0}
    }
    fn decode_fragment(&mut self,bytes:&[u8],final_:bool)->PyResult<usize> {
        self.decoded.clear();
        let mut data=std::mem::take(&mut self.pending);data.extend_from_slice(bytes);
        self.decode(data,0,final_)?;Ok(self.decoded.len())
    }
    fn seek(&mut self,offset:Int,whence:i32)->PyResult<Int> {
        self.buffer()?.borrow().check()?;
        self.buffer()?.borrow_mut().tell().map_err(|error|if error.kind=="OSError"{file_unsupported("underlying stream is not seekable")}else{error})?;
        let offset=match whence {
            0=>{if offset.is_negative(){return Err(pyerr("ValueError","negative seek position"));}offset},
            1=>{if !offset.is_zero(){return Err(file_unsupported("can't do nonzero cur-relative seeks"));}self.tell()?},
            2=>{if !offset.is_zero(){return Err(file_unsupported("can't do nonzero end-relative seeks"));}Int::exact_small(0)},
            _=>return Err(pyerr("ValueError","invalid whence")),
        };
        self.flush()?;
        let (position,flags,feed,skip,need_eof)=text_cookie_parts(&offset)?;
        let position=self.buffer()?.borrow_mut().seek(position as i64,if whence==2{2}else{0})?;
        self.decoded.clear();self.pending.clear();self.pending_cr=None;self.eof=false;
        self.logical=position;self.physical=position;self.read_started=false;self.telling=true;self.snapshot=None;self.decoded_length=0;
        if position==0&&flags==0{self.newline_flags=0;}
        if whence==2{return Ok(Int::exact_small(position as i128));}
        self.pending_cr=if flags&1!=0{Some(position)}else{None};
        let data=if skip!=0{self.buffer()?.borrow_mut().read(Some(feed as usize),false,false)?}else{Vec::new()};
        self.physical=position+data.len()as u64;
        self.snapshot=Some(FileTextSnapshot{bytes:data.clone(),flags,used:skip as usize});
        if skip!=0{
            self.decode(data,position,need_eof)?;self.eof=need_eof;
            self.decoded_length=self.decoded.len();
            if self.decoded.len()<skip as usize{return Err(pyerr("OSError","can't restore logical file position"));}
            for _ in 0..skip{self.logical=self.decoded.pop_front().unwrap().1;}
        }
        self.read_started=true;
        Ok(offset)
    }
}
impl Drop for FileText {fn drop(&mut self){if self.buffer.is_some(){let _=self.flush_output();}}}

fn text_cookie(start:u64,flags:u32,feed:u32,skip:u32,eof:bool)->Int {
    Int::exact_parts(false,vec![start as u32,(start>>32)as u32,flags,feed,skip,if eof{1}else{0}])
}
fn text_cookie_parts(cookie:&Int)->PyResult<(u64,u32,u32,u32,bool)> {
    if cookie.is_negative(){return Err(pyerr("ValueError","negative seek position"));}
    let words=cookie.magnitude();
    if words.len()>6||words.get(5).is_some_and(|word|*word>255){return Err(pyerr("OverflowError","int too big to convert"));}
    let word=|index|words.get(index).copied().unwrap_or(0);
    let position=word(0)as u64|((word(1)as u64)<<32);
    if position>i64::MAX as u64||word(3)>i32::MAX as u32||word(4)>i32::MAX as u32{return Err(pyerr("OSError","can't restore logical file position"));}
    Ok((position,word(2),word(3),word(4),word(5)!=0))
}

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
