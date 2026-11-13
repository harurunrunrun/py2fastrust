"""Default-GIL CP3.14 constant interning boundary for typed set literals.

CodeType string interning can rebuild a frozenset from its physical traversal.
The compiler host's intern pool is not a target-state oracle. Source-owned
interning/reconstruction remains open; closed unchanged or unobserved cases
retain their existing native lowering.
"""
import ast


def unchanged_string(value):
    # Empty/Latin-1 singletons retain their canonical object. In the default
    # GIL build CodeType interns only ASCII [A-Za-z0-9_]* strings; other values
    # never cause its direct-string replacement flag.
    if not value or len(value)==1 and ord(value)<256:return True
    return not value.isascii()or any(not('a'<=ch<='z'or'A'<=ch<='Z'or'0'<=ch<='9'or ch=='_')for ch in value)


def unobserved(model,plan,node,parents):
    """Reuse the existing closed order-erasure proof on original allocations."""
    from .native_unobserved_set_order import Proof,State,Unproved
    from .references import BuiltinIdentity
    from .native_owned_local_lists import observes_frames
    if observes_frames(model):return False
    parent=parents.get(id(node));proof=Proof(model,node,None)
    try:
        if (isinstance(parent,ast.Compare)and parent.comparators[-1]is node
                and isinstance(parent.ops[-1],(ast.In,ast.NotIn))):
            from .native_types import EmptyType,TupleType,TupleSequenceType,alternatives
            from .native_classes import shape
            query=parent.left if len(parent.ops)==1 else parent.comparators[-2]
            cell=model.records.get((plan.index,id(query)))
            def closed(kind):
                if isinstance(kind,EmptyType)or kind in {'int','bool','int_bool','str','bytes','none'}:return True
                if type(kind)is TupleType:return all(closed(child)for child in kind.fields)
                if type(kind)is TupleSequenceType:return closed(kind.element)
                choices=alternatives(kind)
                return len(choices)>1 and all(closed(child)for child in choices)
            # The actual typed mapping-key protocol is callback-free here.
            # A middle comparator is reused and must not use this certificate.
            return cell is not None and closed(shape(cell))
        if isinstance(parent,ast.Call)and len(parent.args)==1 and parent.args[0]is node and not any(keyword.arg is None for keyword in parent.keywords):
            from .native_physical_list_builtins import static_builtin
            if static_builtin(model,plan,parent.func,'list')or proof.targets(plan,parent.func)==(BuiltinIdentity('list'),):
                if parent.keywords:return False
                return Proof(model,parent,None).prove(plan,parent)
            # sorted/len/bool and closed source forwarding use the same
            # effect/alias certificate as the existing materialization path.
            return proof.expression(plan,parent,State())is False
        if isinstance(plan.node,ast.FunctionDef)and plan.class_body is None:
            return proof.prove(plan,node)
    except Unproved:return False
    return False


def certify(emitter,node,record,registry,order_irrelevant):
    from .native_classes import shape,ClassUnsupported
    if shape(record.key)!='str':return
    origins=registry.constant_origins
    values=origins.values(node.elts)if origins is not None else None
    if values is not None and all(type(value)is str for value in values):
        # With at most one distinct entry, any number of reconstructions has
        # exactly the same table order, independently of prior intern state.
        if len(set(values))<=1 or all(unchanged_string(value)for value in values):return
    if order_irrelevant():return
    raise ClassUnsupported(node,'this frozen string-set constant can be reconstructed by CPython CodeType string interning; its source-owned intern-pool and reconstruction history are not implemented yet, and no closed proof erases the resulting order',proof='unchanged or unobserved default-GIL frozen-string constant history')
