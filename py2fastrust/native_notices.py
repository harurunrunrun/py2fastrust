"""Keep notices for third-party code and data retained in native Rust output.

This applies only to the three native emitters. The retained internal runtime
has additional upstream sources and must keep its own complete notice policy.
"""
from importlib.resources import files

from .rust_pruning import _lex
from .rust_layout import compact_blank_lines, strip_comments
from .rust_cleanup import cleanup_rust_source


def retain_native_notices(source: str) -> str:
    """Replace assembly-time notice bundles after helper reachability pruning."""
    resources = files("py2fastrust")
    runtime_notice = resources.joinpath("runtime", "NOTICE.txt").read_text(encoding="utf-8")
    # The repository LICENSE grants an output exception for original helpers.
    # Upstream code and data retain their notices when actually emitted below.
    source = source.replace("/*\n" + runtime_notice + "\n*/\n", "")
    licenses = {}
    for name in ("PYTHON_LICENSE.txt", "UNICODE_LICENSE.txt"):
        text = resources.joinpath("stdlib", name).read_text(encoding="utf-8")
        block = "\n".join("// " + line for line in text.splitlines())
        source = source.replace(block, "")
        licenses[name] = block

    tokens, _comments, _pairs = _lex(source)
    functions = {tokens[index + 1].text for index, token in enumerate(tokens[:-1])
                 if token.text == "fn"}
    constants = {tokens[index + 1].text for index, token in enumerate(tokens[:-1])
                 if token.text == "const"}
    notices = []
    if "native_float_divmod" in functions:
        attribution = (
            "// CPython-derived native_float_divmod: Objects/floatobject.c, Python 3.14.\n"
            "// Copyright Python Software Foundation; PSF License Version 2.\n"
            "// Modifications: Rust f64 arithmetic and Result-based error reporting.\n"
        )
        notices.append(attribution + licenses["PYTHON_LICENSE.txt"])
    # ZEROES and RANGES are function-local tables in the Unicode number parsers;
    # NATIVE_TUPLE_PRINTABLE is the renamed string-repr table. Token definitions, rather
    # than names mentioned in comments/strings, establish whether data remains.
    if (constants & {"ZEROES", "RANGES", "TEXT_PRINTABLE", "NATIVE_TUPLE_PRINTABLE",
                    "NATIVE_FIXED_INT_ZEROES", "NATIVE_FIXED_INT_SPACE"}
            or any(name.startswith("NATIVE_PRED_TABLE_") for name in constants)):
        notices.append(licenses["UNICODE_LICENSE.txt"])
    suffix = "\n\n" + "\n\n".join(notices) if notices else ""
    code = strip_comments(source).strip()
    code = cleanup_rust_source(code)
    return compact_blank_lines(code + suffix + "\n")
