"""Typed, fallible heap comparisons without borrowing across source callbacks."""
import ast
from dataclasses import dataclass

from .native_types import ListType,TupleType,TupleSequenceType,alternatives,EmptyType


@dataclass
class Comparison:
 index:object
 truth:object
 rich:bool


def builtin_kind(kind):
 if getattr(kind,'_native_named_tuple',False):return False
 if kind in {'int','bool','int_bool','str','bytes','none'}or isinstance(kind,EmptyType):return True
 parts=alternatives(kind)
 if len(parts)>1:return all(builtin_kind(part)for part in parts)
 if isinstance(kind,(ListType,TupleSequenceType)):return builtin_kind(kind.element)
 if isinstance(kind,TupleType):return all(builtin_kind(field)for field in kind.fields)
 return False


def analyze(model,plan,node,name,heap,environment):
 from .native_classes import shape,Environment,ClassUnsupported,InstanceType
 from .native_heapq import orderable
 kind=shape(heap.args[0])
 if kind is None or orderable(kind):return None
 from .native_nested_heap_comparisons import analyze as nested_compare
 nested=nested_compare(model,plan,node,name,heap,environment)
 if nested is not None:return nested
 index=('heap_less',name,shape(heap));truth=('heap_truth',name,shape(heap))
 inside=Environment(environment)
 if all(isinstance(part,InstanceType)or builtin_kind(part)for part in alternatives(kind)):
  result=model.operators.comparison(plan,node,index,ast.Lt(),heap.args[0],heap.args[0],inside)
  if result is not None:
   from .native_source_lengths import analyze_truth
   analyze_truth(model,plan,node,result,inside,identity=truth)
   model.replace_environment(environment,model.join(environment,inside,node,'heap_comparison'))
   return Comparison(index,truth,True)
  if builtin_kind(kind):return Comparison(index,truth,False)
 if not model.final:return None
 raise ClassUnsupported(node,'heap item ordering needs an unimplemented nested source comparison, floating-container identity/NaN, key-wrapper or other object protocol; direct source rich comparisons and finite builtin integer/text/list/tuple keys are implemented',types=(('element',kind),),proof='typed fallible heap comparison protocol')


def _builtin(emitter,operator,left,right,node):
 from .native_classes import Expression,ClassUnsupported
 from .native_unions import union_kind,project
 from .native_class_builtins import _type_name
 if union_kind(left.kind):return project(left.kind,left.code,lambda kind,code:_builtin(emitter,operator,Expression('('+code+').clone()',kind),right,node))
 if union_kind(right.kind):return project(right.kind,right.code,lambda kind,code:_builtin(emitter,operator,left,Expression('('+code+').clone()',kind),node))
 a,b=left.kind,right.kind
 from .native_float_identity import scalar_comparison
 identity=scalar_comparison(emitter,operator,left,right,node,identity=True)
 if identity is not None:return identity
 equal=isinstance(operator,ast.Eq)
 if isinstance(a,(TupleType,TupleSequenceType))and isinstance(b,(TupleType,TupleSequenceType))and type(a)is not type(b):
  raise ClassUnsupported(node,'heap tuple keys mixing fixed and homogeneous runtime layouts need a cross-layout lexicographic comparator; that tuple-storage pairing is not implemented',types=(('left',a),('right',b)),proof='cross-layout heap tuple comparator')
 if isinstance(a,EmptyType)or isinstance(b,EmptyType):return 'false'
 if a in {'int','bool','int_bool'}and b in {'int','bool','int_bool'}:
  return '('+emitter.number(left)+')'+('=='if equal else'<')+'('+emitter.number(right)+')'
 if a==b and a in {'str','bytes'}:return '('+left.code+')'+('=='if equal else'<')+'('+right.code+')'
 if a=='none'or b=='none':
  if equal:return str(a==b).lower()
 elif isinstance(a,TupleType)and isinstance(b,TupleType):
  result=str(len(a.fields)==len(b.fields)if equal else len(a.fields)<len(b.fields)).lower()
  for index in reversed(range(min(len(a.fields),len(b.fields)))):
   x=Expression('('+left.code+').'+str(index)+'.clone()',a.fields[index]);y=Expression('('+right.code+').'+str(index)+'.clone()',b.fields[index])
   same=_builtin(emitter,ast.Eq(),x,y,node)
   result='('+same+')&&('+result+')'if equal else'if '+same+'{'+result+'}else{'+_builtin(emitter,ast.Lt(),x,y,node)+'}'
  return '{'+result+'}'
 elif (isinstance(a,ListType)and isinstance(b,ListType))or(isinstance(a,TupleSequenceType)and isinstance(b,TupleSequenceType)):
  first,second,read_a,read_b,x,y,outcome=(emitter.fresh()for _ in range(7))
  item_a=Expression(x+'.clone()',a.element);item_b=Expression(y+'.clone()',b.element)
  same=_builtin(emitter,ast.Eq(),item_a,item_b,node)
  access_a=first+'.borrow()'if isinstance(a,ListType)else first+'.as_slice()'
  access_b=second+'.borrow()'if isinstance(b,ListType)else second+'.as_slice()'
  setup='let '+first+'=('+left.code+').clone();let '+second+'=('+right.code+').clone();let '+read_a+'='+access_a+';let '+read_b+'='+access_b+';'
  if equal:return '{'+setup+read_a+'.len()=='+read_b+'.len()&&'+read_a+'.iter().zip('+read_b+'.iter()).all(|('+x+','+y+')|'+same+')}'
  less=_builtin(emitter,ast.Lt(),item_a,item_b,node)
  return '{'+setup+'let mut '+outcome+'='+read_a+'.len()<'+read_b+'.len();for('+x+','+y+')in '+read_a+'.iter().zip('+read_b+'.iter()){if !('+same+'){'+outcome+'='+less+';break;}}'+outcome+'}'
 if equal:return 'false'
 return emitter.at('Err::<bool,String>(format!("TypeError: \'<\' not supported between instances of \'{}\' and \'{}\'",'+_type_name(emitter,left,node)+','+_type_name(emitter,right,node)+'))',node)


