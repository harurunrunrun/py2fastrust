"""Physical Vec places for nonescaping fresh function-local list bindings.

ListType describes Python values, not ownership. Layout facts are keyed by an
official lexical binding, and whole-list expressions never expose these places.
Element handles retain their existing shallow Clone semantics.
"""
import ast
from dataclasses import dataclass

from .native_types import ListType
from .references import BuiltinIdentity


@dataclass(frozen=True)
class Local:
    name: object
    kind: ListType
    binding: tuple
    allocations: tuple


def static_builtin(emitter,node,name):
    from .native_physical_list_builtins import static_builtin as proved
    return proved(emitter.model,emitter.plan,node,name)


def enumerate_source(emitter,node):
    """An immediate builtin enumerate with an already native integer start."""
    if (not isinstance(node,ast.Call)or not isinstance(node.func,ast.Name)
            or node.func.id!='enumerate' or not 1<=len(node.args)<=2
            or node.keywords
            or emitter.model.builtin_identity(emitter.plan,node.func,{})!=BuiltinIdentity('enumerate')):return None
    if len(node.args)==2 and emitter.kind(node.args[1])not in {'int','bool','int_bool'}:return None
    return node.args[0]


def loop_source(emitter,node,parents):
    """The original immediate iterable consumed by Emitter.for_statement."""
    parent=parents.get(id(node))
    if isinstance(parent,ast.For)and parent.iter is node:return parent
    if enumerate_source(emitter,parent)is not node:return None
    loop=parents.get(id(parent))
    return loop if isinstance(loop,ast.For)and loop.iter is parent else None


def fresh(emitter,node):
    if isinstance(node,(ast.List,ast.ListComp)):return True
    if (isinstance(node,ast.Call)and isinstance(node.func,ast.Name)
            and len(node.args)<=1 and not node.keywords
            and emitter.model.builtin_identity(emitter.plan,node.func,{})==BuiltinIdentity('list')):return True
    return (isinstance(node,ast.BinOp)and isinstance(node.op,ast.Mult)
            and isinstance(node.left,ast.List))


def observes_frames(model):
    from .native_classes import shape
    from .native_module_calls import BuiltinRef
    observers={'locals','eval','exec','compile','vars'}
    def visit(kind,seen=frozenset()):
        if id(kind)in seen:return False
        seen=seen|{id(kind)}
        for identity in (*getattr(kind,'builtins',()),*getattr(kind,'members',())):
            if isinstance(identity,BuiltinIdentity)and identity.name in observers:return True
            if isinstance(identity,BuiltinRef)and(
                    identity.module=='builtins'and identity.name in observers
                    or identity.module=='sys'and identity.name in {'_getframe','settrace','setprofile'}):return True
        return any(visit(child,seen)for child in getattr(kind,'_native_owned_kinds',()))
    if any(visit(shape(cell))for cell in model.records.values()):return True
    for identity in model.callable_cells.member_used:
        if isinstance(identity,BuiltinRef)and(
                identity.module=='builtins'and identity.name in observers
                or identity.module=='sys'and identity.name in {'_getframe','settrace','setprofile'}):return True
    for plan in model.plans:
        if not plan.reachable:continue
        for node in ast.walk(plan.node):
            if(plan.index,id(node))not in model.records:continue
            if isinstance(node,ast.Call)and isinstance(node.func,ast.Name):
                identity=model.builtin_identity(plan,node.func,{})
                if isinstance(identity,BuiltinIdentity)and identity.name in observers:return True
    return False


