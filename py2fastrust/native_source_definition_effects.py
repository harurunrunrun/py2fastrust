"""Source-order definition events and unused-parent StateAbi eligibility.

These are effect transfers for original definition statements, not callable
substitutions.  The original binder, function instances, lazy metadata and
definition publication still run through their existing native consumers.
"""
import ast


def argument_parent_closed(model, plan):
    """Reuse the actual callable's existing incoming-parent certificate.

    A parent environment may exist to hold this definition and its defaults.
    Only the incoming argument is unused; an environment allocated by the
    callee itself would still require its original parent link.
    """
    from .native_call_context_effects import source_plan, unused_parent
    original = source_plan(plan)
    if original is None:
        return False
    lexical = model.lexical
    return (lexical.scope(original) not in lexical.environments
            and (lexical.parent_scope(original) is None
                 or unused_parent(model, original)))


def publication(registry, plan, node):
    """Return the exact official binding for one closed creation event.

    Unknown metadata/application/destructor roles retain the checked path.
    In particular deferred annotations are never visited as eager expressions.
    The enclosing generation/lifetime certificate supplies no Python finalizer
    or frame/GC observer; this helper does not infer that seal from a result ABI.
    """
    if (not isinstance(node, ast.FunctionDef) or node.type_params
            or node.decorator_list
            or getattr(plan, 'class_body', None) is not None):
        return None
    model = registry.model
    ordinal = model.unit.node_ordinals.get(id(node))
    if ordinal is None:
        return None
    rows = [row for row in registry.rows if row.node == ordinal
            and row.role == 'definition']
    if len(rows) != 1:
        return None
    row = rows[0]
    from .native_call_context_effects import source_plan
    caller = source_plan(plan)
    if (caller is None or row.scope != model.lexical.scope(caller)
            or not 0 <= row.owner < len(model.unit.scopes)):
        return None
    # Resolve by the original statement, never by the latest same-name plan.
    try:
        targets = model.namespace.defined_plans(plan, node)
    except (KeyError, AttributeError):
        return None
    original_unit = model.unit.original_unit(node)
    definition_key = original_unit.name, original_unit.ordinal(node)
    from .native_function_instances import instanced
    annotated = (node.returns is not None or any(arg.annotation is not None for arg in
                 (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                  *(() if node.args.vararg is None else (node.args.vararg,)),
                  *(() if node.args.kwarg is None else (node.args.kwarg,)))))
    if annotated:
        # Python 3.14 retains these original expressions in lazy metadata; no
        # annotation expression runs at creation. Existing native metadata
        # consumers reject observing/changing __annotations__/__annotate__/
        # __type_params__, including finite callable alternatives. Retain an
        # explicit actual-definition observer guard here as well. The original
        # callable payload still carries its real defining environment.
        from .native_global_callable_payload import metadata_observed
        provider = getattr(model, 'callable_cells', None)
        if provider is None:
            return None
        observed = metadata_observed(model)
    if not targets:
        return None
    for target in targets:
        original = source_plan(target)
        if (original is None or original.node is not node
                or getattr(original, 'definition_key', None) != definition_key
                or instanced(model.lexical, original)):
            return None
        if annotated and provider.definition(original) in observed:
            return None
    return row


def binding_effect(registry, plan, node):
    """Definition publication writes a binding, not the function's body."""
    row = publication(registry, plan, node)
    if row is None:
        return set(registry.slots)
    # Linked module bindings already use their real qualified namespace keys.
    # A lexical rebinding does not mutate the heap previously held in that
    # binding; unknown owners above are not silently treated as local writes.
    return {row.name} & registry.slots.keys()


def transfer(registry, plan, node, incoming, mode):
    """Evaluate only eager definition operands in Python source order."""
    if node.type_params:
        # Generic default/annotation scopes need their own complete event ABI.
        return set()
    available = set(incoming)
    # Decorator expressions execute before defaults; application executes in
    # reverse order afterwards. No application role is certified here yet.
    for decorator in node.decorator_list:
        available = registry.expression(plan, decorator, available, mode)
    for value in (*node.args.defaults, *node.args.kw_defaults):
        if value is not None:
            available = registry.expression(plan, value, available, mode)
    return available - binding_effect(registry, plan, node)


def assertion_transfer(registry, plan, node, incoming, mode):
    """Keep only the assertion's successful source edge.

    Native assertion emission still performs the original test/truth check and
    conditional failure message. A failure-only message gets no optimization
    annotations in this increment; its writes never become success effects.
    """
    from .native_assertions import literal_truth
    available = registry.expression(plan, node.test, set(incoming), mode)
    # Builtin truth on closed data is nonmutating; source/unknown truth loses
    # witnesses. Result ABI or a scalar return type alone is not that proof.
    available = registry.after_truth(plan, node.test, available)
    bits = (0 if registry.model.integer == 'bigint'
            else 128 if registry.model.integer == 'i128' else 64)
    known = literal_truth(node.test, bits)
    if known is not True and node.msg is not None:
        # This expression is emitted only inside the existing failure branch.
        # Keep a separate mode so no message annotation or mutation is imported
        # into the normal state. Literal-true messages may have no Model facts.
        registry.expression(plan, node.msg, set(available), type(mode)())
    return set() if known is False else available
