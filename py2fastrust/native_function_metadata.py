"""__name__ and __qualname__ of source function objects (Objects/funcobject.c, CPython 3.14).

A function object takes both from its code object when the ``def`` or
``lambda`` executes: ``__name__`` is the definition name (``<lambda>`` for a
lambda) and ``__qualname__`` is the compiler's qualified name, which prefixes
enclosing class names and ``<enclosing function>.<locals>`` (Python/compile.c
compiler_set_qualname); a name declared ``global`` in its enclosing scope keeps
only its own name. Native function values never rebind these attributes (writes
stay positioned diagnostics), so each is a constant of the definition.
"""
import ast

NAMES = frozenset({'__name__', '__qualname__'})


def _definitions(model):
    table = getattr(model, 'native_function_definitions', None)
    if table is None:
        table = model.native_function_definitions = {}
        for unit in model.unit.executable_source_units:
            parents = {}
            for parent in ast.walk(unit.tree):
                for child in ast.iter_child_nodes(parent):
                    parents[id(child)] = parent
            for node in ast.walk(unit.tree):
                if isinstance(node, (ast.FunctionDef, ast.Lambda)):
                    table[model.unit.ordinal(node)] = (node, parents)
    return table


def _qualname(node, parents):
    name = node.name if isinstance(node, ast.FunctionDef) else '<lambda>'
    parts = [name]
    scope = parents.get(id(node))
    first = True
    while scope is not None:
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if first and isinstance(node, ast.FunctionDef) and any(
                    isinstance(item, ast.Global) and node.name in item.names for item in ast.walk(scope)):
                return name
            parts.append((scope.name if not isinstance(scope, ast.Lambda) else '<lambda>') + '.<locals>')
            first = False
        elif isinstance(scope, ast.ClassDef):
            parts.append(scope.name)
            first = False
        scope = parents.get(id(scope))
    return '.'.join(reversed(parts))


def _value(model, definition, name):
    node, parents = _definitions(model)[definition]
    if name == '__name__':
        return node.name if isinstance(node, ast.FunctionDef) else '<lambda>'
    return _qualname(node, parents)


def analyze(model, plan, node, receiver_kind):
    from .native_aot_callables import function_kind
    if getattr(node, 'attr', None) not in NAMES or not function_kind(receiver_kind):return None
    if receiver_kind.builtins or receiver_kind.members or receiver_kind.methods or not receiver_kind.definitions:return None
    table = _definitions(model)
    if any(definition not in table for definition in receiver_kind.definitions):return None
    model.__dict__.setdefault('function_metadata_reads', {})[(plan.index, id(node))] = node.attr
    return model.cell(plan, node, 'str')


def emit(emitter, node):
    from .native_classes import Expression
    from .native_callable_carriers import dispatch
    from .native import _string
    name = getattr(emitter.model, 'function_metadata_reads', {}).get((emitter.plan.index, id(node)))
    if name is None:return None
    before, function = emitter.capture(emitter.expression(node.value))
    texts = {definition: _value(emitter.model, definition, name) for definition in function.kind.definitions}
    if len(set(texts.values())) == 1:
        code = '{let _=&(' + function.code + ');NativeText::from(' + _string(next(iter(texts.values()))) + ')}'
    else:
        code = dispatch(emitter, function.kind, function.code,
                        lambda target, payload: 'NativeText::from(' + _string(texts[target]) + ')', borrow=True)
    return Expression(emitter.coerce(Expression('{' + before + code + '}', 'str'), emitter.kind(node), node), emitter.kind(node))
