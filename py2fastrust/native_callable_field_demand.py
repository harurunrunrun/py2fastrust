"""Original-source demand for private callable module/environment captures.

Lookup/definition/receiver/default evaluation is separate from these private
transport fields. Unknown uses retain the complete original payload.
"""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Demand:
    module:bool=True
    environment:bool=True
    reason:str='callable transport has no complete source demand proof'


def children(kind):
    from .native_class_identity_demand import children as nested_children
    return nested_children(kind)


def builtin_names(identities):
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    return {identity.name for identity in identities
            if isinstance(identity,BuiltinIdentity)
            or isinstance(identity,BuiltinRef)and identity.module=='builtins'}


def observes_produced_identity(node,identities):
    # A sentinel iterator compares the callback result with the sentinel.
    # Those produced references need not occur in its explicit arguments.
    return 'iter'in builtin_names(identities)and(len(node.args)!=1 or bool(node.keywords))


class Registry:
    def __init__(self,model):
        self.model=model
        self.demands={}
        self.observed={}
        self.barrier=None
        self.nodes={id(node):node for node in model.iter_nodes()}
        self.parents={id(child):node for node in model.iter_nodes()for child in ast.iter_child_nodes(node)}
        self.plans=tuple(plan for plan in model.plans if plan.reachable)
        try:self.global_proof()
        except Unproved as error:
            self.barrier=str(error)
            return
        self.observe_uses()
        self.refresh_contexts()

    def refresh_contexts(self):
        if self.barrier is not None:return
        model=self.model;provider=model.callable_cells
        from .native_aot_callables import ordered_targets
        targets=ordered_targets(tuple(provider.used)+tuple(provider.bound_methods.used))
        from .native_bound_methods import BoundMethodTarget
        from .native_call_context_effects import summary
        for target in targets:
            number=target.definition if isinstance(target,BoundMethodTarget)else target
            source=provider.plans.get(number)
            if source is None:continue
            effect=summary(model,source)
            reasons=self.observed.get(target,())
            if reasons:
                self.demands[target]=Demand(reason='; '.join(sorted(reasons)))
            else:
                self.demands[target]=Demand(effect.incoming_module,effect.lexical_parent,
                    effect.reason if effect.incoming_module or effect.lexical_parent else'closed call-only source value; no private capture consumer')

    def kind(self,plan,node):
        from .native_classes import shape
        cell=self.model.records.get((plan.index,id(node)))
        return None if cell is None else shape(cell)

    def targets(self,kind,*,roots=False,seen=frozenset()):
        """Separate Python element values from a native iterator's callbacks."""
        from .native_aot_callables import AotFunctionType
        from .native_classes import InstanceType,shape
        if kind is None or kind in seen:return set()
        seen=seen|{kind}
        result=set(kind.targets)if isinstance(kind,AotFunctionType)else set()
        if getattr(kind,'_native_class_iterator',False)and not roots:
            element=getattr(kind.record,'element',None)
            return result if element is None else result|self.targets(shape(element),seen=seen)
        if isinstance(kind,InstanceType):
            if roots:
                owner=self.model.classes.get(kind.name)
                if owner is not None:
                    for field in owner.fields.values():result.update(self.targets(shape(field.cell),roots=True,seen=seen))
            return result
        for child in children(kind):result.update(self.targets(child,roots=roots,seen=seen))
        return result

    def mark(self,targets,reason):
        for target in targets:self.observed.setdefault(target,set()).add(reason)

    def all_kinds(self):
        from .native_classes import shape
        for cell in self.model.records.values():yield shape(cell)
        for _,kind in (*self.model.namespace.fields(),*self.model.namespace.default_fields()):yield kind
        for owner in self.model.classes.values():
            for field in owner.fields.values():yield shape(field.cell)
        for plan in self.plans:
            yield shape(plan.result)
            for cell in plan.arguments.values():yield shape(cell)

    def identities(self,kind,seen=frozenset()):
        if kind is None or kind in seen:return set()
        seen=seen|{kind}
        result=set(getattr(kind,'builtins',()))|set(getattr(kind,'members',()))
        for child in children(kind):result.update(self.identities(child,seen))
        return result

    def call_identities(self,plan,node):
        """Point facts first; the fallback requires official module ownership."""
        from .references import BuiltinIdentity
        from .native_physical_list_builtins import static_builtin
        kind=self.kind(plan,node.func)
        if kind is not None:return self.identities(kind)
        if isinstance(node.func,ast.Name):
            spelling=self.model.display_name(self.model.resolved_name(plan,node.func))
            if static_builtin(self.model,plan,node.func,spelling):return {BuiltinIdentity(spelling)}
        return set()

    def addressable(self,kind,seen=frozenset()):
        from .native_aot_callables import AotFunctionType
        from .native_classes import InstanceType
        from .native_module_linking import ClassReferenceType
        if kind is None:return True
        if kind in seen:return False
        seen=seen|{kind}
        if isinstance(kind,(InstanceType,ClassReferenceType)):return True
        if isinstance(kind,AotFunctionType):return bool(kind.definitions or kind.methods)
        if getattr(kind,'_native_class_iterator',False)or getattr(kind,'_native_class_generator',False):return True
        return any(self.addressable(child,seen)for child in children(kind))

    def global_proof(self):
        from .native_finite_depth_calls import _model_proof,Unproved as GraphUnproved
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        from .native_aot_callables import AotFunctionType
        try:_model_proof(self.model)
        except GraphUnproved as error:raise Unproved(str(error))from None
        identities=set(self.model.callable_cells.builtin_used)|set(self.model.callable_cells.member_used)
        for kind in self.all_kinds():identities.update(self.identities(kind))
        # Intrinsic direct calls can deliberately omit a func-node value
        # record. Include their official canonical identities as well as
        # retained first-class callable kinds before excluding observers.
        for plan in self.plans:
            for node in self.model.value_classes.own_nodes(plan):
                if isinstance(node,ast.Call):identities.update(self.call_identities(plan,node))
        namespace={'getattr','setattr','delattr','vars','globals','locals','dir','eval','exec','compile'}
        for identity in identities:
            if isinstance(identity,BuiltinIdentity)and identity.name in namespace|{'id'}:
                raise Unproved('a namespace/address observer can expose erased capture lifetime')
            if isinstance(identity,BuiltinRef)and(identity.module in {'gc','weakref'}
                    or identity.module=='sys'and identity.name in {'getrefcount','_getframe','_current_frames'}
                    or identity.module=='builtins'and identity.name in namespace|{'id'}):
                raise Unproved('a retained heap/frame/address observer can expose capture lifetime')
        metadata={'__dict__','__globals__','__closure__','__defaults__','__kwdefaults__',
                  '__annotations__','__annotate__','__code__','tb_frame','f_globals','f_locals','gi_frame','cr_frame'}
        for plan in self.plans:
            for node in self.model.value_classes.own_nodes(plan):
                if isinstance(node,ast.Attribute):
                    kind=self.kind(plan,node.value)
                    if isinstance(kind,AotFunctionType)or node.attr in metadata:
                        raise Unproved('function/namespace/frame metadata has an unclosed captured-root escape')
                    if self.targets(kind,roots=True)and not isinstance(self.parents.get(id(node)),ast.Call):
                        # Normal collection method lookup/calls are classified
                        # below. Exposed private iterator/capture attributes are
                        # not inferred from their spelling.
                        if getattr(kind,'_native_class_iterator',False):
                            raise Unproved('a retained iterator exposes its private callback state')
                if isinstance(node,ast.Call):
                    identities=self.call_identities(plan,node)
                    names=builtin_names(identities)
                    if observes_produced_identity(node,identities):
                        # The sentinel iterator compares produced values, not
                        # just its explicit callable/sentinel operands. Its
                        # retained result graph needs a separate protocol.
                        raise Unproved('the callable/sentinel iteration protocol can observe produced identity')
                    if names&{'print','str','repr','format','ascii','hash'}:
                        args=[*node.args,*(keyword.value for keyword in node.keywords)]
                        if any(self.addressable(self.kind(plan,arg.value if isinstance(arg,ast.Starred)else arg))for arg in args):
                            raise Unproved('an address-bearing display/hash consumer can observe earlier capture release')
                if isinstance(node,ast.FormattedValue)and self.addressable(self.kind(plan,node.value)):
                    raise Unproved('formatting can observe capture-dependent allocation lifetime')
                if isinstance(node,ast.Assert)and node.msg is not None and self.addressable(self.kind(plan,node.msg)):
                    raise Unproved('assertion display can observe capture-dependent lifetime')
                if isinstance(node,ast.BinOp)and isinstance(node.op,ast.Mod)and self.kind(plan,node.left)in {'str','bytes'}and self.addressable(self.kind(plan,node.right)):
                    raise Unproved('text formatting can observe capture-dependent lifetime')

    def source_call(self,plan,node):
        site=self.model.callable_cells.sites.get((plan.index,id(node)))
        if site is not None:
            return bool(site.targets or site.errors or site.constructors)and not(site.builtins or site.members or site.exception_constructors)
        linker=getattr(self.model,'module_linker',None)
        if linker is not None and(plan.index,id(node))in linker.class_calls:return True
        # A callback edge alone does not make the original call a source
        # invocation: sorted/map/container protocols also activate source
        # callbacks. Classify their original argument roles separately.
        from .native_frame_references import call_target
        if call_target(self.model,plan,node)is not None:return True
        from .native_classes import InstanceType
        if isinstance(node.func,ast.Attribute):
            receiver=self.kind(plan,node.func.value)
            if isinstance(receiver,InstanceType):
                owner=self.model.classes.get(receiver.name)
                method=None if owner is None else owner.methods.get(self.model.resolved_name(plan,node.func))
                from .native_call_context_effects import source_plan
                plans={candidate.index:candidate for candidate in self.model.plans if candidate.reachable}
                targets=self.model.call_edges_by_site.get((plan.index,id(node)),())
                return method is not None and bool(targets)and all(
                    index in plans and source_plan(plans[index])is source_plan(method)for index in targets)
        return False

    @staticmethod
    def builtin_role(identity,position):
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        if isinstance(identity,BuiltinRef):
            if identity.module=='functools'and identity.name=='reduce':return 'callback'if position==0 else'transport'
            return 'unknown'
        if not isinstance(identity,BuiltinIdentity):return 'unknown'
        if identity.name in {'map','filter'}:return 'callback'if position==0 else'transport'
        if identity.name in {'sorted','min','max'}:return 'callback'if position=='key'else'compare'
        if identity.name in {'list','tuple','iter','reversed','enumerate','zip','next'}:return 'transport'
        if identity.name in {'len','bool','type','callable','isinstance','any','all','sum'}:return 'value_protocol'
        return 'unknown'

    def observe_call(self,plan,node):
        from .native_types import ListType,TupleType,TupleSequenceType
        data=[(index,arg.value if isinstance(arg,ast.Starred)else arg)for index,arg in enumerate(node.args)]
        data.extend((keyword.arg,keyword.value)for keyword in node.keywords)
        if self.source_call(plan,node):return
        identities=self.call_identities(plan,node)
        receiver_kind=self.kind(plan,node.func.value)if isinstance(node.func,ast.Attribute)else None
        sequence=isinstance(receiver_kind,(ListType,TupleType,TupleSequenceType))
        transport=sequence and node.func.attr in {'append','extend','insert','pop','copy','clear','reverse'}
        comparator=sequence and node.func.attr in {'count','index','remove','sort','__contains__','__eq__','__ne__','__hash__'}
        for position,arg in data:
            kind=self.kind(plan,arg)
            exposed=self.targets(kind)
            captured=self.targets(kind,roots=True)
            if not captured:continue
            if transport:continue
            if comparator:
                self.mark(exposed,'a container comparison argument observes callable identity');continue
            roles={self.builtin_role(identity,position)for identity in identities}
            if roles and roles<={'callback','transport','value_protocol'}:continue
            if roles and roles<={'compare'}:
                self.mark(exposed,'a builtin comparison consumer observes callable identity')
                continue
            self.mark(captured,'a callable escapes through an unproved native argument role')
        if isinstance(node.func,ast.Attribute):
            kind=self.kind(plan,node.func.value)
            targets=self.targets(kind,roots=True)
            if not targets:return
            # Exact builtin sequence receivers have sealed transport methods;
            # a source class with the same spelling uses its source call plan.
            if isinstance(kind,(ListType,TupleType,TupleSequenceType)):
                if node.func.attr in {'append','extend','insert','pop','copy','clear','reverse'}:return
                if node.func.attr in {'count','index','remove','sort','__contains__','__eq__','__ne__','__hash__'}:
                    self.mark(targets,'a container member observes callable identity')
                    return
            self.mark(targets,'a native receiver exposes an unproved callable capture')

    def observe_uses(self):
        from .native_classes import shape
        for kind in self.all_kinds():
            if getattr(kind,'_native_class_mapping',False):
                key=getattr(kind.record,'key',None)
                if key is not None:self.mark(self.targets(shape(key)),'a hashed key requires callable identity')
        for plan in self.plans:
            for node in self.model.value_classes.own_nodes(plan):
                if isinstance(node,ast.Call):self.observe_call(plan,node)
                if isinstance(node,ast.Compare):
                    parts=[node.left,*node.comparators]
                    for left,operator,right in zip(parts,node.ops,parts[1:]):
                        self.mark(self.targets(self.kind(plan,left))&self.targets(self.kind(plan,right)),
                                  'a source comparison can observe same-target callable identity')
                if not isinstance(node,ast.expr)or not isinstance(getattr(node,'ctx',ast.Load()),ast.Load):continue
                kind=self.kind(plan,node);targets=self.targets(kind)
                if not targets:continue
                parent=self.parents.get(id(node))
                if isinstance(parent,ast.Call):continue
                if isinstance(parent,(ast.Assign,ast.AnnAssign,ast.NamedExpr,ast.Return,ast.List,ast.Tuple,ast.IfExp,ast.BoolOp,ast.Compare,ast.Starred,ast.keyword,ast.arguments,ast.comprehension,ast.For)):continue
                if isinstance(parent,ast.Subscript)and parent.value is node:continue
                if isinstance(parent,ast.Attribute)and parent.value is node:continue
                if isinstance(parent,ast.Dict):
                    if node in parent.values:continue
                    self.mark(targets,'a dictionary key requires callable identity');continue
                if isinstance(parent,ast.BinOp)and isinstance(parent.op,ast.Mult):
                    from .native_types import ListType,TupleType,TupleSequenceType
                    if isinstance(kind,(ListType,TupleType,TupleSequenceType)):continue
                self.mark(targets,'a callable has an unproved original value consumer')


class Unproved(Exception):pass


def prepare(model):model.callable_field_demand=Registry(model)


def demand(model,target):
    registry=getattr(model,'callable_field_demand',None)
    if registry is None:return Demand()
    if registry.barrier:return Demand(reason=registry.barrier)
    return registry.demands.get(target,Demand())
