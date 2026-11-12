"""Prove when compiled immutable instances need no private identity token.

Instance identity and class-definition identity are distinct. This certificate
never changes retained class metadata. It only removes private instance IDs
after the original reached source and implicit consumers prove them unobserved.
Unknown capabilities keep the existing identity-bearing value representation.
"""
import ast


class Unproved(Exception):
    pass


def children(kind):
    from .native_types import (ListType, TupleType, TupleSequenceType, DequeType,
                               MaybeType, NullableType, UnionType)
    result=list(getattr(kind,'_native_owned_kinds',()))
    if isinstance(kind,(ListType,TupleSequenceType,DequeType)):
        result.append(kind.element)
    elif isinstance(kind,(MaybeType,NullableType)):
        result.append(kind.value)
    elif isinstance(kind,TupleType):
        result.extend(kind.fields)
    elif isinstance(kind,UnionType):
        result.extend(kind.alternatives)
    return result


def nested(kind,seen=frozenset()):
    if id(kind)in seen:return
    yield kind
    seen=seen|{id(kind)}
    for child in children(kind):yield from nested(child,seen)


class Registry:
    def __init__(self,model):
        self.model=model
        self.values=getattr(model,'value_classes',None)
        self.elided=set()
        self.reasons={}
        self.closed_source=None
        candidates=set(getattr(self.values,'selected',()))
        if not candidates:return
        try:self.global_proof()
        except Unproved as error:
            self.reasons.update((index,str(error))for index in candidates)
            return
        for owner in model.classes.values():
            if owner.index not in candidates:continue
            try:self.prove(owner)
            except Unproved as error:self.reasons[owner.index]=str(error)
            else:self.elided.add(owner.index)
        if self.elided!=candidates:
            # A retained value owner may consume the same logical sequence.
            # Do not renumber that owner's tokens by deleting other sites.
            for index in self.elided:
                self.reasons[index]='another value owner retains the shared identity sequence'
            self.elided.clear()

    def all_kinds(self):
        from .native_classes import shape
        for cell in self.model.records.values():yield shape(cell)
        for plan in self.values.plans.values():
            yield shape(plan.result)
            for cell in plan.arguments.values():yield shape(cell)
        for _,kind in self.model.namespace.fields():yield kind
        for _,kind in self.model.namespace.default_fields():yield kind

    def global_proof(self):
        if self.model.unit is None:
            raise Unproved('no official original source/binding graph')
        # Reuse the semantic portion only: no physical renderer is inspected or
        # patched. This proves finite reached source/import/callback targets,
        # and rejects opaque namespaces, generators, cycles and finalizers.
        from .native_finite_depth_calls import _model_proof, Unproved as CallsUnproved
        try:self.closed_source=_model_proof(self.model)
        except CallsUnproved as error:raise Unproved(str(error))from None
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        identities=set()
        for kind in self.all_kinds():
            for part in nested(kind):
                identities.update(getattr(part,'builtins',()))
                identities.update(getattr(part,'members',()))
        identities.update(self.model.callable_cells.builtin_used)
        identities.update(self.model.callable_cells.member_used)
        for identity in identities:
            if(isinstance(identity,BuiltinIdentity)and identity.name=='id'
                    or isinstance(identity,BuiltinRef)and identity.module=='builtins'and identity.name=='id'):
                # Every unboxed class currently shares one TLS ID sequence.
                # Retain all sites even for IDs observed on another owner, or
                # for a saved observer which is not called in this execution.
                raise Unproved('a retained canonical id observer preserves the whole shared identity sequence')
            if isinstance(identity,BuiltinRef)and(identity.module in {'gc','weakref'}
                    or identity.module=='sys'and identity.name in {'getrefcount','_getframe','_current_frames'}):
                raise Unproved('heap/frame/lifetime observation is retained')
        self.nodes={id(node):node for node in self.model.iter_nodes()}
        for plan in self.values.plans.values():
            for node in self.values.own_nodes(plan):
                if not isinstance(node,ast.Call):continue
                if 'id'in self.values.builtin(plan,node):
                    raise Unproved('a canonical id invocation preserves the whole shared identity sequence')
                if((plan.index,id(node))not in self.model.records
                        and not self.omitted_statement(plan,node)):
                    raise Unproved('an original reached call lacks solved expression facts')

    def omitted_statement(self,plan,node):
        # Missing expression records alone never establish nonexecution. The
        # exact statement filter used by Emitter.statements must independently
        # omit the enclosing original statement. A call in an executed default,
        # decorator, lambda or comprehension cannot be discarded by this test.
        reached=getattr(self.model,'reached_statements',None)
        if reached is None:return False
        while node is not None and not isinstance(node,ast.stmt):
            node=self.values.parents.get(id(node))
        return node is not None and(plan.index,id(node))not in reached

    def contains(self,kind,owner):
        return self.values.contains(kind,owner)

    def kind(self,plan,node):return self.values.kind(plan,node)

    def prove(self,owner):
        from .native_classes import InstanceType
        from .native_types import ListType,TupleType,TupleSequenceType
        from .native_bound_methods import BoundMethodTarget,BoundMethods
        # The callable runtime can emit receiver equality independently of an
        # explicit source comparison. Retaining its payload retains IDs too.
        for target in self.model.callable_cells.bound_methods.used:
            if(isinstance(target,BoundMethodTarget)
                    and isinstance(BoundMethods.receiver_kind(target),InstanceType)
                    and target.owner==self.model.class_key(owner)):
                raise Unproved('a retained instance-bound method needs receiver identity')
        observers={'print','str','repr','format','ascii','hash','sorted','min','max'}
        namespace={'getattr','setattr','delattr','vars','locals','globals','eval','exec','compile'}
        containers={'list','tuple','iter','reversed','enumerate','zip','map','filter','next','any','all','len','bool','isinstance'}
        # An admitted class is already a closed immutable Copy-field value.
        # Recheck source observations separately rather than inferring demand
        # from generated Rust field reads or a lexical allocation site.
        for plan in self.values.plans.values():
            for node in self.values.own_nodes(plan):
                if isinstance(node,ast.Call):
                    names=self.values.builtin(plan,node)
                    if names&namespace:raise Unproved('a namespace or dynamic attribute observer is reached')
                    args=[*node.args,*(item.value for item in node.keywords)]
                    kinds=[self.values.argument_kind(plan,arg)for arg in args]
                    if isinstance(node.func,ast.Attribute):kinds.append(self.kind(plan,node.func.value))
                    observed=any(self.contains(kind,owner)for kind in kinds)
                    if not observed:continue
                    if names&observers:
                        raise Unproved('an identity/representation/hash/comparison builtin consumes the instance')
                    if any(self.values.observer_names(kind)for kind in kinds):
                        raise Unproved('a callback can observe contained instance identity or representation')
                    if names and not names<=containers:
                        raise Unproved('a builtin instance consumer has no identity-free protocol certificate')
                    if isinstance(node.func,ast.Attribute):
                        receiver=self.kind(plan,node.func.value)
                        if type(receiver)in{ListType,TupleType,TupleSequenceType}and node.func.attr in{
                                'count','index','remove','sort','__contains__','__eq__','__ne__','__hash__'}:
                            raise Unproved('a container member has an implicit element identity protocol')
                if isinstance(node,ast.Compare):
                    operands=[node.left,*node.comparators]
                    for left,operator,right in zip(operands,node.ops,operands[1:]):
                        a,b=self.kind(plan,left),self.kind(plan,right)
                        if 'none'in(a,b):continue
                        from .native_class_mappings import MappingType
                        from .native_source_native_effects import comparison_closed
                        if (isinstance(operator,(ast.In,ast.NotIn))
                                and isinstance(b,MappingType)
                                and comparison_closed(a,operator,b)):
                            continue  # Membership never compares stored values.
                        if self.contains(a,owner)or self.contains(b,owner):
                            raise Unproved('instance/container comparison can consume object identity')
                if isinstance(node,ast.Assert)and node.msg is not None and self.contains(self.kind(plan,node.msg),owner):
                    raise Unproved('an assertion message can display the instance')
                if isinstance(node,ast.FormattedValue)and self.contains(self.kind(plan,node.value),owner):
                    raise Unproved('formatting can display the instance')
                if(isinstance(node,ast.BinOp)and isinstance(node.op,ast.Mod)
                        and self.kind(plan,node.left)in{'str','bytes'}
                        and self.contains(self.kind(plan,node.right),owner)):
                    raise Unproved('text formatting can display the instance')
                if isinstance(node,ast.Attribute)and self.contains(self.kind(plan,node.value),owner):
                    if node.attr in{'__dict__','__class__','__repr__','__str__','__hash__','__eq__','__ne__','__reduce__','__reduce_ex__'}:
                        raise Unproved('an instance protocol is explicitly exposed')


def prepare(model):model.class_identity_demand=Registry(model)


def elided(model,owner):
    return owner.index in getattr(getattr(model,'class_identity_demand',None),'elided',())


def token(model,owner):
    from .native_value_classes import selected
    return selected(model,owner)and not elided(model,owner)


def runtime_needed(model):
    return any(token(model,owner)for owner in model.classes.values()if owner.used)
