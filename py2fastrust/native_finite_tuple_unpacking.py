"""Retain field positions when unpacking finite fixed-tuple alternatives."""
import ast
from dataclasses import dataclass


@dataclass
class FiniteUnpack:
    variants:dict
    _finite_tuple_unpack=True


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
        elif kind is not None and default_noniterable(model,kind):variants[kind]=None
        else:return None
    if not tuples:return None
    fields=[model.cell(plan,target,identity=('finite_unpack_position',i))for i in range(len(target.elts))]
    successful=False
    for members in variants.values():
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
    def branch(kind,payload):
        members=record.variants[kind]
        if members is None:
            name=_type_name(emitter,Expression('('+payload+').clone()',kind),target)
            error='format!("TypeError: cannot unpack non-iterable {} object",'+name+')'
            return '{'+emitter.at('Err::<(),String>('+error+')',target)+';}'
        count=len(members)
        if count!=expected:
            message=(f'ValueError: not enough values to unpack (expected {expected}, got {count})'if count<expected else f'ValueError: too many values to unpack (expected {expected}, got {count})')
            return '{'+emitter.at('Err::<(),String>('+_string(message)+'.to_owned())',target)+';}'
        code='';captured=[]
        for index,member in enumerate(members):
            before,field=emitter.capture(Expression('('+payload+').'+str(index)+'.clone()',shape(member)))
            code+=before;captured.append(field)
        code+=''.join(assign(child,field)for child,field in zip(target.elts,captured))
        return '{'+code+'}'
    return setup+project(source.kind,source.code,branch)+';'
