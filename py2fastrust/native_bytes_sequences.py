"""Checked immutable byte repetition, independent of mutable-buffer callers."""
import ast


def requires_frames(unit,analysis):
 nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
 return any(isinstance(nodes.get(site),ast.BinOp)and isinstance(nodes[site].op,ast.Mult)
            and kind=='bytes'for facts in analysis.scopes.values()for site,kind in facts.expressions.items())


def analyze(model,plan,node,operator,left,right,identity=None):
 from .native_classes import shape
 a,b=shape(left),shape(right)
 if not isinstance(operator,ast.Mult)or 'bytes'not in {a,b}:return None
 count=b if a=='bytes'else a
 if count not in {'int','bool','int_bool'}:return None
 model.native_bytes_repeat_required=True
 return model.cell(plan,node,'bytes',identity=identity)


def emit(emitter,operator,left,right,node,wanted):
 from .native_classes import Expression
 if not isinstance(operator,ast.Mult)or 'bytes'not in {left.kind,right.kind}:return None
 source,count=(left,right)if left.kind=='bytes'else(right,left)
 if count.kind not in {'int','bool','int_bool'}:return None
 return Expression(emitter.at('class_bytes_repeat(&'+source.code+',&('+emitter.number(count)+'))',node),wanted)


def runtime(model):
 if not getattr(model,'native_bytes_repeat_required',False):return ''
 number='count.to_i128()'if model.integer=='bigint'else'Some(*count as i128)'
 return r'''
fn class_bytes_repeat(source:&[u8],count:&NativeInt)->Result<Vec<u8>,String>{
 let count=NUMBER.and_then(|count|isize::try_from(count).ok()).ok_or_else(||"OverflowError: cannot fit 'int' into an index-sized integer".to_owned())?.max(0)as usize;
 let length=source.len().checked_mul(count).filter(|length|*length<=isize::MAX as usize).ok_or_else(||"OverflowError: repeated bytes are too long".to_owned())?;
 let mut output=Vec::new();output.try_reserve(length).map_err(|_|"MemoryError".to_owned())?;
 if !source.is_empty(){for _ in 0..count{output.extend_from_slice(source);}}Ok(output)
}
'''.replace('NUMBER',number)
