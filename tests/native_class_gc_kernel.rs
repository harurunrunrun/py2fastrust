use std::cell::{Cell,RefCell};
use std::rc::{Rc,Weak};

#[derive(Default)]
struct Data {
 left:Option<Rc<Node>>,
 right:Option<Rc<Node>>,
}
struct Node {
 data:RefCell<Data>,
 available:Cell<bool>,
 readable:Cell<bool>,
 traces:Rc<Cell<usize>>,
}
impl Node {
 fn new()->Rc<Self>{Self::counted(Rc::new(Cell::new(0)))}
 fn counted(traces:Rc<Cell<usize>>)->Rc<Self>{Rc::new(Self{data:RefCell::new(Data::default()),available:Cell::new(true),readable:Cell::new(true),traces})}
}
impl NativeClassGcNode for Node {
 fn trace(&self,visit:&mut dyn FnMut(usize))->bool{
  self.traces.set(self.traces.get()+1);
  if !self.readable.get(){return false;}
  let Ok(data)=self.data.try_borrow()else{return false;};
  for value in [&data.left,&data.right].into_iter().flatten(){visit(Rc::as_ptr(value)as usize);}
  true
 }
 fn available(&self)->bool{self.available.get()&&self.data.try_borrow_mut().is_ok()}
 fn clear(&self)->bool{
  let Ok(mut data)=self.data.try_borrow_mut()else{return false;};
  data.left=None;data.right=None;true
 }
}
fn register<T:NativeClassGcNode+'static>(gc:&mut NativeClassGc,node:&Rc<T>){
 let erased:Rc<dyn NativeClassGcNode>=node.clone();gc.register(Rc::downgrade(&erased));
}

#[test]
fn unreachable_self_cycle_expires(){
 let mut gc=NativeClassGc::new();let node=Node::new();let weak=Rc::downgrade(&node);
 node.data.borrow_mut().left=Some(node.clone());register(&mut gc,&node);drop(node);
 assert!(weak.upgrade().is_some());assert_eq!(gc.collect(),1);assert!(weak.upgrade().is_none());assert!(gc.nodes.is_empty());
}

#[test]
fn live_alias_duplicate_edges_and_registration_are_exact(){
 let mut gc=NativeClassGc::new();let node=Node::new();let alias=node.clone();let weak=Rc::downgrade(&node);
 node.data.borrow_mut().left=Some(node.clone());node.data.borrow_mut().right=Some(node.clone());
 register(&mut gc,&node);register(&mut gc,&node);drop(node);
 assert_eq!(gc.collect(),0);assert_eq!(gc.nodes.len(),1);assert!(alias.data.borrow().left.is_some());
 drop(alias);assert_eq!(gc.collect(),1);assert!(weak.upgrade().is_none());
}

#[test]
fn actual_borrows_and_conservative_unknown_edges_are_roots(){
 let mut gc=NativeClassGc::new();let a=Node::new();let b=Node::new();
 a.data.borrow_mut().left=Some(b.clone());b.data.borrow_mut().left=Some(a.clone());register(&mut gc,&a);register(&mut gc,&b);
 let read=a.data.borrow();assert_eq!(gc.collect(),0);assert!(read.left.is_some());drop(read);
 let write=b.data.borrow_mut();assert_eq!(gc.collect(),0);drop(write);
 let wa=Rc::downgrade(&a);let wb=Rc::downgrade(&b);a.readable.set(false);a.available.set(false);drop(a);drop(b);
 assert_eq!(gc.collect(),0);assert!(wa.upgrade().is_some());assert!(wb.upgrade().is_some());
 let pinned=wa.upgrade().unwrap();pinned.readable.set(true);pinned.available.set(true);drop(pinned);
 assert_eq!(gc.collect(),2);assert!(wa.upgrade().is_none());assert!(wb.upgrade().is_none());
}

