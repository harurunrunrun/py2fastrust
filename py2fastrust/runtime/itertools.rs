// Lazy itertools state. Shared groupby/tee cursors use only std and retain explicit
// Python roots so that the VM's tracing collector can see buffered values.
#[derive(Clone, Debug)]
enum ToolsState {
    Accumulate { iter: Value, function: Value, total: Option<Value>, initial: Option<Value>, started: bool },
    Batched { iter: Value, size: usize, strict: bool },
    Chain { outer: Value, inner: Option<Value>, done: bool },
    Combinations { pool: Vec<Value>, indices: Vec<usize>, size: usize, replacement: bool, started: bool, done: bool },
    Compress { data: Value, selectors: Value },
    Count { current: Value, step: Value, started: bool },
    Cycle { iter: Option<Value>, cache: Vec<Value>, index: usize },
    DropWhile { predicate: Value, iter: Value, dropping: bool },
    FilterFalse { predicate: Value, iter: Value },
    GroupBy(std::rc::Rc<std::cell::RefCell<ToolsGroup>>),
    Group { shared: std::rc::Rc<std::cell::RefCell<ToolsGroup>>, generation: usize, key: Value },
    ISlice { iter: Value, start: usize, stop: Option<usize>, step: usize, index: usize, target: usize, done: bool },
    Pairwise { iter: Value, previous: Option<Value> },
    Permutations { pool: Vec<Value>, indices: Vec<usize>, cycles: Vec<usize>, size: usize, started: bool, done: bool },
    Product { pools: Vec<Vec<Value>>, indices: Vec<usize>, started: bool, done: bool },
    Repeat { value: Value, remaining: Option<usize> },
    StarMap { function: Value, iter: Value },
    TakeWhile { predicate: Value, iter: Value, done: bool },
    Tee { shared: std::rc::Rc<std::cell::RefCell<ToolsTee>>, cursor: std::rc::Rc<std::cell::Cell<usize>> },
    ZipLongest { iters: Vec<Option<Value>>, fill: Value, active: usize },
}
#[derive(Clone, Debug)]
struct ToolsGroup { iter: Value, function: Value, current: Option<(Value, Value)>, consumed: bool, active_key: Option<Value>, generation: usize, exhausted: bool }
#[derive(Clone, Debug)]
struct ToolsTee { iter: Value, buffer: std::collections::VecDeque<Value>, base: usize, cursors: Vec<std::rc::Weak<std::cell::Cell<usize>>>, exhausted: bool }
impl ToolsState {
    fn roots(&self) -> Vec<Value> {
        let mut out = Vec::new();
        match self {
            Self::Accumulate { iter,function,total,initial,.. } => { out.push(iter.clone()); out.push(function.clone()); out.extend(total.iter().cloned()); out.extend(initial.iter().cloned()); },
            Self::Batched { iter,.. } | Self::ISlice { iter,.. } => out.push(iter.clone()),
            Self::Chain { outer,inner,.. } => { out.push(outer.clone()); out.extend(inner.iter().cloned()); },
            Self::Combinations { pool,.. } | Self::Permutations { pool,.. } => out.extend(pool.iter().cloned()),
            Self::Compress { data,selectors } => { out.push(data.clone()); out.push(selectors.clone()); },
            Self::Count { current,step,.. } => { out.push(current.clone()); out.push(step.clone()); },
            Self::Cycle { iter,cache,.. } => { out.extend(iter.iter().cloned()); out.extend(cache.iter().cloned()); },
            Self::DropWhile { predicate,iter,.. } | Self::FilterFalse { predicate,iter } | Self::TakeWhile { predicate,iter,.. } => { out.push(predicate.clone()); out.push(iter.clone()); },
            Self::GroupBy(shared) | Self::Group { shared,.. } => { let shared = shared.borrow(); out.push(shared.iter.clone()); out.push(shared.function.clone()); out.extend(shared.active_key.iter().cloned()); if let Some((key,value)) = &shared.current { out.push(key.clone()); out.push(value.clone()); } if let Self::Group { key,.. } = self { out.push(key.clone()); } },
            Self::Pairwise { iter,previous } => { out.push(iter.clone()); out.extend(previous.iter().cloned()); },
            Self::Product { pools,.. } => for pool in pools { out.extend(pool.iter().cloned()); },
            Self::Repeat { value,.. } => out.push(value.clone()),
            Self::StarMap { function,iter } => { out.push(function.clone()); out.push(iter.clone()); },
            Self::Tee { shared,.. } => { let shared = shared.borrow(); out.push(shared.iter.clone()); out.extend(shared.buffer.iter().cloned()); },
            Self::ZipLongest { iters,fill,.. } => { out.extend(iters.iter().flatten().cloned()); out.push(fill.clone()); },
        }
        out
    }
}

