// File descriptors on the submission platform use checked system calls rather
// than constructing an OwnedFd from an arbitrary user-supplied integer.
#[cfg(all(unix, target_pointer_width="64"))]
mod file_sys {
    use std::ffi::c_void;
    unsafe extern "C" {
        #[link_name="read"] pub fn read(fd:i32,data:*mut c_void,length:usize)->isize;
        #[link_name="write"] pub fn write(fd:i32,data:*const c_void,length:usize)->isize;
        #[link_name="lseek"] pub fn seek(fd:i32,offset:i64,whence:i32)->i64;
        #[link_name="ftruncate"] pub fn truncate(fd:i32,length:i64)->i32;
        #[link_name="close"] pub fn close(fd:i32)->i32;
        #[link_name="isatty"] pub fn isatty(fd:i32)->i32;
        #[link_name="fcntl"] pub fn fcntl(fd:i32,command:i32,...)->i32;
    }
}

fn file_os_error(error:std::io::Error)->PyException {
    let kind=match error.kind() {
        std::io::ErrorKind::NotFound=>"FileNotFoundError",
        std::io::ErrorKind::PermissionDenied=>"PermissionError",
        std::io::ErrorKind::AlreadyExists=>"FileExistsError",
        std::io::ErrorKind::IsADirectory=>"IsADirectoryError",
        std::io::ErrorKind::NotADirectory=>"NotADirectoryError",
        std::io::ErrorKind::WouldBlock=>"BlockingIOError",
        std::io::ErrorKind::Interrupted=>"InterruptedError",
        _=>"OSError",
    };
    let errno=error.raw_os_error().unwrap_or(0);
    let message=error.to_string();
    let reason=message.rsplit_once(" (os error ").map(|(reason,_)|reason).unwrap_or(&message);
    let mut exception=pyerr(kind,format!("[Errno {errno}] {reason}"));
    exception.args=vec![Value::Int(Int::from_i128(errno as i128).into()),Value::Str(reason.into())];
    let number=exception.args[0].clone();let reason=exception.args[1].clone();
    exception.attributes.insert("errno".into(),number);
    exception.attributes.insert("strerror".into(),reason);
    exception.attributes.insert("filename".into(),Value::None);
    exception.attributes.insert("filename2".into(),Value::None);
    exception
}
fn file_closed()->PyException {pyerr("ValueError","I/O operation on closed file")}
fn file_unsupported(message:&str)->PyException {pyerr("UnsupportedOperation",message)}
fn file_memory()->PyException {pyerr("MemoryError","cannot allocate file buffer")}

