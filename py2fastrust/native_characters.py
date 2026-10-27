"""Logical one-character text whose scalar has already been captured once.

The descriptor belongs to an iterator's local scope. Persistent Python names
still use the ordinary owned-text binding and control-flow machinery.
"""
import ast
from dataclasses import dataclass

from .native import _Expression


@dataclass(frozen=True)
class CharacterBinding:
    codepoint: str
    kind: str = "str"


def local_binding(value):
    """Use only producer outputs, whose projection is a captured scalar local."""
    return CharacterBinding(value.char_code) if value.kind == "str" and value.char_code is not None else None


def read_local(generator, node, environment, *, borrowed=False):
    if not isinstance(node, ast.Name):
        return None
    binding = environment.get(node.id)
    if not isinstance(binding, CharacterBinding):
        return None
    value = generator.text_from_codepoint(binding.codepoint)
    if borrowed:
        return _Expression(f"&({value.code})", "str", owned=False,
                           length=1, nonempty=True, char_code=value.char_code)
    return value


def capture(generator, value):
    """Capture the selected physical value once at the producer yield point."""
    name = generator.temporary()
    if value.kind == "str" and value.char_code is not None:
        return f"let {name}:u32={value.char_code};", generator.text_from_codepoint(name)
    return (f"let {name}={value.code};",
            _Expression(name, value.kind, owned=value.owned,
                        length=value.length, nonempty=value.nonempty))


def truth(value):
    if value.kind == "str" and value.char_code is not None:
        # Even a statically nonempty value may contain an indexed read that
        # raises. Selecting the scalar preserves that evaluation and error.
        return f"{{let _:u32={value.char_code};true}}"
    return None


def length(generator, value):
    if value.kind == "str" and value.char_code is not None:
        return _Expression(f"{{let _:u32={value.char_code};{generator.literal(1)}}}", "int")
    return None
