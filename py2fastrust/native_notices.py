"""Keep notices for third-party code and data retained in native Rust output.

This applies only to the three native emitters. The retained internal runtime
has additional upstream sources and must keep its own complete notice policy.
"""
from importlib.resources import files

from .rust_pruning import _lex
from .rust_layout import compact_blank_lines, strip_comments
from .rust_cleanup import cleanup_rust_source
from .native_unicode_tables import compact_unicode_tables, attach_unicode_notice
from .native_unicode_dependencies import select_unicode_dependencies


def retain_native_notices(source: str) -> str:
    """Replace assembly-time notice bundles after helper reachability pruning."""
    source = select_unicode_dependencies(source)
    resources = files("py2fastrust")
    # Actual assembly comments are removed after token-based reachability
    # checks. Never replace license-shaped text inside a Rust string literal.
    # Upstream code and data retain their notices when actually emitted below.
    licenses = {}
    for name in ("PYTHON_LICENSE.txt", "UNICODE_LICENSE.txt"):
        text = resources.joinpath("stdlib", name).read_text(encoding="utf-8")
        block = "\n".join("// " + line for line in text.splitlines())
        licenses[name] = block

    tokens, _comments, _pairs = _lex(source)
    functions = {tokens[index + 1].text for index, token in enumerate(tokens[:-1])
                 if token.text == "fn"}
    types = {tokens[index + 1].text for index, token in enumerate(tokens[:-1])
             if token.text in {'struct','enum'}}
    notices = []
    if "native_float_divmod" in functions:
        attribution = (
            "// CPython-derived native_float_divmod: Objects/floatobject.c, Python 3.14.\n"
            "// Copyright Python Software Foundation; PSF License Version 2.\n"
            "// Modifications: Rust f64 arithmetic and Result-based error reporting.\n"
        )
        notices.append(attribution + licenses["PYTHON_LICENSE.txt"])
    if functions.intersection({'native_cmp_sort_indices','native_cmp_sort_indices_async'}):
        notices.append(
            '// CPython-derived stable sorting: Objects/listobject.c, Python 3.14.4.\n'
            '// Copyright Python Software Foundation; PSF License Version 2.\n'
            '// Modifications: typed Rust index permutations and fallible synchronous/asynchronous callbacks.\n'+
            (''if notices else licenses['PYTHON_LICENSE.txt']))
    if any(name.startswith('native_fallible_heap')for name in functions):
        notices.append(
            '// CPython-derived fallible heaps: Modules/_heapqmodule.c, Python 3.14.4.\n'
            '// Copyright Python Software Foundation; PSF License Version 2.\n'
            '// Modifications: typed Rust buffers, released borrows, positioned errors and synchronous/asynchronous callbacks.\n'+
            (''if notices else licenses['PYTHON_LICENSE.txt']))
    if 'NativeCPSet'in types or 'NativeCPHashSecret'in types or any(name.startswith('native_cp_hash_')for name in functions):
        notices.append(
            '// CPython-derived set tables and hashes: Objects/setobject.c, Objects/longobject.c, Objects/tupleobject.c, Python/pyhash.c and Python/bootstrap_hash.c, Python 3.14.4.\n'
            '// Copyright Python Software Foundation; PSF License Version 2.\n'
            '// Modifications: typed Rust storage, checked sizes, explicit 64-bit hashes and owned cursors.\n'+
            (''if notices else licenses['PYTHON_LICENSE.txt']))
    if 'native_cp_sip_round'in functions:
        from .native_cpython_hash import SIPHASH_NOTICE
        notices.append('// CPython-derived SipHash13; original csiphash implementation.\n'+'\n'.join('// '+line for line in SIPHASH_NOTICE.splitlines()))
    suffix = "\n\n" + "\n\n".join(notices) if notices else ""
    code = strip_comments(source).strip()
    code = cleanup_rust_source(code)
    code = compact_unicode_tables(code)
    code = attach_unicode_notice(code, licenses["UNICODE_LICENSE.txt"])
    return compact_blank_lines(code + suffix + "\n")
