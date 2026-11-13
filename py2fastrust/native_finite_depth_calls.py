"""Elide logical depth counters only for sealed, bounded native call graphs.

All source calls and the exact exception-frame propagation remain. Unknown
source effects, control state, callbacks, suspension or physical call shapes
keep the ordinary typed native recursion guard.
"""
import ast
from collections import defaultdict, deque


MAX_CERTIFIED_DEPTH = 256


class Unproved(Exception):
    pass


def _guard_weight(tokens, pairs, opening, closing, source_symbols):
    """Bound simultaneously active literal guard invocations in one source body.

    Sequential calls do not retain the depth guard after returning. Unknown
    callback closures keep the original sum: they could invoke a closure whose
    guard was defined elsewhere in this body. Immediate closures and the
    guard's own literal closure cannot escape their canonical consumers.
    """
    calls = [i for i in range(opening + 1, closing)
             if tokens[i].text == 'class_sync_call' and tokens[i + 1].text == '(']
    total = len(calls)
    if total <= 1:
        return total
    bars = set()
    for i in calls:
        end = pairs[i + 1]
        # Skip the actual first argument, including all nested delimiters.
        cursor = i + 2
        while cursor < end and tokens[cursor].text != ',':
            cursor = pairs[cursor] + 1 if tokens[cursor].text in {'(', '[', '{'} else cursor + 1
        start = cursor + 1
        if [token.text for token in tokens[start:start + 2]] != ['|', '|']:
            return total
        bars.update((start, start + 1))
        cursor = start + 2
        if tokens[cursor].text == '{':
            cursor += 1
            # The iterator binder sometimes records whether the actual source
            # entry was reached before propagating StopIteration.
            while (tokens[cursor].kind == 'identifier'
                   and tokens[cursor + 1].text == '='
                   and tokens[cursor + 2].text in {'true', 'false'}
                   and tokens[cursor + 3].text == ';'):
                cursor += 4
        if tokens[cursor].text not in source_symbols or tokens[cursor + 1].text != '(':
            return total
    for i in range(opening + 1, closing):
        if tokens[i].text == 'fn':
            return total
        if tokens[i].text != '|' or i in bars:
            continue
        previous = tokens[i - 1].text
        if previous not in {'(', ',', '=', '{', ';', 'return', 'move'}:
            continue  # A binary operator or the closing parameter bar.
        if previous == '(' and pairs[i - 1] + 1 < closing:
            end = pairs[i - 1]
            if tokens[end + 1].text == '(':
                continue  # The complete closure is invoked immediately.
            if (i >= 3 and tokens[i - 2].text == 'ok_or_else'
                    and tokens[i - 3].text == '.'):
                continue  # Option's literal error closure is also immediate.
        return total
    events = []
    for i in calls:
        events.extend(((i, 1), (pairs[i + 1], -1)))
    active = maximum = 0
    for _, change in sorted(events):
        active += change
        maximum = max(maximum, active)
    return maximum


def _native_reader_call(model, plan, node, result):
    """Recognize the core Model's captured standard-stream call contract.

    These exact intrinsic Cells originate from typed stdin/read attributes.
    A spelling, output kind, descriptor domain or source callable alternative
    alone does not prove the nonreentrant zero-argument native operation.
    """
    if not isinstance(node.func, ast.Name) or node.args or node.keywords:
        return False
    cell = model.records.get((plan.index, id(node.func)))
    if cell is None:
        return False
    root = cell.root()
    tag = root.tag
    if type(tag) is not str or tag not in {'reader_text', 'reader_bytes', 'read_text', 'read_bytes'} or root.args:
        return False
    from .native_classes import shape, domain
    return (domain(shape(root)) == tag
            and shape(result) == ('bytes' if tag in {'reader_bytes', 'read_bytes'} else 'str'))


