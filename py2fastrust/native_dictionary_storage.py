"""Index-aware physical storage operations for typed dictionaries."""


PLAN=r'''
enum NativeDictionaryPlan{Keep,Clear,Physical,Compact(usize),Seed{size:usize,usable:usize,reserve:usize}}
'''


def plans(positioned):
    if not positioned:
        return PLAN+r'''
fn native_dict_literal_plan<T>(_entries:&NativeDictionaryEntries<T>,_count:usize)->Result<NativeDictionaryPlan,String>{Ok(NativeDictionaryPlan::Keep)}
fn native_dict_mapping_plan<T>(_entries:&NativeDictionaryEntries<T>,_source:(usize,usize,usize,usize))->Result<NativeDictionaryPlan,String>{Ok(NativeDictionaryPlan::Keep)}
fn native_dict_keyword_plan<T>(_entries:&NativeDictionaryEntries<T>,_count:usize)->Result<NativeDictionaryPlan,String>{Ok(NativeDictionaryPlan::Keep)}
fn native_dict_seed<T>(entries:&NativeDictionaryEntries<T>)->(usize,usize,usize,usize){(entries.len(),entries.len(),0,0)}
fn native_dict_copy_plan<T>(_entries:&NativeDictionaryEntries<T>,_constructor:bool)->Result<NativeDictionaryPlan,String>{Ok(NativeDictionaryPlan::Physical)}
'''
    return PLAN+r'''
fn native_dict_literal_plan<T>(_entries:&NativeDictionaryEntries<T>,count:usize)->Result<NativeDictionaryPlan,String>{
    Ok(if count>5{NativeDictionaryPlan::Compact(NativeOrderedEntries::<T>::estimated_size(count.min(87381))?)}else{NativeDictionaryPlan::Keep})
}
fn native_dict_mapping_plan<T>(entries:&NativeDictionaryEntries<T>,source:(usize,usize,usize,usize))->Result<NativeDictionaryPlan,String>{
    let(used,count,size,usable)=source;if used==0{return Ok(NativeDictionaryPlan::Keep);}
    let half=size/2;let half_capacity=half/3*2+(half%3)*2/3;
    if entries.length==0&&used==count&&(size==8||half_capacity<used){
        return Ok(NativeDictionaryPlan::Seed{size,usable:usable.checked_add(used).ok_or_else(||"MemoryError: dictionary positions".to_owned())?,reserve:used});
    }
    if entries.table_size/3*2+(entries.table_size%3)*2/3<used{
        let total=entries.length.checked_add(used).ok_or_else(||"MemoryError: dictionary positions".to_owned())?;
        return Ok(NativeDictionaryPlan::Compact(NativeOrderedEntries::<T>::estimated_size(total)?));
    }Ok(NativeDictionaryPlan::Keep)
}
fn native_dict_keyword_plan<T>(entries:&NativeDictionaryEntries<T>,count:usize)->Result<NativeDictionaryPlan,String>{
    if count==0{return Ok(NativeDictionaryPlan::Keep);}
    let mut size=NativeOrderedEntries::<T>::estimated_size(count.min(87381))?;
    while size/3*2+(size%3)*2/3<count{let used=size/3*2+(size%3)*2/3;size=NativeOrderedEntries::<T>::position_size(used.checked_mul(3).ok_or_else(||"MemoryError: dictionary positions".to_owned())?)?;}
    native_dict_mapping_plan(entries,(count,count,size,size/3*2+(size%3)*2/3-count))
}
fn native_dict_seed<T>(entries:&NativeDictionaryEntries<T>)->(usize,usize,usize,usize){entries.mapping_seed()}
fn native_dict_copy_plan<T>(entries:&NativeDictionaryEntries<T>,constructor:bool)->Result<NativeDictionaryPlan,String>{
    if entries.length==0{return Ok(NativeDictionaryPlan::Clear);}
    let half=entries.table_size/2;
    let compact=if constructor{entries.length!=entries.positions.len()||entries.table_size!=8&&half/3*2+(half%3)*2/3>=entries.length}
        else{entries.length<entries.positions.len()/3*2+(entries.positions.len()%3)*2/3};
    Ok(if compact{NativeDictionaryPlan::Compact(NativeOrderedEntries::<T>::estimated_size(entries.length)?)}else{NativeDictionaryPlan::Physical})
}
'''


