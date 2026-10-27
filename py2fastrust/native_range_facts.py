"""Pure region, owner and affine-index facts over the shared semantic graph.

These are compile-time proofs and guarded-operation plans. They never invoke a
code generator or evaluate a Python source expression. Runtime guards must use
already captured range operands and the actual immutable owner's byte length.
"""
from dataclasses import dataclass
from types import MappingProxyType

from .literal_semantics import integer_policy
from .native_constraints import target_names,MethodValue,FunctionValue
from .references import BuiltinIdentity


@dataclass(frozen=True)
class AffineTerm:
    operation: str
    operands: tuple=()
    site: int|None=None
    value: object=None


@dataclass(frozen=True)
class RangeDomain:
    call_site: int
    target: str
    start_site: int|None
    stop_site: int
    step_site: int|None
    start_default: int=0
    step_default: int=1
    unit_step: int=1


@dataclass(frozen=True)
class OwnerRef:
    name: str
    binding_site: int
    kind: str="str"
    read_sites: tuple=()


@dataclass(frozen=True)
class AccessFact:
    index_site: int
    owner: OwnerRef
    affine: AffineTerm
    coefficient: int
    invariants: frozenset


@dataclass(frozen=True)
class EffectFact:
    site: int
    kind: str
    names: frozenset=frozenset()
    may_raise: bool=False
    reason: str=""


@dataclass(frozen=True)
class RegionFact:
    site: int|tuple
    domain: RangeDomain|None
    readonly_owners: tuple[OwnerRef,...]
    accesses: tuple[AccessFact,...]
    invariant_names: frozenset
    written_names: frozenset
    definitely_bound: frozenset
    effects: tuple[EffectFact,...]
    bits: int

    @property
    def vectorizable_when_guarded(self):
        """Necessary effect condition; dependency/control proofs remain required."""
        guarded={access.index_site for access in self.accesses}
        return bool(guarded) and all(effect.kind=="pure" and not effect.may_raise
                                    or effect.kind=="index" and effect.site in guarded
                                    for effect in self.effects)


