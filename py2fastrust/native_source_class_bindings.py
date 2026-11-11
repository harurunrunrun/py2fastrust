"""Source publication evidence for class names reached through real witnesses."""
import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class ClassBinding:
    state: object
    owner: object
    name: object
    slot: object
    producers: tuple


def builtin_value(node):
    if isinstance(node,ast.Constant):
        return type(node.value) in (int,bool,float,str,bytes,type(None))
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
        return isinstance(node.operand,ast.Constant) and type(node.operand.value) in (int,float)
    if isinstance(node,(ast.List,ast.Tuple,ast.Set)):
        return all(builtin_value(value) for value in node.elts)
    if isinstance(node,ast.Dict):
        return all(key is not None and builtin_value(key) and builtin_value(value)
                   for key,value in zip(node.keys,node.values))
    return False


def publication_closed(state,owner):
    """No class-creation callback can expose an instance before name binding.

    Plain type construction over builtin values and original functions has no
    user __set_name__ values or metaclass/base hooks. Class/function annotations
    are deferred by the Python3.14 source semantics; annotation observers are
    outside this certificate. Defaults and decorators must also be closed.
    """
    model=state.model
    if not state.class_root(owner) or owner.body_plan is None:
        return False
    from .native_aot_callables import function_kind
    from .references import BuiltinIdentity
    for node in owner.node.body:
        if isinstance(node,ast.Pass):continue
        if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):continue
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else (node.target,)
            if not all(isinstance(target,ast.Name) for target in targets):return False
            if node.value is not None and not builtin_value(node.value):return False
            continue
        if not isinstance(node,ast.FunctionDef) or node.type_params:
            return False
        defaults=tuple(node.args.defaults)+tuple(value for value in node.args.kw_defaults if value is not None)
        if not all(builtin_value(value) for value in defaults):return False
        if node.decorator_list:
            if len(node.decorator_list)!=1 or not isinstance(node.decorator_list[0],ast.Name):return False
            kind=state.kind(owner.body_plan,node.decorator_list[0])
            if not function_kind(kind) or kind.targets!=(BuiltinIdentity('classmethod'),):return False
    return True


def certify(state,slot,name):
    model=getattr(state,'model',None)
    owner=getattr(slot,'owner',None)
    producers=getattr(state,'producers',None)
    if (model is None or owner is None or not producers or getattr(state,'barrier',None) is not None
            or getattr(model,'unit',None) is None or model.namespace.globals_observed
            or model.class_key(owner)!=name or state.slots.get(slot.key) is not slot):
        return None
    from .native_single_execution_metadata import _identities
    from .native_classes import shape
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    mutation={'globals','locals','vars','setattr','delattr','eval','exec','compile','__import__'}
    for cell in model.records.values():
        for identity in _identities(shape(cell)):
            if isinstance(identity,BuiltinIdentity) and identity.name in mutation:return None
            if isinstance(identity,BuiltinRef) and (
                    identity.module=='builtins' and identity.name in mutation
                    or identity.module=='sys' and identity.name in {'settrace','setprofile','call_tracing'}):return None
    if not publication_closed(state,owner):return None
    origins=[]
    for producer in producers.values():
        if producer.slot.key!=slot.key:continue
        node=producer.node
        if (producer.slot is not slot or not isinstance(node,ast.Call)
                or not isinstance(node.func,ast.Attribute) or node.func.attr!='append'
                or not isinstance(node.func.value,ast.Attribute)
                or state.slot(producer.plan,node.func.value) is not slot):return None
        # A successful original member append supplies an actual class/instance
        # receiver. Under closed class publication, that receiver cannot exist
        # before this canonical name is bound. class_root seals later writes.
        origins.append((producer.plan.index,model.unit.ordinal(node)))
    if not origins:return None
    return ClassBinding(state,owner,name,slot,tuple(origins))
