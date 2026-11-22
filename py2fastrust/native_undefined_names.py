"""Programs that read a global name no statement binds raise NameError when the read runs.

The ordinary emitter needs a typed binding for every name it reads; frames
report CPython's runtime NameError for an unbound global. Selection uses the
official symbol tables: a module-level reference, or an implicit global
reference from a nested scope, whose name the module never assigns, imports or
declares and which is not a builtin.
"""
import builtins


def requires_frames(unit):
    table = unit.table
    bound = {symbol.get_name() for symbol in table.get_symbols()
             if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace() or symbol.is_declared_global()}
    names = set(dir(builtins)) | {'__name__', '__file__', '__doc__', '__builtins__', '__spec__', '__loader__', '__package__',
                                  # compiler-synthesized annotation bookkeeping (PEP 649/749)
                                  '__conditional_annotations__', '__annotate__', '__annotations__', '__classdict__'}

    def visit(scope, module):
        for symbol in scope.get_symbols():
            name = symbol.get_name()
            # symtable's is_global() mistakes a function named 'top' for the
            # module table; an implicit global read is a referenced name that
            # is neither local nor free in this scope.
            reads = symbol.is_referenced() and (module and not symbol.is_assigned() or not module and not symbol.is_local()
                                                 and not symbol.is_free() and not symbol.is_declared_global())
            if reads and name not in bound and name not in names:
                return True
        # Annotation scopes run only when annotations are introspected, and a
        # named function whose name is never loaded is never called.
        return any(visit(child, False) for child in scope.get_children()
                   if child.get_type() != 'annotation'
                   and not (child.get_type() == 'function' and child.get_name().isidentifier() and child.get_name() not in loaded))
    import ast
    loaded = {node.id for node in ast.walk(unit.tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    loaded |= {node.attr for node in ast.walk(unit.tree) if isinstance(node, ast.Attribute)}
    return visit(table, True)
