"""Private-to-the-backends, typed CPython 3.14.4 set-table kernel.

The compiler does not activate this storage yet.  Hashes are explicit CPython
hash values; C is the callback-free equality representation and K retains the
original Python key.  Dict storage and observable-order guards are unchanged.
The table/probing/merge/iterator algorithms follow Objects/setobject.c in
CPython v3.14.4, distributed under the PSF license.
"""

RUNTIME = r'''
enum NativeCPSetSlot<K,C> {
    Unused,
    Dummy,
    Active {key:K,canonical:C,hash:i64},
}
enum NativeCPSetTable<K,C> {
    Small([NativeCPSetSlot<K,C>;8]),
    Large(Vec<NativeCPSetSlot<K,C>>),
}
impl<K,C> NativeCPSetTable<K,C> {
    fn empty()->Self {Self::Small(std::array::from_fn(|_|NativeCPSetSlot::Unused))}
    fn as_slice(&self)->&[NativeCPSetSlot<K,C>] {
        match self {Self::Small(slots)=>slots,Self::Large(slots)=>slots}
    }
    fn as_mut_slice(&mut self)->&mut [NativeCPSetSlot<K,C>] {
        match self {Self::Small(slots)=>slots,Self::Large(slots)=>slots}
    }
}
struct NativeCPSet<K,C> {
    table:NativeCPSetTable<K,C>,fill:usize,used:usize,finger:usize,
}
impl<K,C:Eq> NativeCPSet<K,C> {
    fn new()->Self {Self {table:NativeCPSetTable::empty(),fill:0,used:0,finger:0}}
    fn len(&self)->usize {self.used}
    fn is_empty(&self)->bool {self.used==0}
    fn capacity(&self)->usize {self.table.as_slice().len()}
    fn entries(&self)->impl Iterator<Item=(&K,&C,i64)> {
        self.table.as_slice().iter().filter_map(|slot|match slot {
            NativeCPSetSlot::Active{key,canonical,hash}=>Some((key,canonical,*hash)),_=>None,
        })
    }
    fn locate(&self,canonical:&C,hash:i64)->(usize,bool,bool) {
        let slots=self.table.as_slice();let mask=slots.len()-1;
        let mut index=hash as u64 as usize&mask;let mut perturb=hash as u64;let mut dummy=None;
        loop {
            let probes=if index+9<=mask {9}else{0};
            for offset in 0..=probes {
                let position=index+offset;
                match &slots[position] {
                    NativeCPSetSlot::Unused=>return (dummy.unwrap_or(position),false,dummy.is_none()),
                    NativeCPSetSlot::Dummy=>dummy=Some(position),
                    NativeCPSetSlot::Active{canonical:stored,hash:stored_hash,..}=>{
                        if *stored_hash==hash&&stored==canonical {return(position,true,false);}
                    },
                }
            }
            perturb>>=5;index=index.wrapping_mul(5).wrapping_add(1).wrapping_add(perturb as usize)&mask;
        }
    }
    fn insert_clean(&mut self,key:K,canonical:C,hash:i64) {
        let slots=self.table.as_mut_slice();let mask=slots.len()-1;
        let mut index=hash as u64 as usize&mask;let mut perturb=hash as u64;
        loop {
            let probes=if index+9<=mask {9}else{0};
            for offset in 0..=probes {
                if matches!(&slots[index+offset],NativeCPSetSlot::Unused) {
                    slots[index+offset]=NativeCPSetSlot::Active{key,canonical,hash};return;
                }
            }
            perturb>>=5;index=index.wrapping_mul(5).wrapping_add(1).wrapping_add(perturb as usize)&mask;
        }
    }
    fn resize(&mut self,minused:usize)->Result<(),String> {
        let mut size=8usize;
        while size<=minused {size=size.checked_mul(2).ok_or_else(||"MemoryError".to_owned())?;}
        if size>isize::MAX as usize {return Err("MemoryError".to_owned());}
        if size==8&&self.capacity()==8&&self.fill==self.used {return Ok(());}
        let table=if size==8 {NativeCPSetTable::empty()}else{
            let mut slots=Vec::new();slots.try_reserve_exact(size).map_err(|_|"MemoryError".to_owned())?;
            slots.resize_with(size,||NativeCPSetSlot::Unused);NativeCPSetTable::Large(slots)
        };
        let old=std::mem::replace(&mut self.table,table);self.fill=self.used;
        match old {
            NativeCPSetTable::Small(slots)=>{
                for slot in slots {if let NativeCPSetSlot::Active{key,canonical,hash}=slot {self.insert_clean(key,canonical,hash);}}
            },
            NativeCPSetTable::Large(slots)=>{
                for slot in slots {if let NativeCPSetSlot::Active{key,canonical,hash}=slot {self.insert_clean(key,canonical,hash);}}
            },
        }
        Ok(())
    }
    fn add(&mut self,key:K,canonical:C,hash:i64)->Result<bool,String> {
        assert_ne!(hash,-1);
        let (position,present,unused)=self.locate(&canonical,hash);
        if present {return Ok(false);}
        self.table.as_mut_slice()[position]=NativeCPSetSlot::Active{key,canonical,hash};self.used+=1;
        if unused {
            self.fill+=1;
            if (self.fill as u128)*5>=((self.capacity()-1)as u128)*3 {
                let multiple=if self.used>50000 {2}else{4};
                self.resize(self.used.checked_mul(multiple).ok_or_else(||"MemoryError".to_owned())?)?;
            }
        }
        Ok(true)
    }
    fn contains(&self,canonical:&C,hash:i64)->bool {self.locate(canonical,hash).1}
    fn discard(&mut self,canonical:&C,hash:i64)->bool {
        let (position,present,_)=self.locate(canonical,hash);
        if !present {return false;}
        self.table.as_mut_slice()[position]=NativeCPSetSlot::Dummy;self.used-=1;true
    }
    fn clear(&mut self) {self.table=NativeCPSetTable::empty();self.fill=0;self.used=0;}
    fn pop(&mut self)->Result<K,String> {
        if self.used==0 {return Err("KeyError: 'pop from an empty set'".to_owned());}
        let mask=self.capacity()-1;let mut position=self.finger&mask;
        loop {
            if matches!(&self.table.as_slice()[position],NativeCPSetSlot::Active{..}) {break;}
            position=(position+1)&mask;
        }
        let old=std::mem::replace(&mut self.table.as_mut_slice()[position],NativeCPSetSlot::Dummy);
        self.used-=1;self.finger=position+1;
        match old {NativeCPSetSlot::Active{key,..}=>Ok(key),_=>unreachable!()}
    }
    fn prepare_dict_update(&mut self,length:usize)->Result<(),String> {
        if (self.fill as u128+length as u128)*5>=((self.capacity()-1)as u128)*3 {
            let minused=self.used.checked_add(length).and_then(|value|value.checked_mul(2)).ok_or_else(||"MemoryError".to_owned())?;
            self.resize(minused)?;
        }
        Ok(())
    }
    fn merge(&mut self,other:&Self)->Result<(),String> where K:Clone,C:Clone {
        if std::ptr::eq(self,other){return Ok(());}
        self.merge_projected(other,|key,canonical|(key.clone(),canonical.clone()))
    }
    fn merge_projected<K2,C2:Eq,F>(&mut self,other:&NativeCPSet<K2,C2>,mut convert:F)->Result<(),String>
    where F:FnMut(&K2,&C2)->(K,C) {
        if other.used==0 {return Ok(());}
        self.prepare_dict_update(other.used)?;
        if self.fill==0&&self.capacity()==other.capacity()&&other.fill==other.used {
            for (destination,source)in self.table.as_mut_slice().iter_mut().zip(other.table.as_slice()) {
                if let NativeCPSetSlot::Active{key,canonical,hash}=source {
                    let (key,canonical)=convert(key,canonical);
                    *destination=NativeCPSetSlot::Active{key,canonical,hash:*hash};
                }
            }
            self.fill=other.fill;self.used=other.used;return Ok(());
        }
        if self.fill==0 {
            self.fill=other.used;self.used=other.used;
            for (key,canonical,hash)in other.entries(){let(key,canonical)=convert(key,canonical);self.insert_clean(key,canonical,hash);}
        }else{
            for (key,canonical,hash)in other.entries(){let(key,canonical)=convert(key,canonical);self.add(key,canonical,hash)?;}
        }
        Ok(())
    }
    fn copy_set(&self)->Result<Self,String> where K:Clone,C:Clone {
        let mut result=Self::new();result.merge(self)?;Ok(result)
    }
}
struct NativeCPSetCursor<K,C> {
    owner:Option<std::rc::Rc<std::cell::RefCell<NativeCPSet<K,C>>>>,
    expected:usize,position:usize,remaining:i64,failed:bool,
}
impl<K:Clone,C:Eq> NativeCPSetCursor<K,C> {
    fn new(owner:std::rc::Rc<std::cell::RefCell<NativeCPSet<K,C>>>)->Self {
        let length=owner.borrow().len();
        Self {owner:Some(owner),expected:length,position:0,remaining:length as i64,failed:false}
    }
    fn length_hint(&self)->i64 {
        if let Some(owner)=&self.owner {
            if !self.failed&&owner.borrow().len()==self.expected{return self.remaining;}
        }
        0
    }
    fn next(&mut self)->Result<Option<K>,String> {
        let Some(owner)=&self.owner else{return Ok(None);};let read=owner.borrow();
        if self.failed||read.len()!=self.expected {
            self.failed=true;return Err("RuntimeError: Set changed size during iteration".to_owned());
        }
        while self.position<read.capacity() {
            let position=self.position;self.position+=1;
            if let NativeCPSetSlot::Active{key,..}=&read.table.as_slice()[position] {
                self.remaining-=1;return Ok(Some(key.clone()));
            }
        }
        drop(read);self.owner=None;Ok(None)
    }
}
'''
