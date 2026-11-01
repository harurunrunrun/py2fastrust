"""Typed positional call segments and runtime arity projection.

The metadata refers to original argument expressions. Generated code evaluates
the captured callee once and constructs a call-site-specific Vec<T>, then
projects that vector onto the selected compiled function's original signature.
This is argument binding, without a Python value or instruction interpreter.
"""
import ast
from dataclasses import dataclass, field

from .call_semantics import CallBindingError, normalize_call
from .native_types import EMPTY, EmptyType, TupleType, TupleSequenceType, alternatives
from .references import BuiltinIdentity


def requires_expansion(unit, analysis, node):
    """Retain the proved direct print adapter without attempting an emitter."""
    from .native_types import ListType, DequeType, immutable, reference_cloneable
    from .native_key_types import DictType
    def printable(kind):
        if kind in {"int","bool","int_bool","float","str","bytes","none","list_int","deque_int","dict_int"}:return True
        if isinstance(kind,EmptyType):return True
        choices=alternatives(kind)
        if choices!=(kind,):return all(printable(choice)for choice in choices)
        if isinstance(kind,(ListType,DequeType,TupleSequenceType)):return printable(kind.element)
        if isinstance(kind,TupleType):return all(printable(field)for field in kind.fields)
        if isinstance(kind,DictType):return printable(kind.key)and printable(kind.value)
        return False
    if not isinstance(node.func,ast.Name)or node.func.id!="print":return True
    seen=set()
    for keyword in node.keywords:
        if keyword.arg not in {"sep","end","flush"}or keyword.arg in seen:return True
        seen.add(keyword.arg)
        if not isinstance(keyword.value,ast.Constant):return True
        expected=bool if keyword.arg=="flush"else str
        if type(keyword.value.value)is not expected:return True
    found=False
    for facts in analysis.scopes.values():
        if unit.ordinal(node)not in facts.expressions:continue
        found=True
        identity=facts.values.get(unit.ordinal(node.func))
        if identity is None or identity.unknown or identity.unbound or identity.alternatives!=frozenset({BuiltinIdentity("print")}):return True
        for argument in node.args:
            source=argument.value if isinstance(argument,ast.Starred)else argument
            kind=facts.expressions.get(unit.ordinal(source))
            if isinstance(argument,ast.Starred):
                if kind in {"list_int","deque_int"}:continue
                if isinstance(kind,(ListType,DequeType,TupleSequenceType)):
                    if not printable(kind.element)or not reference_cloneable(kind.element):return True
                elif isinstance(kind,TupleType):
                    if not printable(kind)or not all(immutable(field)for field in kind.fields):return True
                else:return True
            elif not printable(kind):return True
    return not found


@dataclass
class Segment:
    node: object
    spread: bool
    value: object
    iterator: object = None
    element: object = None
    minimum: int = 1
    maximum: int | None = 1
    fields: tuple = ()
    viable: bool = True


@dataclass
class ExpandedTarget:
    plan: object
    implicit: int = 0
    owner: str | None = None
    possible: bool = True
    method: object = None


@dataclass
class ExpandedSite:
    node: object
    arguments: object
    callee: object
    element: object
    result: object
    segments: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
    targets: dict = field(default_factory=dict)
    builtin_errors: dict = field(default_factory=dict)

    @property
    def deferred(self):
        return len(self.arguments.positional) == 1 and self.arguments.positional[0].spread


def _plus(a, b):
    return None if a is None or b is None else a + b


def _function_name(plan):
    return getattr(plan, "qualified_name", getattr(plan.node, "name", "<lambda>")) + "()"


def _range_for(value):
    from .native_classes import shape
    kind = shape(value)
    if isinstance(kind, TupleType):
        return len(kind.fields), len(kind.fields)
    return 0, None


def _iterable_possible(value):
    from .native_classes import shape, domain
    from .native_aot_callables import function_kind
    kind=shape(value)
    # source() has already required the registered pull adapter. Exclude only
    # its proved noniterable branches; additional container adapters need no
    # second, separate allow-list in call binding.
    return kind is None or any(domain(choice)not in {"int","bool","int_bool","float","none"}
                               and not function_kind(choice)for choice in alternatives(kind))


