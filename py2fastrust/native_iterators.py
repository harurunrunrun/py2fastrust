"""Typed, immediately consumed Python iterators lowered to ordinary Rust loops.

Iterator construction and iteration have separate code so generator arguments
can construct their outer iterator before later call arguments, while plain
containers defer iteration until all arguments have been evaluated.
"""

import ast
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from .native import _Binding, _DequeInfo, _Expression, _MaybeInfo, _Unsupported, _string


_REDUCTIONS = {"sum", "any", "all", "min", "max"}
_TYPES = {"int": "NativeInt", "bool": "bool", "int_bool": "NativeScalar",
          "float": "f64", "str": "String", "bytes": "Vec<u8>", "list_int": "Vec<NativeInt>"}


@contextmanager
def _scope(generator, name, trace_id=None):
    previous_trace = generator.expression_trace_id
    generator.expression_scopes.append(name)
    generator.expression_trace_id = trace_id
    try:
        yield
    finally:
        generator.expression_scopes.pop()
        generator.expression_trace_id = previous_trace


@dataclass(frozen=True)
class DeferredScope:
    scope_code: str
    line_code: str


@dataclass(frozen=True)
class TraceContext:
    name: object
    trace_id: str | None = None


def _context(value):
    return value if isinstance(value, TraceContext) else TraceContext(value)


def _scope_code(value):
    return value.scope_code if isinstance(value, DeferredScope) else _string(value)


def _deferred_prefix(scope, trace_id, caller, line):
    caller = _context(caller)
    trace = f"{caller.trace_id}(error)" if caller.trace_id is not None else "error"
    return (f"let {scope.scope_code}: &'static str = {_scope_code(caller.name)};\n"
            f"let {scope.line_code}: usize = {line};\n"
            f"let {trace_id} = |error: NativeError| {trace};\n")


def _owned(generator, value, kind):
    if value.kind == kind and value.owned:
        return value.code
    if kind == "int_bool" and value.owned and value.kind in {"int", "bool"}:
        return f"NativeScalar::{'Int' if value.kind == 'int' else 'Bool'}({value.code})"
    return generator.coerce(value, kind)


@dataclass
class Stream:
    setup: str
    begin: str
    values: tuple[_Expression, ...]
    owners: frozenset[str]
    emit_body: Callable[..., str]
    eager: bool = False
    tupled: bool = False
    iterator: str | None = None
    fields: tuple | None = None
    length: int | None = None
    nonempty: bool = False
    reversible: bool = True

    def construct(self):
        return self.setup + "\n" + self.begin

    def emit(self, action, caller_scope, line, continue_label=None):
        return self.emit_body(action, caller_scope, line, continue_label)


