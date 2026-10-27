"""Public Python API, independent of command-line filesystem writes."""

from dataclasses import dataclass, replace
from pathlib import Path

from .compiler import Compiler
from .codegen import generate
from .diagnostics import CompilationError, Diagnostic
from .ir import SourceLocation
from .native import try_generate_native
from .provenance import add_header
from .reachability import dynamic_compilation_unreachable
from .rust_pruning import prune_rust_source
from .settings import apply_source_options, license_name, source_directives


@dataclass(frozen=True)
class TranspileOptions:
    integer: str = "i64"
    filename: str = "<input>"
    module_paths: tuple[Path, ...] = ()
    include_modules: tuple[str, ...] = ()
    optimize: bool = True
    license: str = "CC0-1.0"


@dataclass(frozen=True)
class TranspileResult:
    rust_source: str | None
    diagnostics: tuple[Diagnostic, ...] = ()
    source_map: tuple[SourceLocation, ...] = ()
    backend: str = "aot"

    @property
    def success(self):
        return self.rust_source is not None and not self.diagnostics


def transpile(source: str, options: TranspileOptions | None = None) -> TranspileResult:
    options = options or TranspileOptions()
    try:
        options = apply_source_options(options, source_directives(source, options.filename))
        if options.integer not in {"i64", "i128", "bigint"}:
            return TranspileResult(None, (Diagnostic("integer must be i64, i128, or bigint", options.filename, code="E004"),))
        try:
            options = replace(options, license=license_name(options.license))
        except ValueError as exc:
            return TranspileResult(None, (Diagnostic(str(exc), options.filename, code="E004"),))
        compiler = Compiler(options.filename, options.module_paths, options.include_modules)
        program = compiler.compile(source)
        if options.optimize and not options.include_modules:
            native = try_generate_native(source, options.filename, options.integer, trusted_imports=frozenset(compiler.native_imports))
            if native is not None:
                source_map = tuple(SourceLocation(code_id, index, code.filename, op.line, op.column)
                                   for code_id, code in enumerate(program.codes)
                                   for index, op in enumerate(code.ops))
                return TranspileResult(add_header(native, source, options, "native"), source_map=source_map, backend="native")
        include_dynamic = not dynamic_compilation_unreachable(source, program)
        rust_source, source_map = generate(program, options.integer, include_dynamic=include_dynamic,
                                          native_leaves=options.optimize)
        if options.optimize:
            rust_source = prune_rust_source(rust_source)
        return TranspileResult(add_header(rust_source, source, options, "aot"), source_map=source_map)
    except CompilationError as exc:
        return TranspileResult(None, (exc.diagnostic,))
    except (OSError, UnicodeError) as exc:
        return TranspileResult(None, (Diagnostic(str(exc), options.filename, code="E005"),))
