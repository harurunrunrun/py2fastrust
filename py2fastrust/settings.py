"""Parse inert conversion directives in the initial Python comment block."""

import argparse
import re
import shlex
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

from .diagnostics import CompilationError, Diagnostic


LICENSES = tuple(sorted(path.name[:-4] for path in files("py2fastrust").joinpath("licenses").iterdir()
                        if path.name.endswith(".txt") and path.name != "NOTICE.txt"))


def license_name(value):
    aliases = {name.casefold(): name for name in LICENSES}
    aliases["cc0"] = "CC0-1.0"
    try:
        return aliases[value.casefold()]
    except (KeyError, AttributeError):
        raise ValueError("unsupported license; use pytors --list-licenses") from None


def add_conversion_arguments(parser, *, defaults=True):
    default = {} if defaults else {"default": argparse.SUPPRESS}
    parser.add_argument("--int", dest="integer", choices=("i64", "i128", "bigint"),
                        **({"default": "i64"} if defaults else default))
    parser.add_argument("--license", type=license_name, metavar="LICENSE",
                        help="generated program license (default: CC0-1.0); see --list-licenses",
                        **({"default": "CC0-1.0"} if defaults else default))
    parser.add_argument("--module-path", type=Path, action="append", **default)
    parser.add_argument("--include-module", action="append", **default)
    optimization = parser.add_mutually_exclusive_group()
    optimization.add_argument("--no-optimize", dest="optimize", action="store_false",
                              help="disable native specialization and source-size optimization; keep direct Rust AOT", **default)
    optimization.add_argument("--optimize", dest="optimize", action="store_true",
                              help="enable proved native optimization", **default)
    if defaults:
        parser.set_defaults(optimize=True)


class _DirectiveParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def source_directives(source, filename):
    """Return explicitly supplied values; never evaluate Python or shell code."""
    parser = _DirectiveParser(add_help=False, allow_abbrev=False)
    add_conversion_arguments(parser, defaults=False)
    parser.add_argument("-o", "--output", type=Path, default=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true", default=argparse.SUPPRESS)
    values = argparse.Namespace()
    # Python physical lines use CR/LF, not the extra separators recognized by
    # str.splitlines() (which may occur inside an ordinary comment).
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line_number, line in enumerate(lines, 1):
        line = line.removeprefix("\ufeff") if line_number == 1 else line
        stripped = line.lstrip(" \t\f")
        if not stripped:
            continue
        if not stripped.startswith("#"):
            break
        match = re.fullmatch(r"#\s*(?:pytors|py2fastrust):\s*(.*)", stripped)
        if match is None:
            continue
        try:
            parser.parse_args(shlex.split(match[1]), namespace=values)
        except (ValueError, argparse.ArgumentError) as error:
            raise CompilationError(Diagnostic(str(error), filename, line_number,
                                              line.index("#") + 1, "E004")) from None
    return vars(values)


def apply_source_options(options, values):
    updates = {key: values[key] for key in ("integer", "license", "optimize") if key in values}
    base = Path(options.filename).resolve().parent
    if "module_path" in values:
        updates["module_paths"] = tuple(path if path.is_absolute() else base / path
                                        for path in values["module_path"])
    if "include_module" in values:
        updates["include_modules"] = tuple(values["include_module"])
    return replace(options, **updates)
