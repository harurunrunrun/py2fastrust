"""Process-local target hash secret, independent of the compiler host."""

RUNTIME=r'''
static NATIVE_CP_PROGRAM_SECRET:std::sync::OnceLock<NativeCPHashSecret>=std::sync::OnceLock::new();
fn native_cp_parse_seed(text:&str)->Result<Option<u32>,String>{
    let invalid=||"Fatal Python error: config_init_hash_seed: PYTHONHASHSEED must be \"random\" or an integer in range [0; 4294967295]\nPython runtime state: preinitialized\n".to_owned();
    if text.is_empty()||text=="random"{return Ok(None);}
    let value=text.trim_start_matches(|character:char|matches!(character,' '| '\t'|'\n'|'\r'|'\x0b'|'\x0c'));
    let (negative,digits)=if let Some(value)=value.strip_prefix('-'){(true,value)}else{(false,value.strip_prefix('+').unwrap_or(value))};
    if digits.is_empty()||!digits.bytes().all(|byte|byte.is_ascii_digit()){return Err(invalid());}
    let mut number=0u64;
    for byte in digits.bytes(){number=number.checked_mul(10).and_then(|value|value.checked_add((byte-b'0')as u64)).ok_or_else(invalid)?;}
    if negative{number=number.wrapping_neg();}
    Ok(Some(u32::try_from(number).map_err(|_|invalid())?))
}
fn native_cp_entropy_secret()->NativeCPHashSecret{
    use std::io::Read as _;
    let mut bytes=[0u8;16];
    if std::fs::File::open("/dev/urandom").and_then(|mut input|input.read_exact(&mut bytes)).is_ok(){
        return NativeCPHashSecret{key0:u64::from_le_bytes(bytes[..8].try_into().unwrap()),key1:u64::from_le_bytes(bytes[8..].try_into().unwrap())};
    }
    let source=std::collections::hash_map::RandomState::new();
    NativeCPHashSecret{key0:std::hash::BuildHasher::hash_one(&source,0u8),key1:std::hash::BuildHasher::hash_one(&source,1u8)}
}
fn native_cp_initialize_secret()->Result<(),String>{
    if NATIVE_CP_PROGRAM_SECRET.get().is_some(){return Ok(());}
    let secret=match std::env::var_os("PYTHONHASHSEED"){
        None=>native_cp_entropy_secret(),
        Some(value)=>{
            let text=value.to_str().ok_or_else(||"Fatal Python error: config_init_hash_seed: PYTHONHASHSEED must be \"random\" or an integer in range [0; 4294967295]\nPython runtime state: preinitialized\n".to_owned())?;
            match native_cp_parse_seed(text)?{Some(seed)=>NativeCPHashSecret::from_seed(seed),None=>native_cp_entropy_secret()}
        },
    };
    let _=NATIVE_CP_PROGRAM_SECRET.set(secret);Ok(())
}
fn native_cp_program_secret()->NativeCPHashSecret{*NATIVE_CP_PROGRAM_SECRET.get().expect("CP hash secret initialized at generated entry")}
'''
