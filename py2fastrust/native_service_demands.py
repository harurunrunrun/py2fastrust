"""Original-source IO demand, independent of ownership and call conventions."""
import ast
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceDemand:
    input: bool = False
    output: bool = False
    complete: bool = True

    def join(self, other):
        return ServiceDemand(self.input or other.input, self.output or other.output,
                             self.complete and other.complete)

    def contains(self, other):
        return (self.input or not other.input) and (self.output or not other.output)


NONE = ServiceDemand()
OUTPUT = ServiceDemand(output=True)
INPUT = ServiceDemand(input=True, output=True)
UNKNOWN = ServiceDemand(True, True, False)
SCALARS = frozenset({'int', 'bool', 'int_bool', 'none', 'float', 'str', 'bytes', 'range'})
PURE_BUILTINS = frozenset({'abs', 'bool', 'int', 'float', 'str', 'bytes', 'len',
                         'range', 'round', 'divmod', 'pow', 'ord', 'chr', 'min', 'max'})


class Registry:
    def __init__(self, unit, analysis, functions):
        self.unit = unit
        self.analysis = analysis
        self.nodes = {}
        self.demands = {}
        self.reasons = {}
        self.edges = {}
        if unit is None or analysis is None or getattr(getattr(analysis, 'graph', None), 'unit', None) is not unit:
            return
        for node in functions:
            self.nodes[unit.ordinal(node)] = node
        direct = {}
        for definition, node in self.nodes.items():
            facts = [(kinds, fact) for (owner, kinds), fact in analysis.scopes.items()
                     if owner == definition]
            self.edges[definition] = set()
            self.reasons[definition] = []
            demand = NONE if facts else self.unknown(definition, node, 'missing reached source context')
            for kinds, scope in facts:
                if not all(self.data(kind) for kind in kinds):
                    demand = demand.join(self.unknown(definition, node, 'open parameter payload/lifetime protocol'))
                demand = demand.join(self.body(definition, node.body, scope))
            direct[definition] = demand
        parents = {definition: set() for definition in self.nodes}
        for parent, children in self.edges.items():
            for child in children:
                if child in parents:
                    parents[child].add(parent)
        self.demands = dict(direct)
        pending = deque(self.nodes)
        queued = set(pending)
        while pending:
            definition = pending.popleft()
            queued.discard(definition)
            demand = direct[definition]
            for child in self.edges[definition]:
                demand = demand.join(self.demands.get(child, UNKNOWN))
            if demand != self.demands[definition]:
                self.demands[definition] = demand
                for parent in parents[definition]:
                    if parent not in queued:
                        pending.append(parent)
                        queued.add(parent)

    def unknown(self, definition, node, reason):
        self.reasons.setdefault(definition, []).append((self.unit.ordinal(node), reason))
        return UNKNOWN

    def demand(self, node):
        if self.unit is None:
            return UNKNOWN
        try:
            definition = self.unit.ordinal(node)
        except KeyError:
            return UNKNOWN
        return self.demands.get(definition, UNKNOWN)

    def data(self, item):
        """Close every MAY payload; this is not an allocation uniqueness proof."""
        from .native_constraints import (Value, Variable, Allocation, TupleValue,
                                         Computed, Projection, ShapeConstraint)
        from .native_types import ListType, TupleType, TupleSequenceType
        from .native_key_types import DictType, SetType
        pending = [item]
        seen = set()
        ground = False
        while pending:
            value = pending.pop()
            if isinstance(value, Value):
                if value.unknown or value.unbound or not value.alternatives:
                    return False
                pending.extend(value.alternatives)
                continue
            if value in seen:
                continue
            seen.add(value)
            if isinstance(value, str) and value in SCALARS:
                ground = True
                continue
            if isinstance(value, Variable):
                incoming = self.analysis.heap.get(value)
                if incoming is None:
                    return False
                pending.append(incoming)
            elif isinstance(value, Allocation):
                roles = {'list': ('element',), 'tuple_sequence': ('element',),
                         'deque': ('element',), 'set': ('key',),
                         'dict': ('key', 'value')}.get(value.category)
                if roles is None:
                    return False
                for role in roles:
                    incoming = self.analysis.heap.get(Variable(value.site, role))
                    if incoming is None:
                        return False
                    pending.append(incoming)
            elif isinstance(value, TupleValue):
                ground = True
                pending.extend(value.fields)
            elif isinstance(value, Computed):
                pending.extend(value.operands)
            elif isinstance(value, Projection):
                pending.append(value.receiver)
            elif isinstance(value, ShapeConstraint):
                # A lower-bound ABI shape is not complete payload provenance.
                return False
            elif isinstance(value, (ListType, TupleSequenceType)):
                pending.append(value.element)
            elif isinstance(value, TupleType):
                # Named tuple descriptors can carry source protocol metadata.
                if type(value) is not TupleType:
                    return False
                ground = True
                pending.extend(value.fields)
            elif isinstance(value, SetType):
                pending.append(value.key)
            elif isinstance(value, DictType):
                pending.extend((value.key, value.value))
            else:
                return False
        return ground

    def value(self, scope, node):
        return scope.values.get(self.unit.ordinal(node))

    def call(self, definition, node, scope):
        from .native_constraints import FunctionValue
        from .references import BuiltinIdentity
        fact = scope.calls.get(self.unit.ordinal(node))
        if (fact is None or fact.identity.unknown or fact.identity.unbound
                or not fact.identity.alternatives):
            return self.unknown(definition, node, 'missing or open actual callable identity')
        demand = NONE
        for target in fact.identity.alternatives:
            if isinstance(target, FunctionValue):
                if target.definition not in self.nodes:
                    demand = demand.join(self.unknown(definition, node, 'unregistered source callee'))
                else:
                    self.edges[definition].add(target.definition)
            elif isinstance(target, BuiltinIdentity):
                if target.name == 'input':
                    demand = demand.join(INPUT)
                elif target.name == 'print':
                    values = (*fact.positional, *(value for _, value in fact.keywords))
                    demand = demand.join(OUTPUT if all(self.data(value) for value in values)
                                         else self.unknown(definition, node, 'open print argument protocol'))
                elif target.name in PURE_BUILTINS and all(
                        self.data(value) for value in (*fact.positional, *(value for _, value in fact.keywords))):
                    continue
                else:
                    demand = demand.join(self.unknown(definition, node, 'unregistered builtin or implicit callback role'))
            else:
                demand = demand.join(self.unknown(definition, node, 'unregistered native or MAY callable role'))
        return demand

    def body(self, definition, body, scope):
        demand = NONE
        pending = list(reversed(body))
        simple = (ast.Constant, ast.Name, ast.Return,
                  ast.Expr, ast.Pass, ast.Break, ast.Continue, ast.Global, ast.Nonlocal,
                  ast.List, ast.Tuple, ast.Slice,
                  ast.NamedExpr, ast.JoinedStr, ast.comprehension,
                  ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context)
        while pending:
            node = pending.pop()
            if isinstance(node, ast.Call):
                demand = demand.join(self.call(definition, node, scope))
            elif isinstance(node, ast.keyword):
                if not isinstance(node.arg, str):
                    demand = demand.join(self.unknown(definition, node, 'mapping argument expansion has no closed service role'))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if node.value is not None and any(isinstance(part, (ast.Tuple, ast.List, ast.Subscript))
                        for target in targets for part in ast.walk(target)):
                    if not self.data(self.value(scope, node.value)):
                        demand = demand.join(self.unknown(definition, node, 'open unpack/store RHS protocol'))
            elif isinstance(node, (ast.Set, ast.Dict)):
                values = node.elts if isinstance(node, ast.Set) else [value for value in (*node.keys, *node.values) if value is not None]
                if not all(self.data(self.value(scope, value)) for value in values):
                    demand = demand.join(self.unknown(definition, node, 'open hash/equality/mapping payload protocol'))
            elif isinstance(node, ast.Starred):
                if isinstance(node.ctx, ast.Load) and not self.data(self.value(scope, node.value)):
                    demand = demand.join(self.unknown(definition, node, 'open starred expansion protocol'))
            elif isinstance(node, (ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
                                   ast.IfExp, ast.Subscript, ast.FormattedValue)):
                operands = [value for value in ast.iter_child_nodes(node) if isinstance(value, ast.expr)]
                if not all(self.data(self.value(scope, value)) for value in operands):
                    demand = demand.join(self.unknown(definition, node, 'open builtin data protocol'))
            elif isinstance(node, (ast.If, ast.While, ast.Assert)):
                if not self.data(self.value(scope, node.test)):
                    demand = demand.join(self.unknown(definition, node, 'open truth protocol'))
                if isinstance(node, ast.Assert) and node.msg is not None and not self.data(self.value(scope, node.msg)):
                    demand = demand.join(self.unknown(definition, node, 'open assertion message protocol'))
            elif isinstance(node, (ast.For, ast.ListComp, ast.SetComp, ast.DictComp)):
                iterable = [node.iter] if isinstance(node, ast.For) else [part.iter for part in node.generators]
                if not all(self.data(self.value(scope, value)) for value in iterable):
                    demand = demand.join(self.unknown(definition, node, 'open iteration protocol'))
                if isinstance(node, ast.SetComp) and not self.data(self.value(scope, node.elt)):
                    demand = demand.join(self.unknown(definition, node, 'open set comprehension key protocol'))
                if isinstance(node, ast.DictComp) and not all(self.data(self.value(scope, value)) for value in (node.key, node.value)):
                    demand = demand.join(self.unknown(definition, node, 'open dictionary comprehension payload protocol'))
            elif isinstance(node, ast.comprehension):
                if not all(self.data(self.value(scope, value)) for value in (node.iter, *node.ifs)):
                    demand = demand.join(self.unknown(definition, node, 'open comprehension iteration/truth protocol'))
            elif isinstance(node, ast.AugAssign):
                if not all(self.data(self.value(scope, value)) for value in (node.target, node.value)):
                    demand = demand.join(self.unknown(definition, node, 'open inplace protocol'))
            elif not isinstance(node, simple):
                # Attribute access, nested definitions, imports, generators,
                # cleanup and new syntax retain the previous service ABI.
                demand = demand.join(self.unknown(definition, node, 'unregistered executable source operation'))
            pending.extend(reversed(list(ast.iter_child_nodes(node))))
        return demand


def prepare(specializations):
    result = getattr(specializations, 'service_demands', None)
    if (result is None or result.unit is not specializations.source_unit
            or result.analysis is not specializations.type_analysis):
        result = Registry(specializations.source_unit, specializations.type_analysis,
                          specializations.functions.definitions)
        specializations.service_demands = result
    return result


def demand(function):
    return getattr(function, 'services', None) or UNKNOWN
