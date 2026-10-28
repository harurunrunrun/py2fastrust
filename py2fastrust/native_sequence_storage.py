"""Physical sequence views for one shared typed method lowering.

Receiver evaluation is eager. A view borrows its contents only after explicit
arguments have been evaluated, so callbacks may mutate the captured object.
Shared handles capture object identity before a callback can replace a field.
"""
from dataclasses import dataclass
import ast

from .native import _Binding,_Unsupported
from .native_types import is_maybe,immutable,unmaybe
from .native_sequence_plans import element_type


@dataclass(frozen=True)
class SequenceStorage:
    setup: tuple[str,...]
    read: str
    mutable: str | None
    kind: object
    shared: bool=False
    binding_name: str | None=None
    forbidden_owners: tuple[str,...]=()
    mutation_binding: object=None
    shared_factory: str="class_list"
    callback_owners: tuple[str,...]=()

    @property
    def element(self):return element_type(self.kind)

    def own(self,code):
        return f"{self.shared_factory}({code})" if self.shared else code


def binding_name(g,node):
    """Query a canonical lexical name without requiring a normalized parent call.

    The current semantic graph can omit a starred print's argument subtree.
    SourceUnit still owns every name and its lexical/private-name mapping.
    Ordinary exact-name binding proofs do not require emitting that subtree.
    """
    unit=getattr(g,"source_unit",None)
    if unit is None:return None
    if isinstance(node,ast.Name):
        try:return unit.name_for(node)
        except KeyError:return None
    analysis=getattr(g,"type_analysis",None)
    if analysis is None:return None
    try:ordinal=unit.ordinal(node)
    except KeyError:return None
    term=analysis.graph.expressions.get(ordinal)
    return term.data if term is not None and term.operation=="name"else None


def capture_owned(g,receiver,node,environment,*,mutates):
    from .native_types import SharedListType
    if isinstance(receiver.kind,SharedListType):
        from dataclasses import replace
        name=binding_name(g,node)
        binding=environment.get(name)
        # sort callbacks must not observe their receiver through any shared
        # alias or parent. Other methods hold no borrow while operands run.
        owners=[]
        unit=getattr(g,"source_unit",None)
        if unit is not None:
            by_ordinal={unit.ordinal(item):item for item in ast.walk(unit.tree)}
            try:scope=unit.nodes[unit.ordinal(node)].scope
            except KeyError:scope=0
            ancestors=set()
            while scope is not None:
                ancestors.add(scope);scope=unit.scopes[scope].parent
            aliases={key for key,item in environment.items()if isinstance(item,_Binding)and isinstance(unmaybe(item.kind),SharedListType)}
            for item in unit.bindings:
                source=by_ordinal.get(item.node)
                try:key=unit.name_for(source)
                except KeyError:continue
                if item.scope in ancestors and key in aliases:owners.append((item.name,item.owner))
        owners=tuple(set(owners))
        return replace(capture_shared(g,receiver),binding_name=name,
                       mutation_binding=binding if isinstance(binding,_Binding)else None,
                       callback_owners=owners)
    if receiver.sequence_view is not None:
        storage=receiver.sequence_view
        if mutates and storage.mutation_binding is not None and storage.mutation_binding.slot in g.borrowed_slots:
            raise _Unsupported("this sequence view is rooted in a read-only borrowed argument; mutating its row would change the caller's storage, and a mutable shared argument representation is not implemented",node=node,types=(("receiver",receiver.kind),),proof="mutable sequence access without violating a borrowed argument")
        if mutates and any(name in g.iterating_lists for name in storage.forbidden_owners):
            raise _Unsupported("this mutation would change a sequence whose owner is held by an active native iteration borrow; shared identity-preserving mutation during iteration is not implemented for this storage",node=node,types=(("receiver",receiver.kind),),proof="sequence mutation without invalidating an active owner/iteration borrow")
        return storage
    owner=g.temporary()
    if receiver.owned:
        return SequenceStorage((f"let mut {owner}={receiver.code};",),
            f"&{owner}",f"&mut {owner}",receiver.kind)
    if g.type_analysis is None or g.source_unit is None:
        raise _Unsupported("capturing this borrowed sequence needs resolved allocation/binding facts so later argument effects cannot change which object is used; those identity facts are unavailable",node=node,types=(("receiver",receiver.kind),),proof="stable borrowed sequence identity across argument evaluation")
    name=binding_name(g,node)
    if name is None:
        raise _Unsupported("this borrowed sequence producer is not a proved stable name binding; an identity handle for its result must survive later argument effects before the sequence is borrowed",node=node,types=(("receiver",receiver.kind),),proof="single evaluation and stable sequence object identity")
    binding=environment.get(name)
    if not isinstance(binding,_Binding):
        raise _Unsupported(f"sequence name {name!r} has no resolved native storage binding; its mutable object identity cannot be captured safely",node=node,types=(("receiver",receiver.kind),),proof="resolved sequence binding and object identity")
    if mutates and (name in g.iterating_lists or binding.slot in g.borrowed_slots):
        raise _Unsupported(f"sequence {name!r} is already borrowed by an active iteration/read; mutation through this owned-vector representation could invalidate that borrow, and shared mutation storage is not implemented here",node=node,types=(("receiver",receiver.kind),),proof="alias-preserving mutation while an iteration/read remains active")
    # Evaluate possible unbound-name errors before any following argument. The
    # later view is non-observable because this backend proves binding identity.
    setup=(f"let _=&({receiver.code});",)
    mutable=(f'{binding.slot}.as_mut().expect("validated sequence receiver")' if is_maybe(binding.kind)
             else f"&mut {binding.slot}")
    read=f"&({receiver.code})"if receiver.kind=="deque_int"else f"&({receiver.code})[..]"
    return SequenceStorage(setup,read,mutable,receiver.kind,binding_name=name)


