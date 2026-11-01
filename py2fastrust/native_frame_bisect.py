"""Captured builtin-list bisection sharing the ordinary typed Rust kernels."""
import ast
from dataclasses import dataclass
from .call_semantics import FunctionSignature,CallBindingError

NAMES=frozenset({'bisect','bisect_left','bisect_right','insort','insort_left','insort_right'})
SIGNATURE=FunctionSignature.declaration(('a','x','lo','hi'),keyword_only=('key',),default_names=('lo','hi','key'))

@dataclass
class BisectCall:
    result:object
    binding:object=None
    error:str|None=None
    key:object=None
    key_argument:object=None
    callback:object=None


def _contribute(model,destination,value,node):
    if not model.namespace.contribute(destination,value,node,force=True):model.contribute(destination,value,node)


def _sites(model):
    if not hasattr(model,'bisect_key_sites'):
        model.bisect_key_sites={}
        from .native_callback_effects import register
        register(model,lambda plan,node:any(key[:2]==(plan.index,id(node))and site.callback is not None for key,site in model.bisect_key_sites.items()))
    return model.bisect_key_sites


def requires_keys(unit,analysis):
    from .native_module_calls import BuiltinRef
    for facts in analysis.scopes.values():
        for call in facts.calls.values():
            if not any(isinstance(identity,BuiltinRef)and identity.module=='bisect'and identity.name in NAMES for identity in call.identity.alternatives):continue
            for name,value in call.keywords:
                if name=='key'and(value.unknown or value.unbound or value.alternatives!=frozenset({'none'})):return True
    return False


class BisectAdapter:
    NAMES=NAMES

    @staticmethod
    def analyze(model,plan,node,identity,call_arguments,arguments,keywords,environment,*,factory):
        from .native_classes import Cell,ClassUnsupported,shape,domain
        from .native_types import alternatives
        from .native_union_sequences import branches
        mutating=identity.name.startswith('insort')
        result=factory('none'if mutating else'int')
        try:binding=SIGNATURE.plan(call_arguments)
        except CallBindingError as error:
            raise ClassUnsupported(node,'bisect argument binding needs its captured C-API TypeError adapter: '+str(error),proof='bisection signature error transport')from None
        values=iter(arguments+[value for _,value in keywords])
        bound=binding.capture(lambda expression,parameter:next(values),defaults={'lo':Cell('int'),'hi':Cell('none'),'key':Cell('none')}).by_name
        sealed={'int','bool','int_bool','none','float','str','bytes','list','tuple','tuple_sequence','range','function','dict','set','dict_view','iterator','globals_dict'}
        for parameter in('lo','hi'):
            for kind in alternatives(shape(bound[parameter])):
                if kind is not None and domain(kind)not in sealed:
                    raise ClassUnsupported(node,'this bisection bound needs its user __index__ method; that index conversion adapter is not implemented',types=((parameter,kind),),proof='bisection integer index protocol')
        for kind in alternatives(shape(bound['a'])):
            if kind is not None and domain(kind)not in {'list','int','bool','int_bool','float','none','function'}:
                raise ClassUnsupported(node,'this bisection member adapter requires builtin list storage; other sequence subscription/insert protocols need their own adapter',types=(('sequence',kind),),proof='bisection sequence storage')
        if mutating:
            for source in branches(bound['a']):
                if source.tag=='list':_contribute(model,source.args[0],bound['x'],node)
        site=BisectCall(result,binding,key=bound['key'])
        sites=_sites(model);sites[(plan.index,id(node),identity.name)]=site
        key_kinds=[kind for kind in alternatives(shape(bound['key']))if kind!='none']if shape(bound['key'])is not None else[]
        if key_kinds:
            from .native_types import union_type,EmptyType
            from .native_classes import Environment
            from .call_semantics import Argument,CallArguments
            from .native_aot_callables import analyze_values
            item=model.cell(plan,node,identity=('bisect_key_argument',identity.name))
            for source in branches(bound['a']):
                if source.tag=='list':_contribute(model,item,source.args[0],node)
            if mutating:_contribute(model,item,bound['x'],node)
            site.key_argument=item
            if shape(item)is not None and not isinstance(shape(item),EmptyType):
                callback=model.cell_for_kind(union_type(*key_kinds))
                inside=Environment(environment)
                site.callback=analyze_values(model.callable_cells,plan,node,callback,
                    CallArguments((Argument(node),),()),[item],[],inside,identity=('bisect_key',identity.name))
                model.replace_environment(environment,model.join(environment,inside,node,('bisect_key',identity.name)))
        return site

    @staticmethod
    def emit(emitter,node,identity,record,arguments,keywords):
        from .native_classes import Expression,shape
        from .native_unions import project,union_kind
        from .native_class_builtins import _type_name,_error
        from .native import _string
        mutating=identity.name.startswith('insort');right=not identity.name.endswith('_left')
        wanted=shape(record.result)
        source=iter(arguments+[value for _,value in keywords])
        bound=record.binding.capture(lambda expression,parameter:next(source),defaults={'lo':Expression(emitter.literal(0),'int',0),'hi':Expression('()','none'),'key':Expression('()','none')}).by_name
        def index(value,parameter):
            if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:index(Expression('('+code+').clone()',kind),parameter))
            if value.kind=='none'and parameter=='hi':return 'None'
            if value.kind in {'int','bool','int_bool'}:
                return 'Some('+emitter.at('native_bisect_index(&('+emitter.number(value)+'))',node)+')'
            template="TypeError: argument should be integer or None, not '{}'"if parameter=='hi'else"TypeError: '{}' object cannot be interpreted as an integer"
            return emitter.at('Err::<Option<isize>,String>(format!('+_string(template)+','+_type_name(emitter,value,node)+'))',node)
        emitter.model.native_frame_bisect=True
        before='';bounds=[]
        for parameter in('lo','hi'):
            temporary=emitter.fresh();before+='let '+temporary+'='+index(bound[parameter],parameter)+';';bounds.append(temporary)
        def leaf(owner):
            if owner.kind in {'int','bool','int_bool','float','none','function'}or getattr(owner.kind,'_native_function_reference',False):
                typename=_type_name(emitter,owner,node)
                length_error='format!(\"TypeError: object of type \'{}\' has no len()\",'+typename+')'
                item_error='format!(\"TypeError: \'{}\' object does not support indexing\",'+typename+')'
                message='if '+bounds[0]+'.unwrap_or(0)<0{\"ValueError: lo must be non-negative\".to_owned()}else if '+bounds[1]+'.is_none()||'+bounds[1]+'==Some(-1){'+length_error+'}else{'+item_error+'}'
                return _error(emitter,node,wanted,message).code
            element=owner.kind.element
            item=bound['x'];comparator=_checked_advance(emitter,element,element if mutating else item.kind,node,right)
            view='&mut ('+owner.code+').borrow_mut()'if mutating else'&('+owner.code+').borrow()'
            item_code=emitter.coerce(item,element,node)if mutating else'&('+item.code+')'
            name='native_bisect_insert_checked'if mutating else'native_bisect_search_checked'
            emitter.model.native_frame_bisect=True
            code=emitter.at(name+'('+view+','+item_code+','+','.join(bounds)+','+comparator+')',node)
            if not mutating:code='class_from_usize('+code+')'
            return code
        owner=bound['a']
        def selected(key):
            if key.kind!='none':return _emit_keyed(emitter,node,identity,record,owner,bound['x'],key,bounds,wanted)
            return project(owner.kind,owner.code,lambda kind,code:leaf(Expression('('+code+').clone()',kind)))if union_kind(owner.kind)else leaf(owner)
        key=bound['key']
        code=project(key.kind,key.code,lambda kind,text:selected(Expression('('+text+').clone()',kind)))if union_kind(key.kind)else selected(key)
        return Expression('{'+before+code+'}',wanted)


