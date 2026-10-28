"""Read a concrete container binding before borrowing its mutable contents.

Python evaluates an argument's name lookup before later arguments. Rust borrows
must wait until those arguments have run when they can mutate the same object.
The direct emitter keeps ordinary names in local Rust slots: accepted callbacks
cannot replace a caller's slot through global/nonlocal writes or dynamic code.
Those unsupported namespace effects must stay rejected until binding identities
have an explicit shared storage representation.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerRead:
    setup: str
    owner: str


def capture(g, node, value, environment):
    """Capture producers once; split optional name checks from later borrows."""
    from .native import _Binding, _MaybeInfo, _Unsupported
    if value.owned:
        owner = g.temporary()
        return ContainerRead(f"let {owner}={value.code};", owner)

    from .native_sequence_storage import binding_name
    name=binding_name(g,node)
    if name is not None:
        binding = environment.get(name)
        if not isinstance(binding, _Binding):
            raise _Unsupported("the container name has no resolved native storage binding; its identity cannot be captured before later argument effects",node=node,types=(("container",value.kind),),proof="stable container binding and argument evaluation order")
        if isinstance(binding.info, _MaybeInfo):
            if binding.info.kind != value.kind:
                raise _Unsupported("the possibly-unbound container binding and captured value have different storage types; an identity-preserving projection is not proved",node=node,types=(("binding",binding.info.kind),("container",value.kind)),proof="consistent container storage across unbound-name checking and deferred borrowing")
            # This checked read owns no persistent borrow. It raises at the
            # original source position before later argument side effects.
            setup = f"let _=&({value.code});"
            owner = f'{binding.slot}.as_ref().expect("validated container binding")'
            return ContainerRead(setup, owner)
        if value.code != binding.slot:
            raise _Unsupported("the captured container expression is not the resolved binding's storage slot; stable object identity across later argument effects is not proved",node=node,types=(("container",value.kind),),proof="stable container binding without replaying or copying its producer")
        return ContainerRead("", binding.slot)

    # A subscript, call, or other producer can raise or have side effects.
    # Keep its complete result instead of replaying it at iterator creation.
    owner = g.temporary()
    return ContainerRead(f"let {owner}={value.code};", owner)
