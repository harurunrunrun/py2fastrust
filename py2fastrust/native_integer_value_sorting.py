"""Use in-place value sorting only when equal integers are indistinguishable."""
import ast


def unstable(generator, element):
    if element != 'int':
        return False
    analysis = getattr(generator, 'type_analysis', None)
    if analysis is None:
        return False
    observers = {'id', 'getrefcount', 'get_referrers', 'get_referents',
                 'locals', 'globals', 'vars', 'eval', 'exec', 'compile'}
    for facts in analysis.scopes.values():
        for site in facts.expressions:
            node = analysis.graph.nodes.get(site)
            if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
                return False
        for call in facts.calls.values():
            if call.identity.unknown or call.identity.unbound:
                return False
            if any(getattr(identity, 'name', None) in observers for identity in call.identity.alternatives):
                return False
    return True
