"""Live typed dictionary views and borrow-free checked mapping cursors."""
import ast
from dataclasses import dataclass,field

from .native_types import alternatives


@dataclass(frozen=True)
class ViewType:
    index:int
    record:object=field(compare=False,hash=False,repr=False)
    _native_reference_cloneable=True
    _native_mapping_view=True

    @property
    def _native_kind_tag(self):return 'class_mapping_view_'+str(self.index)

    @property
    def _native_owned_kinds(self):
        from .native_classes import shape
        return (shape(self.record.source),)


@dataclass
class ViewRecord:
    index:int
    node:object
    plan:object
    mode:str
    source:object
    element:object
    cursor_emitted:bool=False

    @property
    def kind(self):return ViewType(self.index,self)


def view_kind(kind):return isinstance(kind,ViewType)


OWNER_TRAIT=r'''
trait ClassMappingOwner{
    type Key;type Value;type Canonical:Eq+std::hash::Hash;
    fn mapping(&self)->&RefCell<NativeKeyDict<Self::Key,Self::Value,Self::Canonical>>;
}
impl<K,V,C:Eq+std::hash::Hash> ClassMappingOwner for RefCell<NativeKeyDict<K,V,C>>{
    type Key=K;type Value=V;type Canonical=C;
    fn mapping(&self)->&RefCell<NativeKeyDict<K,V,C>>{self}
}
'''

CURSORS=OWNER_TRAIT+r'''
struct ClassMappingCursor<O:ClassMappingOwner>{source:Option<Rc<O>>,expected:usize,position:usize,remaining:usize,failed:bool}
impl<O:ClassMappingOwner> ClassMappingCursor<O>{
    fn new(source:Rc<O>)->Self{
        let expected=source.mapping().borrow().len();
        Self{source:Some(source),expected,position:0,remaining:expected,failed:false}
    }
    fn length_hint(&self)->usize{
        if self.failed{return 0;}
        self.source.as_ref().map_or(0,|source|if source.mapping().borrow().len()==self.expected{self.remaining}else{0})
    }
    fn next<R,F:FnOnce(&O::Key,&O::Value)->R>(&mut self,project:F)->Result<Option<R>,String>{
        let source=match &self.source{Some(source)=>source.clone(),None=>return Ok(None)};
        let read=source.mapping().borrow();
        if self.failed||read.len()!=self.expected{self.failed=true;return Err("RuntimeError: dictionary changed size during iteration".to_owned());}
        let mut position=self.position;
        while position<read.entries.positions.len()&&read.entries.positions[position]==NATIVE_ENTRY_NONE{position+=1;}
        if position>=read.entries.positions.len(){drop(read);self.source=None;return Ok(None);}
        if self.remaining==0{drop(read);self.source=None;return Err("RuntimeError: dictionary keys changed during iteration".to_owned());}
        let slot=read.entries.positions[position];self.position=position+1;self.remaining-=1;
        let pair=&read.entries[slot];Ok(Some(project(&pair.0,&pair.1)))
    }
}
'''



