"""Native bounded text queries and shared byte-pattern cursors."""
from dataclasses import dataclass
from .call_semantics import FunctionSignature
from .native_types import alternatives

NAMES=frozenset({'find','rfind','index','rindex','count','startswith','endswith'})
SIGNATURE=FunctionSignature.declaration(('sub','start','end'),positional_only=('sub','start','end'),default_names=('start','end'))


@dataclass
class SearchSite:
    name:str
    kinds:tuple


def _sites(model):
    if not hasattr(model,'text_search_sites'):model.text_search_sites={}
    return model.text_search_sites


def requires_frames(unit,analysis):
    import ast
    from .native_constraints import MethodValue
    from .native_text_receiver_facts import builtin_text_receiver_kinds
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    for scope in analysis.scopes.values():
        for ordinal,fact in scope.calls.items():
            for identity in fact.identity.alternatives:
                if not isinstance(identity,MethodValue)or identity.name not in NAMES:continue
                node=nodes.get(ordinal)
                kinds=builtin_text_receiver_kinds(unit,scope,node,identity)
                if not kinds:continue
                if identity.name!='count'or kinds!={'str'}:return True
                if not isinstance(node,ast.Call)or not isinstance(node.func,ast.Attribute):return True
                if node.keywords or not 1<=len(node.args)<=3:return True
                if scope.expressions.get(unit.ordinal(node.args[0]))!='str':return True
                for argument in node.args[1:]:
                    kind=scope.expressions.get(unit.ordinal(argument))
                    if kind=='none'and isinstance(argument,ast.Constant)and argument.value is None:continue
                    if kind not in {'int','bool','int_bool'}:return True
    return False


def analyze(model,plan,node,receiver,arguments,keywords):
    from .native_classes import shape
    if node.func.attr not in NAMES:return None
    kinds=alternatives(shape(receiver))
    if not kinds or not all(kind in {'str','bytes'}for kind in kinds):return None
    _sites(model)[(plan.index,id(node))]=SearchSite(node.func.attr,tuple(kinds))
    return model.cell(plan,node,'bool'if node.func.attr in {'startswith','endswith'}else'int')


def bind(kind,name,arguments,keywords,default):
    if keywords:return None,f'TypeError: {kind}.{name}() takes no keyword arguments'
    if not arguments:return None,f'TypeError: {name} expected at least 1 argument, got 0'
    if len(arguments)>3:return None,f'TypeError: {name} expected at most 3 arguments, got {len(arguments)}'
    return SIGNATURE.bind(arguments,keywords,{'start':default,'end':default}).by_name,None


def bound(emitter,node,value,role):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_unions import project,union_kind
    def branch(kind,text):
        if kind=='none':return 'None'
        if domain(kind)=='object':
            raise ClassUnsupported(node,'this search '+role+' bound needs a user __index__ call protocol; the native adapter accepts captured builtin integers, booleans or None',types=((role,kind),),proof='search slice-index conversion')
        if kind not in {'int','bool','int_bool'}:
            return emitter.at('Err::<Option<i128>,String>("TypeError: slice indices must be integers or None or have an __index__ method".to_owned())',node)
        number=emitter.number(Expression(text,kind))
        integer='('+number+') as i128'if emitter.model.integer!='bigint'else'('+number+').to_i128().unwrap_or_else(||if ('+number+').is_negative(){i128::MIN}else{i128::MAX})'
        return 'Some('+integer+')'
    return project(value.kind,value.code,branch)if union_kind(value.kind)else branch(value.kind,value.code)


def byte_needle(emitter,node,value):
    number=emitter.number(value)
    integer='Some(('+number+') as i128)'if emitter.model.integer!='bigint'else'('+number+').to_i128()'
    variable=emitter.fresh()
    return emitter.at(integer+'.filter(|'+variable+'|*'+variable+'>=0&&*'+variable+'<=255).map(|'+variable+'|'+variable+' as u8).ok_or_else(||"ValueError: byte must be in range(0, 256)".to_owned())',node)


