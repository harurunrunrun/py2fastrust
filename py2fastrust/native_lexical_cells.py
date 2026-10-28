"""Typed lexical environments for compiled nested functions.

Definition and binding identities come from SourceUnit, never a module-name
lookup. A lexical environment belongs to an invocation of its owning frame;
its schema is shared by all such invocations, its values are not.
"""
import ast
from dataclasses import dataclass,field


@dataclass
class EnvironmentShape:
    scope: int
    plan: object
    parent: int
    fields: dict=field(default_factory=dict)
    functions: dict=field(default_factory=dict)
    defaults: dict=field(default_factory=dict)


def requires_environments(unit,analysis,targets):
    """Nested executable FunctionDefs require closure conversion up front."""
    owners={binding.node:binding.owner for binding in unit.bindings if binding.role=='definition'}
    nodes={unit.ordinal(node):node for node in ast.walk(unit.tree)}
    entered={definition for definition,kinds in analysis.scopes if definition is not None}
    entered.update(definition for definitions in targets.values()for definition in definitions)
    scopes={unit.scope_for(nodes[definition]).ordinal for definition in entered}
    return any(isinstance(node,ast.FunctionDef)and owners.get(unit.ordinal(node),0)in scopes
               and unit.scopes[owners[unit.ordinal(node)]].kind=='function'
               for node in nodes.values())


def own_return_values(unit,node):
    """Nested returns do not determine an enclosing function's result ABI."""
    if unit is None:
        pending=list(node.body)
        while pending:
            value=pending.pop()
            if isinstance(value,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):continue
            if isinstance(value,ast.Return):yield value.value
            pending.extend(child for child in ast.iter_child_nodes(value)if isinstance(child,ast.stmt))
        return
    scope=unit.scope_for(node).ordinal
    for value in ast.walk(node):
        if isinstance(value,ast.Return)and unit.nodes[unit.ordinal(value)].scope==scope:yield value.value


