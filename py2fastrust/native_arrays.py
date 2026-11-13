"""Canonical array constructors and concrete numeric buffer operations."""
import ast
from dataclasses import dataclass

from .native_types import EMPTY,ListType,alternatives

C_TYPES={'b':'i8','B':'u8','h':'std::os::raw::c_short','H':'std::os::raw::c_ushort',
         'i':'std::os::raw::c_int','I':'std::os::raw::c_uint','l':'std::os::raw::c_long',
         'L':'std::os::raw::c_ulong','q':'i64','Q':'u64','f':'f32','d':'f64'}


@dataclass(frozen=True)
class ArrayType:
    code:str
    _native_array=True
    _native_stored_reference=True
    _native_reference_cloneable=True
    _native_owned_kinds=()
    _native_python_type_name='array.array'

    @property
    def _native_kind_tag(self):return 'array_'+self.code
    @property
    def element(self):return 'float'if self.code in 'fd'else'int'
    @property
    def rust(self):return 'ClassArray_'+self.code
    @property
    def raw(self):return C_TYPES[self.code]



def array_kind(kind):
    parts=alternatives(kind)
    return bool(parts)and all(isinstance(part,ArrayType)for part in parts)


def element_kind(kind):
    from .native_types import union_type
    return union_type(*(part.element for part in alternatives(kind)))


def retain(model,kind):
    if not hasattr(model,'native_array_codes'):model.native_array_codes=set()
    model.native_array_codes.add(kind.code)
    if kind.element=='float':model.formatting_required=True
    return kind


@dataclass
class ArrayCall:
    result:object
    kind:object=None
    error:str|None=None
    source:object=None


class ArrayAdapter:
    NAMES=frozenset({'array'})
    TYPES=NAMES

    @staticmethod
    def match_type(emitter,node,value,name):
        from .native_unions import project,union_kind
        from .native_classes import Expression
        if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:ArrayAdapter.match_type(emitter,node,Expression(code,kind),name))
        return str(isinstance(value.kind,ArrayType)).lower()

    @staticmethod
    def analyze(model,plan,node,identity,normalized_call,positional,keywords,environment,*,factory):
        from .native_classes import ClassUnsupported,shape
        error=None
        if keywords:error='TypeError: array.array() takes no keyword arguments'
        elif not positional:error='TypeError: array() takes at least 1 argument (0 given)'
        elif len(positional)>2:error='TypeError: array() takes at most 2 arguments ('+str(len(positional))+' given)'
        if error:return ArrayCall(factory(EMPTY),error=error)
        expression=normalized_call.positional[0].expression
        if not isinstance(expression,ast.Constant):
            raise ClassUnsupported(expression,'array typecode is not a proved literal character; runtime-varying array element layouts are not implemented',proof='static native array C element layout')
        code=expression.value
        if not isinstance(code,str):
            names={type(None):'NoneType',bool:'bool',int:'int',float:'float',bytes:'bytes'}
            error='TypeError: array() argument 1 must be a unicode character, not '+names.get(type(code),type(code).__name__)
        elif len(code)!=1:error='TypeError: array() argument 1 must be a unicode character, not a string of length '+str(len(code))
        elif code in 'uw':
            raise ClassUnsupported(expression,'array Unicode typecode '+repr(code)+' needs a native character buffer and Unicode conversion protocol; numeric array buffers are implemented',proof='array Unicode character storage')
        elif code not in C_TYPES:error='ValueError: bad typecode (must be b, B, u, w, h, H, i, I, l, L, q, Q, f or d)'
        if error:return ArrayCall(factory(EMPTY),error=error)
        kind=retain(model,ArrayType(code));record=ArrayCall(factory(kind),kind)
        if len(positional)==2:
            source=positional[1];tag=shape(source)
            if getattr(tag,'_native_bytearray',False):
                raise ClassUnsupported(node,'array construction from bytearray requires its raw bytes buffer rather than integer iteration; that mutable-buffer initializer is not implemented',proof='array constructor bytearray buffer export')
            if tag not in {'bytes','str'}:
                record.source=model.iterators.source(plan,node,source,('array_initializer',code),environment=environment)
                model.iterators.demand(plan,node,model.cell_for_kind(record.source),environment)
        return record

    @staticmethod
    def emit(emitter,node,identity,record,positional,keywords):
        from .native_classes import Expression
        from .native import _string
        if record.error:return error(emitter,node,EMPTY,_string(record.error)+'.to_owned()')
        kind=record.kind
        if len(positional)==1:return Expression(kind.rust+'(Rc::new(RefCell::new(Vec::new())))',kind)
        source=positional[1]
        if source.kind==kind:return Expression(emitter.at('class_array_'+str(ord(kind.code))+'_copy(&'+source.code+')',node),kind)
        if source.kind=='bytes':return Expression(emitter.at('class_array_'+str(ord(kind.code))+'_bytes(&'+source.code+')',node),kind)
        if source.kind=='str':return error(emitter,node,kind,_string('TypeError: cannot use a str to initialize an array with typecode '+repr(kind.code))+'.to_owned()')
        return build_iterable(emitter,node,kind,source,record.source)


