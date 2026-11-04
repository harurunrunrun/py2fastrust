"""Pack scalar slots only after a closed initialized-instance proof."""
import ast


class Unproved(Exception):
    pass


class Registry:
    def __init__(self,model):
        self.model=model
        self.selected=set()
        self.reasons={}
        self.values=getattr(model,'value_classes',None)
        self.bindings={binding.node:binding for binding in model.iter_bindings()}
        for owner in model.classes.values():
            if self.values is None or owner.index not in self.values.selected:continue
            try:self.prove(owner)
            except Unproved as error:self.reasons[owner.index]=str(error)
            else:self.selected.add(owner.index)

    def kind(self,plan,node):return self.values.kind(plan,node)

    def class_reference(self,kind,owner,active=frozenset()):
        from .native_module_linking import ClassReferenceType
        if isinstance(kind,ClassReferenceType):return kind.definition==owner.index
        if id(kind)in active:return False
        active=active|{id(kind)}
        children=getattr(kind,'fields',())or getattr(kind,'alternatives',())
        children=(*children,*(getattr(kind,name)for name in('element','key','value')if hasattr(kind,name)),*getattr(kind,'_native_owned_kinds',()))
        return any(self.class_reference(child,owner,active)for child in children)

    def sealed(self,owner):
        from .native_aot_callables import AotFunctionType
        from .native_module_linking import ClassReferenceType
        raw_protocols={'__new__','__subclasses__','__getattribute__','__reduce__','__reduce_ex__','__getstate__','__setstate__'}
        reflection={'getattr','setattr','delattr','vars','locals','globals','eval','exec','compile','type'}
        namespace=getattr(self.model,'class_namespaces',None)
        for plan in self.values.plans.values():
            for node in self.values.own_nodes(plan):
                if isinstance(node,ast.Attribute):
                    if node.attr in raw_protocols:raise Unproved('raw allocation or reflective protocol is reachable')
                    if isinstance(node.ctx,ast.Del):
                        receiver=self.kind(plan,node.value)
                        if receiver is None or self.values.contains(receiver,owner):
                            raise Unproved('an instance field may be deleted')
                if not isinstance(node,ast.Call):continue
                names=self.values.builtin(plan,node)
                if names&reflection:raise Unproved('reflective builtin is reachable')
                callee=self.kind(plan,node.func)
                if isinstance(callee,AotFunctionType)and any(member.module=='gc'for member in callee.members):
                    raise Unproved('heap reflection or collection can observe construction')
                if isinstance(callee,ClassReferenceType)and callee.definition==owner.index:
                    if not self.values.constructor(plan,node,owner):raise Unproved('instance creation is not a sealed canonical constructor')
                arguments=[value.value if isinstance(value,ast.Starred)else value for value in node.args]+[part.value for part in node.keywords]
                class_argument=any(self.class_reference(self.kind(plan,value),owner)for value in arguments)
                instance_result=self.values.contains(self.kind(plan,node),owner)
                if not class_argument and not instance_result:continue
                if names and names<={'isinstance','issubclass'}:continue
                if isinstance(callee,ClassReferenceType):
                    actual=next((item for item in self.model.classes.values()if item.index==callee.definition),None)
                    if actual is not None and self.values.constructor(plan,node,actual):continue
                targets=self.model.call_edges_by_site.get((plan.index,id(node)),())
                if targets and all(target in self.values.plans for target in targets):continue
                if isinstance(callee,AotFunctionType)and callee.targets:
                    source=all((target if isinstance(target,int)else getattr(target,'definition',None))in self.model.callable_cells.plans for target in callee.targets)
                    if source:continue
                raise Unproved('class reference escapes into an unproved constructor protocol')
        if namespace is not None and any((owner.index,name)in namespace.members for name in owner.fields):
            raise Unproved('instance field shares a class namespace member')

    def prove(self,owner):
        from .native_classes import shape
        if not owner.fields:raise Unproved('no instance scalar fields to pack')
        initializer=owner.methods.get('__init__')
        if initializer is None or self.values.initializers.get(initializer.index)is not owner:
            raise Unproved('no sealed borrowed canonical initializer')
        if initializer.node.decorator_list or shape(initializer.result)!='none':
            raise Unproved('initializer result or descriptor is not plain None')
        arguments=[*initializer.node.args.posonlyargs,*initializer.node.args.args]
        if not arguments:raise Unproved('initializer lacks its positional instance parameter')
        parameter=self.bindings.get(self.model.unit.ordinal(arguments[0]))
        scope=self.model.unit.scope_for(initializer.node).ordinal
        if parameter is None or parameter.role!='parameter'or parameter.owner!=scope or parameter.scope!=scope:
            raise Unproved('initializer parameter ownership is not canonical')
        self.sealed(owner)
        flow=Initialized(self,owner,initializer,parameter)
        normal=flow.block(initializer.node.body,set())
        exits=flow.returns+([]if normal is None else[normal])
        required=set(owner.fields)
        if not exits or any(not required<=state for state in exits):
            raise Unproved('not every field is assigned on every normal initializer exit')


