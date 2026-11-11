"""Preselection proofs for values needing the shared typed-frame storage ABI."""
from .native_types import ListType,TupleType,TupleSequenceType,NullableType,MaybeType,UnionType,EmptyType
from .native_key_types import DictType,SetType


def frame_storable(kind):
    """Storage proof only; each consuming operation still proves its protocol."""
    if isinstance(kind,EmptyType)or kind in {"int","bool","int_bool","float","str","bytes","none","range"}:return True
    if isinstance(kind,(NullableType,MaybeType)):return frame_storable(kind.value)
    if isinstance(kind,ListType):return frame_storable(kind.element)
    if isinstance(kind,TupleSequenceType):return frame_storable(kind.element)
    if isinstance(kind,TupleType):return all(frame_storable(field)for field in kind.fields)
    if isinstance(kind,UnionType):return all(frame_storable(branch)for branch in kind.alternatives)
    if isinstance(kind,(DictType,SetType)):
        from .native_class_mappings import key_supported
        return key_supported(kind.key)and(not isinstance(kind,DictType)or frame_storable(kind.value))
    return getattr(kind,"_native_function_reference",False)or getattr(kind,"_native_class_iterator",False)


def _mutable_list(kind):
    if isinstance(kind,ListType):return True
    if isinstance(kind,TupleSequenceType):return _mutable_list(kind.element)
    if isinstance(kind,(DictType,SetType)):return True
    if isinstance(kind,(NullableType,MaybeType)):return _mutable_list(kind.value)
    if isinstance(kind,TupleType):return any(_mutable_list(field)for field in kind.fields)
    if isinstance(kind,UnionType):return any(_mutable_list(branch)for branch in kind.alternatives)
    return False


def shared_tuple_storage(analysis):
    # The ordinary tuple ABI accepts immutable payloads. A solved mutable list
    # payload needs shared handles, also when no class/function syntax is used.
    return any(isinstance(kind,(TupleType,TupleSequenceType))and _mutable_list(kind)and frame_storable(kind)
               for facts in analysis.scopes.values()for kind in facts.expressions.values())


def mapping_handles(unit,analysis):
    """Prove storage/key requirements before either emitter is selected."""
    import ast
    from .native_types import immutable
    from .native_key_containers import key_kind
    from .native_class_mappings import key_supported
    for (definition,arguments),facts in analysis.scopes.items():
        if definition is not None and any(isinstance(kind,(DictType,SetType))and frame_storable(kind)for kind in arguments):return True
    kinds={}
    for facts in analysis.scopes.values():
        for site,kind in facts.expressions.items():kinds.setdefault(site,[]).append(kind)
    for choices in kinds.values():
        for kind in choices:
            if isinstance(kind,(DictType,SetType))and frame_storable(kind):
                if not key_kind(kind.key)and key_supported(kind.key):return True
                if isinstance(kind,DictType)and not immutable(kind.value):return True
    from .native_mapping_view_consumers import immediate,ordinary_compatible
    parents = {id(child): parent for parent in ast.walk(unit.tree) for child in ast.iter_child_nodes(parent)}
    compatible=None
    for node in ast.walk(unit.tree):
        if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)and node.func.attr in {'keys','items','values'}:
            if any(isinstance(kind,DictType)and frame_storable(kind)for kind in kinds.get(unit.ordinal(node.func.value),())):
                if not immediate(unit,analysis,node,parents):return True
                if compatible is None:compatible=ordinary_compatible(unit,analysis,kinds,parents)
                if not compatible:return True
        if not isinstance(node,ast.Assign):continue
        choices=kinds.get(unit.ordinal(node.value),())
        if not any(isinstance(kind,(DictType,SetType))and frame_storable(kind)for kind in choices):continue
        if len(node.targets)>1:return True
        if isinstance(node.value,ast.Name)and any(isinstance(target,ast.Name)and unit.name_for(target)!=unit.name_for(node.value)for target in node.targets):return True
    return False
