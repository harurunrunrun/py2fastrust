"""Use plain shared metadata only after proving module execution is unique.

The safe owned-capable metadata layout is generated first. This late optional
specialization requires the complete finite-depth capability certificate,
original direct module import statements, and a closed loader API boundary.
"""
import ast


class Unproved(Exception):
    pass


def _identities(kind, seen=frozenset()):
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    from .native_types import ListType, TupleType, TupleSequenceType, DequeType, MaybeType, NullableType, UnionType
    if id(kind) in seen:
        return
    seen = seen | {id(kind)}
    if isinstance(kind, (BuiltinIdentity, BuiltinRef)):
        yield kind
    yield from getattr(kind, 'builtins', ())
    yield from getattr(kind, 'members', ())
    children = getattr(kind, '_native_owned_kinds', ())
    if isinstance(kind, (ListType, TupleSequenceType, DequeType)):
        children = (*children, kind.element)
    elif isinstance(kind, TupleType):
        children = (*children, *kind.fields)
    elif isinstance(kind, (MaybeType, NullableType)):
        children = (*children, kind.value)
    elif isinstance(kind, UnionType):
        children = (*children, *kind.alternatives)
    for child in children:
        yield from _identities(child, seen)


def _module_name(model, plan, node):
    from .native_classes import shape, domain
    from .native_module_linking import ModuleType
    cell = model.records.get((plan.index, id(node)))
    if cell is None:
        return None
    kind = shape(cell)
    if domain(kind) == 'sys':
        return 'sys'
    if isinstance(kind, ModuleType):
        module = model.module_linker.by_number[kind.number]
        if module.native_adapter or module.origin == 'stdlib':
            return module.name
    return None


def certify(model):
    from .native_classes import shape
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    depth = getattr(model, 'finite_depth_calls', {})
    if not depth.get('eligible'):
        raise Unproved('the complete closed finite-depth capability certificate is absent')
    linker = getattr(model, 'module_linker', None)
    if linker is None or model.unit is None:
        raise Unproved('retained linked module identities are absent')
    nodes = {id(node): node for node in model.iter_nodes()}
    plans = {plan.index: plan for plan in model.plans if plan.reachable}
    direct = 0
    for (caller, node_id), bindings in linker.imports.items():
        if caller not in plans:
            continue
        plan = plans[caller]
        node = nodes.get(node_id)
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            raise Unproved('a retained import is not an original fixed-name statement')
        original = model.unit.original_unit(node)
        if (not model.is_module_plan(plan) or plan.node is not original.tree
                or not any(statement is node for statement in original.tree.body)):
            raise Unproved('a reached import is inside a function, callback, class or control-flow region')
        direct += 1
    runtime_compilers = {'__import__', 'eval', 'exec', 'compile'}
    loader_modules = {'importlib', 'importlib.util', 'importlib.machinery', 'importlib._bootstrap',
                      'importlib._bootstrap_external', '_frozen_importlib', '_frozen_importlib_external', '_imp', 'imp'}
    identities = set(model.callable_cells.builtin_used) | set(model.callable_cells.member_used)
    for cell in model.records.values():
        identities.update(_identities(shape(cell)))
    for identity in identities:
        if isinstance(identity, BuiltinIdentity) and identity.name in runtime_compilers:
            raise Unproved('a canonical builtin importer or runtime compiler is retained')
        if isinstance(identity, BuiltinRef) and (
                identity.module in loader_modules
                or identity.module == 'builtins' and identity.name in runtime_compilers):
            raise Unproved('a canonical reload, loader, importer or runtime compiler adapter is retained')
    cache_fields = {'modules', 'meta_path', 'path', 'path_hooks', 'path_importer_cache'}
    for (caller, node_id), _ in model.records.items():
        if caller not in plans:
            continue
        node = nodes.get(node_id)
        if not isinstance(node, ast.Attribute):
            continue
        module = _module_name(model, plans[caller], node.value)
        if (module == 'builtins' and node.attr in runtime_compilers | {'__dict__'}
                or module == 'sys' and node.attr in cache_fields
                or module in loader_modules
                or module is not None and node.attr in {'__loader__', '__spec__'}):
            raise Unproved('a canonical import hook, module cache or loader namespace is observed')
    return dict(direct_original_import_sites=direct,
                finite_depth=depth['certified_depth'],
                module_initializers_source_callable=False,
                import_cache_contract='fixed-name class_import helpers cache before initialization and only remove a failed entry; no admitted loader/cache mutation API')


def apply(source, model):
    from .native_static_class_metadata import RUNTIME, once
    from .native_value_classes import selected
    info = {'eligible': False, 'specialized_owners': []}
    model.single_execution_metadata = info
    try:
        info.update(certify(model))
        for owner in model.classes.values():
            if not owner.used or not selected(model, owner) or not once(model, owner):
                continue
            runtime = RUNTIME.replace('__INDEX__', str(owner.index))
            # Source positions, caller argument evaluation and class reference
            # captures remain intact. Only this exact private metadata carrier
            # changes; unknown renderer shapes retain the safe carrier.
            if source.count(runtime) != 1:
                continue
            source = source.replace(runtime, PLAIN_RUNTIME.replace('__INDEX__', str(owner.index)), 1)
            info['specialized_owners'].append(owner.index)
        info['eligible'] = True
    except (Unproved, KeyError) as error:
        info['reason'] = str(error)
    return source


PLAIN_RUNTIME = r'''
#[derive(Clone)]
struct ClassValueMetadata___INDEX__(&'static ClassClassRef);
impl std::ops::Deref for ClassValueMetadata___INDEX__ {
 type Target=ClassClassRef;
 fn deref(&self)->&ClassClassRef {self.0}
}
impl ClassValueMetadata___INDEX__ {
 fn clone(&self)->ClassClassRef {Rc::clone(self.0)}
}
thread_local! {
 static CLASS_VALUE_METADATA___INDEX__:std::cell::OnceCell<&'static ClassClassRef>=std::cell::OnceCell::new();
}
fn class_value_metadata___INDEX__(value:&ClassClassRef)->ClassValueMetadata___INDEX__ {
 let pinned=CLASS_VALUE_METADATA___INDEX__.with(|slot|*slot.get_or_init(||Box::leak(Box::new(value.clone()))));
 ClassValueMetadata___INDEX__(pinned)
}
'''
