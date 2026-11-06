"""Original source points covered by the existing native emission control view.

Missing value records are never evidence of an absent effect. Exclusions use
only the same reached-statement and canonical type-guard branch certificates
that native statement emission consumes, within the existing lexical owner.
"""
import ast


def statement_reached(model, plan, node):
    reached = getattr(model, 'reached_statements', None)
    return reached is None or (plan.index, id(node)) in reached


def _classinfo_closed(model, plan, node, class_root):
    if isinstance(node, ast.Tuple):
        return all(_classinfo_closed(model, plan, child, class_root) for child in node.elts)
    from .native_classes import shape
    from .native_module_linking import ClassReferenceType
    from .native_aot_callables import function_kind
    from .native_type_checks import TYPE_NAMES
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    cell = model.records.get((plan.index, id(node)))
    kind = None if cell is None else shape(cell)
    if isinstance(kind, ClassReferenceType):
        if class_root is None:
            return False
        owner = getattr(getattr(model, 'class_namespaces', None), 'owners', {}).get(kind.definition)
        return owner is not None and class_root(owner)
    if function_kind(kind):
        return bool(kind.targets) and all(
            (isinstance(target, BuiltinIdentity)
             or isinstance(target, BuiltinRef) and target.module == 'builtins')
            and target.name in TYPE_NAMES for target in kind.targets)
    # The original strict static binding proof can close a canonical builtin
    # whose value record is absent; a Name spelling alone cannot do so.
    from .native_physical_list_builtins import static_builtin
    return (isinstance(node, ast.Name) and node.id in TYPE_NAMES
            and static_builtin(model, plan, node, node.id))


def _predicate_closed(model, plan, node):
    """A cached branch mask does not establish the current callable value."""
    from .native_classes import shape
    from .references import BuiltinIdentity
    provider = getattr(model, 'callable_cells', None)
    site = getattr(provider, 'sites', {}).get((plan.index, id(node)))
    if site is not None:
        if getattr(shape(site.callee), 'targets', ()) != (BuiltinIdentity('isinstance'),):
            return False
    else:
        from .native_physical_list_builtins import static_builtin
        if not static_builtin(model, plan, node.func, 'isinstance'):
            return False
    # isinstance may read an object's apparent __class__. A source override
    # is not a primitive type test merely because its final result is bool.
    from .native_source_native_effects import _instance_value
    subject = model.records.get((plan.index, id(node.args[0])))
    kind = None if subject is None else shape(subject)
    if subject is None or not _instance_value(model, kind):
        return False
    from .native_classes import InstanceType
    from .native_types import alternatives
    for part in alternatives(kind):
        if isinstance(part, InstanceType):
            owner = model.classes[part.name]
            members = getattr(getattr(model, 'class_namespaces', None), 'members', {})
            if ('__class__' in owner.methods or '__class__' in getattr(owner, 'fields', {})
                    or (getattr(owner, 'index', None), '__class__') in members):
                return False
    return True


def control_closed(model, plan, raw, class_root=None):
    """Do not consume semantic class-index masks without actual generations."""
    guards = getattr(model, 'type_guard_branches', {})
    for node in raw:
        if not isinstance(node, ast.If) or (plan.index, id(node.test)) not in guards:
            continue
        masks = guards[plan.index, id(node.test)]
        if (not isinstance(masks, tuple) or len(masks) != 2
                or not all(type(value) is bool for value in masks)):
            return False
        test = node.test.operand if isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not) else node.test
        if (not isinstance(test, ast.Call) or len(test.args) != 2 or test.keywords
                or not isinstance(test.args[0], ast.Name)
                or not _predicate_closed(model, plan, test)
                or not _classinfo_closed(model, plan, test.args[1], class_root)):
            return False
    return True


def owned_points(model, plan, raw, executable=None, *, class_root=None):
    """Refine the existing own_nodes execution view without changing the AST."""
    raw_ids = {id(node) for node in raw}
    closed = control_closed(model, plan, raw, class_root)
    executable = ({id(node) for node in model.iter_nodes()}
                  if executable is None else executable)
    body = plan.node.body
    pending = list(reversed(body if isinstance(body, list) else [body]))
    while pending:
        node = pending.pop()
        if id(node) not in raw_ids or id(node) not in executable:
            continue
        if closed and isinstance(node, ast.stmt) and not statement_reached(model, plan, node):
            continue
        yield node
        # Keep the original owner boundary, including eager creation operands.
        # Function bodies and deferred annotations belong to their own view.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            children = [*node.decorator_list, *node.args.defaults,
                        *[value for value in node.args.kw_defaults if value is not None]]
        elif isinstance(node, ast.ClassDef):
            children = [*node.decorator_list, *node.bases,
                        *[keyword.value for keyword in node.keywords]]
        elif isinstance(node, ast.Lambda) and node is not plan.node:
            children = [*node.args.defaults,
                        *[value for value in node.args.kw_defaults if value is not None]]
        elif isinstance(node, ast.If):
            masks = getattr(model, 'type_guard_branches', {}).get((plan.index, id(node.test)))
            if (closed and isinstance(masks, tuple) and len(masks) == 2
                    and all(type(value) is bool for value in masks) and not all(masks)):
                # native_guard_flow.emit retains the evaluated test, then
                # emits only this original branch through statements().
                children = [node.test, *(node.body if masks[0] else node.orelse)]
            else:
                children = list(ast.iter_child_nodes(node))
        else:
            children = list(ast.iter_child_nodes(node))
        pending.extend(reversed(children))


def excluded_binding(ordinal, raw_owned, owned):
    """An unknown binding producer is distinct from a proved excluded point."""
    return ordinal in raw_owned and ordinal not in owned