def error(emitter,node,kind,message):
    from .native_classes import Expression
    return Expression(emitter.at('Err::<'+emitter.rust_type(kind)+',String>('+message+')',node),kind)


def decode(emitter,kind,code):
    if kind.element=='float':return '('+code+') as f64'
    return 'Int::from_i128(('+code+')as i128)'if emitter.model.integer=='bigint'else'('+code+')as NativeInt'


def pack(emitter,node,kind,value):
    from .native_classes import Expression,ClassUnsupported,domain
    from .native_unions import project,union_kind
    from .native_class_builtins import _type_name
    if union_kind(value.kind):return project(value.kind,value.code,lambda part,code:pack(emitter,node,kind,Expression(code,part)))
    from .native_types import EmptyType
    if isinstance(value.kind,EmptyType):return 'native_empty::<'+kind.raw+'>('+value.code+')'
    if value.kind in {'int','bool','int_bool'}:
        if kind.element=='float':
            from .native_float_constructor import frame_value
            return '('+frame_value(emitter,value,node)+')as '+kind.raw
        return emitter.at('class_array_'+str(ord(kind.code))+'_pack(&('+emitter.number(value)+'))',node)
    if kind.element=='float'and value.kind=='float':return '('+value.code+')as '+kind.raw
    if domain(value.kind)=='object':
        raise ClassUnsupported(node,'array element conversion needs this object\'s __index__ or __float__ protocol; custom numeric conversion for native array storage is not implemented',types=(('element',value.kind),),proof='array element numeric protocol')
    message=('format!("TypeError: must be real number, not {}",'+_type_name(emitter,value,node)+')'if kind.element=='float'else
             'format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,value,node)+')')
    return emitter.at('Err::<'+kind.raw+',String>('+message+')',node)


def build_iterable(emitter,node,kind,value,cursor_kind,*,append_to=None,atomic=False):
    from .native_classes import Expression
    cursor=emitter.model.iterators.construct(emitter,node,value,kind=cursor_kind)
    before,cursor=emitter.capture(cursor);result,item,converted=(emitter.fresh()for _ in range(3))
    setup=before
    if append_to is None or atomic:setup+='let '+result+'='+kind.rust+'(Rc::new(RefCell::new(Vec::new())));'
    else:setup+='let '+result+'=('+append_to.code+').clone();'
    pulled=emitter.model.iterators.pull(emitter,node,cursor)
    packed=pack(emitter,node,kind,Expression(item,pulled.kind))
    setup+='loop{let Some('+item+')=('+pulled.code+')else{break;};let '+converted+'='+packed+';'+emitter.at('class_array_'+str(ord(kind.code))+'_append_raw(&'+result+','+converted+')',node)+';}'
    if append_to is not None and atomic:setup+=emitter.at('class_array_'+str(ord(kind.code))+'_extend_raw(&'+append_to.code+',&'+result+')',node)+';'
    return Expression('{'+setup+(result if append_to is None else'()')+'}',kind if append_to is None else'none')


