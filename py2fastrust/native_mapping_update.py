"""Canonical dict.update phases over concrete owners and typed pair producers."""
from dataclasses import dataclass,field,replace
from itertools import product
from .native_types import EMPTY,EmptyType,TupleType,TupleSequenceType,alternatives,list_type


@dataclass
class Row:
    fields:tuple|None=None
    cursor:object=None
    element:object=None
    positional:bool=False


@dataclass
class Update:
    receiver:object
    result:object
    source:object=None
    cursor:object=None
    rows:dict=field(default_factory=dict)
    error:str|None=None


def supported(kind):
    from .native_class_mappings import mapping_kind
    return mapping_kind(kind)and kind.record.category=='dict'and kind.record.flavor in {'dict','defaultdict'}


def require_origin(model,node,choices):
    if not model.final:return
    from .native_dictionary_positions import proved
    from .native_classes import ClassUnsupported
    if not all(proved(kind,model)for kind in choices):
        raise ClassUnsupported(node,'dict.update receiver has an unproved constructor or update origin; builtin mapping contents/insertion history cannot be assumed for this custom source',proof='closed dictionary update receiver origin')


def origins_valid(model,record,seen):
    from .native_classes import shape
    from .native_class_mappings import mapping_kind
    from .native_dictionary_positions import proved,iterable_origin
    from .native_class_iterators import default_noniterable
    for site in getattr(model,'mapping_update_calls',{}).values():
        if site.error or not any(supported(owner)and owner.record is record for owner in alternatives(shape(site.receiver))):continue
        if site.source is None:continue
        for source in alternatives(shape(site.source)):
            if mapping_kind(source)and source.record.category=='dict':
                # A mutation dependency may form a closed SCC; every member's
                # primitive constructor origin was proved before this step.
                if source.record.index in seen:continue
                if not proved(source,model,seen):return False
            elif not(default_noniterable(model,source)or iterable_origin(source,model)):return False
    return True


def binding_error(count):
    return f'TypeError: update expected at most 1 argument, got {count}'if count>1 else None


def sites(model):
    values=getattr(model,'mapping_update_calls',None)
    if values is None:
        values=model.mapping_update_calls={}
        from .native_callback_effects import register
        register(model,lambda plan,node:any(key[:2]==(plan.index,id(node))for key in model.mapping_update_calls))
    return values


def _variants(model,node,kind):
    from .native_class_mappings import key_supported,key_pending,unhashable_leaf
    from .native_classes import ClassUnsupported
    if kind is None:return ()
    choices=alternatives(kind)
    if len(choices)>1:return tuple(result for choice in choices for result in _variants(model,node,choice))
    if isinstance(kind,EmptyType):return ()
    if key_pending(kind)and not model.final:return ()
    if isinstance(kind,TupleType):
        return tuple(replace(kind,fields=tuple(fields))for fields in product(*(_variants(model,node,child)for child in kind.fields)))
    if unhashable_leaf(kind)is not None:return ()
    if key_supported(kind):return(kind,)
    raise ClassUnsupported(node,'dict.update yielded a key whose custom, floating or heterogeneous hash/equality protocol has no typed dictionary adapter',types=(('key',kind),),proof='dictionary update key hash/equality')


def _contribute(model,node,owners,key,value):
    from .native_classes import Cell,shape
    for variant in _variants(model,node,shape(key)):
        for owner in owners:
            model.mappings.contribute_key(owner.record,Cell(variant),node)
            model.contribute(owner.record.value,value,node)


def _closed_inner(model,kind):
    from .native_classes import domain,shape
    from .native_class_iterators import iterator_kind
    from .native_iterator_hints import SourceHint
    if domain(kind)in {'tuple_sequence','str','bytes','range','deque','dict_view','dict','set','array','bytearray'}:return True
    if iterator_kind(kind)and isinstance(kind.record.hint_protocol,SourceHint):
        return all(domain(source)in {'list','tuple','tuple_sequence','str','bytes','range','deque','dict_view','dict','set'}for source in alternatives(shape(kind.record.source)))
    return False


