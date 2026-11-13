"""Owned source-generator cursor captures use the actual validated Rc graph.

This initial facet covers the core builtin cursor layouts and owned integer-word
maps. Unknown providers/callable captures remain explicit capability boundaries.
"""
from dataclasses import dataclass
from types import MappingProxyType

from .native_types import (EmptyType,ListType,TupleType,TupleSequenceType,
                          UnionType,NullableType,MaybeType)


def contains_cursor(kind):
    if getattr(kind,'_native_class_iterator',False):return True
    if isinstance(kind,(ListType,TupleSequenceType)):return contains_cursor(kind.element)
    if isinstance(kind,TupleType):return any(contains_cursor(child)for child in kind.fields)
    if isinstance(kind,UnionType):return any(contains_cursor(child)for child in kind.alternatives)
    if isinstance(kind,(NullableType,MaybeType)):return contains_cursor(kind.value)
    return False


@dataclass(frozen=True)
class GraphReceipt:
    model:object
    edges:object
    members:tuple


def capture(model,raw_edges):
    """Called only after the ordinary lexical ownership DFS succeeds."""
    registry=getattr(model,'iterators',None)
    if registry is None:return
    candidates=[record for record in registry.records
                if record.operation=='source_generator'and record.generator_plan.reachable
                and any(contains_cursor(kind)for kind in record.kind._native_owned_kinds)]
    if not candidates:return
    model.source_generator_cursor_graph=GraphReceipt(model,
        MappingProxyType({node:frozenset(children)for node,children in raw_edges.items()}),
        tuple(registry.records))


