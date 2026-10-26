"""Source-located, stack-based executable IR shared with the Rust runtime."""

from dataclasses import dataclass, field


@dataclass
class Instruction:
    op: str
    args: tuple = ()
    line: int = 1
    column: int = 1


@dataclass
class Pattern:
    kind: str
    args: tuple = ()


@dataclass
class Parameters:
    posonly: int = 0
    positional: list[str] = field(default_factory=list)
    kwonly: list[str] = field(default_factory=list)
    vararg: str | None = None
    kwarg: str | None = None


@dataclass
class Code:
    name: str
    filename: str
    kind: str
    locals: list[str] = field(default_factory=list)
    globals: list[str] = field(default_factory=list)
    nonlocals: list[str] = field(default_factory=list)
    frees: list[str] = field(default_factory=list)
    params: Parameters = field(default_factory=Parameters)
    ops: list[Instruction] = field(default_factory=list)
    is_generator: bool = False
    future_flags: int = 0
    # Assignment versions are analysis metadata, separate from Python names.
    bindings: dict[str, int] = field(default_factory=dict)


@dataclass
class Program:
    codes: list[Code] = field(default_factory=list)
    modules: list[tuple[str, int]] = field(default_factory=list)


@dataclass(frozen=True)
class SourceLocation:
    code: int
    instruction: int
    filename: str
    line: int
    column: int
