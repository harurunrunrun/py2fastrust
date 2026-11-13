use std::rc::Rc;
use std::cell::RefCell;

#[test]
fn preserves_original_shared_key_in_collision_copy_and_merge() {
    let original=Rc::new("original".to_owned());let replacement=Rc::new("replacement".to_owned());
    let mut source=NativeCPSet::new();source.add(original.clone(),17i64,17).unwrap();
    assert!(!source.add(replacement.clone(),17,17).unwrap());
    for key in 1i64..400 {source.add(Rc::new(key.to_string()),key+1000,key).unwrap();}
    assert!(Rc::ptr_eq(source.entries().find(|(_,canonical,_)|**canonical==17).unwrap().0,&original));
    let copy=source.copy_set().unwrap();
    assert!(Rc::ptr_eq(copy.entries().find(|(_,canonical,_)|**canonical==17).unwrap().0,&original));
    let mut destination=NativeCPSet::new();destination.add(replacement.clone(),17,17).unwrap();destination.merge(&source).unwrap();
    assert!(Rc::ptr_eq(destination.entries().find(|(_,canonical,_)|**canonical==17).unwrap().0,&replacement));
    assert!(source.contains(&17,17));assert!(source.discard(&17,17));assert!(!source.contains(&17,17));assert!(!source.discard(&17,17));
}

#[test]
fn checked_resize_failure_preserves_live_table_and_all_key_roots() {
    let key=Rc::new("root".to_owned());let mut set=NativeCPSet::new();set.add(key.clone(),0i64,0).unwrap();
    let capacity=set.capacity();assert_eq!(set.resize(usize::MAX),Err("MemoryError".to_owned()));
    assert_eq!(set.capacity(),capacity);assert_eq!(set.len(),1);assert!(set.contains(&0,0));assert_eq!(Rc::strong_count(&key),2);
    set.clear();assert_eq!(set.capacity(),8);assert!(set.is_empty());assert_eq!(Rc::strong_count(&key),1);
}

#[test]
fn normal_exhaustion_releases_owner_after_the_exhausting_pull() {
    let owner=Rc::new(RefCell::new(NativeCPSet::new()));owner.borrow_mut().add(7,7,7).unwrap();
    let weak=Rc::downgrade(&owner);let mut cursor=NativeCPSetCursor::new(owner.clone());drop(owner);
    assert_eq!(cursor.next(),Ok(Some(7)));assert!(weak.upgrade().is_some());
    assert_eq!(cursor.next(),Ok(None));assert!(weak.upgrade().is_none());assert_eq!(cursor.next(),Ok(None));
}

#[test]
fn size_error_is_sticky_even_after_original_cardinality_is_restored() {
    let owner=Rc::new(RefCell::new(NativeCPSet::<i64,i64>::new()));
    let mut cursor=NativeCPSetCursor::new(owner.clone());owner.borrow_mut().add(1,1,1).unwrap();
    assert_eq!(cursor.next(),Err("RuntimeError: Set changed size during iteration".to_owned()));
    owner.borrow_mut().clear();assert_eq!(cursor.length_hint(),0);
    assert_eq!(cursor.next(),Err("RuntimeError: Set changed size during iteration".to_owned()));
    let weak=Rc::downgrade(&owner);drop(owner);assert!(weak.upgrade().is_some());drop(cursor);assert!(weak.upgrade().is_none());
}
