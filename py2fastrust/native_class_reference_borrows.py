"""Borrow exact class references used only to load ordinary namespace data.

Source argument capture and class-attribute lookup remain in their original
order. The common physical borrow pass keeps synchronous owned references for
unknown Rust headers, address-taken functions and observable destructors.
"""
import ast


class Registry:
    def __init__(self,model):
        from .native_classes import shape
        from .native_class_calls import synchronous
        from .native_module_linking import ClassReferenceType
        from .native_value_classes import selected
        self.parameters={}
        self.applied={}
        self.reasons={}
        namespace=getattr(model,'class_namespaces',None)
        if model.unit is None or namespace is None:return
        bindings=list(model.iter_bindings())
        nodes={model.unit.ordinal(node):node for node in model.iter_nodes()}
        parents={id(child):node for node in model.iter_nodes()for child in ast.iter_child_nodes(node)}
        owners={owner.index:owner for owner in model.classes.values()}
        for plan in model.plans:
            if not plan.reachable or not synchronous(model,plan):continue
            scope=model.lexical.scope(plan)
            declared={binding.name:binding for binding in bindings
                      if binding.owner==scope and binding.scope==scope and binding.role=='parameter'}
            for position,name in enumerate(plan.runtime_parameters):
                kind=shape(plan.arguments[name])
                if not isinstance(kind,ClassReferenceType):continue
                owner=owners.get(kind.definition)
                if owner is None or not selected(model,owner):continue
                key=plan.index,position
                parameter=declared.get(name)
                stored=model.namespace.local_kind(plan,name)
                if parameter is None or stored is not None and stored!=kind:
                    self.reasons[key]='parameter has no stable official class-reference binding';continue
                uses=[binding for binding in bindings if binding.owner==parameter.owner
                      and binding.name==parameter.name and binding is not parameter]
                allowed=bool(uses)
                for use in uses:
                    node=nodes.get(use.node)
                    parent=parents.get(id(node))
                    if (use.scope!=parameter.owner or use.role!='load'
                            or not isinstance(node,ast.Name)or not isinstance(node.ctx,ast.Load)
                            or model.lexical.field_for(node)is not None or model.namespace.owns(plan,node)
                            or not isinstance(parent,ast.Attribute)or parent.value is not node
                            or not isinstance(parent.ctx,ast.Load)):
                        allowed=False;break
                    member=namespace.members.get((owner.index,model.resolved_name(plan,parent)))
                    if member is None or member.plan is not None or member.descriptor!='function':
                        allowed=False;break
                    cell=model.records.get((plan.index,id(node)))
                    if cell is not None and shape(cell)!=kind:allowed=False;break
                if not allowed:
                    self.reasons[key]='parameter is rebound, captured, forwarded, returned or used beyond ordinary class data lookup';continue
                self.parameters[key]='ClassClassRef'


def prepare(model):model.class_reference_borrows=Registry(model)


def apply(source,model):
    from .native_value_parameter_borrows import apply as borrow_parameters
    return borrow_parameters(source,model,registry_name='class_reference_borrows')
