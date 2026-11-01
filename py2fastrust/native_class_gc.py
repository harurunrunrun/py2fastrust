"""Trial deletion for proved direct, callback-free source-class cycles."""
from .native_types import NullableType,UnionType


def _components(graph):
    seen=set();order=[]
    for root in graph:
        if root in seen:continue
        stack=[(root,False)]
        while stack:
            node,done=stack.pop()
            if done:order.append(node);continue
            if node in seen:continue
            seen.add(node);stack.append((node,True))
            stack.extend((child,False)for child in graph.get(node,())if child not in seen)
    reverse={node:set()for node in graph}
    for node,children in graph.items():
        for child in children:reverse.setdefault(child,set()).add(node)
    seen=set()
    for root in reversed(order):
        if root in seen:continue
        found=set();stack=[root]
        while stack:
            node=stack.pop()
            if node in seen:continue
            seen.add(node);found.add(node);stack.extend(reverse.get(node,()))
        yield found


def supported_field(kind):
    from .native_classes import InstanceType
    if isinstance(kind,InstanceType):return True
    if isinstance(kind,NullableType):return supported_field(kind.value)
    if isinstance(kind,UnionType):return all(supported_field(part)for part in kind.alternatives)
    return kind in {'int','bool','int_bool','float','str','bytes','none'}


def admit(model,graph):
    from .native_classes import ClassUnsupported,shape
    cyclic=set()
    for component in _components(graph):
        if len(component)>1 or any(node in graph.get(node,())for node in component):cyclic.update(component)
    for name in sorted(cyclic):
        owner=model.classes[name]
        for field_key,field in owner.fields.items():
            kind=shape(field.cell)
            if not supported_field(kind):
                cycle=' ('+owner.node.name+' -> '+owner.node.name+')'if name in graph.get(name,())else''
                raise ClassUnsupported(owner.node,'this class field participates in a reference cycle'+cycle+' and needs container/callable-mediated collection; the direct class collector supports only builtin scalar values, None and direct source-class references or their finite alternatives',operation='cyclic class field '+owner.node.name+'.'+getattr(field,'name',field_key),types=(('field',kind),),proof='direct callback-free class-cycle edges')
    model.gc_classes=frozenset(cyclic)
    return model.gc_classes


def _trace(kind,code,tracked):
    from .native_classes import InstanceType
    from .native_unions import project,union_kind
    if union_kind(kind):return project(kind,code,lambda part,value:_trace(part,value,tracked))
    if isinstance(kind,InstanceType)and kind.name in tracked:
        return 'visit(Rc::as_ptr(&('+code+'))as usize)'
    return '()'


def lexical_projection(model,edges):
    """Discharge only complete lifetime SCCs owned by this direct collector."""
    tracked=getattr(model,'gc_classes',())
    if not tracked:return edges
    projected={node:set(children)for node,children in edges.items()}
    for component in _components(edges):
        if not all(node[0]=='object'and node[1]in tracked for node in component):continue
        if len(component)==1 and not any(node in edges.get(node,())for node in component):continue
        for node in component:projected[node].difference_update(component)
    return projected


def layout(model,owner):
    if model.class_key(owner)not in getattr(model,'gc_classes',()):return ''
    from .native_classes import shape
    traces=[];clears=[]
    for index,field in enumerate(owner.fields.values()):
        traces.append('if let Some(value)=&data.field_'+str(index)+'{'+_trace(shape(field.cell),'(*value)',model.gc_classes)+';}')
        clears.append('data.field_'+str(index)+'=None;')
    return ('impl NativeClassGcNode for RefCell<ClassData_'+str(owner.index)+'> {'
        'fn trace(&self,visit:&mut dyn FnMut(usize))->bool{let Ok(data)=self.try_borrow()else{return false;};'+''.join(traces)+'true}'
        'fn available(&self)->bool{self.try_borrow_mut().is_ok()}'
        'fn clear(&self)->bool{let Ok(mut data)=self.try_borrow_mut()else{return false;};'+''.join(clears)+'true}}')


