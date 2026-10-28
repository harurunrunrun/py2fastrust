"""Deterministic native backend choice from shared lexical/call identities.

This is a capability selection before either emitter runs. Failed lowering is
never used as evidence to select another backend.
"""
import ast
from dataclasses import dataclass
from types import MappingProxyType

from .native_constraints import FunctionValue,analyze


@dataclass(frozen=True)
class FrameSelection:
    required: bool
    reasons: tuple[str,...]
    analysis: object
    recursive_definitions: frozenset[int]
    call_targets: object
    references: object=None


def _cyclic_nodes(edges):
    """Iterative deterministic SCC walk; compiler depth is not source depth."""
    nodes=sorted(set(edges)|{target for targets in edges.values()for target in targets})
    visited=set();finished=[]
    for root in nodes:
        stack=[(root,False)]
        while stack:
            node,exiting=stack.pop()
            if exiting:finished.append(node);continue
            if node in visited:continue
            visited.add(node);stack.append((node,True))
            stack.extend((child,False)for child in reversed(sorted(edges.get(node,()))))
    reverse={node:set()for node in nodes}
    for source,targets in edges.items():
        for target in targets:reverse[target].add(source)
    assigned=set();recursive=set()
    for root in reversed(finished):
        if root in assigned:continue
        component=set();stack=[root]
        while stack:
            node=stack.pop()
            if node in assigned:continue
            assigned.add(node);component.add(node)
            stack.extend(reversed(sorted(reverse[node])))
        if len(component)>1 or root in edges.get(root,()):recursive.update(component)
    return frozenset(recursive)



def _definition_literal(expression):
    """Total immutable literals need no runtime definition-time capture slot."""
    literal=expression.operand if isinstance(expression,ast.UnaryOp)and isinstance(expression.op,(ast.UAdd,ast.USub))else expression
    return (isinstance(literal,ast.Constant)and type(literal.value)in {int,bool,float,str,type(None)}
            and (not isinstance(expression,ast.UnaryOp)or type(literal.value)in {int,bool,float}))


def _semantic_requirements(unit,analysis,targets):
    # The shared analysis supplies reached callable identities. SourceUnit's
    # official/logical scope owners distinguish real module writes from local
    # shadowing and inlined-comprehension iteration bindings.
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    reached_definitions={definition for definition,kinds in analysis.scopes if definition is not None}
    # An effect-only callee can have no recorded ScopeFacts values. Its
    # canonical CallFact identity still proves that its body is entered.
    reached_definitions.update(definition for definitions in targets.values()for definition in definitions)
    reached={0}|{unit.scope_for(nodes[definition]).ordinal for definition in reached_definitions}
    def execution_scope(scope):
        while scope is not None and unit.scopes[scope].kind=='comprehension':
            scope=unit.scopes[scope].parent
        return scope
    writes=any(binding.owner==0 and binding.role not in {'load','parameter'}
               and execution_scope(binding.scope)not in {0,None}
               and execution_scope(binding.scope)in reached for binding in unit.bindings)
    from .native_lambda_cells import inline_definitions
    inline=inline_definitions(unit,analysis)
    signatures=((unit.ordinal(node),unit.signature_for(node))for node in nodes.values()
                if id(node)in unit.function_signatures)
    defaults=any(slot.expression is not None and not _definition_literal(slot.expression)
                 and execution_scope(slot.definition_scope)in reached
                 for definition,signature in signatures if definition not in inline
                 for slot in signature.defaults)
    return (('module binding writes',)if writes else())+(('definition-time defaults',)if defaults else())


def select_frames(unit):
    if any(isinstance(node,ast.ClassDef)for node in ast.walk(unit.tree)):
        return FrameSelection(True,('class objects',),None,frozenset(),MappingProxyType({}))
    analysis=analyze(unit)
    identities={}
    for (caller,_),facts in analysis.scopes.items():
        for site,fact in facts.calls.items():
            key=(caller,site)
            identities[key]=fact.identity if key not in identities else identities[key].join(fact.identity)
    edges={};targets={}
    for (caller,site),identity in sorted(identities.items(),key=lambda item:(-1 if item[0][0]is None else item[0][0],item[0][1])):
        if identity.unknown or identity.unbound or not identity.alternatives:continue
        if not all(isinstance(value,FunctionValue)for value in identity.alternatives):continue
        definitions=frozenset(value.definition for value in identity.alternatives)
        targets[(caller,site)]=definitions
        if caller is not None:edges.setdefault(caller,set()).update(definitions)
    recursive=_cyclic_nodes(edges)
    from .native_frame_references import prove
    from .native_lexical_cells import requires_environments
    reasons=(('recursive source calls',)if recursive else())+_semantic_requirements(unit,analysis,targets)
    references=prove(unit,analysis,targets)
    if requires_environments(unit,analysis,targets):reasons+=('lexical closure environments',)
    from .native_lambda_cells import requires_instances
    if requires_instances(unit,analysis,targets):reasons+=("escaping lambda instances",)
    from .native_aot_callables import requires_cells
    if requires_cells(unit,analysis,references):reasons+=("first-class AOT function references",)
    if not reasons:references=None
    return FrameSelection(bool(reasons),reasons,analysis,recursive,MappingProxyType(targets),references)
