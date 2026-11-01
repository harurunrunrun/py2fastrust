"""Publish solved class-list element ABIs into the common allocation graph.

An allocation keeps its original element cell across binding wrappers and
union-find links. Several real allocations may share a solved element family;
one cell identity must not overwrite the other allocation's registration.
"""


def register(model,allocation,member):
    registry=getattr(model,'class_allocation_members',None)
    if registry is None:
        registry={};model.class_allocation_members=registry
    registry[allocation]=member


def publish(model):
    from .native_class_globals import complete
    from .native_classes import shape
    from .native_constraints import value
    for allocation,member in getattr(model,'class_allocation_members',{}).items():
        kind=shape(member)
        # Python None is the resolved 'none' kind. A Python None here instead
        # denotes an unresolved compiler cell, not a possible runtime value.
        if complete(kind):model.value_constraints.insert(value(allocation),'element',value(kind))
