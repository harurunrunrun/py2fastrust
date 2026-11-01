"""Frame admission for reached borrowed-container formal binding changes."""
from .native_types import ListType,TupleType,TupleSequenceType,DequeType,alternatives


def requires_frames(unit,analysis):
    from .native_constraints import target_names
    from .native_key_types import DictType,SetType
    def container(kind):
        return any(isinstance(value,(ListType,TupleType,TupleSequenceType,DequeType,DictType,SetType))or
                   value in {'str','bytes','list_int','matrix_int','dict_int','set_int','deque_int'}
                   for value in alternatives(kind))
    def writes(operations):
        names=set()
        for operation in operations:
            if operation.operation in {'assign','delete'}:
                for target in operation.data:names.update(target_names(target))
            elif operation.operation=='augment':names.update(target_names(operation.data[0]))
            elif operation.operation=='for':names.update(target_names(operation.data))
            for child in operation.blocks:names.update(writes(child))
        return names
    for (definition,kinds)in analysis.scopes:
        if definition is None:continue
        function=analysis.graph.functions.get(definition)
        if function is None:continue
        scope=unit.scope_for(analysis.graph.nodes[definition]).ordinal
        lexical={binding.name for binding in unit.bindings if binding.owner==scope and binding.scope==scope and
                 binding.role in {'store','delete','definition','import'}}
        changed=lexical|writes(function.body)
        if any(name in changed and container(kind)for name,kind in zip(function.signature.parameters,kinds)):
            return True
    return False
