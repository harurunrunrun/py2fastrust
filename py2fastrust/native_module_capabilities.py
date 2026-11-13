"""Admit canonical standard exports to independently scoped native frames."""
import ast

LINKED_MODULES=frozenset({'itertools','typing','array','random'})
LINKED_EXPORTS={'sys':frozenset({'exit'}),'collections':frozenset({'Counter','defaultdict'}),'functools':frozenset({'reduce','cmp_to_key'}),'operator':frozenset({'add','sub','mul','and_','or_','xor','lshift','rshift','floordiv','mod','truediv'})}
FRAME_MODULES=frozenset({'heapq','bisect','math'})


def needs_linked_members(program,*,integer="i64"):
    for unit in program.units:
        for imported in unit.imports:
            if imported.origin not in {'builtin','vendored'}:continue
            if imported.module in LINKED_MODULES:return True
            if imported.module in FRAME_MODULES or(imported.module=='collections'and('deque'in imported.names or not imported.names)):
                from .native_frame_selection import select_frames
                from .native import _Unsupported,_direct_diagnostic
                from .native_constraints import ConstraintFailure
                from .diagnostics import CompilationError
                try:required=select_frames(unit,integer=integer).required
                except (SyntaxError,_Unsupported,RecursionError,ConstraintFailure)as error:
                    raise CompilationError(_direct_diagnostic(unit.source,unit.filename,error,unit=unit))from None
                if required:return True
            exports=LINKED_EXPORTS.get(imported.module,frozenset())
            if exports.intersection(imported.names):return True
            if exports and not imported.names:
                # Admission may be conservative for module arguments/aliases.
                # The linked binder still proves the actual receiver's canonical
                # module identity before a native member adapter is invoked.
                if any(isinstance(node,ast.Attribute)and node.attr in exports for node in ast.walk(unit.tree)):return True
    return False
