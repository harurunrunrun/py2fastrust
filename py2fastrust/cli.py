"""Compile source; never execute input Python during transpilation."""

import argparse
import sys
import tokenize
from pathlib import Path

from . import __version__
from .api import TranspileOptions, transpile
from .diagnostics import CompilationError
from .settings import LICENSES, add_conversion_arguments, source_directives


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pytors", description="Compile Python 3.14 to a standalone Rust source file")
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("-o", "--output", type=Path)
    add_conversion_arguments(parser)
    parser.add_argument("--check", action="store_true", help="validate without writing Rust")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--list-licenses", action="store_true", help="list available output licenses")
    args = parser.parse_args(argv)
    if args.list_licenses:
        print("\n".join(LICENSES))
        return 0
    if args.source is None:
        parser.error("the following arguments are required: source")
    try:
        with tokenize.open(args.source) as stream:
            source = stream.read()
        directives = source_directives(source, str(args.source))
        options = TranspileOptions(args.integer, str(args.source), tuple(args.module_path or ()) or (args.source.resolve().parent,),
                                   tuple(args.include_module or ()), args.optimize, args.license,
                                   string_mode=args.string_mode)
        result = transpile(source, options)
        if not result.success:
            for diagnostic in result.diagnostics:
                print(diagnostic, file=sys.stderr)
            return 2
        if not directives.get("check", args.check):
            output = directives.get("output", args.output) or args.source.with_suffix(".rs")
            if "output" in directives and not output.is_absolute():
                output = args.source.resolve().parent / output
            output.write_text(result.rust_source, encoding="utf-8")
        return 0
    except CompilationError as exc:
        print(exc.diagnostic, file=sys.stderr)
        return 2
    except (OSError, UnicodeError, SyntaxError) as exc:
        print(f"{args.source}: {exc}", file=sys.stderr)
        return 2
