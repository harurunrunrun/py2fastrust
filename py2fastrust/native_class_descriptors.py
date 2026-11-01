"""Definition-time descriptor hooks for typed source class namespaces."""


def receiver_kind(registry,owner,node):
    from .native_classes import InstanceType,ClassUnsupported
    if node.decorator_list:
        raise ClassUnsupported(node,"this class method has decorators whose descriptor construction and binding protocol are not implemented",proof="class method decorator identity and descriptor binding")
    return InstanceType(registry.model.class_key(owner))


def analyze_definition(registry,caller,node,member,environment):
    from .native_classes import ClassUnsupported
    if node.decorator_list:
        raise ClassUnsupported(node,"class method decorator execution and descriptor construction are not implemented",proof="definition-time class descriptor construction")


def prepare_definition(registry,caller,node,member,environment):
    return None


def emit_prepare_definition(registry,emitter,node,member):
    return ""


def analyze_member(registry,plan,node,member,receiver,environment):
    return None


def emit_member(registry,emitter,node,member,class_reference,function):
    return None
