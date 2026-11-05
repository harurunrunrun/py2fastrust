"""Original-source adapter for shared scalar and heap value constraints.

Type cells supply kinds and conservative allocation origins, never scalar value
equalities. All source writes and call contexts contribute to separate facts.
"""
import ast

from .native_scalar_constant_facts import Graph,Producer,ProducerCoverage


class Unproved(Exception):
    pass


class Registry:
    def __init__(self,model):
        self.model=model
        try:
            from .native_frame_specialization import source_plan
        except ModuleNotFoundError as error:
            if error.name!=__package__+'.native_frame_specialization':raise
            source_plan=lambda plan:plan
        self.source_plan=source_plan
        self.reason=None
        self.fields={}
        self.values=model.value_classes
        self.plans={plan.index:plan for plan in model.plans if plan.reachable}
        self.nodes={id(node):node for node in model.iter_nodes()}
        self.binding_rows=tuple(model.iter_bindings())
        self.bindings={binding.node:binding for binding in self.binding_rows}
        self.bindings_by_node={}
        for binding in self.binding_rows:
            self.bindings_by_node.setdefault(binding.node,[]).append(binding)
        self.graph=Graph(0 if model.integer=='bigint'else int(model.integer[1:]))
        self.built=set()
        self.parameter_inputs=set()
        self.heap_nodes=set()
        self.heap_unknown=False
        self.class_scopes={}
        self.calls=set()
        self.coverage=ProducerCoverage()
        try:
            self.prepare()
        except Unproved as error:
            self.reason=str(error)
            return
        self.graph.finalize()
        from .native_classes import shape
        from .native_value_classes import selected
        for owner in model.classes.values():
            if not owner.used or not selected(model,owner):continue
            for index,(name,field)in enumerate(owner.fields.items()):
                fact=self.graph.constant(self.field(owner,name))
                kind=shape(field.cell)
                if fact is not None and fact.kind==kind and kind in{'int','bool'}:
                    self.fields[owner.index,index]=fact

    def source(self,plan):
        # The specialization API retains original definition metadata; actual
        # native plan indices still key local expression facts and call edges.
        return self.source_plan(plan)

    def kind(self,plan,node):
        from .native_classes import shape
        cell=self.model.records.get((plan.index,id(node)))
        return None if cell is None else shape(cell)

    def expr(self,plan,node):return('expression',plan.index,id(node))
    def result(self,plan):return('result',plan.index)
    def parameter(self,plan,name):return('parameter',plan.index,name)
    def field(self,owner,name):return('instance_field',owner.index,name)
    def member(self,owner,name):return('class_member',owner.index,name)

    def producer(self,plan,node,operation,scope=None):
        unit=self.model.unit
        source=unit.original_unit(node)if hasattr(unit,'original_unit')else unit
        return Producer(source.name,scope,unit.ordinal(node),plan.index,operation)

    def cover_binding(self,plan,node):
        role=('parameter'if isinstance(node,ast.arg)else'delete'
              if isinstance(getattr(node,'ctx',None),ast.Del)else'store')
        for binding in self.bindings_by_node.get(self.model.unit.ordinal(node),()):
            if binding.role==role:
                self.coverage.record(self.producer(plan,node,'binding:'+role,binding.owner))

    def cover_target(self,plan,node):
        self.coverage.record(self.producer(plan,node,'heap_target'))

    def builtins(self,plan,node):
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        kind=self.kind(plan,node.func)
        targets=getattr(kind,'targets',())
        if targets:
            names=set()
            for target in targets:
                if isinstance(target,BuiltinIdentity):names.add(target.name)
                elif isinstance(target,BuiltinRef)and target.module=='builtins':names.add(target.name)
                else:return set()
            return names
        if isinstance(node.func,ast.Name):
            from .native_physical_list_builtins import static_builtin
            if static_builtin(self.model,plan,node.func,node.func.id):return{node.func.id}
        return set()
    def heap(self,origin):
        result=('list_element',origin)
        self.heap_nodes.add(result)
        return result

    def binding(self,plan,node):
        try:binding=self.bindings.get(self.model.unit.ordinal(node))
        except KeyError:binding=None
        if binding is None:return None
        owner=self.class_scopes.get(binding.owner)
        if owner is not None:return self.member(owner,binding.name)
        # Joining a lexical binding across source/native contexts is a MAY
        # value summary, not equality between those runtime bindings.
        return('binding',binding.owner,binding.name)

    def origins(self,plan,node):
        cell=self.model.records.get((plan.index,id(node)))
        return self.cell_origins(cell)

    def cell_origins(self,cell):
        if cell is None:return None
        cell=cell.root()
        if cell.tag=='list':return cell.list_origins
        if cell.tag=='union':
            found=set()
            for child in cell.args:
                origins=self.cell_origins(child)
                if origins is None:return None
                found.update(origins)
            return frozenset(found)
        return None

    def element(self,plan,node,target):
        origins=self.origins(plan,node)
        if not origins:self.graph.unknown(target)
        else:
            for origin in origins:self.graph.copy(target,self.heap(origin))

    def poison(self,plan,node):
        from .native_classes import InstanceType,shape
        from .native_module_linking import ClassReferenceType
        from .native_types import ListType,TupleType,TupleSequenceType,UnionType,NullableType
        seen=set()
        def visit(cell):
            if cell is None:return
            cell=cell.root()
            if id(cell)in seen:return
            seen.add(id(cell));kind=shape(cell)
            if cell.tag=='list':
                origins=cell.list_origins
                if origins:
                    for origin in origins:self.graph.unknown(self.heap(origin))
                else:self.heap_unknown=True
            elif isinstance(kind,(InstanceType,ClassReferenceType)):
                raise Unproved('an opaque native consumer can reach source instance/class state')
            else:
                for child in cell.args:
                    if hasattr(child,'root'):visit(child)
                # Registered payload families can retain mutable leaves not
                # represented by positional Cell.args. Unknown origins lose
                # the heap proof instead of dropping those ownership edges.
                def owned(kind,path=frozenset()):
                    if id(kind)in path:return
                    if isinstance(kind,(InstanceType,ClassReferenceType)):
                        raise Unproved('an opaque native consumer retains source instance/class state')
                    if isinstance(kind,ListType):self.heap_unknown=True
                    path=path|{id(kind)}
                    for child in getattr(kind,'_native_owned_kinds',()):owned(child,path)
                # A descriptor-tagged Cell can expose the semantic container
                # only through shape(), with no child Cell/origin payload.
                # Inspect the root kind too, not just its registered children.
                from .native_class_identity_demand import children
                def descriptor(kind,path=frozenset()):
                    if id(kind)in path:return
                    owned(kind,path)
                    path=path|{id(kind)}
                    for child in children(kind):descriptor(child,path)
                descriptor(kind)
        visit(self.model.records.get((plan.index,id(node))))

    def source_call(self,plan,node):
        from .native_classes import shape,InstanceType
        from .native_module_linking import ClassReferenceType
        from .native_aot_callables import AotFunctionType
        from .native_bound_methods import BoundMethodTarget
        kind=self.kind(plan,node.func)
        site=self.model.callable_cells.sites.get((plan.index,id(node)))
        if kind is None and site is not None:kind=shape(site.callee)
        if isinstance(kind,ClassReferenceType):return True
        if isinstance(kind,AotFunctionType):
            return bool(kind.targets)and all(isinstance(target,(int,BoundMethodTarget))for target in kind.targets)
        # Model.call's ordinary object-method branch enters the exact compiled
        # owner method without materializing a callable cell. Native list,
        # mapping, deque, text and module operations have different receivers;
        # their source callback edges alone never satisfy this certificate.
        if(isinstance(node.func,ast.Attribute)and site is None
                and not any(isinstance(arg,ast.Starred)for arg in node.args)
                and all(item.arg is not None for item in node.keywords)):
            receiver=self.kind(plan,node.func.value)
            if isinstance(receiver,InstanceType):
                owner=self.model.classes[receiver.name]
                method=owner.methods.get(self.model.resolved_name(plan,node.func))
                targets=self.model.call_edges_by_site.get((plan.index,id(node)),())
                if method is not None and targets and all(
                        index in self.plans and self.source(self.plans[index])is self.source(method)
                        for index in targets):return True
        from .native_frame_references import call_target
        return call_target(self.model,plan,node)is not None

    def check_callback_payloads(self,plan,node):
        return self.check_callback_inputs(plan,[*node.args,*(item.value for item in node.keywords)])

    def check_callback_inputs(self,plan,inputs):
        from .native_aot_callables import AotFunctionType
        from .native_bound_methods import BoundMethodTarget
        from .native_class_identity_demand import children
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        seen=set()
        def visit(kind):
            if id(kind)in seen:return
            seen.add(id(kind))
            if isinstance(kind,AotFunctionType):
                for target in kind.targets:
                    if isinstance(target,BuiltinIdentity):
                        if target.name in{'getattr','setattr','delattr','vars','locals','globals','eval','exec','compile'}:
                            raise Unproved('a native callback has unclosed namespace effects')
                    elif isinstance(target,(int,BoundMethodTarget)):
                        definition=getattr(target,'definition',target)
                        source=self.model.callable_cells.plans.get(definition)
                        if source is None or not any(self.source(item)is source for item in self.plans.values()):
                            raise Unproved('a retained callback lacks a reached source effect body')
                    else:
                        # Module/native callback effects need their own heap
                        # transfer; source callback edges do not describe them.
                        raise Unproved('a native callback lacks a scalar/heap mutation transfer')
            elif getattr(kind,'_native_function_reference',False):
                raise Unproved('an opaque callable payload lacks source heap effects')
            for child in children(kind):visit(child)
        for value in inputs:
            visit(self.kind(plan,value.value if isinstance(value,ast.Starred)else value))

    def prepare(self):
        if self.model.unit is None:raise Unproved('no official source/binding identity')
        from .native_finite_depth_calls import _model_proof,Unproved as CallsUnproved
        try:self.call_proof=_model_proof(self.model)
        except CallsUnproved as error:raise Unproved(str(error))from None
        for owner in self.model.classes.values():
            self.class_scopes[self.model.unit.scope_for(owner.node).ordinal]=owner
        from .native_classes import shape
        # Parameters and binding stores are independent of the scalar type-cell
        # union-find. Every actual source/native invocation contributes below.
        for plan in self.plans.values():
            source=self.source(plan)
            args=getattr(source.node,'args',None)
            if args is not None:
                for argument in[*args.posonlyargs,*args.args,*args.kwonlyargs]:
                    name=self.model.resolved_name(plan,argument)
                    if name not in plan.arguments:continue
                    key=self.binding(plan,argument)
                    if key is not None:
                        self.graph.copy(key,self.parameter(plan,name))
                        self.cover_binding(plan,argument)
            for node in self.values.own_nodes(plan):
                if isinstance(node,ast.expr):self.expression(plan,node)
                if isinstance(node,ast.stmt):self.statement(plan,node)
            if isinstance(source.node,ast.Lambda):
                self.graph.copy(self.result(plan),self.expression(plan,source.node.body))
        self.call_inputs()
        for plan in self.plans.values():
            for name,cell in plan.arguments.items():
                if(plan.index,name)not in self.parameter_inputs:
                    self.graph.unknown(self.parameter(plan,name))
            if shape(plan.result)not in{'int','bool'}:self.graph.unknown(self.result(plan))
        self.audit_producers()
        if self.heap_unknown:
            for key in self.heap_nodes:self.graph.unknown(key)

    def omitted(self,plan,node):
        reached=getattr(self.model,'reached_statements',None)
        if reached is None:return False
        while node is not None and not isinstance(node,ast.stmt):node=self.values.parents.get(id(node))
        return node is not None and(plan.index,id(node))not in reached

    def expression(self,plan,node):
        key=self.expr(plan,node)
        if key in self.built:return key
        self.built.add(key)
        if self.omitted(plan,node):return key
        self.graph.values.setdefault(key,None)
        kind=self.kind(plan,node)
        if isinstance(node,ast.Constant):
            tag='bool'if type(node.value)is bool else'int'if type(node.value)is int else None
            if tag is None:self.graph.unknown(key)
            else:self.graph.seed(key,tag,node.value)
        elif isinstance(node,ast.Name):
            binding=self.binding(plan,node)
            if binding is None:self.graph.unknown(key)
            else:self.graph.copy(key,binding)
        elif isinstance(node,ast.NamedExpr):
            value=self.expression(plan,node.value)
            self.target(plan,node.target,value)
            self.graph.copy(key,value)
        elif isinstance(node,ast.UnaryOp):
            self.graph.add(key,type(node.op).__name__,(self.expression(plan,node.operand),))
        elif isinstance(node,ast.BinOp)and kind in{'int','bool'}:
            self.graph.add(key,type(node.op).__name__,(self.expression(plan,node.left),self.expression(plan,node.right)))
        elif isinstance(node,ast.IfExp):
            self.graph.copy(key,self.expression(plan,node.body));self.graph.copy(key,self.expression(plan,node.orelse))
        elif isinstance(node,ast.Attribute):self.attribute(plan,node,key)
        elif isinstance(node,ast.Subscript)and not isinstance(node.slice,ast.Slice):self.element(plan,node.value,key)
        elif isinstance(node,ast.Call):
            self.check_callback_payloads(plan,node)
            self.call(plan,node,key)
            self.coverage.record(self.producer(plan,node,'call_effect'))
        else:self.graph.unknown(key)
        # Non-scalar successful values are unknown in this scalar domain, not
        # Bottom. Otherwise a mixed branch could silently discard a producer.
        if kind not in{'int','bool'}and not(isinstance(node,ast.Constant)and type(node.value)in{int,bool}):
            self.graph.unknown(key)
        self.allocation(plan,node)
        return key

    def attribute(self,plan,node,key):
        from .native_classes import InstanceType
        from .native_module_linking import ClassReferenceType
        receiver=self.kind(plan,node.value)
        name=self.model.resolved_name(plan,node)
        if isinstance(receiver,InstanceType):
            owner=self.model.classes[receiver.name]
            field=owner.fields.get(name)
            member=getattr(self.model,'class_namespaces',None)
            shared=None if member is None else member.members.get((owner.index,name))
            if field is not None and field.written:self.graph.copy(key,self.field(owner,name))
            if shared is not None and shared.plan is None:self.graph.copy(key,self.member(owner,name))
            if field is None and shared is None:self.graph.unknown(key)
        elif isinstance(receiver,ClassReferenceType):
            owner=next(owner for owner in self.model.classes.values()if owner.index==receiver.definition)
            self.graph.copy(key,self.member(owner,name))
        else:self.graph.unknown(key)

    def allocation(self,plan,node):
        from .native_types import ListType
        if not isinstance(self.kind(plan,node),ListType):return
        origins=self.origins(plan,node)
        if not origins:return
        # Only an allocation made by this node seeds its elements. A list Name
        # or attribute merely carries aliases to existing heap locations.
        records=getattr(self.model,'list_position_allocations',{})
        actual=[origin for origin in origins if origin in records and records[origin].node is node]
        for origin in actual:
            key=self.heap(origin)
            if isinstance(node,ast.List):
                if not node.elts:
                    self.graph.certify_empty_allocation(key,self.producer(plan,node,'empty_list'))
                for value in node.elts:self.graph.copy(key,self.expression(plan,value))
            elif isinstance(node,ast.ListComp):self.graph.copy(key,self.expression(plan,node.elt))
            elif isinstance(node,ast.BinOp)and isinstance(node.op,ast.Mult):
                left,right=node.left,node.right
                source=left if isinstance(self.kind(plan,left),ListType)else right
                self.element(plan,source,key)
            elif isinstance(node,ast.Subscript)and isinstance(node.slice,ast.Slice):self.element(plan,node.value,key)
            elif isinstance(node,ast.Call):
                names=self.builtins(plan,node)
                if names=={'list'}:
                    if node.args:self.element(plan,node.args[0],key)
                elif isinstance(node.func,ast.Attribute)and node.func.attr=='copy':self.element(plan,node.func.value,key)
                else:self.graph.unknown(key)
            else:self.graph.unknown(key)

    def call(self,plan,node,key):
        from .native_types import ListType
        names=self.builtins(plan,node)
        list_receiver=(isinstance(node.func,ast.Attribute)
                       and isinstance(self.kind(plan,node.func.value),ListType))
        if names in({'int'},{'bool'},{'abs'})and len(node.args)==1 and not node.keywords:
            self.graph.add(key,{'int':'Int','bool':'Bool','abs':'Abs'}[next(iter(names))],(self.expression(plan,node.args[0]),))
        elif list_receiver and node.func.attr=='pop':
            self.element(plan,node.func.value,key)
        else:
            targets=self.model.call_edges_by_site.get((plan.index,id(node)),())
            if targets and self.source_call(plan,node):
                for index in targets:
                    callee=self.plans.get(index)
                    if callee is None:self.graph.unknown(key)
                    else:self.graph.copy(key,self.result(callee))
            else:self.graph.unknown(key)
        if list_receiver:
            receiver=node.func.value
            origins=self.origins(plan,receiver)
            if not origins:self.heap_unknown=True;return
            method=node.func.attr
            for origin in origins:
                heap=self.heap(origin)
                if method=='append'and len(node.args)==1:self.graph.copy(heap,self.expression(plan,node.args[0]))
                elif method=='insert'and len(node.args)==2:self.graph.copy(heap,self.expression(plan,node.args[1]))
                elif method=='extend'and len(node.args)==1:self.element(plan,node.args[0],heap)
                elif method=='pop':self.graph.copy(key,heap)
                elif method in{'clear','remove','reverse','sort','copy','count','index'}:pass
                else:self.graph.unknown(heap)
            return
        if self.source_call(plan,node):return
        # Canonical scalar/container builtins have fixed heap behavior; source
        # callbacks are included in the reached graph. Other native adapters
        # lose facts for every passed mutable origin, rather than guessing.
        if names and names<={'input','print','range','len','int','bool','str','float','list','tuple','map','filter','iter','next','zip','enumerate','reversed','any','all','sum','min','max','abs','isinstance','id','repr','format','ascii','set','dict'}:return
        arguments=[*node.args,*(item.value for item in node.keywords)]
        if isinstance(node.func,ast.Attribute):arguments.append(node.func.value)
        arguments.append(node.func)
        for value in arguments:self.poison(plan,value)

    def target(self,plan,node,value):
        from .native_classes import InstanceType
        from .native_module_linking import ClassReferenceType
        if isinstance(node,ast.Name):
            key=self.binding(plan,node)
            if key is not None:
                self.graph.copy(key,value)
                self.cover_binding(plan,node)
        elif isinstance(node,ast.Attribute):
            self.cover_target(plan,node)
            receiver=self.kind(plan,node.value);name=self.model.resolved_name(plan,node)
            if isinstance(receiver,InstanceType):self.graph.copy(self.field(self.model.classes[receiver.name],name),value)
            elif isinstance(receiver,ClassReferenceType):
                owner=next(owner for owner in self.model.classes.values()if owner.index==receiver.definition)
                self.graph.copy(self.member(owner,name),value)
            else:raise Unproved('a scalar/heap write has an unresolved attribute receiver')
        elif isinstance(node,ast.Subscript):
            self.cover_target(plan,node)
            origins=self.origins(plan,node.value)
            if not origins:self.heap_unknown=True;return
            for origin in origins:
                if isinstance(node.slice,ast.Slice):self.graph.unknown(self.heap(origin))
                else:self.graph.copy(self.heap(origin),value)
        elif isinstance(node,(ast.Tuple,ast.List)):
            for child in node.elts:
                unknown=('unpack',plan.index,id(child));self.graph.unknown(unknown)
                self.target(plan,child,unknown)
        elif isinstance(node,ast.Starred):self.target(plan,node.value,value)

    def statement(self,plan,node):
        if self.omitted(plan,node):return
        if isinstance(node,ast.Assign):
            for target in node.targets:self.target(plan,target,self.expression(plan,node.value))
        elif isinstance(node,ast.AnnAssign)and node.value is not None:self.target(plan,node.target,self.expression(plan,node.value))
        elif isinstance(node,ast.AugAssign):
            self.inplace_effect(plan,node)
            key=('augment',plan.index,id(node))
            self.graph.add(key,type(node.op).__name__,(self.expression(plan,node.target),self.expression(plan,node.value)))
            self.target(plan,node.target,key)
        elif isinstance(node,ast.Return):
            if node.value is None:self.graph.unknown(self.result(plan))
            else:self.graph.copy(self.result(plan),self.expression(plan,node.value))
        elif isinstance(node,ast.For):
            key=('loop_item',plan.index,id(node));self.graph.unknown(key)
            self.target(plan,node.target,key)
        elif isinstance(node,ast.With):
            records=self.model.context_managers.sites.get((plan.index,id(node)),())
            for record in records:
                target=record.original.optional_vars
                if target is not None:
                    self.target(plan,target,self.result(record.enter_member.plan))
        elif isinstance(node,ast.Delete):
            for target in node.targets:self.unknown_target(plan,target)

    def inplace_effect(self,plan,node):
        from .native_classes import shape
        from .native_types import ListType,alternatives,TupleType,TupleSequenceType
        self.check_callback_inputs(plan,[node.value])
        cell=self.model.augmented.get((plan.index,id(node)))
        kind=shape(cell)if cell is not None else self.kind(plan,node.target)
        options=alternatives(kind)
        if not options or any(value is None for value in options):
            raise Unproved('an inplace producer has no closed receiver kind')
        if any(isinstance(value,ListType)for value in options):
            # Builtin list inplace operators preserve the runtime object but
            # Model.binary can assign their result a different allocation
            # origin/type epoch. Saved aliases can still name the old epoch.
            # Origins are MAY type facts, not a closed physical-identity
            # graph: lose ALL heap value summaries, including aliases carried
            # through fields, arguments, results and container projections.
            # No count, operator spelling or inferred unchanged element type
            # can make those disconnected origins an alias certificate.
            self.heap_unknown=True
            origins=self.cell_origins(cell)
            if not origins:self.heap_unknown=True
            else:
                for origin in origins:
                    heap=self.heap(origin)
                    if isinstance(node.op,ast.Add):self.element(plan,node.value,heap)
                    elif isinstance(node.op,ast.Mult):pass
                    else:self.graph.unknown(heap)
        elif all(value in{'int','bool','int_bool','float','str','bytes'}
                 or isinstance(value,(TupleType,TupleSequenceType))for value in options):
            # These builtin value operations do not mutate contained elements.
            # Any explicit or implicit source callback still has its original
            # reached body/writes in the closed semantic graph.
            pass
        else:
            raise Unproved('an inplace operator lacks a closed heap mutation transfer')
        self.coverage.record(self.producer(plan,node,'inplace_effect'))

    def unknown_target(self,plan,node):
        from .native_classes import InstanceType
        from .native_module_linking import ClassReferenceType
        if isinstance(node,ast.Name):
            key=self.binding(plan,node)
            if key is not None:self.graph.unknown(key)
            self.cover_binding(plan,node)
        elif isinstance(node,(ast.Tuple,ast.List)):
            for child in node.elts:self.unknown_target(plan,child)
        elif isinstance(node,ast.Starred):self.unknown_target(plan,node.value)
        elif isinstance(node,ast.Attribute):
            self.cover_target(plan,node)
            receiver=self.kind(plan,node.value);name=self.model.resolved_name(plan,node)
            if isinstance(receiver,InstanceType):self.graph.unknown(self.field(self.model.classes[receiver.name],name))
            elif isinstance(receiver,ClassReferenceType):
                owner=next(owner for owner in self.model.classes.values()if owner.index==receiver.definition)
                self.graph.unknown(self.member(owner,name))
            else:raise Unproved('an uncovered attribute producer has no affected owner proof')
            self.heap_unknown=True
        elif isinstance(node,ast.Subscript):
            self.cover_target(plan,node)
            self.poison(plan,node.value)

    def audit_producers(self):
        # Official bindings include stores hidden in expressions, imported
        # aliases, with/except/comprehension targets and definitions. No new
        # producer can silently leave an earlier constant in the value graph.
        for plan in self.plans.values():
            owned={}
            for node in self.values.own_nodes(plan):
                site=self.model.unit.node_ordinals.get(id(node))
                if site is None:
                    if isinstance(node,(ast.stmt,ast.expr,ast.alias,ast.arg,ast.ExceptHandler)):
                        raise Unproved('an executable/binding producer lacks official source metadata')
                    # operator/context/keyword/withitem structural nodes do
                    # not themselves produce values or bind names; their
                    # executable children and actual targets are audited.
                    continue
                owned[site]=node
            source=self.source(plan)
            args=getattr(source.node,'args',None)
            if args is not None:
                for node in[*args.posonlyargs,*args.args,*args.kwonlyargs,
                            *([]if args.vararg is None else[args.vararg]),
                            *([]if args.kwarg is None else[args.kwarg])]:
                    owned[self.model.unit.ordinal(node)]=node
            for site,node in owned.items():
                if self.omitted(plan,node):continue
                for binding in self.bindings_by_node.get(site,()):
                    if binding.role=='load':continue
                    producer=self.producer(plan,node,'binding:'+binding.role,binding.owner)
                    if self.coverage.missing(producer):
                        owner=self.class_scopes.get(binding.owner)
                        key=(self.member(owner,binding.name)if owner is not None
                             else('binding',binding.owner,binding.name))
                        self.graph.unknown(key)
                if isinstance(node,(ast.Attribute,ast.Subscript))and isinstance(node.ctx,(ast.Store,ast.Del)):
                    if self.coverage.missing(self.producer(plan,node,'heap_target')):
                        self.unknown_target(plan,node)
                if isinstance(node,ast.Call)and self.coverage.missing(self.producer(plan,node,'call_effect')):
                    arguments=[*node.args,*(item.value for item in node.keywords),node.func]
                    if isinstance(node.func,ast.Attribute):arguments.append(node.func.value)
                    for value in arguments:self.poison(plan,value)
                if isinstance(node,ast.AugAssign)and self.coverage.missing(self.producer(plan,node,'inplace_effect')):
                    raise Unproved('an original inplace producer has no heap effect coverage')

    def call_inputs(self):
        from .native_classes import InstanceType,shape
        from .native_module_linking import ClassReferenceType
        from .native_bound_methods import BoundMethodTarget
        from .call_semantics import normalize_call,CallBindingError
        for(caller_index,node_id),targets in self.model.call_edges_by_site.items():
            caller=self.plans.get(caller_index);node=self.nodes.get(node_id)
            if caller is None:continue
            for index in targets:
                callee=self.plans.get(index)
                if callee is None or callee.class_body is not None:continue
                source=self.source(callee)
                bindings=None
                if isinstance(node,ast.Call)and self.source_call(caller,node):
                    site=self.model.callable_cells.sites.get((caller_index,node_id))
                    function_kind=self.kind(caller,node.func)
                    implicit=0
                    known=False
                    if isinstance(function_kind,ClassReferenceType):
                        owner=next(owner for owner in self.model.classes.values()if owner.index==function_kind.definition)
                        known=owner.methods.get('__init__')is source;implicit=1
                    if isinstance(node.func,ast.Attribute)and isinstance(self.kind(caller,node.func.value),InstanceType):
                        owner=self.model.classes[self.kind(caller,node.func.value).name]
                        known=owner.methods.get(self.model.resolved_name(caller,node.func))is source;implicit=1
                    if site is not None:
                        for target in site.targets:
                            definition=getattr(target,'definition',target)
                            if self.model.callable_cells.plans.get(definition)is source:
                                known=True;implicit=int(isinstance(target,BoundMethodTarget))
                    if not known and callee.owner is None:
                        from .native_frame_references import call_target
                        known=call_target(self.model,caller,node)is source
                    if known:
                        try:bindings=source.signature.plan(normalize_call(node),implicit_count=implicit,allow_variadic=True)
                        except CallBindingError:pass
                for name,cell in callee.arguments.items():
                    destination=self.parameter(callee,name)
                    self.parameter_inputs.add((callee.index,name))
                    slot=None
                    if bindings is not None:
                        slot=next((item for parameter,item in zip(bindings.parameters,bindings.sources)if parameter==name),None)
                    if slot is not None and slot.kind=='argument':
                        arguments=normalize_call(node)
                        values=[item.expression for item in arguments.positional]+[item.expression for item in arguments.keywords]
                        if slot.index is not None and slot.index<len(values):self.graph.copy(destination,self.expression(caller,values[slot.index]));continue
                    if slot is not None and slot.kind=='default':
                        value=source.defaults.get(name)
                        if isinstance(value,ast.Constant)and type(value.value)in{int,bool}:
                            self.graph.seed(destination,'bool'if type(value.value)is bool else'int',value.value);continue
                    self.graph.unknown(destination)


def prepare(model):model.scalar_heap_constants=Registry(model)


def getter(emitter,owner,index,code):
    registry=getattr(emitter.model,'scalar_heap_constants',None)
    fact=None if registry is None else registry.fields.get((owner.index,index))
    if fact is None:return code
    literal=emitter.literal(fact.low)if fact.kind=='int'else str(fact.low).lower()
    # The real field access is still evaluated first. Optional getters and
    # original receiver/constructor/callback effects keep their error paths.
    return ('{let class_scalar_actual:Result<'+emitter.rust_type(fact.kind)+',String>='+code+';'
            'class_scalar_actual.map(|class_scalar_value|{let _=class_scalar_value;'+literal+'})}')
