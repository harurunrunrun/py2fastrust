"""Keep the zero-iteration entry bindings separate from loop targets."""


def header(model, entry, feedback, node):
    from .native_classes import Environment
    # Joining an absent feedback edge may return entry itself. Binding a loop
    # target must change only the header map; shared payload cells stay shared.
    return Environment(model.join(entry, feedback, node, "loop_header"))
