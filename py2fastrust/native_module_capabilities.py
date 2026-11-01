"""Admit canonical standard exports to independently scoped native frames."""
import ast

LINKED_MODULES=frozenset({'itertools'})
LINKED_EXPORTS={'collections':frozenset({'Counter'})}


def needs_linked_members(program):
    for unit in program.units:
        for imported in unit.imports:
            if imported.origin not in {'builtin','vendored'}:continue
            if imported.module in LINKED_MODULES:return True
            exports=LINKED_EXPORTS.get(imported.module,frozenset())
            if exports.intersection(imported.names):return True
            if exports and not imported.names:
                # Admission may be conservative for module arguments/aliases.
                # The linked binder still proves the actual receiver's canonical
                # module identity before a native member adapter is invoked.
                if any(isinstance(node,ast.Attribute)and node.attr in exports for node in ast.walk(unit.tree)):return True
    return False
