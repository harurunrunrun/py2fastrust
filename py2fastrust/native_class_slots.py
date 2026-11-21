"""Literal ``__slots__`` declarations on base-less classes (Objects/typeobject.c type_new slots).

``__slots__`` replaces the instance ``__dict__`` by one descriptor per listed
name. Instances can then hold only those attributes; a slot that was never
assigned reads as AttributeError like any missing attribute. The native frame
already stores instance attributes as fixed fields, so a declaration is
accepted when every attribute the program writes on instances is a declared
slot. Writes of other names (AttributeError at runtime), class attributes that
conflict with a slot (ValueError at class creation), non-literal declarations,
private names, ``__dict__``/``__weakref__`` entries and base classes remain
positioned diagnostics. ``__slots__`` itself is not readable.
"""
import ast


def _statement(owner, target):
    for statement in owner.body:
        if isinstance(statement, ast.Assign) and any(item is target for item in statement.targets):
            return statement
        if isinstance(statement, ast.AnnAssign) and statement.target is target:
            return statement
    return None


def _names(value):
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return (value.value,)
    if isinstance(value, (ast.Tuple, ast.List)) and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts):
        return tuple(item.value for item in value.elts)
    return None


def declare(model, owner, target):
    """Record the slots of ``owner`` for a ``__slots__ = ...`` class-body store; False if not applicable."""
    from .native_classes import ClassUnsupported
    node = getattr(owner, 'node', None)
    if not isinstance(node, ast.ClassDef):
        return False
    statement = _statement(node, target)
    names = _names(statement.value) if statement is not None and statement.value is not None else None
    if names is None or (isinstance(statement, ast.Assign) and len(statement.targets) != 1):
        raise ClassUnsupported(target, '__slots__ must be a literal string or tuple/list of strings for the native slot layout; computed declarations need the type_new slot protocol',
                               proof='literal __slots__ declaration')
    if node.bases or node.keywords:
        raise ClassUnsupported(target, '__slots__ with base classes or a metaclass needs inherited slot layout validation, which is not implemented', proof='base-less __slots__ class')
    if len(set(names)) != len(names) or any(not name.isidentifier() or name in {'__dict__', '__weakref__'} or name.startswith('__') and not name.endswith('__')
                                            for name in names):
        raise ClassUnsupported(target, 'these __slots__ entries need duplicate, private-name mangling or __dict__/__weakref__ slot handling, which is not implemented',
                               proof='plain __slots__ names')
    defined = set()
    for statement_node in node.body:
        if isinstance(statement_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(statement_node.name)
        elif isinstance(statement_node, ast.Assign):
            defined.update(item.id for item in statement_node.targets if isinstance(item, ast.Name))
        elif isinstance(statement_node, ast.AnnAssign) and isinstance(statement_node.target, ast.Name) and statement_node.value is not None:
            defined.add(statement_node.target.id)
    conflict = sorted(defined.intersection(names))
    if conflict:
        raise ClassUnsupported(target, f'{conflict[0]!r} in __slots__ conflicts with class variable; class creation raises ValueError, and that path is not implemented',
                               proof='__slots__ class variable conflict')
    slots = getattr(model, 'class_slots', None)
    if slots is None:
        slots = model.class_slots = {}
    slots[node] = frozenset(names)
    return True


def check_write(model, owner, name, node):
    slots = getattr(model, 'class_slots', {}).get(getattr(owner, 'node', None))
    if slots is not None and name not in slots:
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node, f'assigning attribute {name!r} that is not in __slots__ raises AttributeError (no __dict__); that error path is not implemented',
                               proof='__slots__ attribute layout')