def emit(emitter,node,receiver,arguments,keywords,wanted):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_class_builtins import _error,_type_name
    from .native_unions import project,union_kind
    site=_sites(emitter.model).get((emitter.plan.index,id(node)))
    if site is None:return None
    reverse=site.name in {'rfind','rindex'};raising=site.name in {'index','rindex'}
    tailmatch=site.name in {'startswith','endswith'}
    def finish(kind,owner,needle,start,stop):
        if tailmatch:
            function='native_frame_text_tailmatch'if kind=='str'else'native_frame_bytes_tailmatch'
            result=emitter.at(function+'(&('+owner+'),'+needle+','+start+','+stop+','+str(site.name=='endswith').lower()+')',node)
            return result
        if site.name=='count':
            function='native_text_count'if kind=='str'else'native_frame_bytes_count'
            result=emitter.at(function+'(&('+owner+'),'+needle+','+start+','+stop+')',node)
            return emitter.coerce(Expression('class_from_usize('+result+')','int'),wanted,node)
        function='native_frame_text_search'if kind=='str'else'native_frame_bytes_rsearch'if reverse else'native_frame_bytes_search'
        found,index=(emitter.fresh()for _ in range(2))
        result=emitter.at(function+'(&('+owner+'),'+needle+','+start+','+stop+(','+str(reverse).lower()if kind=='str'else'')+')',node)
        absent=(_error(emitter,node,'int','"ValueError: '+('substring'if kind=='str'else'subsection')+' not found".to_owned()').code
                if raising else emitter.literal(-1))
        code='{let '+found+'='+result+';match '+found+'{Some('+index+')=>class_from_usize('+index+'),None=>'+absent+'}}'
        return emitter.coerce(Expression(code,'int'),wanted,node)
    def owner_branch(kind,text):
        values,error=bind(kind,site.name,arguments,list(keywords.items()),Expression('()','none'))
        if error:return _error(emitter,node,wanted,'"'+error+'".to_owned()').code
        def bounds():
            start,stop=(emitter.fresh()for _ in range(2))
            before='let '+start+':Option<i128>='+bound(emitter,node,values['start'],'start')+';let '+stop+':Option<i128>='+bound(emitter,node,values['end'],'end')+';'
            return before,start,stop
        pattern=values['sub']
        if tailmatch:
            before,start,stop=bounds()
            def checked_pattern(pattern_kind,pattern_text,inside_tuple=False):
                if union_kind(pattern_kind):
                    return project(pattern_kind,pattern_text,lambda k,t:checked_pattern(k,t,inside_tuple))
                tag=domain(pattern_kind)
                if not inside_tuple and tag=='tuple':
                    result='false'
                    for index,element in reversed(list(enumerate(pattern_kind.fields))):
                        current=checked_pattern(element,'('+pattern_text+').'+str(index)+'.clone()',True)
                        result='if '+current+'{true}else{'+result+'}'
                    return '{'+result+'}'
                if not inside_tuple and tag=='tuple_sequence':
                    item,result=emitter.fresh(),emitter.fresh()
                    predicate=checked_pattern(pattern_kind.element,item+'.clone()',True)
                    return '{let mut '+result+'=false;for '+item+' in ('+pattern_text+').iter(){if '+predicate+'{'+result+'=true;break;}}'+result+'}'
                if pattern_kind==kind:
                    return finish(kind,text,'&('+pattern_text+')',start,stop)
                if kind=='bytes'and tag=='object':
                    raise ClassUnsupported(node,'this byte prefix/suffix pattern needs a user buffer protocol; the native adapter accepts builtin bytes or tuples of builtin bytes',types=(('pattern',pattern_kind),),proof='prefix/suffix builtin buffer representation')
                typename=_type_name(emitter,Expression(pattern_text,pattern_kind),node)
                if inside_tuple:
                    message=('"TypeError: tuple for '+site.name+' must only contain str, not {}"'if kind=='str'else'"TypeError: a bytes-like object is required, not \'{}\'"')
                else:
                    message='"TypeError: '+site.name+' first arg must be '+kind+' or a tuple of '+kind+', not {}"'
                return _error(emitter,node,'bool','format!('+message+','+typename+')').code
            code=checked_pattern(pattern.kind,pattern.code)
            return emitter.coerce(Expression('{'+before+code+'}','bool'),wanted,node)
        def pattern_branch(pattern_kind,pattern_text,start=None,stop=None):
            if kind=='str':
                if pattern_kind!='str':
                    typename='"None"'if pattern_kind=='none'else _type_name(emitter,Expression(pattern_text,pattern_kind),node)
                    return _error(emitter,node,wanted,'format!("TypeError: '+site.name+'() argument 1 must be str, not {}",'+typename+')').code
                before,start,stop=bounds()
                return '{'+before+finish(kind,text,'&('+pattern_text+')',start,stop)+'}'
            if pattern_kind=='bytes':return finish(kind,text,'&('+pattern_text+')',start,stop)
            if pattern_kind in {'int','bool','int_bool'}:
                byte=emitter.fresh();checked=byte_needle(emitter,node,Expression(pattern_text,pattern_kind))
                return '{let '+byte+'=['+checked+'];'+finish(kind,text,'&'+byte,start,stop)+'}'
            if domain(pattern_kind)=='object':
                raise ClassUnsupported(node,'this byte search pattern needs a user __index__/buffer protocol; the native adapter accepts builtin bytes, integers or booleans',types=(('sub',pattern_kind),),proof='search builtin byte needle representation')
            return _error(emitter,node,wanted,'format!("TypeError: argument should be integer or bytes-like object, not \'{}\'",'+_type_name(emitter,Expression(pattern_text,pattern_kind),node)+')').code
        if kind=='str':return project(pattern.kind,pattern.code,pattern_branch)if union_kind(pattern.kind)else pattern_branch(pattern.kind,pattern.code)
        before,start,stop=bounds()
        code=project(pattern.kind,pattern.code,lambda k,t:pattern_branch(k,t,start,stop))if union_kind(pattern.kind)else pattern_branch(pattern.kind,pattern.code,start,stop)
        return '{'+before+code+'}'
    code=project(receiver.kind,receiver.code,owner_branch)if union_kind(receiver.kind)else owner_branch(receiver.kind,receiver.code)
    return Expression(code,wanted)


