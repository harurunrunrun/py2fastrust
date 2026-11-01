"""Canonical sum argument binding over values captured in source order."""
from .call_semantics import FunctionSignature

SIGNATURE=FunctionSignature.declaration(('iterable','start'),positional_only=('iterable',),default_names=('start',))


def error(count,keywords):
    names=tuple(keywords)
    if not count:return 'TypeError: sum() takes at least 1 positional argument (0 given)'
    total=count+len(names)
    if total>2:return f'TypeError: sum() takes at most 2 arguments ({total} given)'
    unknown=next((name for name in names if name!='start'),None)
    if unknown is not None:return f'TypeError: sum() got an unexpected keyword argument {unknown!r}'
    return None


def bind(positional,keywords,default):
    failure=error(len(positional),(name for name,_ in keywords))
    if failure:return None,failure
    values=SIGNATURE.bind(positional,keywords,{'start':default}).by_name
    return [values['iterable'],values['start']],None


def requires_frames(analysis):
    from .references import BuiltinIdentity
    return any(BuiltinIdentity('sum')in call.identity.alternatives
               and error(len(call.positional),(name for name,_ in call.keywords))is not None
               for facts in analysis.scopes.values()for call in facts.calls.values())
