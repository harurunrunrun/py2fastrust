"""Loop exhaustion edges and cleanup-aware native break transfers."""
import ast


def requires_frames(unit,analysis):
    reached={site for facts in analysis.scopes.values()for site in facts.expressions}
    return any(isinstance(node,(ast.For,ast.While))and node.orelse
               and unit.ordinal(node.iter if isinstance(node,ast.For)else node.test)in reached
               for node in ast.walk(unit.tree))


def condition(model,node):
    if not isinstance(node,ast.While)or not node.orelse:return None
    from .native_assertions import literal_truth
    bits=0 if model.integer=='bigint'else 128 if model.integer=='i128'else 64
    return literal_truth(node.test,bits)


def _own_break(nodes):
    for node in nodes:
        if isinstance(node,ast.Break):return True
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):continue
        if isinstance(node,(ast.For,ast.AsyncFor,ast.While)):
            if _own_break(node.orelse):return True
        elif _own_break(ast.iter_child_nodes(node)):return True
    return False


def enter(emitter,node,label):
    if not hasattr(emitter,'loop_else_flags'):emitter.loop_else_flags={}
    needed=bool(node.orelse)and condition(emitter.model,node)is not True and _own_break(node.body)
    flag=emitter.fresh()if needed else None
    emitter.loop_else_flags[label]=flag
    return f'let mut {flag}=true;'if flag is not None else''


def leave(emitter,node,label):
    flag=emitter.loop_else_flags.pop(label)
    if not node.orelse or condition(emitter.model,node)is True:return ''
    body=emitter.statements(node.orelse)
    return f'if {flag}{{{body}}}'if flag is not None and body else body


def transfer(emitter,continuing):
    if not emitter.loops:return 'unreachable!("loop transfer contradicts lexical scope")'
    label=emitter.loops[-1]
    control=('continue'if continuing else'break')+" '"+label
    flag=getattr(emitter,'loop_else_flags',{}).get(label)
    if not continuing and flag is not None:return '{'+flag+'=false;'+control+';}'
    return control
