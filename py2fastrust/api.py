"""Public Python API, independent of command-line filesystem writes."""

from dataclasses import dataclass, replace
from pathlib import Path

from .frontend import build_program
from .diagnostics import CompilationError, Diagnostic
from .source_locations import SourceLocation
from .native import try_generate_native
from .provenance import add_header
from .settings import apply_source_options, license_name, source_directives


@dataclass(frozen=True)
class TranspileOptions:
    integer: str = "i64"
    filename: str = "<input>"
    module_paths: tuple[Path, ...] = ()
    include_modules: tuple[str, ...] = ()
    optimize: bool = True
    license: str = "CC0-1.0"
    string_mode: str = "ascii"


@dataclass(frozen=True)
class TranspileResult:
    rust_source: str | None
    diagnostics: tuple[Diagnostic, ...] = ()
    source_map: tuple[SourceLocation, ...] = ()
    backend: str = "native"

    @property
    def success(self):
        return self.rust_source is not None and not self.diagnostics


def transpile(source: str, options: TranspileOptions | None = None) -> TranspileResult:
    options = options or TranspileOptions()
    try:
        options = apply_source_options(options, source_directives(source, options.filename))
        if options.integer not in {"i64", "i128", "bigint"}:
            return TranspileResult(None, (Diagnostic("integer must be i64, i128, or bigint", options.filename, code="E004"),))
        if options.string_mode not in ("ascii", "unicode"):
            return TranspileResult(None, (Diagnostic("string_mode must be ascii or unicode", options.filename, code="E004"),))
        try:
            options = replace(options, license=license_name(options.license))
        except ValueError as exc:
            return TranspileResult(None, (Diagnostic(str(exc), options.filename, code="E004"),))
        program = build_program(source, options.filename, options.module_paths, options.include_modules)
        if options.include_modules:
            return TranspileResult(None, (Diagnostic(
                "Cannot lower --include-module: native module bundling/linking for the requested modules (" + ", ".join(options.include_modules) + ") is not implemented; their Python namespaces and calls need direct Rust module adapters.",
                options.filename, code="E006"),))
        diagnostics = []
        native = try_generate_native(source, options.filename, options.integer,
                                     unit=program.main,
                                     prune_output=options.optimize, diagnostic_out=diagnostics,
                                     string_mode=options.string_mode)
        if native is None:
            return TranspileResult(None, tuple(diagnostics) or (Diagnostic(
                "Cannot lower program analysis: native generation returned without a supported operation/storage path or a specific rejection context.",
                options.filename, code="E006"),))
        source_map = program.source_map
        return TranspileResult(add_header(native, source, options, "native"), source_map=source_map, backend="native")
    except CompilationError as exc:
        return TranspileResult(None, (exc.diagnostic,))
    except (OSError, UnicodeError) as exc:
        return TranspileResult(None, (Diagnostic(str(exc), options.filename, code="E005"),))
