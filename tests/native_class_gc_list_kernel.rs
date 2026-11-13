use std::cell::RefCell;
use std::rc::Rc;
type ClassHandle_0=Rc<RefCell<ClassData_0>>;
type ClassList<T>=Rc<RefCell<Vec<T>>>;
struct ClassData_0 {field_0:Option<(ClassList<ClassHandle_0>,ClassList<ClassHandle_0>)>}
fn node()->ClassHandle_0{Rc::new(RefCell::new(ClassData_0{field_0:None}))}
fn register(gc:&mut NativeClassGc,node:&ClassHandle_0){
 let erased:Rc<dyn NativeClassGcNode>=node.clone();gc.register(Rc::downgrade(&erased));
}
fn cycle(gc:&mut NativeClassGc)->(std::rc::Weak<RefCell<ClassData_0>>,std::rc::Weak<RefCell<Vec<ClassHandle_0>>>){
 let value=node();let list=Rc::new(RefCell::new(vec![value.clone(),value.clone()]));
 value.borrow_mut().field_0=Some((list.clone(),list.clone()));register(gc,&value);
 (Rc::downgrade(&value),Rc::downgrade(&list))
}
#[test]
fn unreachable_shared_list_cycle_expires(){
 let mut gc=NativeClassGc::new();let(value,list)=cycle(&mut gc);
 assert_eq!(gc.collect(),2);assert!(value.upgrade().is_none());assert!(list.upgrade().is_none());
}
#[test]
fn external_list_alias_is_a_root(){
 let mut gc=NativeClassGc::new();let(value,list)=cycle(&mut gc);let keep=list.upgrade().unwrap();
 assert_eq!(gc.collect(),0);assert_eq!(keep.borrow().len(),2);assert!(value.upgrade().is_some());
 drop(keep);assert_eq!(gc.collect(),2);assert!(value.upgrade().is_none());
}
#[test]
fn external_class_alias_reaches_the_list(){
 let mut gc=NativeClassGc::new();let(value,list)=cycle(&mut gc);let keep=value.upgrade().unwrap();
 assert_eq!(gc.collect(),0);assert!(list.upgrade().is_some());assert!(keep.borrow().field_0.is_some());
 drop(keep);assert_eq!(gc.collect(),2);assert!(list.upgrade().is_none());
}
#[test]
fn duplicate_owners_elements_and_registrations_count_physical_edges(){
 let mut gc=NativeClassGc::new();let a=node();let b=node();
 let list=Rc::new(RefCell::new(vec![a.clone(),b.clone(),a.clone()]));
 a.borrow_mut().field_0=Some((list.clone(),list.clone()));
 b.borrow_mut().field_0=Some((list.clone(),list.clone()));
 register(&mut gc,&a);register(&mut gc,&a);register(&mut gc,&b);
 let wa=Rc::downgrade(&a);let wb=Rc::downgrade(&b);let wl=Rc::downgrade(&list);
 drop(a);drop(b);assert_eq!(gc.collect(),0);assert_eq!(list.borrow().len(),3);
 drop(list);assert_eq!(gc.collect(),3);assert!(wa.upgrade().is_none());assert!(wb.upgrade().is_none());assert!(wl.upgrade().is_none());
}
#[test]
fn borrowed_list_never_panics_or_clears_live_values(){
 let mut gc=NativeClassGc::new();let(value,list)=cycle(&mut gc);let keep=list.upgrade().unwrap();
 let read=keep.borrow();assert_eq!(gc.collect(),0);assert_eq!(read.len(),2);drop(read);
 let write=keep.borrow_mut();assert_eq!(gc.collect(),0);drop(write);drop(keep);
 assert_eq!(gc.collect(),2);assert!(value.upgrade().is_none());
}
#[test]
fn discovery_follows_new_lists_after_previous_collection(){
 let mut gc=NativeClassGc::new();let a=node();let first=Rc::new(RefCell::new(vec![a.clone()]));
 a.borrow_mut().field_0=Some((first.clone(),first.clone()));register(&mut gc,&a);assert_eq!(gc.collect(),0);
 let second=Rc::new(RefCell::new(vec![a.clone(),a.clone()]));let ws=Rc::downgrade(&second);
 a.borrow_mut().field_0=Some((second.clone(),second.clone()));drop(first);drop(second);
 let wa=Rc::downgrade(&a);drop(a);assert_eq!(gc.collect(),2);assert!(wa.upgrade().is_none());assert!(ws.upgrade().is_none());
}