def _rows(model,plan,node,site,item,owners,environment):
    from .native_classes import Cell,shape,ClassUnsupported
    from .native_class_iterators import default_noniterable
    choices=alternatives(shape(item))
    for kind in choices:
        if kind is None:
            if model.final:raise ClassUnsupported(node,'dict.update pair element representation remains unresolved',proof='resolved dictionary update pair')
            continue
        if isinstance(kind,EmptyType):continue
        actual=item if len(choices)==1 else model.namespace.representation(kind,[item],node)
        if isinstance(kind,TupleType)and not getattr(kind,'_native_named_tuple',False):
            row=Row(fields=tuple(actual.root().args));site.rows[kind]=row
            if len(row.fields)==2:_contribute(model,node,owners,*row.fields)
            continue
        if list_type(kind):
            from .native_list_positions import fields,supports_projection
            members=fields(model,actual)
            if members is not None and all(supports_projection(kind.element,shape(member))for member in members):
                row=Row(fields=members,positional=True)
            else:
                member=model.item(actual,node);row=Row(element=member)
            site.rows[kind]=row
            if row.fields is None:_contribute(model,node,owners,row.element,row.element)
            elif len(row.fields)==2:_contribute(model,node,owners,*row.fields)
            continue
        if isinstance(kind,TupleSequenceType):
            row=Row(element=model.item(actual,node));site.rows[kind]=row
            _contribute(model,node,owners,row.element,row.element)
            continue
        if default_noniterable(model,kind):
            raise ClassUnsupported(node,'dict.update encountered a noniterable pair element; Python 3.14 adds a per-element exception note, and that separate exception-note protocol is not implemented',types=(('pair element',kind),),proof='dictionary update pair conversion exception notes')
        if not _closed_inner(model,kind):
            raise ClassUnsupported(node,'dict.update inner pair iteration requires its full materialization, hint callbacks and TypeError exception-note protocol; that custom pair provider has no proved native conversion capability',types=(('pair element',kind),),proof='closed dictionary update pair materialization')
        cursor=model.iterators.source(plan,node,actual,identity=('dict_update_inner',kind),environment=environment)
        member=model.iterators.demand(plan,node,Cell(cursor),environment)
        row=Row(cursor=cursor,element=member);site.rows[kind]=row
        _contribute(model,node,owners,member,member)


def analyze_values(model,plan,node,receiver,arguments,keywords,environment,*,identity=None):
    from .native_classes import Cell,shape,ClassUnsupported
    from .native_class_mappings import mapping_kind
    from .native_dictionary_positions import iterable_origin,proved
    choices=alternatives(shape(receiver))
    if not choices or not all(supported(kind)for kind in choices):return None
    key=plan.index,id(node),identity;values=sites(model);values.pop(key,None)
    error=binding_error(len(arguments));result=model.cell(plan,node,EMPTY if error else'none',identity=('mapping_update',identity))
    site=Update(receiver,result,error=error);values[key]=site
    require_origin(model,node,choices)
    if error:return site
    if arguments:
        site.source=arguments[0];sources=alternatives(shape(site.source))
        mapped=[kind for kind in sources if mapping_kind(kind)and kind.record.category=='dict']
        if mapped and len(mapped)==len(sources):
            for source in mapped:
                if model.final and not proved(source,model):
                    raise ClassUnsupported(node,'dict.update mapping source has an unproved constructor/copy origin',proof='closed dictionary update mapping source')
                _contribute(model,node,choices,source.record.key,source.record.value)
        else:
            if mapped:raise ClassUnsupported(node,'dict.update joined mapping and pair-iterable sources need a per-source acquisition phase not implemented by this adapter',proof='dictionary update source protocol alternatives')
            from .native_class_iterators import default_noniterable
            if model.final and not all(default_noniterable(model,kind)or iterable_origin(kind,model)for kind in sources):
                raise ClassUnsupported(node,'dict.update source may expose a custom keys or dynamic mapping protocol; treating it as a pair iterable is not implemented',types=(('source',shape(site.source)),),proof='canonical mapping-versus-pairs update protocol')
            site.cursor=model.iterators.source(plan,node,site.source,identity=('dict_update_outer',identity),environment=environment)
            item=model.iterators.demand(plan,node,Cell(site.cursor),environment)
            _rows(model,plan,node,site,item,choices,environment)
    for name,value in keywords:_contribute(model,node,choices,Cell('str'),value)
    return site


def analyze(model,plan,node,receiver,arguments,keywords,environment):
    if node.func.attr!='update':return None
    site=analyze_values(model,plan,node,receiver,arguments,keywords,environment)
    return None if site is None else model.remember(plan,node,site.result)


