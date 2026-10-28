"""Original-AST lambda plans and per-evaluation typed callable instances.

A lambda's executable scope is official frontend metadata. Each evaluation
allocates a new function object, while captured local cells are shared with its
lexical owner. Default values live on that object, never on a code definition.
"""
import ast


def inline_definitions(unit,analysis):
    """Canonical proof of existing immediate/eager callback consumers."""
    from .native_constraints import Allocation,MethodValue
    from .references import BuiltinIdentity
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    parents={id(child):parent for parent in nodes.values()for child in ast.iter_child_nodes(parent)}
    calls={}
    for facts in analysis.scopes.values():
        for site,call in facts.calls.items():
            calls[site]=call.identity if site not in calls else calls[site].join(call.identity)
    result=set()
    for ordinal,node in nodes.items():
        if not isinstance(node,ast.Lambda)or id(node)not in unit.function_signatures:continue
        parent=parents.get(id(node))
        if isinstance(parent,ast.Call)and parent.func is node:
            result.add(ordinal);continue
        # Both consumers have an existing eager callback lowering. Proof uses
        # resolved identities and receiver allocation kind, never spelling.
        if not(isinstance(parent,ast.keyword)and parent.arg=='key'):continue
        call=parents.get(id(parent));fact=calls.get(unit.ordinal(call))if isinstance(call,ast.Call)else None
        if fact is None or fact.unknown or fact.unbound or not fact.alternatives:continue
        def eager(identity):
            if identity==BuiltinIdentity('sorted'):return True
            return(isinstance(identity,MethodValue)and identity.name=='sort'
                   and not(identity.receiver.unknown or identity.receiver.unbound)
                   and identity.receiver.alternatives
                   and all(isinstance(item,Allocation)and item.category=='list'for item in identity.receiver.alternatives))
        if all(eager(identity)for identity in fact.alternatives):result.add(ordinal)
    return frozenset(result)


def requires_instances(unit,analysis,targets):
    """Select escaping lambdas before lowering; retain proved eager callbacks."""
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    parents={id(child):parent for parent in nodes.values()for child in ast.iter_child_nodes(parent)}
    entered={definition for definition,kinds in analysis.scopes if definition is not None}
    entered.update(definition for definitions in targets.values()for definition in definitions)
    scopes={0}|{unit.scope_for(nodes[definition]).ordinal for definition in entered}
    inline=inline_definitions(unit,analysis)
    # A directly invoked original Lambda enters its official body scope even
    # when the shared ordinary-function solver has no function-value fact yet.
    while True:
        previous=len(scopes)
        for ordinal,node in nodes.items():
            if not isinstance(node,ast.Lambda)or id(node)not in unit.function_signatures:continue
            parent=parents.get(id(node));owner=unit.nodes[ordinal].scope
            while unit.scopes[owner].kind=='comprehension':owner=unit.scopes[owner].parent
            if owner in scopes and isinstance(parent,ast.Call)and parent.func is node:
                scopes.add(unit.scope_for(node).ordinal)
        if len(scopes)==previous:break
    for ordinal,node in nodes.items():
        if not isinstance(node,ast.Lambda)or id(node)not in unit.function_signatures:continue
        owner=unit.nodes[ordinal].scope
        while unit.scopes[owner].kind=='comprehension':owner=unit.scopes[owner].parent
        if owner in scopes and ordinal not in inline:return True
    return False