def indexed(model,plan,node,owner,index,environment,value=None):
    from .native_classes import shape
    kind=shape(owner)
    if not array_kind(kind):return None
    if not hasattr(model,'native_array_indices'):model.native_array_indices={}
    model.native_array_indices[plan.index,id(node)]=(model.flow_copy(owner),model.flow_copy(index))
    result=model.remember(plan,node,model.cell_for_kind(element_kind(kind)))if value is None else model.remember(plan,node,value)
    return result


def captured_store(model,plan,node,value,environment):
    if not isinstance(node,ast.Subscript):return False
    captured=getattr(model,'native_array_indices',{}).get((plan.index,id(node)))
    if captured is None:return False
    indexed(model,plan,node,*captured,environment,value)
    return True


def index_value(emitter,node,key):
    from .native_classes import ClassUnsupported,domain
    if key.kind in {'int','bool','int_bool'}:return emitter.number(key)
    if domain(key.kind)=='object':raise ClassUnsupported(node,'array index needs this object\'s __index__ protocol; native array indexing currently implements builtin integral keys and their builtin errors',types=(('index',key.kind),),proof='array index __index__ protocol')
    return emitter.at('Err::<NativeInt,String>("TypeError: array indices must be integers".to_owned())',node)


def emit_index(emitter,node,owner,key,wanted=None,value=None):
    from .native_classes import Expression
    kind=owner.kind
    from .native_unions import project,union_kind
    if not array_kind(kind):return None
    if union_kind(kind):
        return Expression(project(kind,owner.code,lambda part,code:emit_index(emitter,node,Expression(code,part),key,wanted,value).code),wanted or 'none')
    setup,index=emitter.capture(Expression(index_value(emitter,node,Expression('('+key.code+').clone()',key.kind)),'int'))
    offset=emitter.fresh();setup+='let '+offset+'='+emitter.at('class_array_'+str(ord(kind.code))+'_index(&'+owner.code+',&'+index.code+','+str(value is not None).lower()+')',node)+';'
    if value is None:
        raw=decode(emitter,kind,owner.code+'.0.borrow()['+offset+']')
        result=emitter.fresh();setup+='let '+result+'='+emitter.coerce(Expression(raw,kind.element),wanted,node)+';'
        return Expression('{'+setup+result+'}',wanted)
    raw=emitter.fresh();setup+='let '+raw+'='+pack(emitter,node,kind,value)+';'+owner.code+'.0.borrow_mut()['+offset+']='+raw+';'
    return Expression('{'+setup+'}', 'none')


def analyze_binary(model,plan,node,operator,left,right,*,identity=None):
    from .native_classes import shape,ClassUnsupported
    a,b=shape(left),shape(right)
    if any(not isinstance(kind,ArrayType)and any(isinstance(part,ArrayType)for part in alternatives(kind))for kind in (a,b)):
        raise ClassUnsupported(node,'array operators over differing typecode alternatives require a finite per-branch buffer-operation adapter; that operator layout is not implemented',proof='finite native array operator alternatives')
    if not isinstance(a,ArrayType)and not isinstance(b,ArrayType):return None
    if isinstance(operator,ast.Mult):kind=a if isinstance(a,ArrayType)else b
    elif isinstance(operator,ast.Add)and isinstance(a,ArrayType):kind=a
    else:raise ClassUnsupported(node,'native array operator '+type(operator).__name__+' is not implemented; array buffers currently support concatenation and repetition',types=(('left',a),('right',b)),proof='native array operator protocol')
    return model.cell(plan,node,kind,identity=identity)


