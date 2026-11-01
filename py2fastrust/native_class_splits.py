"""Bound split/rsplit methods consume borrowed native word cursors directly."""
from dataclasses import dataclass
from .call_semantics import FunctionSignature,CallBindingError
from .native_types import alternatives

SIGNATURE=FunctionSignature.declaration(('sep','maxsplit'),default_names=('sep','maxsplit'))


@dataclass
class SplitSite:
    name:str
    error:str|None=None


def _sites(model):
    if not hasattr(model,'text_split_sites'):model.text_split_sites={}
    return model.text_split_sites


def bind(name,arguments,keywords,defaults):
    try:return SIGNATURE.bind(arguments,keywords,defaults).by_name,None
    except CallBindingError as error:
        message=str(error)
        if message=='too many positional arguments':
            return None,f'TypeError: {name}() takes at most 2 arguments ({len(arguments)} given)'
        if message.startswith('multiple values for argument: '):
            parameter=message.rsplit(': ',1)[1]
            return None,f"TypeError: argument for {name}() given by name ('{parameter}') and position ({1 if parameter=='sep'else 2})"
        if message.startswith('unexpected keyword argument: '):
            parameter=message.rsplit(': ',1)[1]
            return None,f"TypeError: {name}() got an unexpected keyword argument '{parameter}'"
        raise



def requires_frames(unit,analysis):
    from .native_constraints import MethodValue,value
    from .call_semantics import normalize_call
    import ast
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for scope in analysis.scopes.values():
        for ordinal,fact in scope.calls.items():
            for identity in fact.identity.alternatives:
                if not isinstance(identity,MethodValue)or identity.name not in {'split','rsplit'}:continue
                from .native_text_receiver_facts import builtin_text_receiver_kinds
                kinds=builtin_text_receiver_kinds(unit,scope,nodes.get(ordinal),identity)
                if not kinds:continue
                if identity.name=='rsplit'or len(kinds)!=1:return True
                bound,error=bind(identity.name,fact.positional,fact.keywords,{'sep':value('none'),'maxsplit':value('int')})
                if error:return True
                separator=bound['sep'];maximum=bound['maxsplit']
                if separator.unknown or separator.unbound or not separator.alternatives<=kinds|{'none'}:return True
                if maximum.unknown or maximum.unbound or not maximum.alternatives<={'int','bool','int_bool'}:return True
                if 'none'in separator.alternatives:
                    node=nodes[ordinal]
                    try:
                        original=SIGNATURE.plan(normalize_call(node)).capture(lambda expression,parameter:expression,defaults={'sep':None,'maxsplit':None})['sep']
                    except CallBindingError:return True
                    if original is not None and not(isinstance(original,ast.Constant)and original.value is None):return True
    return False


def analyze(model,plan,node,receiver,arguments,keywords):
    from .native_classes import Cell,shape
    name=node.func.attr
    if name not in {'split','rsplit'}:return None
    kinds=alternatives(shape(receiver))
    if not kinds or not all(kind in {'str','bytes'}for kind in kinds):return None
    _,error=bind(name,arguments,keywords,{'sep':Cell('none'),'maxsplit':Cell('int')})
    _sites(model)[(plan.index,id(node))]=SplitSite(name,error)
    element=model.cell(plan,node,identity=('text_split_element',name))
    for kind in kinds:model.contribute(element,Cell(kind),node)
    return model.cell(plan,node,'list',(element,))


def maximum(emitter,node,value):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_class_builtins import _type_name
    from .native_unions import union_kind,project
    def branch(kind,text):
        if domain(kind)=='object':
            raise ClassUnsupported(node,'this maxsplit value needs a user __index__ call protocol; split currently accepts captured builtin integers and booleans',types=(('maxsplit',kind),),proof='split index-sized integer conversion')
        if kind in {'int','bool','int_bool'}:
            number=emitter.number(Expression(text,kind))
            integer='('+number+') as i128'if emitter.model.integer!='bigint'else'('+number+').to_i128().unwrap_or_else(||if ('+number+').is_negative(){i128::MIN}else{i128::MAX})'
            return emitter.at('native_words_limit('+integer+')',node)
        return emitter.at('Err::<isize,String>(format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,Expression(text,kind),node)+'))',node)
    return project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code)


