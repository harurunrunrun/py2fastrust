"""Original-node lambda facts for canonical immediate map/filter callbacks."""
import ast
from .native_constraints import SemanticGraph,Solver,Function,Operation,Expression,FunctionValue,CallFact,value,UNKNOWN
from .references import BuiltinIdentity
from .call_semantics import CallArguments,Argument,CallBindingError
from .native_types import TupleType,TupleSequenceType,UnionType,NullableType,alternatives,EmptyType


def _calls(analysis):
    result={}
    for facts in analysis.scopes.values():
        for site,fact in facts.calls.items():result[site]=fact.identity if site not in result else result[site].join(fact.identity)
    return result


def _closed(kind):
    if isinstance(kind,(TupleType,)):return all(_closed(child)for child in kind.fields)
    if isinstance(kind,TupleSequenceType):return _closed(kind.element)
    if isinstance(kind,(UnionType,NullableType)):return all(_closed(child)for child in alternatives(kind))
    # The ordinary callback ABI has no boxed float identity. Keep those values
    # on the existing typed path, including NaN identity during container equality.
    return kind in {'int','bool','int_bool','str','bytes','none'}


def _eligible(unit,analysis):
    identities=_calls(analysis);result=set()
    for node in ast.walk(unit.tree):
        if not(isinstance(node,ast.Call)and len(node.args)==2 and not node.keywords and isinstance(node.args[0],ast.Lambda)):continue
        fact=identities.get(unit.ordinal(node))
        if fact is None or fact.unknown or fact.unbound or len(fact.alternatives)!=1:continue
        if next(iter(fact.alternatives))not in {BuiltinIdentity('map'),BuiltinIdentity('filter')}:continue
        callback=node.args[0];signature=unit.signature_for(callback)
        if signature.variadic_positional or signature.variadic_keyword:continue
        if any(symbol.has('free')for symbol in unit.scope_for(callback).symbols):continue
        try:signature.plan(CallArguments((Argument(node.args[1]),),()))
        except CallBindingError:continue
        result.add(unit.ordinal(callback))
    return frozenset(result)


class CallbackGraph(SemanticGraph):
    def __init__(self,unit,definitions,integer):
        self.callback_definitions=definitions;self.callback_integer=integer
        super().__init__(unit)

    def expression(self,node):
        site=self.unit.ordinal(node)
        if not(isinstance(node,ast.Lambda)and site in self.callback_definitions):return super().expression(node)
        if site in self.expressions:return self.expressions[site]
        self.site(node)
        signature=self.unit.signature_for(node)
        defaults=tuple((slot.name,self.expression(slot.expression))for slot in signature.defaults)
        body=(Operation(site,'return',(self.expression(node.body),)),)
        self.functions[site]=Function(site,'<lambda>',signature,body,defaults)
        result=Expression(site,'callback_lambda',(),site)
        self.expressions[site]=result
        return result


class CallbackSolver(Solver):
    def expression(self,term,state,globals,locals,context):
        if term.operation!='callback_lambda':return super().expression(term,state,globals,locals,context)
        definition=self.graph.functions[term.data]
        defaults=tuple((name,self.expression(child,state,globals,locals,context))for name,child in definition.defaults)
        result=value(FunctionValue(definition.site,defaults));self.records[(context,term.site)]=result
        return result

    def call(self,identity,args,keywords,term,state,globals,locals,context):
        if identity==BuiltinIdentity('filter')and len(args)==2:
            item=self.field_values(args[1],'iteration')
            for callback in args[0].alternatives:
                if isinstance(callback,FunctionValue)and callback.definition in self.graph.callback_definitions:
                    super().call(callback,(item,),(),term,state,globals,locals,context)
        return super().call(identity,args,keywords,term,state,globals,locals,context)


def supplement(unit,analysis,integer):
    definitions=_eligible(unit,analysis)
    return CallbackSolver(CallbackGraph(unit,definitions,integer)).solve()if definitions else analysis


def _stop_scopes(unit,analysis):
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)};edges={};marked=set()
    for facts in analysis.scopes.values():
        for site,call in facts.calls.items():
            scope=unit.nodes[site].scope
            if call.identity.unknown or call.identity.unbound:marked.add(scope)
            if BuiltinIdentity('next')in call.identity.alternatives and len(call.positional)==1 and not call.keywords:marked.add(scope)
            edges.setdefault(scope,set()).update(unit.scope_for(nodes[target.definition]).ordinal
                for target in call.identity.alternatives if isinstance(target,FunctionValue)and target.definition in nodes)
    while True:
        updated=marked|{scope for scope,targets in edges.items()if targets&marked}
        if updated==marked:return marked
        marked=updated


def _unary_call_capability(unit,node,fact,facts):
    from .native_builtin_values import UNARY_BUILTINS,unary_capability
    for identity in fact.identity.alternatives:
        if not isinstance(identity,BuiltinIdentity)or identity.name not in UNARY_BUILTINS:continue
        if len(node.args)!=1 or node.keywords or isinstance(node.args[0],ast.Starred):return False
        if not unary_capability(identity,facts.expressions.get(unit.ordinal(node.args[0]))):return False
    return True


def _blocked_call_definitions(unit,analysis):
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)};blocked=set();edges={}
    for (definition,_),facts in analysis.scopes.items():
        for site,fact in facts.calls.items():
            node=nodes.get(site)
            if not isinstance(node,ast.Call):continue
            if fact.identity.unknown or fact.identity.unbound or not _unary_call_capability(unit,node,fact,facts):blocked.add(definition)
            edges.setdefault(definition,set()).update(identity.definition for identity in fact.identity.alternatives if isinstance(identity,FunctionValue))
    while True:
        updated=blocked|{definition for definition,targets in edges.items()if targets&blocked}
        if updated==blocked:return blocked
        blocked=updated


