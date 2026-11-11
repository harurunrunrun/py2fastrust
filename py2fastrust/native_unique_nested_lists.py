"""Prove that fresh integer rows never escape their unique outer vector."""
import ast


def allocations(solver):
    from .native_constraints import Allocation, value
    from .native_types import ListType
    from .native_scalar_effects import scalar_rhs
    from .references import BuiltinIdentity

    unit = solver.graph.unit
    observers = {'globals', 'locals', 'vars', 'eval', 'exec', 'compile'}
    if any(fact.identity.unknown or fact.identity.unbound
            or any(getattr(identity, 'name', None) in observers for identity in fact.identity.alternatives)
            for fact in solver.calls.values()):
        return frozenset()
    parents = {id(child): parent for parent in ast.walk(unit.tree) for child in ast.iter_child_nodes(parent)}
    bindings = {row.node: row for row in unit.bindings}
    uses = {}
    ambiguous = set()
    groups = list(solver.records.values())
    groups.extend(item for state in solver.headers.values() for item in state.values())
    for item in groups:
        members = solver.provenance(item).alternatives
        if len(members) != 1:
            ambiguous.update(part for part in members if isinstance(part, Allocation))
    for (context, site), item in solver.records.items():
        for part in solver.provenance(item).alternatives:
            if isinstance(part, Allocation):
                uses.setdefault(part, []).append((context, solver.graph.nodes[site]))

    def scalar(context, node):
        return scalar_rhs(node, lambda child: solver.kind(solver.records.get(
            (context, unit.ordinal(child)), value(None))))

    def builtin(context, call, name):
        fact = solver.calls.get((context, unit.ordinal(call)))
        return (fact is not None and not fact.identity.unknown and not fact.identity.unbound
            and fact.identity.alternatives == {BuiltinIdentity(name)})

    def length(context, node):
        parent = parents.get(id(node))
        return (isinstance(parent, ast.Call) and parent.args == [node]
            and not parent.keywords and builtin(context, parent, 'len'))

    proved = set()
    for root in solver.allocations.values():
        if root.category != 'list' or solver.kind(value(root)) != ListType(ListType('int')):
            continue
        if root in solver.shared_references or root in ambiguous:
            continue
        creation = solver.graph.nodes[root.site[1]]
        assignment = parents.get(id(creation))
        if (not isinstance(assignment, ast.Assign) or assignment.value is not creation
                or len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name)):
            continue
        binding_name = unit.name_for(assignment.targets[0])
        if not (isinstance(creation, ast.ListComp) and isinstance(creation.elt, ast.List)
                or isinstance(creation, ast.List) and all(isinstance(child, ast.List) for child in creation.elts)):
            continue
        children = solver.provenance(solver.field(root, 'element')).alternatives
        if (not children or not all(isinstance(child, Allocation) and child.category == 'list'
                and child not in solver.shared_references for child in children)):
            continue
        fresh_nodes = {id(creation.elt)} if isinstance(creation, ast.ListComp) else {id(child) for child in creation.elts}
        if any(id(solver.graph.nodes[child.site[1]]) not in fresh_nodes for child in children):
            continue
        valid = True
        rows, mutations, iterations = set(), set(), []
        for context, node in uses.get(root, ()):
            if node is creation:
                continue
            row = bindings.get(unit.ordinal(node))
            parent = parents.get(id(node))
            if (not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load)
                    or row is None or row.scope != row.owner):
                valid = False
                break
            if length(context, node):
                continue
            if (not isinstance(parent, ast.Subscript) or parent.value is not node
                    or not isinstance(parent.ctx, ast.Load) or not scalar(context, parent.slice)):
                valid = False
                break
            rows.add(id(parent))
        if not valid:
            continue
        for child in children:
            for context, node in uses.get(child, ()):
                if id(node) in fresh_nodes:
                    continue
                if id(node) not in rows:
                    valid = False
                    break
                parent = parents.get(id(node))
                if isinstance(parent, ast.For) and parent.iter is node:
                    iterations.append(parent)
                elif length(context, node):
                    continue
                elif (isinstance(parent, ast.Subscript) and parent.value is node
                        and isinstance(parent.ctx, ast.Load) and scalar(context, parent.slice)):
                    continue
                elif isinstance(parent, ast.Attribute) and parent.value is node and parent.attr == 'append':
                    call = parents.get(id(parent))
                    if (not isinstance(call, ast.Call) or call.func is not parent
                            or len(call.args) != 1 or call.keywords or not scalar(context, call.args[0])):
                        valid = False
                        break
                    mutations.add(id(call))
                else:
                    valid = False
                    break
            if not valid:
                break
        def changes_owner(node):
            return (isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
                and unit.name_for(node) == binding_name)
        if valid and all(not any(id(node) in mutations or changes_owner(node)
                for statement in loop.body for node in ast.walk(statement)) for loop in iterations):
            proved.add(root)
            proved.update(children)
    return frozenset(proved)
