"""Separate physical tuple places for private fixed-schema Python lists."""
import ast
from dataclasses import dataclass

from .native_types import ListType,TupleType,UnionType,NullableType,EmptyType,tuple_code
from .references import BuiltinIdentity
from .native_physical_list_builtins import static_builtin


@dataclass(frozen=True)
class Record:
    name:object
    kind:ListType
    fields:tuple
    binding:tuple
    definition:object


def _concrete(kind):
    from .native_classes import InstanceType
    if isinstance(kind,(UnionType,NullableType,EmptyType))or kind=='int_bool':return False
    return (kind in {'int','bool','float','str','bytes','none'}
            or isinstance(kind,(InstanceType,ListType,TupleType)))


def prepare(emitter):
    from .native_classes import shape
    from .native_owned_local_lists import observes_frames
    model,plan=emitter.model,emitter.plan
    if model.unit is None or model.is_module_plan(plan):return {}
    if getattr(model,'gc_classes',())or any('__del__'in owner.methods for owner in model.classes.values()if owner.used):return {}
    if not hasattr(model,'local_list_frame_observers'):model.local_list_frame_observers=observes_frames(model)
    if model.local_list_frame_observers:return {}
    unit=model.unit;scope=model.lexical.scope(plan)
    if unit.scopes[scope].kind!='function':return {}
    parents={id(child):node for node in ast.walk(plan.node)for child in ast.iter_child_nodes(node)}
    nodes={unit.node_ordinals[id(node)]:node for node in ast.walk(plan.node)if id(node)in unit.node_ordinals}
    grouped={}
    for binding in unit.bindings:
        if binding.owner==scope and binding.node in nodes:grouped.setdefault(binding.name,[]).append((binding,nodes[binding.node]))
    result={}
    for bindings in grouped.values():
        if any(binding.role=='parameter'for binding,node in bindings):continue
        stores=[node for binding,node in bindings if binding.role=='store']
        if len(stores)!=1:continue
        target=stores[0];definition=parents.get(id(target))
        if (not isinstance(target,ast.Name)or not isinstance(definition,(ast.Assign,ast.AnnAssign))
                or isinstance(definition,ast.Assign)and definition.targets!=[target]
                or not isinstance(definition.value,ast.List)or not definition.value.elts):continue
        name=model.resolved_name(plan,target)
        kinds={shape(value)for value in plan.locals.get(name,())}
        if len(kinds)!=1:continue
        kind=next(iter(kinds))
        if not isinstance(kind,ListType):continue
        shared=model.namespace.local_kind(plan,name)
        if shared is not None and shared!=kind:continue
        value=model.records.get((plan.index,id(definition.value)))
        if value is None or shape(value)!=kind:continue
        root=value.root();origins=getattr(root,'list_origins',None)
        allocations=getattr(model,'list_position_allocations',{})
        if (getattr(model,'list_positions_unknown_heap',False)or not origins or len(origins)!=1
                or not origins<=allocations.keys()):continue
        allocation=allocations[next(iter(origins))]
        if allocation.node is not definition.value or allocation.invalid or allocation.fields is None:continue
        fields=tuple(shape(field)for field in allocation.fields)
        initial=tuple(shape(model.records[plan.index,id(child)])if(plan.index,id(child))in model.records else None for child in definition.value.elts)
        if fields!=initial or not all(_concrete(field)for field in fields):continue
        if not fields or all(field==fields[0]for field in fields):continue
        valid=True
        for binding,node in bindings:
            if (not isinstance(node,ast.Name)or binding.scope!=scope
                    or model.lexical.field_for(node)is not None or model.namespace.owns(plan,node)):
                valid=False;break
            if binding.role=='store':continue
            if binding.role!='load':valid=False;break
            parent=parents.get(id(node))
            if isinstance(parent,ast.Subscript)and parent.value is node and not isinstance(parent.slice,ast.Slice):
                from .native_list_positions import index
                if isinstance(parent.ctx,ast.Del)or index(model,parent.slice)is None:valid=False;break
                continue
            if (isinstance(parent,ast.Call)and parent.args==[node]and not parent.keywords
                    and static_builtin(model,plan,parent.func,'len')):continue
            if (isinstance(parent,ast.Assign)and parent.value is node and len(parent.targets)==1
                    and isinstance(parent.targets[0],(ast.Tuple,ast.List))
                    and not any(isinstance(child,ast.Starred)for child in parent.targets[0].elts)):continue
            valid=False;break
        if valid:result[name]=Record(name,kind,fields,(scope,bindings[0][0].name),definition)
    return result


def selected(emitter,node):
    if not isinstance(node,ast.Name)or not getattr(emitter,'record_places',None):return None
    if id(node)not in emitter.model.unit.node_ordinals:return None
    binding=emitter.model.lexical.binding(node)
    if binding is None or binding.owner!=emitter.model.lexical.scope(emitter.plan):return None
    return emitter.record_places.get(emitter.model.resolved_name(emitter.plan,node))


