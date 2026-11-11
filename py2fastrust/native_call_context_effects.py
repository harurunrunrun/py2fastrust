"""Original-source certificates for independent native invocation contexts.

Callable payloads retain their actual defining module/environment and identity.
Only the invocation's unused module view and lexical-parent argument disappear.
Unknown source effects and binding/default consumers retain the existing ABI.
"""
import ast
from dataclasses import dataclass


class Unproved(Exception):
    pass


def source_plan(plan):
    """A native specialization has the original callable's context contract."""
    seen=set()
    while getattr(plan,'specialization_source',None)is not None:
        if id(plan)in seen:return None
        seen.add(id(plan));plan=plan.specialization_source
    return plan


@dataclass(frozen=True)
class Summary:
    incoming_module:bool=True
    lexical_parent:bool=True
    reason:str='context effects are not certified'


class Registry:
    def __init__(self,model):
        self.model=model;self.summaries={};self.closed_source={}
        from .native_finite_depth_calls import _model_proof,Unproved as GraphUnproved
        try:
            self.closed_source=_model_proof(model)
        except (Unproved,GraphUnproved)as error:
            self.reason=str(error);return
        from .native_classes import shape
        from .native_module_calls import BuiltinRef
        from .native_single_execution_metadata import _identities
        identities=set(model.callable_cells.builtin_used)|set(model.callable_cells.member_used)
        for cell in model.records.values():identities.update(_identities(shape(cell)))
        if any(isinstance(identity,BuiltinRef)and(identity.module in {'gc','weakref'}
                or identity.module=='sys'and identity.name in {'getrefcount','_getframe','_current_frames'})
                for identity in identities):
            self.reason='a frame/reference observer requires actual invocation capture ownership'
            return
        self.bindings={binding.node:binding for binding in model.iter_bindings()}
        self.reason='closed source graph'
        for candidate in model.plans:
            plan=source_plan(candidate)
            if plan is None or plan.index in self.summaries:continue
            try:parent=self.prove(plan)
            except Unproved as error:self.summaries[plan.index]=Summary(reason=str(error))
            else:self.summaries[plan.index]=Summary(False,parent,'original parameter/local computation with actual receiver contexts and retained scalar lexical reads')

    def prove(self,plan):
        from .native_classes import shape,InstanceType
        from .native_class_calls import synchronous
        from .native_types import ListType,TupleType,TupleSequenceType
        from .native_function_instances import instanced
        model=self.model
        if not plan.reachable or model.is_module_plan(plan)or not isinstance(plan.node,ast.FunctionDef):
            raise Unproved('not a reached original ordinary function body')
        if not synchronous(model,plan):raise Unproved('suspended or recursive source frame')
        if plan.node.type_params or plan.node.decorator_list and not self.canonical_classmethod(plan):
            raise Unproved('decorated or parameterized definition metadata is retained')
        if set(plan.defaults)-set(plan.default_literals):
            raise Unproved('binding defaults read the actual module/environment instance')
        from .native_global_callable_payload import metadata_observed
        if model.callable_cells.definition(plan)in metadata_observed(model):
            raise Unproved('function metadata is observed through an original attribute')
        if instanced(model.lexical,plan):raise Unproved('repeated function instance data is retained')
        if model.lexical.scope(plan)in model.lexical.environments:
            raise Unproved('the body creates an environment with an enclosing-parent link')
        if plan.signature.variadic_positional or plan.signature.variadic_keyword:
            raise Unproved('variadic binding context is retained')
        scope=model.lexical.scope(plan)
        parent=False
        called_attributes={id(node.func)for node in model.value_classes.own_nodes(plan)
                           if isinstance(node,ast.Call)and isinstance(node.func,ast.Attribute)}
        allowed=(ast.Return,ast.Assign,ast.AnnAssign,ast.If,ast.For,ast.While,
                 ast.Break,ast.Continue,ast.Pass,ast.Expr,ast.Name,ast.Constant,ast.Tuple,ast.Call,ast.keyword,
                 ast.List,ast.Subscript,ast.Slice,ast.Attribute,ast.BinOp,ast.UnaryOp,
                 ast.BoolOp,ast.Compare,ast.IfExp,ast.Load,ast.Store,ast.operator,
                 ast.unaryop,ast.boolop,ast.cmpop)
        for node in model.value_classes.own_nodes(plan):
            if not isinstance(node,allowed):
                raise Unproved('source operation requires an unproved incoming context: '+type(node).__name__)
            if isinstance(node,ast.Name):
                ordinal=model.unit.node_ordinals.get(id(node))
                binding=self.bindings.get(ordinal)
                if binding is None:raise Unproved('a name has no official binding owner')
                lexical=model.lexical.field_for(node)
                if binding.owner!=scope or binding.scope!=scope:
                    if (binding.scope!=scope or not isinstance(node.ctx,ast.Load)or lexical is None
                            or self.kind(plan,node)not in {'int','bool','int_bool','float','str','bytes','none'}):
                        raise Unproved('a name reads/writes an unproved module or lexical scope')
                    parent=True
                elif lexical is not None:
                    raise Unproved('a local name accesses a captured environment slot')
                if model.namespace.owns(plan,node):
                    raise Unproved('a name accesses a captured namespace/environment slot')
                if isinstance(node.ctx,ast.Load)and(plan.index,id(node))not in model.records:
                    raise Unproved('a source name lacks solved point facts')
            if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
                targets=node.targets if isinstance(node,ast.Assign)else[node.target]
                def local_target(target):
                    return (isinstance(target,ast.Name)or isinstance(target,(ast.Tuple,ast.List))and all(local_target(child)for child in target.elts)
                            or isinstance(target,ast.Subscript)and not isinstance(target.slice,ast.Slice)
                            and isinstance(self.kind(plan,target.value),ListType))
                if not all(local_target(target)for target in targets):
                    raise Unproved('mutation or protocol stores require the ordinary context')
                value=node.value
                if any(isinstance(target,(ast.Tuple,ast.List))and not self.unpack_builtin(target,self.kind(plan,value))for target in targets):
                    raise Unproved('unpacking may invoke an unproved iterable protocol')
            if isinstance(node,ast.Attribute):
                cell=model.records.get((plan.index,id(node.value)))
                kind=None if cell is None else shape(cell)
                from .native_module_linking import ClassReferenceType
                if isinstance(kind,ClassReferenceType):
                    if not self.class_parameter_attribute(plan,node,kind):
                        raise Unproved('class attribute lookup has no exact plain data-member receiver capability')
                    continue
                owner=model.classes.get(kind.name)if isinstance(kind,InstanceType)else None
                method=(None if owner is None else owner.methods.get(model.resolved_name(plan,node)))
                direct_method=(id(node)in called_attributes and method is not None and not method.node.decorator_list)
                if (owner is None or model.resolved_name(plan,node)not in owner.fields and not direct_method
                        or not isinstance(node.ctx,ast.Load)or owner.node.bases or owner.node.keywords or owner.node.decorator_list
                        or any(name in owner.methods for name in ('__getattribute__','__getattr__'))):
                    raise Unproved('attribute lookup has no plain parameter-field capability')
                namespace=getattr(model,'class_namespaces',None)
                member=None if namespace is None else namespace.members.get((owner.index,model.resolved_name(plan,node)))
                if direct_method and member is not None and (member.plan is not method or member.descriptor!='function'):
                    raise Unproved('a method lookup has an unproved descriptor binding')
                if not direct_method and namespace is not None and(owner.index,model.resolved_name(plan,node))in namespace.members:
                    raise Unproved('a descriptor/class namespace field is retained')
            if isinstance(node,ast.Call):
                # Source callable payloads and plain instance methods acquire
                # the callee's actual module/environment in the existing binder.
                # No caller module is needed to invoke those captured values.
                from .native_aot_callables import AotFunctionType
                callee=self.kind(plan,node.func)
                captured=(isinstance(callee,AotFunctionType)and bool(callee.definitions)
                          and not(callee.builtins or callee.members or callee.methods))
                method=False
                if isinstance(node.func,ast.Attribute):
                    receiver=self.kind(plan,node.func.value)
                    owner=model.classes.get(receiver.name)if isinstance(receiver,InstanceType)else None
                    target=None if owner is None else owner.methods.get(model.resolved_name(plan,node.func))
                    method=(target is not None and not target.node.decorator_list
                            and not(owner.node.bases or owner.node.keywords or owner.node.decorator_list)
                            and not any(name in owner.methods for name in ('__getattribute__','__getattr__')))
                if not(captured or method):
                    raise Unproved('a call has no actual source callable or plain receiver context')
            if isinstance(node,ast.Subscript):
                cell=model.records.get((plan.index,id(node.value)))
                kind=None if cell is None else shape(cell)
                if not isinstance(kind,(ListType,TupleType,TupleSequenceType))and kind not in {'str','bytes'}:
                    raise Unproved('subscription requires an unproved source protocol')
                indices=(node.slice.lower,node.slice.upper,node.slice.step)if isinstance(node.slice,ast.Slice)else(node.slice,)
                if any(index is not None and self.kind(plan,index)not in {'int','bool','int_bool','none'}for index in indices):
                    raise Unproved('subscription needs an unproved index conversion')
            if isinstance(node,ast.For):
                kind=self.kind(plan,node.iter)
                if not self.iterable_builtin(kind)or not self.unpack_builtin(node.target,self.item_kind(kind)):
                    raise Unproved('iteration/target binding may invoke an unproved source protocol')
            truths=([node.test]if isinstance(node,(ast.If,ast.While,ast.IfExp))else
                    node.values if isinstance(node,ast.BoolOp)else
                    [node.operand]if isinstance(node,ast.UnaryOp)and isinstance(node.op,ast.Not)else[])
            if any(not self.truth_builtin(self.kind(plan,value))for value in truths):
                raise Unproved('truth conversion may invoke a source __bool__/__len__ protocol')
            if isinstance(node,ast.Compare)and len(node.ops)>1 and not self.truth_builtin(self.kind(plan,node)):
                raise Unproved('a chained comparison can truth-test an unproved protocol result')
            if isinstance(node,(ast.BinOp,ast.UnaryOp,ast.Compare)):
                from .native_callback_effects import may_call
                receiver=self.receiver_operators(plan,node)
                if may_call(model,plan,node)and not receiver:
                    raise Unproved('an implicit callback has no independent receiver context')
                operands=([node.left,*node.comparators]if isinstance(node,ast.Compare)else
                          [node.left,node.right]if isinstance(node,ast.BinOp)else[node.operand])
                identity=isinstance(node,ast.Compare)and all(isinstance(op,(ast.Is,ast.IsNot))for op in node.ops)
                if not receiver and not identity and not all(self.data_builtin(self.kind(plan,value))for value in operands):
                    raise Unproved('an operator has an unproved implicit value protocol')

        return parent

    def canonical_classmethod(self,plan):
        """A validated original descriptor changes binding, not body globals."""
        from .native_aot_callables import AotFunctionType
        from .native_classes import shape
        from .references import BuiltinIdentity
        namespace=getattr(self.model,'class_namespaces',None)
        if namespace is None or not getattr(self.model,'final',False):return False
        members=[member for member in namespace.members.values()
                 if member.plan is not None and source_plan(member.plan)is plan]
        if len(members)!=1 or members[0].descriptor!='classmethod':return False
        owner=members[0].owner
        if (owner.node.bases or owner.node.keywords or owner.node.decorator_list
                or owner.node.type_params or owner.body_plan is None
                or len(plan.node.decorator_list)!=1):return False
        # Descriptor registration starts provisionally. Require the actual
        # definition-time solved value as well as that registered binding.
        value=self.model.records.get((owner.body_plan.index,id(plan.node.decorator_list[0])))
        kind=None if value is None else shape(value)
        return isinstance(kind,AotFunctionType)and kind.targets==(BuiltinIdentity('classmethod'),)

    def class_parameter_attribute(self,plan,node,kind):
        """The unchanged getter uses the actual parameter's module, not Scope."""
        if not isinstance(node.ctx,ast.Load):return False
        namespace=getattr(self.model,'class_namespaces',None)
        if namespace is None:return False
        owner=namespace.owners.get(kind.definition)
        if (owner is None or owner.node.bases or owner.node.keywords
                or owner.node.decorator_list or owner.node.type_params):return False
        records=namespace.attribute_reads.get((plan.index,id(node)))
        if records is None or len(records)!=1:return False
        member=records[0]
        if (member.owner is not owner or member.plan is not None
                or member.function_cell is not None
                or member.name!=self.model.resolved_name(plan,node)):return False
        stored=dict(self.model.namespace.fields()).get(member.key)
        # A plain builtin data payload cannot be a custom descriptor or hide
        # an implicit source callback. Presence, current value and index errors
        # remain in the original runtime getter; constness is not required.
        return self.data_builtin(stored)and self.data_builtin(self.kind(plan,node))

    def kind(self,plan,node):
        from .native_classes import shape
        cell=self.model.records.get((plan.index,id(node)))
        return None if cell is None else shape(cell)

    @staticmethod
    def truth_builtin(kind):
        from .native_types import ListType,TupleType,TupleSequenceType,UnionType,NullableType,alternatives
        if isinstance(kind,(UnionType,NullableType)):return all(Registry.truth_builtin(part)for part in alternatives(kind))
        return kind in {'int','bool','int_bool','float','str','bytes','none'}or isinstance(kind,(ListType,TupleType,TupleSequenceType))

    @staticmethod
    def data_builtin(kind):
        from .native_types import ListType,TupleType,TupleSequenceType,UnionType,NullableType,alternatives
        if isinstance(kind,(UnionType,NullableType)):return all(Registry.data_builtin(part)for part in alternatives(kind))
        if isinstance(kind,(ListType,TupleSequenceType)):return Registry.data_builtin(kind.element)
        if isinstance(kind,TupleType):return all(Registry.data_builtin(field)for field in kind.fields)
        return kind in {'int','bool','int_bool','float','str','bytes','none'}

    @staticmethod
    def iterable_builtin(kind):
        from .native_types import ListType,TupleType,TupleSequenceType
        return isinstance(kind,(ListType,TupleType,TupleSequenceType))or kind in {'str','bytes'}

    @staticmethod
    def item_kind(kind):
        from .native_types import ListType,TupleType,TupleSequenceType,union_type
        if isinstance(kind,(ListType,TupleSequenceType)):return kind.element
        if isinstance(kind,TupleType):return union_type(*kind.fields)
        return 'str'if kind=='str'else'int'if kind=='bytes'else None

    @staticmethod
    def unpack_builtin(target,kind):
        from .native_types import ListType,TupleType,TupleSequenceType,UnionType,NullableType,alternatives
        if isinstance(target,ast.Name):return True
        if not isinstance(target,(ast.Tuple,ast.List)):return False
        if isinstance(kind,(UnionType,NullableType)):return all(Registry.unpack_builtin(target,part)for part in alternatives(kind))
        if isinstance(kind,TupleType):
            return len(kind.fields)!=len(target.elts)or all(Registry.unpack_builtin(child,field)for child,field in zip(target.elts,kind.fields))
        if not Registry.iterable_builtin(kind):return False
        return all(Registry.unpack_builtin(child,Registry.item_kind(kind))for child in target.elts)

    def receiver_operators(self,plan,node):
        """Every retained numeric phase acquires its actual receiver's class."""
        operators=self.model.operators;found=False
        for sites in (operators.sites,operators.unary_sites,operators.comparison_sites):
            for key,site in sites.items():
                if key[:2]!=(plan.index,id(node)):continue
                for branch in site.branches.values():
                    if not branch.complete:return False
                    for phase in branch.phases:
                        if phase.member.descriptor!='function':return False
                        callback=phase.site
                        if phase.negate:
                            from .native_classes import shape
                            if not self.truth_builtin(shape(callback.result)):return False
                        targets=set(callback.targets)|set(callback.errors)
                        if (not targets or any(not isinstance(target,int)or target not in self.model.callable_cells.plans for target in targets)
                                or callback.builtins or callback.members or callback.constructors or callback.exception_constructors):return False
                        found=True
        return found


def prepare(model):
    model.call_context_effects=Registry(model)


def summary(model,plan):
    plan=source_plan(plan)
    registry=getattr(model,'call_context_effects',None)
    return Summary()if registry is None or plan is None else registry.summaries.get(plan.index,Summary())


def incoming_module(model,plan):return summary(model,plan).incoming_module


def unused_parent(model,plan):return not summary(model,plan).lexical_parent


def small_entry(model,plan):
    """Expose short, closed source bodies to Rust without flattening loops."""
    if incoming_module(model,plan):return False
    from .native_class_calls import synchronous
    if not synchronous(model,plan):return False
    nodes=list(model.value_classes.own_nodes(plan))
    return (len(nodes)<=96 and not any(isinstance(node,(ast.For,ast.While,ast.Call))for node in nodes))


def borrowed_parent(model,plan):
    """A synchronous closed leaf cannot retain the invocation's parent handle."""
    return summary(model,plan).lexical_parent and small_entry(model,plan)


def lexical_argument(model,plan,environment):
    if unused_parent(model,plan):return ''
    return ',&('+environment+')'if borrowed_parent(model,plan)else ','+environment+'.clone()'