def _model_proof(model):
    from .native_classes import shape, domain, InstanceType
    from .native_class_calls import synchronous
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    from .native_module_linking import ClassReferenceType
    plans = {plan.index: plan for plan in model.plans if plan.reachable}
    if not plans or any(not synchronous(model, plan) for plan in plans.values()):
        raise Unproved('source graph is recursive, suspended or exceeds the synchronous chain proof')
    if getattr(model, 'gc_classes', ()) or any(owner.used and '__del__' in owner.methods for owner in model.classes.values()):
        raise Unproved('collection or a finalizer can reenter source calls')
    if getattr(getattr(model,'retained_generators',None),'records',None):
        raise Unproved('a retained generator expression keeps cursor/capture state outside ordinary call-frame lifetime proofs')
    if model.generators.records:
        raise Unproved('a generator can contribute suspended logical depth')
    if any(getattr(plan,'source_generator',None)is not None for plan in plans.values()):
        raise Unproved('a source generator retains suspension state outside ordinary call-frame lifetime proofs')
    heights = getattr(model, 'native_call_heights', {})
    if any(index not in heights for index in plans):
        raise Unproved('a reached source plan has no finite acyclic height')
    import_edges, native_imports = set(), set()
    linker = getattr(model, 'module_linker', None)
    if linker is not None:
        for (caller, node_id), bindings in linker.imports.items():
            if caller not in plans:
                continue
            expected = set()
            for binding in bindings:
                parts = binding.module.split('.')
                modules = [linker.modules['.'.join(parts[:i])] for i in range(1, len(parts)+1)]
                modules += [linker.modules[child] for child in binding.children
                            if binding.exported_name is not None and child.rpartition('.')[2] == binding.exported_name]
                for module in modules:
                    if module.initializer is None:
                        native_imports.add(module.number)
                    else:
                        expected.add(module.initializer.index)
            if not expected <= model.call_edges_by_site.get((caller, node_id), set()):
                raise Unproved('an import initializer is missing from the semantic call graph')
            if not expected <= plans.keys() or not expected <= model.call_edges.get(caller, set()):
                raise Unproved('an imported source frame lacks a reached acyclic graph edge')
            import_edges.update((caller, target) for target in expected)
    nodes = {id(node): node for node in model.iter_nodes()}
    observers = {'eval', 'exec', 'compile', 'globals', 'locals', 'vars', 'getattr', 'setattr', 'delattr'}
    def identities(kind, seen=frozenset()):
        if id(kind) in seen:
            return
        seen = seen | {id(kind)}
        for identity in (*getattr(kind, 'builtins', ()), *getattr(kind, 'members', ())):
            yield identity
        for child in getattr(kind, '_native_owned_kinds', ()):
            yield from identities(child, seen)
    for cell in model.records.values():
        for identity in identities(shape(cell)):
            if isinstance(identity, BuiltinIdentity) and identity.name in observers:
                raise Unproved('a reachable namespace or runtime compiler observer is retained')
            if isinstance(identity, BuiltinRef) and identity.module == 'builtins' and identity.name in observers:
                raise Unproved('a canonical builtin-module namespace or runtime compiler adapter is retained')
            if isinstance(identity, BuiltinRef) and identity.module == 'sys' and identity.name == 'setrecursionlimit':
                raise Unproved('a canonical recursion-limit setter or saved adapter is retained')
    for identity in model.callable_cells.member_used:
        if isinstance(identity, BuiltinRef) and identity.module == 'builtins' and identity.name in observers:
            raise Unproved('a saved builtin-module namespace or runtime compiler adapter is retained')
        if isinstance(identity, BuiltinRef) and identity.module == 'sys' and identity.name == 'setrecursionlimit':
            raise Unproved('a saved recursion-limit member adapter is retained')
    sealed = {'int', 'bool', 'int_bool', 'float', 'str', 'bytes', 'list', 'tuple', 'tuple_sequence',
              'deque', 'dict', 'set', 'defaultdict', 'Counter', 'OrderedDict', 'dict_view',
              'range', 'stdin', 'stdin_buffer', 'sys', 'iterator', 'cmp_key'}
    for (index, node_id), cell in model.records.items():
        node = nodes.get(node_id)
        if index not in plans or not isinstance(node, ast.Call):
            continue
        plan = plans[index]
        site = model.callable_cells.sites.get((index, node_id))
        if site is not None:
            if not any((site.targets, site.builtins, site.members, site.constructors, site.exception_constructors)):
                # Direct source constructors also leave a provisional callable
                # site. Their canonical constructor and initializer edge are
                # recorded by the class adapter, rather than that empty site.
                result = shape(cell)
                owner = model.classes.get(result.name) if isinstance(result, InstanceType) else None
                initializer = None if owner is None else owner.methods.get('__init__')
                edges = model.call_edges_by_site.get((index, node_id), ())
                if not (owner is not None and model.value_classes.constructor(plan, node, owner)
                        and (initializer is None or initializer.index in edges)):
                    raise Unproved('a reached invocation has no finite canonical callable targets')
            continue
        if model.call_edges_by_site.get((index, node_id)):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            identity = model.builtin_identity(plan, function, {})
            if isinstance(identity, BuiltinIdentity):
                if identity.name in observers:
                    raise Unproved('a namespace or runtime compiler observer is reached')
                continue
        kind_cell = model.records.get((index, id(function)))
        kind = None if kind_cell is None else shape(kind_cell)
        if _native_reader_call(model, plan, node, cell):
            continue
        if isinstance(kind, ClassReferenceType):
            continue
        result = shape(cell)
        if isinstance(result, InstanceType):
            owner = model.classes.get(result.name)
            if owner is not None and model.value_classes.constructor(plan, node, owner):
                continue
        if isinstance(function, ast.Attribute):
            receiver = model.records.get((index, id(function.value)))
            tag = None if receiver is None else domain(shape(receiver))
            if tag == 'sys' and function.attr == 'setrecursionlimit':
                raise Unproved('a direct canonical recursion-limit setter is reached')
            if isinstance(tag, str) and tag in sealed:
                continue
        raise Unproved('a reached call lacks a closed source or sealed builtin identity')
    return dict(source_plans=len(plans), max_source_height=max(heights[index] for index in plans),
                certified_import_edges=len(import_edges), terminal_native_imports=len(native_imports))


