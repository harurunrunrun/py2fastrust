"""Fixed browser adapter for the public API; submitted source stays data."""

import ast
import hashlib
import json
import os
from pathlib import Path
import symtable
import sys
from importlib.resources import files

from py2fastrust import TranspileOptions, __version__, transpile
from py2fastrust.settings import LICENSES
from py2fastrust.python_profile import profile


WORK_DIRECTORY = Path("/work")
_initialized = False


def initialize(manifest_json):
    """Check the actual installed wheel and compiler before accepting work."""
    global _initialized
    _initialized = False
    manifest = json.loads(manifest_json)
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError("The converter requires Python 3.14.")
    sample = "answer = 1 + 2\n"
    smoke_checks = {
        "ast": isinstance(ast.parse(sample), ast.Module),
        "symtable": symtable.symtable(sample, "smoke.py", "exec").get_type() == "module",
        "compile": compile(sample, "smoke.py", "exec").co_filename == "smoke.py",
        "sha256": hashlib.sha256(b"abc").hexdigest() == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        ),
    }
    if not all(smoke_checks.values()):
        raise RuntimeError("The Python compiler/runtime smoke check failed.")
    resources = manifest["resources"]
    if not resources:
        raise RuntimeError("The wheel resource inventory is empty.")
    package = files("py2fastrust")
    for resource in resources:
        relative = Path(resource["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("Invalid package resource path.")
        data = package.joinpath(*relative.parts).read_bytes()
        if len(data) != resource["size"] or hashlib.sha256(data).hexdigest() != resource["sha256"]:
            raise RuntimeError("Wheel resource integrity check failed: " + resource["path"])
    if __version__ != manifest["package"]["version"]:
        raise RuntimeError("Installed package version does not match the site manifest.")
    WORK_DIRECTORY.mkdir(exist_ok=True)
    os.chdir(WORK_DIRECTORY)
    _initialized = True
    smoke_checks["resources"] = True
    return json.dumps({
        "integer_modes": ["i64", "i128", "bigint"],
        "licenses": list(LICENSES),
        "defaults": {"integer": "i64", "license": "CC0-1.0", "optimize": True},
        "python_version": sys.version.split()[0],
        "python_profile": profile(),
        "package_version": __version__,
        "resource_count": len(resources),
        "smoke_checks": smoke_checks,
    })


def convert(request_json):
    """Translate one source string without executing it or writing it to disk."""
    if not _initialized:
        raise RuntimeError("The converter is not initialized.")
    request = json.loads(request_json)
    source = request.get("source")
    if not isinstance(source, str):
        raise ValueError("Source must be a string.")
    options = request.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("Options must be an object.")
    integer = options.get("integer", "i64")
    license = options.get("license", "CC0-1.0")
    optimize = options.get("optimize", True)
    if not isinstance(integer, str) or not isinstance(license, str) or not isinstance(optimize, bool):
        raise ValueError("Invalid conversion option types.")
    # The core applies source-leading directives after these defaults. Keep
    # main.py relative, so its diagnostics and provenance match the CLI/API.
    os.chdir(WORK_DIRECTORY)
    result = transpile(source, TranspileOptions(
        filename="main.py", integer=integer, license=license, optimize=optimize,
        module_paths=(WORK_DIRECTORY,),
    ))
    return json.dumps({
        "rust_source": result.rust_source,
        "diagnostics": [
            {"filename": item.filename, "line": item.line, "column": item.column,
             "message": item.message, "code": item.code}
            for item in result.diagnostics
        ],
    })
