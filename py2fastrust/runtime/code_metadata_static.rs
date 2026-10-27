// Metadata access for a program whose code has all been compiled to Rust.
impl Code {
    fn instruction_count(&self)->usize {self.compiled_meta.as_ref().map_or(0,|meta|meta.locations.len())}
    fn line_at(&self,position:usize)->usize {self.compiled_meta.as_ref().and_then(|meta|meta.locations.get(position)).map_or(1,|span|span.0)}
    fn is_yield(&self,position:usize)->bool {self.compiled_meta.as_ref().is_some_and(|meta|meta.yields.contains(&position))}
    fn is_yield_from(&self,position:usize)->bool {self.compiled_meta.as_ref().is_some_and(|meta|meta.yield_from.contains(&position))}
    fn function_codes(&self)->Vec<usize> {self.compiled_meta.as_ref().map_or_else(Vec::new,|meta|meta.functions.clone())}
    fn child_codes(&self)->Vec<usize> {self.compiled_meta.as_ref().map_or_else(Vec::new,|meta|meta.children.clone())}
    fn loads_class_cell(&self)->bool {self.compiled_meta.as_ref().is_some_and(|meta|meta.class_cell_load)}
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
    fn find_finally_end(&self,code:usize,start:usize)->usize {self.codes[code].compiled_meta.as_ref().and_then(|meta|meta.finally_ends.iter().find(|(at,_)|*at==start)).map_or(usize::MAX,|(_,end)|*end)}
    fn comprehension_local_names(&self,code:usize)->Vec<String> {self.codes[code].compiled_meta.as_ref().map_or_else(||self.codes[code].locals.clone(),|meta|meta.comprehension_names.clone())}
}
