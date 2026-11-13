use std::cell::RefCell;
use std::rc::Rc;

#[derive(Default)]
struct Data {
 links:Option<(Option<Rc<Node>>,(Option<Rc<Node>>,i64))>,
}
struct Node { data:RefCell<Data> }
impl Node {
 fn new()->Rc<Self>{Rc::new(Self{data:RefCell::new(Data::default())})}
 fn pair(owner:&Rc<Self>,first:&Rc<Self>,second:&Rc<Self>){
  owner.data.borrow_mut().links=Some((Some(first.clone()),(Some(second.clone()),7)));
 }
}
impl NativeClassGcNode for Node {
 fn trace(&self,visit:&mut dyn FnMut(usize))->bool{
  let Ok(data)=self.data.try_borrow()else{return false;};
  if let Some(value)=&data.links { /* GENERATED_TUPLE_TRACE */; }
  true
 }
 fn available(&self)->bool{self.data.try_borrow_mut().is_ok()}
 fn clear(&self)->bool{
  let Ok(mut data)=self.data.try_borrow_mut()else{return false;};
  data.links=None;true
 }
}
fn register(gc:&mut NativeClassGc,node:&Rc<Node>){
 let erased:Rc<dyn NativeClassGcNode>=node.clone();gc.register(Rc::downgrade(&erased));
}

#[test]
fn tuple_duplicate_edges_reclaim_exactly_once(){
 let mut gc=NativeClassGc::new();let node=Node::new();let weak=Rc::downgrade(&node);
 Node::pair(&node,&node,&node);register(&mut gc,&node);register(&mut gc,&node);drop(node);
 assert_eq!(gc.collect(),1);assert!(weak.upgrade().is_none());assert!(gc.nodes.is_empty());
}

#[test]
fn shared_external_tuple_keeps_the_cycle_until_last_alias_drops(){
 let mut gc=NativeClassGc::new();let node=Node::new();let weak=Rc::downgrade(&node);
 Node::pair(&node,&node,&node);register(&mut gc,&node);
 let outside=Rc::new((node.clone(),));let alias=outside.clone();drop(node);
 assert_eq!(gc.collect(),0);assert!(weak.upgrade().is_some());
 drop(outside);assert_eq!(gc.collect(),0);assert!(alias.0.data.borrow().links.is_some());
 drop(alias);assert_eq!(gc.collect(),1);assert!(weak.upgrade().is_none());
}

#[test]
fn nested_mutual_edges_keep_reachable_nodes_and_respect_borrows(){
 let mut gc=NativeClassGc::new();let first=Node::new();let second=Node::new();
 Node::pair(&first,&second,&second);Node::pair(&second,&first,&first);
 register(&mut gc,&first);register(&mut gc,&second);
 let left=Rc::downgrade(&first);let right=Rc::downgrade(&second);
 let saved=(first.clone(),second.clone());drop(first);drop(second);
 let read=saved.0.data.borrow();assert_eq!(gc.collect(),0);assert!(read.links.is_some());drop(read);
 let write=saved.1.data.borrow_mut();assert_eq!(gc.collect(),0);drop(write);
 drop(saved);assert_eq!(gc.collect(),2);assert!(left.upgrade().is_none());assert!(right.upgrade().is_none());
}

#[test]
fn repeated_unreachable_tuple_cycles_have_bounded_registry(){
 let mut gc=NativeClassGc::new();let mut weak=Vec::new();
 for _ in 0..4000{
  let node=Node::new();Node::pair(&node,&node,&node);weak.push(Rc::downgrade(&node));register(&mut gc,&node);
  assert!(gc.nodes.len()<=128);
 }
 drop(gc);assert!(weak.iter().all(|node|node.upgrade().is_none()));
}
