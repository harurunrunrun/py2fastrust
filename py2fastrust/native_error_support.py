"""Shared native error transport; detailed state is allocated on failure only."""

RUNTIME = r'''
#[derive(Debug,Clone)]
struct NativeError(Box<NativeErrorData>);
#[derive(Debug,Clone)]
struct NativeErrorData { message: String, line: usize, function: &'static str, frames: Vec<(usize, &'static str)> }
impl std::ops::Deref for NativeError {
    type Target=NativeErrorData;
    fn deref(&self)->&NativeErrorData {&self.0}
}
impl std::ops::DerefMut for NativeError {
    fn deref_mut(&mut self)->&mut NativeErrorData {&mut self.0}
}
#[cold]
fn native_error(message:String,line:usize,function: &'static str)->NativeError {
    NativeError(Box::new(NativeErrorData {message,line,function,frames:Vec::new()}))
}
fn native_at<T>(result: Result<T, String>, line: usize, function: &'static str) -> Result<T, NativeError> {
    result.map_err(|message| native_error(message,line,function))
}
'''