def emit(emitter,node,name,heap,arguments,wanted,comparison):
 from .native_classes import Expression
 from .native_class_calls import entry_result
 maximum=name.endswith('_max');operation=name.removesuffix('_max')
 asynchronous=not entry_result(emitter.model,emitter.plan)
 modes=getattr(emitter.model,'native_fallible_heap_modes',None)
 if modes is None:modes=emitter.model.native_fallible_heap_modes=set()
 modes.add(asynchronous)
 first,second=emitter.fresh(),emitter.fresh()
 a,b=Expression(first,heap.kind.element),Expression(second,heap.kind.element)
 if maximum:a,b=b,a
 setup=''
 if getattr(comparison,'_native_nested_heap_comparison',False):
  from .native_nested_heap_comparisons import emit as nested_compare
  less=nested_compare(emitter,node,comparison,a,b)
 elif comparison.rich:
  value=emitter.model.operators.emit_comparison(emitter,node,comparison.index,ast.Lt(),a,b)
  setup,value=emitter.capture(value)
  less=emitter.truth(value,node,identity=comparison.truth)
 else:less=_builtin(emitter,ast.Lt(),a,b,node)
 closure=('async 'if asynchronous else'')+'|'+first+':'+emitter.rust_type(heap.kind.element)+','+second+':'+emitter.rust_type(heap.kind.element)+'|{'+setup+'Ok::<bool,NativeError>('+less+')}'
 parameters='&'+heap.code
 if len(arguments)==2:parameters+=','+emitter.coerce(arguments[1],heap.kind.element,node)
 parameters+=','+closure+',&|message:&str|native_error(message.to_owned(),'+str(node.lineno)+','+emitter.location_code()+')'
 code='native_fallible_'+operation+('_async'if asynchronous else'')+'('+parameters+')'+('.await'if asynchronous else'')+'?'
 kind='none'if operation in {'heapify','heappush'}else heap.kind.element
 return emitter.coerce(Expression(code,kind),wanted,node)


def runtime(model):
 modes=getattr(model,'native_fallible_heap_modes',())
 if not modes:return ''
 from .native_fallible_heap_runtime import kernel
 return '\n'.join(kernel(asynchronous=mode)for mode in sorted(modes))
