"""A real class anchor can certify completion of a declaration-only module."""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Publication:
    unit: object
    anchor: object
    target: object
    declarations: tuple


def declarations(state, unit):
    from .native_source_class_bindings import builtin_value, publication_closed
    owners = {id(owner.node): owner for owner in state.model.classes.values()}
    result = []
    for node in unit.tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            if (not all(isinstance(target, ast.Name) for target in targets)
                    or node.value is not None and not builtin_value(node.value)):
                return None
            continue
        if isinstance(node, ast.FunctionDef):
            defaults = (*node.args.defaults, *(value for value in node.args.kw_defaults if value is not None))
            if node.decorator_list or node.type_params or not all(builtin_value(value) for value in defaults):
                return None
            result.append(state.model.unit.ordinal(node))
            continue
        if isinstance(node, ast.ClassDef):
            owner = owners.get(id(node))
            if owner is None or not publication_closed(state, owner):
                return None
            result.append(state.model.unit.ordinal(node))
            continue
        # No source call, control region, descriptor/default callback or
        # namespace escape is permitted before the remaining declarations.
        return None
    return tuple(result)


def certify(model, caller, target):
    state = getattr(model, 'source_state', None)
    if state is None or state.model is not model or state.barrier is not None:
        return None
    from .native_class_binding_contexts import owner
    anchor = owner(model, caller)
    if anchor is None or not state.class_root(anchor):
        return None
    unit = model.unit.original_unit(anchor.node)
    if (model.unit.original_unit(target.node) is not unit
            or target.module_name != anchor.module_name):
        return None
    from .native_single_execution_metadata import _identities
    from .native_classes import shape
    from .native_module_calls import BuiltinRef
    from .references import BuiltinIdentity
    observers = {'globals','locals','vars','setattr','delattr','eval','exec','compile','__import__'}
    for cell in model.records.values():
        for identity in _identities(shape(cell)):
            if isinstance(identity, BuiltinIdentity) and identity.name in observers:
                return None
            if isinstance(identity, BuiltinRef) and (
                    identity.module == 'builtins' and identity.name in observers
                    or identity.module == 'sys' and identity.name in {'settrace','setprofile','call_tracing'}):
                return None
    declared = declarations(state, unit)
    if declared is None or model.unit.ordinal(target.node) not in declared:
        return None
    # The state generation certificate excludes import cycles, retries and
    # loader/cache observers. With no eager publication callback, this actual
    # class anchor cannot reach a source method before module initialization
    # returns. The binding-place certificate separately seals the target's
    # unique original definition and every later binding write.
    return Publication(unit, anchor, target, declared)