class Initialized:
    def __init__(self,registry,owner,plan,parameter):
        self.registry,self.owner,self.plan,self.parameter=registry,owner,plan,parameter
        self.returns=[]

    def field(self,node):
        if not isinstance(node,ast.Attribute)or not isinstance(node.value,ast.Name):return None
        binding=self.registry.bindings.get(self.registry.model.unit.ordinal(node.value))
        if binding is None or(binding.owner,binding.name)!=(self.parameter.owner,self.parameter.name):return None
        if binding.scope!=self.parameter.scope:raise Unproved('initializer receiver crosses a lexical boundary')
        field=self.registry.model.resolved_name(self.plan,node)
        if field not in self.owner.fields:raise Unproved('receiver attribute is not a plain scalar slot')
        return field

    def expression(self,node,initialized):
        if node is None:return
        for child in ast.walk(node):
            if not isinstance(child,ast.Attribute)or not isinstance(child.ctx,ast.Load):continue
            field=self.field(child)
            if field is not None and field not in initialized:
                raise Unproved('an initializer field read can precede its assignment')

    def store(self,target,initialized):
        if isinstance(target,ast.Name):return
        if isinstance(target,(ast.Tuple,ast.List)):
            for child in target.elts:self.store(child,initialized)
            return
        if isinstance(target,ast.Starred):return self.store(target.value,initialized)
        field=self.field(target)
        if field is None:raise Unproved('initializer store is not a plain local or instance slot')
        initialized.add(field)

    def block(self,statements,incoming):
        state=set(incoming)
        for node in statements:
            if isinstance(node,ast.Assign):
                self.expression(node.value,state)
                for target in node.targets:self.store(target,state)
            elif isinstance(node,ast.AnnAssign):
                if node.value is not None:self.expression(node.value,state);self.store(node.target,state)
                else:self.expression(node.target,state)
            elif isinstance(node,ast.AugAssign):
                field=self.field(node.target)
                if field is not None and field not in state:raise Unproved('augmented field store first reads an uninitialized slot')
                if field is None and not isinstance(node.target,ast.Name):raise Unproved('unproved augmented initializer store')
                self.expression(node.value,state)
            elif isinstance(node,ast.If):
                self.expression(node.test,state)
                yes=self.block(node.body,state);no=self.block(node.orelse,state)
                normal=[value for value in(yes,no)if value is not None]
                if not normal:return None
                state=set.intersection(*normal)
            elif isinstance(node,ast.Return):
                if node.value is not None and not(isinstance(node.value,ast.Constant)and node.value.value is None):
                    raise Unproved('initializer return is not literal None')
                self.returns.append(set(state));return None
            elif isinstance(node,ast.Assert):
                self.expression(node.test,state);self.expression(node.msg,state)
            elif isinstance(node,ast.Expr):self.expression(node.value,state)
            elif not isinstance(node,ast.Pass):raise Unproved('initializer control flow is not sealed straightline/if/return')
        return state


def prepare(model):model.packed_value_fields=Registry(model)


def selected(model,owner):
    return owner.index in getattr(getattr(model,'packed_value_fields',None),'selected',())


def initial(kind):return {'int':'0','bool':'false','float':'0.0_f64','none':'()'}[kind]


def raw(receiver,index):return f'({receiver}).borrow().field_{index}.get()'
