"""Source exception classes with an empty body (``class E(ValueError): pass``).

Such a class adds a name and a place in the exception hierarchy but no state or
behavior of its own: its instances are built by ``BaseException.__new__`` and
``BaseException.__init__``, so ``E(*args)`` stores ``args`` exactly as the
builtin base does, and ``str``/``repr`` and the traceback line use the base
implementations with the class's ``__name__``. A module-level class in the main
module whose single base is a supported builtin exception class (or another
such class) and whose name is never rebound is therefore a static exception
class identity; its definition statement binds nothing that native code reads
dynamically.
"""
import ast

from .native_exception_values import ExceptionClass, PARENTS

BASES = frozenset({'Exception', 'LookupError', 'IndexError', 'ValueError', 'TypeError', 'RuntimeError'})


def _empty_body(node):
    return all(isinstance(item, ast.Pass) or isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant)
               and (type(item.value.value) is str or item.value.value is Ellipsis) for item in node.body)


def discover(model, unit, node):
    """Register ``node`` as a source exception class when it qualifies; True when registered."""
    from .native_classes import ClassUnsupported
    if unit is not model.unit.main or len(node.bases) != 1 or node.keywords or node.decorator_list or getattr(node, 'type_params', ()):
        return False
    base = node.bases[0]
    if not isinstance(base, ast.Name):return False
    registry = model.__dict__.setdefault('user_exceptions', {})
    key = model.unit.resolved_names.get(id(base))
    parent = registry.get(key)
    if parent is None:
        if key not in PARENTS:return False
        if key not in BASES:
            raise ClassUnsupported(base, 'subclassing ' + key + ' needs its special runtime protocol (exception groups, iteration or interpreter control); Exception, LookupError, IndexError, ValueError, TypeError and RuntimeError subclasses are implemented',
                                   proof='source exception class base')
        parent = ExceptionClass(key)
    if not _empty_body(node):
        raise ClassUnsupported(node, 'an exception subclass with its own methods or attributes needs a typed exception-instance layout; exception subclasses whose body is only pass or a docstring are implemented',
                               proof='source exception class instance layout')
    import builtins
    if hasattr(builtins, node.name):
        raise ClassUnsupported(node, 'an exception class that reuses a builtin name would share its traceback and handler spelling; that name aliasing is not implemented',
                               proof='distinct source exception class name')
    name = model.definition_name(node)
    for other in ast.walk(unit.tree):
        if other is node:continue
        if (isinstance(other, ast.Name) and not isinstance(other.ctx, ast.Load)
                or isinstance(other, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.alias, ast.arg))):
            if model.unit.resolved_names.get(id(other)) == name:
                raise ClassUnsupported(other, 'this rebinds a source exception class name; a mutable exception-class binding is not implemented',
                                       proof='static source exception class binding')
    registry[name] = ExceptionClass(node.name, parent, len(registry))
    model.__dict__.setdefault('user_exception_nodes', set()).add(id(node))
    return True


def is_definition(model, node):
    return isinstance(node, ast.ClassDef) and id(node) in getattr(model, 'user_exception_nodes', ())


def user_class(model, plan, node):
    registry = getattr(model, 'user_exceptions', None)
    if not registry:return None
    return registry.get(model.resolved_name(plan, node))


def covered(model, names):
    """Add the source exception classes whose ancestry reaches any name in ``names``."""
    result = set(names)
    for kind in getattr(model, 'user_exceptions', {}).values():
        ancestor = kind
        while ancestor is not None:
            if ancestor.name in names:
                result.add(kind.name)
                break
            ancestor = ancestor.parent
    return frozenset(result)