def ordered(positioned):
    position_allocate=('let logical=if compact{length}else{entries.positions.len()};'
        'let mut positions=Vec::new();positions.try_reserve_exact(logical.checked_add(extra).ok_or_else(||"MemoryError".to_owned())?).map_err(|_|"MemoryError".to_owned())?;positions.resize(logical,NATIVE_ENTRY_NONE);')if positioned else''
    position_move=('let position=if compact{next_slot}else{entries.slots[slot].position};positions[position]=next_slot;')if positioned else''
    position_field=',position'if positioned else''
    position_commit=('entries.positions=positions;if let NativeDictionaryPlan::Compact(size)=plan{entries.table_size=size;entries.usable=(size/3*2+(size%3)*2/3).checked_sub(length).expect("dictionary resize capacity");}')if positioned else''
    seed=('if let NativeDictionaryPlan::Seed{size,usable,reserve}=plan{'
          'let mut replacement=NativeOrderedEntries::new();replacement.slots.try_reserve_exact(reserve).map_err(|_|"MemoryError".to_owned())?;replacement.positions.try_reserve_exact(reserve).map_err(|_|"MemoryError".to_owned())?;'
          'let mut replacement_index=std::collections::HashMap::with_hasher(index.hasher().clone());replacement_index.try_reserve(reserve).map_err(|_|"MemoryError".to_owned())?;'
          'replacement.table_size=size;replacement.usable=usable;*entries=replacement;*index=replacement_index;return Ok(());}')if positioned else''
    insert_plan=('if entries.usable==0{let size=NativeOrderedEntries::<T>::position_size(entries.length.checked_mul(3).ok_or_else(||"MemoryError".to_owned())?)?;native_dict_apply_plan(entries,index,NativeDictionaryPlan::Compact(size),1)?;}')if positioned else('if entries.free!=NATIVE_ENTRY_NONE&&entries.length<=entries.slots.len()/2{native_dict_apply_plan(entries,index,NativeDictionaryPlan::Physical,1)?;}')
    copy_plan=('let compact=if constructor{let half=entries.table_size/2;entries.length!=entries.positions.len()||entries.table_size!=8&&half/3*2+(half%3)*2/3>=length}'
        'else{length<entries.positions.len()/3*2+(entries.positions.len()%3)*2/3};'
        'let logical=if compact{length}else{entries.positions.len()};'
        'result.positions.try_reserve_exact(logical).map_err(|_|"MemoryError".to_owned())?;result.positions.resize(logical,NATIVE_ENTRY_NONE);'
        'if compact{let size=NativeOrderedEntries::<(K,V)>::estimated_size(length)?;result.table_size=size;result.usable=(size/3*2+(size%3)*2/3)-length;}'
        'else{result.table_size=entries.table_size;result.usable=entries.usable;}')if positioned else'let _=constructor;'
    copy_position=('let position=if compact{order}else{entries.slots[slot].position};result.positions[position]=destination;result.slots[destination].position=position;')if positioned else''
    copy_dense_position=('let position=if compact{order}else{entries.slots[slot].position};result.positions[position]=slot;result.slots[slot].position=position;')if positioned else''
    copy_dense_positions=('let mut slot=entries.head;let mut order=0;while slot!=NATIVE_ENTRY_NONE{'+copy_dense_position+'order+=1;slot=entries.slots[slot].next;}')if positioned else''
    return plans(positioned)+r'''
fn native_dict_apply_plan<T,C:Eq+std::hash::Hash,S:std::hash::BuildHasher+Clone>(entries:&mut NativeDictionaryEntries<T>,index:&mut std::collections::HashMap<C,usize,S>,plan:NativeDictionaryPlan,extra:usize)->Result<(),String>{
    if matches!(plan,NativeDictionaryPlan::Keep){return Ok(());}
    if matches!(plan,NativeDictionaryPlan::Clear){entries.clear();*index=std::collections::HashMap::with_hasher(index.hasher().clone());return Ok(());}
    '''+seed+r'''
    let compact=matches!(plan,NativeDictionaryPlan::Compact(_));let length=entries.length;
    if let NativeDictionaryPlan::Compact(size)=plan{if (size/3*2+(size%3)*2/3)<length{return Err("MemoryError: dictionary resize capacity".to_owned());}}
    let capacity=length.checked_add(extra).filter(|value|*value<=isize::MAX as usize).ok_or_else(||"MemoryError".to_owned())?;
    let mut slots=Vec::new();slots.try_reserve_exact(capacity).map_err(|_|"MemoryError".to_owned())?;
    let mut replacement=std::collections::HashMap::with_hasher(index.hasher().clone());replacement.try_reserve(capacity).map_err(|_|"MemoryError".to_owned())?;
    '''+position_allocate+r'''
    let mut slot=entries.head;
    while slot!=NATIVE_ENTRY_NONE{
        let next=entries.slots[slot].next;let next_slot=slots.len();
        '''+position_move+r'''
        slots.push(NativeEntrySlot{value:entries.slots[slot].value.take(),previous:if next_slot==0{NATIVE_ENTRY_NONE}else{next_slot-1},next:if next_slot+1==length{NATIVE_ENTRY_NONE}else{next_slot+1}'''+position_field+r'''});
        entries.slots[slot].previous=next_slot;slot=next;
    }
    for(key,old_slot)in index.drain(){replacement.insert(key,entries.slots[old_slot].previous);}
    entries.slots=slots;entries.head=if length==0{NATIVE_ENTRY_NONE}else{0};entries.tail=if length==0{NATIVE_ENTRY_NONE}else{length-1};entries.free=NATIVE_ENTRY_NONE;entries.index_unerased=true;
    '''+position_commit+r'''
    *index=replacement;Ok(())
}
fn native_dict_insert<T,C:Eq+std::hash::Hash,S:std::hash::BuildHasher+Clone>(entries:&mut NativeDictionaryEntries<T>,index:&mut std::collections::HashMap<C,usize,S>,value:T)->Result<usize,String>{
    '''+insert_plan+r'''
    entries.insert(value)
}
fn native_dict_copy_slots<T:Copy>(target:&mut Vec<NativeEntrySlot<T>>,source:&[NativeEntrySlot<T>]){
    assert!(target.is_empty());assert!(target.capacity()>=source.len());
    unsafe{std::ptr::copy_nonoverlapping(source.as_ptr(),target.as_mut_ptr(),source.len());target.set_len(source.len());}
}
fn native_dict_try_copy<K:Clone,V:Clone,C:Clone+Eq+std::hash::Hash,S:std::hash::BuildHasher+Clone,F:FnMut(&K)->C>(entries:&NativeDictionaryEntries<(K,V)>,index:&std::collections::HashMap<C,usize,S>,canonical:F,constructor:bool)->Result<(NativeDictionaryEntries<(K,V)>,std::collections::HashMap<C,usize,S>),String>{
    native_dict_try_copy_with(entries,index,canonical,constructor,|target,source|target.extend_from_slice(source))
}
fn native_dict_try_copy_bits<K:Copy,V:Copy,C:Clone+Eq+std::hash::Hash,S:std::hash::BuildHasher+Clone,F:FnMut(&K)->C>(entries:&NativeDictionaryEntries<(K,V)>,index:&std::collections::HashMap<C,usize,S>,canonical:F,constructor:bool)->Result<(NativeDictionaryEntries<(K,V)>,std::collections::HashMap<C,usize,S>),String>{
    native_dict_try_copy_with(entries,index,canonical,constructor,native_dict_copy_slots::<(K,V)>)
}
fn native_dict_try_copy_with<K:Clone,V:Clone,C:Clone+Eq+std::hash::Hash,S:std::hash::BuildHasher+Clone,F:FnMut(&K)->C,R:FnOnce(&mut Vec<NativeEntrySlot<(K,V)>>,&[NativeEntrySlot<(K,V)>])>(entries:&NativeDictionaryEntries<(K,V)>,index:&std::collections::HashMap<C,usize,S>,mut canonical:F,constructor:bool,rows:R)->Result<(NativeDictionaryEntries<(K,V)>,std::collections::HashMap<C,usize,S>),String>{
    let length=entries.length;let mut result=NativeOrderedEntries::new();let mut copied=std::collections::HashMap::with_hasher(index.hasher().clone());
    if length==0{return Ok((result,copied));}
    result.slots.try_reserve_exact(length).map_err(|_|"MemoryError".to_owned())?;copied.try_reserve(length).map_err(|_|"MemoryError".to_owned())?;
    '''+copy_plan+r'''
    if entries.free==NATIVE_ENTRY_NONE{
        rows(&mut result.slots,&entries.slots);result.head=entries.head;result.tail=entries.tail;
        if entries.index_unerased&&copied.capacity()==index.capacity(){copied.clone_from(index);}else{
            for(slot,row)in entries.slots.iter().enumerate(){let pair=row.value.as_ref().expect("live dictionary slot");let query=canonical(&pair.0);let(stored,found)=index.get_key_value(&query).expect("registered dictionary canonical key");debug_assert_eq!(*found,slot);copied.insert(stored.clone(),slot);}
        }
        '''+copy_dense_positions+r'''
    }else{
        let mut slot=entries.head;let mut order=0;
        while slot!=NATIVE_ENTRY_NONE{
            let pair=entries.slots[slot].value.as_ref().expect("live dictionary slot");let query=canonical(&pair.0);
            let(stored,found)=index.get_key_value(&query).expect("registered dictionary canonical key");debug_assert_eq!(*found,slot);
            let destination=result.slots.len();copied.insert(stored.clone(),destination);
            result.slots.push(NativeEntrySlot{value:Some(pair.clone()),previous:if destination==0{NATIVE_ENTRY_NONE}else{destination-1},next:if destination+1==length{NATIVE_ENTRY_NONE}else{destination+1}'''+(',position:0'if positioned else'')+r'''});
            '''+copy_position+r'''
            order+=1;slot=entries.slots[slot].next;
        }
        result.head=0;result.tail=length-1;
    }
    result.length=length;Ok((result,copied))
}
'''


