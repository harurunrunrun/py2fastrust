"""MAY-alias mutation summaries for actual native loop and call scopes.

Heap-site summaries never imply one runtime object. A list may be borrowed
across iteration only when every possible source allocation is disjoint from
all reached mutations and no unmodeled/reentrant operation can run.
"""
from contextlib import contextmanager
from dataclasses import dataclass,field


@dataclass(frozen=True)
class IterationAccess:
    readonly:bool
    sources:frozenset
    mutations:frozenset
    opaque:bool


@dataclass
class Effects:
    mutations:set=field(default_factory=set)
    opaque:bool=False
    global_reads:dict=field(default_factory=dict)
    closed_inputs:set=field(default_factory=set)


class Recorder:
    def __init__(self,solver):
        self.solver=solver
        self.reset()

    def reset(self):
        self.loops=[]
        self.functions=[]
        self.records={}
        self.summaries={}
        self.epoch_aliases={}
        self.opaque_epochs=set()
        self.epoch_related=set()
        self.epoch_sites={}
        self.epoch_receivers={}
        self.raw_writes=set()
        self.field_updates={}
        self.opaque_memory=False
        self.incomplete_analysis=False
        self.unknown_heap=False
        self.protocol_inputs=set()

    def mutation(self,receiver):
        for effects in (*self.loops,*self.functions):effects.mutations.add(receiver)

    def unknown(self):
        self.unknown_heap=True
        for effects in (*self.loops,*self.functions):effects.opaque=True

    def incomplete(self):
        # Reaching a CFG iteration cap does not establish disjointness, even
        # for nested loops visited only before that unfinished fixed point.
        self.incomplete_analysis=True
        self.unknown()

    def implicit(self,*items):
        # Unmodeled protocols can change aliases before a later loop, and a
        # reentrant callback can revisit an earlier function. Preconditions and
        # unknown heap effects therefore apply to the whole analyzed program.
        self.protocol_inputs.add(items)
        for effects in (*self.loops,*self.functions):effects.closed_inputs.add(items)
        if not all(self.closed(item)for item in items):self.unknown()

    def global_read(self,name,item):
        if not self.functions:return
        from .native_constraints import BOTTOM
        value=self.solver.provenance(item)
        for effects in self.functions:
            origins,paths=effects.global_reads.get(name,(BOTTOM,BOTTOM))
            effects.global_reads[name]=(origins.join(value),paths.join(item))

    def matches_globals(self,context,namespace):
        from .native_constraints import MISSING
        effects=self.summaries.get(context)
        return effects is not None and all(
            self.solver.provenance(namespace.get(name,MISSING))==origins
            and namespace.get(name,MISSING)==paths
            for name,(origins,paths)in effects.global_reads.items())

    def store(self,receiver,role,item):
        # Keep symbolic receivers, including projections through a parent that
        # is cleared/refilled by another frame. Type-layout fields deliberately
        # stay separate from these conservative object-reference facts.
        self.raw_writes.add((receiver,role,item))

    def alias_epoch(self,fresh,receiver):
        from .native_constraints import Allocation
        for part in fresh.alternatives:
            if isinstance(part,Allocation):
                self.epoch_receivers.setdefault(part,set()).add(receiver)
                self.link_epoch(part,receiver)

    def link_epoch(self,fresh,receiver):
        from .native_constraints import Allocation
        previous=self.provenance(receiver)
        roots={part for part in previous.alternatives if isinstance(part,Allocation)}
        before=len(self.epoch_aliases.get(fresh,()))
        self.epoch_aliases.setdefault(fresh,set()).update(roots)
        self.epoch_related.update(roots);self.epoch_related.add(fresh)
        for part in (*roots,fresh):self.epoch_sites.setdefault(part.site,set()).add(part)
        return len(self.epoch_aliases[fresh])!=before

    def stabilize(self):
        from .native_constraints import Allocation,Variable,BOTTOM
        changed=True
        while changed:
            changed=False
            for fresh,receivers in self.epoch_receivers.items():
                for receiver in receivers:changed|=self.link_epoch(fresh,receiver)
            for receiver,role,item in self.raw_writes:
                for part in self.provenance(receiver).alternatives:
                    if not isinstance(part,Allocation):continue
                    variable=Variable(part.site,role)
                    old=self.field_updates.get(variable,BOTTOM)
                    new=old.join(item)
                    if old!=new:self.field_updates[variable]=new;changed=True
        self.opaque_epochs.clear()
        for fresh,receivers in self.epoch_receivers.items():
            for receiver in receivers:
                resolved=self.provenance(receiver)
                if(resolved.unknown or resolved.unbound or not resolved.alternatives
                        or any(not isinstance(part,Allocation)for part in resolved.alternatives)):
                    self.opaque_epochs.add(fresh)
        for receiver,_,_ in self.raw_writes:
            resolved=self.provenance(receiver)
            if(resolved.unknown or resolved.unbound or not resolved.alternatives
                    or any(not isinstance(part,Allocation)for part in resolved.alternatives)):
                self.opaque_memory=True

    def origins(self,allocation):
        pending=[allocation];seen=set();roots=set();unknown=False
        while pending:
            current=pending.pop()
            if current in seen:continue
            seen.add(current)
            unknown|=current in self.opaque_epochs
            if current in self.epoch_aliases:pending.extend(self.epoch_aliases[current])
            else:roots.add(current)
        return roots,unknown or not roots

    def provenance(self,item,active=frozenset()):
        """Resolve reference fields across every content epoch of an object.

        Type inference keeps epochs separate so clear() may change a uniquely
        owned container's element layout. Identity proofs must additionally see
        children stored through aliases or caller-owned clear/refill functions.
        """
        from .native_constraints import (Value,Variable,Projection,TupleValue,IteratorValue,ShapeConstraint,BOTTOM,UNKNOWN,value)
        result=Value(unbound=item.unbound,unknown=item.unknown)
        for part in item.alternatives:
            if isinstance(part,(Variable,Projection)):
                if part in active:
                    continue
                if isinstance(part,Projection):
                    receiver=self.provenance(part.receiver,active|{part})
                    incoming=self.solver.field_values(receiver,part.role,part.index)
                else:
                    incoming=self.solver.variables.get(part,BOTTOM).join(self.field_updates.get(part,BOTTOM))
                    owners=self.epoch_sites.get(part.allocation,())
                    for owner in owners:
                        roots,unknown=self.origins(owner)
                        if unknown:incoming=incoming.join(UNKNOWN)
                        for alias in self.epoch_related:
                            candidate,unknown=self.origins(alias)
                            if roots.intersection(candidate):
                                field=Variable(alias.site,part.field)
                                incoming=incoming.join(self.solver.variables.get(field,BOTTOM)).join(self.field_updates.get(field,BOTTOM))
                                if unknown:incoming=incoming.join(UNKNOWN)
                result=result.join(self.provenance(incoming,active|{part}))
            elif isinstance(part,ShapeConstraint):continue
            elif isinstance(part,TupleValue):result=result.join(value(TupleValue(tuple(self.provenance(field,active)for field in part.fields))))
            elif isinstance(part,IteratorValue):
                sources=set(part.sources);may_call=part.may_call
                for source in part.source_inputs:
                    resolved=self.provenance(source,active)
                    sources.update(self.solver.iteration_allocations(resolved))
                    may_call|=self.iteration_may_call_resolved(resolved)
                result=result.join(value(IteratorValue(self.provenance(part.item,active),frozenset(sources),may_call,part.source_inputs)))
            else:result=result.join(value(part))
        return result

    def iterator_inputs(self,items):
        # Rewrapping an iterator preserves its retained input roots rather than
        # growing an abstract iterator-inside-iterator history on each back edge.
        from .native_constraints import Value,IteratorValue,value
        result=[]
        for item in items:
            plain=set()
            for part in item.alternatives:
                if isinstance(part,IteratorValue):
                    result.extend(part.source_inputs)
                    result.extend(value(source)for source in part.sources)
                else:plain.add(part)
            if plain or item.unknown or item.unbound:
                result.append(Value(frozenset(plain),item.unbound,item.unknown))
        return frozenset(result)

    def sealed_mapper(self,callback,inputs,*,filtering=False):
        from .references import BuiltinIdentity
        # These exact builtin identities cannot invoke a source protocol when
        # all possible item values are closed builtin data. Other callbacks
        # retain their deferred/reentrant classification.
        if callback.unknown or callback.unbound or not callback.alternatives:return False
        for part in callback.alternatives:
            if filtering and part=='none':continue
            if not isinstance(part,BuiltinIdentity)or part.name not in{'int','float','bool','str','bytes','abs','len','ord','hash','bin','oct','hex'}:return False
        items=tuple(self.solver.field_values(item,'iteration')for item in inputs)
        self.implicit(*items)
        return all(self.closed(item)for item in items)

    def iteration_allocations(self,item):
        return self.solver.iteration_allocations(self.provenance(item))

    def latent(self,item):
        from .native_constraints import IteratorValue
        item=self.provenance(item)
        return item.unknown or any(isinstance(part,IteratorValue)and part.may_call for part in item.alternatives)

    def iteration_may_call(self,item):
        return self.iteration_may_call_resolved(self.provenance(item))

    def iteration_may_call_resolved(self,item):
        from .native_constraints import Allocation,IteratorValue,TupleValue
        from .native_types import ListType,SharedListType,DequeType,TupleType,TupleSequenceType
        from .native_key_types import DictType,SetType
        if item.unknown or item.unbound or not item.alternatives:return True
        for part in item.alternatives:
            if isinstance(part,IteratorValue):
                if part.may_call:return True
            elif isinstance(part,Allocation):
                if part.category not in{'list','dict','set','deque','tuple_sequence'}:return True
            elif isinstance(part,TupleValue):continue
            elif type(part)in{ListType,SharedListType,DequeType,TupleType,TupleSequenceType,DictType,SetType}:continue
            elif part not in{'str','bytes'}:return True
        return False

    def closed(self,item,active=frozenset(),empty=False):
        from .native_constraints import Allocation,TupleValue,IteratorValue,Computed,value
        from .native_types import (shared_payload,ListType,SharedListType,DequeType,TupleType,TupleSequenceType,NullableType,UnionType,EmptyType)
        from .native_key_types import DictType,SetType
        def kind(value):
            if getattr(value,'_native_named_tuple',False):return False
            if isinstance(value,EmptyType):return True
            if type(value)in{ListType,SharedListType,DequeType,TupleSequenceType}:return kind(value.element)
            if type(value)is DictType:return kind(value.key)and kind(value.value)
            if type(value)is SetType:return kind(value.key)
            if isinstance(value,TupleType):return all(kind(field)for field in value.fields)
            if isinstance(value,NullableType):return kind(value.value)
            if isinstance(value,UnionType):return all(kind(part)for part in value.alternatives)
            return value=='float'or shared_payload(value)
        resolved=self.provenance(item)
        if resolved.unknown or resolved.unbound:return False
        if not resolved.alternatives:return empty
        for part in resolved.alternatives:
            if isinstance(part,Allocation):
                if part in active:continue
                if part.category in{'list','tuple_sequence','deque'}:roles=('element',)
                elif part.category=='set':roles=('key',)
                elif part.category=='dict':roles=('key','value')
                else:return False
                if not all(self.closed(self.solver.field(part,role),active|{part},True)for role in roles):return False
            elif isinstance(part,TupleValue):
                if not all(self.closed(field,active)for field in part.fields):return False
            elif isinstance(part,IteratorValue):
                if part.may_call or not self.closed(part.item,active):return False
            elif isinstance(part,Computed):
                if not kind(self.solver.kind(value(part))):return False
            elif not kind(part):return False
        return True

    def method_stores(self,identity,args,keywords):
        receiver,name=identity.receiver,identity.name
        if name in{'append','appendleft','add'}and args:
            self.store(receiver,'key'if name=='add'else'element',args[0])
        elif name=='insert'and len(args)>1:self.store(receiver,'element',args[1])
        elif name in{'extend','extendleft'}and args:
            self.store(receiver,'element',self.solver.field_values(args[0],'iteration'))
        elif name=='update'and args:
            from .native_key_types import DictType,SetType
            kind=self.solver.kind(receiver)
            if isinstance(kind,SetType):self.store(receiver,'key',self.solver.field_values(args[0],'iteration'))
            elif isinstance(kind,DictType):
                self.store(receiver,'key',self.solver.field_values(args[0],'iteration'))
                self.store(receiver,'value',self.solver.field_values(args[0],'value'))
        elif name=='setdefault'and args:
            from .native_constraints import value
            self.store(receiver,'key',args[0])
            self.store(receiver,'value',args[1]if len(args)>1 else value('none'))

    def call(self,callee,args,keywords):
        from .native_constraints import FunctionValue,MethodValue
        for identity in callee.alternatives:
            if isinstance(identity,MethodValue):self.method_stores(identity,args,keywords)
        from .references import BuiltinIdentity,DequeConstructor
        from .native_stdio import _IOReference
        if callee.unknown or callee.unbound or not callee.alternatives:self.unknown()
        for identity in callee.alternatives:
            if isinstance(identity,FunctionValue):
                definition=self.solver.graph.nodes[identity.definition]
                scope=self.solver.graph.unit.scope_for(definition)
                captured=any(symbol.flags&{'free','nonlocal'}for symbol in scope.symbols)
                if identity.definition in self.solver.active or getattr(definition,'decorator_list',())or captured:self.unknown()
                continue
            if isinstance(identity,DequeConstructor)or isinstance(identity,_IOReference)and identity.name=='reader':
                self.implicit(*args,*(value for _,value in keywords))
                if all(self.closed(item)for item in(*args,*(value for _,value in keywords))):continue
                self.unknown();continue
            if isinstance(identity,MethodValue):
                self.implicit(identity.receiver,*args,*(value for _,value in keywords))
                if identity.name in{'append','appendleft','extend','extendleft','clear','reverse','rotate','sort','pop','popleft','insert','remove','add','discard','update','setdefault','popitem','difference_update','intersection_update','symmetric_difference_update'}:
                    self.mutation(identity.receiver)
                kind=self.solver.kind(identity.receiver)
                from .native_types import ListType,DequeType
                if isinstance(kind,(ListType,DequeType))and self.closed(identity.receiver):
                    if identity.name in {'append','appendleft','pop','popleft','clear','reverse','rotate','sort','insert','remove','copy','count','index'}:
                        if all(self.closed(value)for value in(*args,*(value for _,value in keywords))):continue
                    if identity.name in{'extend','extendleft'}and all(self.closed(value)for value in args):continue
                from .native_key_types import DictType,SetType
                if type(kind)is DictType and identity.name=='update':
                    # Mapping/keyword/pair sources have different insertion
                    # protocols; the type solver does not model all of them.
                    self.unknown();continue
                if type(kind)in{DictType,SetType}and self.closed(identity.receiver):
                    if identity.name in{'add','discard','remove','clear','update','pop','popitem','setdefault','copy','get','keys','values','items','difference_update','intersection_update','symmetric_difference_update'}:
                        if all(self.closed(value)for value in(*args,*(value for _,value in keywords))):continue
                if kind in {'int','bool','int_bool','float','str','bytes'}and all(self.closed(value)for value in(*args,*(value for _,value in keywords))):continue
                self.unknown();continue
            if isinstance(identity,BuiltinIdentity):
                if identity.name in{'map','filter'}:
                    # Construction captures an iterable; its callback remains
                    # deferred. Consumption is classified by IteratorValue.
                    inputs=args[1:]
                    checked=(*inputs,*(value for _,value in keywords))
                    self.implicit(*checked)
                    if all(self.closed(item)for item in checked):continue
                    self.unknown();continue
                self.implicit(*args,*(value for _,value in keywords))
                if identity.name in {'int','float','bool','str','bytes','abs','len','pow','ord','hash','bin','oct','hex','input','print','range','iter','reversed','enumerate','zip','list','tuple','set','dict','frozenset','sum','any','all','min','max','isinstance','issubclass','exit','quit'}:
                    if all(self.closed(value)for value in(*args,*(value for _,value in keywords))):continue
                self.unknown();continue
            from .native_module_calls import BuiltinRef
            if isinstance(identity,BuiltinRef)and(identity.module in {'math','bisect','heapq'}or identity.module=='sys'and identity.name in{'exit','setrecursionlimit','getrecursionlimit'}):
                self.implicit(*args,*(value for _,value in keywords))
                if all(self.closed(value)for value in(*args,*(value for _,value in keywords))):continue
            self.unknown()

    @contextmanager
    def loop(self,source,context,site):
        opaque=self.iteration_may_call(source)if site is not None else False
        if opaque:self.unknown()
        if site is None:
            yield
            return
        effects=Effects(opaque=opaque);self.loops.append(effects)
        try:yield
        except BaseException:
            effects.opaque=True
            raise
        finally:
            assert self.loops.pop()is effects
            previous=self.records.get((context,site))
            if previous is not None:
                old_source,old_effects=previous
                source=source.join(old_source)
                effects.mutations.update(old_effects.mutations)
                effects.opaque|=old_effects.opaque
                effects.closed_inputs.update(old_effects.closed_inputs)
            self.records[(context,site)]=source,effects

    @contextmanager
    def function(self,context):
        effects=Effects();self.functions.append(effects)
        try:yield
        except BaseException:
            effects.opaque=True
            raise
        finally:
            assert self.functions.pop()is effects
            self.summaries[context]=effects

    def replay(self,context,namespace):
        from .native_constraints import MISSING
        effects=self.summaries.get(context)
        if effects is None:
            self.unknown()
            return
        for receiver in effects.mutations:self.mutation(receiver)
        for inputs in effects.closed_inputs:self.implicit(*inputs)
        for name in effects.global_reads:self.global_read(name,namespace.get(name,MISSING))
        if effects.opaque:self.unknown()

    def export(self,key):
        from .native_constraints import Allocation,Value,TupleValue,canonical_kind
        from .native_types import immutable
        self.stabilize()
        if any(not all(self.closed(item)for item in inputs)for inputs in self.protocol_inputs):self.unknown()
        result={}
        for(context,site),record in self.records.items():
            sources=set();mutations=set();opaque=False
            for source,effects in(record,):
                resolved=self.provenance(source)
                raw=self.solver.iteration_allocations(resolved)
                opaque|=(effects.opaque or self.opaque_memory or self.incomplete_analysis or self.unknown_heap or resolved.unknown or resolved.unbound or not raw
                         or self.iteration_may_call(source)
                         or any(not all(self.closed(item)for item in inputs)for inputs in effects.closed_inputs))
                for allocation in raw:
                    roots,unknown=self.origins(allocation)
                    sources.update(roots);opaque|=unknown
                for receiver in effects.mutations:
                    resolved=self.provenance(receiver)
                    opaque|=resolved.unknown or resolved.unbound or not resolved.alternatives
                    for part in resolved.alternatives:
                        if isinstance(part,Allocation):
                            roots,unknown=self.origins(part)
                            mutations.update(roots);opaque|=unknown
                        elif not isinstance(part,TupleValue):
                            kind=self.solver.kind(Value(frozenset({part})))
                            # A shape without allocation provenance cannot be
                            # proved disjoint from a captured list. Scalar
                            # augmented assignment only replaces its value.
                            if kind is None or not immutable(canonical_kind(kind)):opaque=True
            fact=IterationAccess(bool(sources)and not opaque and not sources.intersection(mutations),frozenset(sources),frozenset(mutations),opaque)
            target=result.setdefault(key(context),{})
            if site in target:
                old=target[site];fact=IterationAccess(old.readonly and fact.readonly,old.sources|fact.sources,old.mutations|fact.mutations,old.opaque or fact.opaque)
                fact=IterationAccess(fact.readonly and not fact.sources.intersection(fact.mutations),fact.sources,fact.mutations,fact.opaque)
            target[site]=fact
        return result