def prepare(emitter):
    from .native_classes import shape
    model,plan=emitter.model,emitter.plan
    if model.unit is None or model.is_module_plan(plan):return {}
    if not hasattr(model,'local_list_frame_observers'):
        model.local_list_frame_observers=observes_frames(model)
    if model.local_list_frame_observers:return {}
    unit=model.unit
    scope=model.lexical.scope(plan)
    parents={id(child):node for node in ast.walk(plan.node)for child in ast.iter_child_nodes(node)}
    nodes={}
    for node in ast.walk(plan.node):
        ordinal=unit.node_ordinals.get(id(node))
        if ordinal is None:
            if isinstance(node,ast.Name)and(plan.index,id(node))in model.records:return {}
        else:nodes[ordinal]=node
    grouped={}
    for binding in unit.bindings:
        if binding.owner==scope and binding.node in nodes:
            grouped.setdefault(binding.name,[]).append((binding,nodes[binding.node]))
    result={}
    for bindings in grouped.values():
        if any(binding.role=='parameter'for binding,node in bindings):continue
        name=model.resolved_name(plan,bindings[0][1])
        values=plan.locals.get(name,())
        kinds={shape(value)for value in values}
        if len(kinds)!=1:continue
        kind=next(iter(kinds))
        if not isinstance(kind,ListType):continue
        stored=model.namespace.local_kind(plan,name)
        if stored is not None and stored!=kind:continue
        valid=True
        writes=0
        iterates=False
        allocations=[]
        for binding,node in bindings:
            parent=parents.get(id(node))
            if (not isinstance(node,ast.Name)or model.lexical.field_for(node)is not None
                    or model.namespace.owns(plan,node)):
                valid=False;break
            if binding.role=='store':
                if (not isinstance(parent,(ast.Assign,ast.AnnAssign))
                        or isinstance(parent,ast.Assign)and(parent.targets!=[node])
                        or isinstance(parent,ast.AnnAssign)and parent.target is not node
                        or parent.value is None or not fresh(emitter,parent.value)):
                    valid=False;break
                value=model.records.get((plan.index,id(parent.value)))
                if value is None or shape(value)!=kind:
                    valid=False;break
                if isinstance(parent.value,ast.BinOp):
                    count=model.records.get((plan.index,id(parent.value.right)))
                    if count is None or shape(count)not in {'int','bool','int_bool'}:
                        valid=False;break
                if isinstance(parent.value,ast.Call)and parent.value.args:
                    source=model.records.get((plan.index,id(parent.value.args[0])))
                    from .native_classes import domain
                    if (source is None or domain(shape(source))in {'union','none','int','bool','int_bool','float','function'}
                            or getattr(shape(source),'_native_class_generator',False)):
                        valid=False;break
                writes+=1
                allocation_site=unit.node_ordinals.get(id(parent.value))
                if allocation_site is None:valid=False;break
                allocations.append(allocation_site)
            elif binding.role=='load':
                direct=isinstance(parent,ast.Subscript)and parent.value is node and not isinstance(parent.slice,ast.Slice)
                length=(isinstance(parent,ast.Call)and parent.args==[node]and not parent.keywords
                        and static_builtin(emitter,parent.func,'len'))
                method=parents.get(id(parent))if isinstance(parent,ast.Attribute)else None
                mutation=(isinstance(parent,ast.Attribute)and parent.value is node
                          and isinstance(method,ast.Call)and method.func is parent and not method.keywords
                          and(plan.index,id(method))in model.sequence_calls
                          and(parent.attr=='append'and len(method.args)==1
                              or parent.attr=='pop'and len(method.args)<=1))
                iteration=loop_source(emitter,node,parents)
                if iteration is not None:iterates=True
                if not direct and not length and not mutation and iteration is None:valid=False;break
            else:
                valid=False;break
        # A Python iterator retains the original allocation after a rebind.
        # Direct places need no retained handle only when that binding cannot
        # be replaced during any iteration (captures/deletions already fail).
        if valid and writes and(not iterates or writes==1):
            result[name]=Local(name,kind,(scope,bindings[0][0].name),tuple(allocations))
    return result


def selected(emitter,node):
    if not emitter.owned_local_lists or not isinstance(node,ast.Name):return None
    if id(node)not in emitter.model.unit.node_ordinals:return None
    binding=emitter.model.lexical.binding(node)
    if binding is None or binding.owner!=emitter.model.lexical.scope(emitter.plan):return None
    return emitter.owned_local_lists.get(emitter.model.resolved_name(emitter.plan,node))


def checked(emitter,local,node,mutable=False):
    from .native import _string
    slot=emitter.slot(local.name,local.kind)
    message="UnboundLocalError: cannot access local variable '"+emitter.model.display_name(local.name)+"' where it is not associated with a value"
    return emitter.at(f'{slot}.as_{"mut"if mutable else"ref"}().ok_or_else(||{_string(message)}.to_owned())',node)


def iteration(emitter,node):
    from .native_classes import Expression
    local=selected(emitter,node)
    if local is None:return None
    # Evaluate source existence before enumerate's start argument, but retain
    # no Rust loan across a Python body or callback. Each pull checks the
    # current length and clones only one element, preserving mutation rules.
    owner=checked(emitter,local,node)
    return owner+';',Expression('('+owner+')',local.kind)