def preparation(emitter,node,owner,name,arguments):
    if not emitter.model.mappings.views.positions_enabled():return ''
    return emitter.at(owner+'.borrow_mut().'+name+'('+arguments+')',node)+';'


def _insert(emitter,node,owner,key,value):
    from .native_classes import Expression
    from .native_class_mappings import unhashable_leaf,query_type_name
    from .native_types import tuple_code
    from .native_unions import project,union_kind
    from .native import _string
    def visit(part,finish,outer=None):
        kind,code=part.kind,part.code
        if union_kind(kind):return project(kind,code,lambda child,text:'{'+visit(Expression('('+text+').clone()',child),finish,outer)+'}')+';'
        if outer is None:outer=part
        if isinstance(kind,EmptyType):return 'native_empty::<()>('+code+');'
        if isinstance(kind,TupleType):
            def field(index,values):
                if index==len(kind.fields):return finish(Expression(tuple_code(item.code for item in values),replace(kind,fields=tuple(item.kind for item in values))))
                return visit(Expression('('+code+').'+str(index)+'.clone()',kind.fields[index]),lambda saved:field(index+1,values+[saved]),outer)
            return field(0,[])
        leaf=unhashable_leaf(kind)
        if leaf is not None:
            error='format!("TypeError: cannot use \'{}\' as a dict key (unhashable type: \'{}\')",'+query_type_name(emitter,outer,node)+','+_string(leaf)+')'
            return emitter.at('Err::<(),String>('+error+')',node)+';'
        return finish(part)
    return visit(key,lambda saved:emitter.model.mappings._set(emitter,node,owner,saved,value))


def _length_error(emitter,node,index,count):
    return emitter.at('Err::<(),String>(format!("ValueError: dictionary update sequence element #{} has length {}; 2 is required",'+index+','+count+'))',node)+';'


def _row(emitter,node,site,owner,value,index):
    from .native_classes import Expression,shape
    from .native_unions import project
    def leaf(kind,code):
        if isinstance(kind,EmptyType):return 'native_empty::<()>('+code+');'
        row=site.rows[kind]
        if row.fields is not None:
            if len(row.fields)!=2:return _length_error(emitter,node,index,str(len(row.fields)))
            if list_type(kind):
                read=emitter.fresh();key,val=(emitter.fresh()for _ in range(2))
                from .native_list_positions import project_element
                left=project_element(emitter,read+'[0].clone()',kind.element,shape(row.fields[0]),node)
                right=project_element(emitter,read+'[1].clone()',kind.element,shape(row.fields[1]),node)
                before='let ('+key+','+val+')={let '+read+'=('+code+').borrow();('+left.code+','+right.code+')};'
                return before+_insert(emitter,node,owner,Expression(key,shape(row.fields[0])),Expression(val,shape(row.fields[1])))
            return _insert(emitter,node,owner,Expression('('+code+').0.clone()',kind.fields[0]),Expression('('+code+').1.clone()',kind.fields[1]))
        if list_type(kind):
            stable,read,key,val=(emitter.fresh()for _ in range(4))
            error=_length_error(emitter,node,index,read+'.len()')
            before='let '+stable+'=('+code+').clone();let ('+key+','+val+')={let '+read+'='+stable+'.borrow();if '+read+'.len()!=2{'+error+'}('+read+'[0].clone(),'+read+'[1].clone())};'
            return before+_insert(emitter,node,owner,Expression(key,kind.element),Expression(val,kind.element))
        if isinstance(kind,TupleSequenceType):
            stable,read,key,val=(emitter.fresh()for _ in range(4))
            before='let '+stable+'=('+code+').clone();let '+read+'='+stable+'.as_slice();if '+read+'.len()!=2{'+_length_error(emitter,node,index,read+'.len()')+'}'
            before+='let '+key+'='+read+'[0].clone();let '+val+'='+read+'[1].clone();'
            return before+_insert(emitter,node,owner,Expression(key,kind.element),Expression(val,kind.element))
        source=Expression('('+code+').clone()',kind)
        before,iterator=emitter.capture(emitter.model.iterators.construct(emitter,node,source,kind=row.cursor))
        pulled=emitter.model.iterators.pull(emitter,node,iterator)
        values,item,key,val=(emitter.fresh()for _ in range(4));element=shape(row.element)
        from .native_materializer_hints import emit as materializer_hint
        from .native_source_lengths import reserve_hint
        from .native_class_iterators import iterator_kind
        # A canonical builtin cursor returns itself from iter(); its captured
        # owner is also the original hint owner, without a temporary Rc loan.
        hint_owner=iterator if iterator_kind(kind)else source
        hint=materializer_hint(emitter,node,hint_owner,'list')
        before+='let mut '+values+'=Vec::<'+emitter.rust_type(element)+'>::new();'+reserve_hint(emitter,node,values,hint)
        before+='loop{let Some('+item+')=('+pulled.code+')else{break;};'+reserve_hint(emitter,node,values,'1_usize')+values+'.push('+emitter.coerce(Expression(item,pulled.kind),element,node)+');}'
        before+='if '+values+'.len()!=2{'+_length_error(emitter,node,index,values+'.len()')+'}'
        before+='let '+key+'='+values+'[0].clone();let '+val+'='+values+'[1].clone();'
        return before+_insert(emitter,node,owner,Expression(key,element),Expression(val,element))
    return project(value.kind,value.code,lambda kind,code:'{'+leaf(kind,code)+'}')+';'