def emit_binary(emitter,operator,left,right,node,wanted,*,inplace=False):
    from .native_classes import Expression
    from .native_class_builtins import _type_name
    if not isinstance(left.kind,ArrayType)and not isinstance(right.kind,ArrayType):return None
    if isinstance(operator,ast.Add)and isinstance(left.kind,ArrayType):
        kind=left.kind
        if right.kind!=kind:
            if inplace and not isinstance(right.kind,ArrayType):message='format!("TypeError: can only extend array with array (not \\\"{}\\\")",'+_type_name(emitter,right,node)+')'
            else:message='"TypeError: bad argument type for built-in operation".to_owned()'
            return error(emitter,node,wanted,message)
        method='extend_raw'if inplace else'concat'
        result=emitter.at('class_array_'+str(ord(kind.code))+'_'+method+'(&'+left.code+',&'+right.code+')',node)
        if inplace:result='{'+result+';'+left.code+'.clone()}'
        return emitter.encoded(result,kind,wanted,node)
    if isinstance(operator,ast.Mult):
        array,count=(left,right)if isinstance(left.kind,ArrayType)else(right,left);kind=array.kind
        if count.kind not in {'int','bool','int_bool'}:
            return error(emitter,node,wanted,'format!("TypeError: can\'t multiply sequence by non-int of type \'{}\'",'+_type_name(emitter,count,node)+')')
        result=emitter.at('class_array_'+str(ord(kind.code))+'_repeat(&'+array.code+',&('+emitter.number(count)+'),'+str(inplace).lower()+')',node)
        return emitter.encoded(result,kind,wanted,node)
    return None


def attribute(model,plan,node,owner):
    from .native_classes import shape,ClassUnsupported
    kind=shape(owner)
    if not array_kind(kind):return None
    if node.attr=='typecode':return model.cell(plan,node,'str')
    if node.attr=='itemsize':return model.cell(plan,node,'int')
    raise ClassUnsupported(node,'array attribute '+repr(node.attr)+' needs its native array attribute or retained bound-method adapter; that API is not implemented',proof='native array attribute '+node.attr)


def emit_attribute(emitter,node,owner,wanted):
    from .native_classes import Expression
    from .native import _string
    from .native_unions import union_kind,project
    if not array_kind(owner.kind):return None
    if union_kind(owner.kind):return Expression(project(owner.kind,owner.code,lambda part,code:emit_attribute(emitter,node,Expression(code,part),wanted).code),wanted)
    if node.attr=='typecode':return Expression('NativeText::from('+_string(owner.kind.code)+')',wanted)
    if node.attr=='itemsize':return Expression('class_from_usize(std::mem::size_of::<'+owner.kind.raw+'>())',wanted)
    return None


class ArrayCursor:
    @staticmethod
    def owned(record):
        from .native_classes import shape
        return (shape(record.source),)
    @staticmethod
    def demand(registry,plan,node,record,environment,active):return record.element
    @staticmethod
    def may_call(registry,record,seen):return False
    @staticmethod
    def fields(emitter,record):
        from .native_classes import shape
        return 'source:Option<'+emitter.rust_type(shape(record.source))+'>,index:usize'
    @staticmethod
    def pull(registry,emitter,node,value,active):
        from .native_classes import Expression,shape
        from .native_unions import project,union_kind
        kind=shape(value.kind.record.source);wanted=shape(value.kind.record.element)
        state,source,item=(emitter.fresh()for _ in range(3))
        reverse=value.kind.record.operation=='array_reverse'
        index=state+'.index-1'if reverse else state+'.index'
        def read(part,code):
            raw=emitter.fresh()
            converted=emitter.coerce(Expression(decode(emitter,part,raw),part.element),wanted,node)
            result=emitter.fresh()
            return '{let '+result+'=('+code+').0.borrow().get('+index+').copied().map(|'+raw+'|'+converted+');'+result+'}'
        select=project(kind,source,read)if union_kind(kind)else read(kind,source)
        if reverse:select='if '+state+'.index==0{None}else{'+select+'}'
        change=state+'.index'+('-=1;'if reverse else'+=1;')
        code='{let mut '+state+'='+value.code+'.borrow_mut();let '+item+'=match '+state+'.source.clone(){Some('+source+')=>'+select+',None=>None};match '+item+'{Some(value)=>{'+change+'Some(value)},None=>{'+state+'.source=None;None}}}'
        return Expression(code,wanted)



