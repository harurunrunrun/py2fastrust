"""Select typed binding alternatives from actual solved list provenance."""
import ast

from .native_types import ListType
from .native_positional_selection import Provenance


def requires_frames(unit,analysis):
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    flow=Provenance(analysis.heap)
    layouts={}
    for facts in analysis.scopes.values():
        for site,kind in facts.allocations.items():
            if isinstance(kind,ListType):layouts.setdefault(site,set()).add(kind)
    for facts in analysis.scopes.values():
        for site,value in facts.values.items():
            node=nodes.get(site)
            if not isinstance(node,ast.Name)or not isinstance(node.ctx,ast.Load):continue
            origins=flow.lists(value)
            if not origins or len(origins)<2:continue
            # This selects a capable analyzer before emission. It does not
            # certify an allocation layout or treat MAY-alias sites as unique.
            choices=set()
            for origin in origins:choices.update(layouts.get(origin.site[1],()))
            if len(choices)>1:return True
    return False
