"""Canonical mutable bytes over an owned, aliased native u8 buffer."""
import ast
from dataclasses import dataclass

@dataclass(frozen=True)
class ByteArrayType:
 _native_kind_tag='bytearray'
 _native_bytearray=True
 _native_stored_reference=True
 _native_reference_cloneable=True
 _native_owned_kinds=()
 _native_python_type_name='bytearray'
 rust='ClassByteArray'
 element='int'

BYTEARRAY=ByteArrayType()

def retain(model):
 model.native_bytearray_required=True
 model.native_bytes_constructor_required=True
 model.native_frame_slices_required=True
 return BYTEARRAY

def requires_frames(analysis):
 from .references import BuiltinIdentity
 return any(BuiltinIdentity('bytearray')in call.identity.alternatives for facts in analysis.scopes.values()for call in facts.calls.values())

@dataclass
class Construction:
 source:object=None
 error:str|None=None


def analyze_constructor(model,plan,node,arguments,keywords,environment,factory):
 from .native_classes import ClassUnsupported,shape
 if len(arguments)>1 or any(name in {'encoding','errors'}for name,_ in keywords):
  raise ClassUnsupported(node,'bytearray text encoding/errors construction is not implemented; empty, integral count, bytes, bytearray and typed integer iterable sources are implemented',proof='native bytearray encoding constructor')
 record=Construction()
 if len(arguments)+sum(name=='source'for name,_ in keywords)>1:record.error="TypeError: argument for bytearray() given by name ('source') and position (1)"
 for name,_ in keywords:
  if name!='source':record.error="TypeError: bytearray() got an unexpected keyword argument '"+str(name)+"'"
 values=arguments+[value for name,value in (keywords.items()if isinstance(keywords,dict)else keywords)if name=='source']
 if not record.error and values:
  kind=shape(values[0])
  if kind is None and not model.final:
   from .native_guard_flow import AnalysisPending
   raise AnalysisPending()
  if getattr(kind,'_native_array',False):
   raise ClassUnsupported(node,'bytearray construction from a numeric array requires its raw buffer export rather than integer iteration; that buffer-protocol constructor is not implemented',proof='bytearray raw numeric buffer initialization')
  from .native_types import alternatives
  if len(alternatives(kind))>1:
   raise ClassUnsupported(node,'bytearray constructor source alternatives need per-type count/buffer/iterable dispatch; that finite constructor-source adapter is not implemented',types=(('source',kind),),proof='finite bytearray constructor source alternatives')
  if kind not in {'int','bool','int_bool','bytes','str','float','none',BYTEARRAY}:
   record.source=model.iterators.source(plan,node,values[0],('bytearray_constructor',),environment=environment)
   model.iterators.demand(plan,node,model.cell_for_kind(record.source),environment)
 if not hasattr(model,'native_bytearray_constructors'):
  model.native_bytearray_constructors={}
  from .native_callback_effects import register
  register(model,lambda caller,call:(caller.index,id(call))in model.native_bytearray_constructors and model.native_bytearray_constructors[caller.index,id(call)].source is not None)
 model.native_bytearray_constructors[plan.index,id(node)]=record
 return factory(retain(model))


def failure(emitter,node,kind,message):
 from .native_classes import Expression
 return Expression(emitter.at('Err::<'+emitter.rust_type(kind)+',String>('+message+')',node),kind)


def pack(emitter,node,value):
 from .native_classes import ClassUnsupported,Expression
 from .native_unions import union_kind,project
 from .native_class_builtins import _type_name
 if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:pack(emitter,node,Expression(code,kind)))
 if value.kind in {'int','bool','int_bool'}:return emitter.at('class_bytearray_pack(&('+emitter.number(value)+'))',node)
 if getattr(value.kind,'name',None)is not None:
  raise ClassUnsupported(node,"bytearray element needs this source object's __index__ conversion; custom byte numeric conversion is not implemented",types=(('element',value.kind),),proof='bytearray element __index__ protocol')
 return emitter.at('Err::<u8,String>(format!("TypeError: \'{}\' object cannot be interpreted as an integer",'+_type_name(emitter,value,node)+'))',node)


