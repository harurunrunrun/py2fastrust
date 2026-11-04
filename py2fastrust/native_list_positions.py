"""Positional type constraints for fixed-shape builtin list allocations.

The semantic ListType and physical uniform element carrier do not change.
Private slot cells are lower bounds over every possibly aliased allocation;
unknown length and reorder operations widen them back to the element ABI.
"""
import ast
from dataclasses import dataclass


@dataclass
class AllocationPositions:
    member: object
    fields: tuple | None
    node: object
    invalid: bool = False


def registry(model):
    if not hasattr(model, 'list_position_allocations'):
        model.list_position_allocations = {}
    return model.list_position_allocations


def allocation_origins(value):
    """Known outer allocation sites, independently of positional precision."""
    root=value.root()
    return root.list_origins if root.tag=='list'else None


def join_origins(left, right, seen=None):
    """Equal value ABIs can still carry distinct allocation alternatives."""
    from .native_classes import shape
    from .native_types import ListType
    left,right=left.root(),right.root()
    if left is right:return
    seen=set()if seen is None else seen
    key=id(left),id(right)
    if key in seen:return
    seen.add(key)
    if isinstance(shape(left),ListType)and isinstance(shape(right),ListType):
        origins=(None if left.list_origins is None or right.list_origins is None
                 else left.list_origins|right.list_origins)
        left.list_origins=right.list_origins=origins
    if left.tag==right.tag=='union':
        for a in left.args:
            for b in right.args:
                if shape(a)==shape(b):join_origins(a,b,seen)
    elif left.tag==right.tag and len(left.args)==len(right.args):
        for a,b in zip(left.args,right.args):
            if hasattr(a,'root')and hasattr(b,'root'):
                join_origins(a,b,seen)


def fresh_at(model, plan, node, value):
    """A fresh allocation at this expression, never singleton-site identity."""
    origins=allocation_origins(value)
    records=registry(model)
    return bool(origins)and all(origin in records and records[origin].node is node
        and origin.site[0][:2]==('class',plan.index)for origin in origins)


def register(model, allocation, member, node):
    records = registry(model)
    if allocation not in records:
        from .native_classes import Cell
        fields = tuple(Cell() for _ in node.elts) if isinstance(node, ast.List) else None
        records[allocation] = AllocationPositions(member, fields, node,
            getattr(model,'list_positions_unknown_heap',False))


def actual_lists(model):
    pending=list(model.records.values())+list(model.node_cells.values())
    seen=set();result=[]
    while pending:
        value=pending.pop().root()
        if id(value)in seen:continue
        seen.add(id(value))
        from .native_classes import shape
        from .native_types import ListType
        if value.tag=='list'or isinstance(shape(value),ListType):result.append(value)
        pending.extend(child for child in value.args if hasattr(child,'root'))
    return result


def groups(model):
    records=registry(model)
    parents={record.member.root():record.member.root()for record in records.values()}
    def find(value):
        parents.setdefault(value,value)
        if parents[value]is not value:parents[value]=find(parents[value])
        return parents[value]
    for owner in actual_lists(model):
        if owner.tag!='list':continue
        root=find(owner.args[0].root())
        for origin in owner.list_origins or ():
            if origin in records:
                other=find(records[origin].member.root())
                parents[other]=root
    clusters={}
    for record in records.values():
        clusters.setdefault(find(record.member.root()),[]).append(record)
    return {member:clusters.get(find(member),[])for member in parents}


def refresh(model):
    """A lost shape proof must widen users that were inferred previously."""
    records=registry(model)
    if any(value.tag!='list'or value.list_origins is None or not value.list_origins
            or not value.list_origins<=records.keys()for value in actual_lists(model)):
        # An unregistered value producer is not a closed origin proof. Keep
        # that loss persistent, including allocations reached in later passes.
        model.list_positions_unknown_heap=True
    if getattr(model,'list_positions_unknown_heap',False):
        for record in records.values():record.invalid=True
    done=set()
    for member, records in groups(model).items():
        if id(records)in done:continue
        done.add(id(records))
        lengths = {len(r.fields) for r in records if r.fields is not None}
        lost = (any(r.invalid or r.fields is None for r in records)
                or len(lengths) != 1)
        if lost:
            for record in records:
                for field in record.fields or ():
                    model.contribute(field, member, record.node)
        elif records:
            # Share type bounds in both directions. An older read of any
            # allocation must widen even if its source point is not revisited.
            first=records[0]
            for record in records[1:]:
                for field,value in zip(first.fields,record.fields):
                    model.contribute(field,value,record.node)
            for record in records[1:]:
                for field,value in zip(record.fields,first.fields):
                    model.contribute(field,value,record.node)


def literal(model, owner, values, node):
    member = owner.root().args[0].root()
    for record in registry(model).values():
        if record.node is node and record.fields is not None:
            for field, value in zip(record.fields, values):
                model.contribute(field, value, node)


