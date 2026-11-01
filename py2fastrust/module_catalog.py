"""Standard module identities shared by source resolution and retained code."""
import sys

BUILTIN_MODULES = frozenset({
    "sys", "math", "heapq", "bisect", "collections", "itertools", "functools",
    "builtins", "operator", "types", "typing", "string", "string.templatelib",
    "gc", "time", "io", "_py2fastrust_functools", "__future__",
})
# This is the target CPython 3.14 build's real BuiltinImporter catalog, also
# when conversion runs inside Pyodide. It does not import any submitted module.
TARGET_BUILTIN_MODULES = frozenset(sys.builtin_module_names) & BUILTIN_MODULES
VENDORED_MODULES = frozenset({"heapq", "bisect", "collections", "functools", "__future__"})

# Sources are data for the official frontend, never imported into the converter.
VENDORED_PACKAGES = {"atcoder": ("vendor", "ac_library_python", "atcoder")}
