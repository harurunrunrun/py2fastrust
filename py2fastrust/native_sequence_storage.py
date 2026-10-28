"""Physical sequence views for one shared typed method lowering.

Receiver evaluation is eager. A view borrows its contents only after explicit
arguments have been evaluated, so callbacks may mutate the captured object.
Shared handles capture object identity before a callback can replace a field.
"""
from dataclasses import dataclass

from .native import _Binding,_Unsupported
from .native_types import is_maybe,immutable
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

    @property
    def element(self):return element_type(self.kind)

    def own(self,code):
        return f"class_list({code})" if self.shared else code


def capture_owned(g,receiver,node,environment,*,mutates):
    if receiver.sequence_view is not None:
        storage=receiver.sequence_view
        if mutates and any(name in g.iterating_lists for name in storage.forbidden_owners):
            raise _Unsupported("this mutation would change a sequence whose owner is held by an active native iteration borrow; shared identity-preserving mutation during iteration is not implemented for this storage",node=node,types=(("receiver",receiver.kind),),proof="sequence mutation without invalidating an active owner/iteration borrow")
        return storage
    owner=g.temporary()
    if receiver.owned:
        return SequenceStorage((f"let mut {owner}={receiver.code};",),
            f"&{owner}",f"&mut {owner}",receiver.kind)
    if g.type_analysis is None or g.source_unit is None:
        raise _Unsupported("capturing this borrowed sequence needs resolved allocation/binding facts so later argument effects cannot change which object is used; those identity facts are unavailable",node=node,types=(("receiver",receiver.kind),),proof="stable borrowed sequence identity across argument evaluation")
    term=g.type_analysis.graph.expressions[g.source_unit.ordinal(node)]
    if term.operation!="name":
        raise _Unsupported("this borrowed sequence producer is not a proved stable name binding; an identity handle for its result must survive later argument effects before the sequence is borrowed",node=node,types=(("receiver",receiver.kind),),proof="single evaluation and stable sequence object identity")
    name=term.data
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
    return SequenceStorage(setup,f"&({receiver.code})[..]",mutable,receiver.kind,binding_name=name)


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
        f"&({owner}.borrow())[..]",f"&mut *{owner}.borrow_mut()",receiver.kind,shared=True)


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
    term=g.type_analysis.graph.expressions[g.source_unit.ordinal(node)]
    if term.operation!="name"or not isinstance(environment.get(term.data),_Binding):
        raise _Unsupported("a mutable argument's truth must be tested after later arguments run, but this producer has no proved stable name/identity handle; copying its contents would hide intervening mutations",node=node,types=(("value",value.kind),),proof="mutable object identity and deferred truth-test evaluation order")
    return (f"let _=&({value.code});",),value,()
