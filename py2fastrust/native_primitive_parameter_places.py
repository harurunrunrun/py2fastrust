"""Readonly bindings load from their existing owned native argument place."""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class ArgumentPlace:
    name:object
    scope:int
    kind:object
    index:int

    @property
    def code(self):return 'class_argument_'+str(self.index)


# Preserve the historical primitive-place descriptor API.
Parameter=ArgumentPlace


def readonly_binding(bindings,scope,name):
    """Audit every official producer, including non-Name exception/import rows."""
    rows=[row for row in bindings if row.owner==scope and row.name==name]
    return sum(row.role=='parameter'for row in rows)==1 and all(row.role in {'parameter','load'}for row in rows)


def readonly_parameter(unit,bindings,scope,name):
    # The official symbol table is an independent producer seal. For example,
    # a mapping-pattern **rest binding is a string field rather than ast.Name;
    # even an incomplete per-node binding inventory must fail closed for it.
    symbol=next((symbol for symbol in unit.scopes[scope].symbols if symbol.name==name),None)
    return(symbol is not None and symbol.has('parameter')
           and not any(symbol.has(flag)for flag in ('assigned','imported','free','nonlocal','declared_global'))
           and readonly_binding(bindings,scope,name))


def copy_kind(model,kind):
    return kind in {'bool','float','none'}or kind=='int'and model.integer in {'i64','i128'}



def owned_load(model,kind,seen=frozenset()):
    """Closed native Clone payloads whose destruction cannot call Python.

    This describes the carrier, not source binding or value immutability.
    Mutable builtin lists are allowed when all retained payloads are closed.
    """
    from .native_types import TupleType,TupleSequenceType,ListType,SharedListType,NullableType,UnionType
    if kind in seen:return False
    if kind in {'int','bool','int_bool','float','none','str','bytes','range'}:return True
    seen=seen|{kind}
    if type(kind)is TupleType:return all(owned_load(model,child,seen)for child in kind.fields)
    if type(kind)in {TupleSequenceType,ListType,SharedListType}:return owned_load(model,kind.element,seen)
    if type(kind)is NullableType:return owned_load(model,kind.value,seen)
    if type(kind)is UnionType:return bool(kind.alternatives)and all(owned_load(model,child,seen)for child in kind.alternatives)
    from .native_classes import InstanceType
    if type(kind)is InstanceType:
        from .native_value_classes import selected
        owner=getattr(model,'classes',{}).get(kind.name)
        return owner is not None and selected(model,owner)
    return False


def owned_lifetime(model):
    """Changing an argument root's Rust storage cannot expose a drop order."""
    return not getattr(model,'gc_classes',())and not any(
        owner.used and '__del__'in owner.methods for owner in model.classes.values())


def borrowed_parameter(model,plan,index,name,kind):
    from .native_value_classes import borrowed_self
    from .native_owned_object_places import receiver
    if borrowed_self(model,plan,name,kind)or receiver(model,plan,name):return True
    for attribute in ('value_parameter_borrows','class_reference_borrows'):
        if (plan.index,index)in getattr(getattr(model,attribute,None),'parameters',{}):return True
    # Class references can have a private borrowed formal even when the
    # prospective pass later declines. Keep their original storage protocol.
    from .native_module_linking import ClassReferenceType
    return isinstance(kind,ClassReferenceType)


def observers(model):
    from .native_class_identity_demand import children
    from .native_classes import shape
    from .native_module_calls import BuiltinRef
    from .references import BuiltinIdentity
    from .native_physical_list_builtins import static_builtin
    prohibited={'locals','vars','dir','globals','eval','exec','compile','getattr','setattr','delattr'}
    identities=set(model.callable_cells.builtin_used)|set(model.callable_cells.member_used)
    seen=set()
    def visit(kind):
        if kind is None or kind in seen:return
        seen.add(kind);identities.update(getattr(kind,'builtins',()));identities.update(getattr(kind,'members',()))
        for child in children(kind):visit(child)
    for cell in model.records.values():visit(shape(cell))
    for _,kind in (*model.namespace.fields(),*model.namespace.default_fields()):visit(kind)
    for plan in model.plans:
        if not plan.reachable:continue
        for node in model.value_classes.own_nodes(plan):
            if isinstance(node,ast.Attribute)and node.attr in {'f_locals','f_globals','f_back','tb_frame','gi_frame','cr_frame'}:
                return True
            if isinstance(node,ast.Call)and isinstance(node.func,ast.Name):
                spelling=model.display_name(model.resolved_name(plan,node.func))
                if spelling in prohibited and static_builtin(model,plan,node.func,spelling):return True
    return any(isinstance(identity,BuiltinIdentity)and identity.name in prohibited
               or isinstance(identity,BuiltinRef)and(identity.module=='builtins'and identity.name in prohibited
                   or identity.module=='sys'and identity.name in {'_getframe','_current_frames','settrace','setprofile'})
               for identity in identities)