def fields(model, owner):
    owner = owner.root()
    if owner.tag != 'list':
        return None
    refresh(model)
    if owner.list_origins is None or not owner.list_origins or not owner.list_origins<=registry(model).keys():
        invalidate(model,owner)
        return None
    records = groups(model).get(owner.args[0].root(), ())
    if not records or any(r.invalid or r.fields is None for r in records):
        return None
    if len({len(r.fields) for r in records}) != 1:
        return None
    result = records[0].fields
    for record in records[1:]:
        for field, value in zip(result, record.fields):
            model.contribute(field, value, record.node)
    return result


def index(model, node):
    # The source literal is a Python int, but a selected fixed-width runtime
    # normalizes it before subscription. Stores must update that actual slot.
    from .native_union_sequences import constant_index
    if isinstance(node,ast.UnaryOp)and isinstance(node.op,ast.USub):
        operand=constant_index(model,node.operand)
        if operand is not None:
            from .literal_semantics import integer_policy
            bits=0 if model.integer=='bigint'else 64 if model.integer=='i64'else 128
            return integer_policy(bits).normalize(-operand)
    return constant_index(model, node)


def read(model, owner, index_node):
    members = fields(model, owner)
    offset = index(model, index_node)
    if members is not None and offset is not None and -len(members) <= offset < len(members):
        from .native_classes import shape
        if supports_projection(shape(owner.root().args[0]),shape(members[offset])):
            return members[offset]
    return None


def store(model, owner, index_node, value, node):
    owner = owner.root()
    if owner.tag != 'list':
        return
    offset = index(model, index_node)
    for record in groups(model).get(owner.args[0].root(), ()):
        if record.fields is None:
            continue
        if offset is None:
            destinations = record.fields
        elif -len(record.fields) <= offset < len(record.fields):
            destinations = (record.fields[offset],)
        else:
            destinations = ()
        for field in destinations:
            model.contribute(field, value, node)


def invalidate(model, owner):
    owner = owner.root()
    if owner.tag != 'list':
        return
    for record in groups(model).get(owner.args[0].root(), ()):
        record.invalid = True
    refresh(model)


def unknown_heap(model):
    model.list_positions_unknown_heap = True
    for record in registry(model).values():
        record.invalid = True
    refresh(model)


def closed(kind):
    """Builtin payload operations cannot reenter source code."""
    from .native_types import ListType, TupleType, TupleSequenceType, UnionType, NullableType
    if isinstance(kind,(ListType,TupleSequenceType)):
        return closed(kind.element)
    if isinstance(kind,TupleType):
        return all(closed(x)for x in kind.fields)
    if isinstance(kind,UnionType):
        return all(closed(x)for x in kind.alternatives)
    if isinstance(kind,NullableType):
        return closed(kind.value)
    return kind in {'int','bool','int_bool','float','str','bytes','none','range'}


def after_call(model, plan, node):
    """Unknown whole-value uses cannot preserve a private record contract."""
    from .native_classes import shape
    from .references import BuiltinIdentity
    modeled = bool(model.call_edges_by_site.get((plan.index,id(node))))
    readonly_length = (isinstance(node.func,ast.Name)
        and model.builtin_identity(plan,node.func,{})==BuiltinIdentity('len'))
    if isinstance(node.func,ast.Name):
        identity=model.builtin_identity(plan,node.func,{})
        if isinstance(identity,BuiltinIdentity)and identity.name in {'locals','eval','exec','compile','vars'}:
            unknown_heap(model)
    callee=model.records.get((plan.index,id(node.func)))
    if callee is not None:
        from .native_module_calls import BuiltinRef
        kind=shape(callee)
        identities=(*getattr(kind,'builtins',()),*getattr(kind,'members',()))
        if any(isinstance(identity,BuiltinIdentity)and identity.name in {'locals','eval','exec','compile','vars'}
                or isinstance(identity,BuiltinRef)and(identity.module=='builtins'and identity.name in {'locals','eval','exec','compile','vars'}
                    or identity.module=='sys'and identity.name in {'_getframe','settrace','setprofile'})
                for identity in identities):
            unknown_heap(model)
    if isinstance(node.func, ast.Attribute):
        receiver = model.records.get((plan.index, id(node.func.value)))
        if receiver is not None:
            tag=receiver.root().tag
            if tag=='list':
                invalidate(model, receiver)
            if tag in {'list','tuple','tuple_sequence'}and not modeled and not closed(shape(receiver)):
                unknown_heap(model)
    seen = set()
    def escape(value):
        value = value.root()
        if id(value) in seen:
            return
        seen.add(id(value))
        if value.tag == 'list':
            invalidate(model, value)
        for child in value.args:
            if hasattr(child, 'root'):
                escape(child)
    for argument in (*node.args, *(x.value for x in node.keywords)):
        value = model.records.get((plan.index, id(argument)))
        if value is not None:
            if not modeled and not closed(shape(value)):
                unknown_heap(model)
            if not readonly_length:
                escape(value)


def snapshot(model):
    from .native_classes import shape
    origins=tuple(value.list_origins for value in actual_lists(model))
    return (getattr(model,'list_positions_unknown_heap',False),origins,tuple((allocation, record.invalid,
                  None if record.fields is None else tuple(shape(x) for x in record.fields))
                 for allocation, record in registry(model).items()))