#[derive(Debug)]
enum FileHandle {
    Owned(std::fs::File),
    #[cfg(all(unix,target_pointer_width="64"))]
    Descriptor {fd:i32,closefd:bool},
}
impl Drop for FileHandle {
    fn drop(&mut self) {
        #[cfg(all(unix,target_pointer_width="64"))]
        if let Self::Descriptor{fd,closefd:true}=self {unsafe{file_sys::close(*fd);}}
    }
}
#[derive(Debug)]
struct FileRaw {
    handle:Option<FileHandle>,readable:bool,writable:bool,
}
type FileRawRef=std::rc::Rc<std::cell::RefCell<FileRaw>>;
impl FileRaw {
    fn owned(file:std::fs::File,readable:bool,writable:bool)->Self {
        #[cfg(all(unix,target_pointer_width="64"))]
        {
            // Other Python file objects may wrap and close this same numeric
            // descriptor. Keep ownership here as checked raw system calls so
            // that the original wrapper reports EBADF rather than triggering
            // Rust OwnedFd's I/O-safety abort during a later double close.
            use std::os::fd::IntoRawFd;
            Self{handle:Some(FileHandle::Descriptor{fd:file.into_raw_fd(),closefd:true}),readable,writable}
        }
        #[cfg(not(all(unix,target_pointer_width="64")))]
        {Self{handle:Some(FileHandle::Owned(file)),readable,writable}}
    }
    fn check(&self)->PyResult<()> {if self.handle.is_none(){Err(file_closed())}else{Ok(())}}
    fn descriptor(fd:i32,closefd:bool,readable:bool,writable:bool)->PyResult<Self> {
        if fd<0{return Err(pyerr("ValueError","negative file descriptor"));}
        #[cfg(all(unix,target_pointer_width="64"))]
        {
            // F_GETFD validates the integer; errors never enter Rust's I/O
            // ownership contract and an invalid integer remains an OSError.
            if unsafe{file_sys::fcntl(fd,1)}<0 {return Err(file_os_error(std::io::Error::last_os_error()));}
            Ok(Self{handle:Some(FileHandle::Descriptor{fd,closefd}),readable,writable})
        }
        #[cfg(not(all(unix,target_pointer_width="64")))]
        {let _=(fd,closefd,readable,writable);Err(pyerr("NotImplementedError","integer file descriptors require a 64-bit Unix target"))}
    }
    fn read(&mut self,bytes:&mut[u8])->PyResult<usize> {
        self.check()?;
        if !self.readable{return Err(file_unsupported("File not open for reading"));}
        loop {
            let result=match self.handle.as_mut().unwrap() {
                FileHandle::Owned(file)=>std::io::Read::read(file,bytes),
                #[cfg(all(unix,target_pointer_width="64"))]
                FileHandle::Descriptor{fd,..}=>{
                    let size=unsafe{file_sys::read(*fd,bytes.as_mut_ptr().cast(),bytes.len())};
                    if size<0{Err(std::io::Error::last_os_error())}else{Ok(size as usize)}
                },
            };
            match result {Err(error) if error.kind()==std::io::ErrorKind::Interrupted=>continue,result=>return result.map_err(file_os_error)}
        }
    }
    fn write(&mut self,bytes:&[u8])->PyResult<usize> {
        self.check()?;
        if !self.writable{return Err(file_unsupported("File not open for writing"));}
        loop {
            let result=match self.handle.as_mut().unwrap() {
                FileHandle::Owned(file)=>std::io::Write::write(file,bytes),
                #[cfg(all(unix,target_pointer_width="64"))]
                FileHandle::Descriptor{fd,..}=>{
                    let size=unsafe{file_sys::write(*fd,bytes.as_ptr().cast(),bytes.len())};
                    if size<0{Err(std::io::Error::last_os_error())}else{Ok(size as usize)}
                },
            };
            match result {Err(error) if error.kind()==std::io::ErrorKind::Interrupted=>continue,result=>return result.map_err(file_os_error)}
        }
    }
    fn seek(&mut self,offset:i64,whence:i32)->PyResult<u64> {
        self.check()?;
        let position=match whence {
            0 if offset>=0=>std::io::SeekFrom::Start(offset as u64),
            0=>return Err(file_os_error(std::io::Error::from_raw_os_error(22))),
            1=>std::io::SeekFrom::Current(offset),2=>std::io::SeekFrom::End(offset),
            _=>return Err(pyerr("ValueError","invalid whence")),
        };
        match self.handle.as_mut().unwrap() {
            FileHandle::Owned(file)=>std::io::Seek::seek(file,position).map_err(file_os_error),
            #[cfg(all(unix,target_pointer_width="64"))]
            FileHandle::Descriptor{fd,..}=>{
                let result=unsafe{file_sys::seek(*fd,offset,whence)};
                if result<0{Err(file_os_error(std::io::Error::last_os_error()))}else{Ok(result as u64)}
            },
        }
    }
    fn truncate(&mut self,size:u64)->PyResult<()> {
        self.check()?;
        if !self.writable{return Err(file_unsupported("truncate"));}
        match self.handle.as_mut().unwrap() {
            FileHandle::Owned(file)=>file.set_len(size).map_err(file_os_error),
            #[cfg(all(unix,target_pointer_width="64"))]
            FileHandle::Descriptor{fd,..}=>{
                let size=i64::try_from(size).map_err(|_|pyerr("OverflowError","file size is too large"))?;
                if unsafe{file_sys::truncate(*fd,size)}<0{Err(file_os_error(std::io::Error::last_os_error()))}else{Ok(())}
            },
        }
    }
    fn fileno(&self)->PyResult<i32> {
        self.check()?;
        match self.handle.as_ref().unwrap() {
            FileHandle::Owned(file)=>{
                #[cfg(unix)]{use std::os::fd::AsRawFd;Ok(file.as_raw_fd())}
                #[cfg(not(unix))]{let _=file;Err(file_unsupported("fileno"))}
            },
            #[cfg(all(unix,target_pointer_width="64"))]
            FileHandle::Descriptor{fd,..}=>Ok(*fd),
        }
    }
    fn isatty(&self)->PyResult<bool> {
        self.check()?;
        match self.handle.as_ref().unwrap() {
            FileHandle::Owned(file)=>{use std::io::IsTerminal;Ok(file.is_terminal())},
            #[cfg(all(unix,target_pointer_width="64"))]
            FileHandle::Descriptor{fd,..}=>Ok(unsafe{file_sys::isatty(*fd)}!=0),
        }
    }
    fn close(&mut self)->PyResult<()> {
        let Some(mut handle)=self.handle.take() else{return Ok(())};
        #[cfg(all(unix,target_pointer_width="64"))]
        if let FileHandle::Descriptor{fd,closefd}=&mut handle {
            if *closefd {
                *closefd=false;
                if unsafe{file_sys::close(*fd)}<0{return Err(file_os_error(std::io::Error::last_os_error()));}
            }
        }
        Ok(())
    }
}

