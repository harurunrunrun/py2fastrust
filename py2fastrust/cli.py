"""Compile source; never execute input Python during transpilation."""

import argparse
import sys
import tokenize
from pathlib import Path

from . import __version__
from .api import TranspileOptions, transpile


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compile Python 3.14 to a standalone Rust source file")
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--int", dest="integer", choices=("i64", "i128", "bigint"), default="i64")
    parser.add_argument("--module-path", type=Path, action="append", default=[])
    parser.add_argument("--include-module", action="append", default=[])
    parser.add_argument("--check", action="store_true", help="validate without writing Rust")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        with tokenize.open(args.source) as stream:
            source = stream.read()
        options = TranspileOptions(args.integer, str(args.source), tuple(args.module_path) or (args.source.resolve().parent,),
                                   tuple(args.include_module))
        result = transpile(source, options)
        if not result.success:
            for diagnostic in result.diagnostics:
                print(diagnostic, file=sys.stderr)
            return 2
        if not args.check:
            output = args.output or args.source.with_suffix(".rs")
            output.write_text(result.rust_source, encoding="utf-8")
        return 0
    except (OSError, UnicodeError, SyntaxError) as exc:
        print(f"{args.source}: {exc}", file=sys.stderr)
        return 2