def registration(model,owner):
    if model.class_key(owner)not in getattr(model,'gc_classes',()):return ''
    return '{let tracked:Rc<dyn NativeClassGcNode>=object.clone();class_scope.control.borrow_mut().gc.register(Rc::downgrade(&tracked));}'


def runtime(source,model):
    if not getattr(model,'gc_classes',()):return source
    from .rust_pruning import _lex
    tokens,_,pairs=_lex(source);edits=[];declarations=0;constructors=0
    for index,token in enumerate(tokens[:-1]):
        if token.text!='ClassControl'or tokens[index+1].text!='{':continue
        close=tokens[pairs[index+1]]
        prefix=''if source[:close.start].rstrip().endswith(',')else','
        if index and tokens[index-1].text=='struct':field='gc:NativeClassGc';declarations+=1
        else:
            if tokens[index+2].text not in {'child','depth','limit'}or tokens[index+3].text!=':':continue
            field='gc:NativeClassGc::new()';constructors+=1
        edits.append((close.start,close.start,prefix+field))
    assert declarations==1 and constructors>0,(declarations,constructors)
    for begin,end,text in sorted(edits,reverse=True):source=source[:begin]+text+source[end:]
    return source+'\n'+RUNTIME


RUNTIME=r'''
trait NativeClassGcNode {
 fn trace(&self,visit:&mut dyn FnMut(usize))->bool;
 fn available(&self)->bool;
 fn clear(&self)->bool;
}
struct NativeClassGc {
 nodes:Vec<std::rc::Weak<dyn NativeClassGcNode>>,
 threshold:usize,
}
impl NativeClassGc {
 fn new()->Self{Self{nodes:Vec::new(),threshold:64}}
 fn register(&mut self,node:std::rc::Weak<dyn NativeClassGcNode>){
  self.nodes.push(node);
  if self.nodes.len()>=self.threshold{self.collect();}
 }
 fn collect(&mut self)->usize{
  let mut pins:Vec<Rc<dyn NativeClassGcNode>>=Vec::new();
  let mut indexes=std::collections::HashMap::<usize,usize>::new();
  for weak in &self.nodes{
   if let Some(node)=weak.upgrade(){
    let address=Rc::as_ptr(&node)as *const ()as usize;
    if !indexes.contains_key(&address){indexes.insert(address,pins.len());pins.push(node);}
   }
  }
  let mut incoming=vec![0usize;pins.len()];
  let mut edges=vec![Vec::<usize>::new();pins.len()];
  let mut marked=vec![false;pins.len()];
  for (index,node)in pins.iter().enumerate(){
   let traced=node.trace(&mut |address|{
    if let Some(&target)=indexes.get(&address){
     incoming[target]=incoming[target].checked_add(1).expect("class edge count exceeds reference count");
     edges[index].push(target);
    }
   });
   if !traced||!node.available(){marked[index]=true;}
  }
  let mut pending=Vec::new();
  for (index,node)in pins.iter().enumerate(){
   if marked[index]||Rc::strong_count(node)>incoming[index].saturating_add(1){marked[index]=true;pending.push(index);}
  }
  while let Some(index)=pending.pop(){for &target in &edges[index]{if !marked[target]{marked[target]=true;pending.push(target);}}}
  let mut cleared=0;
  for (index,node)in pins.iter().enumerate(){if !marked[index]&&node.clear(){cleared+=1;}}
  let retained:Vec<_>=pins.iter().map(Rc::downgrade).collect();
  drop(pins);
  self.nodes=retained.into_iter().filter(|node|node.strong_count()!=0).collect();
  self.threshold=self.nodes.len().saturating_mul(2).max(64);
  cleared
 }
}
impl Drop for NativeClassGc{
 fn drop(&mut self){while self.collect()!=0{}}
}
'''