def _consume(emitter,node,site,owner,source):
    from .native_classes import Expression,shape
    from .native_class_mappings import mapping_kind
    from .native_unions import project
    if site.cursor is None:
        def merge(kind,code):
            other,read,info,key,val=(emitter.fresh()for _ in range(5))
            copied=preparation(emitter,node,owner.code,'prepare_mapping_info',info)
            before='let '+other+'=('+code+').clone();'
            body='let '+info+'={'+other+'.borrow().entries.mapping_seed()};'+copied if emitter.model.mappings.views.positions_enabled()else''
            body+='let '+read+'='+other+'.borrow();for ('+key+','+val+')in '+read+'.entries.iter(){'+_insert(emitter,node,owner,Expression(key+'.clone()',shape(kind.record.key)),Expression(val+'.clone()',shape(kind.record.value)))+'}'
            return before+'if Rc::as_ptr(&'+owner.code+')as *const ()!=Rc::as_ptr(&'+other+')as *const (){'+body+'}'
        return project(source.kind,source.code,lambda kind,code:'{'+merge(kind,code)+'}')+';'
    before,iterator=emitter.capture(emitter.model.iterators.construct(emitter,node,source,kind=site.cursor));pulled=emitter.model.iterators.pull(emitter,node,iterator);item,index=(emitter.fresh()for _ in range(2))
    return before+'let mut '+index+'=0usize;loop{let Some('+item+')=('+pulled.code+')else{break;};'+_row(emitter,node,site,owner,Expression(item,pulled.kind),index)+index+'='+index+'.checked_add(1).ok_or_else(||native_error("OverflowError: dictionary update pair index".to_owned(),'+str(node.lineno)+','+emitter.location_code()+'))?;}'


def emit_values(emitter,node,site,owner,arguments,keywords,wanted):
    from .native_classes import Expression
    from .native_unions import project
    if site.error:
        from .native_class_builtins import _error
        from .native import _string
        return _error(emitter,node,wanted,_string(site.error)+'.to_owned()')
    setup,owner=emitter.capture(owner)
    def update(kind,code):
        stable=emitter.fresh();target=Expression(stable,kind);body='let '+stable+'=('+code+').clone();'
        if arguments:body+=_consume(emitter,node,site,target,arguments[0])
        if keywords:body+=preparation(emitter,node,stable,'prepare_keywords',str(len(keywords)))
        from .native import _string
        for name,value in keywords:body+=_insert(emitter,node,target,Expression('NativeText::from('+_string(name)+')','str'),value)
        return '{'+body+'()}'
    return Expression('{'+setup+project(owner.kind,owner.code,update)+'}',wanted)


def emit(emitter,node):
    from .call_semantics import normalize_call
    from .native_classes import Expression
    site=getattr(emitter.model,'mapping_update_calls',{}).get((emitter.plan.index,id(node),None))
    if site is None:return None
    setup,owner=emitter.capture(emitter.expression(node.func.value));arguments=[];keywords=[]
    normalized=normalize_call(node)
    for item in normalized.evaluation_order:
        before,value=emitter.capture(emitter.expression(item.expression));setup+=before
        if item.name is None:arguments.append(value)
        else:keywords.append((item.name,value))
    result=emit_values(emitter,node,site,owner,arguments,keywords,emitter.kind(node))
    return Expression('{'+setup+result.code+'}',result.kind)
