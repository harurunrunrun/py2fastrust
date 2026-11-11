"""Immediate builtin view consumers need a producer loan, not an escaped view."""
import ast


def ordinary_compatible(unit, analysis, kinds, parents):
    """Every mapping operation must already have an ordinary typed adapter.

    Changing the storage selection affects the containing program, including
    dictionaries other than the immediate view's receiver. Keep captured or
    escaped owners, dynamic queries and richer method protocols on their
    existing shared representation.
    """
    from .native_key_types import DictType, compatible_keys
    from .native_key_containers import key_kind
    from .references import BuiltinIdentity
    bindings = {row.node: row for row in unit.bindings}

    def owners(node):
        return [kind for kind in kinds.get(unit.ordinal(node), ()) if isinstance(kind, DictType)]

    def builtin(call, names):
        seen = False
        for facts in analysis.scopes.values():
            record = facts.calls.get(unit.ordinal(call))
            if record is None:
                continue
            if record.identity.unknown or record.identity.unbound:
                return False
            choices = record.identity.alternatives
            if not any(choices == {BuiltinIdentity(name)} for name in names):
                return False
            seen = True
        return seen

    def query(node, containers):
        choices = kinds.get(unit.ordinal(node), ())
        return bool(choices) and all(key_kind(kind) and compatible_keys(kind, owner.key)
            for kind in choices for owner in containers)

    for node in ast.walk(unit.tree):
        if isinstance(node, ast.Subscript) and (containers := owners(node.value)):
            if isinstance(node.slice, ast.Slice) or not query(node.slice, containers):
                return False
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            containers = owners(node.func.value)
            if containers:
                if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
                    return False
                method = node.func.attr
                if method in {'keys', 'items', 'values', 'clear'}:
                    if node.args:
                        return False
                elif method == 'get' and len(node.args) == 2:
                    if not query(node.args[0], containers):
                        return False
                    defaults = kinds.get(unit.ordinal(node.args[1]), ())
                    numeric = {'int', 'bool', 'int_bool'}
                    if not defaults or not all(kind == owner.value or kind in numeric and owner.value in numeric
                            for kind in defaults for owner in containers):
                        return False
                else:
                    return False
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load) or not owners(node):
            continue
        row = bindings.get(unit.ordinal(node))
        if row is None or row.scope != row.owner:
            return False
        parent = parents.get(id(node))
        if isinstance(parent, ast.Subscript) and parent.value is node:
            continue
        if isinstance(parent, ast.Attribute) and parent.value is node:
            call = parents.get(id(parent))
            if isinstance(call, ast.Call) and call.func is parent:
                continue
        if isinstance(parent, ast.Call) and node in parent.args and builtin(parent, {'len', 'bool', 'list', 'sum', 'print'}):
            continue
        if isinstance(parent, (ast.If, ast.While)) and parent.test is node:
            continue
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            continue
        if (isinstance(parent, ast.Compare) and len(parent.ops) == 1
                and isinstance(parent.ops[0], (ast.In, ast.NotIn))
                and parent.comparators[0] is node and query(parent.left, owners(node))):
            continue
        return False
    return True


def immediate(unit, analysis, node, parents):
    if (node.args or node.keywords or not isinstance(node.func.value, ast.Name)):
        return False
    parent = parents.get(id(node))
    if (not isinstance(parent, ast.Call) or len(parent.args) != 1
            or parent.args[0] is not node or parent.keywords):
        return False
    from .native_key_types import DictType
    from .references import BuiltinIdentity
    receiver = unit.ordinal(node.func.value)
    site = unit.ordinal(parent)
    witnessed = False
    for facts in analysis.scopes.values():
        if not isinstance(facts.expressions.get(receiver), DictType):
            continue
        call = facts.calls.get(site)
        if call is None or call.identity.unknown or call.identity.unbound:
            return False
        identities = call.identity.alternatives
        if identities not in ({BuiltinIdentity('list')}, {BuiltinIdentity('sum')}):
            return False
        if identities == {BuiltinIdentity('sum')}:
            owner = facts.expressions[receiver]
            element = owner.value if node.func.attr == 'values' else owner.key
            if node.func.attr == 'items' or element not in {'int', 'bool', 'int_bool'}:
                return False
        witnessed = True
    return witnessed
