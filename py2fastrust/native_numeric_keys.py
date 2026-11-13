"""Closed numeric key equality, rational hashes and checked query projection."""
import ast
import math
from .native_types import EmptyType,TupleType,TupleSequenceType,alternatives

NUMERIC=frozenset({'int','bool','int_bool','float'})


def numeric(kind):
    choices=alternatives(kind)
    return bool(choices)and all(type(choice)is str and choice in NUMERIC for choice in choices)


def common_key(kind):
    """A canonical hash ABI, independent of the retained source key ABI."""
    from .native_unions import union_kind
    from .native_types import union_type
    if not union_kind(kind)or numeric(kind):return kind
    choices=alternatives(kind)
    if choices and all(isinstance(choice,TupleType)for choice in choices):
        length=len(choices[0].fields)
        if all(len(choice.fields)==length for choice in choices):
            fields=tuple(common_key(union_type(*(choice.fields[index]for choice in choices)))for index in range(length))
            if all(field is not None for field in fields):return TupleType(fields)
    return None


def floating(kind):
    from .native_float_identity import floating as contains
    return contains(kind)


def requires_frames(unit,analysis):
    from .native_key_types import DictType,SetType
    from .native_constraints import Allocation
    from .references import BuiltinIdentity
    def owner(facts,node):
        site=unit.ordinal(node);kind=facts.expressions.get(site)
        if isinstance(kind,(DictType,SetType))or kind in {'dict_int','set_int'}:return True
        return any(isinstance(choice,Allocation)and choice.category in {'dict','set'}for choice in getattr(facts.values.get(site),'alternatives',()))
    def source_key(kind,dictionary):
        from .native_types import ListType
        if isinstance(kind,(DictType,SetType)):return kind.key
        if isinstance(kind,(ListType,TupleSequenceType)):
            element=kind.element
            return element.fields[0]if dictionary and isinstance(element,TupleType)and len(element.fields)==2 else element if not dictionary else None
        return None
    for facts in analysis.scopes.values():
        for kind in facts.expressions.values():
            if isinstance(kind,(DictType,SetType))and floating(kind.key):return True
        for node in ast.walk(unit.tree):
            site=unit.ordinal(node)
            if isinstance(node,(ast.Dict,ast.Set,ast.DictComp,ast.SetComp)):
                keys=node.keys if isinstance(node,ast.Dict)else node.elts if isinstance(node,ast.Set)else(node.key,)if isinstance(node,ast.DictComp)else(node.elt,)
                if any(key is not None and floating(facts.expressions.get(unit.ordinal(key)))for key in keys):return True
            if isinstance(node,ast.Subscript)and owner(facts,node.value)and floating(facts.expressions.get(unit.ordinal(node.slice))):return True
            if isinstance(node,ast.Compare):
                values=[node.left,*node.comparators]
                if any(isinstance(operation,(ast.In,ast.NotIn))and owner(facts,values[index+1])and floating(facts.expressions.get(unit.ordinal(values[index])))for index,operation in enumerate(node.ops)):return True
            if not isinstance(node,ast.Call):continue
            call=facts.calls.get(site)
            if call is not None:
                for name in ('dict','set'):
                    if BuiltinIdentity(name)in call.identity.alternatives and any(floating(source_key(facts.expressions.get(unit.ordinal(arg)),name=='dict'))for arg in node.args):return True
            if isinstance(node.func,ast.Attribute)and owner(facts,node.func.value)and any(floating(facts.expressions.get(unit.ordinal(arg)))for arg in node.args):return True
    return False


def canonical(emitter,value):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:canonical(emitter,Expression('('+code+').clone()',kind)))
    if value.kind=='float':return 'NativeNumericKey::Float(('+value.code+').clone())'
    return 'NativeNumericKey::Integer('+emitter.number(Expression('('+value.code+').clone()',value.kind))+')'


def query(emitter,value,wanted):
    from .native_classes import Expression
    from .native_unions import project,union_kind
    if not numeric(value.kind)or not numeric(wanted):return None
    if floating(wanted):return 'Some('+canonical(emitter,value)+')'
    if union_kind(value.kind):return project(value.kind,value.code,lambda kind,code:query(emitter,Expression('('+code+').clone()',kind),wanted))
    if value.kind=='float':
        emitter.model.native_numeric_query_required=True
        return 'native_numeric_query_integer('+emitter.scalar(value).code+')'
    return None


def record_source(model,record,value,node):
    sources=getattr(model,'native_numeric_key_sources',None)
    if sources is None:sources=model.native_numeric_key_sources={}
    sources.setdefault(record.index,{})[id(node),id(value)]=(value,node)


def literal_non_nan(node):
    if isinstance(node,ast.Constant):return type(node.value)in {int,bool,str,bytes,type(None)}or type(node.value)is float and not math.isnan(node.value)
    if isinstance(node,ast.Tuple):return all(literal_non_nan(child)for child in node.elts)
    return isinstance(node,ast.UnaryOp)and isinstance(node.op,(ast.UAdd,ast.USub))and isinstance(node.operand,ast.Constant)and type(node.operand.value)in {int,float}and literal_non_nan(node.operand)


def sequence_non_nan(node):
    return isinstance(node,(ast.List,ast.Tuple))and all(literal_non_nan(child)for child in node.elts)


