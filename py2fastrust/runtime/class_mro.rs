// Class linearization and transactional base changes. Implemented independently
// from Python 3.14's documented type model and differential behavior probes.
#[derive(Clone,Debug,PartialEq,Eq)]
struct MroShape { family:String, slots:usize, dict:bool, weak:bool, gc:bool, variable:bool }

#[derive(Clone,Debug)]
struct MroPlan { owner:usize, previous:Option<usize>, descriptor:Option<Value>, metaclass:Value }
impl MroPlan {
    fn roots(&self,out:&mut Vec<Value>) {
        out.push(Value::Obj(self.owner));out.extend(self.previous.iter().map(|index|Value::Obj(*index)));
        out.extend(self.descriptor.iter().cloned());out.push(self.metaclass.clone());
    }
}
#[derive(Clone,Debug)]
struct MroChange { owner:usize, previous:Option<usize>, installed:usize, slots:Vec<usize>, allocator:ClassAllocator, allocator_epoch:usize }

impl Runtime {
    fn mro_class(&self,owner:usize)->PyResult<Class> {
        match self.heap.get(owner).and_then(Option::as_ref){Some(Object::Class(class))=>Ok(class.clone()),_=>Err(pyerr("TypeError","expected a class"))}
    }
    fn mro_primary(&self,value:&Value)->Option<Value> {
        match value {
            Value::Obj(owner)=>self.mro_class(*owner).ok().map(|class|class.layout_base),
            Value::Builtin(name) if name=="object"=>None,
            Value::Builtin(name) if name=="bool"=>Some(Value::Builtin("int".into())),
            Value::Type(name)=>{let parent=if name=="ExceptionGroup"{"BaseExceptionGroup"}else{Self::exception_parent(name)};Some(if parent.is_empty(){Value::Builtin("object".into())}else{Value::Type(parent.into())})},
            Value::Builtin(_)=>Some(Value::Builtin("object".into())),
            _=>None,
        }
    }
    fn mro_shape(&self,value:&Value)->MroShape {
        let mut current=value.clone();let mut slots=0usize;let mut outer_flags=None;
        while let Value::Obj(owner)=current {
            let Ok(class)=self.mro_class(owner)else{break};
            if outer_flags.is_none(){outer_flags=Some((class.dict_allowed,class.weakref_allowed));}
            slots=slots.saturating_add(class.own_slot_names.len());current=class.layout_base;
        }
        let value=&current;
        let name=self.class_name(value);
        let family=if let Value::Type(exception)=value {
            let mut name=exception.as_str();
            loop {
                if ["OSError","SyntaxError","UnicodeDecodeError","UnicodeEncodeError","UnicodeTranslateError","BaseExceptionGroup","StopIteration","SystemExit","ImportError","AttributeError","NameError"].contains(&name){break name.to_owned();}
                let next=Self::exception_parent(name);if next.is_empty(){break "BaseException".to_owned();}name=next;
            }
        }else if name=="typing.Generic"{"object".into()}else{name.clone()};
        MroShape{family,slots,dict:outer_flags.map(|flags|flags.0).unwrap_or_else(||self.class_allows_dict(value)),weak:outer_flags.map(|flags|flags.1).unwrap_or_else(||self.class_allows_weakref(value)),
            gc:outer_flags.is_some()||matches!(value,Value::Type(_))||!["object","int","bool","str","bytes","float","complex"].contains(&name.as_str()),
            variable:["int","bool","tuple","bytes","type"].contains(&name.as_str())}
    }
    fn mro_base_chain_subtype(&self,left:&Value,right:&Value)->bool {
        let mut current=Some(left.clone());let mut seen=std::collections::HashSet::new();
        while let Some(value)=current {
            if Self::same_type(&value,right){return true;}
            let key=match &value{Value::Obj(index)=>format!("o{index}"),_=>self.class_name(&value)};
            if !seen.insert(key){break;}
            current=self.mro_primary(&value);
        }false
    }
    fn mro_cached_subtype(&self,left:&Value,right:&Value)->bool {
        if let Value::Obj(owner)=left {
            if let Ok(class)=self.mro_class(*owner) {
                if let Some(mro)=class.mro_value {
                    return matches!(self.heap.get(mro).and_then(Option::as_ref),Some(Object::Tuple(values))if values.iter().any(|value|Self::same_type(value,right)));
                }
                return self.mro_base_chain_subtype(left,right);
            }
        }
        self.class_mro(left,0).is_some_and(|values|values.iter().any(|value|Self::same_type(value,right)))
    }
    fn mro_structural_subtype(&self,left:&Value,right:&Value)->bool {
        let mut pending=vec![left.clone()];let mut seen=std::collections::HashSet::new();
        while let Some(value)=pending.pop(){
            if Self::same_type(&value,right){return true;}
            let key=match &value{Value::Obj(index)=>format!("o{index}"),_=>self.class_name(&value)};
            if !seen.insert(key){continue;}
            if let Value::Obj(owner)=&value {if let Ok(class)=self.mro_class(*owner){pending.extend(class.bases);continue;}}
            pending.extend(self.mro_primary(&value));
        }false
    }
    fn mro_solid(&self,value:&Value)->Value {
        let mut current=value.clone();
        loop {
            if let Value::Obj(owner)=&current {
                if let Ok(class)=self.mro_class(*owner) {
                    if !class.own_slot_names.is_empty(){return current;}
                    current=class.layout_base;continue;
                }
            }
            let Some(parent)=self.mro_primary(&current)else{return current};
            let a=self.mro_shape(&current);let b=self.mro_shape(&parent);
            if a.family!=b.family||a.slots!=b.slots{return current;}
            current=parent;
        }
    }
    fn mro_best_base(&self,bases:&[Value])->PyResult<Value> {
        let mut best=None;let mut winner=None;
        for base in bases {
            if !self.native_is_class(base){return Err(pyerr("TypeError","bases must be types"));}
            if matches!(base,Value::Builtin(name)if ["bool","memoryview","range","slice","NoneType"].contains(&name.as_str())){return Err(pyerr("TypeError","type is not an acceptable base type"));}
            if let Value::Obj(owner)=base {if self.mro_class(*owner)?.mro_value.is_none(){return Err(pyerr("TypeError","cannot extend an incomplete type"));}}
            let candidate=self.mro_solid(base);
            match &winner {
                None=>{best=Some(base.clone());winner=Some(candidate);},
                Some(previous) if self.mro_cached_subtype(previous,&candidate)=>(),
                Some(previous) if self.mro_cached_subtype(&candidate,previous)=>{best=Some(base.clone());winner=Some(candidate);},
                _=>return Err(pyerr("TypeError","multiple bases have instance lay-out conflict")),
            }
        }best.ok_or_else(||pyerr("TypeError","bases must not be empty"))
    }
    fn mro_prepare(&mut self,owner:usize)->PyResult<MroPlan> {
        let class=self.mro_class(owner)?;
        let descriptor=if matches!(&class.metaclass,Value::Builtin(name)if name=="type"){None}else{
            Some(self.class_attribute_lookup(&class.metaclass,"mro").ok_or_else(||pyerr("AttributeError","metaclass has no mro method"))?)
        };
        // Binding a user descriptor can reenter and collect. Return raw lookup
        // state first so the previous MRO is rooted before __get__ can run.
        Ok(MroPlan{owner,previous:class.mro_value,descriptor,metaclass:class.metaclass})
    }
    fn mro_finish(&mut self,plan:MroPlan,result:Value)->PyResult<Option<MroChange>> {
        let mut roots=vec![result.clone()];plan.roots(&mut roots);
        self.view_rooted(roots,|runtime,root|{
            let (tuple,values)=if let Value::Obj(index)=&result {
                if let Some(Object::Tuple(values))=runtime.heap.get(*index).and_then(Option::as_ref){(*index,values.clone())}
                else{let values=runtime.to_vec(result.clone())?;let tuple=runtime.alloc(Object::Tuple(values.clone()));(tuple,values)}
            }else{let values=runtime.to_vec(result.clone())?;let tuple=runtime.alloc(Object::Tuple(values.clone()));(tuple,values)};
            runtime.roots[root].push(Value::Obj(tuple));
            if values.is_empty(){return Err(pyerr("TypeError","type MRO must not be empty"));}
            // C3 already produces a valid class sequence. Python applies the
            // solid-layout result check only to a custom metaclass invocation;
            // checking the still-visible previous MRO here would reject a
            // valid ordinary rebase of a class that owns additional slots.
            if plan.descriptor.is_some() {
                let solid=runtime.mro_solid(&Value::Obj(plan.owner));
                for value in &values {
                    if !runtime.native_is_class(value){return Err(pyerr("TypeError","mro() returned a non-class"));}
                    if !runtime.mro_cached_subtype(&solid,&runtime.mro_solid(value)) {return Err(pyerr("TypeError","mro() returned base with unsuitable layout"));}
                }
            }
            let current=runtime.mro_class(plan.owner)?;
            if current.mro_value!=plan.previous{return Ok(None);}
            let change=MroChange{owner:plan.owner,previous:plan.previous,installed:tuple,slots:current.canonical_slots,allocator:current.allocator,allocator_epoch:current.allocator_epoch};
            if let Some(Object::Class(class))=runtime.heap[plan.owner].as_mut(){class.mro_value=Some(tuple);}
            runtime.mro_refresh_slots(plan.owner);
            runtime.class_refresh_allocator(plan.owner);
            runtime.class_refresh_native_instances(plan.owner)?;
            Ok(Some(change))
        })
    }
    fn mro_recompute(&mut self,owner:usize)->PyResult<Option<MroChange>> {
        // Temporary native fallback. The public prepare/finish plan is also
        // usable by a caller-owned Python-frame continuation adapter.
        let marker=0u8;let address=(&marker as *const u8) as usize;
        let outer=self.mro_native_depth==0;
        let base=self.mro_native_stack_base.unwrap_or(address);
        if self.mro_native_depth>=24||address.abs_diff(base)>1024*1024{return Err(pyerr("RecursionError","native class construction reentry limit exceeded"));}
        if outer{self.mro_native_stack_base=Some(address);}
        self.mro_native_depth+=1;
        let result=self.view_rooted(vec![Value::Obj(owner)],|runtime,root|{
            let plan=runtime.mro_prepare(owner)?;plan.roots(&mut runtime.roots[root]);
            let result=if let Some(descriptor)=&plan.descriptor {
                let method=runtime.bind_descriptor(descriptor.clone(),Some(Value::Obj(owner)),plan.metaclass.clone())?;
                runtime.roots[root].push(method.clone());runtime.call(method,Vec::new(),Vec::new(),None)?
            }
                else{let values=runtime.calculate_class_mro(&Value::Obj(owner),0).ok_or_else(||pyerr("TypeError","Cannot create a consistent method resolution order (MRO)"))?;runtime.obj_value(Object::Tuple(values))};
            runtime.mro_finish(plan,result)
        });self.mro_native_depth-=1;if outer{self.mro_native_stack_base=None;}result
    }
    fn mro_children(&self,parent:&Value)->Vec<usize> {
        let mut children:Vec<_>=self.heap.iter().enumerate().filter_map(|(owner,object)|{
            let Some(Object::Class(class))=object else{return None};
            class.registered_bases.iter().find(|(base,_)|Self::same_type(base,parent)).map(|(_,order)|(*order,owner))
        }).collect();children.sort_by_key(|(order,_)|*order);children.into_iter().map(|(_,owner)|owner).collect()
    }
    fn mro_register_bases(&mut self,owner:usize)->PyResult<()> {
        let class=self.mro_class(owner)?;let start=self.next_subclass_order;
        let end=start.checked_add(class.bases.len()).ok_or_else(||pyerr("OverflowError","subclass registry order exhausted"))?;
        let registered=class.bases.into_iter().enumerate().map(|(offset,base)|(base,start+offset+1)).collect();
        self.next_subclass_order=end;
        if let Some(Object::Class(class))=self.heap[owner].as_mut(){class.registered_bases=registered;}
        Ok(())
    }
    fn mro_slot_storage(&self,owner:usize)->Vec<usize> {
        let Ok(class)=self.mro_class(owner)else{return Vec::new()};let mut result=if let Value::Obj(base)=class.layout_base {
            self.mro_class(base).map(|base|base.canonical_slots).unwrap_or_default()
        }else{Vec::new()};let mut slots=class.own_slots;slots.sort_by(|a,b|a.0.cmp(&b.0));result.extend(slots.into_iter().map(|(_,slot)|slot));result
    }
    fn mro_migrate_slots(&mut self,owner:usize,old:&[usize],new:&[usize]) {
        let instances:Vec<_>=self.instance_slots.keys().copied().filter(|index|{
            match self.heap.get(*index).and_then(Option::as_ref){Some(Object::Instance{class,..}|Object::BuiltinInstance{class,..})=>Self::same_type(class,&Value::Obj(owner)),Some(Object::Exception(error))=>error.class.as_ref().is_some_and(|class|Self::same_type(class,&Value::Obj(owner))),_=>false}
        }).collect();
        for instance in instances {if let Some(values)=self.instance_slots.get_mut(&instance){let mut moved=Vec::new();for (&a,&b) in old.iter().zip(new){if a!=b{if let Some(value)=values.remove(&a){moved.push((b,value));}}}values.extend(moved);}}
    }
    fn mro_refresh_slots(&mut self,owner:usize) {
        let Ok(class)=self.mro_class(owner)else{return};let slots=self.mro_slot_storage(owner);
        self.mro_migrate_slots(owner,&class.canonical_slots,&slots);
        if let Some(Object::Class(class))=self.heap[owner].as_mut(){class.canonical_slots=slots;}
    }
    fn mro_compatible_bases(&self,old:&Value,new:&Value)->bool {
        let old_shape=self.mro_shape(old);let new_shape=self.mro_shape(new);
        if old_shape.gc!=new_shape.gc||old_shape.dict!=new_shape.dict||old_shape.weak!=new_shape.weak||old_shape.variable!=new_shape.variable{return false;}
        let collapse=|value:&Value|{let mut value=value.clone();while let Some(parent)=self.mro_primary(&value){if self.mro_shape(&value)!=self.mro_shape(&parent){break;}value=parent;}value};
        let old=collapse(old);let new=collapse(new);if Self::same_type(&old,&new){return true;}
        match (&old,&new) {
            (Value::Obj(a),Value::Obj(b))=>match (self.mro_class(*a),self.mro_class(*b)){
                (Ok(a),Ok(b))=>Self::same_type(&a.layout_base,&b.layout_base)&&a.own_slot_names==b.own_slot_names&&self.mro_shape(&old)==self.mro_shape(&new),_=>false,
            },_=>false,
        }
    }
    fn mro_rollback(&mut self,changes:&[MroChange]) {
        for change in changes.iter().rev() {
            if let Ok(class)=self.mro_class(change.owner) {
                if class.mro_value==Some(change.installed) {
                    self.mro_migrate_slots(change.owner,&class.canonical_slots,&change.slots);
                    if let Some(Object::Class(class))=self.heap[change.owner].as_mut(){
                        class.mro_value=change.previous;class.canonical_slots=change.slots.clone();
                        if class.allocator_epoch==change.allocator_epoch{class.allocator=change.allocator.clone();}
                    }
                    self.class_refresh_allocator(change.owner);
                    let _=self.class_refresh_native_instances(change.owner);
                }
            }
        }
    }
    fn mro_bases_prepare(&self,owner:usize,value:&Value)->PyResult<(Vec<Value>,Value,Class)> {
        let payload=self.native_payload(value).unwrap_or_else(||value.clone());
        let bases=match payload{Value::Obj(index)=>match self.object(index)?{Object::Tuple(values)=>values,_=>return Err(pyerr("TypeError","__bases__ must be a tuple"))},_=>return Err(pyerr("TypeError","__bases__ must be a tuple"))};
        if bases.is_empty(){return Err(pyerr("TypeError","__bases__ must not be empty"));}
        for base in &bases{
            if !self.native_is_class(base){return Err(pyerr("TypeError","__bases__ items must be classes"));}
            if self.mro_structural_subtype(base,&Value::Obj(owner))||self.class_mro(base,0).is_some_and(|mro|mro.iter().any(|base|Self::same_type(base,&Value::Obj(owner)))){return Err(pyerr("TypeError","a __bases__ item causes an inheritance cycle"));}
        }
        let best=self.mro_best_base(&bases)?;let previous=self.mro_class(owner)?;
        if !self.mro_compatible_bases(&previous.layout_base,&best){return Err(pyerr("TypeError","__bases__ assignment: object layout differs"));}
        Ok((bases,best,previous))
    }
    fn mro_set_bases(&mut self,owner:usize,value:Value)->PyResult<()> {
        let (bases,best,previous)=self.mro_bases_prepare(owner,&value)?;
        let mut roots=vec![Value::Obj(owner),value.clone(),previous.bases_value.clone(),previous.layout_base.clone()];roots.extend(previous.mro_value.iter().map(|index|Value::Obj(*index)));
        self.view_rooted(roots,|runtime,root|{
            if let Some(Object::Class(class))=runtime.heap[owner].as_mut(){class.bases=bases;class.bases_value=value.clone();class.layout_base=best;}
            let mut changes=Vec::new();let mut pending=vec![(owner,Vec::<usize>::new())];
            let result=(||{
                while let Some((current,mut ancestors))=pending.pop(){
                    if ancestors.contains(&current){return Err(pyerr("RecursionError","cyclic pending subclass update"));}
                    ancestors.push(current);
                    runtime.roots[root].push(Value::Obj(current));
                    if let Some(change)=runtime.mro_recompute(current)? {
                        runtime.roots[root].push(Value::Obj(change.installed));runtime.roots[root].extend(change.previous.iter().map(|index|Value::Obj(*index)));
                        changes.push(change);
                        let mut children=runtime.mro_children(&Value::Obj(current));
                        // A copied subclass list owns every pending child even
                        // if an earlier callback drops user references and GC.
                        runtime.roots[root].extend(children.iter().map(|index|Value::Obj(*index)));
                        children.reverse();pending.extend(children.into_iter().map(|owner|(owner,ancestors.clone())));
                    }
                }Ok(())
            })();
            if result.is_err(){runtime.mro_rollback(&changes);}
            if runtime.mro_class(owner)?.bases_value.same_identity(&value) {
                if result.is_err(){if let Some(Object::Class(class))=runtime.heap[owner].as_mut(){class.bases=previous.bases;class.bases_value=previous.bases_value;class.layout_base=previous.layout_base;}}
                else{runtime.mro_register_bases(owner)?;}
            }
            result
        })
    }
}