def materialize(emitter,node,value,cursor_kind):
 from .native_classes import Expression
 values=emitter.fresh()
 if value.kind in {'bytes',BYTEARRAY}:
  code='('+value.code+').clone()'if value.kind=='bytes'else'('+value.code+').0.borrow().clone()'
  return 'let '+values+'='+code+';',values
 cursor=emitter.model.iterators.construct(emitter,node,value,kind=cursor_kind)
 setup,cursor=emitter.capture(cursor)
 pulled=emitter.model.iterators.pull(emitter,node,cursor);item=emitter.fresh();raw=emitter.fresh()
 setup+='let mut '+values+'=Vec::<u8>::new();loop{let Some('+item+')=('+pulled.code+')else{break;};let '+raw+'='+pack(emitter,node,Expression(item,pulled.kind))+';'
 setup+=emitter.at(values+'.try_reserve(1).map_err(|_|"MemoryError".to_owned())',node)+';'+values+'.push('+raw+');}'
 return setup,values


def emit_constructor(emitter,node,arguments,keywords):
 from .native_classes import Expression
 from .native import _string
 from .native_class_builtins import _type_name
 record=emitter.model.native_bytearray_constructors[emitter.plan.index,id(node)]
 if record.error:return failure(emitter,node,BYTEARRAY,_string(record.error)+'.to_owned()')
 values=arguments+[value for name,value in (keywords.items()if isinstance(keywords,dict)else keywords)if name=='source']
 if not values:return Expression('ClassByteArray(Rc::new(RefCell::new(Vec::new())))',BYTEARRAY)
 value=values[0]
 if value.kind in {'int','bool','int_bool'}:code=emitter.at('class_bytes_count(&('+emitter.number(value)+'))',node)
 elif value.kind in {'bytes',BYTEARRAY}:code='('+value.code+').clone()'if value.kind=='bytes'else'('+value.code+').0.borrow().clone()'
 elif value.kind in {'str','float','none'}:
  message='"TypeError: string argument without an encoding".to_owned()'if value.kind=='str'else'format!("TypeError: cannot convert \'{}\' object to bytearray",'+_type_name(emitter,value,node)+')'
  return failure(emitter,node,BYTEARRAY,message)
 else:
  setup,name=materialize(emitter,node,value,record.source)
  return Expression('{'+setup+'ClassByteArray(Rc::new(RefCell::new('+name+')))}',BYTEARRAY)
 data=emitter.fresh()
 return Expression('{let '+data+'='+code+';ClassByteArray(Rc::new(RefCell::new('+data+')))}',BYTEARRAY)


def analyze_binary(model,plan,node,operator,left,right,identity=None):
 from .native_classes import shape,ClassUnsupported
 a,b=shape(left),shape(right)
 if BYTEARRAY not in {a,b}:return None
 if isinstance(operator,ast.Add)and any(getattr(kind,'_native_array',False)for kind in(a,b)):
  raise ClassUnsupported(node,'bytearray concatenation with a numeric array requires its raw buffer export; that bytes-like operand adapter is not implemented',proof='bytearray concatenation raw buffer protocol')
 if isinstance(operator,ast.Add)and a not in {BYTEARRAY,'bytes'}:
  raise ClassUnsupported(node,'concatenation with bytearray on the right needs the original left operand protocol and type-specific error adapter; that reflected concatenation form is not implemented',proof='left operand bytearray concatenation protocol')
 if isinstance(node,ast.AugAssign)and isinstance(node.target,ast.Subscript)and isinstance(node.target.slice,ast.Slice):
  raise ClassUnsupported(node,'augmented bytearray slice assignment needs a retained captured-slice read/modify/write adapter; that augmented slice protocol is not implemented',proof='native bytearray augmented slice write')
 if isinstance(operator,(ast.Add,ast.Mult)):
  result='bytes'if isinstance(operator,ast.Add)and a=='bytes'else BYTEARRAY
  return model.cell(plan,node,result,identity=identity)
 raise ClassUnsupported(node,'bytearray operator '+type(operator).__name__+' is not implemented; native mutable bytes support concatenation and repetition',proof='native bytearray operator')