@dataclass
class PositionalUnpack:
    fields: tuple
    _positional_list_unpack = True


def analyze_unpack(model, plan, target, value, environment, bind_target=None):
    if any(isinstance(child, ast.Starred) for child in target.elts):
        return None
    members = fields(model, value)
    if members is None or len(members) != len(target.elts):
        return None
    from .native_classes import shape
    raw=shape(value.root().args[0])
    if not all(supports_projection(raw,shape(member))for member in members):return None
    for child, member in zip(target.elts, members):
        if bind_target is None:
            model.target(plan, child, member, environment)
        else:
            bind_target(child, member)
    return PositionalUnpack(members)


def _alternatives(kind):
    from .native_types import alternatives
    return ('int','bool')if kind=='int_bool'else alternatives(kind)


def intersects(raw, wanted):
    """Only prove disjointness for structurally closed value alternatives."""
    from .native_classes import domain
    from .native_types import TupleType
    from .native_unions import union_kind
    if raw==wanted:return True
    if raw=='int_bool'or wanted=='int_bool'or union_kind(raw)or union_kind(wanted):
        return any(intersects(a,b)for a in _alternatives(raw)for b in _alternatives(wanted))
    if isinstance(raw,TupleType)and isinstance(wanted,TupleType):
        return len(raw.fields)==len(wanted.fields)and all(intersects(a,b)for a,b in zip(raw.fields,wanted.fields))
    if getattr(raw,'_native_function_reference',False)and getattr(wanted,'_native_function_reference',False):
        return bool(set(raw.targets)&set(wanted.targets))
    return domain(raw)==domain(wanted)


def supports_projection(raw, wanted):
    from .native_types import TupleType,tuple_nominal_compatible
    from .native_unions import union_kind
    if raw==wanted:return True
    if wanted=='int_bool'and raw in {'int','bool'}:return True
    if raw=='int_bool'or union_kind(raw):
        choices=[kind for kind in _alternatives(raw)if intersects(kind,wanted)]
        return bool(choices)and all(supports_projection(kind,wanted)for kind in choices)
    if union_kind(wanted):
        choices=[kind for kind in _alternatives(wanted)if intersects(raw,kind)]
        return len(choices)==1 and supports_projection(raw,choices[0])
    if isinstance(raw,TupleType)and isinstance(wanted,TupleType):
        return (len(raw.fields)==len(wanted.fields)and tuple_nominal_compatible(raw,wanted)
            and all(supports_projection(a,b)for a,b in zip(raw.fields,wanted.fields)))
    return False


def project_element(emitter, code, raw_kind, wanted, node):
    """Project a cloned carrier; retain feasible unsupported conversions."""
    from .native_classes import Expression, ClassUnsupported
    from .native_types import TupleType,tuple_code
    from .native_unions import project,union_kind,construct
    def convert(raw,target,payload):
        if raw==target:return payload
        if not intersects(raw,target):
            return 'unreachable!("positional list type constraint violated")'
        if not supports_projection(raw,target):
            raise ClassUnsupported(node,'the positional list value has no identity-preserving projection between these physical carriers',
                types=(('carrier',raw),('position',target)),proof='supported positional carrier projection')
        if raw=='int_bool':
            local=emitter.fresh()
            return ('match &('+payload+'){NativeScalar::Int('+local+')=>'
                +convert('int',target,'(*'+local+').clone()')+',NativeScalar::Bool('+local+')=>'
                +convert('bool',target,'(*'+local+').clone()')+'}')
        if union_kind(raw):
            return project(raw,payload,lambda kind,value:convert(kind,target,'('+value+').clone()'))
        if union_kind(target):
            selected=next(kind for kind in _alternatives(target)if intersects(raw,kind))
            return construct(target,selected,convert(raw,selected,payload))
        if isinstance(raw,TupleType)and isinstance(target,TupleType):
            captured=emitter.fresh()
            values=[convert(a,b,captured+'.'+str(i)+'.clone()')for i,(a,b)in enumerate(zip(raw.fields,target.fields))]
            return '{let '+captured+'='+payload+';'+tuple_code(values)+'}'
        return emitter.coerce(Expression(payload,raw),target,node)
    return Expression(convert(raw_kind,wanted,code),wanted)


def emit_unpack(emitter, target, value, record, assign_target=None):
    from .native_classes import shape
    setup, source = emitter.capture(value)
    unpacked = emitter.fresh()
    setup += 'let ' + unpacked + '=' + emitter.at(
        'class_unpack(&' + source.code + ',' + str(len(target.elts)) + ')', target) + ';'
    members = []
    for i, field in enumerate(record.fields):
        value = project_element(emitter, unpacked + '[' + str(i) + '].clone()',
                                source.kind.element, shape(field), target)
        before, value = emitter.capture(value)
        setup += before
        members.append(value)
    assign = assign_target or emitter.assign
    return setup + ''.join(assign(child, member) for child, member in zip(target.elts, members))
