"""Choose native Rust calls from the resolved Python call graph.

Recursive components and longer chains keep the typed compiled-future call
stack. Small acyclic chains use Result-returning Rust functions. The logical
Python depth and exception frames remain shared between both representations.
"""
from collections import deque


MAX_NATIVE_CALL_DEPTH = 32


def classify(model):
    plans={plan.index:plan for plan in model.plans if plan.reachable}
    children={index:set(model.call_edges.get(index,())) for index in plans}
    parents={index:set() for index in plans}
    for parent,targets in children.items():
        for child in targets:parents[child].add(parent)
    remaining={index:len(targets) for index,targets in children.items()}
    ready=deque(index for index,count in remaining.items() if count==0)
    heights={}
    while ready:
        index=ready.popleft()
        heights[index]=1+max((heights[child] for child in children[index]),default=0)
        for parent in parents[index]:
            remaining[parent]-=1
            if remaining[parent]==0:ready.append(parent)
    model.native_call_heights=heights
    model.synchronous_calls=frozenset(index for index,height in heights.items()
                                    if height<=MAX_NATIVE_CALL_DEPTH)


def synchronous(model,plan):
    return plan is None or plan.index in model.synchronous_calls


def call(emitter,invocation,callee,node):
    from .native import _string
    mode=synchronous(emitter.model,callee)
    if mode:
        return (f"class_sync_call(&class_scope,||{invocation},"
                f"{node.lineno},{_string(emitter.plan.scope)})?")
    if synchronous(emitter.model,emitter.plan):
        raise RuntimeError("a synchronous native function has an unrecorded asynchronous callee")
    return (f"class_call(class_scope.clone(),{invocation},"
            f"{node.lineno},{_string(emitter.plan.scope)}).await?")


def runtime(source,model):
    if all(synchronous(model,plan) for plan in model.plans if plan.reachable):
        source=source.replace("struct ClassControl { child: Option<ClassTask>, depth: usize, limit: usize }",
                              "struct ClassControl { depth: usize, limit: usize }")
        source=source.replace("ClassControl{child:None,depth:0,limit:1000}",
                              "ClassControl{depth:0,limit:1000}")
        # The unreachable future executor still references the removed field;
        # discard those complete Rust items before ordinary reachability pruning.
        from .rust_pruning import _lex,_parse
        tokens,comments,pairs=_lex(source)
        excluded={"ClassFuture","ClassTask","ClassNoop","ClassCall","class_call","class_execute"}
        async_imports={"Future","Pin","Arc","Context","Poll","Wake","Waker"}
        source="\n".join(source[item.start:item.end] for item in _parse(source,tokens,comments,pairs)
                         if item.name not in excluded and item.owner not in {"ClassNoop","ClassCall"}
                         and not (item.kind=="use"and item.references & async_imports))
    return source
