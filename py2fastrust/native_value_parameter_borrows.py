"""Borrow closed value parameters used only for Copy scalar field loads.

The source proof uses official binding owners. A separate physical Rust ABI
pass preserves every original argument capture and only borrows the existing
actual argument at its final synchronous invocation.
"""
import ast


class Registry:
    def __init__(self, model):
        from .native_classes import InstanceType, shape
        from .native_class_calls import synchronous
        from .native_value_classes import selected, borrowed_self
        self.parameters = {}
        self.applied = {}
        self.reasons = {}
        if model.unit is None:
            return
        nodes = {model.unit.ordinal(node): node for node in model.iter_nodes()}
        parents = {id(child): node for node in model.iter_nodes() for child in ast.iter_child_nodes(node)}
        bindings = list(model.iter_bindings())
        for plan in model.plans:
            if not plan.reachable or not synchronous(model, plan):
                continue
            scope = model.lexical.scope(plan)
            declared = {binding.name: binding for binding in bindings
                        if binding.owner == scope and binding.scope == scope and binding.role == 'parameter'}
            for position, name in enumerate(plan.runtime_parameters):
                kind = shape(plan.arguments[name])
                if not isinstance(kind, InstanceType) or kind.name not in model.classes:
                    continue
                owner = model.classes[kind.name]
                if not selected(model, owner) or borrowed_self(model, plan, name, kind):
                    continue
                binding = declared.get(name)
                key = plan.index, position
                if binding is None:
                    self.reasons[key] = 'parameter has no exact official binding'
                    continue
                stored = model.namespace.local_kind(plan, name)
                if stored is not None and stored != kind:
                    self.reasons[key] = 'parameter shares a changing or alternative local schema'
                    continue
                uses = [value for value in bindings if value.owner == binding.owner
                        and value.name == binding.name and value is not binding]
                allowed = bool(uses)
                for use in uses:
                    node = nodes.get(use.node)
                    parent = parents.get(id(node))
                    if (use.scope != binding.owner or use.role != 'load'
                            or not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load)
                            or model.lexical.field_for(node) is not None
                            or model.namespace.owns(plan, node)
                            or not isinstance(parent, ast.Attribute) or parent.value is not node
                            or not isinstance(parent.ctx, ast.Load)
                            or model.resolved_name(plan, parent) not in owner.fields):
                        allowed = False
                        break
                    cell = model.records.get((plan.index, id(node)))
                    # This exact official parameter binding cannot change
                    # type: every use above is a field load and no store or
                    # capture is admitted. Unreached source branches need no
                    # fabricated expression record to inherit that invariant.
                    if cell is not None and shape(cell) != kind:
                        allowed = False
                        break
                if not allowed:
                    self.reasons[key] = 'parameter is rebound, captured, passed, returned, observed or used beyond a plain scalar field load'
                    continue
                self.parameters[key] = owner.index


def prepare(model):
    model.value_parameter_borrows = Registry(model)


def _split(tokens, pairs, opening, *, types):
    """Split a compiler-owned parameter/call group; unknown arities stay owned."""
    from .rust_pruning import _group_end
    closing = pairs[opening]
    spans = []
    first = opening + 1
    cursor = first
    while cursor < closing:
        text = tokens[cursor].text
        if text in {'(', '[', '{'}:
            cursor = pairs[cursor] + 1
            continue
        if text == '<' and (types or cursor >= 2 and
                            tokens[cursor-1].text == ':' and tokens[cursor-2].text == ':'):
            cursor = _group_end(tokens, cursor)
            continue
        if not types and text == '|':
            return None
        if text == ',':
            if first == cursor:
                return None
            spans.append((first, cursor))
            first = cursor + 1
        cursor += 1
    if first < closing:
        spans.append((first, closing))
    return spans


