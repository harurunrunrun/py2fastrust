// Fast native input capabilities are inherited from the dominant base's MRO
// at creation. They do not add visible methods or follow later MRO mutations.
impl Runtime {
    fn class_init_native_capability(&mut self,owner:usize) {
        let Ok(class)=self.mro_class(owner)else{return};
        let flag=[("BaseException",Value::Type("BaseException".into())),("type",Value::Builtin("type".into())),("int",Value::Builtin("int".into())),("bytes",Value::Builtin("bytes".into())),("str",Value::Builtin("str".into())),("tuple",Value::Builtin("tuple".into())),("list",Value::Builtin("list".into())),("dict",Value::Builtin("dict".into()))].into_iter().find_map(|(name,base)|self.mro_cached_subtype(&class.layout_base,&base).then_some(name));
        if let Some(Object::Class(class))=self.heap[owner].as_mut(){class.fast_native=flag;}
    }
    fn class_refresh_native_instances(&mut self,owner:usize)->PyResult<()> {
        let instances:Vec<_>=self.heap.iter().enumerate().filter_map(|(index,object)|match object{Some(Object::BuiltinInstance{class,..})if Self::same_type(class,&Value::Obj(owner))=>Some(index),_=>None}).collect();
        self.view_rooted(instances.iter().map(|index|Value::Obj(*index)).collect(),|runtime,_|{
            for index in instances {
                let value=Value::Obj(index);
                if let Some((base,_))=runtime.class_hidden_payload(&value){runtime.class_hide_allocation(value,base)?;}
            }Ok(())
        })
    }
    fn native_capability_payload(&self,value:&Value,capability:&str)->Option<Value> {
        let primitive=match value {
            Value::Int(_)|Value::Bool(_)=>Some("int"),Value::Str(_)=>Some("str"),Value::Bytes(_)=>Some("bytes"),
            Value::Obj(owner)=>match self.heap.get(*owner).and_then(Option::as_ref){Some(Object::Tuple(_))=>Some("tuple"),Some(Object::List(_))=>Some("list"),Some(Object::Dict(_))=>Some("dict"),_=>None},_=>None,
        };
        if primitive==Some(capability){return Some(value.clone());}
        let class=self.object_class(value)?;let Value::Obj(class)=class else{return None};
        if self.mro_class(class).ok()?.fast_native!=Some(capability){return None;}
        self.class_hidden_payload(value).map(|(_,payload)|payload).or_else(||self.native_payload(value))
    }
    fn native_operand_payload(&self,owner:&str,name:&str,value:&Value)->Value {
        let comparison=["__eq__","__ne__","__lt__","__le__","__gt__","__ge__"].contains(&name);
        let flag=match owner {
            "int"|"bool"=>Some("int"),
            "float"|"complex"=>Some("int"),
            "str"=>Some("str"),"tuple"=>Some("tuple"),"list"=>Some("list"),"dict" if comparison=>Some("dict"),
            "bytes" if comparison=>Some("bytes"),_=>None,
        };
        if let Some(flag)=flag {
            if let Some(payload)=self.native_capability_payload(value,flag){return payload;}
            // These inputs require a fast flag, even when an unusual MRO
            // exposes the native type but the dominant parent had hidden it.
            if !["float","complex"].contains(&owner){return value.clone();}
        }
        self.native_payload(value).unwrap_or_else(||value.clone())
    }
}
