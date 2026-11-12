"""Unpack finite builtin-sequence alternatives without materializing iterators."""
import ast
from dataclasses import dataclass


@dataclass
class FiniteUnpack:
    variants:dict
    _finite_tuple_unpack=True


@dataclass
class SequenceMembers:
    member:object
    mutable:bool


def analyze(model,plan,target,value,environment,*,bind_target=None):
    from .native_classes import Cell,shape
    from .native_types import EMPTY
    from .native_unions import union_kind
    from .native_class_iterators import default_noniterable
    if any(isinstance(child,ast.Starred)for child in target.elts):return None
    source=value.root()
    if source.tag!='union'or not union_kind(shape(source)):return None
    variants={};tuples=False
    for part in source.args:
        part=part.root();kind=shape(part)
        if part.tag=='tuple'or getattr(part.tag,'_native_tuple_record',False):
            variants[kind]=part.args;tuples=True
        elif part.tag in {'list','tuple_sequence'}:
            variants[kind]=SequenceMembers(part.args[0],part.tag=='list');tuples=True
        elif kind is not None and default_noniterable(model,kind):variants[kind]=None
        else:return None
    if not tuples:return None
    fields=[model.cell(plan,target,identity=('finite_unpack_position',i))for i in range(len(target.elts))]
    successful=False
    for members in variants.values():
        if isinstance(members,SequenceMembers):
            successful=True
            for slot in fields:model.contribute(slot,members.member,target)
            continue
        if members is None or len(members)!=len(fields):continue
        successful=True
        for slot,member in zip(fields,members):model.contribute(slot,member,target)
    if not successful:
        for slot in fields:model.contribute(slot,Cell(EMPTY),target)
    for child,field in zip(target.elts,fields):
        if bind_target is None:model.target(plan,child,field,environment)
        else:bind_target(child,field)
    return FiniteUnpack(variants)


def emit(emitter,target,value,record,*,assign_target=None):
    from .native import _string
    from .native_classes import Expression,shape
    from .native_class_builtins import _type_name
    from .native_unions import project
    setup,source=emitter.capture(value)
    assign=assign_target or emitter.assign
    expected=len(target.elts)
    def copy_field(code,kind):
        scalar=(kind in {'bool','float','none'}
                or emitter.model.integer in {'i64','i128'}and kind in {'int','int_bool'})
        return code if scalar else code+'.clone()'
    def branch(kind,payload):
        members=record.variants[kind]
        if members is None:
            name=_type_name(emitter,Expression('('+payload+').clone()',kind),target)
            error='format!("TypeError: cannot unpack non-iterable {} object",'+name+')'
            return '{'+emitter.at('Err::<(),String>('+error+')',target)+';}'
        if isinstance(members,SequenceMembers):
            # Capture every value at this unpacking level before the first
            # target is evaluated. A target may mutate the source list; its
            # temporary Vec lease must already have ended at that point.
            guard=emitter.fresh()
            captured=[emitter.fresh()for _ in target.elts]
            source=('('+payload+').borrow()'if members.mutable
                    else'('+payload+').as_slice()')
            checked=emitter.at('class_unpack_length('+guard+'.len(),'+str(expected)+')',target)+';'
            values=','.join(copy_field(guard+'['+str(i)+']',shape(members.member))
                            for i in range(expected))
            tuple_pattern='('+','.join(captured)+(','if captured else'')+')'
            tuple_value='('+values+(','if captured else'')+')'
            code=('let '+tuple_pattern+'={let '+guard+'='+source+';'+checked
                  +tuple_value+'};')
            code+=''.join(assign(child,Expression(field,shape(members.member)))
                          for child,field in zip(target.elts,captured))
            return '{'+code+'}'
        count=len(members)
        if count!=expected:
            message=(f'ValueError: not enough values to unpack (expected {expected}, got {count})'if count<expected else f'ValueError: too many values to unpack (expected {expected}, got {count})')
            return '{'+emitter.at('Err::<(),String>('+_string(message)+'.to_owned())',target)+';}'
        code='';captured=[]
        for index,member in enumerate(members):
            kind=shape(member)
            before,field=emitter.capture(Expression(copy_field('('+payload+').'+str(index),kind),kind))
            code+=before;captured.append(field)
        code+=''.join(assign(child,field)for child,field in zip(target.elts,captured))
        return '{'+code+'}'
    return setup+project(source.kind,source.code,branch)+';'