class RegionAnalysis:
    def __init__(self,analysis,facts,bits):
        self.analysis=analysis
        self.graph=analysis.graph
        self.facts=facts
        self.bits=bits
        self.policy=integer_policy(bits)
        self.result={}

    def children(self,term):
        for operand in term.operands:
            if hasattr(operand,"operation"):yield operand
            elif isinstance(operand,tuple):
                yield from self.tuple_children(operand)

    def tuple_children(self,items):
        for item in items:
            if hasattr(item,"operation"):yield item
            elif isinstance(item,tuple):yield from self.tuple_children(item)

    def bound(self,term,kind=None):
        item=self.facts.values.get(term.site)
        return (term.operation=="name" and item is not None and not item.unbound and not item.unknown
                and (kind is None or self.facts.expressions.get(term.site)==kind))

    def callable(self,site,name):
        call=self.facts.calls.get(site)
        return (call is not None and not call.identity.unbound and not call.identity.unknown
                and bool(call.identity.alternatives)
                and all(isinstance(identity,BuiltinIdentity) and identity.name==name
                        for identity in call.identity.alternatives))

    def constant(self,term):
        if term.operation=="constant":
            literal=self.graph.literals.get(term.site)
            if literal is not None and literal.kind in {"int","bool"}:return self.policy.normalize(literal.value)
        if term.operation=="unary" and term.data in {"UAdd","USub"}:
            value=self.constant(term.operands[0])
            if value is not None:return self.policy.normalize(-value if term.data=="USub" else value)
        if term.operation=="binary" and term.data in {"Add","Sub","Mult"}:
            left,right=(self.constant(child) for child in term.operands)
            if left is not None and right is not None:
                return self.policy.normalize(left+right if term.data=="Add" else left-right if term.data=="Sub" else left*right)
        return None

    def domain(self,term,target):
        if target[0]!="name" or term.operation!="call" or not self.callable(term.site,"range"):return None
        _,arguments,keywords=term.operands
        if keywords or not 1<=len(arguments)<=3:return None
        start,stop=(None,arguments[0]) if len(arguments)==1 else arguments[:2]
        step=arguments[2] if len(arguments)==3 else None
        if step is not None and self.constant(step)!=1:return None
        return RangeDomain(term.site,target[1],None if start is None else start.site,stop.site,None if step is None else step.site)

    def affine(self,term,target,written):
        if term.operation=="constant":
            value=self.constant(term)
            return None if value is None else (AffineTerm("literal",site=term.site,value=value),0,frozenset())
        if term.operation=="name":
            if term.data==target:return AffineTerm("induction",site=term.site,value=target),1,frozenset()
            if (term.data in written or not self.bound(term)
                    or self.facts.expressions.get(term.site) not in {"int","bool","int_bool"}):return None
            return AffineTerm("invariant",site=term.site,value=term.data),0,frozenset({term.data})
        if term.operation=="call" and self.callable(term.site,"len"):
            _,arguments,keywords=term.operands
            if keywords or len(arguments)!=1:return None
            owner=arguments[0]
            if owner.operation!="name" or owner.data in written or not self.bound(owner,"str"):return None
            leaf=AffineTerm("owner_length",site=owner.site,value=owner.data)
            return AffineTerm("len",(leaf,),term.site),0,frozenset()
        if term.operation=="unary" and term.data in {"UAdd","USub"}:
            child=self.affine(term.operands[0],target,written)
            if child is None:return None
            value,coefficient,names=child
            return AffineTerm(term.data,(value,),term.site),(-coefficient if term.data=="USub" else coefficient),names
        if term.operation=="binary" and term.data in {"Add","Sub","Mult"}:
            left,right=(self.affine(child,target,written) for child in term.operands)
            if left is None or right is None:return None
            a,x,names=left;b,y,other=right
            if term.data=="Add":coefficient=x+y
            elif term.data=="Sub":coefficient=x-y
            elif x==y==0:coefficient=0
            elif x and y:return None
            else:
                multiplier=self.constant(term.operands[1 if x else 0])
                if multiplier is None:return None
                coefficient=(x or y)*multiplier
            return AffineTerm(term.data,(a,b),term.site),coefficient,names|other
        return None

    def call_effect(self,term):
        call=self.facts.calls.get(term.site)
        if call is None or call.identity.unknown or call.identity.unbound or len(call.identity.alternatives)!=1:
            return EffectFact(term.site,"unknown",reason="unproved callable identity")
        identity=next(iter(call.identity.alternatives))
        if isinstance(identity,FunctionValue):return EffectFact(term.site,"unknown",reason="user callback has no region effect summary")
        if isinstance(identity,BuiltinIdentity):
            if identity.name in {"print","input"}:return EffectFact(term.site,"io",may_raise=True)
            if identity.name=="len":
                args=term.operands[1]
                if len(args)==1 and not term.operands[2] and self.facts.expressions.get(args[0].site) in {"str","bytes","list_int","dict_int","set_int","matrix_int","deque_int"}:
                    return EffectFact(term.site,"pure")
            if identity.name in {"range","int","str","bool","float","ord","chr","abs","pow","tuple","list","set","dict"}:
                return EffectFact(term.site,"pure",may_raise=True)
            return EffectFact(term.site,"unknown",reason="callback-capable or unsummarized builtin")
        if isinstance(identity,MethodValue):
            kinds=identity.receiver.alternatives
            callee=term.operands[0]
            owner=callee.operands[0] if callee.operation=="attribute" else None
            names=frozenset({owner.data}) if owner is not None and owner.operation=="name" else frozenset()
            if kinds==frozenset({"str"}) and identity.name in {"count","find","index","strip","lstrip","rstrip","join","split","startswith","endswith"}:
                return EffectFact(term.site,"pure",may_raise=True)
            if identity.name in {"append","appendleft","extend","extendleft","add","clear","update","pop","popleft","remove","reverse","rotate","sort","setdefault"}:
                return EffectFact(term.site,"mutation",names,True,"mutable method")
            return EffectFact(term.site,"unknown",names,reason="unsummarized method")
        if getattr(identity,"name",None)=="reader" and hasattr(identity,"binary"):
            return EffectFact(term.site,"io",may_raise=True)
        return EffectFact(term.site,"unknown",reason="unsummarized module or stream callable")

    def expression_info(self,term,reads,effects,*,nested=False):
        if term.operation=="comprehension":
            clauses,items=term.operands
            for _,source,filters in clauses:
                self.expression_info(source,[],effects,nested=True)
                for condition in filters:self.expression_info(condition,[],effects,nested=True)
            for item in items:self.expression_info(item,[],effects,nested=True)
            return
        for child in self.children(term):self.expression_info(child,reads,effects,nested=nested)
        if term.operation=="index":
            if not nested:reads.append(term)
            effects.append(EffectFact(term.site,"index",may_raise=True))
        elif term.operation=="call":effects.append(self.call_effect(term))
        elif term.operation=="attribute":
            receiver=term.operands[0]
            item=self.facts.values.get(term.site)
            trusted=(item is not None and not item.unbound and not item.unknown and bool(item.alternatives)
                     and all(getattr(value,"_native_reference",False) for value in item.alternatives))
            if self.facts.expressions.get(receiver.site) in {"str","bytes"}:
                effects.append(EffectFact(term.site,"pure",may_raise=True,reason="primitive attribute lookup"))
            elif not trusted:
                effects.append(EffectFact(term.site,"unknown",reason="unproved attribute/descriptor effect"))
        elif term.operation=="unknown":effects.append(EffectFact(term.site,"unknown",reason="unsupported semantic expression"))
        elif term.operation in {"list","set","dict","slice"} or term.operation=="binary" and self.facts.expressions.get(term.site)=="str":
            effects.append(EffectFact(term.site,"pure",may_raise=True,reason="allocating value operation"))
        elif term.operation=="binary" and term.data not in {"Add","Sub","Mult","BitAnd","BitOr","BitXor"}:
            effects.append(EffectFact(term.site,"pure",may_raise=True,reason="potentially raising arithmetic"))

    def block_info(self,operations,reads,effects,written,*,nested=False):
        for operation in operations:
            op=operation.operation
            for term in operation.operands:self.expression_info(term,reads,effects,nested=nested)
            if op in {"assign","augment"}:
                targets=operation.data if op=="assign" else (operation.data[0],)
                for target in targets:
                    written|=target_names(target)
                    if target[0] in {"index","attribute"}:
                        owner=target[1]
                        names=frozenset({owner.data}) if owner.operation=="name" else frozenset()
                        effects.append(EffectFact(operation.site,"mutation",names,True,"container or namespace assignment"))
            elif op=="for":written|=target_names(operation.data)
            elif op in {"break","continue","return"}:
                effects.append(EffectFact(operation.site,"control",reason="ordered control transfer"))
            elif op in {"definition","import","unknown"}:
                effects.append(EffectFact(operation.site,"unknown",reason="namespace or unsupported operation"))
            for body in operation.blocks:self.block_info(body,reads,effects,written,nested=nested or op in {"for","while"})

    def region(self,key,domain,reads,effects,written):
        if any(effect.kind in {"unknown","mutation"} for effect in effects):return
        candidates={}
        for read in reads:
            owner,_=read.operands
            if owner.operation=="name" and owner.data not in written and self.bound(owner,"str"):
                candidates.setdefault(owner.data,[]).append(read)
        owners={name:OwnerRef(name,items[0].operands[0].site,"str",tuple(item.site for item in items)) for name,items in candidates.items()}
        accesses=[];invariants=set()
        if domain is not None and domain.target not in written and self.bits in {64,128}:
            for read in reads:
                owner,index=read.operands
                if owner.operation!="name" or owner.data not in owners:continue
                fact=self.affine(index,domain.target,written)
                if fact is None:continue
                term,coefficient,names=fact
                if coefficient!=1:continue
                def length_owners(value):
                    if value.operation=="owner_length":yield value
                    for child in value.operands:yield from length_owners(child)
                for dependency in length_owners(term):
                    owners.setdefault(dependency.value,OwnerRef(dependency.value,dependency.site))
                accesses.append(AccessFact(read.site,owners[owner.data],term,coefficient,names));invariants|=names
        if not owners:return
        bound=set(owners)|invariants
        self.result[key]=RegionFact(key,domain,tuple(owners.values()),tuple(accesses),frozenset(invariants),frozenset(written),frozenset(bound),tuple(effects),self.bits)

    def stable_construction(self,term):
        effects=[]
        self.expression_info(term,[],effects,nested=True)
        return not any(effect.kind in {"unknown","mutation"} for effect in effects)

    def visit_expression(self,term):
        if term.operation=="comprehension":
            clauses,items=term.operands
            if len(clauses)==1:
                target,source,filters=clauses[0];reads=[];effects=[];written=set()
                for item in (*filters,*items):self.expression_info(item,reads,effects)
                if self.stable_construction(source):
                    self.region((term.site,0),self.domain(source,target),reads,effects,written)
        for child in self.children(term):self.visit_expression(child)

    def visit_block(self,operations):
        for operation in operations:
            if operation.operation=="for":
                reads=[];effects=[];written=set()
                self.block_info(operation.blocks[0],reads,effects,written)
                if self.stable_construction(operation.operands[0]):
                    self.region(operation.site,self.domain(operation.operands[0],operation.data),reads,effects,written)
            for term in operation.operands:self.visit_expression(term)
            for body in operation.blocks:self.visit_block(body)


def derive_regions(analysis,facts,bits,*,body=None):
    visitor=RegionAnalysis(analysis,facts,bits)
    visitor.visit_block(analysis.graph.body if body is None else body)
    return MappingProxyType(visitor.result)
