"""Seeded table hashing; Python-visible hash and insertion order stay separate."""

HELPERS = r'''
#[derive(Clone)]
struct NativeKeyBuildHasher{seed:u64}
impl Default for NativeKeyBuildHasher{
    fn default()->Self{
        let source=std::collections::hash_map::RandomState::new();
        Self{seed:std::hash::BuildHasher::hash_one(&source,0_u8)}
    }
}
struct NativeKeyHasher{state:u64}
impl std::hash::BuildHasher for NativeKeyBuildHasher{
    type Hasher=NativeKeyHasher;
    fn build_hasher(&self)->NativeKeyHasher{NativeKeyHasher{state:self.seed}}
}
impl NativeKeyHasher{
    #[inline]
    fn absorb(&mut self,value:u64){
        let product=((self.state^value)as u128)*0xa0761d6478bd642f_u128;
        self.state=(product as u64)^((product>>64)as u64);
    }
}
impl std::hash::Hasher for NativeKeyHasher{
    #[inline]fn finish(&self)->u64{self.state}
    fn write(&mut self,bytes:&[u8]){
        self.absorb(bytes.len()as u64);
        let mut chunks=bytes.chunks_exact(8);
        for chunk in &mut chunks{
            self.absorb(u64::from_ne_bytes(chunk.try_into().unwrap()));
        }
        let tail=chunks.remainder();
        if !tail.is_empty(){
            let mut word=[0_u8;8];word[..tail.len()].copy_from_slice(tail);
            self.absorb(u64::from_ne_bytes(word));
        }
    }
    #[inline]fn write_u8(&mut self,value:u8){self.absorb(value as u64)}
    #[inline]fn write_u16(&mut self,value:u16){self.absorb(value as u64)}
    #[inline]fn write_u32(&mut self,value:u32){self.absorb(value as u64)}
    #[inline]fn write_u64(&mut self,value:u64){self.absorb(value)}
    #[inline]fn write_u128(&mut self,value:u128){self.absorb(value as u64);self.absorb((value>>64)as u64)}
    #[inline]fn write_usize(&mut self,value:usize){self.absorb(value as u64)}
    #[inline]fn write_i8(&mut self,value:i8){self.absorb(value as u64)}
    #[inline]fn write_i16(&mut self,value:i16){self.absorb(value as u64)}
    #[inline]fn write_i32(&mut self,value:i32){self.absorb(value as u64)}
    #[inline]fn write_i64(&mut self,value:i64){self.absorb(value as u64)}
    #[inline]fn write_i128(&mut self,value:i128){self.write_u128(value as u128)}
    #[inline]fn write_isize(&mut self,value:isize){self.absorb(value as u64)}
}
'''
