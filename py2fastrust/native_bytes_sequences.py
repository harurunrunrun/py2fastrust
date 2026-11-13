"""Checked immutable byte operations, independent of mutable-buffer callers."""
import ast


def requires_frames(unit,analysis):
 nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
 from .native_types import alternatives
 for facts in analysis.scopes.values():
  for site,node in nodes.items():
   if not isinstance(node,(ast.BinOp,ast.AugAssign))or not isinstance(node.op,(ast.Add,ast.Mult)):continue
   operands=(node.left,node.right)if isinstance(node,ast.BinOp)else(node.target,node.value)
   kind=facts.expressions.get(site)
   if any('bytes'in alternatives(value)for value in(kind,*(facts.expressions.get(unit.ordinal(child))for child in operands))):return True
 return False


def analyze(model,plan,node,operator,left,right,identity=None):
 from .native_classes import shape
 from .native_types import alternatives
 a,b=shape(left),shape(right)
 # Finite primitive dispatch emits these same concrete operations per arm.
 # Register their helpers even when the enclosing result includes an error arm.
 for first in alternatives(a):
  for second in alternatives(b):
   if isinstance(operator,ast.Add)and first==second=='bytes':model.native_bytes_concat_required=True
   if isinstance(operator,ast.Mult)and 'bytes'in {first,second}and(second if first=='bytes'else first)in {'int','bool','int_bool'}:model.native_bytes_repeat_required=True
 if isinstance(operator,ast.Add)and a==b=='bytes':return model.cell(plan,node,'bytes',identity=identity)
 if not isinstance(operator,ast.Mult)or 'bytes'not in {a,b}:return None
 count=b if a=='bytes'else a
 if count not in {'int','bool','int_bool'}:return None
 model.native_bytes_repeat_required=True
 return model.cell(plan,node,'bytes',identity=identity)


def emit(emitter,operator,left,right,node,wanted):
 from .native_classes import Expression
 if isinstance(operator,ast.Add)and left.kind==right.kind=='bytes':
  source=left.code if left.owned else '('+left.code+').clone()'
  return Expression(emitter.at('class_bytes_concat('+source+',&'+right.code+')',node),wanted)
 if not isinstance(operator,ast.Mult)or 'bytes'not in {left.kind,right.kind}:return None
 source,count=(left,right)if left.kind=='bytes'else(right,left)
 if count.kind not in {'int','bool','int_bool'}:return None
 return Expression(emitter.at('class_bytes_repeat(&'+source.code+',&('+emitter.number(count)+'))',node),wanted)


def runtime(model):
 result=[]
 if getattr(model,'native_bytes_concat_required',False):result.append(r'''
fn class_bytes_concat(mut left:Vec<u8>,right:&[u8])->Result<Vec<u8>,String>{
 left.len().checked_add(right.len()).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"MemoryError".to_owned())?;
 left.try_reserve(right.len()).map_err(|_|"MemoryError".to_owned())?;left.extend_from_slice(right);Ok(left)
}
''')
 if not getattr(model,'native_bytes_repeat_required',False):return '\n'.join(result)
 number='count.to_i128()'if model.integer=='bigint'else'Some(*count as i128)'
 result.append(r'''
fn class_bytes_repeat(source:&[u8],count:&NativeInt)->Result<Vec<u8>,String>{
 let count=NUMBER.and_then(|count|isize::try_from(count).ok()).ok_or_else(||"OverflowError: cannot fit 'int' into an index-sized integer".to_owned())?.max(0)as usize;
 let length=source.len().checked_mul(count).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"OverflowError: repeated bytes are too long".to_owned())?;
 let mut output=Vec::new();output.try_reserve(length).map_err(|_|"MemoryError".to_owned())?;
 if !source.is_empty(){for _ in 0..count{output.extend_from_slice(source);}}Ok(output)
}
'''.replace('NUMBER',number))
 return '\n'.join(result)