def emit_binary(emitter,operator,left,right,node,wanted,inplace=False):
 from .native_classes import Expression,ClassUnsupported
 from .native_class_builtins import _type_name
 if BYTEARRAY not in {left.kind,right.kind}:return None
 if isinstance(operator,ast.Mult):
  owner,count=(left,right)if left.kind==BYTEARRAY else(right,left)
  if count.kind not in {'int','bool','int_bool'}:return failure(emitter,node,wanted,'format!("TypeError: can\'t multiply sequence by non-int of type \'{}\'",'+_type_name(emitter,count,node)+')')
  return Expression(emitter.at('class_bytearray_repeat(&'+owner.code+',&('+emitter.number(count)+'),'+str(inplace).lower()+')',node),wanted)
 if isinstance(operator,ast.Add):
  if left.kind not in {BYTEARRAY,'bytes'}or right.kind not in {BYTEARRAY,'bytes'}:
   return failure(emitter,node,wanted,'format!("TypeError: can\'t concat {} to bytearray",'+_type_name(emitter,right,node)+')')
  source='('+right.code+').clone()'if right.kind=='bytes'else'('+right.code+').0.borrow().clone()'
  if left.kind=='bytes':return Expression('{let mut result='+left.code+'.clone();let other='+source+';'+emitter.at('result.try_reserve(other.len()).map_err(|_|"MemoryError".to_owned())',node)+';result.extend_from_slice(&other);result}',wanted)
  raw=emitter.fresh();setup=''
  if inplace and right.kind==BYTEARRAY:
   setup+='if Rc::ptr_eq(&'+left.code+'.0,&'+right.code+'.0)&&!'+right.code+'.0.borrow().is_empty(){'+emitter.at('Err::<(),String>("BufferError: Existing exports of data: object cannot be re-sized".to_owned())',node)+';}'
  setup+='let '+raw+'='+source+';'
  return Expression('{'+setup+emitter.at('class_bytearray_concat(&'+left.code+',&'+raw+','+str(inplace).lower()+')',node)+'}',wanted)
 raise ClassUnsupported(node,'this bytearray binary operator has no native lowering',proof='native bytearray binary operator')


def indexed(model,plan,node,owner,index,environment,value=None):
 from .native_classes import shape
 if shape(owner)!=BYTEARRAY:return None
 if not hasattr(model,'native_bytearray_indices'):model.native_bytearray_indices={}
 model.native_bytearray_indices[plan.index,id(node)]=(model.flow_copy(owner),model.flow_copy(index))
 return model.remember(plan,node,model.cell(plan,node,'int')if value is None else value)


def captured_store(model,plan,node,value,environment):
 record=getattr(model,'native_bytearray_indices',{}).get((plan.index,id(node)))
 if record is None:return False
 indexed(model,plan,node,*record,environment,value);return True


def key(emitter,node,value):
 from .native_class_builtins import _type_name
 from .native_classes import ClassUnsupported
 if value.kind in {'int','bool','int_bool'}:return emitter.at('class_bytearray_key(&('+emitter.number(value)+'))',node)
 if getattr(value.kind,'name',None)is not None:raise ClassUnsupported(node,'bytearray index requires the source object __index__ protocol; custom integral indexes are not implemented',proof='bytearray index __index__ protocol')
 return emitter.at('Err::<isize,String>(format!("TypeError: bytearray indices must be integers or slices, not {}",'+_type_name(emitter,value,node)+'))',node)


def emit_index(emitter,node,owner,index,wanted=None,value=None):
 from .native_classes import Expression
 if owner.kind!=BYTEARRAY:return None
 position=emitter.fresh();setup='let '+position+'='+key(emitter,node,index)+';'
 if value is not None:
  raw=emitter.fresh();setup+='let '+raw+'='+pack(emitter,node,value)+';'+emitter.at('class_bytearray_set(&'+owner.code+','+position+','+raw+')',node)+';'
  return Expression('{'+setup+'}', 'none')
 raw=emitter.at('class_bytearray_get(&'+owner.code+','+position+')',node)
 decoded='Int::from_i128(('+raw+')as i128)'if emitter.model.integer=='bigint'else'('+raw+')as NativeInt'
 return Expression('{'+setup+decoded+'}',wanted or'int')


@dataclass
class SliceWrite:
 bounds:tuple
 source:object
 cursor:object=None


def analyze_slice_store(model,plan,node,owner,value,environment):
 from .native_classes import shape,ClassUnsupported
 if shape(owner)!=BYTEARRAY or not isinstance(node.slice,ast.Slice):return False
 bounds=tuple(None if child is None else model.expression(plan,child,environment)for child in(node.slice.lower,node.slice.upper,node.slice.step))
 from .native_frame_slices import INTEGRAL,INVALID_BOUNDS
 from .native_classes import domain
 from .native_types import alternatives
 for bound in bounds:
  if bound is None:continue
  for kind in alternatives(shape(bound)):
   if kind is None and not model.final:continue
   if domain(kind)not in INTEGRAL|{'none'}|INVALID_BOUNDS:
    raise ClassUnsupported(node.slice,'bytearray slice bound needs its source __index__ method; custom slice-index conversion is not implemented',types=(('bound',kind),),proof='bytearray slice __index__ protocol')
 kind=shape(value)
 if getattr(kind,'_native_array',False):
  raise ClassUnsupported(node,'bytearray slice assignment from a numeric array requires its raw buffer bytes, not integer iteration; that buffer-protocol assignment is not implemented',proof='bytearray raw numeric buffer slice source')
 cursor=None
 if kind not in {BYTEARRAY,'bytes','int','bool','int_bool','float','none','str'}:
  cursor=model.iterators.source(plan,node,value,('bytearray_slice',),environment=environment)
  model.iterators.demand(plan,node,model.cell_for_kind(cursor),environment)
 if not hasattr(model,'native_bytearray_slices'):model.native_bytearray_slices={}
 model.native_bytearray_slices[plan.index,id(node)]=SliceWrite(bounds,model.flow_copy(value),cursor)
 model.native_frame_slices_required=True
 model.remember(plan,node,model.cell(plan,node,BYTEARRAY))
 return True


