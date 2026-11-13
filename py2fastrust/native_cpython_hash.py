"""Callback-free CPython 3.14.4 hashes for the explicit 64-bit LE target.

The registered typed CP-set backend selects these helpers through proved
source-key and process hash-seed adapters. Dictionary storage and ordinary
native-set hashing remain separate.

Algorithm references: CPython v3.14.4 Python/pyhash.c,
Python/bootstrap_hash.c, Objects/longobject.c, Objects/tupleobject.c,
Include/internal/pycore_tuple.h and Objects/unicodeobject.c (PSF license).
The SipHash adaptation also retains the upstream MIT notice below. Generated
outputs retain the relevant PSF and SipHash notices only for retained helpers.
"""

SIPHASH_NOTICE = '''Copyright (c) 2013 Marek Majkowski <marek@popcount.org>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
'''

RUNTIME = r'''
#[derive(Clone,Copy)]
struct NativeCPHashSecret { key0:u64,key1:u64 }
impl NativeCPHashSecret {
    fn from_seed(seed:u32)->Self {
        let mut bytes=[0u8;24];
        if seed!=0 {
            let mut state=seed;
            for byte in &mut bytes {
                state=state.wrapping_mul(214013).wrapping_add(2531011);
                *byte=(state>>16)as u8;
            }
        }
        Self {key0:u64::from_le_bytes(bytes[..8].try_into().unwrap()),key1:u64::from_le_bytes(bytes[8..16].try_into().unwrap())}
    }
}
fn native_cp_hash_finish(value:u64)->i64 {
    if value==u64::MAX {-2} else {value as i64}
}
fn native_cp_hash_integer(value:i128)->i64 {
    let magnitude=(value.unsigned_abs()%2305843009213693951u128)as i64;
    let result=if value<0 {-magnitude}else{magnitude};
    if result==-1 {-2}else{result}
}
fn native_cp_hash_digits(negative:bool,digits:&[u32])->i64 {
    let mut value=0u128;
    for &digit in digits.iter().rev() {
        value=((value<<32)+digit as u128)%2305843009213693951u128;
    }
    let result=if negative {-(value as i64)}else{value as i64};
    if result==-1 {-2}else{result}
}
fn native_cp_hash_none()->i64 {0xfca86420}
fn native_cp_hash_tuple(lanes:impl IntoIterator<Item=i64>)->i64 {
    let mut accumulator=2870177450012600261u64;
    let mut length=0u64;
    for lane in lanes {
        accumulator=accumulator.wrapping_add((lane as u64).wrapping_mul(14029467366897019727));
        accumulator=accumulator.rotate_left(31).wrapping_mul(11400714785074694791);
        length=length.wrapping_add(1);
    }
    accumulator=accumulator.wrapping_add(length^(2870177450012600261u64^3527539));
    if accumulator==u64::MAX {1546275796}else{accumulator as i64}
}
fn native_cp_sip_round(state:&mut [u64;4]) {
    state[0]=state[0].wrapping_add(state[1]);state[1]=state[1].rotate_left(13);state[1]^=state[0];state[0]=state[0].rotate_left(32);
    state[2]=state[2].wrapping_add(state[3]);state[3]=state[3].rotate_left(16);state[3]^=state[2];
    state[0]=state[0].wrapping_add(state[3]);state[3]=state[3].rotate_left(21);state[3]^=state[0];
    state[2]=state[2].wrapping_add(state[1]);state[1]=state[1].rotate_left(17);state[1]^=state[2];state[2]=state[2].rotate_left(32);
}
fn native_cp_hash_bytes(value:&[u8],secret:NativeCPHashSecret)->i64 {
    if value.is_empty(){return 0;}
    let mut state=[secret.key0^0x736f6d6570736575,secret.key1^0x646f72616e646f6d,secret.key0^0x6c7967656e657261,secret.key1^0x7465646279746573];
    let mut chunks=value.chunks_exact(8);
    for chunk in &mut chunks {
        let message=u64::from_le_bytes(chunk.try_into().unwrap());
        state[3]^=message;native_cp_sip_round(&mut state);state[0]^=message;
    }
    let mut last=(value.len()as u64).wrapping_shl(56);
    for (index,&byte)in chunks.remainder().iter().enumerate(){last|=(byte as u64)<<(index*8);}
    state[3]^=last;native_cp_sip_round(&mut state);state[0]^=last;state[2]^=0xff;
    for _ in 0..3 {native_cp_sip_round(&mut state);}
    native_cp_hash_finish(state[0]^state[1]^state[2]^state[3])
}
fn native_cp_hash_text(value:&str,secret:NativeCPHashSecret)->i64 {
    if value.is_ascii(){return native_cp_hash_bytes(value.as_bytes(),secret);}
    let maximum=value.chars().map(|character|character as u32).max().unwrap_or(0);
    let bytes:Vec<u8>=if maximum<=255 {
        value.chars().map(|character|character as u8).collect()
    }else if maximum<=65535 {
        value.chars().flat_map(|character|(character as u16).to_le_bytes()).collect()
    }else{
        value.chars().flat_map(|character|(character as u32).to_le_bytes()).collect()
    };
    native_cp_hash_bytes(&bytes,secret)
}
'''

# Binary decomposition implements the numeric rational hash modulo 2**61-1.
# The NaN object-pointer case is handled separately by the key identity layer.
FLOAT_HASH = r'''
fn native_cp_hash_float(value:f64)->i64{
    debug_assert!(!value.is_nan());
    if value.is_infinite(){return if value.is_sign_negative(){-314159}else{314159};}
    let bits=value.to_bits();let exponent=((bits>>52)&2047)as i32;
    let mantissa=(bits&((1u64<<52)-1))|if exponent==0{0}else{1u64<<52};
    let power=if exponent==0{-1074}else{exponent-1023-52};
    let shift=power.rem_euclid(61)as u32;
    let magnitude=((mantissa.wrapping_shl(shift)&2305843009213693951)|(mantissa>>(61-shift)))as i64;
    let hash=if value.is_sign_negative(){-magnitude}else{magnitude};
    if hash==-1{-2}else{hash}
}
'''