#[derive(Debug)]
struct FileBuffer {
    raw:Option<FileRawRef>,input:Vec<u8>,at:usize,output:Vec<u8>,capacity:usize,can_read:bool,can_write:bool,
}
type FileBufferRef=std::rc::Rc<std::cell::RefCell<FileBuffer>>;
impl FileBuffer {
    fn new(raw:FileRawRef,capacity:usize)->Self {
        let (can_read,can_write)={let raw=raw.borrow();(raw.readable,raw.writable)};
        Self{raw:Some(raw),input:Vec::new(),at:0,output:Vec::new(),capacity:capacity.max(1),can_read,can_write}
    }
    fn raw(&self)->PyResult<FileRawRef> {self.raw.clone().ok_or_else(||pyerr("ValueError","raw stream has been detached"))}
    fn check(&self)->PyResult<()> {self.raw()?.borrow().check()}
    fn flush_output(&mut self)->PyResult<()> {
        let raw=self.raw()?;raw.borrow().check()?;
        let mut sent=0;
        while sent<self.output.len() {
            match raw.borrow_mut().write(&self.output[sent..]) {
                Ok(0)=>{self.output.drain(..sent);return Err(pyerr("OSError","write returned zero bytes"));},
                Ok(count)=>sent+=count,
                Err(error)=>{self.output.drain(..sent);return Err(error);},
            }
        }
        self.output.clear();Ok(())
    }
    fn flush(&mut self)->PyResult<()> {
        self.flush_output()?;
        let raw=self.raw()?;
        if self.can_read&&self.can_write{self.rewind_input()?;}
        Ok(())
    }
    fn readable(&self)->PyResult<()> {let raw=self.raw()?;let raw=raw.borrow();raw.check()?;if self.can_read{Ok(())}else{Err(file_unsupported("read"))}}
    fn writable(&self)->PyResult<()> {let raw=self.raw()?;let raw=raw.borrow();raw.check()?;if self.can_write{Ok(())}else{Err(file_unsupported("write"))}}
    fn fill(&mut self)->PyResult<bool> {
        self.fill_sized(self.capacity)
    }
    fn fill_sized(&mut self,size:usize)->PyResult<bool> {
        self.readable()?;self.flush_output()?;
        if self.at<self.input.len(){return Ok(true);}
        self.input.clear();self.at=0;
        self.input.try_reserve(size).map_err(|_|file_memory())?;
        self.input.resize(size,0);
        let result=self.raw()?.borrow_mut().read(&mut self.input);
        match result {Ok(count)=>{self.input.truncate(count);Ok(count!=0)},Err(error)=>{self.input.clear();Err(error)}}
    }
    fn byte(&mut self)->PyResult<Option<u8>> {
        if !self.fill()?{return Ok(None);}
        let byte=self.input[self.at];self.at+=1;Ok(Some(byte))
    }
    fn peek_byte(&mut self)->PyResult<Option<u8>> {Ok(if self.fill()?{Some(self.input[self.at])}else{None})}
    fn read(&mut self,count:Option<usize>,line:bool,once:bool)->PyResult<Vec<u8>> {
        self.readable()?;self.flush_output()?;
        let mut output=Vec::new();
        if count==Some(0){return Ok(output);}
        let mut fetched=false;
        loop {
            if self.at==self.input.len() {
                if once && fetched{break;}
                let available=if once{self.fill_sized(count.unwrap_or(self.capacity))?}else{self.fill()?};
                if !available{break;}
                fetched=true;
            }
            let mut end=self.input.len();
            if let Some(count)=count{end=end.min(self.at.saturating_add(count-output.len()));}
            if line {if let Some(index)=self.input[self.at..end].iter().position(|byte|*byte==b'\n'){end=self.at+index+1;}}
            output.try_reserve(end-self.at).map_err(|_|file_memory())?;
            output.extend_from_slice(&self.input[self.at..end]);self.at=end;
            if (line&&output.last()==Some(&b'\n'))||count==Some(output.len())||once{break;}
        }
        Ok(output)
    }
    fn readinto_bytes(&mut self,size:usize,once:bool)->PyResult<Vec<u8>> {
        self.readable()?;self.flush_output()?;
        let mut output=Vec::new();output.try_reserve(size).map_err(|_|file_memory())?;
        let mut called=false;
        while output.len()<size {
            let available=self.input.len()-self.at;
            if available!=0 {
                let copied=(size-output.len()).min(available);
                output.extend_from_slice(&self.input[self.at..self.at+copied]);self.at+=copied;
                if output.len()==size{break;}
            }
            if once&&called{break;}
            let remaining=size-output.len();
            if remaining>self.capacity {
                let start=output.len();output.resize(size,0);
                let read=self.raw()?.borrow_mut().read(&mut output[start..])?;
                output.truncate(start+read);called=true;
                if read==0{break;}
            } else {
                if once&&!output.is_empty(){break;}
                if !self.fill()?{break;}
                called=true;
            }
        }
        Ok(output)
    }
    fn rewind_input(&mut self)->PyResult<()> {
        let remaining=self.input.len()-self.at;
        if remaining!=0 {
            let offset=i64::try_from(remaining).map_err(|_|pyerr("OverflowError","input buffer is too large"))?;
            self.raw()?.borrow_mut().seek(-offset,1)?;
        }
        self.input.clear();self.at=0;Ok(())
    }
    fn write(&mut self,bytes:&[u8])->PyResult<usize> {
        self.writable()?;self.rewind_input()?;
        self.output.try_reserve(bytes.len()).map_err(|_|file_memory())?;
        self.output.extend_from_slice(bytes);
        if self.output.len()>=self.capacity{self.flush()?;}
        Ok(bytes.len())
    }
    fn tell(&mut self)->PyResult<u64> {
        let position=self.raw()?.borrow_mut().seek(0,1)?;
        let remaining=(self.input.len()-self.at) as u64;
        position.checked_sub(remaining).and_then(|value|value.checked_add(self.output.len() as u64))
            .ok_or_else(||pyerr("OSError","invalid buffered file position"))
    }
    fn seek(&mut self,offset:i64,whence:i32)->PyResult<u64> {
        self.check()?;self.flush()?;
        let corrected=if whence==1 {offset.checked_sub(i64::try_from(self.input.len()-self.at).map_err(|_|pyerr("OverflowError","input buffer is too large"))?)
            .ok_or_else(||pyerr("OverflowError","seek position is too large"))?}else{offset};
        let position=self.raw()?.borrow_mut().seek(corrected,whence)?;
        self.input.clear();self.at=0;Ok(position)
    }
    fn truncate(&mut self,size:u64)->PyResult<()> {self.writable()?;self.flush()?;self.rewind_input()?;self.raw()?.borrow_mut().truncate(size)}
    fn close(&mut self)->PyResult<()> {
        let raw=self.raw()?;
        if raw.borrow().handle.is_none(){return Ok(());}
        let flushed=self.flush();let closed=raw.borrow_mut().close();flushed.and(closed)
    }
}
impl Drop for FileBuffer {
    fn drop(&mut self){if self.raw.is_some(){let _=self.flush();}}
}