class Planner:
    def __init__(self, generator, snapshot_strings=()):
        self.g = generator
        self.snapshot_strings = frozenset(snapshot_strings)

    def leaf(self, setup, begin, iterator, fields, owners=(), eager=False, tupled=False,
             length=None, nonempty=False):
        """Build one loop; fields describe borrowed or owning iterator items."""
        g = self.g
        item = g.temporary()
        names = [g.temporary() for _ in fields]
        values = tuple(_Expression(name, kind, owned=kind != "list_int" or owned)
                       for name, (kind, _, owned) in zip(names, fields))
        assignments = []
        for name, (kind, raw, owned) in zip(names, fields):
            code = raw.replace("@", item)
            if not owned and kind != "list_int":
                code = g.coerce(_Expression(code, kind), kind)
            assignments.append(f"let {name} = {code};")
        prefix = "\n".join(assignments)

        def emit(action, _scope, _line, continue_label=None):
            label = f"'{continue_label}: " if continue_label else ""
            return f"{label}for {item} in {iterator} {{\n{prefix}\n{action}\n}}"

        return Stream(setup, begin, values, frozenset(owners), emit, eager, tupled,
                      iterator, tuple(fields), length, nonempty or length is not None and length > 0)

    def stream(self, node, environment, *, allow_set=False):
        g = self.g
        if isinstance(node, ast.GeneratorExp):
            return self.generator(node, environment)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "range":
                setup, iterator, arguments = g.range_iterator(node, environment)
                length = None
                if all(argument.constant is not None for argument in arguments):
                    start, stop, step = (int(argument.constant) for argument in arguments)
                    if step > 0:
                        length = max(0, (stop-start+step-1)//step)
                    elif step < 0:
                        length = max(0, (start-stop-step-1)//-step)
                owner, cursor = g.temporary(), g.temporary()
                # NativeRange::new validates zero steps here, before later
                # reduction arguments, just as constructing range() does.
                setup += f"\nlet {owner} = {iterator};"
                result = self.leaf(setup, f"let {cursor} = {owner};", cursor,
                                   (("int", "@", True),), length=length)
                result.reversible = g.bits != 0 and arguments[2].constant in {1, -1}
                return result
            if node.func.id == "map":
                return self.map_stream(node, environment)
            if node.func.id == "filter":
                return self.filter_stream(node, environment)
            if node.func.id == "enumerate":
                return self.enumerate_stream(node, environment)
            if node.func.id == "zip":
                return self.zip_stream(node, environment)
            if node.func.id == "reversed":
                return self.reverse_stream(node, environment)
        if g.input_words(node,environment):
            g.has_input = g.needs_integer_runtime = True
            text, cursor = g.temporary(), g.temporary()
            setup = f"let {text} = {g.at('native_input.line(&mut native_output)', node)}.to_owned();"
            begin = f"let {cursor} = {text}.split(native_space).filter(|word| !word.is_empty());"
            return self.leaf(setup, begin, cursor, (("str", "@.to_owned()", True),))
        if isinstance(node, (ast.List, ast.Tuple)):
            values = [g.expression(value, environment) for value in node.elts]
            kind = ("list_int" if values and all(value.kind == "list_int" and value.owned for value in values)
                    else g.scalar_kind(values) if values else "int")
            owner, cursor = g.temporary(), g.temporary()
            code = ", ".join(_owned(g, value, kind) for value in values)
            setup = f"let {owner}: [{_TYPES[kind]}; {len(values)}] = [{code}];"
            return self.leaf(setup, f"let {cursor} = {owner}.into_iter();", cursor,
                             ((kind, "@", True),), length=len(values))
        view = g.dict_view(node, environment)
        value = view[0] if view else g.expression(node, environment)
        if value.kind == "str":
            owner, cursor = g.temporary(), g.temporary()
            named = (isinstance(node, ast.Name) and isinstance(environment.get(node.id), _Binding)
                     and environment[node.id].kind == "str")
            if named and node.id not in self.snapshot_strings:
                owner, setup = environment[node.id].slot, ""
            elif named:
                setup = f"let {owner} = {environment[node.id].slot}.clone();"
            else:
                value = g.read_expression(node, environment) if hasattr(g, "read_expression") else value
                setup = f"let {owner} = {value.code};"
            length = len(node.value) if isinstance(node, ast.Constant) and type(node.value) is str else None
            begin = f"let {cursor} = {owner}.chars();"
            return self.leaf(setup, begin, cursor, (("str", "@.to_string()", True),),
                             {node.id} if named and node.id not in self.snapshot_strings else (), length=length)
        if value.kind not in {"list_int", "matrix_int", "dict_int", "deque_int", "set_int"}:
            raise _Unsupported
        if value.kind == "set_int" and not allow_set:
            # A mapped/filtering consumer can observe set traversal order.
            raise _Unsupported
        receiver = view[2] if view else node
        owners = ({receiver.id} if isinstance(receiver, ast.Name) else
                  {receiver.value.id} if isinstance(receiver, ast.Subscript)
                  and isinstance(receiver.value, ast.Name) else set())
        cursor = g.temporary()
        if value.owned:
            owner = g.temporary()
            setup = f"let {owner} = {value.code};"
        elif isinstance(receiver, ast.Name):
            # Reading a proved name has no effects; defer the Rust borrow so
            # sum(q, q.popleft()) can evaluate its start before iter(q).
            owner, setup = value.code, ""
        else:
            owner = g.temporary()
            setup = f"let {owner} = {value.code};"
        if value.kind == "dict_int":
            begin = f"let {cursor} = {owner}.entries.iter();"
            mode = view[1] if view else "keys"
            fields = (("int", "@.0", False), ("int", "@.1", False)) if mode == "items" else (
                ("int", "@.1" if mode == "values" else "@.0", False),)
        else:
            begin = f"let {cursor} = {owner}.iter();"
            fields = (("list_int", "@", False),) if value.kind == "matrix_int" else (("int", "*@", False),)
        return self.leaf(setup, begin, cursor, fields, owners,
                         tupled=bool(view and view[1] == "items"), length=value.length,
                         nonempty=value.nonempty)

    def bind_target(self, target, stream, environment):
        values = stream.values
        if isinstance(target, ast.Name):
            if stream.tupled or len(values) != 1:
                raise _Unsupported
            targets = [target]
        elif (stream.tupled and isinstance(target, (ast.Tuple, ast.List))
              and len(target.elts) == len(values)):
            targets = target.elts
        else:
            raise _Unsupported
        if not all(isinstance(target, ast.Name) for target in targets):
            raise _Unsupported
        inside = environment.copy()
        for target, value in zip(targets, values):
            inside[target.id] = _Binding(value.code, self.g.binding(value))
        return inside

    def generator(self, node, environment):
        g = self.g
        g.has_iterator_frames = True
        trace_id = g.temporary()
        if not node.generators or any(clause.is_async for clause in node.generators):
            raise _Unsupported
        clauses = []
        owners = set()
        # Only the first iterable is evaluated in the containing scope.
        first = self.stream(node.generators[0].iter, environment)
        inside = self.bind_target(node.generators[0].target, first, environment)
        owners.update(first.owners)
        mutation_start = len(g.expression_mutations)
        with _scope(g, "<genexpr>", trace_id):
            guard_depth = len(g.iterating_lists)
            g.iterating_lists.extend(first.owners)
            try:
                filters = [g.expression(test, inside) for test in node.generators[0].ifs]
                clauses.append((first, filters))
                for clause in node.generators[1:]:
                    stream = self.stream(clause.iter, inside)
                    inside = self.bind_target(clause.target, stream, inside)
                    owners.update(stream.owners)
                    g.iterating_lists.extend(stream.owners)
                    filters = [g.expression(test, inside) for test in clause.ifs]
                    clauses.append((stream, filters))
                elements = node.elt.elts if isinstance(node.elt, ast.Tuple) else [node.elt]
                values = [g.expression(element, inside) for element in elements]
            finally:
                # Preserve guards installed by enclosing iterator plans.
                del g.iterating_lists[guard_depth:]
        if first.length != 0:
            # Deferred expressions may mutate a separately named deque. Their
            # execution is conditional, so invalidate cardinality instead of
            # pretending every syntactic pop necessarily executes.
            changed = {id(binding) for binding in g.expression_mutations[mutation_start:]}
            for name, binding in list(environment.items()):
                if id(binding) in changed and isinstance(binding.info, _DequeInfo):
                    g.update_info(environment, name, _DequeInfo(None))
        names = [g.temporary() for _ in values]
        output = tuple(_Expression(name, value.kind, owned=value.owned,
                                   length=value.length, nonempty=value.nonempty)
                       for name, value in zip(names, values))
        yielded = "\n".join(f"let {name} = {value.code};" for name, value in zip(names, values))

        def emit(action, caller_scope, line, continue_label=None):
            caller = _context(caller_scope)
            body = yielded + "\n" + action
            for index in reversed(range(len(clauses))):
                stream, filters = clauses[index]
                for test in reversed(filters):
                    body = f"if {g.truth(test)} {{\n{body}\n}}"
                body = stream.emit(body, TraceContext("<genexpr>", trace_id), node.elt.lineno,
                                   continue_label if index == len(clauses)-1 else None)
                if index:
                    body = stream.construct() + "\n" + body
            # Only producer operations use this context. A consumer callback
            # runs after the producer has yielded and keeps its own context.
            parent = f"{caller.trace_id}(error)" if caller.trace_id is not None else "error"
            prefix = (f"let {trace_id} = |mut error: NativeError| {{ "
                      f"error.frames.push(({line}, {_scope_code(caller.name)})); {parent} }};\n")
            return prefix + body

        length = 1
        for stream, filters in clauses:
            if filters or stream.length is None:
                length = None
                break
            length *= stream.length
        return Stream(first.construct(), "", output, frozenset(owners), emit, True,
                      isinstance(node.elt, ast.Tuple), length=length)

    def map_stream(self, node, environment):
        if len(node.args) != 2 or node.keywords or not isinstance(node.args[0], ast.Name):
            raise _Unsupported
        g = self.g
        source = self.stream(node.args[1], environment)
        if source.tupled or len(source.values) != 1:
            raise _Unsupported
        argument = "\0iterator_" + g.temporary()
        inside = environment.copy()
        inside[argument] = _Binding(source.values[0].code, g.binding(source.values[0]))
        call = ast.copy_location(ast.Call(func=node.args[0], args=[ast.Name(id=argument, ctx=ast.Load())], keywords=[]), node)
        ast.fix_missing_locations(call)
        scope = DeferredScope(g.temporary(), g.temporary())
        trace_id = g.temporary()
        g.iterating_lists.extend(source.owners)
        try:
            with _scope(g, scope, trace_id):
                value = g.expression(call, inside)
        finally:
            if source.owners:
                del g.iterating_lists[-len(source.owners):]
        item = g.temporary()

        def emit(action, caller_scope, line, continue_label=None):
            prefix = _deferred_prefix(scope, trace_id, caller_scope, line)
            return prefix + source.emit(f"let {item} = {value.code};\n{action}", caller_scope, line, continue_label)

        return Stream(source.construct(), "", (_Expression(item, value.kind),), source.owners, emit,
                      True, length=source.length, nonempty=source.nonempty)

    def filter_stream(self, node, environment):
        if len(node.args) != 2 or node.keywords:
            raise _Unsupported
        g = self.g
        source = self.stream(node.args[1], environment)
        if not source.tupled and len(source.values) != 1:
            raise _Unsupported
        scope = DeferredScope(g.temporary(), g.temporary())
        trace_id = g.temporary()
        if isinstance(node.args[0], ast.Constant) and node.args[0].value is None:
            test = str(bool(source.values)).lower() if source.tupled else g.truth(source.values[0])
        elif isinstance(node.args[0], ast.Name):
            if source.tupled:
                raise _Unsupported
            argument = "\0iterator_" + g.temporary()
            inside = environment.copy()
            inside[argument] = _Binding(source.values[0].code, g.binding(source.values[0]))
            call = ast.copy_location(ast.Call(func=node.args[0], args=[ast.Name(id=argument, ctx=ast.Load())], keywords=[]), node)
            ast.fix_missing_locations(call)
            g.iterating_lists.extend(source.owners)
            try:
                with _scope(g, scope, trace_id):
                    test = g.truth(g.expression(call, inside))
            finally:
                if source.owners:
                    del g.iterating_lists[-len(source.owners):]
        else:
            raise _Unsupported

        def emit(action, caller_scope, line, continue_label=None):
            prefix = _deferred_prefix(scope, trace_id, caller_scope, line)
            return prefix + source.emit(f"if {test} {{\n{action}\n}}", caller_scope, line, continue_label)

        return Stream(source.construct(), "", source.values, source.owners, emit,
                      True, source.tupled, length=0 if source.length == 0 else None)

    def enumerate_stream(self, node, environment):
        if not 1 <= len(node.args) <= 2:
            raise _Unsupported
        start_node = node.args[1] if len(node.args) == 2 else None
        for keyword in node.keywords:
            if keyword.arg != "start" or start_node is not None:
                raise _Unsupported
            start_node = keyword.value
        g = self.g
        source = self.stream(node.args[0], environment)
        if source.tupled or len(source.values) != 1:
            raise _Unsupported
        g.iterating_lists.extend(source.owners)
        try:
            start = g.expression(start_node, environment) if start_node is not None else _Expression(g.literal(0), "int", 0)
        finally:
            if source.owners:
                del g.iterating_lists[-len(source.owners):]
        counter, item = g.temporary(), g.temporary()
        setup = source.construct() + f"\nlet mut {counter} = {g.number(start)};"
        increment = g.binary(ast.Add(), _Expression(counter, "int"), _Expression(g.literal(1), "int", 1), node)

        def emit(action, caller_scope, line, continue_label=None):
            value = g.coerce(_Expression(counter, "int"), "int")
            return source.emit(f"let {item} = {value};\n{counter} = {increment.code};\n{action}", caller_scope, line, continue_label)

        return Stream(setup, "", (_Expression(item, "int"), *source.values), source.owners,
                      emit, True, True, length=source.length, nonempty=source.nonempty)

    def reverse_stream(self, node, environment):
        if len(node.args) != 1 or node.keywords:
            raise _Unsupported
        source = self.stream(node.args[0], environment)
        if source.eager or source.iterator is None or not source.reversible:
            raise _Unsupported
        cursor = self.g.temporary()
        setup = source.construct() + f"\nlet {cursor} = ({source.iterator}).rev();"
        return self.leaf(setup, "", cursor, source.fields, source.owners,
                         eager=True, tupled=source.tupled,
                         length=source.length, nonempty=source.nonempty)

    def zip_stream(self, node, environment):
        if not node.args or node.keywords:
            raise _Unsupported
        g = self.g
        children = [self.stream(argument, environment) for argument in node.args]
        if any(child.eager or child.tupled or child.iterator is None or len(child.values) != 1 for child in children):
            # Callback-bearing streams need a typed pull-state representation
            # before two such streams can be advanced alternately.
            raise _Unsupported
        # zip evaluates every argument before obtaining any argument iterator.
        setup = "\n".join(child.setup for child in children)
        setup += "\n" + "\n".join(child.begin for child in children)
        cursor = g.temporary()
        iterator = children[0].iterator
        paths = ["@"]
        for child in children[1:]:
            iterator = f"({iterator}).zip({child.iterator})"
            paths = [path.replace("@", "@.0") for path in paths] + ["@.1"]
        if len(children) == 1:
            # One-element tuple is still a tuple, including its truth value.
            paths = ["@"]
        fields = []
        for child, path in zip(children, paths):
            kind, raw, owned = child.fields[0]
            fields.append((kind, raw.replace("@", path), owned))
        setup += f"\nlet {cursor} = {iterator};"
        owners = set().union(*(child.owners for child in children))
        mutates = any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                      and isinstance(child.func.value, ast.Name) and child.func.value.id in owners
                      and child.func.attr in {"pop", "popleft"}
                      for argument in node.args for child in ast.walk(argument))
        length = (min(child.length for child in children) if all(child.length is not None for child in children)
                  else 0 if any(child.length == 0 for child in children) else None)
        return self.leaf(setup, "", cursor, fields, owners, eager=True, tupled=True,
                         length=None if mutates else length,
                         nonempty=not mutates and all(child.nonempty for child in children))


def try_reduction(generator, node, environment):
    """Return typed Rust for a supported consumer, or None for other syntax."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _REDUCTIONS):
        return None
    name = node.func.id
    if name in {"min", "max"} and len(node.args) != 1:
        return None
    if name == "sum" and not 1 <= len(node.args) <= 2:
        raise _Unsupported
    if name in {"any", "all"} and (len(node.args) != 1 or node.keywords):
        raise _Unsupported
    if not node.args or any(isinstance(argument, ast.Starred) for argument in node.args):
        raise _Unsupported
    g = generator
    stream = Planner(g).stream(node.args[0], environment, allow_set=True)
    if stream.tupled and name not in {"any", "all"} or not stream.tupled and len(stream.values) != 1:
        raise _Unsupported
    value = stream.values[0] if stream.values else None
    setup = stream.setup + ("\n" + stream.begin if stream.eager else "")
    arguments = []
    if name == "sum" and len(node.args) == 2:
        arguments.append(("start", node.args[1]))
    for keyword in node.keywords:
        if name == "sum" and keyword.arg == "start" and not arguments:
            arguments.append(("start", keyword.value))
        elif name in {"min", "max"} and keyword.arg == "default" and not any(key == "default" for key, _ in arguments):
            arguments.append(("default", keyword.value))
        elif name in {"min", "max"} and keyword.arg == "key" and isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
            pass
        else:
            raise _Unsupported
    extra = None
    if stream.eager:
        g.iterating_lists.extend(stream.owners)
    try:
        for _, expression in arguments:
            extra = g.expression(expression, environment)
    finally:
        if stream.eager and stream.owners:
            del g.iterating_lists[-len(stream.owners):]
    accumulator = g.temporary()
    if name == "sum":
        start = extra or _Expression(g.literal(0), "int", 0)
        if value.kind not in {"int", "bool", "int_bool"} or start.kind not in {"int", "bool", "int_bool"}:
            raise _Unsupported
        kind = g.scalar_kind([start, _Expression("", "int")])
        setup += f"\nlet mut {accumulator} = {_owned(g, start, kind)};"
        previous = _Expression(g.coerce(_Expression(accumulator, kind), kind), kind)
        addition = g.binary(ast.Add(), previous, value, node)
        action = f"{accumulator} = {_owned(g, addition, kind)};"
        final = accumulator
    elif name in {"any", "all"}:
        kind = "bool"
        identity = "true" if name == "all" else "false"
        setup += f"\nlet mut {accumulator} = {identity};"
        test = str(bool(stream.values)).lower() if stream.tupled else g.truth(value)
        if name == "all":
            test = f"!({test})"
        action = f"if {test} {{ {accumulator} = {'false' if name == 'all' else 'true'}; return Ok(true); }}"
        final = accumulator
    else:
        kind = g.scalar_kind([value] + ([extra] if extra is not None else []))
        if kind not in _TYPES or kind == "list_int":
            raise _Unsupported
        default = g.temporary() if extra is not None else None
        if extra is not None:
            setup += f"\nlet {default} = {_owned(g, extra, kind)};"
        setup += f"\nlet mut {accumulator}: Option<{_TYPES[kind]}> = None;"
        item, previous = g.temporary(), g.temporary()
        candidate = _Expression(item, kind)
        before = _Expression(f"(*{previous})", kind)
        if kind in {"float", "str"}:
            compare = f"{item} {'>' if name == 'max' else '<'} *{previous}"
        else:
            compare = f"{g.number(candidate)} {'>' if name == 'max' else '<'} {g.number(before)}"
        action = (f"let {item} = {_owned(g, value, kind)};\n"
                  f"if {accumulator}.as_ref().map_or(true, |{previous}| {compare}) {{ {accumulator} = Some({item}); }}")
        final = (f"{accumulator}.unwrap_or({default})" if default is not None else
                 g.at(f'{accumulator}.ok_or_else(|| "ValueError: {name}() iterable argument is empty".to_string())', node))
    if not stream.eager:
        setup += "\n" + stream.begin
    body = stream.emit(action, TraceContext(g.scope_name(), g.expression_trace_id), g.line_code(node))
    code = f"{{\n{setup}\n(|| -> Result<bool, NativeError> {{\n{body}\nOk(false)\n}})()?;\n{final}\n}}"
    return _Expression(code, kind)


def try_for_loop(generator, node, environment):
    """Lower a typed stream with the common binding and loop-edge proofs."""
    if not isinstance(node, ast.For):
        return None
    g = generator
    written = {target.id for statement in node.body for target in ast.walk(statement)
               if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store)}
    written.update(target.id for target in ast.walk(node.target) if isinstance(target, ast.Name))
    planner = Planner(g, snapshot_strings=written)
    stream = planner.stream(node.iter, environment)
    # Validate tuple shape independently of the function/module bindings.
    planner.bind_target(node.target, stream, environment)
    targets = [node.target] if isinstance(node.target, ast.Name) else node.target.elts
    if any(target.id in g.iterating_lists for target in targets):
        raise _Unsupported
    if any(value.kind == "list_int" and not value.owned for value in stream.values):
        # A Python row binding may survive mutation/replacement of its owner.
        # Those persistent shared rows need the shared-container backend.
        raise _Unsupported
    nonempty = stream.nonempty or stream.length is not None and stream.length > 0
    zero = stream.length == 0
    optional_initializers = []
    if not nonempty:
        environment = environment.copy()
        for target, value in zip(targets, stream.values):
            if target.id not in environment:
                if value.kind not in {"int", "bool", "int_bool", "str", "float", "bytes"}:
                    raise _Unsupported
                slot = g.slot("maybe_" + value.kind)
                owner = g.function.node.name if g.function else g.entry_scope
                environment[target.id] = _Binding(slot, _MaybeInfo(value.kind, owner))
                optional_initializers.append(f"{slot} = None;")
    header_initializers, widened = g.loop_header(node, environment)
    inside = widened.copy()
    target_slots = [g.bind(target.id, value, inside) for target, value in zip(targets, stream.values)]
    break_label, continue_label = g.temporary(), g.temporary()
    context = {"label": continue_label, "break_label": break_label,
               "continue_label": continue_label, "edges": []}
    broken = g.temporary() if node.orelse else None
    if broken:
        context["break_flag"] = broken
    guard_depth = len(g.iterating_lists)
    target_names = {target.id for target in targets}
    g.iterating_lists.extend(stream.owners - target_names)
    g.loops.append(context)
    try:
        body, remaining = g.statements(node.body, inside)
    finally:
        g.loops.pop()
        del g.iterating_lists[guard_depth:]
    initialization, body, joined = g.finish_loop(
        node, environment, inside, context, body, remaining,
        nonempty, stream.length is None or stream.length > 1, zero)
    assignments = "\n".join(f"{slot} = {_owned(g, value, value.kind)};"
                             for slot, value in zip(target_slots, stream.values))
    loop = stream.emit(assignments + "\n" + body,
                       TraceContext(g.scope_name(), g.expression_trace_id), g.line_code(node),
                       continue_label)
    code = (stream.construct() + "\n" + "\n".join(optional_initializers) + "\n" + header_initializers + "\n" + initialization
            + (f"\nlet mut {broken} = false;" if broken else "")
            + f"\n'{break_label}: {{\n{loop}\n}}")
    if not node.orelse:
        return code, joined
    otherwise, otherwise_environment = g.statements(node.orelse, joined)
    can_break = not zero and any(kind == "break" for _, kind, _ in context["edges"])
    if not can_break:
        return code + "\n" + otherwise, otherwise_environment
    final, moves = g.join([otherwise_environment, joined])
    yes = otherwise + "\n" + "\n".join(moves[0])
    no = "\n".join(moves[1])
    return code + f"\nif !{broken} {{\n{yes}\n}} else {{\n{no}\n}}", final
