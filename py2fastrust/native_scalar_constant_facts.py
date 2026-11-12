"""Compile-time scalar value constraints, independent of a native backend.

Keys denote original program expressions, bindings, parameters or heap slots.
They are never type-union-find roots. This graph is not emitted or executed by
generated programs, and no source function is evaluated by this analysis.
"""
from dataclasses import dataclass
import operator

from .literal_semantics import integer_policy


class _Unknown:
    pass


UNKNOWN=_Unknown()
BOTTOM=None


@dataclass(frozen=True)
class Scalar:
    kind:str
    low:object
    high:object

    @property
    def singleton(self):return self.low==self.high


def join(left,right):
    if left is BOTTOM:return right
    if right is BOTTOM:return left
    if left is UNKNOWN or right is UNKNOWN:return UNKNOWN
    if left==right:return left
    if left.kind==right.kind=='int':
        return Scalar('int',min(left.low,right.low),max(left.high,right.high))
    return UNKNOWN


@dataclass(frozen=True)
class Rule:
    target:object
    operation:str
    operands:tuple=()
    data:object=None


@dataclass(frozen=True)
class Producer:
    source:object
    scope:object
    site:object
    context:object
    operation:str


class ProducerCoverage:
    """Backend-independent ledger: absent transfers cannot prove constants."""
    def __init__(self):
        self.modeled=set()
        self.unknown=set()

    def record(self,producer):self.modeled.add(producer)

    def missing(self,producer):
        if producer in self.modeled:return False
        self.unknown.add(producer)
        return True


