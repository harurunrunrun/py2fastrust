"""Physical constant slots require value, initialized-state and observer proofs.

Logical fields and original source expressions remain intact. This pass only
removes proved redundant Copy storage; scalar facts alone never erase a slot.
"""
import ast


class Unproved(Exception):
    pass


class Registry:
    def __init__(self,model):
        self.model=model
        self.fields={}
        self.reasons={}
        self.owners={}
        self.scalars=getattr(model,'scalar_heap_constants',None)
        self.values=getattr(model,'value_classes',None)
        self.packed=getattr(model,'packed_value_fields',None)
        from .native_classes import shape
        for owner in model.classes.values():
            if not owner.used:continue
            try:self.prove(owner)
            except Unproved as error:self.owners[owner.index]=str(error);continue
            for index,field in enumerate(owner.fields.values()):
                key=owner.index,index
                fact=self.scalars.fields.get(key)
                kind=shape(field.cell)
                if(fact is None or not fact.singleton or fact.kind!=kind
                        or kind not in {'int','bool'}):
                    self.reasons[key]='no same-kind scalar singleton across all reached source contexts'
                elif kind=='int'and model.integer not in {'i64','i128'}:
                    self.reasons[key]='reference-backed integers do not have redundant Copy storage'
                else:self.fields[key]=fact

    def canonical(self,plan,node):
        """MAY callable identities, never a builtin inferred from spelling."""
        from .native_classes import shape
        from .native_types import alternatives
        from .native_physical_list_builtins import static_builtin
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        kind=self.scalars.kind(plan,node.func)
        site=self.model.callable_cells.sites.get((plan.index,id(node)))
        if kind is None and site is not None:kind=shape(site.callee)
        identities=set()
        for part in alternatives(kind):
            if isinstance(part,(BuiltinIdentity,BuiltinRef)):identities.add(part)
            identities.update(getattr(part,'targets',()))
        if site is not None:
            identities.update(site.builtins)
            identities.update(site.members)
        if isinstance(node.func,ast.Name)and static_builtin(self.model,plan,node.func,node.func.id):
            identities.add(BuiltinIdentity(node.func.id))
        return identities

    def prove(self,owner):
        from .native_value_classes import selected as value_selected
        from .native_copy_scalar_fields import selected as copy_selected
        from .native_packed_value_fields import selected as packed_selected
        from .native_class_identity_demand import elided as identity_elided
        from .references import BuiltinIdentity
        from .native_module_calls import BuiltinRef
        if self.scalars is None or self.scalars.reason is not None:
            raise Unproved('the closed scalar producer/heap graph is unavailable')
        if not copy_selected(self.model,owner):
            raise Unproved('owner does not have closed Copy scalar fields')
        if not packed_selected(self.model,owner):
            raise Unproved('field presence and read-after-initialization are not independently proved')
        if value_selected(self.model,owner)and not identity_elided(self.model,owner):
            raise Unproved('owner identity/representation/heap observations retain its physical layout')
        if not value_selected(self.model,owner):
            # Packed shared instances retain their Rc identity and all mutable
            # fields. The ordered constructor proof seals field presence; the
            # whole-source MAY value graph, including every aliasing write,
            # separately establishes a redundant constant slot.
            from .native_namespace_read_places import lifetime_closed
            if not lifetime_closed(self.model):
                raise Unproved('shared instance lifetime/observer proof is absent')
        namespace={'getattr','setattr','delattr','vars','locals','globals','eval','exec','compile','type'}
        observers={'id','print','str','repr','format','ascii','hash','sorted','min','max'}
        for plan in self.scalars.plans.values():
            for node in self.values.own_nodes(plan):
                if not isinstance(node,ast.Call)or self.scalars.omitted(plan,node):continue
                identities=self.canonical(plan,node)
                names={identity.name for identity in identities
                       if isinstance(identity,BuiltinIdentity)
                       or isinstance(identity,BuiltinRef)and identity.module=='builtins'}
                if names&namespace:
                    raise Unproved('a canonical namespace/type observer can inspect physical instance state')
                arguments=[*node.args,*(item.value for item in node.keywords)]
                if isinstance(node.func,ast.Attribute):arguments.append(node.func.value)
                kinds=[self.scalars.kind(plan,value.value if isinstance(value,ast.Starred)else value)
                       for value in arguments]
                observed=any(self.values.contains(kind,owner)
                             or self.packed.class_reference(kind,owner)for kind in kinds)
                if not observed:continue
                if names&observers:
                    raise Unproved('a canonical identity/representation/comparison observer receives this owner')
                if any(isinstance(identity,BuiltinRef)and identity.module!='builtins'
                       for identity in identities):
                    raise Unproved('a native module consumer has no physical-layout observation certificate')


def prepare(model):model.constant_field_projection=Registry(model)


def selected(model,owner,index):
    return(owner.index,index)in getattr(getattr(model,'constant_field_projection',None),'fields',())


def literal(model,owner,index):
    registry=getattr(model,'constant_field_projection',None)
    fact=None if registry is None else registry.fields.get((owner.index,index))
    if fact is None:return None
    if fact.kind=='bool':return str(fact.low).lower()
    from .native import _string
    return registry.scalars.graph.policy.rust_literal(fact.low,_string)


def read(model,owner,receiver,index):
    value=literal(model,owner,index)
    if value is None:return None
    # Keep evaluating the actual owner expression. Definite initialization,
    # not its constant value, is what permits dropping the old slot access.
    return '{let _=&('+receiver+');'+value+'}'


def store(model,owner,receiver,index,value):
    if not selected(model,owner,index):return None
    # Existing statement lowering has already captured RHS before target
    # owner. Keep these expressions/coercions too; only the Copy write dies.
    return '{let _=&('+receiver+');let _=('+value+');};'
