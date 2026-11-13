"""Direct append over actual finite builtin-list receiver allocations.

Every branch keeps its existing list handle and element ABI. No list contents
are copied to merge representations; only the selected runtime arm is mutated.
"""
import ast


def _members(receiver):
    from .native_union_sequences import branches
    root=receiver.root()
    if root.tag!='union':return ()
    members=tuple(branches(root))
    return members if members and all(member.tag=='list'for member in members)else ()


def _error(count,keywords):
    if keywords:return 'TypeError: list.append() takes no keyword arguments'
    if count!=1:return 'TypeError: list.append() takes exactly one argument ('+str(count)+' given)'
    return None


def analyze(model,plan,node,receiver,arguments,keywords):
    key=plan.index,id(node)
    sites=getattr(model,'finite_list_append_sites',None)
    if sites is not None:sites.pop(key,None)
    if not isinstance(node.func,ast.Attribute)or node.func.attr!='append':return None
    members=_members(receiver)
    if not members:return None
    from .native_sequence_plans import LIST_METHODS
    method=LIST_METHODS['append']
    error=_error(len(arguments),keywords)
    if error is None:
        # The canonical builtin signature establishes the value parameter.
        # Its source expression was already evaluated once after the receiver.
        bound=method.signature.bind([receiver]+arguments,keywords,{}).by_name
        for member in members:model.contribute(member.args[0],bound['value'],node)
    if sites is None:sites=model.finite_list_append_sites={}
    if error is not None:
        from dataclasses import replace
        method=replace(method,error=error,mutates=False)
    # Reuse the canonical operation/effect metadata consumed by ownership and
    # call-region proofs, even though emission selects several element ABIs.
    model.sequence_calls[key]=method
    sites[key]=error
    return model.cell(plan,node,'none')


def _closed(kind):
    from .native_types import alternatives,ListType,SharedListType
    return all(type(part)in{ListType,SharedListType}for part in alternatives(kind))


def emit(emitter,node):
    sites=getattr(emitter.model,'finite_list_append_sites',{})
    key=emitter.plan.index,id(node)
    if key not in sites:return None
    kind=emitter.kind(node.func.value)
    if not _closed(kind):return None
    from .native_classes import Expression
    from .call_semantics import normalize_call
    from .native_unions import project
    from .native_class_builtins import _error as runtime_error
    from .native import _string
    # Capture the actual object before argument callbacks can rebind its name
    # or field. No element borrow is held while those callbacks execute.
    setup,owner=emitter.capture(emitter.expression(node.func.value))
    values=[]
    invocation=normalize_call(node)
    for argument in invocation.evaluation_order:
        before,value=emitter.capture(emitter.expression(argument.expression))
        setup+=before;values.append(value)
    error=sites[key]
    if error is not None:
        result=runtime_error(emitter,node,'none',_string(error)+'.to_owned()')
        return Expression('{'+setup+result.code+'}','none')
    value=values[0]
    def branch(kind,code):
        payload=emitter.fresh()
        converted=emitter.coerce(value,kind.element,node)
        pushed=emitter.at('native_typed_push(&mut *('+code+').borrow_mut(),'+payload+')',node)
        return '{let '+payload+'='+converted+';'+pushed+'}'
    return Expression('{'+setup+project(owner.kind,owner.code,branch)+'}','none')
