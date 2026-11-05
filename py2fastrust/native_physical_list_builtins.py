"""Static builtin lookup proofs shared by private physical list adapters."""
import ast

from .references import BuiltinIdentity


def static_builtin(model,plan,node,name):
    # Inline-comprehension targets are distinct official bindings even when
    # their spelling is a builtin and the function's declared set omits them.
    # An empty expression environment cannot prove their callable identity.
    unit=model.unit
    if not isinstance(node,ast.Name)or unit is None or id(node)not in unit.node_ordinals:return False
    binding=model.lexical.binding(node)
    return (binding is not None and model.module_owner(binding.owner)
            and model.builtin_identity(plan,node,{})==BuiltinIdentity(name))


def readonly_length(model,plan,node):
    """Effect proof only; it never omits callee lookup or argument capture."""
    if static_builtin(model,plan,node,'len'):return True
    from .native_aot_callables import AotFunctionType
    from .native_classes import shape
    cell=model.records.get((plan.index,id(node)))
    kind=shape(cell)if cell is not None else None
    return isinstance(kind,AotFunctionType)and kind.targets==(BuiltinIdentity('len'),)
