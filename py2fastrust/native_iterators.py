"""Typed, immediately consumed Python iterators lowered to ordinary Rust loops.

Iterator construction and iteration have separate code so generator arguments
can construct their outer iterator before later call arguments, while plain
containers defer iteration until all arguments have been evaluated.
"""

import ast
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from .native import _Binding, _Expression, _Unsupported, _string


_REDUCTIONS = {"sum", "any", "all", "min", "max"}
_TYPES = {"int": "NativeInt", "bool": "bool", "int_bool": "NativeScalar",
          "float": "f64", "str": "String", "list_int": "Vec<NativeInt>"}


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
    emit_body: Callable[[str, str, int], str]
    eager: bool = False
    tupled: bool = False
    iterator: str | None = None
    fields: tuple | None = None

    def construct(self):
        return self.setup + "\n" + self.begin

    def emit(self, action, caller_scope, line):
        return self.emit_body(action, caller_scope, line)


class Planner:
    def __init__(self, generator):
        self.g = generator

    def leaf(self, setup, begin, iterator, fields, owners=(), eager=False, tupled=False):
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

        def emit(action, _scope, _line):
            return f"for {item} in {iterator} {{\n{prefix}\n{action}\n}}"

        return Stream(setup, begin, values, frozenset(owners), emit, eager, tupled, iterator, tuple(fields))

    def stream(self, node, environment, *, allow_set=False):
        g = self.g
        if isinstance(node, ast.GeneratorExp):
            return self.generator(node, environment)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "range":
                setup, iterator, _ = g.range_iterator(node, environment)
                owner, cursor = g.temporary(), g.temporary()
                # NativeRange::new validates zero steps here, before later
                # reduction arguments, just as constructing range() does.
                setup += f"\nlet {owner} = {iterator};"
                return self.leaf(setup, f"let {cursor} = {owner};", cursor,
                                 (("int", "@", True),))
            if node.func.id == "map":
                return self.map_stream(node, environment)
            if node.func.id == "filter":
                return self.filter_stream(node, environment)
            if node.func.id == "enumerate":
                return self.enumerate_stream(node, environment)
            if node.func.id == "zip":
                return self.zip_stream(node, environment)
        if g.input_words(node):
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
                             ((kind, "@", True),))
        view = g.dict_view(node, environment)
        value = view[0] if view else g.expression(node, environment)
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
        return self.leaf(setup, begin, cursor, fields, owners, tupled=bool(view and view[1] == "items"))

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
        inside = environment.copy()
        owners = set()
        # Only the first iterable is evaluated in the containing scope.
        first = self.stream(node.generators[0].iter, inside)
        inside = self.bind_target(node.generators[0].target, first, inside)
        owners.update(first.owners)
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
        names = [g.temporary() for _ in values]
        output = tuple(_Expression(name, value.kind, owned=value.owned,
                                   length=value.length, nonempty=value.nonempty)
                       for name, value in zip(names, values))
        yielded = "\n".join(f"let {name} = {value.code};" for name, value in zip(names, values))

        def emit(action, caller_scope, line):
            caller = _context(caller_scope)
            body = yielded + "\n" + action
            for index in reversed(range(len(clauses))):
                stream, filters = clauses[index]
                for test in reversed(filters):
                    body = f"if {g.truth(test)} {{\n{body}\n}}"
                body = stream.emit(body, TraceContext("<genexpr>", trace_id), node.elt.lineno)
                if index:
                    body = stream.construct() + "\n" + body
            # Only producer operations use this context. A consumer callback
            # runs after the producer has yielded and keeps its own context.
            parent = f"{caller.trace_id}(error)" if caller.trace_id is not None else "error"
            prefix = (f"let {trace_id} = |mut error: NativeError| {{ "
                      f"error.frames.push(({line}, {_scope_code(caller.name)})); {parent} }};\n")
            return prefix + body

        return Stream(first.construct(), "", output, frozenset(owners), emit, True, isinstance(node.elt, ast.Tuple))

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

        def emit(action, caller_scope, line):
            prefix = _deferred_prefix(scope, trace_id, caller_scope, line)
            return prefix + source.emit(f"let {item} = {value.code};\n{action}", caller_scope, line)

        return Stream(source.construct(), "", (_Expression(item, value.kind),), source.owners, emit, True)

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

        def emit(action, caller_scope, line):
            prefix = _deferred_prefix(scope, trace_id, caller_scope, line)
            return prefix + source.emit(f"if {test} {{\n{action}\n}}", caller_scope, line)

        return Stream(source.construct(), "", source.values, source.owners, emit, True, source.tupled)

    def enumerate_stream(self, node, environment):
        if not 1 <= len(node.args) <= 2 or node.keywords:
            raise _Unsupported
        g = self.g
        source = self.stream(node.args[0], environment)
        if source.tupled or len(source.values) != 1:
            raise _Unsupported
        g.iterating_lists.extend(source.owners)
        try:
            start = g.expression(node.args[1], environment) if len(node.args) == 2 else _Expression(g.literal(0), "int", 0)
        finally:
            if source.owners:
                del g.iterating_lists[-len(source.owners):]
        counter, item = g.temporary(), g.temporary()
        setup = source.construct() + f"\nlet mut {counter} = {g.number(start)};"
        increment = g.binary(ast.Add(), _Expression(counter, "int"), _Expression(g.literal(1), "int", 1), node)

        def emit(action, caller_scope, line):
            value = g.coerce(_Expression(counter, "int"), "int")
            return source.emit(f"let {item} = {value};\n{counter} = {increment.code};\n{action}", caller_scope, line)

        return Stream(setup, "", (_Expression(item, "int"), *source.values), source.owners, emit, True, True)

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
        return self.leaf(setup, "", cursor, fields, owners, eager=True, tupled=True)


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