def reference(emitter,node):
 if not isinstance(node,ast.Subscript):return None
 if(emitter.plan.index,id(node))not in getattr(emitter.model,'native_bytearray_slices',{}):return None
 setup,owner=emitter.capture(emitter.expression(node.value));bounds=[]
 for child in(node.slice.lower,node.slice.upper,node.slice.step):
  if child is None:bounds.append(None)
  else:
   before,bound=emitter.capture(emitter.expression(child));setup+=before;bounds.append(bound)
 return setup,('bytearray_slice',owner,tuple(bounds))


def store_slice(emitter,reference,value,node):
 from .native_frame_slices import convert_bounds
 from .native_classes import ClassUnsupported
 setup,names=convert_bounds(emitter,node,reference[2])
 record=emitter.model.native_bytearray_slices[emitter.plan.index,id(node)]
 if value.kind in {'int','bool','int_bool','float','none','str'}:
  setup+='let _:(Option<i128>,Option<i128>,Option<i128>)=('+','.join(names)+');'
  return setup+failure(emitter,node,'none','"TypeError: can assign only bytes, buffers, or iterables of ints in range(0, 256)".to_owned()').code+';'
 before,values=materialize(emitter,node,value,record.cursor);setup+=before
 return setup+emitter.at('class_bytearray_slice_assign(&'+reference[1].code+','+','.join(names)+','+values+')',node)+';'


class BytearrayCursor:
 @staticmethod
 def owned(record):
  from .native_classes import shape
  return(shape(record.source),)
 @staticmethod
 def demand(registry,plan,node,record,environment,active):return record.element
 @staticmethod
 def may_call(registry,record,seen):return False
 @staticmethod
 def fields(emitter,record):return 'source:Option<ClassByteArray>,index:usize'
 @staticmethod
 def pull(registry,emitter,node,value,active):
  from .native_classes import Expression
  state,source,item=(emitter.fresh()for _ in range(3));reverse=value.kind.record.operation=='bytearray_reverse';index=state+'.index-1'if reverse else state+'.index'
  raw=emitter.fresh();decoded='Int::from_i128('+raw+' as i128)'if emitter.model.integer=='bigint'else raw+' as NativeInt'
  read='{let result='+source+'.0.borrow().get('+index+').copied().map(|'+raw+'|'+decoded+');result}'
  if reverse:read='if '+state+'.index==0{None}else{'+read+'}'
  change=state+'.index'+('-=1;'if reverse else'+=1;')
  return Expression('{let mut '+state+'='+value.code+'.borrow_mut();let '+item+'=match '+state+'.source.clone(){Some('+source+')=>'+read+',None=>None};match '+item+'{Some(value)=>{'+change+'Some(value)},None=>{'+state+'.source=None;None}}}','int')


def source_cursor(registry,plan,node,value,identity,operation):
 from .native_classes import shape
 if shape(value)!=BYTEARRAY:return None
 record=registry._record(plan,node,'bytearray_reverse'if operation=='reverse'else'bytearray_source',identity);record.adapter=BytearrayCursor
 from .native_iterator_hints import IndexedOwnerHint
 record.hint_protocol=IndexedOwnerHint(reverse=operation=='reverse')
 registry._contribute(record.source,value,node);registry._contribute(record.element,registry.model.cell_for_kind('int'),node)
 return record.kind


def construct_cursor(registry,emitter,node,value,kind):
 from .native_classes import Expression
 if value.kind!=BYTEARRAY:return None
 kind=kind or registry.sites[emitter.plan.index,id(node),'bytearray_source',None].kind
 if getattr(kind.record,'adapter',None)is not BytearrayCursor:return None
 kind.record.emitted=True
 setup,owner=emitter.capture(value);index=emitter.fresh();start=owner.code+'.0.borrow().len()'if kind.record.operation=='bytearray_reverse'else'0_usize'
 setup+='let '+index+'='+start+';'
 return Expression('{'+setup+'Rc::new(RefCell::new(ClassIteratorState_'+str(kind.index)+'{source:Some('+owner.code+'),index:'+index+'}))}',kind)


