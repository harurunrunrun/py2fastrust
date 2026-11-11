"""Nominal equality only for actual classes in one sealed source generation."""


def match(model, plan, actual):
    state = getattr(model, 'source_state', None)
    if state is None or state.barrier is not None or state.model is not model:
        return None
    from .native_class_binding_contexts import owner
    context = owner(model, plan)
    if context is None or actual is None:
        return None
    from .native_value_classes import selected
    # Closed scalar value instances cannot change their concrete class. Both
    # names must also have one original definition and no source replacement.
    # A ClassDef ordinal alone cannot establish equality across import retries.
    if (not selected(model, actual) or not selected(model, context)
            or not state.class_root(actual) or not state.class_root(context)):
        return None
    return actual is context
