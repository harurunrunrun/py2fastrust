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

    unit = getattr(g, "source_unit", None)
    analysis = getattr(g, "type_analysis", None)
    term = None
    if unit is not None and analysis is not None:
        try:
            term = analysis.graph.expressions[unit.ordinal(node)]
        except KeyError:
            pass
    if term is not None and term.operation == "name":
        binding = environment.get(term.data)
        if not isinstance(binding, _Binding):
            raise _Unsupported
        if isinstance(binding.info, _MaybeInfo):
            if binding.info.kind != value.kind:
                raise _Unsupported
            # This checked read owns no persistent borrow. It raises at the
            # original source position before later argument side effects.
            setup = f"let _=&({value.code});"
            owner = f'{binding.slot}.as_ref().expect("validated container binding")'
            return ContainerRead(setup, owner)
        if value.code != binding.slot:
            raise _Unsupported
        return ContainerRead("", binding.slot)

    # A subscript, call, or other producer can raise or have side effects.
    # Keep its complete result instead of replaying it at iterator creation.
    owner = g.temporary()
    return ContainerRead(f"let {owner}={value.code};", owner)
