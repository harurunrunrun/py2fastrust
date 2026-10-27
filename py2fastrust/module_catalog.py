"""Standard module identities shared by source resolution and retained code."""

BUILTIN_MODULES = frozenset({
    "sys", "math", "heapq", "bisect", "collections", "itertools", "functools",
    "builtins", "operator", "types", "typing", "string", "string.templatelib",
    "gc", "time", "io", "_py2fastrust_functools", "__future__",
})
VENDORED_MODULES = frozenset({"heapq", "bisect", "collections", "functools", "__future__"})
