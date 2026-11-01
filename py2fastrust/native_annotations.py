"""Keep lazy annotation syntax out of ordinary executable value inference.

Python 3.14 creates deferred annotations. We retain original AST/scope metadata
for future annotation-object support; unobserved annotations supply no types and
execute no expressions. This is an execution view, never an AST rewrite.
"""
import ast
from collections import deque


def executable_nodes(root):
    pending=deque([root])
    while pending:
        node=pending.popleft()
        yield node
        if isinstance(node,ast.arg):continue
        excluded=set()
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            if node.returns is not None:excluded.add(id(node.returns))
        if isinstance(node,ast.AnnAssign):excluded.add(id(node.annotation))
        children=[child for child in ast.iter_child_nodes(node)if id(child)not in excluded]
        pending.extend(children)


def target_inputs(target):
    """An annotation-only non-simple target evaluates primaries, not a lookup."""
    if isinstance(target,ast.Attribute):return(target.value,)
    if isinstance(target,ast.Subscript):
        if isinstance(target.slice,ast.Slice):
            return(target.value,*(bound for bound in(target.slice.lower,target.slice.upper,target.slice.step)if bound is not None))
        return(target.value,target.slice)
    return()


def future_directive(node):
    return isinstance(node,ast.ImportFrom)and not node.level and node.module=='__future__'


def class_body_statement(node):
    return isinstance(node,ast.Assert)or isinstance(node,ast.AnnAssign)and node.value is None


def class_body_effect(node):
    return isinstance(node,ast.Assert)or isinstance(node,ast.AnnAssign)and node.value is None and bool(target_inputs(node.target))


def try_statement(g,node,environment):
    if future_directive(node):return '',environment
    if isinstance(node,ast.Assert):
        from .native_assertions import lower
        return lower(g,node,environment),environment
    if not isinstance(node,ast.AnnAssign):return None
    if node.value is None:
        return ''.join(g.expression(expression,environment).code+';'for expression in target_inputs(node.target)),environment
    from .native import _Expression,_Unsupported
    from .native_types import reference_cloneable,list_type
    value=g.expression(node.value,environment)
    saved=g.temporary()
    if isinstance(node.target,ast.Name):
        if node.target.id in g.iterating_lists or not reference_cloneable(value.kind)and not value.owned:
            raise _Unsupported('this annotated assignment needs a shared identity-preserving mutable binding, but the solved source storage has no such carrier',node=node,types=(('value',value.kind),),proof='annotated binding alias lifetime')
        code=g.coerce(value,value.kind)if reference_cloneable(value.kind)and not value.owned else value.code
        slot=g.bind(node.target.id,value,environment)
        return f'let {saved}={code};{slot}={saved};',environment
    if isinstance(node.target,ast.Subscript)and not isinstance(node.target.slice,ast.Slice):
        target=node.target
        owner=g.expression(target.value,environment)
        if not list_type(owner.kind):
            raise _Unsupported('this annotated target requires a mapping or user-object item-assignment adapter; only the shared builtin list target storage is implemented here',node=target,types=(('target',owner.kind),),proof='annotated item-assignment target protocol')
        from .native_sequence_storage import capture_owned
        from .native_typed_lists import _enable,_index
        storage=capture_owned(g,owner,target.value,environment,mutates=True)
        if storage.mutable is None:raise _Unsupported('the annotated target has no writable sequence view',node=target)
        _enable(g)
        offset=g.expression(target.slice,environment)
        index,position=g.temporary(),g.temporary()
        converted=g.coerce(_Expression(saved,value.kind,owned=False),storage.element)
        code=(f'let {saved}={value.code};'+''.join(storage.setup)+f'let {index}={g.number(offset)};'
              f'let {position}='+_index(g,index,f'({storage.read}).len()',target,assignment=True)+';'
              f'({storage.mutable})[{position}]={converted};')
        return code,environment
    raise _Unsupported('this annotated assignment requires a user-object attribute or slice-assignment protocol that has no ordinary native storage adapter',node=node.target,proof='annotated assignment target protocol')


def metadata_target(model,plan,target,environment):
    # A known function-name receiver proves the unsupported metadata operation
    # without evaluating any target primary or changing RHS execution order.
    if(isinstance(target,ast.Attribute)and isinstance(target.value,ast.Name)
            and target.attr in {'__annotations__','__annotate__','__type_params__'}):
        from .native_classes import shape
        metadata_access(target,shape(model.expression(plan,target.value,environment)))


def metadata_access(node,kind):
    if not isinstance(node,ast.Attribute)or node.attr not in {'__annotations__','__annotate__','__type_params__'}:return
    from .native_types import alternatives
    if any(getattr(value,'_native_function_reference',False)for value in alternatives(kind)):
        from .native import _Unsupported
        raise _Unsupported('the original deferred annotation syntax and official scopes are preserved, but observing or changing function annotation metadata requires lazy annotation objects, defining-namespace evaluation and caching that are not implemented yet',node=node,operation='function '+node.attr+' metadata access',proof='lazy annotation object and namespace lifetime')
