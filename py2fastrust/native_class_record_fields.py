"""Typed tuple storage for proved private fixed-schema class list fields."""
import ast
from dataclasses import dataclass

from .native_types import TupleType,tuple_code


@dataclass(frozen=True)
class Record:
    field:object
    fields:tuple


class Registry:
    def __init__(self,model):
        self.model=model;self.fields={};self.reasons={}
        for key,info in model.owned_class_lists.fields.items():
            record,reason=self.prove(info)
            if record is None:self.reasons[key]=reason
            else:self.fields[key]=record

    def prove(self,info):
        from .native_classes import shape
        from .native_record_places import _concrete
        from .native_list_positions import index
        model=self.model;literal=info.statement.value
        if not isinstance(literal,ast.List)or not literal.elts:return None,'the fresh field is not a fixed nonempty list literal'
        if getattr(model,'list_positions_unknown_heap',False):return None,'list positional ownership includes an unproved producer'
        value=info.owner.fields[info.name].cell.root()
        origins=getattr(value,'list_origins',None)
        allocations=getattr(model,'list_position_allocations',{})
        if not origins or len(origins)!=1 or not origins<=allocations.keys():return None,'the field has no single canonical literal origin'
        allocation=allocations[next(iter(origins))]
        if allocation.node is not literal or allocation.invalid or allocation.fields is None:return None,'the field has no stable positional schema'
        init=info.owner.methods['__init__']
        fields=tuple(shape(field)for field in allocation.fields)
        initial=tuple(shape(model.records[init.index,id(child)])if(init.index,id(child))in model.records else None for child in literal.elts)
        if fields!=initial:return None,'the slot types change after initialization'
        if not fields or not all(_concrete(field)for field in fields):return None,'a frozen slot ABI is unresolved or requires a union'
        if all(field==fields[0]for field in fields):return None,'the fixed list is homogeneous'
        base=model.value_classes
        for (plan,node_id),field in model.owned_class_lists.sites.items():
            if field is not info:continue
            node=base.nodes[node_id];parent=base.parents.get(node_id)
            if isinstance(node.ctx,ast.Store):continue
            if isinstance(parent,ast.Subscript)and parent.value is node:
                if index(model,parent.slice)is None:return None,'an indexed use needs a runtime-varying slot'
            elif not model.owned_class_lists.builtin_len(base.plans[plan],parent):
                return None,'a field use is not a constant indexed place or builtin len'
        return Record(info,fields),None


def prepare(model):model.class_record_fields=Registry(model)


def selected(model,info):
    registry=getattr(model,'class_record_fields',None)
    return None if registry is None else registry.fields.get((info.owner.index,info.index))


def physical_type(emitter,record):return emitter.rust_type(TupleType(record.fields))


def offset(model,record,node):
    from .native_list_positions import index
    value=index(model,node.slice)
    assert value is not None,'record field index was not proved constant'
    return value%len(record.fields)if -len(record.fields)<=value<len(record.fields)else None


def failure(emitter,node,kind,assignment=False):
    from .native_record_places import _failure
    return _failure(emitter,node,kind,assignment)


def load(emitter,record,owner,node,kind=None):
    from .native_list_positions import project_element
    from .native_owned_class_lists import prefix
    wanted=emitter.kind(node)if kind is None else kind
    field=offset(emitter.model,record,node)
    if field is None:return failure(emitter,node,wanted)
    code=emitter.at(prefix(record.field)+'_get_'+str(field)+'(&'+owner.code+')',node)
    return project_element(emitter,code,record.fields[field],wanted,node)


def store(emitter,record,owner,value,node):
    from .native_list_positions import project_element
    from .native_owned_class_lists import prefix
    field=offset(emitter.model,record,node)
    if field is None:return failure(emitter,node,'none',True).code+';'
    value=project_element(emitter,value.code,value.kind,record.fields[field],node)
    code=prefix(record.field)+'_set_'+str(field)+'(&'+owner.code+','+value.code+')'
    return emitter.at(code,node)+';'


def initialize(emitter,record,node):
    before='';members=[]
    for child,kind in zip(node.value.elts,record.fields):
        setup,value=emitter.capture(emitter.expression(child));before+=setup
        members.append(emitter.coerce(value,kind,child))
    setup,owner=emitter.capture(emitter.expression(record.field.target.value))
    return '{'+before+setup+owner.code+'.borrow_mut().field_'+str(record.field.index)+'=Some('+tuple_code(members)+');}'


def runtime(emitter,record):
    from .native import _string
    from .native_owned_class_lists import prefix
    info=record.field;owner=info.owner
    name=prefix(info);handle=f'&ClassHandle_{owner.index}';field=f'field_{info.index}'
    error=_string(f"AttributeError: '{owner.node.name}' object has no attribute '{owner.fields[info.name].name}'")
    result=[f'fn {name}_ensure(owner:{handle})->Result<(),String>{{if owner.borrow().{field}.is_some(){{Ok(())}}else{{Err({error}.to_owned())}}}}',
            f'fn {name}_len(owner:{handle})->Result<usize,String>{{{name}_ensure(owner)?;Ok({len(record.fields)})}}']
    for index,kind in enumerate(record.fields):
        rust=emitter.rust_type(kind)
        result.append(f'fn {name}_get_{index}(owner:{handle})->Result<{rust},String>{{let result={{let owner=owner.borrow();let values=owner.{field}.as_ref().expect("checked stable field");values.{index}.clone()}};Ok(result)}}')
        result.append(f'fn {name}_set_{index}(owner:{handle},value:{rust})->Result<(),String>{{let previous={{let mut owner=owner.borrow_mut();let values=owner.{field}.as_mut().expect("checked stable field");std::mem::replace(&mut values.{index},value)}};drop(previous);Ok(())}}')
    return '\n'.join(result)
