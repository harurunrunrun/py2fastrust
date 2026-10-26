// Included only when the compiler proves dynamic compilation unreachable.
// The signatures keep the common built-in dispatcher independent of pruning.
fn compile_dynamic(
    _source: &str,
    _filename: &str,
    _mode: &str,
    _code_offset: usize,
    _future_flags: u32,
) -> Result<Vec<Code>, String> {
    Err("RuntimeError: unreachable dynamic compilation".to_owned())
}
fn compile_dynamic_optimized(
    source: &str,
    filename: &str,
    mode: &str,
    code_offset: usize,
    future_flags: u32,
    _optimize: u8,
) -> Result<Vec<Code>, String> {
    compile_dynamic(source, filename, mode, code_offset, future_flags)
}