def non_nan_record(model,record,active=frozenset()):
    from .native_classes import shape
    from .native_class_mappings import mapping_kind
    if not floating(shape(record.key)):return True
    if record.index in active:return False
    active=active|{record.index}
    sources=getattr(model,'native_numeric_key_sources',{}).get(record.index,{})
    if not sources:return False
    def source_safe(value,node):
        from .native_class_mappings import key_pending
        if key_pending(shape(value)):return False
        if not floating(shape(value)):return True
        if literal_non_nan(node):return True
        if not isinstance(node,ast.Call):return False
        if node is record.node and record.operation=='constructor':
            if len(node.args)==1 and not node.keywords and sequence_non_nan(node.args[0]):return True
            source=shape(record.source)if record.source is not None else None
            choices=alternatives(source)
            if choices and all(mapping_kind(kind)and value is kind.record.key and non_nan_record(model,kind.record,active)for kind in choices):return True
        for(_,site),(receiver,name)in model.mappings.methods.items():
            if site!=id(node)or node.keywords:continue
            choices=alternatives(shape(receiver))
            if name=='add'and any(mapping_kind(kind)and kind.record is record for kind in choices):
                return len(node.args)==1 and literal_non_nan(node.args[0])
            if name=='copy'and node is record.node and record.operation=='copy':
                return bool(choices)and all(mapping_kind(kind)and non_nan_record(model,kind.record,active)for kind in choices)
        for(_,site),call in model.mappings.set_methods.sites.items():
            if site!=id(node)or getattr(call,'expanded',False)or call.keywords:continue
            if any(mapping_kind(kind)and kind.record is record for kind in alternatives(shape(call.receiver))):
                return all(sequence_non_nan(argument)for argument in node.args)
        return False
    return all(source_safe(value,node)for value,node in sources.values())


def observe_set(emitter,kind,node):
    from .native_class_mappings import mapping_kind
    from .native_classes import shape
    if mapping_kind(kind)and kind.record.category=='set'and not non_nan_record(emitter.model,kind.record):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node,'this set traversal can expose NaN object-pointer hashing; its numeric producers do not prove NaN absent, and a source-owned pointer-hash traversal adapter is not implemented',types=(('set key',shape(kind.record.key)),),proof='proved non-NaN numeric set traversal')


def runtime(model):
    from .native_classes import shape
    parts=[]
    needed=any(record.emitted and floating(shape(record.key))for record in model.mappings.records)
    if needed:
        from .native_cpython_hash import FLOAT_HASH
        integer=('let magnitude=(value.unsigned_abs()%2305843009213693951u128)as i64;let result=if *value<0{-magnitude}else{magnitude};if result==-1{-2}else{result}'if model.integer=='i128'else
                 'let magnitude=(value.unsigned_abs()as u128%2305843009213693951u128)as i64;let result=if *value<0{-magnitude}else{magnitude};if result==-1{-2}else{result}'if model.integer=='i64'else
                 'let(negative,digits)=match &value.0{IntRepr::Small(number)=>{let magnitude=number.unsigned_abs()%2305843009213693951u128;let result=if *number<0{-(magnitude as i64)}else{magnitude as i64};return if result==-1{-2}else{result};},IntRepr::Big{negative,digits}=>(*negative,digits)};let mut value=0u128;for &digit in digits.iter().rev(){value=((value<<32)+digit as u128)%2305843009213693951u128;}let result=if negative{-(value as i64)}else{value as i64};if result==-1{-2}else{result}')
        equal='integer.cmp_f64(floating.value)'if model.integer=='bigint'else'native_integer_float_compare(*integer,floating.value)'
        parts=[FLOAT_HASH,RUNTIME.replace('INTEGER_HASH_BODY',integer).replace('EXACT_REAL_EQUAL',equal)]
    if getattr(model,'native_numeric_query_required',False):
        body=('Int::from_f64(value).ok()'if model.integer=='bigint'else
              'let lower=NativeInt::MIN as f64;if value<lower||value>=-lower{return None;}Some(value as NativeInt)')
        parts.append('fn native_numeric_query_integer(value:f64)->Option<NativeInt>{if !value.is_finite()||value.fract()!=0.0{return None;}'+body+'}')
    return '\n'.join(parts)


RUNTIME=r'''
#[derive(Clone)]
enum NativeNumericKey{Integer(NativeInt),Float(NativeIdentityFloat)}
impl PartialEq for NativeNumericKey{
    fn eq(&self,other:&Self)->bool{
        match(self,other){
            (Self::Integer(left),Self::Integer(right))=>left==right,
            (Self::Float(left),Self::Float(right))=>left.value==right.value||(left.nan_identity!=0&&left.nan_identity==right.nan_identity),
            (Self::Integer(integer),Self::Float(floating))|(Self::Float(floating),Self::Integer(integer))=>matches!(EXACT_REAL_EQUAL,Some(std::cmp::Ordering::Equal)),
        }
    }
}
impl Eq for NativeNumericKey{}
impl std::hash::Hash for NativeNumericKey{fn hash<H:std::hash::Hasher>(&self,state:&mut H){std::hash::Hash::hash(&native_numeric_key_hash(self),state);}}
fn native_numeric_integer_hash(value:&NativeInt)->i64{INTEGER_HASH_BODY}
fn native_numeric_key_hash(value:&NativeNumericKey)->i64{
    match value{
        NativeNumericKey::Integer(value)=>native_numeric_integer_hash(value),
        NativeNumericKey::Float(value)=>{
            if value.value.is_nan(){
                debug_assert_ne!(value.nan_identity,0);
                let hash=(value.nan_identity as u64).wrapping_mul(0x9e3779b97f4a7c15)as i64;
                if hash==-1{-2}else{hash}
            }else{native_cp_hash_float(value.value)}
        }
    }
}
'''