class LambdaCells:
    def __init__(self,model):
        self.model=model
        self.plans={}
        self.active=set()

    def is_lambda(self,plan):return isinstance(plan.node,ast.Lambda)

    def capture_parent(self,plan,parent):
        # Definition/default evaluation and lexical qualification still use
        # the real enclosing scope. The runtime object needs it only when the
        # official body symbol table reports free lexical cells.
        scope=self.model.unit.scope_for(plan.node)
        return parent if any(symbol.has('free')for symbol in scope.symbols)else 0

    def register_scope(self,lexical,scope):
        if scope in lexical.scope_plans:return True
        metadata=self.model.unit.scopes[scope]
        if metadata.kind!='comprehension':return False
        if not self.register_scope(lexical,metadata.parent):return False
        # A logical inlined scope has cells, but no synthesized callable plan.
        lexical.scope_plans[scope]=lexical.scope_plans[metadata.parent]
        lexical.parents[scope]=metadata.parent
        return True

    def register(self,lexical,definition,node,owner):
        plan=self.model.function(node)
        self.plans[definition]=plan
        lexical.plans[definition]=plan
        scope=self.model.unit.scope_for(node).ordinal
        lexical.scope_plans[scope]=plan
        lexical.parents[scope]=owner
        captured=self.capture_parent(plan,owner)
        if captured:lexical.environment(captured)
        for name in plan.defaults:self.model.namespace.defaults.pop((plan.index,name),None)
        return plan

    def value(self,plan,node,environment):
        from .native_classes import Cell,ClassUnsupported
        definition=self.model.unit.ordinal(node)
        target=self.plans[definition]
        owner=self.model.lexical.parent_scope(target)
        for name,expression in target.defaults.items():
            if name in target.default_literals:continue
            value=self.model.expression(plan,expression,environment)
            self.model.contribute(target.default_cells[name],value,expression)
        self.active.add(definition)
        self.model.callable_cells.used.add(definition)
        return self.model.remember(plan,node,self.model.cell(plan,node,'function',(definition,)))

    @staticmethod
    def instance_type(definition):return f'ClassLambdaInstance{definition}'

    def payload_type(self,target):return self.instance_type(self.model.unit.ordinal(target.node))

    def emit_value(self,emitter,node):
        from .native_aot_callables import AotFunctionType
        from .native_classes import Expression,shape
        definition=self.model.unit.ordinal(node);plan=self.plans[definition]
        lines=[];fields=[]
        parent=self.model.lexical.parent_scope(plan)
        if parent:
            owner=self.model.lexical.expression_environment(emitter,parent)
            fields.append(f'environment:({owner}).clone()')
        for index,(name,expression)in enumerate(plan.defaults.items()):
            if name in plan.default_literals:continue
            before,value=emitter.capture(emitter.expression(expression));lines.append(before)
            fields.append(f'default_{index}:'+emitter.coerce(value,shape(plan.default_cells[name]),expression))
        instance=f'std::rc::Rc::new({self.instance_type(definition)}{{'+','.join(fields)+'})'
        value=self.model.callable_cells.lambda_reference_code(emitter,plan,instance)
        return Expression('{'+''.join(lines)+value+'}',AotFunctionType((definition,)))

    def default_read(self,emitter,plan,name):
        from .native_classes import Expression,shape
        instance=getattr(emitter,'lambda_instance_override',None)
        if instance is None:raise RuntimeError('lambda defaults require a captured current callee instance')
        index=list(plan.defaults).index(name)
        return Expression(f'({instance}).default_{index}.clone()',shape(plan.default_cells[name]))

    def comprehension_initialize(self,emitter,node):
        scope=self.model.unit.scope_for(node).ordinal
        shape=self.model.lexical.environments.get(scope)
        if shape is None:return '',None
        name=emitter.fresh()
        parent=''if not shape.parent else self.model.lexical.expression_environment(emitter,shape.parent)+'.clone()'
        return f'let {name}=std::rc::Rc::new({self.model.lexical.environment_type(scope)}::new({parent}));',(scope,name)

    def add_lifetime_edges(self,edges,targets):
        from .native_classes import shape
        for definition in self.active:
            plan=self.plans[definition];node=('lambda',definition);edges[node]=set()
            parent=self.model.lexical.parent_scope(plan)
            if parent:edges[node].add(('environment',parent))
            for cell in plan.default_cells.values():edges[node].update(targets(shape(cell)))

    def runtime(self,emitter):
        from .native_classes import shape
        lines=[]
        for definition in sorted(self.active):
            plan=self.plans[definition];fields=[]
            parent=self.model.lexical.parent_scope(plan)
            if parent:fields.append('environment:std::rc::Rc<'+self.model.lexical.environment_type(parent)+'>')
            for index,name in enumerate(plan.defaults):
                if name not in plan.default_literals:
                    fields.append(f'default_{index}:'+emitter.rust_type(shape(plan.default_cells[name])))
            lines.append('struct '+self.instance_type(definition)+'{'+','.join(fields)+'}')
        return '\n'.join(lines)
