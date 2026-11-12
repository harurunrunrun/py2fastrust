"""Read-only scalar-instance formals accept shared or owned concrete data."""
import ast


class Registry:
    def __init__(self,model):
        from .native_classes import InstanceType,shape
        from .native_scalar_constructor_data import selected
        self.model=model
        self.parameters={}
        self.reasons={}
        if model.unit is None or not getattr(getattr(model,'scalar_constructor_data',None),'owners',()):return
        rows=tuple(model.iter_bindings())
        nodes={model.unit.ordinal(node):node for node in model.iter_nodes()}
        parents=model.value_classes.parents
        for plan in model.plans:
            if not plan.reachable:continue
            scope=model.lexical.scope(plan)
            reached=set()
            def visit(node):
                reached.add(id(node))
                if isinstance(node,ast.If):
                    mask=getattr(model,'type_guard_branches',{}).get((plan.index,id(node.test)))
                    if mask is not None and not all(mask):
                        visit(node.test)
                        for child in node.body if mask[0]else node.orelse:visit(child)
                        return
                for child in ast.iter_child_nodes(node):visit(child)
            visit(plan.node)
            for position,name in enumerate(plan.runtime_parameters):
                kind=shape(plan.arguments[name])
                if not isinstance(kind,InstanceType):continue
                owner=model.classes[kind.name]
                if not selected(model,owner):continue
                stored=model.namespace.local_kind(plan,name)
                if stored is not None and stored!=kind:continue
                uses=[row for row in rows if row.owner==scope and row.name==name]
                declaration=[row for row in uses if row.role=='parameter'and row.scope==scope]
                if len(declaration)!=1:continue
                loads=[row for row in uses if row is not declaration[0]]
                valid=bool(loads)
                for row in loads:
                    node=nodes.get(row.node);parent=parents.get(id(node))
                    if node is not None and id(node)not in reached:continue
                    if (row.scope!=scope or row.role!='load'or not isinstance(node,ast.Name)
                            or not isinstance(node.ctx,ast.Load)
                            or model.lexical.field_for(node)is not None or model.namespace.owns(plan,node)):
                        valid=False;break
                    field=(isinstance(parent,ast.Attribute)and parent.value is node
                           and isinstance(parent.ctx,ast.Load)
                           and model.resolved_name(plan,parent)in owner.fields)
                    if not field and not self.type_predicate(plan,parent,node):
                        valid=False;break
                if valid:self.parameters[plan.index,name]=(position,owner.index)

    def kind(self,plan,node):return self.model.value_classes.kind(plan,node)

    def type_predicate(self,plan,node,subject):
        if (not isinstance(node,ast.Call)or len(node.args)!=2 or node.keywords
                or node.args[0]is not subject):return False
        from .native_source_native_effects import _identity,sealed_builtin
        identity=_identity(self,plan,node.func)
        return (getattr(identity,'name',None)=='isinstance'
                and sealed_builtin(self.model,identity,[self.kind(plan,arg)for arg in node.args]))


def prepare(model):model.scalar_data_parameters=Registry(model)


def parameter(model,plan,name):
    return getattr(getattr(model,'scalar_data_parameters',None),'parameters',{}).get((plan.index,name))


def parameter_type(model,plan,name):
    entry=parameter(model,plan,name)
    return None if entry is None else'impl AsRef<ClassData_'+str(entry[1])+'>'


def read(emitter,node):
    if not isinstance(node,ast.Name)or not isinstance(node.ctx,ast.Load):return None
    name=emitter.model.resolved_name(emitter.plan,node)
    entry=parameter(emitter.model,emitter.plan,name)
    if entry is None:return None
    from .native_classes import Expression
    return Expression('class_argument_'+str(entry[0])+'.as_ref()',emitter.kind(node))
