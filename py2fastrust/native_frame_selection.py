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
    # Ordinary specialization retains only static callable/module references.
    # A reached source function reading actual module data needs the already
    # implemented typed namespace frame, including read-only data cells.
    bindings={binding.node:binding for binding in unit.bindings}
    stored={binding.name for binding in unit.bindings if binding.owner==0 and binding.role in {'store','delete'}}
    reads=False
    for (definition,kinds),facts in analysis.scopes.items():
        if definition is None or definition not in reached_definitions:continue
        for site,value in facts.values.items():
            binding=bindings.get(site)
            if binding is None or binding.role!='load'or binding.owner!=0 or binding.name not in stored:continue
            if value.unknown or value.unbound or not value.alternatives or any(
                    not isinstance(part,FunctionValue)and not getattr(part,'_native_reference',False)
                    for part in value.alternatives):
                reads=True;break
        if reads:break
    return (('module binding writes',)if writes else())+(('definition-time defaults',)if defaults else())+(('module data binding reads',)if reads else())


def select_frames(unit,*,integer="i64"):
    if any(isinstance(node,ast.ClassDef)for node in ast.walk(unit.tree)):
        return FrameSelection(True,('class objects',),None,frozenset(),MappingProxyType({}))
    analysis=analyze(unit)
    from .native_callback_analysis import supplement
    analysis=supplement(unit,analysis,integer)
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
    from .native_exit import requires_frames as exit_requires_frames
    if exit_requires_frames(analysis):reasons+=('native process termination unwinding',)
    from .native_sum_binding import requires_frames as sum_requires_frames
    if sum_requires_frames(analysis):reasons+=('canonical sum binding errors',)
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    reached={definition for definitions in targets.values()for definition in definitions}
    if any(unit.signature_for(nodes[definition]).variadic_positional for definition in reached):reasons+=("positional variadic argument packs",)
    references=prove(unit,analysis,targets)
    if requires_environments(unit,analysis,targets):reasons+=('lexical closure environments',)
    from .native_class_unpacking import requires_frames as unpack_requires_frames
    if unpack_requires_frames(unit,analysis):reasons+=('extended assignment unpacking',)
    from .native_lambda_cells import requires_instances
    if requires_instances(unit,analysis,targets):reasons+=("escaping lambda instances",)
    from .native_aot_callables import requires_cells
    if requires_cells(unit,analysis,references):reasons+=("first-class AOT function references",)
    from .native_class_capabilities import shared_tuple_storage,mapping_handles
    if shared_tuple_storage(analysis):reasons+=("shared mutable tuple storage",)
    if mapping_handles(unit,analysis):reasons+=("native mapping identity/key storage",)
    from .native_class_deques import requires_frames as deque_requires_frames
    if deque_requires_frames(unit,analysis):reasons+=("shared deque identity and element storage",)
    from .native_frame_bisect import requires_keys as bisect_requires_keys
    if bisect_requires_keys(unit,analysis):reasons+=("captured bisection key callbacks",)
    from .native_class_iterators import requires_state
    if requires_state(unit,analysis,integer=integer):reasons+=("stored lazy builtin iterators",)
    from .native_starred_calls import requires_expansion
    recorded={site for facts in analysis.scopes.values()for site in facts.expressions}
    if any(site in recorded and isinstance(node,ast.Call)and any(isinstance(value,ast.Starred)for value in node.args)
           and requires_expansion(unit,analysis,node)
           for site,node in nodes.items()):reasons+=("expanded positional call arguments",)
    from .native_builtin_singletons import requires_frames as singleton_requires_frames
    if singleton_requires_frames(unit,analysis):reasons+=("canonical builtin singleton values",)
    from .native_exception_values import requires_frames as exception_requires_frames
    if exception_requires_frames(unit,analysis):reasons+=('typed builtin exception values and raise',)
    from .native_type_checks import requires_frames
    if requires_frames(analysis):reasons+=("captured builtin type predicates",)
    from .native_heap_selection import requires_frames as heap_selection_requires_frames
    if heap_selection_requires_frames(analysis):reasons+=("bounded native heap selections",)
    from .native_float_constructor import requires_frames as float_requires_frames
    if float_requires_frames(analysis):reasons+=("captured float argument and signature protocols",)
    from .native_frame_slices import requires_frames as slice_requires_frames
    if slice_requires_frames(unit,analysis):reasons+=("finite sequence slice alternatives and bounds",)
    from .native_loop_else import requires_frames as loop_else_requires_frames
    if loop_else_requires_frames(unit,analysis):reasons+=("loop exhaustion and else control flow",)
    from .native_class_extrema import requires_frames as extrema_requires_frames
    if extrema_requires_frames(unit,analysis):reasons+=('captured extrema keys and defaults',)
    from .native_class_sorting import requires_frames as sorting_requires_frames
    if sorting_requires_frames(unit,analysis):reasons+=('direct sorted generator collection',)
    from .native_class_divmod import requires_frames as divmod_requires_frames
    if divmod_requires_frames(analysis):reasons+=('captured quotient/remainder builtin',)
    from .native_class_splits import requires_frames as split_requires_frames
    if split_requires_frames(unit,analysis):reasons+=('bound text/bytes split protocols',)
    from .native_class_text_ops import requires_frames as text_requires_frames
    if text_requires_frames(unit,analysis):reasons+=('bound text/bytes strip protocols',)
    from .native_text_join import requires_frames as join_requires_frames
    if join_requires_frames(unit,analysis):reasons+=('typed text/bytes join cursor and validation protocols',)
    from .native_generator_effects import requires_frames as generator_error_requires_frames
    if generator_error_requires_frames(unit,analysis):reasons+=('generator body StopIteration error boundary',)
    from .native_formatting import requires_frames as formatting_requires_frames
    if formatting_requires_frames(unit,analysis):reasons+=("typed format fields and canonical formatting calls",)
    from .native_character_builtins import requires_frames as character_requires_frames
    if character_requires_frames(analysis):reasons+=('character codes and integer radix output',)
    from .native_math_calls import requires_frames as math_requires_frames
    if math_requires_frames(analysis,integer):reasons+=('BigInt real-valued math representation',)
    from .native_integer_base import requires_frames as integer_base_requires_frames
    if integer_base_requires_frames(analysis):reasons+=('explicit-base captured integer conversion',)
    from .native_formal_bindings import requires_frames as formal_bindings_require_frames
    if formal_bindings_require_frames(unit,analysis):reasons+=("container formal binding changes",)
    from .native_positional_selection import requires_frames as positional_requires_frames
    if positional_requires_frames(unit,analysis):reasons+=("fixed list record positional constraints",)
    if not reasons:references=None
    return FrameSelection(bool(reasons),reasons,analysis,recursive,MappingProxyType(targets),references)
