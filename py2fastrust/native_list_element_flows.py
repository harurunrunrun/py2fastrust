"""Retain actual concatenation inputs while sharing a list element ABI."""


def concatenate(model, plan, node, left, right, *, identity=None,
                allow_unresolved=False):
    from .native_classes import Cell, merge

    inputs = getattr(model, 'list_concatenation_inputs', None)
    if inputs is None:
        inputs = model.list_concatenation_inputs = {}
    key = plan.index, id(node), identity, left, right
    source = inputs.setdefault(key, Cell())
    value = model.flow_copy(right)
    source.tag, source.args = value.tag, value.args
    source.list_origins = value.list_origins
    # Raw union-find merging alone is insufficient for a member with derived
    # directional flow: its next append would recompute the member from only
    # the old append inputs, forgetting this real concatenation producer.
    model.namespace.contribute(left, source, node, force=True)
    merge(left, right, node, allow_unresolved=allow_unresolved)
