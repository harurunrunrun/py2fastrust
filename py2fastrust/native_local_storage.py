"""The concrete carrier of an official local binding, independent of its value kind."""


def rust_type(emitter,name,kind):
    from .native_scalar_data_locals import local_type as snapshot_type
    snapshot=snapshot_type(emitter,name)
    if snapshot is not None:return snapshot
    from .native_scalar_data_results import local_type
    projected=local_type(emitter,name)
    if projected is not None:return projected
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