HELPERS=r'''
fn native_frame_text_tailmatch(text:&NativeText,pattern:&str,start:Option<i128>,stop:Option<i128>,suffix:bool)->Result<bool,String>{
    let Some(window)=native_text_window(text,start,stop)?else{return Ok(false);};
    Ok(if suffix{window.ends_with(pattern)}else{window.starts_with(pattern)})
}
fn native_frame_text_search(text:&NativeText,pattern:&str,start:Option<i128>,stop:Option<i128>,reverse:bool)->Result<Option<usize>,String>{
    let Some(window)=native_text_window(text,start,stop)?else{return Ok(None);};
    let found=if reverse{window.rfind(pattern)}else{window.find(pattern)};
    let Some(index)=found else{return Ok(None);};
    let base=(window.as_ptr() as usize).checked_sub(text.as_str().as_ptr() as usize)
        .and_then(|base|base.checked_add(index)).ok_or_else(||"OverflowError: search result offset is too large".to_owned())?;
    Ok(Some(@OFFSET@))
}
fn native_frame_byte_window(length:usize,start:Option<i128>,stop:Option<i128>)->Option<(usize,usize)>{
    let length=length as i128;
    let bound=|value:i128|if value<0{value.saturating_add(length).max(0)}else{value};
    let start=start.map(bound).unwrap_or(0);
    let stop=stop.map(bound).unwrap_or(length).min(length);
    if start>length||start>stop{return None;}
    Some((start as usize,stop as usize))
}
fn native_frame_bytes_tailmatch(text:&[u8],pattern:&[u8],start:Option<i128>,stop:Option<i128>,suffix:bool)->Result<bool,String>{
    let Some((start,stop))=native_frame_byte_window(text.len(),start,stop)else{return Ok(false);};
    let window=&text[start..stop];
    Ok(if suffix{window.ends_with(pattern)}else{window.starts_with(pattern)})
}
fn native_frame_bytes_search(text:&[u8],pattern:&[u8],start:Option<i128>,stop:Option<i128>)->Result<Option<usize>,String>{
    let Some((start,stop))=native_frame_byte_window(text.len(),start,stop)else{return Ok(None);};
    if pattern.is_empty(){return Ok(Some(start));}
    if pattern.len()>stop-start{return Ok(None);}
    let found=if pattern.len()==1{text[start..stop].iter().position(|byte|*byte==pattern[0])}else{
        let prefix=native_byte_pattern_prefix(pattern)?;
        NativeBytePatternMatches{text:&text[start..stop],pattern,prefix:&prefix,cursor:0,matched:0}.next()
    };
    match found{
        Some(offset)=>start.checked_add(offset).map(Some).ok_or_else(||"OverflowError: search result offset is too large".to_owned()),
        None=>Ok(None),
    }
}
fn native_frame_bytes_count(text:&[u8],pattern:&[u8],start:Option<i128>,stop:Option<i128>)->Result<usize,String>{
    let Some((start,stop))=native_frame_byte_window(text.len(),start,stop)else{return Ok(0);};
    if pattern.is_empty(){return (stop-start).checked_add(1).ok_or_else(||"OverflowError: byte count is too large".to_owned());}
    if pattern.len()>stop-start{return Ok(0);}
    if pattern.len()==1{return Ok(text[start..stop].iter().filter(|byte|**byte==pattern[0]).count());}
    let prefix=native_byte_pattern_prefix(pattern)?;
    Ok(NativeBytePatternMatches{text:&text[start..stop],pattern,prefix:&prefix,cursor:0,matched:0}.count())
}
fn native_frame_byte_reverse_prefix(pattern:&[u8])->Result<Vec<usize>,String>{
    let mut prefix=Vec::new();
    prefix.try_reserve_exact(pattern.len()).map_err(|_|"MemoryError: cannot allocate byte pattern".to_owned())?;
    prefix.resize(pattern.len(),0);
    let at=|index:usize|pattern[pattern.len()-1-index];
    let mut matched=0;
    for index in 1..pattern.len(){
        while matched>0&&at(index)!=at(matched){matched=prefix[matched-1];}
        if at(index)==at(matched){matched+=1;}
        prefix[index]=matched;
    }
    Ok(prefix)
}
fn native_frame_bytes_rsearch(text:&[u8],pattern:&[u8],start:Option<i128>,stop:Option<i128>)->Result<Option<usize>,String>{
    let Some((start,stop))=native_frame_byte_window(text.len(),start,stop)else{return Ok(None);};
    if pattern.is_empty(){return Ok(Some(stop));}
    if pattern.len()>stop-start{return Ok(None);}
    if pattern.len()==1{
        return match text[start..stop].iter().rposition(|byte|*byte==pattern[0]){
            Some(offset)=>start.checked_add(offset).map(Some).ok_or_else(||"OverflowError: search result offset is too large".to_owned()),
            None=>Ok(None),
        };
    }
    let prefix=native_frame_byte_reverse_prefix(pattern)?;
    let at=|index:usize|pattern[pattern.len()-1-index];
    let mut matched=0;
    for index in (start..stop).rev(){
        while matched>0&&text[index]!=at(matched){matched=prefix[matched-1];}
        if text[index]==at(matched){matched+=1;}
        if matched==pattern.len(){return Ok(Some(index));}
    }
    Ok(None)
}
'''