def source_cursor(registry,plan,node,value,identity,operation):
    from .native_classes import shape,Cell
    kind=shape(value)
    if not array_kind(kind):return None
    record=registry._record(plan,node,'array_reverse'if operation=='reverse'else'array_source',identity)
    record.adapter=ArrayCursor
    registry._contribute(record.source,value,node)
    registry._contribute(record.element,registry.model.cell_for_kind(element_kind(kind)),node)
    return record.kind


def construct_cursor(registry,emitter,node,value,kind):
    from .native_classes import Expression
    if not array_kind(value.kind):return None
    if kind is None:
        kind=registry.sites[emitter.plan.index,id(node),'array_source',None].kind
    if getattr(kind.record,'adapter',None)is not ArrayCursor:return None
    kind.record.emitted=True
    setup,owner=emitter.capture(value);index=emitter.fresh()
    if kind.record.operation=='array_reverse':
        from .native_unions import union_kind,project
        start=project(owner.kind,'('+owner.code+').clone()',lambda part,code:'{let len='+code+'.0.borrow().len();len}')if union_kind(owner.kind)else owner.code+'.0.borrow().len()'
    else:start='0_usize'
    setup+='let '+index+'='+start+';'
    from .native_classes import shape
    payload=emitter.coerce(owner,shape(kind.record.source),node)
    return Expression('{'+setup+'Rc::new(RefCell::new(ClassIteratorState_'+str(kind.index)+'{source:Some('+payload+'),index:'+index+'}))}',kind)


@dataclass
class ArrayMethod:
    owner:object
    name:str
    result:object
    error:str|None=None
    source:object=None


METHODS=frozenset({'append','extend','frombytes','fromlist','tobytes','tolist','pop','reverse','clear','byteswap'})


def method_binding(name,count,keywords):
    if name=='extend':
        total=count+len(keywords)
        if total>1:return 'TypeError: extend() takes at most 1 argument ('+str(total)+' given)'
        if count!=1:return 'TypeError: extend() takes exactly 1 positional argument ('+str(count)+' given)'
        return None
    if keywords:return 'TypeError: array.'+name+'() takes no keyword arguments'
    if name in {'append','frombytes','fromlist'}:
        if count!=1:return 'TypeError: array.'+name+'() takes exactly one argument ('+str(count)+' given)'
    elif name=='pop':
        if count>1:return 'TypeError: pop expected at most 1 argument, got '+str(count)
    elif count:return 'TypeError: array.'+name+'() takes no arguments ('+str(count)+' given)'
    return None


def analyze_method(model,plan,node,owner,arguments,keywords,environment):
    from .native_classes import shape,ClassUnsupported
    kind=shape(owner)
    if not isinstance(kind,ArrayType):
        if array_kind(kind):raise ClassUnsupported(node,'array method '+repr(node.func.attr)+' on differing typecode alternatives needs a finite per-branch method adapter; that call layout is not implemented',proof='finite native array method alternatives')
        return None
    name=node.func.attr
    if name not in METHODS:raise ClassUnsupported(node,'array method '+repr(name)+' is not implemented by the native numeric-buffer adapter',proof='native array method '+name)
    if any(isinstance(value,ast.Starred)for value in node.args)or any(key is None for key,_ in keywords):
        raise ClassUnsupported(node,'array method '+repr(name)+' with expanded starred/keyword arguments needs a retained typed method-binding adapter; that call form is not implemented',proof='expanded native array method arguments')
    error=method_binding(name,len(arguments),keywords)
    result=EMPTY if error else ListType(kind.element)if name=='tolist'else'bytes'if name=='tobytes'else kind.element if name=='pop'else'none'
    record=ArrayMethod(kind,name,model.cell_for_kind(result),error)
    if not error and name in {'extend','fromlist'}:
        value=arguments[0]
        if name=='extend'and array_kind(shape(value))and not isinstance(shape(value),ArrayType):
            raise ClassUnsupported(node,'array.extend() with differing array typecode alternatives needs exact per-branch typecode validation; that call layout is not implemented',proof='finite array extend typecode validation')
        if name=='fromlist'and not isinstance(shape(value),ListType):record.error='TypeError: arg must be list';record.result=model.cell_for_kind(EMPTY)
        elif name=='extend'and isinstance(shape(value),ArrayType)and shape(value)!=kind:
            record.error='TypeError: can only extend with array of same kind';record.result=model.cell_for_kind(EMPTY)
        else:
            record.source=model.iterators.source(plan,node,value,('array_method',name),environment=environment)
            model.iterators.demand(plan,node,model.cell_for_kind(record.source),environment)
    if not error and name=='frombytes'and getattr(shape(arguments[0]),'_native_bytearray',False):
        raise ClassUnsupported(node,'array.frombytes() from bytearray requires its mutable bytes-buffer export adapter; that buffer source form is not implemented',proof='array frombytes bytearray buffer export')
    if not hasattr(model,'native_array_methods'):
        model.native_array_methods={}
        from .native_callback_effects import register
        register(model,lambda caller,call:any(key==(caller.index,id(call))and site.source is not None for key,site in model.native_array_methods.items()))
    model.native_array_methods[plan.index,id(node)]=record
    return model.remember(plan,node,record.result)


