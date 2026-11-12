"""Nominal equality only for actual classes in one sealed source generation."""


def match(model, plan, actual):
    state = getattr(model, 'source_state', None)
    if state is None or state.barrier is not None or state.model is not model:
        return None
    from .native_class_binding_contexts import owner
    context = owner(model, plan)
    if context is None or actual is None:
        return None
    from .native_source_native_effects import _instance_value
    from .native_classes import InstanceType
    # Mutable fields do not change the actual nominal class. Exclude custom
    # lookup/__class__ slots, and retain the independent source-generation and
    # original class-binding certificates for both operands.
    if (not _instance_value(model,InstanceType(model.class_key(actual)))
            or not _instance_value(model,InstanceType(model.class_key(context)))
            or actual.index not in getattr(model,'published_metadata',())
            or context.index not in getattr(model,'published_metadata',())
            or not state.class_root(actual) or not state.class_root(context)):
        return None
    return actual is context
