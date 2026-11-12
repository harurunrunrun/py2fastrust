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
            if self.values is None or not owner.used:continue
            try:self.prove(owner)
            except Unproved as error:self.reasons[owner.index]=str(error)
            else:self.selected.add(owner.index)

    def kind(self,plan,node):return self.values.kind(plan,node)

    def map_constructor(self,plan,node,owner,*,consumer=False):
        """The registered map callback allocates a fresh canonical instance."""
        from .native_classes import shape
        from .native_module_linking import ClassReferenceType
        for record in self.model.iterators.records:
            if record.operation != 'map':continue
            if not consumer and (record.plan is not plan or record.node is not node):continue
            kind=shape(record.callback)
            if not isinstance(kind,ClassReferenceType)or kind.definition!=owner.index:continue
            if not consumer:return True
            site=record.demands.get((plan.index,id(node)))
            if (site is not None and not(site.targets or site.errors or site.builtins
                    or site.members or site.exception_constructors)
                    and set(site.constructors)=={owner.index}
                    and site.constructors[owner.index].owner is owner
                    and site.constructors[owner.index].error is None):
                return True
        return False

    def shared_initializer(self,owner,initializer):
        """Retain shared identity/mutations; certify only field presence."""
        from .native_copy_scalar_fields import selected
        from .native_class_calls import synchronous
        from .native_classes import InstanceType,shape
        from .native_namespace_read_places import lifetime_closed
        if not selected(self.model,owner)or not lifetime_closed(self.model):
            raise Unproved('shared scalar layout lacks a closed lifetime certificate')
        if (owner.node.bases or owner.node.keywords or owner.node.decorator_list
                or owner.node.type_params or any(name in owner.methods for name in
                    ('__new__','__del__','__setattr__','__delattr__','__getattribute__','__getattr__'))):
            raise Unproved('shared allocation or attribute protocol is not plain')
        if not synchronous(self.model,initializer)or not initializer.runtime_parameters:
            raise Unproved('shared initializer can suspend or has no receiver')
        name=initializer.runtime_parameters[0]
        if shape(initializer.arguments[name])!=InstanceType(self.model.class_key(owner)):
            raise Unproved('shared initializer receiver has no exact instance layout')
        for (index,node_id),targets in self.model.call_edges_by_site.items():
            if initializer.index not in targets:continue
            caller=self.values.plans.get(index);node=self.values.nodes.get(node_id)
            if (caller is None or node is None or not(
                    self.values.constructor(caller,node,owner)
                    or self.map_constructor(caller,node,owner,consumer=True))):
                raise Unproved('initializer can be invoked on an existing or unproved instance')
        scope=self.model.lexical.scope(initializer)
        for node in self.values.own_nodes(initializer):
            if not isinstance(node,ast.Name)or self.model.resolved_name(initializer,node)!=name:continue
            parent=self.values.parents.get(id(node))
            binding=self.bindings.get(self.model.unit.ordinal(node))
            if (not isinstance(node.ctx,ast.Load)or binding is None
                    or binding.owner!=scope or binding.scope!=scope
                    or not isinstance(parent,ast.Attribute)or parent.value is not node
                    or self.model.resolved_name(initializer,parent)not in owner.fields):
                raise Unproved('partly initialized receiver can escape or invoke another protocol')

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
        raw_protocols={'__new__','__dict__','__subclasses__','__getattribute__','__reduce__','__reduce_ex__','__getstate__','__setstate__'}
        reflection={'getattr','setattr','delattr','vars','locals','globals','eval','exec','compile','type'}
        namespace=getattr(self.model,'class_namespaces',None)
        for plan in self.values.plans.values():
            for node in self.values.own_nodes(plan):
                if isinstance(node,ast.Attribute):
                    if node.attr in raw_protocols:raise Unproved('raw allocation or reflective protocol is reachable')
                    receiver=self.kind(plan,node.value)
                    if (isinstance(receiver,ClassReferenceType)and receiver.definition==owner.index
                            and isinstance(node.ctx,(ast.Store,ast.Del))):
                        raise Unproved('the source class namespace can change after publication')
                    if isinstance(node.ctx,ast.Del):
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
                if self.map_constructor(plan,node,owner):continue
                from .native_source_native_effects import _identity, sealed_builtin
                identity=_identity(self,plan,node.func)
                if identity is not None and sealed_builtin(self.model,identity,
                        [self.kind(plan,value)for value in arguments]):
                    continue
                if isinstance(callee,ClassReferenceType):
                    actual=next((item for item in self.model.classes.values()if item.index==callee.definition),None)
                    if actual is not None and self.values.constructor(plan,node,actual):continue
                targets=self.model.call_edges_by_site.get((plan.index,id(node)),())
                if targets and all(target in self.values.plans for target in targets):continue
                if isinstance(callee,AotFunctionType)and callee.targets:
                    source=all((target if isinstance(target,int)else getattr(target,'definition',None))in self.model.callable_cells.plans for target in callee.targets)
                    if source:continue
                raise Unproved('class reference escapes into an unproved constructor protocol: '
                               + ast.unparse(node)[:160])
        if namespace is not None and any((owner.index,name)in namespace.members for name in owner.fields):
            raise Unproved('instance field shares a class namespace member')

    def prove(self,owner):
        from .native_classes import shape
        if not owner.fields:raise Unproved('no instance scalar fields to pack')
        initializer=owner.methods.get('__init__')
        if initializer is None:raise Unproved('no canonical initializer')
        if self.values.initializers.get(initializer.index)is not owner:
            self.shared_initializer(owner,initializer)
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
