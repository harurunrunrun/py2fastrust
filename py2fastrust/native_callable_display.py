"""Stable canonical builtin/member representations without address invention."""
from .native_aot_callables import variant


def emit(emitter,value,node):
    from .native import _string
    from .native_classes import ClassUnsupported
    from .native_class_builtins import SUPPORTED
    from .native_type_checks import TYPE_NAMES
    if value.kind.definitions or value.kind.methods:
        raise ClassUnsupported(node,"this stored source function needs Python's function-object repr/name/address protocol; typed callable capture and direct dispatch are supported, but function-object display metadata is not implemented",types=(("value",value.kind),),proof="function-object display protocol")
    arms=[]
    for identity in value.kind.builtins:
        if identity.name not in SUPPORTED:
            raise ClassUnsupported(node,'this captured builtin needs its canonical object representation metadata',types=(('value',value.kind),),proof='builtin object display metadata')
        text=("<class '"+identity.name+"'>"if identity.name in TYPE_NAMES else'<built-in function '+identity.name+'>')
        arms.append(variant(identity)+'=>'+_string(text)+'.to_owned()')
    for identity in value.kind.members:
        adapter=emitter.model.callable_cells.member_adapters.get(identity.module)
        if adapter is None or identity.name not in adapter.NAMES:
            raise ClassUnsupported(node,'this native member needs its canonical object representation metadata',types=(('value',value.kind),),proof='native member object display metadata')
        text=("<class '"+identity.module+'.'+identity.name+"'>"if identity.name in getattr(adapter,'TYPES',())else'<built-in function '+identity.name+'>')
        arms.append(variant(identity)+'=>'+_string(text)+'.to_owned()')
    arms.append('_=>unreachable!("callable display contradicts finite target proof")')
    return 'match &('+value.code+'){' + ','.join(arms)+'}'
