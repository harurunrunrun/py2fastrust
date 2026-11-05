"""Canonical builtin function values, independently of operation adapters.

The host is the frontend's required CPython version.  Inspecting its builtin
objects establishes identity/signature metadata; it never executes source or
calls a builtin on speculative user arguments.
"""
import builtins
import inspect
from functools import lru_cache
from types import BuiltinFunctionType


FUNCTIONS = frozenset(name for name, value in vars(builtins).items()
                      if isinstance(value, BuiltinFunctionType))


def names():
    from .native_class_builtins import SUPPORTED
    return FUNCTIONS | SUPPORTED


@lru_cache(None)
def _single_positional(name):
    if name not in FUNCTIONS:
        return False
    try:
        parameters = tuple(inspect.signature(vars(builtins)[name]).parameters.values())
    except (TypeError, ValueError):
        return False
    return (len(parameters) == 1
            and parameters[0].kind is inspect.Parameter.POSITIONAL_ONLY
            and parameters[0].default is inspect.Parameter.empty)


def binding_error(name, count, keywords):
    """A sealed one-positional-only builtin has a real binding error.

    A valid signature does not imply that its numeric/object operation is
    implemented.  Those calls continue to their explicit capability adapter.
    """
    if not _single_positional(name):
        return None
    if keywords:
        return f'TypeError: {name}() takes no keyword arguments'
    if count != 1:
        return f'TypeError: {name}() takes exactly one argument ({count} given)'
    return None
