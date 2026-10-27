// Class statements dispatch through their frame's captured builtins.
impl Runtime {
    fn make_function_value(&mut self,f:&Frame,code:usize,defs:Vec<Value>,kwdefaults:Vec<String>,kwvals:Vec<Value>)->PyResult<Value> {
        let closure=if let Some(scope)=f.comprehensions.last(){Some(scope.namespace)}else if matches!(self.codes[code].kind,ScopeKind::Annotation|ScopeKind::TypeParameters){Some(f.locals)}else{
            match self.codes[f.code].kind {ScopeKind::Class=>f.closure,ScopeKind::Module=>None,_=>Some(f.locals)}
        };
        let defaults_set=!defs.is_empty();
        let attrs=self.alloc(Object::Dict(Vec::new()));
        let annotations=self.obj_value(Object::Dict(Vec::new()));
        let type_params=self.obj_value(Object::Tuple(Vec::new()));
        let name=self.code_constant(code,Const::Str(self.codes[code].name.clone()))?;
        let qualname=self.code_constant(code,Const::Str(self.codes[code].qualname.clone()))?;
        let doc=match self.codes[code].docstring.clone(){Some(value)=>self.code_constant(code,Const::Str(value))?,_=>Value::None};
        let mut roots=defs.clone();roots.extend(kwvals.iter().cloned());
        roots.extend([Value::Obj(attrs),annotations.clone(),type_params.clone(),doc.clone(),Value::Obj(f.globals),f.builtins.clone()]);
        roots.extend(closure.map(Value::Obj));
        self.view_rooted(roots,|runtime,root|{
            // Retain exactly the shared free-variable cells, rather than the
            // enclosing namespace and every unrelated local it contains.
            // Otherwise a namespace's own function binding manufactures a
            // reference cycle and keeps acyclic buffer exports alive.
            let names=runtime.closure_names(code);
            let closure=if names.is_empty(){None}else{
                let mut cells=Vec::with_capacity(names.len());
                for name in names {
                    let cell=Value::Obj(runtime.closure_cell(closure,&name)?);
                    runtime.roots[root].push(cell.clone());cells.push(cell);
                }
                let namespace=runtime.closure_namespace(code,&cells);
                runtime.roots[root].push(Value::Obj(namespace));Some(namespace)
            };
            let module=runtime.global_name_get(f.globals,"__name__")?.unwrap_or(Value::None);
            runtime.roots[root].push(module.clone());
            let builtins=runtime.capture_builtins(f.globals,f.builtins.clone())?;
            Ok(runtime.obj_value(Object::Function(Function{
                annotate:None,annotations_evaluated:false,attrs,name,qualname,module,doc,annotations,type_params,
                code,globals:f.globals,builtins,closure,defaults:defs,defaults_set,kwdefaults:kwdefaults.into_iter().zip(kwvals).collect(),
            })))
        })
    }
    fn builtin_build_class(&mut self,args:Vec<Value>,kwargs:KeywordArgs,caller:Option<&Frame>)->PyResult<Value> {
        if args.len()<2 {return Err(pyerr("TypeError","__build_class__: not enough arguments"));}
        let owner=args[0].clone();
        if !matches!(&owner,Value::Obj(index)if matches!(self.heap.get(*index).and_then(Option::as_ref),Some(Object::Function(_)))) {
            return Err(pyerr("TypeError","__build_class__: func must be a function"));
        }
        if !matches!(self.native_payload(&args[1]).unwrap_or_else(||args[1].clone()),Value::Str(_)) {return Err(pyerr("TypeError","__build_class__: name is not a string"));}
        self.make_class(owner,args[1].clone(),args[2..].to_vec(),kwargs,caller)
    }
}

