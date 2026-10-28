"""Typed insertion-order storage with reusable slots for dictionary deletion."""

DENSE_HELPERS=r'''
type NativeDictionaryEntries<T>=Vec<T>;
fn native_dict_insert<T>(entries:&mut NativeDictionaryEntries<T>,value:T)->Result<usize,String>{
    let index=entries.len();
    index.checked_add(1).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"MemoryError: dictionary is too large".to_owned())?;
    entries.try_reserve(1).map_err(|_|"MemoryError: cannot allocate dictionary entries".to_owned())?;
    entries.push(value);Ok(index)
}
fn native_dict_remove<T,C>(entries:&mut NativeDictionaryEntries<T>,index:&mut std::collections::HashMap<C,usize>,slot:usize)->T{
    let value=entries.remove(slot);
    for offset in index.values_mut(){if *offset>slot{*offset-=1;}}
    value
}
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
fn native_dict_remove<T,C>(entries:&mut NativeDictionaryEntries<T>,_index:&mut std::collections::HashMap<C,usize>,slot:usize)->T{entries.remove(slot)}
'''


def helpers(deletion):
    return ORDERED_HELPERS if deletion else DENSE_HELPERS