def physical_type(emitter,record):return emitter.rust_type(TupleType(record.fields))


def target_kind(emitter,reference,node):
    if reference[0]=='record_slot':
        _,record,offset=reference
        if -len(record.fields)<=offset<len(record.fields):return record.fields[offset%len(record.fields)]
        return None
    if reference[0]=='owned_class_index':
        from .native_class_record_fields import selected,offset
        record=selected(emitter.model,reference[1])
        if record is not None:
            field=offset(emitter.model,record,node)
            if field is not None:return record.fields[field]
    return None


def checked(emitter,record,node,mutable=False):
    from .native import _string
    slot=emitter.slot(record.name,record.kind)
    message="UnboundLocalError: cannot access local variable '"+emitter.model.display_name(record.name)+"' where it is not associated with a value"
    return emitter.at(f'{slot}.as_{"mut"if mutable else"ref"}().ok_or_else(||{_string(message)}.to_owned())',node)


def reference(emitter,node):
    if not isinstance(node,ast.Subscript):return None
    record=selected(emitter,node.value)
    if record is None:return None
    from .native_list_positions import index
    offset=index(emitter.model,node.slice)
    # The accepted literal index is total and effect-free. Its selected-width
    # normalization happened in index(), before physical field selection.
    return checked(emitter,record,node.value)+';',('record_slot',record,offset)


def _failure(emitter,node,kind,assignment=False):
    from .native_class_builtins import _error
    message='IndexError: list assignment index out of range'if assignment else'IndexError: list index out of range'
    from .native import _string
    return _error(emitter,node,kind,_string(message)+'.to_owned()')


def load(emitter,place,node,kind=None):
    from .native_classes import Expression
    from .native_list_positions import project_element
    _,record,offset=place
    wanted=emitter.kind(node)if kind is None else kind
    if not -len(record.fields)<=offset<len(record.fields):return _failure(emitter,node,wanted)
    field=offset%len(record.fields)
    code='('+checked(emitter,record,node)+').'+str(field)+'.clone()'
    return project_element(emitter,code,record.fields[field],wanted,node)


def store(emitter,place,value,node):
    from .native_list_positions import project_element
    _,record,offset=place
    if not -len(record.fields)<=offset<len(record.fields):return _failure(emitter,node,'none',True).code+';'
    field=offset%len(record.fields)
    converted=project_element(emitter,value.code,value.kind,record.fields[field],node)
    before,captured=emitter.capture(converted)
    return before+'('+checked(emitter,record,node,True)+').'+str(field)+'='+captured.code+';'


def read(emitter,node):
    from .native_classes import Expression
    indexed=reference(emitter,node)
    if indexed is not None:
        before,place=indexed
        return Expression('{'+before+load(emitter,place,node).code+'}',emitter.kind(node))
    if (isinstance(node,ast.Call)and len(node.args)==1 and not node.keywords
            and static_builtin(emitter.model,emitter.plan,node.func,'len')):
        record=selected(emitter,node.args[0])
        if record is not None:return Expression('{'+checked(emitter,record,node.args[0])+';class_from_usize('+str(len(record.fields))+')}',emitter.kind(node))
    return None


def statement(emitter,node):
    from .native_classes import Expression
    from .native import _string
    if isinstance(node,ast.Assign)and len(node.targets)==1:target=node.targets[0]
    elif isinstance(node,ast.AnnAssign)and node.value is not None:target=node.target
    else:return None
    record=selected(emitter,target)
    if record is not None:
        before='';members=[]
        for child,kind in zip(node.value.elts,record.fields):
            setup,value=emitter.capture(emitter.expression(child));before+=setup
            members.append(emitter.coerce(value,kind,child))
        return before+emitter.slot(record.name,record.kind)+'=Some('+tuple_code(members)+');'
    if not isinstance(target,(ast.Tuple,ast.List)):return None
    record=selected(emitter,node.value)
    if record is None:return None
    count=len(target.elts);actual=len(record.fields)
    before=checked(emitter,record,node.value)+';'
    if count!=actual:
        message=(f'ValueError: not enough values to unpack (expected {count}, got {actual})'if actual<count
                 else f'ValueError: too many values to unpack (expected {count}, got {actual})')
        return before+emitter.at('Err::<(),String>('+_string(message)+'.to_owned())',target)+';'
    snapshot=emitter.fresh();owner=emitter.fresh()
    values=tuple_code(f'{owner}.{i}.clone()'for i in range(actual))
    before+=f'let {snapshot}={{let {owner}='+checked(emitter,record,node.value)+';'+values+'};'
    return before+''.join(emitter.assign(child,Expression(f'{snapshot}.{i}',kind))for i,(child,kind)in enumerate(zip(target.elts,record.fields)))