def _expressions_closed(unit,root,facts,*,globals_forbidden=False,symbols=None):
    nodes=list(ast.walk(root));parents={id(child):parent for parent in nodes for child in ast.iter_child_nodes(parent)}
    symbols={}if symbols is None else symbols
    for node in nodes:
        if not isinstance(node,ast.expr)or isinstance(node,ast.Lambda):continue
        site=unit.ordinal(node);kind=facts.expressions.get(site)
        current=facts.values.get(site)
        if current is None or current.unknown or current.unbound:return False
        if _closed(kind):
            if globals_forbidden and isinstance(node,ast.Name):
                symbol=symbols.get(unit.name_for(node))
                if symbol is not None and symbol.has('global'):return False
        else:
            parent=parents.get(id(node))
            while isinstance(parent,ast.Attribute)and parent.value is node:
                node=parent;parent=parents.get(id(node))
            if not(isinstance(parent,ast.Call)and parent.func is node):return False
            if not current.alternatives or not all(isinstance(part,FunctionValue)or getattr(part,'_native_reference',False)for part in current.alternatives):return False
    return True


def _operators_closed(unit,node,facts,integer):
    from .native_primitive_ops import classify
    from .literal_semantics import Literal,integer_policy
    bits=0 if integer=='bigint'else 64 if integer=='i64'else 128
    for expression in ast.walk(node.body):
        if isinstance(expression,ast.NamedExpr):return False
        if isinstance(expression,ast.BinOp):
            left=facts.expressions.get(unit.ordinal(expression.left));right=facts.expressions.get(unit.ordinal(expression.right))
            for a in alternatives(left):
                for b in alternatives(right):
                    result=classify(expression.op,a,b,integer)
                    if result.protocol or result.error:return False
            if isinstance(expression.op,ast.Pow):
                literal=Literal.from_ast(expression.right)
                if literal is None or literal.kind not in {'int','bool'}or integer_policy(bits).normalize(literal.value)<0:return False
        if isinstance(expression,ast.UnaryOp)and not isinstance(expression.op,ast.Not):
            kind=facts.expressions.get(unit.ordinal(expression.operand))
            if kind not in ({'int','bool','int_bool'}if isinstance(expression.op,ast.Invert)else{'int','bool','int_bool','float'}):return False
    return True


def inline_callbacks(unit,analysis):
    definitions=getattr(analysis.graph,'callback_definitions',())
    if not definitions:return frozenset()
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)};parents={id(child):parent for parent in nodes.values()for child in ast.iter_child_nodes(parent)}
    stop=_stop_scopes(unit,analysis);blocked=_blocked_call_definitions(unit,analysis);result=set()
    for definition in definitions:
        node=nodes[definition];scope=unit.scope_for(node).ordinal
        if scope in stop or definition in blocked:continue
        contexts=[facts for (target,_),facts in analysis.scopes.items()if target==definition]
        if not contexts:continue
        if not all(_expressions_closed(unit,node.body,facts,globals_forbidden=True,symbols={symbol.name:symbol for symbol in unit.scope_for(node).symbols})and _operators_closed(unit,node,facts,analysis.graph.callback_integer)for facts in contexts):continue
        valid=True;seen=False
        for facts in analysis.scopes.values():
            for site,call in facts.calls.items():
                if not any(isinstance(part,FunctionValue)and part.definition==definition for value_ in call.positional[:1]for part in value_.alternatives):continue
                parent=nodes[site]
                if not(isinstance(parent,ast.Call)and parent.args and parent.args[0]is node):continue
                if call.identity.unknown or call.identity.unbound or len(call.identity.alternatives)!=1 or not call.identity.alternatives<={BuiltinIdentity('map'),BuiltinIdentity('filter')}:valid=False;break
                seen=True
                from .native_iterator_selection import _elements
                elements=_elements(unit,facts,parent.args[1])
                if not elements or not all(_closed(element)for element in elements):valid=False;break
                for part in call.positional[0].alternatives:
                    if isinstance(part,FunctionValue)and part.definition==definition:
                        for name,value_ in part.defaults:
                            # Default expression facts belong to the enclosing scope.
                            expression=next(slot.expression for slot in unit.signature_for(node).defaults if slot.name==name)
                            if not _closed(facts.expressions.get(unit.ordinal(expression))):valid=False
                            if not _expressions_closed(unit,expression,facts):valid=False
                            for child in ast.walk(expression):
                                if isinstance(child,ast.Call):
                                    info=facts.calls.get(unit.ordinal(child))
                                    if info is None or info.identity.unknown or info.identity.unbound:valid=False;continue
                                    if not _unary_call_capability(unit,child,info,facts):valid=False
                                    if any(isinstance(identity,FunctionValue)and identity.definition in blocked for identity in info.identity.alternatives):valid=False
                                    if BuiltinIdentity('next')in info.identity.alternatives and len(info.positional)==1 and not info.keywords:valid=False
                                    if any(isinstance(identity,FunctionValue)and unit.scope_for(nodes[identity.definition]).ordinal in stop for identity in info.identity.alternatives):valid=False
                consumer=parents.get(id(parent))
                if BuiltinIdentity('map')in call.identity.alternatives and isinstance(consumer,ast.Call):
                    identity=facts.calls.get(unit.ordinal(consumer))
                    if identity is not None and BuiltinIdentity('sum')in identity.identity.alternatives:
                        if any(fact.expressions.get(unit.ordinal(node.body))not in {'int','bool','int_bool'}for fact in contexts):valid=False
        if valid and seen:result.add(definition)
    return frozenset(result)
