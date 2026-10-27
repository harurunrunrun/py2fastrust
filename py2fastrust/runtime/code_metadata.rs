// Static code keeps scope/source/ownership data independently of execution.
type CompiledEntry = fn(&mut Runtime, &mut Frame, usize) -> PyResult<Option<FrameExit>>;
#[derive(Clone,Debug)]
struct CompiledMetadata {
    locations:Vec<(usize,usize)>,
    children:Vec<usize>,
    functions:Vec<usize>,
    comprehension_names:Vec<String>,
    class_cell_load:bool,
    yields:Vec<usize>,
    yield_from:Vec<usize>,
    finally_ends:Vec<(usize,usize)>,
}
impl Code {
    fn instruction_count(&self)->usize {self.compiled_meta.as_ref().map_or_else(||self.ops.len(),|meta|meta.locations.len())}
    fn line_at(&self,position:usize)->usize {self.compiled_meta.as_ref().and_then(|meta|meta.locations.get(position).map(|span|span.0)).or_else(||self.ops.get(position).map(|instruction|instruction.line)).unwrap_or(1)}
    fn is_yield(&self,position:usize)->bool {self.compiled_meta.as_ref().map_or_else(||matches!(self.ops.get(position).map(|instruction|&instruction.op),Some(Op::Yield)),|meta|meta.yields.contains(&position))}
    fn is_yield_from(&self,position:usize)->bool {self.compiled_meta.as_ref().map_or_else(||matches!(self.ops.get(position).map(|instruction|&instruction.op),Some(Op::YieldFrom)),|meta|meta.yield_from.contains(&position))}
    fn function_codes(&self)->Vec<usize> {self.compiled_meta.as_ref().map_or_else(||self.ops.iter().filter_map(|instruction|if let Op::MakeFunction{code,..}=instruction.op{Some(code)}else{None}).collect(),|meta|meta.functions.clone())}
    fn child_codes(&self)->Vec<usize> {self.compiled_meta.as_ref().map_or_else(||self.ops.iter().filter_map(|instruction|match instruction.op{Op::MakeFunction{code,..}|Op::PrepareClass(code)|Op::MakeClass{code,..}|Op::MakeClassEx{code,..}=>Some(code),_=>None}).collect(),|meta|meta.children.clone())}
    fn loads_class_cell(&self)->bool {self.compiled_meta.as_ref().map_or_else(||self.ops.iter().any(|instruction|matches!(&instruction.op,Op::Load(name)if name=="__class__"||name=="super")),|meta|meta.class_cell_load)}
}

impl Runtime {
    fn compiled_frame_checkpoint(&mut self,frame:&Frame,root_index:usize) {
        self.active_future_flags=self.codes[frame.code].future_flags;
        self.active_builtins=frame.builtins.clone();
        self.handled_exception=frame.exception.clone().or_else(||frame.inherited_exception.clone());
        let mut roots=Vec::new();
        Self::frame_roots(frame,&mut roots);
        self.roots.truncate(root_index+1);
        self.roots[root_index]=roots;
        if self.gc_enabled && self.allocations>10000 {self.collect();self.allocations=0;}
    }
    fn find_finally_end(&self, code: usize, start: usize) -> usize {
        if let Some(meta)=&self.codes[code].compiled_meta {return meta.finally_ends.iter().find(|(at,_)|*at==start).map(|(_,end)|*end).unwrap_or(usize::MAX);}
        let mut depth = 0;
        for (i, ins) in self.codes[code].ops.iter().enumerate().skip(start) {
            match ins.op {
                Op::SetupFinally(_) => depth += 1,
                Op::EndFinally => {
                    if depth == 0 {
                        return i;
                    } else {
                        depth -= 1
                    }
                }
                _ => {}
            }
        }
        usize::MAX
    }
    fn comprehension_local_names(&self, code:usize)->Vec<String> {
        let owner=&self.codes[code];
        if let Some(meta)=&owner.compiled_meta {return meta.comprehension_names.clone();}
        let mut inline=Vec::new();
        for instruction in &owner.ops {
            if let Op::BeginComprehension(child)=instruction.op {
                for name in &self.codes[child].locals {
                    if name!=".0" && !name.starts_with(['$', '\0']) && !inline.contains(name) {inline.push(name.clone());}
                }
            }
        }
        if inline.is_empty(){return owner.locals.clone();}
        let mut cells=Vec::new();
        let parameters=&owner.params;
        for instruction in &owner.ops {
            if let Op::MakeFunction{code:child,..}=instruction.op {
                for name in &self.codes[child].frees {
                    if owner.locals.contains(name) && !inline.contains(name) && !parameters.positional.contains(name) && !parameters.kwonly.contains(name) && parameters.vararg.as_ref()!=Some(name) && parameters.kwarg.as_ref()!=Some(name) && !cells.contains(name){cells.push(name.clone());}
                }
            }
        }
        cells.sort();
        let mut names=Vec::new();
        for instruction in &owner.ops {
            let candidates=match &instruction.op {
                Op::BeginComprehension(child)=>self.codes[*child].locals.clone(),
                Op::Load(name)|Op::Store(name)|Op::Delete(name)=>vec![name.clone()],
                _=>Vec::new(),
            };
            for name in candidates {
                if (owner.locals.contains(&name) || inline.contains(&name)) && !cells.contains(&name) && !names.contains(&name){names.push(name);}
            }
        }
        for name in &owner.locals {if !cells.contains(name) && !names.contains(name){names.push(name.clone());}}
        names.extend(cells);names
    }
}
