"""Captured str/bytes replacement with checked sizes and linear byte matching."""
from dataclasses import dataclass
from .call_semantics import FunctionSignature
from .native_types import alternatives

SIGNATURE=FunctionSignature.declaration(('old','new','count'),positional_only=('old','new'),default_names=('count',))


@dataclass
class ReplaceSite:
    receiver:object


def _sites(model):
    if not hasattr(model,'text_replace_sites'):model.text_replace_sites={}
    return model.text_replace_sites


def requires_frames(unit,analysis):
    import ast
    from .native_constraints import MethodValue
    from .native_text_receiver_facts import builtin_text_receiver_kinds
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    return any(isinstance(identity,MethodValue)and identity.name=='replace'
               and builtin_text_receiver_kinds(unit,scope,nodes.get(ordinal),identity)
               for scope in analysis.scopes.values()for ordinal,fact in scope.calls.items()
               for identity in fact.identity.alternatives)


def analyze(model,plan,node,receiver,arguments,keywords):
    from .native_classes import Cell,shape
    if node.func.attr!='replace':return None
    kinds=alternatives(shape(receiver))
    if not kinds or not all(kind in {'str','bytes'}for kind in kinds):return None
    _sites(model)[(plan.index,id(node))]=ReplaceSite(receiver)
    result=model.cell(plan,node)
    for kind in kinds:model.contribute(result,Cell(kind),node)
    return result


def bind(kind,arguments,keywords,default):
    if kind=='bytes'and keywords:return None,'TypeError: bytes.replace() takes no keyword arguments'
    total=len(arguments)+len(keywords)
    if len(arguments)<2:return None,f'TypeError: replace() takes at least 2 positional arguments ({len(arguments)} given)'
    if total>3:return None,f'TypeError: replace() takes at most 3 arguments ({total} given)'
    for name,value in keywords:
        if name!='count':return None,f"TypeError: replace() got an unexpected keyword argument '{name}'"
    return SIGNATURE.bind(arguments,keywords,{'count':default}).by_name,None


def count(emitter,node,value):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_unions import project,union_kind
    from .native_class_builtins import _type_name
    def branch(kind,text):
        if domain(kind)=='object':
            raise ClassUnsupported(node,'this replace count needs a user __index__ call protocol; the native adapter accepts captured builtin integers and booleans',types=(('count',kind),),proof='replace index-sized count conversion')
        if kind not in {'int','bool','int_bool'}:
            return emitter.at('Err::<isize,String>(format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,Expression(text,kind),node)+'))',node)
        number=emitter.number(Expression(text,kind))
        integer='('+number+') as i128'if emitter.model.integer!='bigint'else'('+number+').to_i128().unwrap_or_else(||if ('+number+').is_negative(){i128::MIN}else{i128::MAX})'
        return emitter.at('isize::try_from('+integer+').map_err(|_|"OverflowError: Python int too large to convert to C ssize_t".to_owned())',node)
    return project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code)


def emit(emitter,node,receiver,arguments,keywords,wanted):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_class_builtins import _error,_type_name
    from .native_unions import project,union_kind
    if (emitter.plan.index,id(node))not in _sites(emitter.model):return None
    def owner_branch(kind,text):
        bound,error=bind(kind,arguments,list(keywords.items()),Expression(emitter.literal(-1),'int',-1))
        if error:return _error(emitter,node,wanted,'"'+error+'".to_owned()').code
        def old_branch(old_kind,old):
            def invalid(value,position):
                if kind=='bytes'and domain(value.kind)=='object':
                    raise ClassUnsupported(node,'this replace argument needs a user bytes-buffer protocol; the native adapter accepts captured builtin bytes',types=(('argument '+str(position),value.kind),),proof='replace builtin buffer representation')
                if kind=='str':
                    typename='"None"'if value.kind=='none'else _type_name(emitter,value,node)
                    message='format!("TypeError: replace() argument '+str(position)+' must be str, not {}",'+typename+')'
                else:message='format!("TypeError: a bytes-like object is required, not \'{}\'",'+_type_name(emitter,value,node)+')'
                return _error(emitter,node,wanted,message).code
            if old_kind!=kind:return invalid(Expression(old,old_kind),1)
            def new_branch(new_kind,new):
                if new_kind!=kind:return invalid(Expression(new,new_kind),2)
                limit=emitter.fresh();before='let '+limit+'='+count(emitter,node,bound['count'])+';'
                function='native_frame_text_replace'if kind=='str'else'native_frame_bytes_replace'
                code=emitter.at(function+'(&('+text+'),&('+old+'),&('+new+'),'+limit+')',node)
                if kind=='str':code='NativeText::from('+code+')'
                return '{'+before+emitter.coerce(Expression(code,kind),wanted,node)+'}'
            value=bound['new']
            return project(value.kind,value.code,new_branch)if union_kind(value.kind)else new_branch(value.kind,value.code)
        value=bound['old']
        return project(value.kind,value.code,old_branch)if union_kind(value.kind)else old_branch(value.kind,value.code)
    code=project(receiver.kind,receiver.code,owner_branch)if union_kind(receiver.kind)else owner_branch(receiver.kind,receiver.code)
    return Expression(code,wanted)