def runtime(model):
    sites=getattr(model,'text_search_sites',{})
    if not sites:return ''
    kinds={kind for site in sites.values()for kind in site.kinds}
    pieces=[]
    text,byte=HELPERS.split('fn native_frame_byte_window',1)
    if 'str'in kinds:
        if not getattr(model,'text_operation_sites',None):
            from .native_text_methods import HELPERS as TEXT_HELPERS
            pieces.append(TEXT_HELPERS)
        if model.string_mode=='unicode':pieces.append(UNICODE_OFFSET)
        pieces.append(text.replace('@OFFSET@','base'if model.string_mode=='ascii'else'native_frame_search_character_offset(text,base)?'))
    if 'bytes'in kinds:
        if not getattr(model,'text_replace_sites',None):
            from .native_class_text_replace import HELPERS as BYTE_HELPERS
            pieces.append(BYTE_HELPERS)
        pieces.append('fn native_frame_byte_window'+byte)
    return '\n'.join(pieces)


UNICODE_OFFSET=r'''
fn native_frame_search_character_offset(text:&NativeText,byte:usize)->Result<usize,String>{
    let mut start=0;let mut stop=text.codepoint_len();
    while start<stop{
        let middle=start+(stop-start)/2;
        let boundary=text.byte_offset(middle)?.ok_or_else(||"RuntimeError: invalid native search boundary".to_owned())?;
        if boundary<byte{start=middle+1;}else{stop=middle;}
    }
    if text.byte_offset(start)?==Some(byte){Ok(start)}else{Err("RuntimeError: invalid native search boundary".to_owned())}
}
'''
