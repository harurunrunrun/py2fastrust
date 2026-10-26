"""Stable, source-positioned compiler diagnostics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    message: str
    filename: str = "<input>"
    line: int = 1
    column: int = 1
    code: str = "E001"

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.column}: {self.code}: {self.message}"


class CompilationError(Exception):
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic
        super().__init__(str(diagnostic))