def _body(tokens, pairs, first, end):
    opening = next((i for i in range(first, len(tokens)) if tokens[i].start < end and tokens[i].text == '{'), None)
    if opening is None:
        raise Unproved('a physical function has no recognized body')
    return opening, pairs[opening]


def _components(edges):
    """Iterative SCC traversal avoids using the host's recursion limit."""
    seen, order = set(), []
    for start in edges:
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                order.append(node)
                continue
            if node in seen:
                continue
            seen.add(node)
            stack.append((node, True))
            stack.extend((child, False) for child in edges[node] if child not in seen)
    reverse = {node: set() for node in edges}
    for node, children in edges.items():
        for child in children:
            reverse[child].add(node)
    membership, groups = {}, []
    for start in reversed(order):
        if start in membership:
            continue
        component = len(groups)
        group, stack = [], [start]
        membership[start] = component
        while stack:
            node = stack.pop()
            group.append(node)
            for child in reverse[node]:
                if child not in membership:
                    membership[child] = component
                    stack.append(child)
        groups.append(group)
    return membership, groups


def _weighted_bounds(edges, weights):
    membership, groups = _components(edges)
    component_weights, children = {}, {}
    for index, group in enumerate(groups):
        weight = sum(weights[node] for node in group)
        if weight and (len(group) > 1 or any(node in edges[node] for node in group)):
            raise Unproved('a physical recursion component can retain a positive depth counter')
        component_weights[index] = weight
        children[index] = {membership[child] for node in group for child in edges[node] if membership[child] != index}
    parents = defaultdict(set)
    for parent, targets in children.items():
        for child in targets:
            parents[child].add(parent)
    remaining = {index: len(targets) for index, targets in children.items()}
    ready = deque(index for index, count in remaining.items() if not count)
    bounds = {}
    while ready:
        index = ready.popleft()
        bounds[index] = component_weights[index] + max((bounds[child] for child in children[index]), default=0)
        for parent in parents[index]:
            remaining[parent] -= 1
            if not remaining[parent]:
                ready.append(parent)
    return ({node: bounds[membership[node]] for node in edges},
            sum(not value for value in component_weights.values()))