def emit(emitter,node,receiver,arguments,keywords,wanted):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_class_builtins import _error,_type_name
    from .native_unions import union_kind,project
    site=_sites(emitter.model).get((emitter.plan.index,id(node)))
    if site is None:return None
    bound,error=bind(site.name,arguments,list(keywords.items()),{'sep':Expression('()','none'),'maxsplit':Expression(emitter.literal(-1),'int',-1)})
    if error:return _error(emitter,node,wanted,'"'+error+'".to_owned()')
    limit=emitter.fresh();before='let '+limit+'='+maximum(emitter,node,bound['maxsplit'])+';'
    separator=bound['sep'];reverse=site.name=='rsplit'
    def owner_branch(kind,text):
        def separator_branch(sep_kind,sep):
            if sep_kind not in {kind,'none'}:
                if kind=='bytes'and domain(sep_kind)=='object':
                    raise ClassUnsupported(node,'this bytes separator needs a user buffer protocol; split supports only captured builtin bytes or None',types=(('separator',sep_kind),),proof='split builtin separator representation')
                typename=_type_name(emitter,Expression(sep,sep_kind),node)
                message='format!("TypeError: must be str or None, not {}",'+typename+')'if kind=='str'else'format!("TypeError: a bytes-like object is required, not \'{}\'",'+typename+')'
                return _error(emitter,node,wanted,message).code
            factory=('NativeReverseWords'if reverse else'NativeWords')if kind=='str'else('NativeReverseByteWords'if reverse else'NativeByteWords')
            sep_code='None'if sep_kind=='none'else'Some(('+sep+').as_str())'if kind=='str'else'Some(('+sep+').as_slice())'
            cursor=emitter.at(factory+'::new(&('+text+'),'+sep_code+','+limit+' as i128)',node)
            part,values=(emitter.fresh()for _ in range(2))
            item=Expression('NativeText::from('+part+')'if kind=='str'else part+'.to_vec()',kind)
            converted=emitter.coerce(item,wanted.element,node)
            code='let mut '+values+'=('+cursor+').map(|'+part+'|'+converted+').collect::<Vec<'+emitter.rust_type(wanted.element)+'>>();'
            if reverse:code+=values+'.reverse();'
            return '{'+code+'class_list('+values+')}'
        return project(separator.kind,separator.code,separator_branch)if union_kind(separator.kind)else separator_branch(separator.kind,separator.code)
    code=project(receiver.kind,receiver.code,owner_branch)if union_kind(receiver.kind)else owner_branch(receiver.kind,receiver.code)
    return Expression('{'+before+code+'}',wanted)


REVERSE_TEXT=r'''
struct NativeReverseWords<'a>{text:&'a str,separator:Option<&'a str>,cursor:usize,remaining:isize,done:bool}
impl<'a> NativeReverseWords<'a>{
    fn new(text:&'a str,separator:Option<&'a str>,maximum:i128)->Result<Self,String>{
        let remaining=native_words_limit(maximum)?;
        if separator.is_some_and(str::is_empty){return Err("ValueError: empty separator".into());}
        Ok(Self{text,separator,cursor:text.len(),remaining,done:false})
    }
}
impl<'a> Iterator for NativeReverseWords<'a>{
    type Item=&'a str;
    fn next(&mut self)->Option<Self::Item>{
        if self.done{return None;}
        if let Some(separator)=self.separator{
            let stop=self.cursor;
            if self.remaining!=0{
                if let Some(start)=self.text[..stop].rfind(separator){
                    self.cursor=start;if self.remaining>0{self.remaining-=1;}
                    return Some(&self.text[start+separator.len()..stop]);
                }
            }
            self.done=true;return Some(&self.text[..stop]);
        }
        @TRIM@
        if self.cursor==0{self.done=true;return None;}
        let stop=self.cursor;
        if self.remaining==0{self.done=true;return Some(&self.text[..stop]);}
        @WORD@
        if self.remaining>0{self.remaining-=1;}
        Some(&self.text[self.cursor..stop])
    }
}
'''
REVERSE_BYTES=r'''
struct NativeReverseByteWords<'a>{text:&'a[u8],separator:Option<&'a[u8]>,cursor:usize,remaining:isize,done:bool}
impl<'a> NativeReverseByteWords<'a>{
    fn new(text:&'a[u8],separator:Option<&'a[u8]>,maximum:i128)->Result<Self,String>{
        let remaining=native_words_limit(maximum)?;
        if separator.is_some_and(|value|value.is_empty()){return Err("ValueError: empty separator".into());}
        Ok(Self{text,separator,cursor:text.len(),remaining,done:false})
    }
}
impl<'a> Iterator for NativeReverseByteWords<'a>{
    type Item=&'a[u8];
    fn next(&mut self)->Option<Self::Item>{
        if self.done{return None;}
        if let Some(separator)=self.separator{
            let stop=self.cursor;
            if self.remaining!=0{
                if let Some(start)=self.text[..stop].windows(separator.len()).rposition(|part|part==separator){
                    self.cursor=start;if self.remaining>0{self.remaining-=1;}
                    return Some(&self.text[start+separator.len()..stop]);
                }
            }
            self.done=true;return Some(&self.text[..stop]);
        }
        while self.cursor>0&&native_words_byte_space(self.text[self.cursor-1]){self.cursor-=1;}
        if self.cursor==0{self.done=true;return None;}
        let stop=self.cursor;
        if self.remaining==0{self.done=true;return Some(&self.text[..stop]);}
        while self.cursor>0&&!native_words_byte_space(self.text[self.cursor-1]){self.cursor-=1;}
        if self.remaining>0{self.remaining-=1;}
        Some(&self.text[self.cursor..stop])
    }
}
'''


def runtime(model):
    if not getattr(model,'text_split_sites',None):return ''
    from .native_words import HELPERS
    if model.string_mode=='ascii':
        trim='while self.cursor>0&&matches!(self.text.as_bytes()[self.cursor-1],9..=13|28..=32){self.cursor-=1;}'
        word='while self.cursor>0&&!matches!(self.text.as_bytes()[self.cursor-1],9..=13|28..=32){self.cursor-=1;}'
    else:
        trim='while self.cursor>0{let c=self.text[..self.cursor].chars().next_back().unwrap();if !native_words_space(c){break;}self.cursor-=c.len_utf8();}'
        word='while self.cursor>0{let c=self.text[..self.cursor].chars().next_back().unwrap();if native_words_space(c){break;}self.cursor-=c.len_utf8();}'
    return HELPERS+'\n'+REVERSE_TEXT.replace('@TRIM@',trim).replace('@WORD@',word)+'\n'+REVERSE_BYTES