HELPERS=r'''
fn native_replace_size(length:usize,old:usize,new:usize,count:usize)->Result<usize,String>{
    let overflow=||"OverflowError: replace result is too long".to_owned();
    let removed=old.checked_mul(count).ok_or_else(overflow)?;
    let added=new.checked_mul(count).ok_or_else(overflow)?;
    length.checked_sub(removed).and_then(|length|length.checked_add(added))
        .filter(|length|*length<=isize::MAX as usize).ok_or_else(overflow)
}
fn native_frame_text_replace(text:&str,old:&str,new:&str,count:isize)->Result<String,String>{
    let limit=if count<0{usize::MAX}else{count as usize};
    let matches=text.match_indices(old).take(limit).count();
    let length=native_replace_size(text.len(),old.len(),new.len(),matches)?;
    let mut result=String::new();
    result.try_reserve_exact(length).map_err(|_|"MemoryError: cannot allocate replacement string".to_owned())?;
    let mut start=0;
    for(index,_)in text.match_indices(old).take(matches){
        result.push_str(&text[start..index]);result.push_str(new);start=index+old.len();
    }
    result.push_str(&text[start..]);Ok(result)
}
fn native_byte_pattern_prefix(pattern:&[u8])->Result<Vec<usize>,String>{
    if pattern.len()<=1{return Ok(Vec::new());}
    let mut prefix=Vec::new();
    prefix.try_reserve_exact(pattern.len()).map_err(|_|"MemoryError: cannot allocate byte pattern".to_owned())?;
    prefix.resize(pattern.len(),0);
    let mut matched=0;
    for index in 1..pattern.len(){
        while matched>0&&pattern[index]!=pattern[matched]{matched=prefix[matched-1];}
        if pattern[index]==pattern[matched]{matched+=1;}
        prefix[index]=matched;
    }
    Ok(prefix)
}
#[derive(Clone,Copy)]
struct NativeBytePatternMatches<'a>{text:&'a[u8],pattern:&'a[u8],prefix:&'a[usize],cursor:usize,matched:usize}
impl<'a> Iterator for NativeBytePatternMatches<'a>{
    type Item=usize;
    fn next(&mut self)->Option<usize>{
        if self.pattern.is_empty(){
            if self.cursor>self.text.len(){return None;}
            let index=self.cursor;self.cursor+=1;return Some(index);
        }
        while self.cursor<self.text.len(){
            let byte=self.text[self.cursor];
            while self.matched>0&&byte!=self.pattern[self.matched]{self.matched=self.prefix[self.matched-1];}
            if byte==self.pattern[self.matched]{self.matched+=1;}
            self.cursor+=1;
            if self.matched==self.pattern.len(){self.matched=0;return Some(self.cursor-self.pattern.len());}
        }
        None
    }
}
fn native_frame_bytes_replace(text:&[u8],old:&[u8],new:&[u8],count:isize)->Result<Vec<u8>,String>{
    let limit=if count<0{usize::MAX}else{count as usize};
    let prefix=if limit==0{Vec::new()}else{native_byte_pattern_prefix(old)?};
    let cursor=NativeBytePatternMatches{text,pattern:old,prefix:&prefix,cursor:0,matched:0};
    let matches=cursor.take(limit).count();
    let length=native_replace_size(text.len(),old.len(),new.len(),matches)?;
    let mut result=Vec::new();
    result.try_reserve_exact(length).map_err(|_|"MemoryError: cannot allocate replacement bytes".to_owned())?;
    let mut start=0;
    for index in cursor.take(matches){
        result.extend_from_slice(&text[start..index]);result.extend_from_slice(new);start=index+old.len();
    }
    result.extend_from_slice(&text[start..]);Ok(result)
}
'''


def runtime(model):return HELPERS if getattr(model,'text_replace_sites',None)else''
