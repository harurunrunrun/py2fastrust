"""Choose positional native constraints before either Rust emitter runs.

Only reached record consumers connected to solved literal allocations qualify.
Allocation sites are MAY-alias provenance, not unique runtime object proofs.
The selected emitter separately validates mutation, escape and slot precision.
"""
import ast

from .native_constraints import Allocation,Variable,Projection,TupleValue,IteratorValue,Value,ShapeConstraint
from .native_types import ListType
from .references import BuiltinIdentity


class Provenance:
    def __init__(self,heap):self.heap=heap

    def resolve(self,value,active=frozenset()):
        if value is None or value.unknown or value.unbound:return None
        result=set()
        for part in value.alternatives:
            if isinstance(part,ShapeConstraint):continue
            if isinstance(part,(Variable,Projection)):
                if part in active:return None
                if isinstance(part,Variable):incoming=self.heap.get(part)
                else:incoming=self.field(part.receiver,part.role,part.index,active|{part})
                members=self.resolve(incoming,active|{part})
                if members is None:return None
                result.update(members)
            else:result.add(part)
        return frozenset(result)

    def field(self,value,role,index=None,active=frozenset()):
        members=self.resolve(value,active)
        if not members:return None
        result=Value()
        for part in members:
            if isinstance(part,Allocation)and part.category in {'list','tuple_sequence','deque'}:
                incoming=self.heap.get(Variable(part.site,'element'))
            elif isinstance(part,IteratorValue):incoming=part.item
            elif isinstance(part,TupleValue):
                if index is not None:
                    incoming=part.fields[index]if -len(part.fields)<=index<len(part.fields)else None
                else:
                    incoming=Value()
                    for member in part.fields:incoming=incoming.join(member)
            else:return None
            if incoming is None:return None
            result=result.join(incoming)
        return result

    def lists(self,value):
        members=self.resolve(value)
        return members if members and all(isinstance(part,Allocation)and part.category=='list'for part in members)else None


def requires_frames(unit,analysis):
    from .native_list_positions import closed
    from .native_constraints import MethodValue
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    flow=Provenance(getattr(analysis,'heap',{}))
    schemas={};heterogeneous=set()
    for facts in analysis.scopes.values():
        for site,kind in facts.allocations.items():
            node=nodes.get(site)
            if not isinstance(node,ast.List)or not node.elts:continue
            # Capability selection needs the literal's canonical provenance
            # and closed child facts, not a proved uniform element ABI. A
            # coarse aggregate can be unresolved after indexed mutation;
            # the selected model still independently validates every use.
            if kind is not None and not isinstance(kind,ListType):continue
            slots=tuple(facts.expressions.get(unit.ordinal(child))for child in node.elts)
            if any(slot is None or not closed(slot)for slot in slots):continue
            origins=flow.lists(facts.values.get(site))
            if not origins:continue
            for origin in origins:
                if origin.site[1]!=site:continue
                schemas[origin]=len(slots)
                if any(slot!=slots[0]for slot in slots[1:]):heterogeneous.add(origin)
    if not schemas:return False

    def record(value,length=None,*,mixed=False):
        origins=flow.lists(value)
        allowed=heterogeneous if mixed else schemas.keys()
        return bool(origins and origins<=allowed and(length is None or all(schemas[part]==length for part in origins)))

    def unpack(target,value,*,mixed=False):
        if not isinstance(target,(ast.Tuple,ast.List))or any(isinstance(child,ast.Starred)for child in target.elts):return False
        if record(value,len(target.elts),mixed=mixed):return True
        members=flow.resolve(value)
        if not members or not all(isinstance(part,TupleValue)and len(part.fields)==len(target.elts)for part in members):return False
        return any(unpack(child,part.fields[i],mixed=mixed)for part in members for i,child in enumerate(target.elts))

    for facts in analysis.scopes.values():
        for site,value in facts.values.items():
            node=nodes.get(site)
            if (isinstance(node,ast.Subscript)and isinstance(node.ctx,ast.Load)
                    and isinstance(node.slice,(ast.Constant,ast.UnaryOp))):
                index=node.slice.operand if isinstance(node.slice,ast.UnaryOp)and isinstance(node.slice.op,(ast.USub,ast.UAdd))else node.slice
                if isinstance(index,ast.Constant)and type(index.value)is int and record(facts.values.get(unit.ordinal(node.value)),mixed=True):return True
        for node in nodes.values():
            if isinstance(node,(ast.Assign,ast.AnnAssign))and node.value is not None:
                value=facts.values.get(unit.ordinal(node.value))
                targets=node.targets if isinstance(node,ast.Assign)else[node.target]
                if any(unpack(target,value,mixed=True)for target in targets):return True
            elif isinstance(node,(ast.For,ast.comprehension)):
                value=flow.field(facts.values.get(unit.ordinal(node.iter)),'iteration')
                if unpack(node.target,value):return True
        for site,call in facts.calls.items():
            node=nodes.get(site)
            if not isinstance(node,ast.Call)or not any(name=='key'for name,_ in call.keywords):continue
            for identity in call.identity.alternatives:
                source=(call.positional[0]if isinstance(identity,BuiltinIdentity)and identity.name=='sorted'and call.positional else
                        identity.receiver if isinstance(identity,MethodValue)and identity.name=='sort'else None)
                if record(flow.field(source,'iteration'),mixed=True):return True
    return False
