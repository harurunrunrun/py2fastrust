"""Canonical module functions use one native CPython-compatible MT stream."""
from dataclasses import dataclass
from types import SimpleNamespace

from .call_semantics import FunctionSignature,CallBindingError
from .native_types import EMPTY,ListType,alternatives


SIGNATURES={
 'seed':FunctionSignature.declaration(('self','a','version'),default_names=('a','version')),
 'randrange':FunctionSignature.declaration(('self','start','stop','step'),default_names=('stop','step')),
 'randint':FunctionSignature.declaration(('self','a','b')),
 'shuffle':FunctionSignature.declaration(('self','x')),
}
C_FUNCTIONS=frozenset({'random','getrandbits'})
PRIMITIVE=frozenset({'int','bool','int_bool','float','none','str','bytes'})


@dataclass
class RandomCall:
    result:object
    error:str|None=None


def binding(name,positional,keywords,metadata):
    if name in C_FUNCTIONS:
        if keywords:return 'TypeError: Random.'+name+'() takes no keyword arguments'
        count=len(positional)
        if name=='random'and count:return 'TypeError: Random.random() takes no arguments ('+str(count)+' given)'
        if name=='getrandbits'and count!=1:return 'TypeError: Random.getrandbits() takes exactly one argument ('+str(count)+' given)'
        return None
    try:SIGNATURES[name].bind([None]+positional,keywords,{'a':None,'version':None,'stop':None,'step':None})
    except CallBindingError as error:
        from .native_aot_callables import binding_error
        target=SimpleNamespace(signature=SIGNATURES[name],qualified_name='Random.'+name,node=metadata)
        return binding_error(target,metadata,error,implicit_count=1)
    return None


def arguments(name,positional,keywords,*,emitter=None):
    if name in C_FUNCTIONS:return positional
    if emitter is None:
        from .native_classes import Cell
        none=Cell('none');integer=Cell('int')
    else:
        from .native_classes import Expression
        none=Expression('()','none');integer=Expression(emitter.literal(1),'int')
    defaults={'a':none,'version':integer if emitter is None else Expression(emitter.literal(2),'int'),'stop':none,'step':integer}
    return SIGNATURES[name].bind([none]+positional,keywords,defaults).by_name


def supported_index(model,node,value,label):
    from .native_classes import shape,ClassUnsupported,domain
    from .native_types import EmptyType
    sealed={'int','bool','int_bool','float','none','str','bytes','list','tuple','tuple_sequence','dict','set','deque','iterator','function','array','builtin_singleton','exception_class','exception_value'}
    for kind in alternatives(shape(value)):
        if kind is None or isinstance(kind,EmptyType)or domain(kind)in sealed:continue
        raise ClassUnsupported(node,'random '+label+' requires this value\'s __index__ conversion or an unimplemented native type-error adapter; builtin integral arguments and sealed primitive errors are implemented',types=((label,kind),),proof='native random '+label+' index protocol')


class RandomAdapter:
    NAMES=frozenset({'seed','random','getrandbits','randrange','randint','shuffle'})
    TYPES=frozenset()
    DISPLAY_REQUIRES_BOUND_RECEIVER=True

    @staticmethod
    def member_type_name(name):return 'builtin_function_or_method'if name in C_FUNCTIONS else'method'

    @staticmethod
    def analyze(model,plan,node,identity,metadata,positional,keywords,environment,*,factory):
        from .native_classes import shape,ClassUnsupported
        from .native_arrays import array_kind
        name=identity.name;failure=binding(name,positional,keywords,metadata)
        if failure:return RandomCall(factory(EMPTY),failure)
        values=arguments(name,positional,keywords)
        model.native_random_required=True
        if name=='seed':
            for kind in alternatives(shape(values['a'])):
                if kind is None or kind in {'none','int','bool','int_bool'}:continue
                if kind in {'str','bytes','float'}:
                    raise ClassUnsupported(node,'random.seed() with '+str(kind)+' needs its versioned text/hash or float-hash seed conversion; this native MT slice implements integer and None seeds',types=(('seed',kind),),proof='native random seed conversion')
                # Invalid sealed/container seeds produce Python's ordinary type error.
                from .native_classes import domain
                if domain(kind)=='object':raise ClassUnsupported(node,'random.seed() with a source instance needs its Python seed-type validation and possible custom version comparison; this seed object protocol is not implemented',proof='native random seed object validation')
            if any(kind is not None and kind not in PRIMITIVE for kind in alternatives(shape(values['version']))):
                raise ClassUnsupported(node,'random.seed(version=...) needs a custom equality protocol for this version value; only sealed primitive version comparisons are implemented',proof='random seed version comparison effects')
        elif name=='getrandbits':supported_index(model,node,values[0],'bit count')
        elif name=='randrange':
            supported_index(model,node,values['start'],'start')
            supported_index(model,node,values['stop'],'stop')
            supported_index(model,node,values['step'],'step')
        elif name=='randint':
            supported_index(model,node,values['a'],'lower bound')
            supported_index(model,node,values['b'],'upper bound')
        elif name=='shuffle':
            kind=shape(values['x'])
            if kind is not None and not isinstance(kind,ListType)and not array_kind(kind):
                raise ClassUnsupported(node,'random.shuffle() needs ordered mutable item access for this receiver; native standard lists and numeric arrays are implemented, but user/immutable sequence shuffle protocols are not',types=(('sequence',kind),),proof='native random mutable shuffle sequence')
        return RandomCall(factory('float'if name=='random'else'int'if name in {'getrandbits','randrange','randint'}else'none'))

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        from .native_classes import Expression,shape
        from .native import _string
        from .native_unions import union_kind,project
        wanted=shape(record.result)
        if record.error:return Expression(emitter.at('Err::<'+emitter.rust_type(wanted)+',String>('+_string(record.error)+'.to_owned())',node),wanted)
        name=identity.name;values=arguments(name,positional,keywords,emitter=emitter)
        if name=='seed':
            seed=values['a']
            def seeded(kind,code):
                value=Expression(code,kind)
                if kind=='none':return emitter.at('class_random_seed_none()',node)
                if kind in {'int','bool','int_bool'}:return emitter.at('class_random_seed_integer(&('+emitter.number(value)+'))',node)
                return emitter.at('Err::<(),String>("TypeError: The only supported seed types are:\\nNone, int, float, str, bytes, and bytearray.".to_owned())',node)
            code=project(seed.kind,seed.code,seeded)if union_kind(seed.kind)else seeded(seed.kind,seed.code)
        elif name=='random':code=emitter.at('class_random_float()',node)
        elif name=='getrandbits':code=emitter.at('class_random_bits(&('+index_value(emitter,node,values[0])+'))',node)
        elif name=='randrange':code=range_value(emitter,node,values)
        elif name=='randint':code=randint_value(emitter,node,values)
        else:code=shuffle_value(emitter,node,values['x'])
        return Expression(code,wanted)


