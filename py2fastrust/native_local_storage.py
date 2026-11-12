"""The concrete carrier of an official local binding, independent of its value kind."""


def rust_type(emitter,name,kind):
    matrix=emitter.owned_matrices.get(name)
    if matrix is not None:
        from .native_owned_matrix_places import physical_type
        return physical_type(emitter,matrix.tree)
    record=emitter.record_places.get(name)
    if record is not None:
        from .native_record_places import physical_type
        return physical_type(emitter,record)
    if name in emitter.owned_local_lists:return 'Vec<'+emitter.rust_type(kind.element)+'>'
    return emitter.rust_type(kind)