class ExpandedCalls:
    def __init__(self, model):
        self.model = model
        self.sites = {}

    def snapshot(self):
        from .native_classes import shape
        return tuple((key, shape(site.callee), shape(site.element), shape(site.result),
                      tuple((part.spread, shape(part.value), part.minimum, part.maximum)
                            for part in site.segments))
                     for key, site in sorted(self.sites.items()))

    def kinds(self):
        from .native_classes import shape
        for site in self.sites.values():
            yield shape(site.element)
            yield shape(site.callee)
            yield shape(site.result)

    def default_empty(self):
        from .native_classes import Cell, merge
        for site in self.sites.values():
            if site.element.root().tag is None:
                merge(site.element, Cell(EMPTY), site.node)

    def _contribute(self, destination, source, node):
        if not self.model.namespace.contribute(destination, source, node, force=True):
            self.model.contribute(destination, source, node)

    def analyze(self, plan, node, environment):
        if not any(isinstance(value, ast.Starred) for value in node.args):
            return None
        from .native_classes import Cell, ClassUnsupported, shape
        from .native_aot_callables import function_kind
        from .native_bound_methods import BoundMethodTarget
        try:
            arguments = normalize_call(node, allow_starred=True)
        except CallBindingError as error:
            raise ClassUnsupported(node, str(error), proof="expanded keyword mapping protocol") from None
        key = plan.index, id(node)
        if key not in self.sites:
            self.sites[key] = ExpandedSite(node, arguments, Cell(), Cell(), self.model.cell(plan, node))
        site = self.sites[key]
        self._contribute(site.callee, self.model.expression(plan, node.func, environment), node.func)
        segments = []
        for original, argument in zip(node.args, arguments.positional):
            value = self.model.expression(plan, argument.expression, environment)
            part = Segment(original, argument.spread, value)
            if argument.spread:
                if getattr(shape(value),'_native_class_generator',False):
                    part.element = self.model.generators.demand(plan,node,value,environment)
                else:
                    part.iterator = self.model.iterators.source(plan, original, value)
                    part.element = self.model.iterators.demand(plan, node,
                                                              Cell(part.iterator), environment)
                part.minimum, part.maximum = _range_for(value)
                part.viable = _iterable_possible(value)
                if value.root().tag == "tuple":part.fields = value.root().args
                self._contribute(site.element, part.element, original)
            else:
                self._contribute(site.element, value, original)
            segments.append(part)
        site.segments = segments
        site.keywords = [(argument.name, self.model.expression(plan, argument.expression, environment))
                         for argument in arguments.keywords]
        kinds = alternatives(shape(site.callee)) if shape(site.callee) is not None else ()
        for kind in kinds:
            if function_kind(kind):
                provider = self.model.callable_cells
                for definition in kind.definitions:
                    provider.used.add(definition)
                    target = provider.plans[definition]
                    site.targets[definition] = self._analyze_target(plan, node, target, segments,
                        site.keywords, environment)
                    if site.targets[definition].possible:
                        self._contribute(site.result, target.result, node)
                for method in kind.methods:
                    provider.bound_methods.used.add(method)
                    target = provider.plans[method.definition]
                    site.targets[method] = self._analyze_target(plan, node, target, segments,
                        site.keywords, environment, implicit=1, owner=method.owner, method=method)
                    if site.targets[method].possible:
                        self._contribute(site.result, target.result, node)
                for identity in kind.builtins:
                    provider.builtin_used.add(identity)
                    if identity.name != "print":
                        raise ClassUnsupported(node, "expanded arguments to builtin " + repr(identity.name) +
                            " need its runtime-arity typed operand adapter; this expansion adapter currently supports print and compiled source functions",
                            proof="builtin expanded-call signature and operand projection")
                    from .native_builtin_callables import binding_error
                    site.builtin_errors[identity] = binding_error(identity, arguments)
                    self._contribute(site.result, Cell("none"), node)
                if kind.members:
                    member = kind.members[0]
                    raise ClassUnsupported(node, "expanded arguments to native member " +
                        repr(member.module + "." + member.name) + " need that member's runtime-arity projection",
                        proof="native member expanded-call adapter")
            elif kind is not None:
                from .native_classes import domain
                if domain(kind) not in {"int", "bool", "int_bool", "float", "str", "bytes", "none", "list", "tuple", "tuple_sequence", "object"}:
                    raise ClassUnsupported(node, "this expanded callee needs its constructor or callable-object adapter",
                                           types=(("callee", kind),), proof="expanded callable-object protocol")
                self._contribute(site.result, Cell("none"), node)
        if self.model.final and site.result.root().tag is None:
            self._contribute(site.result, Cell("none"), node)
        return self.model.remember(plan, node, site.result)

    def _analyze_target(self, caller, node, target, segments, keywords, environment, *, implicit=0, owner=None, method=None):
        from .native_classes import Cell
        signature = target.signature
        supplied = dict(keywords)
        minimum = implicit + sum(part.minimum for part in segments)
        maximum = implicit
        for part in segments:maximum = _plus(maximum, part.maximum)
        defaults = target.default_cells
        maximum_positional = len(signature.positional)
        possible = not any(name not in signature.parameters or name in signature.positional_only
                           or name == signature.variadic_positional for name in supplied)
        if any(not part.viable for part in segments):possible=False
        if not signature.variadic_positional and minimum > maximum_positional:possible = False
        if any(name not in supplied and name not in defaults for name in signature.keyword_only):possible = False
        for index, name in enumerate(signature.positional):
            if name in supplied and minimum > index:possible = False
            if name not in supplied and name not in defaults and maximum is not None and maximum <= index:possible = False
        record = ExpandedTarget(target, implicit, owner, possible, method)
        if not possible:return record
        self.model.activate_frame(caller, node, target, environment)
        candidates = {name: [] for name in signature.parameters}
        if implicit:
            receiver = self.model.cell_for_kind(self.model.callable_cells.bound_methods.receiver_kind(method))
            if signature.positional:candidates[signature.positional[0]].append(receiver)
            elif signature.variadic_positional:candidates[signature.variadic_positional].append(receiver)
        low = high = implicit
        for part in segments:
            values = part.fields if part.spread and part.fields else (part.element if part.spread else part.value,)
            exact_fields = bool(part.fields)
            for offset, value in enumerate(values):
                first = low + offset if exact_fields else low
                last = _plus(high, offset) if exact_fields or not part.spread else None
                if part.spread and part.maximum == 0:continue
                for index, name in enumerate(signature.positional):
                    if index >= first and (last is None or index <= last):candidates[name].append(value)
                if signature.variadic_positional and (last is None or last >= maximum_positional):
                    candidates[signature.variadic_positional].append(value)
            low += part.minimum
            high = _plus(high, part.maximum)
        for name in signature.positional:
            index = signature.positional.index(name)
            if name in supplied:candidates[name].append(supplied[name])
            elif minimum <= index and name in defaults:candidates[name].append(defaults[name])
        for name in signature.keyword_only:
            if name in supplied:candidates[name].append(supplied[name])
            elif name in defaults:candidates[name].append(defaults[name])
        for name, values in candidates.items():
            if name in getattr(target,"erased_context_parameters",()):continue
            if name == signature.variadic_positional:
                from .native_variadic import pack_analysis
                self._contribute(target.arguments[name], pack_analysis(self.model, target, values, node), node)
            else:
                for value in values:self._contribute(target.arguments[name], value, node)
        self.model.namespace.call_effects(caller, target, environment)
        return record

    def _not_iterable(self, emitter, node, site, callee, source):
        from .native_class_builtins import _type_name
        from .native import _string
        name = _type_name(emitter, source, node)
        if not site.deferred:return f'format!("TypeError: Value after * must be an iterable, not {{}}",{name})'
        function = self._function_string(emitter, node, callee)
        return f'format!("TypeError: {{}} argument after * must be an iterable, not {{}}",{function},{name})'

    def _function_string(self, emitter, node, value):
        from .native import _string
        from .native_aot_callables import function_kind, variant
        from .native_classes import Expression
        from .native_unions import project, union_kind
        if union_kind(value.kind):
            return project(value.kind, value.code, lambda kind, code:
                self._function_string(emitter, node, Expression(code, kind)))
        if not function_kind(value.kind):return emitter.show(value, node)
        provider = self.model.callable_cells
        arms = []
        for definition in value.kind.definitions:
            target = provider.plans[definition]
            arms.append(provider.reference_pattern(definition) + "=>" + _string(target.module_name + "." + _function_name(target)))
        for method in value.kind.methods:
            target = provider.plans[method.definition]
            arms.append(provider.bound_methods.reference_pattern(method) + "=>" + _string(target.module_name + "." + _function_name(target)))
        for identity in value.kind.builtins:arms.append(variant(identity) + "=>" + _string(identity.name + "()"))
        arms.append('_=>unreachable!("expanded callable contradicts finite proof")')
        return "match " + value.code + "{" + ",".join(arms) + "}"

    def _materialize(self, emitter, node, site, part, source, callee, vector, element):
        from .native_classes import Expression
        if getattr(source.kind,'_native_class_generator',False):
            def append_item(e,item):
                reserve=e.at(f'{vector}.try_reserve(1).map_err(|_|"MemoryError: cannot expand positional arguments".to_owned())',node)
                return reserve+';'+f'{vector}.push({e.coerce(item,element,node)});'
            return self.model.generators.consume(emitter,node,'expanded_arguments',source,[],{},'none',append_item=append_item).code+';'
        callback = lambda value:self._not_iterable(emitter, node, site, callee, value)
        iterator = self.model.iterators.construct(emitter, node, source, kind=part.iterator, not_iterable=callback)
        before, iterator = emitter.capture(iterator)
        pulled = self.model.iterators.pull(emitter, node, iterator)
        current = emitter.fresh()
        item = emitter.coerce(Expression(current, pulled.kind), element, node)
        push = emitter.at(f'{vector}.try_reserve(1).map_err(|_|"MemoryError: cannot expand positional arguments".to_owned())', node) + ";"
        return before + "loop{" + f"let Some({current})=({pulled.code}) else{{break;}};{push}{vector}.push({item});" + "}"

    def emit(self, emitter, node):
        from .native_classes import Expression, shape
        site = self.sites.get((emitter.plan.index, id(node)))
        if site is None:return None
        wanted = shape(site.result)
        before, callee = emitter.capture(emitter.expression(node.func))
        lines = [before]
        vector = emitter.fresh()
        element = shape(site.element)
        lines.append(f"let mut {vector}:Vec<{emitter.rust_type(element)}>=Vec::new();")
        deferred = None
        for part in site.segments:
            original = part.node.value if part.spread else part.node
            before, value = emitter.capture(emitter.expression(original))
            lines.append(before)
            if part.spread:
                if site.deferred:deferred = part, value
                else:lines.append(self._materialize(emitter, node, site, part, value, callee, vector, element))
            else:
                item = emitter.coerce(value, element, original)
                lines.append(emitter.at(f'{vector}.try_reserve(1).map_err(|_|"MemoryError: cannot expand positional arguments".to_owned())', original) + ";")
                lines.append(f"{vector}.push({item});")
        keywords = []
        for argument in site.arguments.keywords:
            before, value = emitter.capture(emitter.expression(argument.expression))
            lines.append(before);keywords.append((argument.name, value))
        if deferred:
            part, value = deferred
            lines.append(self._materialize(emitter, node, site, part, value, callee, vector, element))
        code = self._dispatch(emitter, node, site, callee, vector, element, keywords, wanted)
        return Expression("{" + "".join(lines) + code + "}", wanted)

    def _dispatch(self, emitter, node, site, callee, vector, element, keywords, wanted):
        from .native_classes import Expression, ClassUnsupported, domain
        from .native_aot_callables import function_kind, variant
        from .native_unions import project, union_kind
        from .native import _string
        if union_kind(callee.kind):
            return project(callee.kind, callee.code, lambda kind, code:
                self._dispatch(emitter, node, site, Expression(code, kind), vector, element, keywords, wanted))
        if function_kind(callee.kind):
            provider = self.model.callable_cells
            arms = []
            for definition in callee.kind.definitions:
                record = site.targets[definition]
                code = self._emit_target(emitter, node, record, vector, element, keywords, wanted)
                context = provider.call_context_setup(emitter, record.plan)
                if context:code = "{" + context + code + "}"
                arms.append(provider.call_pattern(definition) + "=>" + code)
            for method in callee.kind.methods:
                record = site.targets[method]
                code = self._emit_target(emitter, node, record, vector, element, keywords, wanted)
                from .native_class_descriptors import ClassMethodTarget,wrap_expanded
                if isinstance(method,ClassMethodTarget):code=wrap_expanded(provider,emitter,method,code)
                elif hasattr(self.model, "module_linker"):
                    code = "{" + self.model.module_linker.call_context(emitter, "class_selected_method.module.clone()") + code + "}"
                arms.append(provider.bound_methods.call_pattern(method) + "=>" + code)
            for identity in callee.kind.builtins:
                if site.builtin_errors.get(identity):
                    code = self._error(emitter, node, wanted, _string(site.builtin_errors[identity]) + ".to_owned()")
                else:code = self._print(emitter, node, vector, element, dict(keywords), wanted)
                arms.append(variant(identity) + "=>" + code)
            arms.append('_=>unreachable!("expanded callable contradicts finite target proof")')
            return "match " + callee.code + "{" + ",".join(arms) + "}"
        from .native_class_builtins import _type_name
        name = _type_name(emitter, callee, node)
        return self._error(emitter, node, wanted, f'format!("TypeError: \'{{}}\' object is not callable",{name})')

    @staticmethod
    def _error(emitter, node, wanted, message):
        return emitter.at(f"Err::<{emitter.rust_type(wanted)},String>({message})", node)

    def _checks(self, emitter, node, record, vector, keywords, wanted):
        from .native import _string
        target = record.plan;signature = target.signature
        count = emitter.fresh()
        length=f"{vector}.len()"
        if record.implicit:
            length=emitter.at(f'{length}.checked_add({record.implicit}).ok_or_else(||"OverflowError: expanded argument count is too large".to_owned())',node)
        lines = [f"let {count}={length};"]
        name = _function_name(target)
        supplied = dict(keywords)
        for parameter, _ in keywords:
            if parameter not in signature.parameters or parameter in signature.positional_only or parameter == signature.variadic_positional:
                positional_only = [value for value in signature.positional if value in signature.positional_only and value in supplied]
                text = (f"TypeError: {name} got some positional-only arguments passed as keyword arguments: {', '.join(positional_only)!r}"
                        if positional_only else f"TypeError: {name} got an unexpected keyword argument {parameter!r}")
                lines.append(self._error(emitter, node, wanted, _string(text) + ".to_owned()") + ";")
                return "".join(lines), count, False
            if parameter in signature.positional:
                index = signature.positional.index(parameter)
                text = f"TypeError: {name} got multiple values for argument {parameter!r}"
                lines.append(f"if {count}>{index}{{" + self._error(emitter, node, wanted, _string(text) + ".to_owned()") + ";}")
        maximum = len(signature.positional)
        defaults = target.default_cells
        if not signature.variadic_positional:
            minimum = sum(parameter not in defaults for parameter in signature.positional)
            quantity = str(maximum) if maximum == minimum else f"from {minimum} to {maximum}"
            noun = "argument" if maximum == minimum == 1 else "arguments"
            keyword_count = sum(parameter in signature.keyword_only for parameter in supplied)
            if keyword_count:
                suffix = f'format!("{{}} positional argument{{}} (and {keyword_count} keyword-only argument{""if keyword_count==1 else"s"}) were",{count},if {count}==1{{""}}else{{"s"}})'
            else:suffix = f'format!("{{}} {{}}",{count},if {count}==1{{"was"}}else{{"were"}})'
            message = f'format!("TypeError: {name} takes {quantity} positional {noun} but {{}} given",{suffix})'
            lines.append(f"if {count}>{maximum}{{" + self._error(emitter, node, wanted, message) + ";}")
        positional_missing=[(index,parameter)for index,parameter in enumerate(signature.positional)
                            if parameter not in supplied and parameter not in defaults]
        if positional_missing:
            missing = emitter.fresh();lines.append(f"let mut {missing}:Vec<&str>=Vec::new();")
            for index,parameter in positional_missing:
                lines.append(f"if {count}<={index}{{{missing}.push({_string(parameter)});}}")
            message = f"class_expanded_missing({_string(name)},&{missing},false)"
            lines.append(f"if !{missing}.is_empty(){{" + self._error(emitter, node, wanted, message) + ";}")
        required = [parameter for parameter in signature.keyword_only if parameter not in supplied and parameter not in defaults]
        if required:
            values = ",".join(_string(parameter) for parameter in required)
            message = f"class_expanded_missing({_string(name)},&[{values}],true)"
            lines.append(self._error(emitter, node, wanted, message) + ";")
            return "".join(lines), count, False
        return "".join(lines), count, record.possible

    def _emit_target(self, emitter, node, record, vector, element, keywords, wanted):
        from .native_classes import Expression, shape, InstanceType
        from .native_class_globals import narrow_binding
        from .native_class_calls import call
        target = record.plan;signature = target.signature
        checks, count, possible = self._checks(emitter, node, record, vector, keywords, wanted)
        if not possible:
            return "{" + checks + 'unreachable!("expanded binding contradicted static arity proof")}'
        default_emitter = self.model.emitter(target)
        parent = self.model.lexical.parent_scope(target)
        is_lambda = isinstance(target.node, ast.Lambda)
        if is_lambda:default_emitter.lambda_instance_override = "class_selected_environment"
        if parent:default_emitter.lexical_environment_override = "class_selected_environment.environment" if is_lambda else "class_selected_environment"
        defaults = default_emitter.captured_defaults(target)
        supplied = dict(keywords)
        arguments = []
        for index, parameter in enumerate(signature.positional):
            kind = shape(target.arguments[parameter])
            if getattr(kind,"_native_erased_argument",False):
                arguments.append("()");continue
            if index < record.implicit:
                value = Expression("class_selected_method.receiver.clone()", self.model.callable_cells.bound_methods.receiver_kind(record.method))
                arguments.append(emitter.coerce(value, kind, node));continue
            position = index - record.implicit
            present = narrow_binding(emitter, node, element, kind, f"{vector}[{position}].clone()").code
            if parameter in supplied:absent = emitter.coerce(supplied[parameter], kind, node)
            elif parameter in defaults:absent = emitter.coerce(defaults[parameter], kind, node)
            else:absent = 'unreachable!("validated expanded positional argument is absent")'
            arguments.append(f"if {count}>{index}{{{present}}}else{{{absent}}}")
        if signature.variadic_positional and signature.variadic_positional in getattr(target,"erased_context_parameters",()):
            arguments.append("()")
        elif signature.variadic_positional:
            kind = shape(target.variadic_element)
            value = emitter.fresh()
            converted = narrow_binding(emitter, node, element, kind, value).code
            skip = max(0, len(signature.positional) - record.implicit)
            rest = f"{vector}.into_iter().skip({skip}).map(|{value}|{converted}).collect::<Vec<{emitter.rust_type(kind)}>>()"
            if record.implicit and not signature.positional:
                receiver = emitter.coerce(Expression("class_selected_method.receiver.clone()", self.model.callable_cells.bound_methods.receiver_kind(record.method)), kind, node)
                rest = "{" + f"let mut values=vec![{receiver}];values.extend({rest});values" + "}"
            arguments.append("NativeTuple::from_vec(" + rest + ")")
        for parameter in signature.keyword_only:
            value = supplied.get(parameter, defaults.get(parameter))
            arguments.append(emitter.coerce(value, shape(target.arguments[parameter]), node))
        environment = ((",class_selected_environment.environment.clone()" if is_lambda else ",class_selected_environment.clone()") if parent else "")
        invocation = emitter.function_name(target) + "(class_scope.clone()" + environment + ("," + ",".join(arguments) if arguments else "") + ")"
        result = emitter.coerce(Expression(call(emitter, invocation, target, node), shape(target.result)), wanted, node)
        return "{" + checks + result + "}"

    def _print(self, emitter, node, vector, element, keywords, wanted):
        from .native_classes import Expression, ClassUnsupported
        from .native_class_builtins import _type_name
        from .native_unions import project, union_kind
        from .native_builtin_singletons import has_singleton
        if "flush"in keywords and has_singleton(keywords["flush"].kind):
            checked=emitter.fresh()
            converted=emitter.truth(keywords["flush"],node)
            result=self._print(emitter,node,vector,element,{**keywords,"flush":Expression(checked,"bool")},wanted)
            return "{let "+checked+"="+converted+";"+result+"}"
        for parameter in ("sep", "end", "file"):
            value = keywords.get(parameter)
            if value is not None and union_kind(value.kind):
                return project(value.kind, value.code, lambda kind, code:self._print(emitter, node, vector, element,
                    {**keywords, parameter:Expression(code, kind)}, wanted))
        separator = keywords.get("sep", Expression('NativeText::from(" ")', "str"))
        ending = keywords.get("end", Expression('NativeText::from("\\n")', "str"))
        if separator.kind == "none":separator = Expression('NativeText::from(" ")', "str")
        if ending.kind == "none":ending = Expression('NativeText::from("\\n")', "str")
        for parameter, value in (("sep", separator), ("end", ending)):
            if value.kind != "str":
                name = _type_name(emitter, value, node)
                return self._error(emitter, node, wanted, f'format!("TypeError: {parameter} must be None or a string, not {{}}",{name})')
        if "file" in keywords and keywords["file"].kind != "none":
            raise ClassUnsupported(node, "expanded print needs this supplied writer's write/flush protocol; arbitrary stored output writers are not implemented", proof="print writer object protocol")
        index, value = emitter.fresh(), emitter.fresh()
        rendered = emitter.show(Expression(value + ".clone()", element), node)
        text = (f"for({index},{value})in {vector}.iter().enumerate(){{if {index}>0{{class_scope.io.borrow_mut().output.push_str(&{separator.code});}}"
                f"class_scope.io.borrow_mut().output.push_str(&({rendered}));}}"
                f"class_scope.io.borrow_mut().output.push_str(&{ending.code});")
        if "flush" in keywords:
            flush = emitter.truth(keywords["flush"])
            flush_call = emitter.at("native_flush_output(&mut class_scope.io.borrow_mut().output)", node)
            text += f"if {flush}{{{flush_call};}}"
        return "{" + text + emitter.coerce(Expression("()", "none"), wanted, node) + "}"


def runtime(model):
    if not model.expanded_calls.sites:return ""
    return r'''
fn class_expanded_missing(name:&str,missing:&[&str],keyword:bool)->String {
    let quoted:Vec<String>=missing.iter().map(|value|format!("'{}'",value)).collect();
    let names=if quoted.len()==1{quoted[0].clone()}else if quoted.len()==2{quoted.join(" and ")}
        else{format!("{}, and {}",quoted[..quoted.len()-1].join(", "),quoted.last().unwrap())};
    format!("TypeError: {} missing {} required {} argument{}: {}",name,missing.len(),
        if keyword{"keyword-only"}else{"positional"},if missing.len()==1{""}else{"s"},names)
}
'''