def comparison(emitter,operator,left,right,node):
 from .native_classes import ClassUnsupported
 if BYTEARRAY not in {left.kind,right.kind}:return None
 if isinstance(operator,(ast.Is,ast.IsNot)):
  code='Rc::ptr_eq(&'+left.code+'.0,&'+right.code+'.0)'if left.kind==right.kind==BYTEARRAY else'false'
  return '!('+code+')'if isinstance(operator,ast.IsNot)else code
 if isinstance(operator,(ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE)):
  if left.kind in {BYTEARRAY,'bytes'}and right.kind in {BYTEARRAY,'bytes'}:
   a=left.code+'.0.borrow().as_slice()'if left.kind==BYTEARRAY else left.code+'.as_slice()';b=right.code+'.0.borrow().as_slice()'if right.kind==BYTEARRAY else right.code+'.as_slice()'
   symbol={ast.Eq:'==',ast.NotEq:'!=',ast.Lt:'<',ast.LtE:'<=',ast.Gt:'>',ast.GtE:'>='}[type(operator)]
   return '('+a+')'+symbol+'('+b+')'
  if isinstance(operator,(ast.Eq,ast.NotEq)):return str(isinstance(operator,ast.NotEq)).lower()
 raise ClassUnsupported(node,'bytearray comparison '+type(operator).__name__+' needs a bytes-like or integral containment adapter; that comparison is not implemented',proof='native bytearray comparison')


@dataclass
class Method:
 name:str
 result:object
 error:str|None=None


def analyze_method(model,plan,node,owner,arguments,keywords,environment):
 from .native_classes import shape,ClassUnsupported
 if shape(owner)!=BYTEARRAY:return None
 name=node.func.attr
 if name not in {'append','extend','clear','copy','reverse'}:
  raise ClassUnsupported(node,'bytearray method '+repr(name)+' is not implemented; native methods currently implement append, bytes-like extend, clear, copy and reverse',proof='native bytearray method '+name)
 expected=1 if name in {'append','extend'}else 0
 error=None
 if keywords:error='TypeError: bytearray.'+name+'() takes no keyword arguments'
 elif len(arguments)!=expected:error='TypeError: bytearray.'+name+'() takes '+('exactly one argument'if expected else'no arguments')+' ('+str(len(arguments))+' given)'
 if not error and name=='extend'and shape(arguments[0])not in {BYTEARRAY,'bytes'}:
  raise ClassUnsupported(node,'bytearray.extend() from a non-buffer iterable requires its source length-hint schedule before atomic byte validation; that iterable extend form is not implemented',proof='bytearray iterable extend source length hint')
 result=BYTEARRAY if name=='copy'else'none'
 if not hasattr(model,'native_bytearray_methods'):model.native_bytearray_methods={}
 model.native_bytearray_methods[plan.index,id(node)]=Method(name,result,error)
 return model.remember(plan,node,model.cell(plan,node,result))


def emit_method(emitter,node):
 from .native_classes import Expression
 from .native import _string
 from .call_semantics import normalize_call
 record=getattr(emitter.model,'native_bytearray_methods',{}).get((emitter.plan.index,id(node)))
 if record is None:return None
 setup,owner=emitter.capture(emitter.expression(node.func.value));arguments=[]
 for argument in normalize_call(node).evaluation_order:
  before,value=emitter.capture(emitter.expression(argument.expression));setup+=before;arguments.append(value)
 if record.error:result=failure(emitter,node,record.result,_string(record.error)+'.to_owned()')
 elif record.name=='append':
  raw=emitter.fresh();code='let '+raw+'='+pack(emitter,node,arguments[0])+';'+emitter.at('class_bytearray_append(&'+owner.code+','+raw+')',node)+';'
  result=Expression('{'+code+'}','none')
 elif record.name=='extend':
  source=arguments[0];raw=emitter.fresh();code='let '+raw+'='+('('+source.code+').clone()'if source.kind=='bytes'else'('+source.code+').0.borrow().clone()')+';'+emitter.at('class_bytearray_concat(&'+owner.code+',&'+raw+',true)',node)+';'
  result=Expression('{'+code+'}','none')
 elif record.name=='copy':
  data=emitter.fresh();result=Expression('{let '+data+'='+owner.code+'.0.borrow().clone();ClassByteArray(Rc::new(RefCell::new('+data+')))}',BYTEARRAY)
 else:
  code=owner.code+'.0.borrow_mut().'+record.name+'();'
  result=Expression('{'+code+'}','none')
 return Expression('{'+setup+result.code+'}',record.result)