def row_expression(g,node,owner,index,environment):
    """Describe an already lowered row owner/index; never visit either twice."""
    from .native import _Expression
    binding=environment.get(node.value.id)
    if not isinstance(binding,_Binding):
        raise _Unsupported("the matrix row's owner has no resolved native binding; retaining the same row across later argument effects requires an identity-preserving owner/row handle",node=node,types=(("owner",owner.kind),),proof="stable matrix owner and row identity")
    offset=g.temporary()
    setup=(f"let _=&({owner.code});",
           f"let {offset}={g.at(f'native_index({g.number(index)},({owner.code}).len())',node)};")
    read=f"&(({owner.code})[{offset}])[..]"
    parent=(f'{binding.slot}.as_mut().expect("validated matrix receiver")'if is_maybe(binding.kind)
            else binding.slot)
    storage=SequenceStorage(setup,read,f"&mut ({parent})[{offset}]","list_int",
                            forbidden_owners=(node.value.id,),mutation_binding=binding)
    code="{"+"".join(setup)+f"&({owner.code})[{offset}]"+"}"
    return _Expression(code,"list_int",owned=False,sequence_view=storage)


def capture_shared(g,receiver):
    owner=g.temporary()
    return SequenceStorage((f"let {owner}={receiver.code};",),
        f"&({owner}.borrow())[..]",f"&mut *{owner}.borrow_mut()",receiver.kind,shared=True,
        shared_factory="native_shared_list"if receiver.kind.__class__.__name__=="SharedListType"else"class_list")


def deferred_truth(g,value,node,environment):
    """Capture mutable identity before later args, then inspect contents later.

    An owned value can move into an ordinary temporary, and immutable values
    can be snapshotted. A borrowed container must retain object identity: copying
    its contents would hide mutations made by subsequent argument expressions.
    Name bindings are stable in this backend; dynamic rebinding is not admitted.
    """
    if value.owned or immutable(value.kind):return None
    if value.sequence_view is not None:
        storage=value.sequence_view
        from .native import _Expression
        return storage.setup,_Expression(storage.read,value.kind,owned=False),storage.forbidden_owners
    if g.type_analysis is None or g.source_unit is None:
        raise _Unsupported("a mutable argument's truth must be tested after later arguments run; allocation/binding facts needed to retain that same object are unavailable",node=node,types=(("value",value.kind),),proof="mutable object identity and deferred truth-test evaluation order")
    name=binding_name(g,node)
    if name is None or not isinstance(environment.get(name),_Binding):
        raise _Unsupported("a mutable argument's truth must be tested after later arguments run, but this producer has no proved stable name/identity handle; copying its contents would hide intervening mutations",node=node,types=(("value",value.kind),),proof="mutable object identity and deferred truth-test evaluation order")
    return (f"let _=&({value.code});",),value,()