impl Runtime {
    fn import_statement(&mut self,frame:&Frame,module:&str,names:&[String],level:usize)->PyResult<Value> {
        let importer=self.builtin_lookup(frame.builtins.clone(),"__import__")?.ok_or_else(||pyerr("ImportError","__import__ not found"))?;
        let fromlist=if names.is_empty(){Value::None}else{
            let key=LiteralKey::ImportNames(names.to_vec());
            if let Some(value)=self.literal_pools.get(&frame.code).and_then(|pool|pool.get(&key)){value.clone()}
            else{
                let names=names.iter().map(|name|Value::Str(self.intern_keyword(name))).collect();
                let value=self.obj_value(Object::Tuple(names));
                self.literal_pools.entry(frame.code).or_default().insert(key,value.clone());value
            }
        };
        let locals=if matches!(self.codes[frame.code].kind,ScopeKind::Module|ScopeKind::Class){self.execution_locals_value(frame.locals)}else{Value::None};
        let name=Value::Str(self.intern_keyword(module));
        self.call(importer,vec![name,Value::Obj(frame.globals),locals,fromlist,Value::Int(Int::from_i128(level as i128).into())],Vec::new(),Some(frame))
    }
    fn import_from(&mut self,module:Value,name:&str)->PyResult<Value> {
        match self.getattr(module.clone(),name){
            Ok(value)=>Ok(value),
            Err(error) if self.exception_has_native_class(&error,"AttributeError")=>{
                let module_name=match self.getattr(module,"__name__") {Ok(Value::Str(name))=>name.to_string(),Ok(_)=>"<unknown module name>".to_owned(),Err(error) if self.exception_has_native_class(&error,"AttributeError")=>"<unknown module name>".to_owned(),Err(error)=>return Err(error)};
                if let Some(value)=self.modules.get(&format!("{module_name}.{name}")){return Ok(value.clone());}
                Err(pyerr("ImportError",format!("cannot import name '{name}' from '{module_name}' (unknown location)")))
            }
            Err(error)=>Err(error),
        }
    }
    fn import_star(&mut self,frame:&Frame,module:Value)->PyResult<()> {
        self.view_rooted(vec![module.clone()],|runtime,root|{
            let (names,all)=match runtime.getattr(module.clone(),"__all__") {
                Ok(names)=>(names,true),
                Err(error) if runtime.exception_has_native_class(&error,"AttributeError")=>{
                    let dictionary=runtime.getattr(module.clone(),"__dict__")?;runtime.roots[root].push(dictionary.clone());
                    let keys=runtime.getattr(dictionary,"keys")?;
                    let keys=runtime.call(keys,Vec::new(),Vec::new(),None)?;runtime.roots[root].push(keys.clone());
                    let values=runtime.to_vec(keys)?;(runtime.obj_value(Object::List(values)),false)
                },
                Err(error)=>return Err(error),
            };
            runtime.roots[root].push(names.clone());
            let fixed_roots=runtime.roots[root].len();
            let mut index=0usize;
            loop{
                let name=match runtime.getitem(names.clone(),Value::Int(Int::exact_small(index as i128).into())){
                    Ok(name)=>name,Err(error) if runtime.exception_has_native_class(&error,"IndexError")=>break,Err(error)=>return Err(error),
                };
                runtime.roots[root].push(name.clone());
                let spelling=match runtime.native_payload(&name).unwrap_or_else(||name.clone()) {Value::Str(name)=>name.to_string(),_=>return Err(pyerr("TypeError",format!("Item in {} must be str, not {}",if all {"module.__all__"}else{"module.__dict__"},runtime.typename(&name))))};
                if all || !spelling.starts_with('_') {
                    let value=runtime.getattr(module.clone(),&spelling)?;
                    runtime.setitem(runtime.execution_locals_value(frame.locals),name,value)?;
                }
                runtime.roots[root].truncate(fixed_roots);
                index=index.checked_add(1).ok_or_else(||pyerr("OverflowError","too many imported names"))?;
            }
            Ok(())
        })
    }
    fn import_handle_fromlist(&mut self,module:Value,absolute:&str,fromlist:Value,recursive:bool)->PyResult<()> {
        self.view_rooted(vec![module.clone(),fromlist.clone()],|runtime,root|{
            let iterator=runtime.iter(fromlist)?;runtime.roots[root].push(iterator.clone());
            while let Some(item)=runtime.next(iterator.clone())? {
                let item=match runtime.native_payload(&item).unwrap_or_else(||item.clone()) {Value::Str(item)=>item.to_string(),_=>return Err(pyerr("TypeError",format!("Item in from list must be str, not {}",runtime.typename(&item))))};
                if item=="*" {
                    if !recursive {
                        match runtime.getattr(module.clone(),"__all__") {
                            Ok(names)=>runtime.import_handle_fromlist(module.clone(),absolute,names,true)?,
                            Err(error) if runtime.exception_has_native_class(&error,"AttributeError")=>{},
                            Err(error)=>return Err(error),
                        }
                    }
                    continue;
                }
                match runtime.getattr(module.clone(),&item){Ok(_)=>continue,Err(error) if runtime.exception_has_native_class(&error,"AttributeError")=>{},Err(error)=>return Err(error)};
                let child=format!("{absolute}.{item}");
                match runtime.import_module(&child) {
                    Ok(_)=>{},
                    Err(error) if runtime.exception_has_native_class(&error,"ModuleNotFoundError") && error.message==format!("No module named '{child}'")=>{},
                    Err(error)=>return Err(error),
                }
            }
            Ok(())
        })
    }
    fn import_package(&mut self,globals:usize)->PyResult<String> {
        if let Some(value)=self.global_name_get(globals,"__package__")? {
            if !matches!(value,Value::None){
                return match self.native_payload(&value).unwrap_or(value){Value::Str(package)=>Ok(package.to_string()),_=>Err(pyerr("TypeError","package must be a string"))};
            }
        }
        if let Some(spec)=self.global_name_get(globals,"__spec__")? {
            if !matches!(spec,Value::None){
                let parent=self.getattr(spec,"parent")?;
                return match self.native_payload(&parent).unwrap_or(parent){Value::Str(package)=>Ok(package.to_string()),_=>Err(pyerr("TypeError","__spec__.parent must be a string"))};
            }
        }
        let name=self.global_name_get(globals,"__name__")?.ok_or_else(||pyerr("KeyError","'__name__' not in globals"))?;
        let name=match self.native_payload(&name).unwrap_or(name){Value::Str(name)=>name.to_string(),_=>return Err(pyerr("TypeError","__name__ must be a string"))};
        if self.global_name_get(globals,"__path__")?.is_some(){Ok(name)}else{Ok(name.rsplit_once('.').map(|(parent,_)|parent).unwrap_or("").to_owned())}
    }
    fn builtin_import(&mut self,args:Vec<Value>,kwargs:KeywordArgs)->PyResult<Value> {
        let mut values=codec_bind("__import__",args,kwargs,&["name","globals","locals","fromlist","level"])?;
        let name=values[0].take().ok_or_else(||pyerr("TypeError","__import__() missing required argument 'name' (pos 1)"))?;
        let level=values[4].as_ref().map(|value|self.execution_c_int(value)).transpose()?.unwrap_or(0);
        if level<0{return Err(pyerr("ValueError","level must be >= 0"));}
        let name=match self.native_payload(&name).unwrap_or(name){Value::Str(name)=>name.to_string(),_=>return Err(pyerr("TypeError","module name must be a string"))};
        let globals=values[1].clone().unwrap_or(Value::None);
        let fromlist=values[3].clone().unwrap_or(Value::None);
        if level==0 && name.is_empty(){return Err(pyerr("ValueError","Empty module name"));}
        let absolute=if level==0 {name.clone()}else{
            let globals=match globals {Value::Obj(index) if matches!(self.native_payload(&Value::Obj(index)).unwrap_or(Value::Obj(index)),Value::Obj(owner)if matches!(self.heap.get(owner).and_then(Option::as_ref),Some(Object::Dict(_)|Object::Namespace(..))))=>index,_=>return Err(pyerr("TypeError","globals must be a dict"))};
            let package=self.import_package(globals)?;
            if package.is_empty(){return Err(pyerr("ImportError","attempted relative import with no known parent package"));}
            let mut parts=package.split('.').collect::<Vec<_>>();
            if parts.len()<level as usize {return Err(pyerr("ImportError","attempted relative import beyond top-level package"));}
            for _ in 1..level{parts.pop();}
            let mut absolute=parts.join(".");if !name.is_empty(){absolute.push('.');absolute.push_str(&name);}absolute
        };
        let module=self.import_module(&absolute)?;
        self.view_rooted(vec![module.clone(),fromlist.clone()],|runtime,root|{
            if runtime.truth(&fromlist)? {
                let package=match runtime.getattr(module.clone(),"__path__"){Ok(_)=>true,Err(error) if runtime.exception_has_native_class(&error,"AttributeError")=>false,Err(error)=>return Err(error)};
                if package {runtime.import_handle_fromlist(module.clone(),&absolute,fromlist,false)?;}
                Ok(module)
            }else{
                let top=if level==0 {absolute.split('.').next().unwrap_or("").to_owned()}
                else if name.is_empty(){absolute.clone()}
                else{let count=name.split('.').count();absolute.split('.').take(absolute.split('.').count()-count+1).collect::<Vec<_>>().join(".")};
                runtime.import_module(&top)
            }
        })
    }
}