def apply(source, model, *, registry_name="value_parameter_borrows"):
    from .rust_pruning import _lex, _parse, _Unsupported
    registry = getattr(model, registry_name, None)
    if registry is None or not registry.parameters:
        return source
    registry.applied.clear()
    try:
        tokens, comments, pairs = _lex(source)
        items = _parse(source, tokens, comments, pairs)
        functions = {item.name: item for item in items if item.kind == 'fn'}
        token_positions = {token.start: i for i, token in enumerate(tokens)}
        nominal = {item.name for item in items if item.kind in {'struct', 'enum', 'type', 'union'}}
        dropping = set()
        for owner in set(registry.parameters.values()):
            aliases = {owner if isinstance(owner,str) else f'ClassHandle_{owner}'}
            while True:
                found = set(aliases)
                for item in items:
                    if item.kind != 'type':
                        continue
                    if item.name in aliases:
                        found.update(item.references & nominal)
                    if item.references & aliases:
                        found.add(item.name)
                if found == aliases:
                    break
                aliases = found
            if any(item.kind == 'impl' and item.trait and item.owner in aliases
                   and 'Drop' in item.references for item in items):
                dropping.add(owner)
        wanted = {}
        from .native_source_symbols import function_plans
        variants = {}
        for symbol, plan in function_plans(model).items():
            variants.setdefault(plan.index, []).append(symbol)
        for (plan, position), owner in registry.parameters.items():
            # Keep the existing standalone physical-pass contract: its
            # registry already certifies ordinary source function parameters.
            wanted.setdefault(f'class_function_{plan}', {})[f'class_argument_{position}'] = owner
            for symbol in variants.get(plan, ()):
                wanted.setdefault(symbol, {})[f'class_argument_{position}'] = owner
        definitions = {}
        for i, token in enumerate(tokens[:-1]):
            if token.text not in wanted or not i or tokens[i-1].text != 'fn':
                continue
            item = functions.get(token.text)
            if item is None or tokens[i+1].text != '(':
                continue
            first = token_positions.get(item.start)
            if first is None or any(part.text in {'async', 'const', 'unsafe', 'extern'}
                                    for part in tokens[first:i]):
                continue
            opening = i+1
            spans = _split(tokens, pairs, opening, types=True)
            cursor = pairs[opening]+1
            while cursor < len(tokens) and tokens[cursor].start < item.end and tokens[cursor].text != '{':
                cursor += 1
            if cursor >= len(tokens) or tokens[cursor].text != '{':
                continue
            body, end = cursor, pairs[cursor]
            if not spans or 'ClassResult' not in {part.text for part in tokens[pairs[opening]+1:body]}:
                continue
            if any(part.text in {'move', 'async'} for part in tokens[body+1:end]):
                continue
            candidates = {}
            for physical, (first, stop) in enumerate(spans):
                if tokens[first].text not in wanted[token.text]:
                    continue
                argument = tokens[first].text
                owner = wanted[token.text][argument]
                if owner in dropping:
                    continue
                handle = owner if isinstance(owner,str) else f'ClassHandle_{owner}'
                if [part.text for part in tokens[first:stop]] != [argument, ':', handle]:
                    continue
                occurrences = [j for j in range(body+1, end) if tokens[j].text == argument]
                if len(occurrences) != 1:
                    continue
                j = occurrences[0]
                if ([part.text for part in tokens[j-3:j]] != ['=', 'Some', '(']
                        or [part.text for part in tokens[j+1:j+3]] != [')', ';']):
                    continue
                slot = tokens[j-4].text
                declarations = [k for k in range(body+1, end-10)
                                if [part.text for part in tokens[k:k+11]] ==
                                ['let', 'mut', slot, ':', 'Option', '<', handle, '>', '=', 'None', ';']]
                if len(declarations) != 1:
                    continue
                candidates[physical] = (first+2, declarations[0]+6, argument)
            if candidates:
                definitions[token.text] = (len(spans), candidates)
        escaped = {token.text for i, token in enumerate(tokens[:-1])
                   if token.text in definitions and tokens[i+1].text != '('}
        calls = {name: [] for name in definitions if name not in escaped}
        invalid = set()
        for i, token in enumerate(tokens[:-1]):
            if token.text not in calls or tokens[i+1].text != '(' or i and tokens[i-1].text == 'fn':
                continue
            spans = _split(tokens, pairs, i+1, types=False)
            if spans is None or len(spans) != definitions[token.text][0]:
                invalid.add(token.text)
            else:
                calls[token.text].append(spans)
        edits = []
        for name, invocations in calls.items():
            if name in invalid or not invocations:
                continue
            candidates = definitions[name][1]
            for parameter, local, argument in candidates.values():
                edits.extend(((tokens[parameter].start, tokens[parameter].start, '&'),
                              (tokens[local].start, tokens[local].start, '&')))
            for spans in invocations:
                for position in candidates:
                    first, stop = spans[position]
                    edits.extend(((tokens[first].start, tokens[first].start, '&('),
                                  (tokens[stop].start, tokens[stop].start, ')')))
            registry.applied[name] = tuple(record[2] for record in candidates.values())
        for first, stop, replacement in sorted(edits, reverse=True):
            source = source[:first] + replacement + source[stop:]
        return source
    except _Unsupported:
        # This is an optimization capability guard; the original typed native
        # ABI and source behavior remain intact on an unknown Rust shape.
        return source