def index_value(emitter,node,value):
    from .native_classes import Expression,ClassUnsupported
    from .native_types import EmptyType
    from .native_unions import union_kind,project
    from .native_class_builtins import _type_name
    if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:index_value(emitter,node,Expression(code,kind)))
    if isinstance(value.kind,EmptyType):return 'native_empty::<NativeInt>('+value.code+')'
    if value.kind in {'int','bool','int_bool'}:return emitter.number(value)
    return emitter.at('Err::<NativeInt,String>(format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,value,node)+'))',node)


def exact(emitter,code):
    return '('+code+').clone()'if emitter.model.integer=='bigint'else'Int::exact_small(('+code+')as i128)'


def is_one(emitter,value):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:is_one(emitter,Expression(code,kind)))
    if value.kind=='int':return '('+value.code+').to_i128()==Some(1)'if emitter.model.integer=='bigint'else'('+value.code+').clone()==1'
    if value.kind=='int_bool':
        check='value.to_i128()==Some(1)'if emitter.model.integer=='bigint'else'*value==1'
        return 'matches!(&('+value.code+'),NativeScalar::Int(value)if '+check+')'
    return 'false'


def range_value(emitter,node,values):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    start=values['start'];stop=values['stop'];step=values['step']
    first=emitter.fresh();setup='let '+first+'='+exact(emitter,index_value(emitter,node,Expression('('+start.code+').clone()',start.kind)))+';'
    def stopped(kind,code):
        if kind=='none':
            bad=emitter.at('Err::<(),String>("TypeError: Missing a non-None stop argument".to_owned())',node)
            return '{if !('+is_one(emitter,step)+'){'+bad+';}'+emitter.at('class_random_range_one(&'+first+')',node)+'}'
        stop_value=Expression(code,kind);last,stride=emitter.fresh(),emitter.fresh()
        prefix='let '+last+'='+exact(emitter,index_value(emitter,node,stop_value))+';let '+stride+'='+exact(emitter,index_value(emitter,node,Expression('('+step.code+').clone()',step.kind)))+';'
        start_text=emitter.show(start,node);stop_text=emitter.show(stop_value,node);step_text=emitter.show(step,node)
        message='|include_step|if include_step{format!("ValueError: empty range in randrange({}, {}, {})",'+start_text+','+stop_text+','+step_text+')}else{format!("ValueError: empty range in randrange({}, {})",'+start_text+','+stop_text+')}'
        return '{'+prefix+emitter.at('class_random_range_step(&'+first+',&'+last+',&'+stride+','+message+')',node)+'}'
    body=project(stop.kind,stop.code,stopped)if union_kind(stop.kind)else stopped(stop.kind,stop.code)
    return '{'+setup+body+'}'


def randint_value(emitter,node,values):
    from .native_classes import Expression
    lower,upper=values['a'],values['b']
    first,last=emitter.fresh(),emitter.fresh()
    setup='let '+first+'='+exact(emitter,index_value(emitter,node,Expression('('+lower.code+').clone()',lower.kind)))+';'
    setup+='let '+last+'='+exact(emitter,index_value(emitter,node,Expression('('+upper.code+').clone()',upper.kind)))+';'
    return '{'+setup+emitter.at('class_random_randint(&'+first+',&'+last+')',node)+'}'


def shuffle_value(emitter,node,value):
    from .native_classes import Expression,ClassUnsupported
    from .native_arrays import ArrayType
    from .native_unions import union_kind,project
    if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:shuffle_value(emitter,node,Expression(code,kind)))
    if isinstance(value.kind,ListType):target=value.code
    elif isinstance(value.kind,ArrayType):target=value.code+'.0'
    else:raise ClassUnsupported(node,'random.shuffle() receiver storage is not a native mutable sequence',proof='native random shuffle storage')
    return emitter.at('class_random_shuffle(&mut *('+target+').borrow_mut())',node)