def prepare(emitter):
    emitter.readonly_owned_parameters={}
    model=emitter.model;plan=emitter.plan;unit=model.unit
    if unit is None or not plan.reachable or not isinstance(plan.node,(ast.FunctionDef,ast.Lambda)):
        return {}
    if getattr(plan.node,'type_params',()):return {}
    if getattr(model,'value_classes',None)is None or not hasattr(model,'synchronous_calls'):return {}
    from .native_class_calls import synchronous
    if not synchronous(model,plan):return {}
    if getattr(model.namespace,'globals_observed',False):return {}
    marker=getattr(model,'primitive_parameter_observers',None)
    if marker is None:marker=observers(model);model.primitive_parameter_observers=marker
    if marker:return {}
    from .native_frame_specialization import source_plan
    source=source_plan(plan)
    if source is None:return {}
    scope=model.lexical.scope(source)
    if unit.scopes[scope].kind not in {'function','lambda'}:return {}
    from .native_classes import shape
    nodes=tuple(model.value_classes.own_nodes(plan))
    if any(isinstance(node,(ast.GeneratorExp,ast.Yield,ast.YieldFrom))for node in nodes):return {}
    rows=tuple(model.iter_bindings());selected={}
    captures=model.lexical.environments.get(scope)
    from .native_value_classes import borrowed_self
    for index,name in enumerate(plan.runtime_parameters):
        kind=shape(plan.arguments[name])
        copied=copy_kind(model,kind)
        if not copied and(not owned_load(model,kind)or not owned_lifetime(model)):continue
        if not readonly_parameter(unit,rows,scope,name):continue
        if borrowed_parameter(model,plan,index,name,kind):continue
        if not copied and not any(row.owner==scope and row.name==name and row.role=='load'for row in rows):continue
        if captures is not None and name in captures.fields:continue
        if model.namespace.local_kind(plan,name)is not None:continue
        good=True
        for node in nodes:
            if not isinstance(node,ast.Name):continue
            binding=model.lexical.binding(node)
            if binding is None:
                if model.resolved_name(plan,node)==name:good=False;break
                continue
            if binding.owner!=scope or binding.name!=name:continue
            if(model.namespace.owns(plan,node)or model.lexical.field_for(node)is not None
                    or model.lexical.execution_scope(binding.scope)!=scope):
                good=False;break
            if isinstance(node.ctx,ast.Load):
                cell=model.records.get((plan.index,id(node)))
                if cell is None or shape(cell)!=kind:good=False;break
        if good:selected[name]=Parameter(name,scope,kind,index)
    emitter.readonly_owned_parameters={name:value for name,value in selected.items()if not copy_kind(model,value.kind)}
    return {name:value for name,value in selected.items()if copy_kind(model,value.kind)}


def lookup(emitter,name):
    return (getattr(emitter,'primitive_parameters',{}).get(name)
            or getattr(emitter,'readonly_owned_parameters',{}).get(name))


def read(emitter,node):
    if not isinstance(node,ast.Name)or not isinstance(node.ctx,ast.Load):return None
    name=emitter.model.resolved_name(emitter.plan,node)
    parameter=lookup(emitter,name)
    if parameter is None:return None
    binding=emitter.model.lexical.binding(node)
    if(binding is None or binding.owner!=parameter.scope or binding.name!=name
            or emitter.kind(node)!=parameter.kind):return None
    from .native_classes import Expression
    code=parameter.code if copy_kind(emitter.model,parameter.kind)else '('+parameter.code+').clone()'
    return Expression(code,parameter.kind)


def argument(emitter,name,kind):
    """Known-defined physical root; callers already checked lexical ownership."""
    parameter=lookup(emitter,name)
    return parameter.code if parameter is not None and parameter.kind==kind else None


def reference(emitter,node):
    """Short reference for existing leaf projections, never a source borrow."""
    if not isinstance(node,ast.Name)or not isinstance(node.ctx,ast.Load):return None
    model=emitter.model;name=model.resolved_name(emitter.plan,node)
    parameter=lookup(emitter,name)
    if parameter is None:return None
    binding=model.lexical.binding(node)
    if(binding is None or binding.owner!=parameter.scope or binding.name!=name
            or emitter.kind(node)!=parameter.kind):return None
    return '&('+parameter.code+')'


def slot_required(emitter,name,kind):
    selected=lookup(emitter,name)
    return selected is None or selected.kind!=kind
