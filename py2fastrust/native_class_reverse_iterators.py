"""Closed reverse-source providers share the ordinary typed pull registry."""

def payload(emitter,kind):
    from .native_classes import domain
    return 'NativeReverseRange'if domain(kind)=='range'else'NativeReverseSequence<'+emitter.rust_type(kind)+'>'

def construct(emitter,node,source):
    from .native_classes import domain
    tag=domain(source.kind)
    if tag=='range':return 'NativeReverseRange::new(&('+source.code+'))'
    owner=emitter.fresh()
    if tag=='list':length=owner+'.borrow().len()'
    elif tag=='tuple':length=str(len(source.kind.fields))
    elif tag=='tuple_sequence':length=owner+'.as_slice().len()'
    else:length=owner+'.len()'
    size=emitter.fresh()
    return '{let '+owner+'='+source.code+';let '+size+'='+length+';NativeReverseSequence::new('+owner+','+size+')}'

def pull(emitter,node,kind,source,wanted):
    from .native_classes import Expression,domain
    tag=domain(kind)
    if tag not in {'list','tuple','tuple_sequence','range','str','bytes'}:return 'None::<'+emitter.rust_type(wanted)+'>'
    if tag=='range':
        item=emitter.fresh();converted=emitter.coerce(Expression(item,'int'),wanted,node)
        return source+'.next().map(|'+item+'|'+converted+')'
    owner,end,item=(emitter.fresh()for _ in range(3))
    if tag=='tuple':
        arms=[]
        for index,old in enumerate(kind.fields):
            converted=emitter.coerce(Expression(owner+'.'+str(index)+'.clone()',old),wanted,node)
            arms.append(str(index)+'=>Some(('+converted+',1))')
        body='match '+end+'-1{'+','.join(arms+['_=>None'])+'}'
    else:
        old_kind='int'if tag=='bytes'else'str'if tag=='str'else kind.element
        converted=emitter.coerce(Expression(item,old_kind),wanted,node)
        if tag=='list':read=owner+'.borrow().get('+end+'-1).cloned()';width='1'
        elif tag=='tuple_sequence':read=owner+'.as_slice().get('+end+'-1).cloned()';width='1'
        elif tag=='bytes':read=owner+'.get('+end+'-1).map(|value|class_from_usize(*value as usize))';width='1'
        elif emitter.model.string_mode=='ascii':read=owner+'.as_bytes().get('+end+'-1).map(|value|NativeText::from(*value as char))';width='1'
        else:
            read=owner+'.get(..'+end+').and_then(|value|value.chars().next_back()).map(NativeText::from)';width=item+'.len()'
        # Capture byte width before moving the selected text into a union.
        step=emitter.fresh()
        body=read+'.map(|'+item+'|{let '+step+'='+width+';('+converted+','+step+')})'
    return source+'.next(|'+owner+','+end+'|'+body+')'

def runtime(emitter):
    fixed=r'''
struct NativeReverseRange{cursor:NativeInt,first:NativeInt,step:NativeInt,active:bool}
impl NativeReverseRange{
    fn new(source:&ClassRange)->Self{
        let active=if source.step>0{source.start<source.stop}else{source.start>source.stop};
        let cursor=if !active{source.start}else if source.step>0{
            let distance=(source.stop as u128).wrapping_sub(source.start as u128);
            let remainder=(distance-1)%(source.step as u128);
            source.stop.wrapping_sub(1).wrapping_sub(remainder as NativeInt)
        }else{
            let distance=(source.start as u128).wrapping_sub(source.stop as u128);
            let remainder=(distance-1)%(source.step.unsigned_abs()as u128);
            source.stop.wrapping_add(1).wrapping_add(remainder as NativeInt)
        };
        Self{cursor,first:source.start,step:source.step,active}
    }
    fn next(&mut self)->Option<NativeInt>{
        if !self.active{return None;}
        let value=self.cursor;
        if value==self.first{self.active=false;}else{self.cursor=self.cursor.checked_sub(self.step).expect("proved reverse range endpoint");}
        Some(value)
    }
}
'''
    big=r'''
struct NativeReverseRange{cursor:NativeInt,first:NativeInt,step:NativeInt,active:bool}
impl NativeReverseRange{
    fn new(source:&ClassRange)->Self{
        let active=if source.step.is_negative(){source.start>source.stop}else{source.start<source.stop};
        let one=Int::from_i128(1);
        let cursor=if !active{source.start.clone()}else if !source.step.is_negative(){
            let distance=source.stop.sub(&source.start);
            let remainder=distance.sub(&one).modulo(&source.step).unwrap();
            source.stop.sub(&one).sub(&remainder)
        }else{
            let distance=source.start.sub(&source.stop);
            let remainder=distance.sub(&one).modulo(&source.step.abs()).unwrap();
            source.stop.add(&one).add(&remainder)
        };
        Self{cursor,first:source.start.clone(),step:source.step.clone(),active}
    }
    fn next(&mut self)->Option<NativeInt>{
        if !self.active{return None;}
        let value=self.cursor.clone();
        if value==self.first{self.active=false;}else{self.cursor=self.cursor.sub(&self.step);}
        Some(value)
    }
}
'''
    return SEQUENCE+(big if emitter.model.integer=='bigint'else fixed)

SEQUENCE=r'''
struct NativeReverseSequence<T>{source:Option<T>,end:usize}
impl<T> NativeReverseSequence<T>{
    fn new(source:T,end:usize)->Self{Self{source:Some(source),end}}
    fn next<U>(&mut self,read:impl FnOnce(&T,usize)->Option<(U,usize)>)->Option<U>{
        if self.end==0{self.source=None;return None;}
        let result=self.source.as_ref().and_then(|source|read(source,self.end));
        match result{
            Some((value,width))=>{self.end=self.end.checked_sub(width).expect("proved reverse source width");Some(value)},
            None=>{self.end=0;self.source=None;None}
        }
    }
}
'''


def matches_builtin_reversed(emitter,value):
    from .native_classes import shape,domain
    from .native_types import alternatives
    from .native_unions import union_kind
    if domain(value.kind)!='iterator'or value.kind.record.operation!='reverse':return 'false'
    record=value.kind.record;source=shape(record.source)
    def result(kind):return str(domain(kind)in {'tuple','tuple_sequence','str','bytes'}).lower()
    if not union_kind(source):return result(source)
    state=emitter.fresh();arms=[]
    for index,kind in enumerate(alternatives(source)):arms.append('ClassIteratorSource_'+str(record.index)+'::V'+str(index)+'(_)=>'+result(kind))
    return '{let '+state+'=('+value.code+').borrow();match &'+state+'.source{'+','.join(arms)+'}}'
