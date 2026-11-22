"""Name metadata of source class objects (Objects/typeobject.c type_name/type_qualname/type_module).

``C.__name__`` and ``C.__qualname__`` come from the class statement and its
enclosing classes, and ``C.__module__`` from the defining module's ``__name__``
(stored in the class namespace by the compiler). Native class statements
execute once and writes to these special names stay positioned diagnostics, so
each is a constant of the class definition. A class body that binds one of
these names itself keeps the existing metadata diagnostic.
"""
NAMES = frozenset({'__name__', '__qualname__', '__module__'})


def _value(namespaces, owner, name):
    if name == '__name__':return owner.node.name
    if name == '__qualname__':return namespaces.qualname(owner)
    return owner.module_name


def analyze(namespaces, plan, node, receiver_kind):
    name = getattr(node, 'attr', None)
    if name not in NAMES:return None
    choices = namespaces.class_choices(receiver_kind)
    if not choices:return None
    owners = [namespaces.owners[choice.definition] for choice in choices]
    if any(name in namespaces.own_names.get(owner.index, ()) for owner in owners):return None
    namespaces.__dict__.setdefault('metadata_reads', {})[(plan.index, id(node))] = name
    return namespaces.model.cell(plan, node, 'str')


def emit(namespaces, emitter, node, receiver):
    from .native_classes import Expression
    from .native_unions import project, union_kind
    from .native import _string
    name = getattr(namespaces, 'metadata_reads', {}).get((emitter.plan.index, id(node)))
    if name is None:return None

    def branch(kind, code):
        text = _value(namespaces, namespaces.owners[kind.definition], name)
        return '{let _=&(' + code + ');NativeText::from(' + _string(text) + ')}'
    code = project(receiver.kind, receiver.code, branch) if union_kind(receiver.kind) else branch(receiver.kind, receiver.code)
    return Expression(emitter.coerce(Expression(code, 'str'), emitter.kind(node), node), emitter.kind(node))