class Graph:
    """Finite monotone constraints with bounded integer-interval widening."""
    def __init__(self,bits):
        self.policy=integer_policy(bits)
        self.values={}
        self.rules=[]
        self.improvements={}
        self.no_successful_values={}
        self.completeness_unknown=set()

    def literal(self,kind,value):
        if kind=='int'and type(value)is int:
            value=self.policy.normalize(value)
            if value.bit_length()>4096:return UNKNOWN
        elif kind=='bool'and type(value)is bool:pass
        else:return UNKNOWN
        return Scalar(kind,value,value)

    def add(self,target,operation,operands=(),data=None):
        self.values.setdefault(target,BOTTOM)
        self.rules.append(Rule(target,operation,tuple(operands),data))
        for key in operands:self.values.setdefault(key,BOTTOM)

    def seed(self,target,kind,value):self.add(target,'seed',data=self.literal(kind,value))
    def unknown(self,target):self.add(target,'seed',data=UNKNOWN)
    def copy(self,target,source):self.add(target,'copy',(source,))

    def certify_empty_allocation(self,target,producer):
        """Only an explicitly empty allocation may initially have no values.

        All later writes still contribute normally. An unmodeled write must
        widen the target before finalize; the certificate is not immutability.
        """
        self.values.setdefault(target,BOTTOM)
        self.no_successful_values[target]=producer

    def finalize(self):
        incoming={rule.target for rule in self.rules}
        for key in tuple(self.values):
            if key not in incoming and key not in self.no_successful_values:
                self.unknown(key);self.completeness_unknown.add(key)
        self.solve()
        # Unsupported inputs and unseeded dependency cycles are Unknown. A
        # missing rule must never disappear when joined with a real constant.
        missing=[key for key,value in self.values.items()
                 if value is BOTTOM and key not in self.no_successful_values]
        for key in missing:
            self.unknown(key);self.completeness_unknown.add(key)
        if missing:self.solve()

    def normalized_range(self,low,high):
        if max(low.bit_length(),high.bit_length())>4096:return UNKNOWN
        bits=self.policy.bits
        if bits and not(-(1<<(bits-1))<=low<=high<(1<<(bits-1))):return UNKNOWN
        return Scalar('int',low,high)

    def evaluate(self,rule):
        if rule.operation=='seed':return rule.data
        values=[self.values[key]for key in rule.operands]
        if rule.operation=='join':
            result=BOTTOM
            for value in values:result=join(result,value)
            return result
        if rule.operation=='restrict_integer':
            if values[0]is BOTTOM:return BOTTOM
            low,high=rule.data
            if isinstance(values[0],Scalar):
                if values[0].kind not in{'int','bool'}:return UNKNOWN
                low,high=max(low,values[0].low),min(high,values[0].high)
            return self.normalized_range(low,high)if low<=high else BOTTOM
        if rule.operation=='Mod'and rule.data=='closed_integer_operands':
            divisor=values[1]
            if isinstance(divisor,Scalar)and divisor.kind in{'int','bool'}and divisor.singleton and divisor.low:
                if values[0]is BOTTOM:return BOTTOM
                if values[0]is UNKNOWN or not values[0].singleton:
                    low,high=(0,int(divisor.low)-1)if divisor.low>0 else(int(divisor.low)+1,0)
                    return self.normalized_range(low,high)
        if any(value is UNKNOWN for value in values):return UNKNOWN
        if any(value is BOTTOM for value in values):return BOTTOM
        if rule.operation=='copy':return values[0]
        if not all(value.kind in{'int','bool'}for value in values):return UNKNOWN
        if rule.operation=='range_items':
            start,stop,step=values
            if step.low>0:
                low,high=start.low,stop.high-1
            elif step.high<0:
                low,high=stop.low+1,start.high
            else:return UNKNOWN
            return self.normalized_range(low,high)if low<=high else BOTTOM
        if all(value.singleton for value in values):
            args=[int(value.low)for value in values]
            try:
                if rule.operation=='UAdd':result=args[0]
                elif rule.operation=='USub':result=-args[0]
                elif rule.operation=='Invert':result=~args[0]
                elif rule.operation=='Not':return self.literal('bool',not args[0])
                elif rule.operation=='Abs':result=abs(args[0])
                elif rule.operation=='Int':result=args[0]
                elif rule.operation=='Bool':return self.literal('bool',bool(args[0]))
                elif rule.operation=='Pow':
                    if not(0<=args[1]<=256 and max(1,args[0].bit_length())*args[1]<=4096):return UNKNOWN
                    result=pow(*args)
                elif rule.operation in{'LShift','RShift'}:
                    if not 0<=args[1]<=4096:return UNKNOWN
                    result=(operator.lshift if rule.operation=='LShift'else operator.rshift)(*args)
                else:
                    operation={'Add':operator.add,'Sub':operator.sub,'Mult':operator.mul,
                               'FloorDiv':operator.floordiv,'Mod':operator.mod,
                               'BitAnd':operator.and_,'BitOr':operator.or_,'BitXor':operator.xor}.get(rule.operation)
                    if operation is None:return UNKNOWN
                    result=operation(*args)
                if(rule.operation in{'BitAnd','BitOr','BitXor'}
                        and all(value.kind=='bool'for value in values)):
                    return self.literal('bool',bool(result))
                return self.literal('int',result)
            except(ArithmeticError,ValueError,OverflowError):return UNKNOWN
        # Interval transfer is deliberately small. A wrapped/discontinuous
        # range is unknown; singleton operations above normalize every result.
        if len(values)==2 and rule.operation in{'Add','Sub','Mult'}:
            a,b=values
            if rule.operation=='Add':low,high=a.low+b.low,a.high+b.high
            elif rule.operation=='Sub':low,high=a.low-b.high,a.high-b.low
            else:
                products=[x*y for x in(a.low,a.high)for y in(b.low,b.high)]
                low,high=min(products),max(products)
            return self.normalized_range(low,high)
        if len(values)==2 and rule.operation in{'LShift','RShift'}:
            value,count=values
            if not count.singleton or not 0<=count.low<=(self.policy.bits or 4096):return UNKNOWN
            shift=int(count.low)
            low,high=((value.low<<shift,value.high<<shift)if rule.operation=='LShift'else
                      (value.low>>shift,value.high>>shift))
            return self.normalized_range(low,high)
        return UNKNOWN

    def solve(self):
        # Four strict increases per node suffice to retain singleton proofs and
        # useful small intervals, while loop recurrences always reach Unknown.
        for _ in range(max(8,5*len(self.values)+1)):
            changed=False
            for rule in self.rules:
                old=self.values[rule.target]
                value=join(old,self.evaluate(rule))
                if value is old or value==old:continue
                count=self.improvements.get(rule.target,0)+1
                self.improvements[rule.target]=count
                if count>4:value=UNKNOWN
                self.values[rule.target]=value
                changed=True
            if not changed:return
        # This is an optimization certificate. Never change accepted source if
        # a newly introduced transfer cannot establish a finite fixed point.
        self.values={key:UNKNOWN for key in self.values}

    def constant(self,key):
        value=self.values.get(key,BOTTOM)
        return value if isinstance(value,Scalar)and value.singleton else None