DENSE=plans(False)+r'''
fn native_dict_apply_plan<T,C:Eq+std::hash::Hash,S:std::hash::BuildHasher+Clone>(_entries:&mut NativeDictionaryEntries<T>,_index:&mut std::collections::HashMap<C,usize,S>,_plan:NativeDictionaryPlan,_extra:usize)->Result<(),String>{Ok(())}
fn native_dict_try_copy<K:Clone,V:Clone,C:Clone+Eq+std::hash::Hash,S:std::hash::BuildHasher+Clone,F:FnMut(&K)->C>(entries:&NativeDictionaryEntries<(K,V)>,index:&std::collections::HashMap<C,usize,S>,mut canonical:F,_constructor:bool)->Result<(NativeDictionaryEntries<(K,V)>,std::collections::HashMap<C,usize,S>),String>{
    let mut result=NativeDictionaryEntries::new();result.try_reserve_exact(entries.len()).map_err(|_|"MemoryError".to_owned())?;let mut copied=std::collections::HashMap::with_hasher(index.hasher().clone());copied.try_reserve(index.len()).map_err(|_|"MemoryError".to_owned())?;
    result.extend_from_slice(entries);if entries.index_unerased&&copied.capacity()==index.capacity(){copied.clone_from(index);}else{for(slot,pair)in entries.iter().enumerate(){let query=canonical(&pair.0);let(stored,found)=index.get_key_value(&query).expect("registered dictionary canonical key");debug_assert_eq!(*found,slot);copied.insert(stored.clone(),slot);}}Ok((result,copied))
}
'''

DENSE += r'''
fn native_dict_try_copy_bits<K:Copy,V:Copy,C:Clone+Eq+std::hash::Hash,S:std::hash::BuildHasher+Clone,F:FnMut(&K)->C>(entries:&NativeDictionaryEntries<(K,V)>,index:&std::collections::HashMap<C,usize,S>,canonical:F,constructor:bool)->Result<(NativeDictionaryEntries<(K,V)>,std::collections::HashMap<C,usize,S>),String>{
    native_dict_try_copy(entries,index,canonical,constructor)
}
'''