def allocation(emitter,node,kind):
    from .native_classes import Expression
    if isinstance(node,ast.List):
        values=[emitter.coerce(emitter.expression(value),kind.element,value)for value in node.elts]
        return Expression('vec!['+','.join(values)+']'if values else f'Vec::<{emitter.rust_type(kind.element)}>::new()',kind)
    if isinstance(node,ast.ListComp):
        from .native_class_comprehensions import emit
        return emit(emitter,node,owned=True)
    if isinstance(node,ast.Call):
        from .native_classes import domain
        if node.args and domain(emitter.kind(node.args[0]))=='map_int':
            values=emitter.parse_words(node.args[0],consumer=node)
            if kind.element!='int':
                item=emitter.fresh()
                converted=emitter.coerce(Expression(item,'int'),kind.element,node)
                values=f'({values}).into_iter().map(|{item}|{converted}).collect::<Vec<_>>()'
            return Expression(values,kind)
        from .native_class_builtins import emit
        before=[];arguments=[]
        for argument in node.args:
            setup,value=emitter.capture(emitter.expression(argument))
            before.append(setup);arguments.append(value)
        result=emit(emitter,node,BuiltinIdentity('list'),arguments,{},kind,kind,owned_list=True)
        value=emitter.fresh()
        return Expression('{'+''.join(before)+f'let {value}={result.code};{value}'+'}',kind)
    before,values=emitter.capture(allocation(emitter,node.left,kind))
    after,count=emitter.capture(emitter.expression(node.right))
    emitter.model.owned_list_repetition=True
    value=emitter.at(f'class_owned_list_repeat(&{values.code},&({emitter.number(count)}))',node)
    return Expression('{'+before+after+value+'}',kind)


def statement(emitter,node):
    if isinstance(node,ast.Assign)and len(node.targets)==1:target=node.targets[0]
    elif isinstance(node,ast.AnnAssign)and node.value is not None:target=node.target
    else:return None
    local=selected(emitter,target)
    if local is None:return None
    value=allocation(emitter,node.value,local.kind)
    return f'{emitter.slot(local.name,local.kind)}=Some({value.code});'


def reference(emitter,node):
    if not isinstance(node,ast.Subscript):return None
    local=selected(emitter,node.value)
    if local is None:return None
    before=checked(emitter,local,node.value)+';'
    after,index=emitter.capture(emitter.expression(node.slice))
    return before+after,('owned_local_list',local,index,emitter.kind(node))


def load(emitter,reference,node,kind=None):
    from .native_list_positions import project_element
    from .native_list_end_indices import method,result
    _,local,index,element=reference
    owner=emitter.fresh();offset=emitter.fresh()
    checked_owner=checked(emitter,local,node.value if isinstance(node,ast.Subscript)else node)
    operation=method(node.slice)if isinstance(node,ast.Subscript)else None
    if operation is None:
        offset_code=emitter.at(f'class_index(&({emitter.number(index)}),{owner}.len())',node)
        value=f'let {offset}={offset_code};{owner}[{offset}].clone()'
    else:value=emitter.at(result(owner,operation),node)
    code='{'+f'let {owner}={checked_owner};'+value+'}'
    return project_element(emitter,code,local.kind.element,kind or element,node)


def store(emitter,reference,value,node):
    _,local,index,element=reference
    # Snapshot/coerce the RHS before taking a mutable vector reference. In
    # particular, a[i] = a[j] must never clone the whole list or overlap loans.
    before,captured=emitter.capture(value)
    owner=emitter.fresh();offset=emitter.fresh()
    index_code=emitter.at(f'class_index(&({emitter.number(index)}),{owner}.len()).map_err(|_|"IndexError: list assignment index out of range".to_owned())',node)
    return ('{'+before+f'let {owner}={checked(emitter,local,node,True)};let {offset}={index_code};'
            +f'{owner}[{offset}]={emitter.coerce(captured,local.kind.element,node)};'+'}')


def read(emitter,node):
    from .native_classes import Expression
    indexed=reference(emitter,node)
    if indexed is not None:
        before,place=indexed
        return Expression('{'+before+load(emitter,place,node).code+'}',emitter.kind(node))
    if (isinstance(node,ast.Call)and len(node.args)==1 and not node.keywords
            and static_builtin(emitter,node.func,'len')):
        local=selected(emitter,node.args[0])
        if local is not None:
            return Expression('class_from_usize(('+checked(emitter,local,node.args[0])+').len())','int')
    if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute):
        local=selected(emitter,node.func.value)
        if local is not None:
            from .native_sequence_storage import SequenceStorage
            storage=SequenceStorage((checked(emitter,local,node.func.value)+';',),
                checked(emitter,local,node),checked(emitter,local,node,True),local.kind,shared=True)
            return emitter.sequence_call(node,emitter.model.sequence_calls[(emitter.plan.index,id(node))],storage=storage)
    return None


RUNTIME='''
fn class_owned_list_repeat<T:Clone>(values:&[T],count:&NativeInt)->Result<Vec<T>,String>{
    let count=class_repetition_count(count)?;
    if count==0||values.is_empty(){return Ok(Vec::new());}
    let length=values.len().checked_mul(count).ok_or_else(||"MemoryError: list is too large".to_owned())?;
    let mut result=Vec::new();result.try_reserve(length).map_err(|_|"MemoryError: cannot allocate list".to_owned())?;
    for _ in 0..count{result.extend(values.iter().cloned());}
    Ok(result)
}
'''
