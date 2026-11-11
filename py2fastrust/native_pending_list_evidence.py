"""Transport a pending shared-list element cell without inventing evidence.

This is a directional type view, not a new allocation or an identity proof.
All contributing lists must already share their mutable element summary.
Other cases retain the existing caller's contribution/decline behavior.
"""


def contribute(namespace, destination, source, node):
    from .native_classes import Cell
    from .native_class_storage import check_merge, contains_cell

    left, right = destination.root(), source.root()
    if left is right:
        return right.tag == 'list'
    previous = namespace.flow_inputs.get(left)
    if previous is None:
        previous = set() if left.tag is None else {
            Cell(left.tag, left.args, list_origins=left.list_origins)}
    inputs = set(previous)
    inputs.add(source)
    roots = [value.root() for value in inputs]
    # Do not silently drop an unresolved/non-list alternative. Different
    # element summaries need the established ordinary contribution path;
    # choosing the first list would lose writes through another MAY source.
    if (not roots or any(value.tag != 'list' or len(value.args) != 1 for value in roots)
            or len({value.args[0].root() for value in roots}) != 1):
        return False
    if contains_cell(right, left):
        check_merge(left, right, node)
    origins = (None if any(value.list_origins is None for value in roots)
               else frozenset().union(*(value.list_origins for value in roots)))
    element = roots[0].args[0]
    if destination.parent is not None:
        # The outer binding remains directional. Only the already-shared
        # mutable element cell is retained; source roots are never unioned.
        destination.parent = None
        left = destination
    # Keep the original inputs, including their pending element cells, so a
    # later complete contribution re-evaluates the real producer evidence.
    namespace.flow_inputs[left] = inputs
    left.tag, left.args, left.list_origins = 'list', (element,), origins
    namespace.flow_cells.add(left)
    return True