class LexicalCells:
    def __init__(self,model):
        from .native_classes import Cell
        self.model=model
        self.unit=model.unit
        self.bindings={binding.node:binding for binding in self.unit.bindings}if self.unit else{}
        self.plans={}
        self.scope_plans={0:model.module}
        self.parents={0:None}
        self.definitions={}
        self.environments={}
        self.definition_cells={}
        self.boundary_writes=set()
        self.repeated_definitions=set()
        self.active=set()
        self.Cell=Cell
        if self.unit is not None:self.discover()

    def definition(self,plan):return self.unit.ordinal(plan.node)

    def scope(self,plan):return 0 if plan is self.model.module else self.unit.scope_for(plan.node).ordinal

    def execution_scope(self,scope):
        while scope is not None and self.unit.scopes[scope].kind=='comprehension':scope=self.unit.scopes[scope].parent
        return scope

    def discover(self):
        from .native_classes import ClassUnsupported
        # Existing module functions and class methods keep their registered
        # plans. Nested functions extend the canonical definition registry.
        for plan in self.model.plans[1:]:
            if not isinstance(plan.node,ast.FunctionDef):continue
            self.plans[self.definition(plan)]=plan
            self.scope_plans[self.scope(plan)]=plan
        nodes={self.unit.ordinal(node):node for node in ast.walk(self.unit.tree)}
        ast_parents={id(child):parent for parent in ast.walk(self.unit.tree)for child in ast.iter_child_nodes(parent)}
        pending=[(ordinal,node)for ordinal,node in nodes.items()
                 if isinstance(node,ast.FunctionDef)and ordinal not in self.plans]
        while pending:
            remaining=[]
            for ordinal,node in pending:
                binding=self.bindings.get(ordinal)
                owner=binding.owner if binding else 0
                if self.unit.scopes[owner].kind!='function':
                    raise ClassUnsupported(node,'this function definition belongs to an unimplemented class/dynamic namespace',proof='canonical lexical callable ownership')
                if owner not in self.scope_plans:remaining.append((ordinal,node));continue
                plan=self.model.function(node)
                self.plans[ordinal]=plan
                self.scope_plans[self.scope(plan)]=plan
            if len(remaining)==len(pending):
                raise ClassUnsupported(remaining[0][1],'the enclosing lexical function has no compiled frame plan',proof='lexical frame ancestry')
            pending=remaining
        for definition,plan in self.plans.items():
            binding=self.bindings[definition]
            owner=binding.owner
            if self.unit.scopes[owner].kind=='class':owner=0
            self.parents[self.scope(plan)]=owner
            if owner==0:continue
            key=owner,binding.name
            if key in self.definitions:
                raise ClassUnsupported(plan.node,'repeated definitions of one lexical callable binding require per-definition version/default cells',proof='lexical function definition versions')
            self.definitions[key]=plan
            parent=ast_parents.get(id(plan.node))
            while parent is not None and not isinstance(parent,(ast.FunctionDef,ast.ClassDef)):
                if isinstance(parent,(ast.For,ast.While,ast.AsyncFor)):self.repeated_definitions.add(definition)
                parent=ast_parents.get(id(parent))
            self.definition_cells[definition]=self.Cell('function',(definition,))
            environment=self.environment(owner)
            environment.functions[definition]=plan
            for name in plan.defaults:
                if name in plan.default_literals:continue
                environment.defaults[(plan.index,name)]=plan.default_cells[name]
                self.model.namespace.defaults.pop((plan.index,name),None)
        def qualify(plan):
            cached=getattr(plan,'qualified_name',None)
            if cached is not None:return cached
            parent=self.parents[self.scope(plan)]
            if plan.owner is not None:result=plan.owner.node.name+'.'+plan.node.name
            elif parent:result=qualify(self.scope_plans[parent])+'.<locals>.'+plan.node.name
            else:result=plan.node.name
            plan.qualified_name=result
            return result
        for plan in self.plans.values():qualify(plan)
        for binding in self.unit.bindings:
            key=binding.owner,binding.name
            if key in self.definitions and binding.role not in {'load','definition'}:
                self.boundary_writes.add(key)
            if binding.owner==0 or self.unit.scopes[binding.owner].kind!='function':continue
            if self.execution_scope(binding.scope)==binding.owner or key in self.definitions:continue
            environment=self.environment(binding.owner)
            environment.fields.setdefault(binding.name,self.Cell())
        # An environment can access every enclosing environment through a
        # typed parent pointer. There is one pointer per lexical nesting edge.
        for environment in list(self.environments.values()):
            parent=environment.parent
            while parent not in {0,None}:
                self.environment(parent)
                parent=self.parents[parent]

    def environment(self,scope):
        if scope not in self.environments:
            self.environments[scope]=EnvironmentShape(scope,self.scope_plans[scope],self.parents.get(scope,0))
        return self.environments[scope]

    def binding(self,node):return self.bindings.get(self.unit.ordinal(node))

    def function_for(self,node):
        binding=self.binding(node)
        return None if binding is None else self.definitions.get((binding.owner,binding.name))

    def field_for(self,node):
        binding=self.binding(node)
        environment=self.environments.get(binding.owner)if binding else None
        if environment is None or binding.name not in environment.fields:return None
        return environment,binding.name,environment.fields[binding.name]

    def store(self,plan,node,value,environment):
        field=self.field_for(node)
        if field is None:return False
        owner,name,schema=field
        self.model.namespace.contribute(schema,value,node,force=True)
        self.active.add(owner.scope)
        environment[name]=schema
        environment.definite.add(name)
        self.model.canonical_local(plan,name,schema)
        self.model.remember(plan,node,schema)
        return True

    def read(self,plan,node,environment):
        field=self.field_for(node)
        if field is None:return None
        owner,name,schema=field
        self.active.add(owner.scope)
        return schema

    def snapshot(self):
        from .native_classes import shape
        return tuple((scope,tuple((name,shape(cell))for name,cell in sorted(environment.fields.items())))
                     for scope,environment in sorted(self.environments.items()))

    def define(self,plan,node,environment):
        nested=self.plans.get(self.unit.ordinal(node))if isinstance(node,ast.FunctionDef)else None
        if nested is None or self.parents[self.scope(nested)]==0:return False
        binding=self.binding(node)
        if binding.owner!=self.scope(plan):return False
        if self.definition(nested)in self.repeated_definitions:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,'a nested function definition executed repeatedly in one enclosing frame needs distinct function-object/default instances, beyond one lexical environment instance',proof='per-execution nested callable identity and defaults')
        value=self.definition_cells[self.definition(nested)]
        environment[binding.name]=value
        environment.definite.add(binding.name)
        self.active.add(binding.owner)
        return True

    def function_value(self,plan,node,environment):
        target=self.function_for(node)
        if target is None:return None
        binding=self.binding(node)
        if(binding.owner,binding.name)in self.boundary_writes:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(node,'this lexical callable binding also has non-definition writes; versioned callable/closure lifetime cells are required',proof='lexical callable versions and cycle-safe environment ownership')
        self.active.add(binding.owner)
        return self.definition_cells[self.definition(target)]

    def seed_arguments(self,plan):
        shape=self.environments.get(self.scope(plan))
        if shape is None:return
        for name,value in plan.arguments.items():
            if name in shape.fields:
                self.model.namespace.contribute(shape.fields[name],value,plan.node,force=True)

    def default_uninhabited(self):
        for environment in self.environments.values():
            if not environment.plan.reachable:continue
            for cell in environment.fields.values():
                if cell.root().tag is None:cell.root().tag='int'

    def parent_scope(self,plan):return self.parents.get(self.scope(plan),0)

    def expression_environment(self,emitter,scope):
        own=self.scope(emitter.plan)
        if own==scope and own in self.environments:return 'class_lexical_environment'
        current=self.parent_scope(emitter.plan)
        code=getattr(emitter,'lexical_environment_override',None)or'class_lexical_parent'
        while current not in {scope,0,None}:
            code=f'({code}).parent.clone()'
            current=self.parents[current]
        if current!=scope:
            from .native_classes import ClassUnsupported
            raise ClassUnsupported(emitter.plan.node,'the requested lexical binding is not in this closure environment chain',proof='typed lexical environment ancestry')
        return code

    @staticmethod
    def environment_type(scope):return f'ClassLexicalEnvironment{scope}'

    def signature(self,plan):
        parent=self.parent_scope(plan)
        return ''if not parent else f',class_lexical_parent:std::rc::Rc<{self.environment_type(parent)}>'

    def error_message(self,emitter,node):
        binding=self.binding(node);name=binding.name
        if binding.owner==self.scope(emitter.plan):
            return f"UnboundLocalError: cannot access local variable '{name}' where it is not associated with a value"
        return f"NameError: cannot access free variable '{name}' where it is not associated with a value in enclosing scope"

    def emit_read(self,emitter,node,wanted):
        from .native import _string
        from .native_classes import Expression,shape
        field=self.field_for(node)
        if field is None:return None
        environment,name,schema=field;index=sorted(environment.fields).index(name)
        owner=self.expression_environment(emitter,environment.scope)
        code=f'class_lexical_get_{environment.scope}_{index}(&({owner})).ok_or_else(||{_string(self.error_message(emitter,node))}.to_owned())'
        value=Expression(emitter.at(code,node),shape(schema))
        return Expression(emitter.coerce(value,wanted,node),wanted)

    def emit_store(self,emitter,node,value):
        from .native_classes import shape
        field=self.field_for(node)
        if field is None:return None
        environment,name,schema=field;index=sorted(environment.fields).index(name)
        owner=self.expression_environment(emitter,environment.scope)
        return f'({owner}).value_{index}.replace(Some({emitter.coerce(value,shape(schema),node)}));'

    def emit_function(self,emitter,node,wanted):
        from .native import _string
        from .native_classes import Expression
        from .native_aot_callables import AotFunctionType
        target=self.function_for(node)
        if target is None:return None
        parent=self.parent_scope(target);definition=self.definition(target)
        owner=self.expression_environment(emitter,parent)
        code=f'if ({owner}).defined_{definition}.get(){{Ok(ClassFunctionRef::F{definition}(({owner}).clone()))}}else{{Err({_string(self.error_message(emitter,node))}.to_owned())}}'
        value=Expression(emitter.at(code,node),AotFunctionType((definition,)))
        return Expression(emitter.coerce(value,wanted,node),wanted)

    def emit_define(self,emitter,node):
        from .native_classes import shape
        plan=self.plans.get(self.unit.ordinal(node))if isinstance(node,ast.FunctionDef)else None
        if plan is None or not self.parent_scope(plan):return None
        owner=self.environment(self.parent_scope(plan));environment=self.expression_environment(emitter,owner.scope);code=[]
        for name,expression in plan.defaults.items():
            if name in plan.default_literals:continue
            before,value=emitter.capture(emitter.expression(expression));index=sorted(owner.defaults).index((plan.index,name))
            code.append(before+f'({environment}).default_{index}.replace(Some({emitter.coerce(value,shape(plan.default_cells[name]),expression)}));')
        code.append(f'({environment}).defined_{self.definition(plan)}.set(true);')
        return ''.join(code)

    def default_read(self,emitter,plan,name):
        from .native_classes import Expression,shape
        parent=self.parent_scope(plan)
        if not parent:return None
        owner=self.environments[parent];index=sorted(owner.defaults).index((plan.index,name))
        # During indirect dispatch this must be the captured callee's owner,
        # not an environment belonging to another invocation of the caller.
        environment=getattr(emitter,'lexical_environment_override',None)
        if environment is None:environment=self.expression_environment(emitter,parent)
        code=f'class_lexical_default_{parent}_{index}(&({environment}))'
        return Expression(code,shape(plan.default_cells[name]))

    def initialize(self,emitter):
        from .native_classes import Expression,shape
        scope=self.scope(emitter.plan);environment=self.environments.get(scope)
        if environment is None:return ''
        parent=''if not environment.parent else 'class_lexical_parent.clone()'
        code=f'let class_lexical_environment=std::rc::Rc::new({self.environment_type(scope)}::new({parent}));'
        for index,name in enumerate(emitter.plan.parameters+emitter.plan.keyword_only):
            if name not in environment.fields:continue
            argument=Expression(f'class_argument_{index}',shape(emitter.plan.arguments[name]));slot=sorted(environment.fields).index(name)
            code+=f'class_lexical_environment.value_{slot}.replace(Some({emitter.coerce(argument,shape(environment.fields[name]),emitter.plan.node)}));'
        return code

    def delete(self,plan,node,environment):
        field=self.field_for(node)
        if field is None:return False
        owner,name,schema=field;self.active.add(owner.scope)
        environment[name]=schema;environment.definite.discard(name);self.model.remember(plan,node,schema)
        return True

    def emit_delete(self,emitter,node):
        from .native import _string
        field=self.field_for(node)
        if field is None:return None
        owner,name,schema=field;environment=self.expression_environment(emitter,owner.scope);index=sorted(owner.fields).index(name)
        result=f'if ({environment}).value_{index}.borrow_mut().take().is_some(){{Ok(())}}else{{Err({_string(self.error_message(emitter,node))}.to_owned())}}'
        return emitter.at(result,node)+';'

    def runtime(self,emitter):
        from .native_classes import shape
        lines=[]
        for scope,environment in sorted(self.environments.items()):
            if not environment.plan.reachable:continue
            fields=[];initial=[];parameters=[]
            if environment.parent:
                parent=self.environment_type(environment.parent)
                fields.append(f'parent:std::rc::Rc<{parent}>');initial.append('parent');parameters.append(f'parent:std::rc::Rc<{parent}>')
            for index,(name,cell)in enumerate(sorted(environment.fields.items())):
                kind=emitter.rust_type(shape(cell));fields.append(f'value_{index}:std::cell::RefCell<Option<{kind}>>');initial.append(f'value_{index}:std::cell::RefCell::new(None)')
                lines.append(f'fn class_lexical_get_{scope}_{index}(owner:&std::rc::Rc<{self.environment_type(scope)}>)->Option<{kind}>{{owner.value_{index}.borrow().clone()}}')
            for definition in sorted(environment.functions):
                fields.append(f'defined_{definition}:std::cell::Cell<bool>');initial.append(f'defined_{definition}:std::cell::Cell::new(false)')
            for index,((plan_index,name),cell)in enumerate(sorted(environment.defaults.items())):
                kind=emitter.rust_type(shape(cell));fields.append(f'default_{index}:std::cell::RefCell<Option<{kind}>>');initial.append(f'default_{index}:std::cell::RefCell::new(None)')
                lines.append(f'fn class_lexical_default_{scope}_{index}(owner:&std::rc::Rc<{self.environment_type(scope)}>)->{kind}{{owner.default_{index}.borrow().clone().expect("lexical default initialized before callable binding")}}')
            name=self.environment_type(scope);lines.append(f'struct {name}{{'+','.join(fields)+'}')
            lines.append(f'impl {name}{{fn new('+','.join(parameters)+')->Self{Self{'+','.join(initial)+'}}}')
        return '\n'.join(lines)

    def validate(self):
        """Reject unproved Rc cycles rather than retain every dead invocation."""
        from .native_classes import ClassUnsupported,InstanceType,shape
        from .native_types import ListType,TupleType,NullableType,MaybeType,UnionType
        def targets(kind):
            if getattr(kind,'_native_function_reference',False):
                for definition in kind.definitions:
                    parent=self.parent_scope(self.plans[definition])
                    if parent:yield('environment',parent)
            elif isinstance(kind,InstanceType):yield('object',kind.name)
            elif isinstance(kind,(NullableType,MaybeType)):yield from targets(kind.value)
            elif isinstance(kind,ListType):yield from targets(kind.element)
            elif isinstance(kind,TupleType):
                for field in kind.fields:yield from targets(field)
            elif isinstance(kind,UnionType):
                for branch in kind.alternatives:yield from targets(branch)
        edges={}
        for scope,environment in self.environments.items():
            if not environment.plan.reachable:continue
            node=('environment',scope);edges[node]=set()
            if environment.parent:edges[node].add(('environment',environment.parent))
            for cell in(*environment.fields.values(),*environment.defaults.values()):
                self.model.storage(cell,environment.plan.node)
                edges[node].update(targets(shape(cell)))
        for name,owner in self.model.classes.items():
            edges[('object',name)]={target for field in owner.fields.values()for target in targets(shape(field.cell))}
        done=set();visiting=set()
        def visit(node):
            if node in visiting:
                owner=next(iter(self.environments.values()))
                raise ClassUnsupported(owner.plan.node,'these captured object/function fields can form a reference cycle; cycle-aware closure lifetime collection is not implemented, so an invocation environment cannot safely be retained by Rc alone',proof='cycle-safe lexical environment ownership')
            if node in done:return
            visiting.add(node)
            for target in edges.get(node,()):visit(target)
            visiting.remove(node);done.add(node)
        if self.environments:
            for node in edges:visit(node)