impl Runtime {
    fn tools_iterator(&mut self, state: ToolsState) -> Value { self.obj_value(Object::Iterator(IteratorState::Tools(Box::new(state)))) }
    fn tools_arguments(&self, name: &str, args: Vec<Value>, kwargs: Vec<(String,Value)>, names: &[&str], max_positional: usize, positional_only: usize, required: usize) -> PyResult<Vec<Option<Value>>> {
        if args.len() > max_positional { return Err(pyerr("TypeError",format!("{name}() received too many positional arguments"))); }
        let mut bound = vec![None; names.len()]; for (index,value) in args.into_iter().enumerate() { bound[index] = Some(value); }
        for (key,value) in kwargs {
            let index = names.iter().position(|name|*name==key).filter(|index|*index>=positional_only).ok_or_else(||pyerr("TypeError",format!("'{key}' is an invalid keyword argument for {name}()")))?;
            if bound[index].is_some() { return Err(pyerr("TypeError",format!("argument '{key}' given by name and position"))); } bound[index] = Some(value);
        }
        if bound[..required].iter().any(Option::is_none) { return Err(pyerr("TypeError",format!("{name}() is missing a required argument"))); }
        Ok(bound)
    }
    fn tools_integer(&mut self, value: &Value) -> PyResult<i128> {
        self.as_int(value)?.to_i128().ok_or_else(||pyerr("OverflowError","Python int too large to convert to index"))
    }
    fn tools_size(&mut self, value: &Value, negative_zero: bool) -> PyResult<usize> {
        let value = self.tools_integer(value)?;
        if value < 0 { if negative_zero { return Ok(0); } return Err(pyerr("ValueError","argument must be non-negative")); }
        if value > isize::MAX as i128 { return Err(pyerr("OverflowError","Python int too large to convert to index")); }
        Ok(value as usize)
    }
    fn tools_keep(&mut self, root: usize, value: Value) -> Value { self.roots[root].push(value.clone()); value }
    fn tools_pool(&mut self, value: Value, root: usize) -> PyResult<Vec<Value>> {
        let iter = self.iter(value)?; self.roots[root].push(iter.clone()); let mut pool = Vec::new();
        while let Some(value) = self.next(iter.clone())? { pool.push(self.tools_keep(root,value)); }
        Ok(pool)
    }
    fn itertools_call(&mut self, name: &str, args: Vec<Value>, kwargs: Vec<(String,Value)>) -> PyResult<Value> {
        let root = self.roots.len(); let mut roots = args.clone(); roots.extend(kwargs.iter().map(|(_,value)|value.clone())); self.roots.push(roots);
        let result = self.itertools_construct(name,args,kwargs,root); self.roots.truncate(root); result
    }
    fn itertools_construct(&mut self, name: &str, args: Vec<Value>, kwargs: Vec<(String,Value)>, root: usize) -> PyResult<Value> {
        let zero = || Value::Int(Int::from_i128(0).into()); let one = || Value::Int(Int::from_i128(1).into());
        let state = match name {
            "accumulate" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["iterable","func","initial"],2,0,1)?;
                let iter = self.iter(a[0].take().unwrap())?; let function = a[1].take().unwrap_or(Value::None); let initial = a[2].take().filter(|v|!matches!(v,Value::None));
                ToolsState::Accumulate { iter,function,total:None,initial,started:false }
            }
            "batched" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["iterable","n","strict"],2,0,2)?;
                let size = self.tools_size(a[1].as_ref().unwrap(),false)?; if size==0 { return Err(pyerr("ValueError","n must be at least one")); }
                let strict = if let Some(value) = a[2].take() { self.truth(&value)? } else { false }; let iter = self.iter(a[0].take().unwrap())?;
                ToolsState::Batched { iter,size,strict }
            }
            "chain" => {
                if !kwargs.is_empty() { return Err(pyerr("TypeError","chain() takes no keyword arguments")); }
                let input = self.obj_value(Object::Tuple(args)); self.tools_keep(root,input.clone()); let outer = self.iter(input)?; ToolsState::Chain { outer,inner:None,done:false }
            }
            "chain.from_iterable" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["iterable"],1,1,1)?; let outer = self.iter(a[0].take().unwrap())?; ToolsState::Chain { outer,inner:None,done:false }
            }
            "combinations" | "combinations_with_replacement" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["iterable","r"],2,0,2)?;
                let size = self.tools_size(a[1].as_ref().unwrap(),false)?; let pool = self.tools_pool(a[0].take().unwrap(),root)?; let replacement = name=="combinations_with_replacement";
                let done = if replacement { pool.is_empty() && size!=0 } else { size>pool.len() };
                let indices = if done { Vec::new() } else if replacement { vec![0;size] } else { (0..size).collect() };
                ToolsState::Combinations { pool,indices,size,replacement,started:false,done }
            }
            "compress" => { let mut a = self.tools_arguments(name,args,kwargs,&["data","selectors"],2,0,2)?; let data = self.iter(a[0].take().unwrap())?; self.tools_keep(root,data.clone()); let selectors = self.iter(a[1].take().unwrap())?; ToolsState::Compress { data,selectors } }
            "count" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["start","step"],2,0,0)?; let mut current = a[0].take().unwrap_or_else(zero); let step = a[1].take().unwrap_or_else(one);
                if !matches!(current,Value::Int(_) | Value::Float(_) | Value::Bool(_)) || !matches!(step,Value::Int(_) | Value::Float(_) | Value::Bool(_)) { return Err(pyerr("TypeError","a number is required")); }
                if matches!(&step,Value::Int(value) if *value==Int::from_i128(1)) || matches!(step,Value::Bool(true)) { if let Value::Bool(value)=current { current=Value::Int(Int::from_i128(if value{1}else{0}).into()); } }
                ToolsState::Count { current,step,started:false }
            }
            "cycle" => { let mut a = self.tools_arguments(name,args,kwargs,&["iterable"],1,1,1)?; ToolsState::Cycle { iter:Some(self.iter(a[0].take().unwrap())?),cache:Vec::new(),index:0 } }
            "dropwhile" | "filterfalse" | "takewhile" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["predicate","iterable"],2,2,2)?; let predicate = a[0].take().unwrap(); let iter = self.iter(a[1].take().unwrap())?;
                match name { "dropwhile"=>ToolsState::DropWhile { predicate,iter,dropping:true },"filterfalse"=>ToolsState::FilterFalse { predicate,iter },_=>ToolsState::TakeWhile { predicate,iter,done:false } }
            }
            "groupby" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["iterable","key"],2,0,1)?; let iter = self.iter(a[0].take().unwrap())?; let function = a[1].take().unwrap_or(Value::None);
                ToolsState::GroupBy(std::rc::Rc::new(std::cell::RefCell::new(ToolsGroup { iter,function,current:None,consumed:false,active_key:None,generation:0,exhausted:false })))
            }
            "islice" => {
                if !kwargs.is_empty() || args.len()<2 || args.len()>4 { return Err(pyerr("TypeError","islice() requires 2 to 4 positional arguments")); }
                let index = |rt: &mut Self,value: Option<&Value>,default: Option<usize>| -> PyResult<Option<usize>> {
                    match value { None | Some(Value::None)=>Ok(default),Some(value)=>{let n=rt.tools_integer(value).map_err(|_|pyerr("ValueError","Indices for islice() must be None or an integer: 0 <= x <= sys.maxsize"))?;if n<0||n>isize::MAX as i128{return Err(pyerr("ValueError","Indices for islice() must be None or an integer: 0 <= x <= sys.maxsize"));}Ok(Some(n as usize))} }
                };
                let (start,stop,step) = if args.len()==2 { (0,index(self,args.get(1),None)?,1) } else { (index(self,args.get(1),Some(0))?.unwrap(),index(self,args.get(2),None)?,index(self,args.get(3),Some(1))?.unwrap()) };
                if step==0 { return Err(pyerr("ValueError","Step for islice() must be a positive integer or None")); }
                let iter = self.iter(args[0].clone())?; ToolsState::ISlice { iter,start,stop,step,index:0,target:start,done:false }
            }
            "pairwise" => { let mut a = self.tools_arguments(name,args,kwargs,&["iterable"],1,1,1)?; ToolsState::Pairwise { iter:self.iter(a[0].take().unwrap())?,previous:None } }
            "permutations" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["iterable","r"],2,0,1)?; let pool = self.tools_pool(a[0].take().unwrap(),root)?;
                let size = if let Some(value) = a[1].take().filter(|v|!matches!(v,Value::None)) { self.tools_size(&value,false)? } else { pool.len() }; let done = size>pool.len();
                let indices = (0..pool.len()).collect(); let cycles = if done { Vec::new() } else { (0..size).map(|index|pool.len()-index).collect() };
                ToolsState::Permutations { pool,indices,cycles,size,started:false,done }
            }
            "product" => {
                let mut repeat = 1; let mut found = false;
                for (key,value) in kwargs { if key!="repeat" || found { return Err(pyerr("TypeError","invalid keyword argument for product()")); } repeat = self.tools_size(&value,false)?; found=true; }
                let mut originals = Vec::new(); if repeat!=0 { for arg in args { originals.push(self.tools_pool(arg,root)?); } }
                let count = originals.len().checked_mul(repeat).ok_or_else(||pyerr("OverflowError","repeat argument is too large"))?;
                let mut pools = Vec::new(); pools.try_reserve(count).map_err(|_|pyerr("MemoryError","cannot allocate product pools"))?; for _ in 0..repeat { pools.extend(originals.iter().cloned()); }
                let done = pools.iter().any(Vec::is_empty); let indices = vec![0;pools.len()]; ToolsState::Product { pools,indices,started:false,done }
            }
            "repeat" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["object","times"],2,0,1)?; let value = a[0].take().unwrap(); let remaining = if let Some(times) = a[1].take() { Some(self.tools_size(&times,true)?) } else { None }; ToolsState::Repeat { value,remaining }
            }
            "starmap" => { let mut a = self.tools_arguments(name,args,kwargs,&["function","iterable"],2,2,2)?; let function = a[0].take().unwrap(); let iter = self.iter(a[1].take().unwrap())?; ToolsState::StarMap { function,iter } }
            "tee" => {
                let mut a = self.tools_arguments(name,args,kwargs,&["iterable","n"],2,2,1)?; let count = if let Some(value) = a[1].take() { self.tools_size(&value,false)? } else { 2 }; let source = self.iter(a[0].take().unwrap())?;
                let existing = match &source { Value::Obj(index)=>match self.object(*index)? { Object::Iterator(IteratorState::Tools(state))=>if let ToolsState::Tee { shared,cursor } = *state { Some((shared,cursor.get())) }else{None},_=>None },_=>None };
                let (shared,position) = existing.unwrap_or_else(||(std::rc::Rc::new(std::cell::RefCell::new(ToolsTee { iter:source,buffer:std::collections::VecDeque::new(),base:0,cursors:Vec::new(),exhausted:false })),0));
                let mut tees = Vec::new(); tees.try_reserve(count).map_err(|_|pyerr("MemoryError","cannot allocate tee iterators"))?;
                for _ in 0..count { let cursor = std::rc::Rc::new(std::cell::Cell::new(position)); shared.borrow_mut().cursors.push(std::rc::Rc::downgrade(&cursor)); let value = self.tools_iterator(ToolsState::Tee { shared:shared.clone(),cursor }); self.tools_keep(root,value.clone()); tees.push(value); }
                return Ok(self.obj_value(Object::Tuple(tees)));
            }
            "zip_longest" => {
                let mut fill = Value::None; let mut found = false; for (key,value) in kwargs { if key!="fillvalue" || found { return Err(pyerr("TypeError","invalid keyword argument for zip_longest()")); } fill=value; found=true; }
                let mut iters = Vec::new(); for arg in args { let iter=self.iter(arg)?; self.tools_keep(root,iter.clone()); iters.push(Some(iter)); } let active=iters.len(); ToolsState::ZipLongest { iters,fill,active }
            }
            _ => return Err(pyerr("AttributeError",format!("module 'itertools' has no attribute '{name}'"))),
        };
        Ok(self.tools_iterator(state))
    }
    fn tools_group_advance(&mut self, shared: &std::rc::Rc<std::cell::RefCell<ToolsGroup>>, root: usize) -> PyResult<bool> {
        let (iter,function,exhausted) = { let state=shared.borrow(); (state.iter.clone(),state.function.clone(),state.exhausted) };
        if exhausted { return Ok(false); }
        if let Some(value) = self.next(iter)? {
            self.tools_keep(root,value.clone()); let key = if matches!(function,Value::None) { value.clone() } else { self.call(function,vec![value.clone()],Vec::new(),None)? }; self.tools_keep(root,key.clone());
            let mut state=shared.borrow_mut(); state.current=Some((key,value)); state.consumed=false; Ok(true)
        } else { let mut state=shared.borrow_mut();state.exhausted=true;state.current=None;Ok(false) }
    }
    fn tool_next(&mut self, state: &mut ToolsState) -> PyResult<Option<Value>> {
        let root = self.roots.len(); self.roots.push(state.roots()); let result=self.tool_next_inner(state,root); self.roots.truncate(root); result
    }
    fn tool_next_inner(&mut self, state: &mut ToolsState, root: usize) -> PyResult<Option<Value>> {
        match state {
            ToolsState::Accumulate { iter,function,total,initial,started } => {
                if !*started { *started=true; if let Some(value)=initial.take() { *total=Some(value.clone());return Ok(Some(value)); } }
                let value=match self.next(iter.clone())?{Some(value)=>self.tools_keep(root,value),None=>return Ok(None)};
                let value=if let Some(previous)=total.clone(){if matches!(function,Value::None){self.binary("+",previous,value)?}else{self.call(function.clone(),vec![previous,value],Vec::new(),None)?}}else{value};
                *total=Some(value.clone());Ok(Some(value))
            }
            ToolsState::Batched { iter,size,strict } => {
                let mut batch=Vec::new(); for _ in 0..*size { if let Some(value)=self.next(iter.clone())?{batch.push(self.tools_keep(root,value))}else{break} }
                if batch.is_empty(){Ok(None)}else if *strict&&batch.len()!=*size{Err(pyerr("ValueError","batched(): incomplete batch"))}else{Ok(Some(self.obj_value(Object::Tuple(batch))))}
            }
            ToolsState::Chain { outer,inner,done } => loop {
                if *done { return Ok(None); }
                if let Some(iter)=inner { if let Some(value)=self.next(iter.clone())?{return Ok(Some(value));} *inner=None; }
                let value=match self.next(outer.clone()){Ok(Some(value))=>self.tools_keep(root,value),Ok(None)=>{*done=true;return Ok(None)},Err(error)=>{*done=true;return Err(error)}}; let iter=match self.iter(value){Ok(iter)=>iter,Err(error)=>{*done=true;return Err(error)}}; self.tools_keep(root,iter.clone()); *inner=Some(iter);
            },
            ToolsState::Combinations { pool,indices,size,replacement,started,done } => {
                if *done{return Ok(None)}
                if *started {
                    if *size==0{*done=true;return Ok(None)}
                    let mut changed=false;
                    for index in (0..*size).rev(){let limit=if *replacement{pool.len()-1}else{index+pool.len()-*size};if indices[index]<limit{indices[index]+=1;for next in index+1..*size{indices[next]=if *replacement{indices[index]}else{indices[next-1]+1};}changed=true;break;}}
                    if !changed{*done=true;return Ok(None)}
                }else{*started=true;}
                Ok(Some(self.obj_value(Object::Tuple(indices.iter().map(|index|pool[*index].clone()).collect()))))
            }
            ToolsState::Compress { data,selectors } => loop {
                let value=match self.next(data.clone())?{Some(value)=>self.tools_keep(root,value),None=>return Ok(None)};
                let selector=match self.next(selectors.clone())?{Some(value)=>self.tools_keep(root,value),None=>return Ok(None)};if self.truth(&selector)?{return Ok(Some(value))}
            },
            ToolsState::Count { current,step,started } => {if *started{*current=self.binary("+",current.clone(),step.clone())?;}else{*started=true;}Ok(Some(current.clone()))},
            ToolsState::Cycle { iter,cache,index } => {
                if let Some(source)=iter {if let Some(value)=self.next(source.clone())?{cache.push(value.clone());return Ok(Some(value));}*iter=None;}
                if cache.is_empty(){Ok(None)}else{let value=cache[*index].clone();*index=(*index+1)%cache.len();Ok(Some(value))}
            }
            ToolsState::DropWhile { predicate,iter,dropping } => loop {
                let value=match self.next(iter.clone())?{Some(value)=>self.tools_keep(root,value),None=>return Ok(None)};
                if *dropping{let test=self.call(predicate.clone(),vec![value.clone()],Vec::new(),None)?;if self.truth(&test)?{continue;}*dropping=false;}return Ok(Some(value));
            },
            ToolsState::FilterFalse { predicate,iter } => loop {
                let value=match self.next(iter.clone())?{Some(value)=>self.tools_keep(root,value),None=>return Ok(None)};let test=if matches!(predicate,Value::None){value.clone()}else{self.call(predicate.clone(),vec![value.clone()],Vec::new(),None)?};if !self.truth(&test)?{return Ok(Some(value))}
            },
            ToolsState::GroupBy(shared) => {
                loop {
                    let (current,consumed,active,exhausted)={let state=shared.borrow();(state.current.clone(),state.consumed,state.active_key.clone(),state.exhausted)};
                    if exhausted{return Ok(None)}
                    match current {None=>{if !self.tools_group_advance(shared,root)?{return Ok(None)}},Some((key,_))=>{if consumed {if !self.tools_group_advance(shared,root)?{return Ok(None)}}else if let Some(active)=active{if self.identical_or_equal(&key,&active)?{if !self.tools_group_advance(shared,root)?{return Ok(None)}}else{break}}else{break}}}
                }
                let (key,generation)={let mut state=shared.borrow_mut();let key=state.current.as_ref().unwrap().0.clone();state.active_key=Some(key.clone());state.generation=state.generation.checked_add(1).ok_or_else(||pyerr("OverflowError","too many groups"))?;(key,state.generation)};
                let group=self.tools_iterator(ToolsState::Group { shared:shared.clone(),generation,key:key.clone() });self.tools_keep(root,group.clone());Ok(Some(self.obj_value(Object::Tuple(vec![key,group]))))
            }
            ToolsState::Group { shared,generation,key } => {
                let (actual,consumed)={let state=shared.borrow();(state.generation,state.consumed)};if actual!=*generation{return Ok(None)}
                if consumed && !self.tools_group_advance(shared,root)?{return Ok(None)}
                let current=shared.borrow().current.clone();if let Some((current_key,value))=current{if self.identical_or_equal(&current_key,key)?{shared.borrow_mut().consumed=true;return Ok(Some(value));}}Ok(None)
            }
            ToolsState::ISlice { iter,start,stop,step,index,target,done } => {
                if *done{return Ok(None)}
                let limit=stop.map(|stop|stop.max(*start));
                while limit.is_none_or(|limit|*index<limit){let position=*index;let value=match self.next(iter.clone())?{Some(value)=>value,None=>{*done=true;return Ok(None)}};*index=index.checked_add(1).ok_or_else(||pyerr("OverflowError","islice index overflow"))?;
                    if position==*target && stop.is_none_or(|stop|position<stop){*target=target.saturating_add(*step);return Ok(Some(value));}
                }*done=true;Ok(None)
            }
            ToolsState::Pairwise { iter,previous } => {
                if previous.is_none(){match self.next(iter.clone())?{Some(value)=>{self.tools_keep(root,value.clone());*previous=Some(value);},None=>return Ok(None)}}
                if let Some(value)=self.next(iter.clone())?{let previous=previous.replace(value.clone()).unwrap();Ok(Some(self.obj_value(Object::Tuple(vec![previous,value]))))}else{Ok(None)}
            }
            ToolsState::Permutations { pool,indices,cycles,size,started,done } => {
                if *done{return Ok(None)}
                if *started {let mut changed=false;for index in (0..*size).rev(){cycles[index]-=1;if cycles[index]==0{indices[index..].rotate_left(1);cycles[index]=pool.len()-index;}else{let next=pool.len()-cycles[index];indices.swap(index,next);changed=true;break;}}if !changed{*done=true;return Ok(None)}}else{*started=true;}
                Ok(Some(self.obj_value(Object::Tuple(indices[..*size].iter().map(|index|pool[*index].clone()).collect()))))
            }
            ToolsState::Product { pools,indices,started,done } => {
                if *done{return Ok(None)}
                if *started{let mut changed=false;for index in (0..pools.len()).rev(){indices[index]+=1;if indices[index]<pools[index].len(){changed=true;break;}indices[index]=0;}if !changed{*done=true;return Ok(None)}}else{*started=true;}
                Ok(Some(self.obj_value(Object::Tuple(pools.iter().zip(indices.iter()).map(|(pool,index)|pool[*index].clone()).collect()))))
            }
            ToolsState::Repeat { value,remaining } => {if let Some(remaining)=remaining{if *remaining==0{return Ok(None)}*remaining-=1;}Ok(Some(value.clone()))},
            ToolsState::StarMap { function,iter } => {let value=match self.next(iter.clone())?{Some(value)=>self.tools_keep(root,value),None=>return Ok(None)};let args=self.tools_pool(value,root)?;Ok(Some(self.call(function.clone(),args,Vec::new(),None)?))},
            ToolsState::TakeWhile { predicate,iter,done } => {if *done{return Ok(None)}let value=match self.next(iter.clone())?{Some(value)=>self.tools_keep(root,value),None=>{*done=true;return Ok(None)}};let test=self.call(predicate.clone(),vec![value.clone()],Vec::new(),None)?;if self.truth(&test)?{Ok(Some(value))}else{*done=true;Ok(None)}},
            ToolsState::Tee { shared,cursor } => {
                let position=cursor.get();let (value,iter,exhausted)={let state=shared.borrow();(state.buffer.get(position-state.base).cloned(),state.iter.clone(),state.exhausted)};
                let value=if let Some(value)=value{value}else{if exhausted{return Ok(None)}match self.next(iter)?{Some(value)=>{shared.borrow_mut().buffer.push_back(value.clone());value},None=>{shared.borrow_mut().exhausted=true;return Ok(None)}}};
                cursor.set(position.checked_add(1).ok_or_else(||pyerr("OverflowError","tee index overflow"))?);
                {let mut state=shared.borrow_mut();state.cursors.retain(|cursor|cursor.strong_count()!=0);let oldest=state.cursors.iter().filter_map(std::rc::Weak::upgrade).map(|cursor|cursor.get()).min().unwrap_or(cursor.get());while state.base<oldest{state.buffer.pop_front();state.base+=1;}}
                Ok(Some(value))
            }
            ToolsState::ZipLongest { iters,fill,active } => {
                if *active==0{return Ok(None)}let mut values=Vec::new();for iter in iters{let value=if let Some(source)=iter{match self.next(source.clone()){Ok(Some(value))=>value,Ok(None)=>{*iter=None;*active-=1;if *active==0{return Ok(None)}fill.clone()},Err(error)=>{*active=0;return Err(error)}}}else{fill.clone()};values.push(self.tools_keep(root,value));}Ok(Some(self.obj_value(Object::Tuple(values))))
            }
        }
    }
}
