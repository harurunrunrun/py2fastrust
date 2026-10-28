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
from .native_types import TupleType, immutable, maybe_type, rust_type, tuple_code, tuple_field
from .call_semantics import CallBindingError
from .native_stream_plans import ConsumerKind, ProducerKind, consumer_plan, context
from .references import BuiltinIdentity


_REDUCTIONS = {"sum", "any", "all", "min", "max"}
_TYPES = {"int": "NativeInt", "bool": "bool", "int_bool": "NativeScalar",
          "float": "f64", "str": "NativeText", "bytes": "Vec<u8>", "list_int": "Vec<NativeInt>"}


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


def stream_item(g,source,*,borrowed=False):
    if source.tupled:
        kind = TupleType(tuple(value.kind for value in source.values))
        g.register_type(kind)
        fields = (g.coerce(value,value.kind) if borrowed else _owned(g,value,value.kind)
                  for value in source.values)
        return _Expression(tuple_code(fields),kind)
    if len(source.values) != 1:
        raise _Unsupported
    return source.values[0]


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
    words: object = None
    integer_words: object = None
    range_capture: object = None

    def construct(self):
        return self.setup + "\n" + self.begin

    def emit(self, action, caller_scope, line, continue_label=None):
        return self.emit_body(action, caller_scope, line, continue_label)


@dataclass(frozen=True)
class ItemField:
    """An iterator field plus an optional captured-codepoint projection."""
    kind: object
    raw: str
    owned: bool
    codepoint: str | None = None

    def __iter__(self):
        # Existing non-text producers describe ordinary fields as triples.
        return iter((self.kind, self.raw, self.owned))

    @classmethod
    def from_field(cls, field):
        return field if isinstance(field, cls) else cls(*field)

    def project(self, path):
        return ItemField(self.kind, self.raw.replace("@", path), self.owned,
                         self.codepoint.replace("@", path) if self.codepoint is not None else None)