class Proof:
    def __init__(self,model,plan):
        self.model=model;self.plan=plan
        self.receipt=getattr(model,'source_generator_cursor_graph',None)
        self.root=('iterator',plan.source_generator.record.index)

    def fail(self,message,kind=None):
        from .native_classes import ClassUnsupported
        raise ClassUnsupported(self.plan.node,message,
            types=()if kind is None else(('retained cursor payload',kind),),
            proof='complete acyclic owned source-generator cursor graph')

    def require_receipt(self):
        if (self.receipt is None or self.receipt.model is not self.model
                or not getattr(self.model,'final',False)):
            self.fail('source-generator iterator retention needs a successful final lexical ownership-graph receipt; that coverage proof is unavailable')

    def registered(self,kind):
        self.require_receipt()
        if (not self.model.iterators.owns(kind)or kind.index>=len(self.receipt.members)
                or self.receipt.members[kind.index]is not kind.record):
            self.fail('this source-generator iterator capture is not a member of the actual validated cursor registry; its retained state has no ownership-graph coverage',kind)
        return ('iterator',kind.index)

    def targets(self,kind):
        from .native_classes import InstanceType
        from .native_aot_callables import function_kind
        from .references import BuiltinIdentity
        if isinstance(kind,EmptyType)or kind in {'int','bool','int_bool','none','float','str','bytes','range'}:return set()
        if isinstance(kind,(ListType,TupleSequenceType)):return self.targets(kind.element)
        if isinstance(kind,TupleType):
            return set().union(*(self.targets(child)for child in kind.fields))
        if isinstance(kind,(NullableType,MaybeType)):return self.targets(kind.value)
        if isinstance(kind,UnionType):
            return set().union(*(self.targets(child)for child in kind.alternatives))
        if getattr(kind,'_native_class_iterator',False):return {self.registered(kind)}
        if function_kind(kind):
            if kind.targets and all(isinstance(target,BuiltinIdentity)for target in kind.targets):return set()
            self.fail('this source-generator cursor retains a source, module or custom callable capture; its suspended callable/environment ownership facet is not implemented by the initial canonical-builtin cursor adapter',kind)
        if isinstance(kind,InstanceType):
            if getattr(self.model,'gc_classes',()):
                self.fail('this source-generator cursor can retain a collected class instance; suspended cursor roots for the class collector are not implemented',kind)
            return {('object',kind.name)}
        self.fail('this source-generator cursor has an unresolved or unsupported retained payload; an owned frame facet for that value has not been implemented',kind)

    def iterator_targets(self,record,root_types):
        from .native_source_generators import ADAPTER
        from .native_source_generator_environments import lifetime_edges
        from .native_integer_word_maps import IntegerWordMap
        if ('iterator',record.index)==self.root:
            if (record is not self.plan.source_generator.record
                    or getattr(record,'adapter',None)is not ADAPTER
                    or record.generator_plan is not self.plan):
                self.fail('the source-generator frame does not match its registered ownership-graph root')
            if root_types is None:
                self.fail('the source-generator root requires its complete solved frame schemas before cursor retention can be certified')
            from .native_class_binding_contexts import parameter
            if parameter(self.model,self.plan):
                self.fail('source-generator iterator retention with a captured class-definition context needs its additional owned class-reference facet; that suspended context is not implemented')
            result=set().union(*(self.targets(kind)for kind in root_types))
            extra={self.root:set()};lifetime_edges(self.model,record,extra)
            result.update(extra[self.root]);return result
        adapter=getattr(record,'adapter',None)
        if adapter is not None:
            if type(adapter)is not IntegerWordMap or record.operation!='map'or adapter.source_kind not in {'str','bytes'}:
                self.fail('this source-generator cursor uses provider '+repr(record.operation)+' whose suspended owned-state facet is not implemented')
            from .native_classes import shape
            from .references import BuiltinIdentity
            callback=shape(record.callback)
            if getattr(callback,'targets',())!=(BuiltinIdentity('int'),):
                self.fail('the integer-word cursor has no canonical int callable identity for its owned snapshot facet')
        elif record.operation not in {'source','reverse','map','zip','filter','enumerate'}:
            self.fail('this source-generator cursor uses provider '+repr(record.operation)+' whose retained typed-state ownership facet is not implemented')
        return set().union(*(self.targets(kind)for kind in record.kind._native_owned_kinds))

    def node_targets(self,node,root_types):
        from .native_classes import shape
        tag=node[0]
        if tag=='iterator':
            index=node[1]
            if index>=len(self.receipt.members)or index>=len(self.model.iterators.records):
                self.fail('a retained cursor ownership node is absent from the validated registry')
            record=self.model.iterators.records[index];self.registered(record.kind)
            return self.iterator_targets(record,root_types)
        if tag=='environment':
            environment=self.model.lexical.environments.get(node[1])
            if environment is None or not environment.plan.reachable:
                self.fail('a retained lexical environment has no actual reachable owned layout')
            result=set().union(*(self.targets(shape(cell))for cell in environment.defaults.values()))
            if environment.parent:result.add(('environment',environment.parent))
            from .native_lexical_capture_views import shared,cell_node
            for name,cell in environment.fields.items():
                if shared(self.model,environment.scope,name):
                    result.add(cell_node(environment.scope,name))
                else:result.update(self.targets(shape(cell)))
            return result
        if tag=='lexical_cell':
            environment=self.model.lexical.environments.get(node[1])
            from .native_lexical_capture_views import shared,cell_node
            if (environment is None or node[2]not in environment.fields
                    or not shared(self.model,node[1],node[2])or cell_node(node[1],node[2])!=node):
                self.fail('a retained shared lexical cell has no matching actual owned binding')
            return self.targets(shape(environment.fields[node[2]]))
        if tag=='object':
            owner=self.model.classes.get(node[1])
            if owner is None or not owner.used:
                self.fail('a retained source instance has no actual owned class-field layout')
            return set().union(*(self.targets(shape(field.cell))for field in owner.fields.values()))
        self.fail('source-generator cursor retention reaches ownership node '+repr(node)+'; an owned suspension facet for that node has not been implemented')

    def check(self,node,*,root_types=None):
        self.require_receipt();done=set();visiting=set()
        def visit(current):
            if current in visiting:
                self.fail('source-generator cursor retention reaches a raw reference cycle '+repr(current)+'; cycle-aware suspended cursor ownership is not implemented')
            if current in done:return
            if current not in self.receipt.edges:
                self.fail('a source-generator cursor ownership node '+repr(current)+' has no validated raw-graph coverage; absence is not an acyclicity proof')
            visiting.add(current)
            expected=self.node_targets(current,root_types)
            if not expected.issubset(self.receipt.edges[current]):
                self.fail('source-generator retained ownership edges changed after validation; the actual typed frame has incomplete raw-graph coverage')
            for child in self.receipt.edges[current]:visit(child)
            visiting.remove(current);done.add(current)
        visit(node)


def cursor(model,plan,kind):
    if not getattr(kind,'_native_class_iterator',False):return False
    proof=Proof(model,plan);node=proof.registered(kind)
    # This proves the actual cursor subtree only. The complete frame/root
    # obligation is discharged after all local schemas pass their own guards.
    proof.check(node)
    return True


def frame(model,plan,kinds,*,direct):
    if not any(contains_cursor(kind)for kind in kinds):return
    proof=Proof(model,plan)
    proof.require_receipt()
    if proof.root not in proof.receipt.edges:proof.fail('the source-generator frame root is absent from its validated ownership graph')
    proof.check(proof.root,root_types=tuple(direct))
