"""Pure direct-range capabilities shared by selection and stream lowering."""
from dataclasses import dataclass
from .references import BuiltinIdentity


def ordinary_reverse_range_step(bits,step):
    return bool(bits)and step in {1,-1}


@dataclass(frozen=True)
class ReverseRangeCapability:
    canonical_range:bool
    ordinary:bool
    step:int|None=None


def reverse_range_capability(analysis,facts,site,integer):
    term=analysis.graph.expressions.get(site)
    call=facts.calls.get(site)
    if(term is None or term.operation!='call'or call is None
       or call.identity.unknown or call.identity.unbound
       or call.identity.alternatives!=frozenset({BuiltinIdentity('range')})):
        return ReverseRangeCapability(False,False)
    _,arguments,keywords=term.operands
    if keywords or not 1<=len(arguments)<=3:
        return ReverseRangeCapability(True,False)
    if not all(facts.expressions.get(argument.site)in {'int','bool','int_bool'}for argument in arguments):
        return ReverseRangeCapability(True,False)
    bits={'i64':64,'i128':128,'bigint':0}[integer]
    from .native_range_facts import RegionAnalysis
    step=1 if len(arguments)<3 else RegionAnalysis(analysis,facts,bits).constant(arguments[2])
    return ReverseRangeCapability(True,ordinary_reverse_range_step(bits,step),step)