def borrowable_for(plan):
    from .native_stream_plans import ProducerKind
    if plan.kind is ProducerKind.VALUE:return True
    return (plan.kind in{ProducerKind.ITER,ProducerKind.ENUMERATE}
            and len(plan.sources)==1 and borrowable_for(plan.sources[0]))


def borrow_stream(generator,node,value,planner):
    """Scope one immutable lease to a proved direct for-loop's execution.

    One-source iter/enumerate adapters emit through this same loop scope, after
    all eager arguments. Cursor-combining adapters retain their existing live
    cursors until their construction/lease phases share an explicit carrier.
    """
    statement=getattr(planner,'iteration_site',None)
    if statement is None:return None
    from .native_constraint_lowering import facts_for
    facts,site=facts_for(generator,statement)
    proof=None if facts is None else facts.iteration_access.get(site)
    if proof is None or not proof.readonly:return None
    owner,lease,guard,cursor,length=(generator.temporary()for _ in range(5))
    result=planner.leaf(f'let {owner}={value.code};','',cursor,
                        ((value.kind.element,'@',True),),
                        unpack_length=(f'let {length}={owner}.borrow().len();',length))
    emit=result.emit_body
    def leased(action,scope,line,continue_label=None):
        body=emit(action,scope,line,continue_label)
        # Moving the captured handle into this block releases it on every
        # ordinary/control-flow/error exit, before the loop's else or successor.
        return ('{'+f'let {lease}={owner};let {guard}={lease}.borrow();'
                f'let {cursor}={guard}.iter().cloned();'+body+'}')
    result.emit_body=leased
    result.reversible=False
    return result
