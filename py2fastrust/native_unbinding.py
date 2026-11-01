"""Delete lexical value bindings while retaining live iterator-owned objects."""
import ast

from .native import _Binding,_MaybeInfo,_Unsupported
from .native_types import is_maybe,maybe_type


def try_statement(generator,node,environment):
    if not isinstance(node,ast.Delete):return None
    targets=[]
    def collect(target):
        if isinstance(target,ast.Name):targets.append(target);return True
        if isinstance(target,(ast.Tuple,ast.List)):
            return all(collect(child)for child in target.elts)
        return False
    if not all(collect(target)for target in node.targets):return None
    lines=[]
    for target in targets:
        binding=environment.get(target.id)
        if not isinstance(binding,_Binding):
            raise _Unsupported('deleting this name needs a stored lexical value binding; imported and callable-reference identities have no ordinary unbinding cell',node=target,proof='lexical binding presence and owned value lifetime')
        if is_maybe(binding.kind):
            value=generator.expression(target,environment)
            lines.append('let _=&('+value.code+');')
            lines.append(binding.slot+'=None;')
        else:
            slot=generator.slot(maybe_type(binding.kind))
            owner=generator.function.node.name if generator.function else generator.entry_scope
            environment[target.id]=_Binding(slot,_MaybeInfo(binding.kind,owner))
            scalar_copy=binding.kind in {'bool','float','none'}or generator.bits and binding.kind in {'int','int_bool'}
            if not scalar_copy:lines.append('drop('+binding.slot+');')
            lines.append(slot+'=None;')
    return '\n'.join(lines),environment