def _emit_keyed(*arguments):
    from .native_bisect_keys import emit
    return emit(*arguments)


def _checked_advance(emitter,element,item,node,right):
    from .native import _string
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_types import EmptyType,TupleType,TupleSequenceType,immutable
    from .native_unions import project
    from .native_bisect import _advance
    from .native_frame_heapq import Comparator
    from .native_class_builtins import _type_name
    from .native_union_sequences import INTEGRAL,SEQUENCES,NONINDEXABLE
    left,right_name=emitter.fresh(),emitter.fresh()
    numeric=INTEGRAL|{'float'}
    sealed=numeric|SEQUENCES|NONINDEXABLE|{'range','globals_dict'}
    def leaf(a,x,b,y):
        numeric_pair=a in numeric and b in numeric
        text_pair=a==b and a in {'str','bytes'}
        tuple_pair=isinstance(a,(TupleType,TupleSequenceType))and isinstance(b,(TupleType,TupleSequenceType))
        if isinstance(a,EmptyType)or isinstance(b,EmptyType):return 'Ok(false)'
        if numeric_pair or text_pair or tuple_pair and immutable(a)and immutable(b):
            compare=_advance(Comparator(emitter),a,b,node,right)
            temporary=emitter.fresh()
            return '{let '+temporary+':fn(&'+emitter.rust_type(a)+',&'+emitter.rust_type(b)+')->bool='+compare+';Ok('+temporary+'(&('+x+'),&('+y+')))}'
        da,db=domain(a),domain(b)
        incompatible=(da in sealed and db in sealed and not {da,db}<=numeric
                      and not {da,db}<={'tuple','tuple_sequence'}
                      and not(da==db and da not in {'none','function','range','globals_dict'}))
        if incompatible:
            first=Expression(y,b)if right else Expression(x,a)
            second=Expression(x,a)if right else Expression(y,b)
            template="TypeError: '<' not supported between instances of '{}' and '{}'"
            return 'Err(format!('+_string(template)+','+_type_name(emitter,first,node)+','+_type_name(emitter,second,node)+'))'
        raise ClassUnsupported(node,'these bisection alternatives need mutable/custom ordering or an identity-aware tuple comparator; no exception-aware adapter for that pair is implemented',types=(('element',a),('item',b)),proof='bisection per-visited-element comparison protocol')
    body=project(element,'(*'+left+')',lambda a,x:project(item,'(*'+right_name+')',lambda b,y:leaf(a,x,b,y)))
    return '|'+left+':&'+emitter.rust_type(element)+','+right_name+':&'+emitter.rust_type(item)+'|->Result<bool,String>{'+body+'}'


def runtime(model):
    if not getattr(model,'native_frame_bisect',False):return ''
    from .native_bisect import helpers
    return helpers({'i64':64,'i128':128,'bigint':0}[model.integer],checked=True)
