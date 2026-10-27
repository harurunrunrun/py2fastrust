"""Stable public source coordinates, independent of any executable IR."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLocation:
    code: int
    instruction: int
    filename: str
    line: int
    column: int