def emit_method(emitter,node):
    from .call_semantics import normalize_call
    from .native_classes import Expression
    from .native_class_builtins import _type_name
    from .native import _string
    record=getattr(emitter.model,'native_array_methods',{}).get((emitter.plan.index,id(node)))
    if record is None:return None
    setup,owner=emitter.capture(emitter.expression(node.func.value));arguments=[]
    for argument in normalize_call(node).evaluation_order:
        before,value=emitter.capture(emitter.expression(argument.expression));setup+=before;arguments.append(value)
    wanted=emitter.kind(node);kind=record.owner;name=record.name
    if record.error:result=error(emitter,node,wanted,_string(record.error)+'.to_owned()')
    elif name=='extend'and isinstance(arguments[0].kind,ArrayType):
        result=Expression(emitter.at('class_array_'+str(ord(kind.code))+'_extend_raw(&'+owner.code+',&'+arguments[0].code+')',node),'none')
    elif name in {'extend','fromlist'}:
        result=build_iterable(emitter,node,kind,arguments[0],record.source,append_to=owner,atomic=name=='fromlist')
    elif name=='append':
        raw=emitter.fresh();code='let '+raw+'='+pack(emitter,node,kind,arguments[0])+';'+emitter.at('class_array_'+str(ord(kind.code))+'_append_raw(&'+owner.code+','+raw+')',node)+';'
        result=Expression('{'+code+'}', 'none')
    elif name=='frombytes':
        if arguments[0].kind!='bytes':result=error(emitter,node,'none','format!("TypeError: a bytes-like object is required, not \'{}\'",'+_type_name(emitter,arguments[0],node)+')')
        else:result=Expression(emitter.at('class_array_'+str(ord(kind.code))+'_extend_bytes(&'+owner.code+',&'+arguments[0].code+')',node),'none')
    elif name=='tobytes':result=Expression(emitter.at('class_array_'+str(ord(kind.code))+'_asbytes(&'+owner.code+')',node),'bytes')
    elif name=='tolist':
        raw=emitter.fresh();code=owner.code+'.0.borrow().iter().copied().map(|'+raw+'|'+decode(emitter,kind,raw)+').collect()'
        result=Expression('class_list('+code+')',ListType(kind.element))
    elif name in {'clear','reverse','byteswap'}:
        if name=='byteswap':code='class_array_'+str(ord(kind.code))+'_swap(&'+owner.code+');'
        else:code=owner.code+'.0.borrow_mut().'+name+'();'
        result=Expression('{'+code+'}', 'none')
    else:
        index=arguments[0]if arguments else Expression(emitter.literal(-1),'int')
        if index.kind not in {'int','bool','int_bool'}:
            result=error(emitter,node,wanted,'format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,index,node)+')')
        else:
            code=emitter.at('class_array_'+str(ord(kind.code))+'_pop(&'+owner.code+',&('+emitter.number(index)+'))',node)
            result=Expression(decode(emitter,kind,code),kind.element)
    before,result=emitter.capture(result)
    return Expression('{'+setup+before+emitter.coerce(result,wanted,node)+'}',wanted)
