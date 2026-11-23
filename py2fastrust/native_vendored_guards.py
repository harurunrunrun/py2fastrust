"""Conversion-time boundaries of independently implemented vendored packages.

A bundled package that re-implements a third-party API (sortedcontainers) only
covers part of the upstream surface. Where a program steps outside that part,
plain Python semantics of the bundled code would produce a different runtime
error than the upstream package (for example an unexpected keyword argument
instead of a key-function list, or AttributeError for an upstream method). Such
uses are positioned conversion errors instead.
"""
INDEPENDENT_PACKAGES = frozenset({'sortedcontainers'})


def independent(model, module_name):
    if not module_name:return False
    linker = getattr(model, 'module_linker', None)
    module = None if linker is None else linker.modules.get(module_name)
    return (module is not None and module.origin == 'vendored'
            and module_name.split('.')[0] in INDEPENDENT_PACKAGES)


def check_binding(model, plan, node, error):
    """A call of independent vendored code that Python would reject at binding time."""
    if independent(model, getattr(plan, 'module_name', None)):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(node, 'this call uses arguments that the bundled ' + plan.module_name.split('.')[0]
                               + ' implementation does not accept (' + str(error) + '); that part of the upstream API is not implemented',
                               proof='implemented vendored API surface')


def _instance_names(owner):
    """Names that methods of ``owner`` (and its bases) assign on their receiver."""
    import ast
    names = set()
    while owner is not None:
        for item in owner.node.body:
            if not isinstance(item, ast.FunctionDef) or not item.args.args:continue
            receiver = item.args.args[0].arg
            for node in ast.walk(item):
                if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
                        and isinstance(node.value, ast.Name) and node.value.id == receiver):
                    names.add(node.attr)
        owner = getattr(owner, 'base', None)
    return names


def check_attribute(model, plan, node, owner, name):
    """An attribute, read by the program, that an independent vendored class does not define."""
    if independent(model, getattr(plan, 'module_name', None)):return
    if not independent(model, getattr(owner, 'module_name', None)):return
    namespaces = getattr(model, 'class_namespaces', None)
    if namespaces is not None and namespaces.lookup(owner, name) is not None:return
    if name in owner.methods or name in _instance_names(owner):return
    from .native_classes import ClassUnsupported
    raise ClassUnsupported(node, 'attribute ' + repr(name) + ' of the bundled ' + owner.module_name.split('.')[0] + '.'
                           + owner.node.name + ' is not implemented', proof='implemented vendored API surface')


def check_slot(model, plan, node, owner, slot):
    """An operator protocol, used by the program, that an independent vendored class does not define."""
    if independent(model, getattr(plan, 'module_name', None)):return
    if not independent(model, getattr(owner, 'module_name', None)) or slot in owner.methods:return
    from .native_classes import ClassUnsupported
    raise ClassUnsupported(node, 'the ' + slot + ' protocol of the bundled ' + owner.module_name.split('.')[0] + '.'
                           + owner.node.name + ' is not implemented', proof='implemented vendored API surface')