class Planner:
    def __init__(self, generator, snapshot_strings=()):
        self.g = generator
        self.snapshot_strings = frozenset(snapshot_strings)

    def leaf(self, setup, begin, iterator, fields, owners=(), eager=False, tupled=False,
             length=None, nonempty=False):
        """Build one loop; fields describe borrowed or owning iterator items."""
        g = self.g
        fields = tuple(ItemField.from_field(field) for field in fields)
        item = g.temporary()
        names = [g.temporary() for _ in fields]
        values = []
        assignments = []
        for name, field in zip(names, fields):
            kind, raw, owned = field
            if field.codepoint is not None:
                assignments.append(f"let {name}:u32={field.codepoint.replace('@',item)};")
                values.append(g.text_from_codepoint(name))
                continue
            code = raw.replace("@", item)
            if not owned and kind != "list_int":
                code = g.coerce(_Expression(code, kind), kind)
            assignments.append(f"let {name} = {code};")
            values.append(_Expression(name, kind, owned=kind != "list_int" or owned))
        prefix = "\n".join(assignments)

        def emit(action, _scope, _line, continue_label=None):
            label = f"'{continue_label}: " if continue_label else ""
            return f"{label}for {item} in {iterator} {{\n{prefix}\n{action}\n}}"

        return Stream(setup, begin, tuple(values), frozenset(owners), emit, eager, tupled,
                      iterator, tuple(fields), length, nonempty or length is not None and length > 0)

    def stream(self, node, environment, *, allow_set=False):
        try:
            plan=context(self.g,environment).producer(node)
            return self.lower(plan,environment,allow_set=allow_set)
        except CallBindingError as error:
            raise _Unsupported from error

    def lower(self,plan,environment,*,allow_set=False,captured_value=None):
        g = self.g
        node=plan.node
        if plan.kind is ProducerKind.GENERATOR:
            return self.generator(plan, environment)
        if plan.kind is ProducerKind.WORDS:
            from .native_words import lower
            return lower(g,plan,environment,self)
        if plan.kind in {ProducerKind.ITER,ProducerKind.RANGE,ProducerKind.MAP,ProducerKind.FILTER,
                         ProducerKind.ENUMERATE,ProducerKind.ZIP,ProducerKind.REVERSED}:
            if plan.kind is ProducerKind.ITER:
                # iter alone neither calls user code per item nor exposes a
                # position. Consumers may retain an order-insensitive proof.
                result = self.lower(plan.sources[0],environment,allow_set=allow_set)
                result.eager = True
                return result
            if plan.kind is ProducerKind.RANGE:
                range_code=g.range_iterator(plan, environment)
                setup, iterator, arguments = range_code
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
                result.range_capture=range_code.captures
                result.reversible = g.bits != 0 and arguments[2].constant in {1, -1}
                return result
            if plan.kind is ProducerKind.MAP:
                return self.map_stream(plan, environment)
            if plan.kind is ProducerKind.FILTER:
                return self.filter_stream(plan, environment)
            if plan.kind is ProducerKind.ENUMERATE:
                return self.enumerate_stream(plan, environment)
            if plan.kind is ProducerKind.ZIP:
                return self.zip_stream(plan, environment)
            if plan.kind is ProducerKind.REVERSED:
                return self.reverse_stream(plan, environment)
        if plan.kind is ProducerKind.SEQUENCE:
            values = [g.expression(value, environment) for value in plan.elements]
            kind = ("list_int" if values and all(value.kind == "list_int" and value.owned for value in values)
                    else g.scalar_kind(values) if values else "int")
            owner, cursor = g.temporary(), g.temporary()
            code = ", ".join(_owned(g, value, kind) for value in values)
            setup = f"let {owner}: [{rust_type(kind)}; {len(values)}] = [{code}];"
            return self.leaf(setup, f"let {cursor} = {owner}.into_iter();", cursor,
                             ((kind, "@", True),), length=len(values))
        from .native_key_containers import stream as keyed_stream
        keyed=keyed_stream(g,node,environment,self,allow_set)
        if keyed is not None:return keyed
        view = g.dict_view(node, environment)if captured_value is None else None
        value = (view[0] if view else g.expression(node, environment))if captured_value is None else captured_value
        from .native_key_containers import stream_value as keyed_value_stream
        keyed=keyed_value_stream(g,node,value,self,allow_set,environment=environment)
        if keyed is not None:return keyed
        from .native_typed_lists import stream as typed_stream
        typed = typed_stream(g,node,environment,self,value=value)
        if typed is not None:
            return typed
        if isinstance(value.kind,TupleType):
            owner,cursor = g.temporary(),g.temporary()
            values = [_Expression(tuple_field(owner,index),kind,owned=False)
                      for index,kind in enumerate(value.kind.fields)]
            kind = g.scalar_kind(values) if values else "int"
            setup = f"let {owner}={value.code};"
            setup += f"\nlet {cursor}=[" + ",".join(g.coerce(field,kind) for field in values) + "].into_iter();"
            return self.leaf(setup,"",cursor,((kind,"@",True),),length=len(values))
        if value.kind == "str":
            owner, cursor = g.temporary(), g.temporary()
            named = (isinstance(node, ast.Name) and isinstance(environment.get(node.id), _Binding)
                     and environment[node.id].kind == "str")
            if named and node.id not in self.snapshot_strings:
                owner, setup = environment[node.id].slot, ""
            elif named:
                setup = f"let {owner} = {environment[node.id].slot}.clone();"
            else:
                setup = f"let {owner} = {value.code};"
            length = len(node.value) if isinstance(node, ast.Constant) and type(node.value) is str else None
            traversal = "bytes" if g.string_mode == "ascii" else "chars"
            begin = f"let {cursor} = {owner}.{traversal}();"
            field = ItemField("str", "@", True, "(@ as u32)")
            return self.leaf(setup, begin, cursor, (field,),
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
        from .native_container_reads import capture
        read = capture(g,receiver,value,environment)
        owner, setup = read.owner, read.setup
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

    def target_values(self,target,stream):
        g = self.g
        if (stream.tupled and isinstance(target,(ast.Tuple,ast.List))
                and len(target.elts) == len(stream.values)):
            result = []
            for nested,value in zip(target.elts,stream.values):
                child = Stream("","",(value,),stream.owners,lambda *_: "")
                result.extend(self.target_values(nested,child))
            return result
        if stream.tupled:
            kind = TupleType(tuple(value.kind for value in stream.values))
            g.register_type(kind)
            value = _Expression(tuple_code(_owned(g,value,value.kind) for value in stream.values),kind)
        elif len(stream.values) == 1:
            value = stream.values[0]
        else:
            raise _Unsupported
        def unpack(target,value):
            if isinstance(target,ast.Name):
                return [(target,value)]
            if not (isinstance(target,(ast.Tuple,ast.List)) and isinstance(value.kind,TupleType)
                    and len(target.elts) == len(value.kind.fields)):
                raise _Unsupported
            result = []
            for index,(nested,kind) in enumerate(zip(target.elts,value.kind.fields)):
                field = _Expression(tuple_field(value.code,index),kind,owned=False)
                result.extend(unpack(nested,field))
            return result
        return unpack(target,value)

    def bind_target(self, target, stream, environment):
        pairs = self.target_values(target,stream)
        inside = environment.copy()
        for target, value in pairs:
            from .native_characters import local_binding
            inside[target.id] = local_binding(value) or _Binding(value.code, self.g.binding(value))
        return inside

    def generator(self, plan, environment):
        g = self.g
        node=plan.node
        g.has_iterator_frames |= plan.frame is not None
        trace_id = g.temporary() if plan.frame is not None else g.expression_trace_id
        producer_scope=plan.frame or g.scope_name()
        if not node.generators or any(clause.is_async for clause in node.generators):
            raise _Unsupported
        clauses = []
        owners = set()
        # Only the first iterable is evaluated in the containing scope.
        first = self.lower(plan.clauses[0].source, environment)
        inside = self.bind_target(node.generators[0].target, first, environment)
        # A typed unary projection of a word stream is the same producer
        # whether expressed by map(), a generator or an eager comprehension.
        if first.words is not None and len(plan.clauses)==1 and not plan.clauses[0].filters:
            element=plan.element
            if isinstance(element,ast.Call):
                normalizer=context(g,inside)
                invocation=normalizer.invocation(element)
                if isinstance(invocation.identity,BuiltinIdentity) and invocation.identity.name=="int":
                    from .call_semantics import FunctionSignature
                    binding=normalizer.bind(invocation,FunctionSignature.declaration(("value",),positional_only=("value",)))
                    argument=binding.binding["value"].expression
                    if (isinstance(argument,ast.Name) and argument.id in inside
                            and isinstance(inside[argument.id],_Binding)
                            and inside[argument.id].slot==first.values[0].code):
                        from .native_words import integer_map
                        return integer_map(g,first,self,element,frame=plan.frame,inline=plan.frame is None)
        owners.update(first.owners)
        mutation_start = len(g.expression_mutations)
        from .native_regions import scope,site
        region=scope(g,(site(g,node),0),inside,first)
        with _scope(g, producer_scope, trace_id),region:
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
        from .native_characters import capture
        captures = [capture(g,value) for value in values]
        output = tuple(value for _,value in captures)
        yielded = "\n".join(code for code,_ in captures)

        def emit(action, caller_scope, line, continue_label=None):
            caller = _context(caller_scope)
            body = yielded + "\n" + action
            for index in reversed(range(len(clauses))):
                stream, filters = clauses[index]
                for test in reversed(filters):
                    body = f"if {g.truth(test)} {{\n{body}\n}}"
                emit=region.emit if index==0 else stream.emit
                body = (emit(stream,body,TraceContext(producer_scope,trace_id),node.elt.lineno,continue_label if index==len(clauses)-1 else None)
                        if index==0 else emit(body,TraceContext(producer_scope,trace_id),node.elt.lineno,continue_label if index==len(clauses)-1 else None))
                if index:
                    body = stream.construct() + "\n" + body
            # Only producer operations use this context. A consumer callback
            # runs after the producer has yielded and keeps its own context.
            parent = f"{caller.trace_id}(error)" if caller.trace_id is not None else "error"
            prefix = ((f"let {trace_id} = |mut error: NativeError| {{ "
                       f"error.frames.push(({line}, {_scope_code(caller.name)})); {parent} }};\n")
                      if plan.frame is not None else "")
            return prefix + body

        length = 0 if any(stream.length == 0 for stream,_ in clauses) else 1
        if length:
            for stream, filters in clauses:
                if filters or stream.length is None:
                    length = None
                    break
                length *= stream.length
        return Stream(first.construct(), "", output, frozenset(owners), emit, True,
                      isinstance(node.elt, ast.Tuple), length=length)

    def map_stream(self, plan, environment):
        node=plan.node
        callback=plan.binding.binding["function"].expression
        g = self.g
        source = self.lower(plan.sources[0], environment)
        if isinstance(plan.callback,BuiltinIdentity)and plan.callback.name=="int"and source.words is not None:
            from .native_words import integer_map
            return integer_map(g,source,self,node)
        source_value = stream_item(g,source)
        argument = "\0iterator_" + g.temporary()
        inside = environment.copy()
        from .native_characters import local_binding
        inside[argument] = local_binding(source_value) or _Binding(source_value.code, g.binding(source_value))
        call = ast.copy_location(ast.Call(func=callback, args=[ast.Name(id=argument, ctx=ast.Load())], keywords=[]), node)
        ast.fix_missing_locations(call)
        scope = DeferredScope(g.temporary(), g.temporary())
        trace_id = g.temporary()
        g.iterating_lists.extend(source.owners)
        try:
            with _scope(g, scope, trace_id):
                from .native_builtin_values import unary
                value = unary(g,plan.callback,source_value,node) if isinstance(plan.callback,BuiltinIdentity) else g.expression(call,inside)
        finally:
            if source.owners:
                del g.iterating_lists[-len(source.owners):]
        from .native_characters import capture
        captured, output = capture(g,value)

        def emit(action, caller_scope, line, continue_label=None):
            prefix = _deferred_prefix(scope, trace_id, caller_scope, line)
            return prefix + source.emit(captured+"\n"+action, caller_scope, line, continue_label)

        return Stream(source.construct(), "", (output,), source.owners, emit,
                      True, length=source.length, nonempty=source.nonempty)

    def filter_stream(self, plan, environment):
        node=plan.node
        callback=plan.binding.binding["function"].expression
        g = self.g
        source = self.lower(plan.sources[0], environment)
        if not source.tupled and len(source.values) != 1:
            raise _Unsupported
        scope = DeferredScope(g.temporary(), g.temporary())
        trace_id = g.temporary()
        if isinstance(callback, ast.Constant) and callback.value is None:
            test = str(bool(source.values)).lower() if source.tupled else g.truth(source.values[0])
        elif getattr(plan.callback,"_native_reference",False):
            source_value = stream_item(g,source,borrowed=True)
            argument = "\0iterator_" + g.temporary()
            inside = environment.copy()
            from .native_characters import local_binding
            inside[argument] = local_binding(source_value) or _Binding(source_value.code, g.binding(source_value))
            call = ast.copy_location(ast.Call(func=callback, args=[ast.Name(id=argument, ctx=ast.Load())], keywords=[]), node)
            ast.fix_missing_locations(call)
            g.iterating_lists.extend(source.owners)
            try:
                with _scope(g, scope, trace_id):
                    from .native_builtin_values import unary
                    value = unary(g,plan.callback,source_value,node) if isinstance(plan.callback,BuiltinIdentity) else g.expression(call,inside)
                    test = g.truth(value)
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

    def enumerate_stream(self, plan, environment):
        node=plan.node
        start_node=plan.binding.binding["start"].expression
        g = self.g
        source = self.lower(plan.sources[0], environment)
        source_value = stream_item(g,source)
        packed = g.temporary() if source.tupled else None
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
            prefix = f"let {packed}={source_value.code};\n" if packed else ""
            return source.emit(f"let {item} = {value};\n{counter} = {increment.code};\n{prefix}{action}", caller_scope, line, continue_label)

        output = _Expression(packed,source_value.kind) if packed else source_value
        return Stream(setup, "", (_Expression(item, "int"), output), source.owners,
                      emit, True, True, length=source.length, nonempty=source.nonempty)

    def reverse_stream(self, plan, environment):
        source = self.lower(plan.sources[0], environment)
        if source.eager or source.iterator is None or not source.reversible:
            raise _Unsupported
        cursor = self.g.temporary()
        setup = source.construct() + f"\nlet {cursor} = ({source.iterator}).rev();"
        return self.leaf(setup, "", cursor, source.fields, source.owners,
                         eager=True, tupled=source.tupled,
                         length=source.length, nonempty=source.nonempty)

    def zip_stream(self, plan, environment):
        node=plan.node
        g = self.g
        if not plan.sources:
            cursor = g.temporary()
            return self.leaf(f"let {cursor}=std::iter::empty::<()>();","",cursor,(),eager=True,tupled=True,length=0)
        children = []
        depth = len(g.iterating_lists)
        try:
            for argument in plan.sources:
                child = self.lower(argument,environment)
                children.append(child)
                if child.eager:
                    g.iterating_lists.extend(child.owners)
        finally:
            del g.iterating_lists[depth:]
        if any(child.iterator is None or child.fields is None for child in children):
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
            if child.tupled:
                kind = TupleType(tuple(kind for kind,_,_ in child.fields))
                g.register_type(kind)
                components=[]
                for field in child.fields:
                    projected=ItemField.from_field(field).project(path)
                    value=(g.text_from_codepoint(projected.codepoint) if projected.codepoint is not None else
                           _Expression(projected.raw,projected.kind,owned=projected.owned))
                    components.append(_owned(g,value,value.kind))
                raw = tuple_code(components)
                fields.append((kind,raw,True))
            elif len(child.fields) == 1:
                fields.append(ItemField.from_field(child.fields[0]).project(path))
            else:
                raise _Unsupported
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
    plan=consumer_plan(generator,node,environment,{ConsumerKind.SUM,ConsumerKind.ANY,ConsumerKind.ALL,ConsumerKind.MIN,ConsumerKind.MAX,ConsumerKind.MIN_ARGUMENTS,ConsumerKind.MAX_ARGUMENTS})
    if plan is None:return None
    if plan.kind in {ConsumerKind.MIN_ARGUMENTS,ConsumerKind.MAX_ARGUMENTS}:
        from .native_extrema import positional
        return positional(generator,plan,environment)
    name=plan.kind.value
    g = generator
    stream = Planner(g).lower(plan.source, environment, allow_set=True)
    value = stream_item(g,stream)
    setup = stream.setup + ("\n" + stream.begin if stream.eager else "")
    arguments=[]
    for operand in plan.binding.explicit_order:
        if operand.parameter=="iterable":continue
        if operand.parameter=="key":
            if not(isinstance(operand.expression,ast.Constant)and operand.expression.value is None):raise _Unsupported
        else:arguments.append((operand.parameter,operand.expression))
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
        from .native_types import EmptyType
        if isinstance(value.kind,EmptyType):value=_Expression(g.coerce(value,"int"),"int")
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
        if not immutable(kind):
            raise _Unsupported
        default = g.temporary() if extra is not None else None
        if extra is not None:
            setup += f"\nlet {default} = {_owned(g, extra, kind)};"
        setup += f"\nlet mut {accumulator}: Option<{rust_type(kind)}> = None;"
        item, previous = g.temporary(), g.temporary()
        candidate = _Expression(item, kind)
        before = _Expression(f"(*{previous})", kind)
        if isinstance(kind,TupleType):
            from .native_tuples import tuple_compare, _scalar
            if not _scalar(kind):
                raise _Unsupported
            compare = tuple_compare(g,candidate,before,ast.Gt() if name == "max" else ast.Lt(),node)
        elif kind in {"float", "str"}:
            compare = f"{item} {'>' if name == 'max' else '<'} *{previous}"
        else:
            compare = f"{g.number(candidate)} {'>' if name == 'max' else '<'} {g.number(before)}"
        action = (f"let {item} = {_owned(g, value, kind)};\n"
                  f"if match {accumulator}.as_ref() {{None=>true,Some({previous})=>{compare}}} {{ {accumulator} = Some({item}); }}")
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
    plan=consumer_plan(g,node,environment,{ConsumerKind.FOR})
    written = {target.id for statement in node.body for target in ast.walk(statement)
               if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store)}
    written.update(target.id for target in ast.walk(node.target) if isinstance(target, ast.Name))
    planner = Planner(g, snapshot_strings=written)
    stream = planner.lower(plan.source, environment)
    # Validate tuple shape independently of the function/module bindings.
    pairs = planner.target_values(node.target,stream)
    targets = [target for target,_ in pairs]
    values = [value for _,value in pairs]
    refinement=""
    if any(target.id in g.iterating_lists for target in targets):
        raise _Unsupported
    if any(value.kind == "list_int" and not value.owned for value in values):
        # A Python row binding may survive mutation/replacement of its owner.
        # Those persistent shared rows need the shared-container backend.
        raise _Unsupported
    nonempty = stream.nonempty or stream.length is not None and stream.length > 0
    zero = stream.length == 0
    optional_initializers = []
    if not nonempty:
        environment = environment.copy()
        for target, value in pairs:
            if target.id not in environment:
                if not immutable(value.kind):
                    raise _Unsupported
                slot = g.slot(maybe_type(value.kind))
                owner = g.function.node.name if g.function else g.entry_scope
                environment[target.id] = _Binding(slot, _MaybeInfo(value.kind, owner))
                optional_initializers.append(f"{slot} = None;")
    header_initializers, widened = g.loop_header(node, environment)
    inside = widened.copy()
    target_slots = [g.bind(target.id, value, inside) for target, value in pairs]
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
    from .native_regions import scope,site
    region=scope(g,site(g,node),inside,stream)
    try:
        with region:
            body, remaining = g.statements(node.body, inside)
    finally:
        g.loops.pop()
        del g.iterating_lists[guard_depth:]
    initialization, body, joined = g.finish_loop(
        node, environment, inside, context, body, remaining,
        nonempty, stream.length is None or stream.length > 1, zero)
    assignments = "\n".join(f"{slot} = {_owned(g, value, value.kind)};"
                             for slot, value in zip(target_slots, values))
    loop = region.emit(stream,assignments + "\n" + body,
                       TraceContext(g.scope_name(), g.expression_trace_id), g.line_code(node),
                       continue_label)
    code = (stream.construct() + "\n" + refinement + "\n" + "\n".join(optional_initializers) + "\n" + header_initializers + "\n" + initialization
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