def apply(source, model):
    from .rust_pruning import _lex, _parse, _Unsupported
    info = {'eligible': False}
    model.finite_depth_calls = info
    try:
        info.update(_model_proof(model))
        tokens, comments, pairs = _lex(source)
        items = _parse(source, tokens, comments, pairs)
        positions = {token.start: i for i, token in enumerate(tokens)}
        if any(token.text in {'async', 'ClassFuture', 'ClassTask', 'ClassCall', 'generator_depth', 'class_generator_enter'} for token in tokens):
            raise Unproved('a suspended or generator depth runtime is retained')
        functions = [item for item in items if item.kind == 'fn']
        functions += [child for item in items if item.kind == 'impl' and not item.trait
                      for child in item.children if child.kind == 'fn']
        guard = next((item for item in functions if item.name == 'class_sync_call'), None)
        if guard is None:
            raise Unproved('the canonical synchronous guard is absent')
        body, ending = _body(tokens, pairs, positions[guard.start], guard.end)
        if tokens[body+1].text != '{':
            raise Unproved('the synchronous guard prefix changed')
        check, check_end = body+1, pairs[body+1]
        condition = next(i for i in range(check+1, check_end) if tokens[i].text == 'if')
        condition_body = next(i for i in range(condition+1, check_end) if tokens[i].text == '{')
        texts = lambda first, stop: [token.text for token in tokens[first:stop]]
        if texts(check+1, condition) != ['let', 'mut', 'control', '=', 'scope', '.', 'control', '.', 'borrow_mut', '(', ')', ';']:
            raise Unproved('the synchronous guard has an unknown counter acquisition')
        if texts(condition, condition_body) != ['if', 'control', '.', 'depth', '>', '=', 'control', '.', 'limit']:
            raise Unproved('the synchronous guard has an unknown limit condition')
        if texts(pairs[condition_body]+1, check_end) != ['control', '.', 'depth', '+', '=', '1', ';']:
            raise Unproved('the synchronous guard has an unknown depth increment')
        after = check_end+1
        if texts(after, after+8) != ['let', '_depth', '=', 'ClassSyncDepth', '(', 'scope', ')', ';']:
            raise Unproved('the synchronous guard has an unknown cleanup capability')
        keep = after+8
        if texts(keep, keep+5) != ['call', '(', ')', '.', 'map_err']:
            raise Unproved('the synchronous exception-frame propagation changed')
        # Both fields are sealed: one default control constructor, one root
        # activation, the exact existing guard, and canonical limit getters.
        initializers = 0
        depth_cleanup = [item for item in items if item.kind == 'impl' and item.owner == 'ClassSyncDepth']
        if len(depth_cleanup) != 1:
            raise Unproved('the depth cleanup implementation is not unique')
        cleanup = depth_cleanup[0]
        cleanup_text = texts(positions[cleanup.start], next(i for i in range(positions[cleanup.start], len(tokens)) if tokens[i].start >= cleanup.end))
        canonical_cleanup = "impl Drop for ClassSyncDepth<'_>{fn drop(&mut self){self.0.control.borrow_mut().depth-=1;}}"
        if cleanup_text != [token.text for token in _lex(canonical_cleanup)[0]]:
            raise Unproved('the depth destructor has unknown effects')
        main = next((item for item in functions if item.name == 'main'), None)
        for i, token in enumerate(tokens):
            if token.text == 'ClassControl' and i+1 < len(tokens) and tokens[i+1].text == '{' and (not i or tokens[i-1].text != 'struct'):
                if texts(i+2, pairs[i+1]) != ['depth', ':', '0', ',', 'limit', ':', '1000']:
                    raise Unproved('a control object does not start at the default limit')
                initializers += 1
            if i == 0 or tokens[i-1].text != '.' or token.text not in {'depth', 'limit'}:
                continue
            if guard.start <= token.start < guard.end or cleanup.start <= token.start < cleanup.end:
                continue
            if token.text == 'depth' and main is not None and main.start <= token.start < main.end:
                if texts(i-8, i+4) == ['scope', '.', 'control', '.', 'borrow_mut', '(', ')', '.', 'depth', '=', '1', ';']:
                    continue
            if token.text == 'limit' and texts(i-10, i+2) == ['class_from_usize', '(', 'class_scope', '.', 'control', '.', 'borrow', '(', ')', '.', 'limit', ')']:
                continue
            raise Unproved('control depth or limit has a noncanonical observer or setter')
        if initializers != 1:
            raise Unproved('the default control constructor is not unique')
        by_name = defaultdict(set)
        bodies = {}
        for item in functions:
            key = item.start
            by_name[item.name].add(key)
            bodies[key] = (item, *_body(tokens, pairs, positions[item.start], item.end))
        from .native_source_symbols import function_plans, constructor_names
        source_plans = function_plans(model)
        constructors = constructor_names(model)
        source_symbols = set(source_plans) | constructors
        for name in by_name:
            if (name.startswith(('class_function_', 'class_state_function_', 'class_state_enter_'))
                    and name not in source_plans):
                raise Unproved('a physical source activation has no registered solved plan')
            if (name.startswith(('class_construct_', 'class_state_construct_'))
                    and name not in constructors):
                raise Unproved('a physical constructor has no registered source owner')
        for i, token in enumerate(tokens[:-1]):
            if token.text in source_symbols and tokens[i+1].text != '(':
                raise Unproved('a physical source-function address escapes the closed call graph')
        edges, weights = {}, {}
        sequential_guard_reductions = 0
        for key, (item, opening, closing) in bodies.items():
            edges[key], weights[key] = set(), 0
            if item is guard:
                continue
            for i in range(opening+1, closing):
                if tokens[i+1].text != '(':
                    continue
                name = tokens[i].text
                if name == 'class_sync_call':
                    weights[key] += 1
                else:
                    edges[key].update(by_name.get(name, ()))
            if item.name in source_symbols:
                weight = _guard_weight(tokens, pairs, opening, closing, source_symbols)
                sequential_guard_reductions += weights[key] - weight
                weights[key] = weight
        bounds, zero_components = _weighted_bounds(edges, weights)
        named_path_bound = 1 + max(bounds.values(), default=0)
        # A generic Rust helper can invoke a closure supplied by its caller:
        # its guard and that closure's source target occur on separate named
        # edges. Do not mistake the named longest path for a complete bound.
        # Cut entry edges to every source activation and bound only the
        # remaining synthetic span. Source/import heights above certify how
        # many such spans may be simultaneously active. The extra activation
        # covers terminal constructors and native adapter import frames.
        source_entries = {key for key, (item, _, _) in bodies.items()
                          if item.name in source_plans}
        ranks = {}
        for key in source_entries:
            plan = source_plans[bodies[key][0].name]
            if plan.index not in model.native_call_heights:
                raise Unproved('a physical source activation lacks an exact semantic rank')
            ranks[key] = model.native_call_heights[plan.index]
        transitions = set()
        for caller in source_entries:
            pending, visited = list(edges[caller]), set()
            while pending:
                target = pending.pop()
                if target in visited:
                    continue
                visited.add(target)
                if target in source_entries:
                    if ranks[target] >= ranks[caller]:
                        raise Unproved('a physical source transition does not decrease its certified semantic rank')
                    transitions.add((caller, target))
                else:
                    pending.extend(edges[target])
        cut_edges = {key: targets - source_entries for key, targets in edges.items()}
        cut_bounds, _ = _weighted_bounds(cut_edges, weights)
        synthetic_span = max(cut_bounds.values(), default=0)
        guard_sites = sum(weights.values())
        physical_bound = max(named_path_bound,
                             1 + (info['max_source_height'] + 1) * synthetic_span)
        if physical_bound >= MAX_CERTIFIED_DEPTH:
            raise Unproved('the certified physical depth is not well below the default limit')
        source_reaching = set(source_entries)
        reverse = defaultdict(set)
        for caller, targets in edges.items():
            for target in targets:
                reverse[target].add(caller)
        pending = list(source_entries)
        while pending:
            for caller in reverse[pending.pop()]:
                if caller not in source_reaching:
                    source_reaching.add(caller)
                    pending.append(caller)
        # Trait/default/other opaque bodies must not hide a source call. Their
        # ordinary scalar operations and zero-counter helpers need no roots.
        for item in items:
            if item.kind not in {'impl', 'trait'} or item.kind == 'impl' and not item.trait:
                continue
            first = positions[item.start]
            stop = next((i for i in range(first, len(tokens)) if tokens[i].start >= item.end), len(tokens))
            for i in range(first, stop-1):
                if tokens[i+1].text != '(':
                    continue
                name = tokens[i].text
                if name == 'class_sync_call' or any(key in source_reaching or bounds[key]
                                                   for key in by_name.get(name, ())):
                    raise Unproved('an opaque trait body can hide a guarded source callback')
        info.update(eligible=True, certified_depth=physical_bound, named_path_depth=named_path_bound,
                    synthetic_span=synthetic_span, guard_sites=guard_sites,
                    certified_source_transitions=len(transitions),
                    rust_functions=len(functions), zero_weight_components=zero_components,
                    sequential_guard_reductions=sequential_guard_reductions)
        # Preserve the complete existing call/error-frame expression byte for
        # byte, including exception identity and context synchronization.
        return source[:tokens[body].end] + '\n' + source[tokens[keep].start:]
    except (Unproved, _Unsupported, StopIteration, KeyError, IndexError) as error:
        info['reason'] = str(error) or type(error).__name__
        return source
