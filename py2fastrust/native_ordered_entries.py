"""Typed insertion-order storage with reusable slots for dictionary deletion."""

DENSE_HELPERS=r'''
type NativeDictionaryEntries<T>=Vec<T>;
fn native_dict_insert<T>(entries:&mut NativeDictionaryEntries<T>,value:T)->Result<usize,String>{
    let index=entries.len();
    index.checked_add(1).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"MemoryError: dictionary is too large".to_owned())?;
    entries.try_reserve(1).map_err(|_|"MemoryError: cannot allocate dictionary entries".to_owned())?;
    entries.push(value);Ok(index)
}
fn native_dict_remove<T,C,S>(entries:&mut NativeDictionaryEntries<T>,index:&mut std::collections::HashMap<C,usize,S>,slot:usize)->T{
    let value=entries.remove(slot);
    for offset in index.values_mut(){if *offset>slot{*offset-=1;}}
    value
}
'''

POSITIONED_HELPERS=r'''
const NATIVE_ENTRY_NONE:usize=usize::MAX;
#[derive(Clone)]
struct NativeEntrySlot<T>{value:Option<T>,previous:usize,next:usize,position:usize}
#[derive(Clone)]
struct NativeOrderedEntries<T>{slots:Vec<NativeEntrySlot<T>>,head:usize,tail:usize,free:usize,length:usize,positions:Vec<usize>,table_size:usize,usable:usize}
type NativeDictionaryEntries<T>=NativeOrderedEntries<T>;
impl<T> NativeOrderedEntries<T>{
    fn new()->Self{Self{slots:Vec::new(),head:NATIVE_ENTRY_NONE,tail:NATIVE_ENTRY_NONE,free:NATIVE_ENTRY_NONE,length:0,positions:Vec::new(),table_size:0,usable:0}}
    fn len(&self)->usize{self.length}
    fn is_empty(&self)->bool{self.length==0}
    fn pop(&mut self)->Option<T>{let slot=self.tail;if slot==NATIVE_ENTRY_NONE{None}else{let position=self.slots[slot].position;let value=self.remove(slot);self.positions.truncate(position);Some(value)}}
    fn clear(&mut self){self.slots.clear();self.head=NATIVE_ENTRY_NONE;self.tail=NATIVE_ENTRY_NONE;self.free=NATIVE_ENTRY_NONE;self.length=0;self.positions.clear();self.table_size=0;self.usable=0;}
    fn position_size(minimum:usize)->Result<usize,String>{minimum.max(8).checked_next_power_of_two().ok_or_else(||"MemoryError: dictionary is too large".to_owned())}
    fn estimated_size(used:usize)->Result<usize,String>{Self::position_size(used.checked_mul(3).and_then(|value|value.checked_add(1)).map(|value|value/2).ok_or_else(||"MemoryError: dictionary is too large".to_owned())?)}
    fn compact_positions(&mut self,size:usize)->Result<(),String>{
        let mut positions=Vec::new();positions.try_reserve(self.length).map_err(|_|"MemoryError: dictionary positions".to_owned())?;
        let mut slot=self.head;while slot!=NATIVE_ENTRY_NONE{self.slots[slot].position=positions.len();positions.push(slot);slot=self.slots[slot].next;}
        self.positions=positions;self.table_size=size;self.usable=(size/3*2+(size%3)*2/3)-self.length;Ok(())
    }
    fn presize_literal(&mut self,count:usize)->Result<(),String>{
        if count>5{let size=Self::estimated_size(count.min(87381))?;self.compact_positions(size)?;}Ok(())
    }
    fn mapping_seed(&self)->(usize,usize,usize,usize){(self.length,self.positions.len(),self.table_size,self.usable)}
    fn prepare_mapping_info(&mut self,source:(usize,usize,usize,usize))->Result<(),String>{
        let(used,entries,size,usable)=source;if used==0{return Ok(());}
        let half=size/2;let half_capacity=half/3*2+(half%3)*2/3;
        if self.length==0&&used==entries&&(size==8||half_capacity<used){self.positions.clear();self.table_size=size;self.usable=usable.checked_add(used).ok_or_else(||"MemoryError: dictionary positions".to_owned())?;}
        else if self.table_size/3*2+(self.table_size%3)*2/3<used{self.compact_positions(Self::estimated_size(self.length.checked_add(used).ok_or_else(||"MemoryError: dictionary positions".to_owned())?)?)?;}Ok(())
    }
    fn prepare_mapping_seed<U>(&mut self,source:&NativeOrderedEntries<U>)->Result<(),String>{
        self.prepare_mapping_info(source.mapping_seed())
    }
    fn prepare_keywords(&mut self,count:usize)->Result<(),String>{
        if count==0{return Ok(());}
        let mut size=Self::estimated_size(count.min(87381))?;
        while size/3*2+(size%3)*2/3<count{let used=size/3*2+(size%3)*2/3;size=Self::position_size(used.checked_mul(3).ok_or_else(||"MemoryError: dictionary positions".to_owned())?)?;}
        let usable=size/3*2+(size%3)*2/3-count;
        self.prepare_mapping_info((count,count,size,usable))
    }
    fn prepare_python_copy(&mut self)->Result<(),String>{
        if self.length==0{self.clear();return Ok(());}
        if self.length<self.positions.len()/3*2+(self.positions.len()%3)*2/3{self.compact_positions(Self::estimated_size(self.length)?)?;}Ok(())
    }
    fn prepare_constructor_copy(&mut self)->Result<(),String>{
        if self.length==0{self.clear();return Ok(());}
        let half=self.table_size/2;let half_capacity=half/3*2+(half%3)*2/3;
        if self.length!=self.positions.len()||self.table_size!=8&&half_capacity>=self.length{self.compact_positions(Self::estimated_size(self.length)?)?;}Ok(())
    }
    fn insert(&mut self,value:T)->Result<usize,String>{
        let length=self.length.checked_add(1).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"MemoryError: dictionary is too large".to_owned())?;
        if self.usable==0{let minimum=self.length.checked_mul(3).ok_or_else(||"MemoryError: dictionary is too large".to_owned())?;self.compact_positions(Self::position_size(minimum)?)?;}
        self.positions.try_reserve(1).map_err(|_|"MemoryError: dictionary positions".to_owned())?;
        let position=self.positions.len();
        let slot=if self.free==NATIVE_ENTRY_NONE{
            self.slots.try_reserve(1).map_err(|_|"MemoryError: cannot allocate dictionary entries".to_owned())?;
            let slot=self.slots.len();
            self.slots.push(NativeEntrySlot{value:Some(value),previous:self.tail,next:NATIVE_ENTRY_NONE,position});slot
        }else{
            let slot=self.free;self.free=self.slots[slot].next;
            self.slots[slot]=NativeEntrySlot{value:Some(value),previous:self.tail,next:NATIVE_ENTRY_NONE,position};slot
        };
        if self.tail==NATIVE_ENTRY_NONE{self.head=slot;}else{self.slots[self.tail].next=slot;}
        self.tail=slot;self.length=length;self.positions.push(slot);self.usable-=1;Ok(slot)
    }
    fn remove(&mut self,slot:usize)->T{
        let previous=self.slots[slot].previous;let next=self.slots[slot].next;
        if previous==NATIVE_ENTRY_NONE{self.head=next;}else{self.slots[previous].next=next;}
        if next==NATIVE_ENTRY_NONE{self.tail=previous;}else{self.slots[next].previous=previous;}
        let value=self.slots[slot].value.take().expect("live dictionary slot");
        self.positions[self.slots[slot].position]=NATIVE_ENTRY_NONE;
        self.slots[slot].previous=NATIVE_ENTRY_NONE;self.slots[slot].next=self.free;self.free=slot;self.length-=1;value
    }
    fn iter(&self)->NativeOrderedIter<'_,T>{NativeOrderedIter{entries:self,head:self.head,tail:self.tail,remaining:self.length}}
}
impl<T> std::ops::Index<usize> for NativeOrderedEntries<T>{
    type Output=T;
    fn index(&self,slot:usize)->&T{self.slots[slot].value.as_ref().expect("live dictionary slot")}
}
impl<T> std::ops::IndexMut<usize> for NativeOrderedEntries<T>{
    fn index_mut(&mut self,slot:usize)->&mut T{self.slots[slot].value.as_mut().expect("live dictionary slot")}
}
struct NativeOrderedIter<'a,T>{entries:&'a NativeOrderedEntries<T>,head:usize,tail:usize,remaining:usize}
impl<'a,T> Iterator for NativeOrderedIter<'a,T>{
    type Item=&'a T;
    fn next(&mut self)->Option<Self::Item>{
        if self.remaining==0{return None;}
        let slot=self.head;self.head=self.entries.slots[slot].next;self.remaining-=1;Some(&self.entries[slot])
    }
    fn size_hint(&self)->(usize,Option<usize>){(self.remaining,Some(self.remaining))}
}
impl<'a,T> DoubleEndedIterator for NativeOrderedIter<'a,T>{
    fn next_back(&mut self)->Option<Self::Item>{
        if self.remaining==0{return None;}
        let slot=self.tail;self.tail=self.entries.slots[slot].previous;self.remaining-=1;Some(&self.entries[slot])
    }
}
impl<T> ExactSizeIterator for NativeOrderedIter<'_,T>{}
impl<T> std::iter::FusedIterator for NativeOrderedIter<'_,T>{}
struct NativeOrderedIntoIter<T>{entries:NativeOrderedEntries<T>}
impl<T> Iterator for NativeOrderedIntoIter<T>{
    type Item=T;
    fn next(&mut self)->Option<T>{let slot=self.entries.head;if slot==NATIVE_ENTRY_NONE{None}else{Some(self.entries.remove(slot))}}
    fn size_hint(&self)->(usize,Option<usize>){(self.entries.length,Some(self.entries.length))}
}
impl<T> DoubleEndedIterator for NativeOrderedIntoIter<T>{
    fn next_back(&mut self)->Option<T>{let slot=self.entries.tail;if slot==NATIVE_ENTRY_NONE{None}else{Some(self.entries.remove(slot))}}
}
impl<T> ExactSizeIterator for NativeOrderedIntoIter<T>{}
impl<T> std::iter::FusedIterator for NativeOrderedIntoIter<T>{}
impl<T> IntoIterator for NativeOrderedEntries<T>{
    type Item=T;type IntoIter=NativeOrderedIntoIter<T>;
    fn into_iter(self)->Self::IntoIter{NativeOrderedIntoIter{entries:self}}
}
fn native_dict_insert<T>(entries:&mut NativeDictionaryEntries<T>,value:T)->Result<usize,String>{entries.insert(value)}
fn native_dict_remove<T,C,S>(entries:&mut NativeDictionaryEntries<T>,_index:&mut std::collections::HashMap<C,usize,S>,slot:usize)->T{entries.remove(slot)}
'''