struct Left { right:RefCell<Option<Rc<Right>>> }
struct Right { left:RefCell<Option<Rc<Left>>> }
impl NativeClassGcNode for Left{
 fn trace(&self,visit:&mut dyn FnMut(usize))->bool{let Ok(v)=self.right.try_borrow()else{return false;};if let Some(v)=&*v{visit(Rc::as_ptr(v)as usize);}true}
 fn available(&self)->bool{self.right.try_borrow_mut().is_ok()}
 fn clear(&self)->bool{let Ok(mut v)=self.right.try_borrow_mut()else{return false;};*v=None;true}
}
impl NativeClassGcNode for Right{
 fn trace(&self,visit:&mut dyn FnMut(usize))->bool{let Ok(v)=self.left.try_borrow()else{return false;};if let Some(v)=&*v{visit(Rc::as_ptr(v)as usize);}true}
 fn available(&self)->bool{self.left.try_borrow_mut().is_ok()}
 fn clear(&self)->bool{let Ok(mut v)=self.left.try_borrow_mut()else{return false;};*v=None;true}
}
#[test]
fn two_concrete_classes_are_one_graph(){
 let mut gc=NativeClassGc::new();let a=Rc::new(Left{right:RefCell::new(None)});let b=Rc::new(Right{left:RefCell::new(Some(a.clone()))});
 *a.right.borrow_mut()=Some(b.clone());register(&mut gc,&a);register(&mut gc,&b);
 let wa=Rc::downgrade(&a);let wb=Rc::downgrade(&b);drop(a);drop(b);
 assert_eq!(gc.collect(),2);assert!(wa.upgrade().is_none());assert!(wb.upgrade().is_none());
}

struct Untracked { child:Rc<Node> }
struct Outer { link:RefCell<Option<Rc<Outer>>>,owner:RefCell<Option<Rc<Untracked>>> }
impl NativeClassGcNode for Outer{
 fn trace(&self,visit:&mut dyn FnMut(usize))->bool{let Ok(v)=self.link.try_borrow()else{return false;};if let Some(v)=&*v{visit(Rc::as_ptr(v)as usize);}true}
 fn available(&self)->bool{self.link.try_borrow_mut().is_ok()&&self.owner.try_borrow_mut().is_ok()}
 fn clear(&self)->bool{let Ok(mut link)=self.link.try_borrow_mut()else{return false;};let Ok(mut owner)=self.owner.try_borrow_mut()else{return false;};*link=None;*owner=None;true}
}
#[test]
fn untracked_outbound_owner_is_conservative_and_drop_drains(){
 let mut gc=NativeClassGc::new();let child=Node::new();child.data.borrow_mut().left=Some(child.clone());
 let owner=Rc::new(Untracked{child:child.clone()});assert!(Rc::ptr_eq(&owner.child,&child));
 let outer=Rc::new(Outer{link:RefCell::new(None),owner:RefCell::new(Some(owner))});*outer.link.borrow_mut()=Some(outer.clone());
 register(&mut gc,&child);register(&mut gc,&outer);let weak=Rc::downgrade(&child);drop(child);drop(outer);
 assert_eq!(gc.collect(),1);assert!(weak.upgrade().is_some());drop(gc);assert!(weak.upgrade().is_none());
}

#[test]
fn unreachable_allocation_growth_remains_bounded(){
 let mut gc=NativeClassGc::new();let mut weak=Vec::new();
 for _ in 0..20000{
  let node=Node::new();node.data.borrow_mut().left=Some(node.clone());weak.push(Rc::downgrade(&node));register(&mut gc,&node);
  assert!(gc.nodes.len()<=128);
 }
 drop(gc);assert!(weak.iter().all(|node|node.upgrade().is_none()));
}

#[test]
fn live_graph_registration_uses_geometric_trace_work(){
 let count=32768;let traces=Rc::new(Cell::new(0));let mut gc=NativeClassGc::new();let mut roots=Vec::new();let mut weak=Vec::new();
 for _ in 0..count{
  let node=Node::counted(traces.clone());node.data.borrow_mut().left=Some(node.clone());register(&mut gc,&node);weak.push(Rc::downgrade(&node));roots.push(node);
 }
 assert!(traces.get()<count*3);assert!(weak.iter().all(|node|node.upgrade().is_some()));
 drop(roots);gc.collect();assert!(weak.iter().all(|node|node.upgrade().is_none()));
}