class Views:
    def __init__(self,mappings):
        self.mappings=mappings;self.model=mappings.model;self.records=[];self.sites={};self.iteration_elements={}

    def positions_enabled(self):
        from .native_classes import shape
        from .native_dictionary_positions import primitive_sources,dictionary_kind
        return any(dictionary_kind(kind)for source in primitive_sources(self.model)for kind in alternatives(shape(source)))

    def hint_cursor(self,emitter,node,kind,code):
        from .native_classes import shape
        self.require_positions(kind,node)
        sources=alternatives(shape(kind.record.source))if view_kind(kind)else(kind,)
        if not view_kind(kind):return '('+code+').length_hint()'
        record=kind.record;arms=[]
        for index,source in enumerate(sources):
            arms.append('ClassMappingViewCursor_'+str(record.index)+'::V'+str(index)+'(cursor)=>cursor.length_hint()')
        return 'match &('+code+'){'+','.join(arms)+'}'

    def require_positions(self,kind,node):
        from .native_classes import shape,ClassUnsupported
        from .native_dictionary_positions import proved,dictionary_kind
        if not dictionary_kind(kind):return
        sources=alternatives(shape(kind.record.source))if view_kind(kind)else(kind,)
        if not all(proved(source,self.model)for source in sources):
            raise ClassUnsupported(node,'this dictionary cursor comes from an unproved constructor/copy origin; its entry-position history and remaining-length hint are not implemented',types=(('dictionary cursor source',kind),),proof='source-owned dictionary entry-position history')

    def snapshot(self):
        from .native_classes import shape
        return tuple((r.mode,shape(r.source),shape(r.element))for r in self.records)

    def analyze(self,plan,node,receiver,arguments,keywords):
        from .native_classes import Cell,shape,ClassUnsupported
        from .native_class_mappings import mapping_kind
        if node.func.attr not in {'keys','items','values'}:return None
        kinds=alternatives(shape(receiver))
        if not kinds or not all(mapping_kind(kind)and kind.record.category=='dict'for kind in kinds):return None
        if arguments or keywords:
            raise ClassUnsupported(node,'this dictionary view method takes no arguments; its invalid binding must use the builtin method call error protocol',proof='dictionary view method signature')
        key=plan.index,id(node)
        if key not in self.sites:
            self.sites[key]=ViewRecord(len(self.records),node,plan,node.func.attr,Cell(),Cell());self.records.append(self.sites[key])
        record=self.sites[key];self.model.contribute(record.source,receiver,node)
        for kind in kinds:
            owner=kind.record
            element=(owner.key if record.mode=='keys'else owner.value if record.mode=='values'else Cell('tuple',(owner.key,owner.value)))
            self.model.contribute(record.element,element,node)
        return self.model.cell(plan,node,record.kind)

    def element(self,kind):
        from .native_class_mappings import mapping_kind
        from .native_set_cursors import accepts
        if accepts(self.model,kind):return kind.record.key
        if mapping_kind(kind)and kind.record.category=='dict':return kind.record.key
        if view_kind(kind):return kind.record.element
        choices=alternatives(kind)
        if len(choices)>1:
            values=[self.element(choice)for choice in choices]
            if all(value is not None for value in values):
                from .native_classes import Cell
                if kind not in self.iteration_elements:self.iteration_elements[kind]=Cell()
                result=self.iteration_elements[kind]
                if not self.model.final:
                    for choice,value in zip(choices,values):self.model.contribute(result,value,choice.record.node)
                return result
        return None

    def validate(self,kind,node,seen):
        from .native_classes import shape,ClassUnsupported
        if not 0<=kind.index<len(self.records)or self.records[kind.index]is not kind.record:
            raise ClassUnsupported(node,'this dictionary view has no registered typed source/lifetime family',proof='registered live dictionary view')
        marker=('mapping_view',kind.index)
        if marker in seen:raise ClassUnsupported(node,'this live view closes a recursive mapping ownership cycle; cycle-aware mapping/view lifetime is not implemented',proof='acyclic view ownership')
        for source in alternatives(shape(kind.record.source)):self.mappings.validate(source,node,seen|{marker})

    def add_lifetime_edges(self,edges,targets):
        from .native_classes import shape
        for record in self.records:edges[('mapping_view',record.index)]=set(targets(shape(record.source)))

    def emit(self,emitter,node,owner,wanted):
        record=wanted.record
        return 'Rc::new(ClassMappingView_'+str(record.index)+'{source:'+owner.code+'})'

    def rust_type(self,kind):return 'Rc<ClassMappingView_'+str(kind.index)+'>'

    def length(self,emitter,value):
        from .native_classes import shape
        from .native_unions import project,union_kind
        source=shape(value.kind.record.source);text='('+value.code+').source.clone()'
        def branch(kind,code):return '{let owner='+code+';let length=owner.borrow().len();length}'
        return project(source,text,branch)if union_kind(source)else branch(source,text)

    def truth(self,emitter,value):return '('+self.length(emitter,value)+'>0)'

    def show(self,emitter,value,node):
        from .native_classes import Expression,shape
        from .native_unions import project,union_kind
        record=value.kind.record;source=shape(record.source)
        def branch(kind,code):
            key,item,owner,read=(emitter.fresh()for _ in range(4))
            part=self.project(emitter,kind,record.mode,key,item)
            display=emitter.show(part,node,True)
            return '{let '+owner+'='+code+';let '+read+'='+owner+'.borrow();format!("dict_'+record.mode+'([{}])",'+read+'.entries.iter().map(|('+key+','+item+')|'+display+').collect::<Vec<_>>().join(", "))}'
        text='('+value.code+').source.clone()'
        return project(source,text,branch)if union_kind(source)else branch(source,text)

    def project(self,emitter,kind,mode,key,value):
        from .native_classes import Expression,shape
        from .native_types import TupleType
        k,v=shape(kind.record.key),shape(kind.record.value)
        if mode=='keys':return Expression('('+key+').clone()',k)
        if mode=='values':return Expression('('+value+').clone()',v)
        return Expression('('+key+'.clone(),'+value+'.clone())',TupleType((k,v)))

    def cursor_payload(self,emitter,kind):
        from .native_classes import shape
        from .native_class_mappings import mapping_kind,canonical_type
        from .native_set_cursors import accepts,payload
        if accepts(self.model,kind):return payload(emitter,kind)
        if view_kind(kind):
            kind.record.cursor_emitted=True
            return 'ClassMappingViewCursor_'+str(kind.index)
        if mapping_kind(kind)and kind.record.category=='dict':
            r=kind.record
            owner=self.model.mappings.defaultdicts.owner_type(r)if r.flavor=='defaultdict'else'RefCell<NativeKeyDict<'+emitter.rust_type(shape(r.key))+','+emitter.rust_type(shape(r.value))+','+canonical_type(shape(r.key))+'>>'
            return 'ClassMappingCursor<'+owner+'>'
        return None

    def construct_cursor(self,emitter,kind,code):
        from .native_classes import shape
        from .native_unions import project,union_kind
        from .native_set_cursors import accepts,construct
        if accepts(self.model,kind):return construct(code)
        self.require_positions(kind,kind.record.node)
        if not view_kind(kind):return 'ClassMappingCursor::new('+code+')'
        record=kind.record;record.cursor_emitted=True;source=shape(record.source);choices=alternatives(source)
        def branch(part,text):return 'ClassMappingViewCursor_'+str(record.index)+'::V'+str(choices.index(part))+'(ClassMappingCursor::new(('+text+').clone()))'
        text='('+code+').source.clone()'
        return project(source,text,branch)if union_kind(source)else branch(source,text)

    def pull_cursor(self,emitter,node,kind,code,wanted):
        from .native_classes import shape
        from .native_set_cursors import accepts,pull
        if accepts(self.model,kind):return pull(emitter,node,kind,code,wanted)
        if not view_kind(kind):
            part=self.project(emitter,kind,'keys','key','value')
            converted=emitter.coerce(part,wanted,node)
            return emitter.at(code+'.next(|key,value|'+converted+')',node)
        record=kind.record;arms=[]
        for index,source in enumerate(alternatives(shape(record.source))):
            part=self.project(emitter,source,record.mode,'key','value')
            converted=emitter.coerce(part,wanted,node)
            pull=emitter.at('cursor.next(|key,value|'+converted+')',node)
            arms.append('ClassMappingViewCursor_'+str(record.index)+'::V'+str(index)+'(cursor)=>'+pull)
        return 'match &mut '+code+'{'+','.join(arms)+'}'

    def runtime(self,emitter):
        from .native_classes import shape
        dictionaries=any(record.category=='dict'for record in self.mappings.records)
        result=([CURSORS]if self.positions_enabled()else[OWNER_TRAIT])if dictionaries else[]
        for record in self.records:
            result.append('struct ClassMappingView_'+str(record.index)+'{source:'+emitter.rust_type(shape(record.source))+'}')
            if record.cursor_emitted:
                variants=['V'+str(index)+'('+self.cursor_payload(emitter,source)+')'for index,source in enumerate(alternatives(shape(record.source)))]
                result.append('enum ClassMappingViewCursor_'+str(record.index)+'{'+','.join(variants)+'}')
        return '\n'.join(result)