ORDERED_HELPERS=r'''
const NATIVE_ENTRY_NONE:usize=usize::MAX;
#[derive(Clone)]
struct NativeEntrySlot<T>{value:Option<T>,previous:usize,next:usize}
#[derive(Clone)]
struct NativeOrderedEntries<T>{slots:Vec<NativeEntrySlot<T>>,head:usize,tail:usize,free:usize,length:usize}
type NativeDictionaryEntries<T>=NativeOrderedEntries<T>;
impl<T> NativeOrderedEntries<T>{
    fn new()->Self{Self{slots:Vec::new(),head:NATIVE_ENTRY_NONE,tail:NATIVE_ENTRY_NONE,free:NATIVE_ENTRY_NONE,length:0}}
    fn len(&self)->usize{self.length}
    fn is_empty(&self)->bool{self.length==0}
    fn pop(&mut self)->Option<T>{let slot=self.tail;if slot==NATIVE_ENTRY_NONE{None}else{Some(self.remove(slot))}}
    fn clear(&mut self){self.slots.clear();self.head=NATIVE_ENTRY_NONE;self.tail=NATIVE_ENTRY_NONE;self.free=NATIVE_ENTRY_NONE;self.length=0;}
    fn insert(&mut self,value:T)->Result<usize,String>{
        let length=self.length.checked_add(1).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"MemoryError: dictionary is too large".to_owned())?;
        let slot=if self.free==NATIVE_ENTRY_NONE{
            self.slots.try_reserve(1).map_err(|_|"MemoryError: cannot allocate dictionary entries".to_owned())?;
            let slot=self.slots.len();
            self.slots.push(NativeEntrySlot{value:Some(value),previous:self.tail,next:NATIVE_ENTRY_NONE});slot
        }else{
            let slot=self.free;self.free=self.slots[slot].next;
            self.slots[slot]=NativeEntrySlot{value:Some(value),previous:self.tail,next:NATIVE_ENTRY_NONE};slot
        };
        if self.tail==NATIVE_ENTRY_NONE{self.head=slot;}else{self.slots[self.tail].next=slot;}
        self.tail=slot;self.length=length;Ok(slot)
    }
    fn remove(&mut self,slot:usize)->T{
        let previous=self.slots[slot].previous;let next=self.slots[slot].next;
        if previous==NATIVE_ENTRY_NONE{self.head=next;}else{self.slots[previous].next=next;}
        if next==NATIVE_ENTRY_NONE{self.tail=previous;}else{self.slots[next].previous=previous;}
        let value=self.slots[slot].value.take().expect("live dictionary slot");
        self.slots[slot].previous=NATIVE_ENTRY_NONE;self.slots[slot].next=self.free;self.free=slot;self.length-=1;value
    }
    fn iter(&self)->NativeOrderedIter<'_,T>{NativeOrderedIter{entries:self,head:self.head,tail:self.tail,remaining:self.length}}
}
impl<T> std::ops::Index<usize> for NativeOrderedEntries<T>{
    type Output=T;
    fn index(&self,slot:usize)->&T{self.slots[slot].value.as_ref().expect("live dictionary slot")}
}
impl<T> std::ops::IndexMut<usize> for NativeOrderedEntries<T>{
    fn index_mut(&mut self,slot:usize)->&mut T{self.slots[slot].value.as_mut().expect("live dictionary slot")}
}
struct NativeOrderedIter<'a,T>{entries:&'a NativeOrderedEntries<T>,head:usize,tail:usize,remaining:usize}
impl<'a,T> Iterator for NativeOrderedIter<'a,T>{
    type Item=&'a T;
    fn next(&mut self)->Option<Self::Item>{
        if self.remaining==0{return None;}
        let slot=self.head;self.head=self.entries.slots[slot].next;self.remaining-=1;Some(&self.entries[slot])
    }
    fn size_hint(&self)->(usize,Option<usize>){(self.remaining,Some(self.remaining))}
}
impl<'a,T> DoubleEndedIterator for NativeOrderedIter<'a,T>{
    fn next_back(&mut self)->Option<Self::Item>{
        if self.remaining==0{return None;}
        let slot=self.tail;self.tail=self.entries.slots[slot].previous;self.remaining-=1;Some(&self.entries[slot])
    }
}
impl<T> ExactSizeIterator for NativeOrderedIter<'_,T>{}
impl<T> std::iter::FusedIterator for NativeOrderedIter<'_,T>{}
struct NativeOrderedIntoIter<T>{entries:NativeOrderedEntries<T>}
impl<T> Iterator for NativeOrderedIntoIter<T>{
    type Item=T;
    fn next(&mut self)->Option<T>{let slot=self.entries.head;if slot==NATIVE_ENTRY_NONE{None}else{Some(self.entries.remove(slot))}}
    fn size_hint(&self)->(usize,Option<usize>){(self.entries.length,Some(self.entries.length))}
}
impl<T> DoubleEndedIterator for NativeOrderedIntoIter<T>{
    fn next_back(&mut self)->Option<T>{let slot=self.entries.tail;if slot==NATIVE_ENTRY_NONE{None}else{Some(self.entries.remove(slot))}}
}
impl<T> ExactSizeIterator for NativeOrderedIntoIter<T>{}
impl<T> std::iter::FusedIterator for NativeOrderedIntoIter<T>{}
impl<T> IntoIterator for NativeOrderedEntries<T>{
    type Item=T;type IntoIter=NativeOrderedIntoIter<T>;
    fn into_iter(self)->Self::IntoIter{NativeOrderedIntoIter{entries:self}}
}
fn native_dict_insert<T>(entries:&mut NativeDictionaryEntries<T>,value:T)->Result<usize,String>{entries.insert(value)}
fn native_dict_remove<T,C,S>(entries:&mut NativeDictionaryEntries<T>,_index:&mut std::collections::HashMap<C,usize,S>,slot:usize)->T{entries.remove(slot)}
'''


def helpers(deletion):
    return (ORDERED_HELPERS if deletion else DENSE_HELPERS)+POPITEM_HELPER


POPITEM_HELPER=r'''
fn native_dict_popitem<K,V,C,S,F>(entries:&mut NativeDictionaryEntries<(K,V)>,index:&mut std::collections::HashMap<C,usize,S>,canonical:F)->Result<(K,V),String>
where C:Eq+std::hash::Hash,S:std::hash::BuildHasher,F:FnOnce(&K)->C {
    let value=entries.pop().ok_or_else(||"KeyError: 'popitem(): dictionary is empty'".to_owned())?;
    let removed=index.remove(&canonical(&value.0));
    debug_assert!(removed.is_some());
    Ok(value)
}
'''
