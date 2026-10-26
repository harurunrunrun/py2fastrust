"""Public Python API, independent of command-line filesystem writes."""

from dataclasses import dataclass
from pathlib import Path

from .compiler import Compiler
from .codegen import generate
from .diagnostics import CompilationError, Diagnostic
from .ir import SourceLocation


@dataclass(frozen=True)
class TranspileOptions:
    integer: str = "i64"
    filename: str = "<input>"
    module_paths: tuple[Path, ...] = ()
    include_modules: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranspileResult:
    rust_source: str | None
    diagnostics: tuple[Diagnostic, ...] = ()
    source_map: tuple[SourceLocation, ...] = ()

    @property
    def success(self):
        return self.rust_source is not None and not self.diagnostics


def transpile(source: str, options: TranspileOptions | None = None) -> TranspileResult:
    options = options or TranspileOptions()
    if options.integer not in {"i64", "i128", "bigint"}:
        return TranspileResult(None, (Diagnostic("integer must be i64, i128, or bigint", options.filename, code="E004"),))
    try:
        program = Compiler(options.filename, options.module_paths, options.include_modules).compile(source)
        rust_source, source_map = generate(program, options.integer)
        return TranspileResult(rust_source, source_map=source_map)
    except CompilationError as exc:
        return TranspileResult(None, (exc.diagnostic,))
    except (OSError, UnicodeError) as exc:
        return TranspileResult(None, (Diagnostic(str(exc), options.filename, code="E005"),))
