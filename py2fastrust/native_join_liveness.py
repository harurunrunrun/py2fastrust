"""Backward binding liveness for ordinary native control-flow transfers.

Only redundant carrier moves are removed. Source evaluations and assignments
stay in their original order. Keys use the official binding owner, including
the distinct local targets of generator expressions and comprehensions.
"""
import ast
from contextlib import contextmanager


class UnsupportedFlow(Exception):pass


def closed_calls(g):
    """Close reached source calls and captured callbacks over real solver facts."""
    from .references import BuiltinIdentity
    from .native_module_calls import BuiltinRef
    from .native_constraints import FunctionValue,MethodValue,TupleValue
    observers={'locals','globals','vars','eval','exec','compile'}
    scopes={}
    for(definition,_),facts in getattr(getattr(g,'type_analysis',None),'scopes',{}).items():
        if definition is not None:scopes.setdefault(definition,[]).append(facts)
    pending=[g.constraint_facts];seen=set()
    while pending:
        facts=pending.pop()
        if id(facts)in seen:continue
        seen.add(id(facts))
        nodes=getattr(getattr(getattr(g,'type_analysis',None),'graph',None),'nodes',{})
        if any(isinstance(nodes.get(site),ast.Call)and site not in facts.calls
               for site in facts.expressions):
            # Expanded/unproved invocations need actual callee-effect facts too.
            raise UnsupportedFlow
        for call in facts.calls.values():
            if(call.identity.unknown or not call.identity.alternatives
                    or any(not isinstance(identity,(BuiltinIdentity,BuiltinRef,FunctionValue,MethodValue))
                           for identity in call.identity.alternatives)):
                raise UnsupportedFlow
            values=[call.identity,*call.positional,*(value for _,value in call.keywords)]
            visited=set()
            while values:
                value=values.pop()
                if id(value)in visited:continue
                visited.add(id(value))
                for identity in value.alternatives:
                    if isinstance(identity,(BuiltinIdentity,BuiltinRef))and identity.name in observers:
                        raise UnsupportedFlow
                    if isinstance(identity,FunctionValue):
                        reached=scopes.get(identity.definition)
                        if not reached:raise UnsupportedFlow
                        pending.extend(reached)
                        values.extend(value for _,value in identity.defaults)
                    elif isinstance(identity,TupleValue):values.extend(identity.fields)


class Flow:
    def __init__(self,g):
        self.unit=g.source_unit
        if self.unit is None or g.constraint_facts is None:raise UnsupportedFlow
        self.owner=self.unit.scope_for(g.function.node).ordinal if g.function else 0
        self.bindings={binding.node:binding for binding in self.unit.bindings}
        self.pinned={binding.name for binding in self.unit.bindings
                     if binding.owner==self.owner and binding.scope!=self.owner
                     and binding.role=='load'}
        self.exits={};self.headers={}
        closed_calls(g)
        body=g.function.node.body if g.function else self.unit.tree.body
        if not isinstance(body,(list,tuple)):raise UnsupportedFlow
        self.block(body,set(),None,None)

    def key(self,node):
        binding=self.bindings.get(self.unit.ordinal(node))
        return binding.name if binding is not None and binding.owner==self.owner else None

    def uses(self,node):
        return {name for child in ast.walk(node)if isinstance(child,ast.Name)
                and isinstance(child.ctx,ast.Load)and(name:=self.key(child))is not None}

    def definitions(self,node):
        if isinstance(node,ast.Name):
            name=self.key(node)
            return {name}if name is not None else set()
        if isinstance(node,(ast.Tuple,ast.List)):
            return set().union(*(self.definitions(child)for child in node.elts))
        if isinstance(node,ast.Starred):return self.definitions(node.value)
        return set()

    def block(self,body,after,breaking,continuing):
        live=set(after)|self.pinned
        for node in reversed(body):
            live=self.statement(node,live,breaking,continuing)|self.pinned
        return live

    def statement(self,node,after,breaking,continuing):
        if isinstance(node,(ast.For,ast.While)):
            otherwise=self.block(node.orelse,after,breaking,continuing)
            exiting=set(after)|otherwise|self.pinned
            head=set(exiting)
            while True:
                inside=self.block(node.body,head,after,head)
                if isinstance(node,ast.For):
                    repeated=(inside-self.definitions(node.target))|self.uses(node.target)
                else:repeated=inside|self.uses(node.test)
                updated=exiting|repeated|self.pinned
                if updated==head:break
                head=updated
            self.exits[id(node)]=frozenset(exiting)
            self.headers[id(node)]=frozenset(head)
            return head|(self.uses(node.iter)if isinstance(node,ast.For)else set())
        if isinstance(node,ast.If):
            return (self.uses(node.test)|self.block(node.body,after,breaking,continuing)
                    |self.block(node.orelse,after,breaking,continuing))
        if isinstance(node,ast.Assign):
            defined=set().union(*(self.definitions(target)for target in node.targets))
            return((after-defined)|self.uses(node.value)
                   |set().union(*(self.uses(target)for target in node.targets)))
        if isinstance(node,ast.AnnAssign):
            # An annotation without a value leaves the existing binding intact.
            retained=after if node.value is None else after-self.definitions(node.target)
            return(retained|self.uses(node.target)
                   |self.uses(node.annotation)|(self.uses(node.value)if node.value is not None else set()))
        if isinstance(node,ast.AugAssign):
            return after|self.uses(node.target)|self.definitions(node.target)|self.uses(node.value)
        if isinstance(node,ast.Delete):
            # Deleting an absent binding is observable even without a later load.
            return after|set().union(*(self.definitions(target)|self.uses(target)for target in node.targets))
        if isinstance(node,ast.Break):
            if breaking is None:raise UnsupportedFlow
            return set(breaking)
        if isinstance(node,ast.Continue):
            if continuing is None:raise UnsupportedFlow
            return set(continuing)
        if isinstance(node,(ast.Return,ast.Raise)):
            return self.uses(node)
        if isinstance(node,(ast.Expr,ast.Assert)):
            return after|self.uses(node)
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            # Function bodies have separate execution frames. Free binding loads
            # are pinned above, including closures which escape this function.
            expressions=list(node.decorator_list)+list(node.args.defaults)
            expressions += [value for value in node.args.kw_defaults if value is not None]
            return after|set().union(*(self.uses(value)for value in expressions))
        if isinstance(node,(ast.Import,ast.ImportFrom,ast.Pass,ast.Global,ast.Nonlocal)):
            return set(after)
        raise UnsupportedFlow


def analysis(g):
    if not hasattr(g,'join_liveness'):
        try:g.join_liveness=Flow(g)
        except UnsupportedFlow:g.join_liveness=None
    return g.join_liveness


def passive(kind):
    """These concrete carriers have no source finalizer or cleanup protocol."""
    from .native_types import (immutable,unmaybe,ListType,DequeType,TupleType,
                               TupleSequenceType,UnionType,NullableType)
    kind=unmaybe(kind)
    if immutable(kind)or kind in {'list_int','matrix_int','deque_int','dict_int','set_int'}:return True
    if isinstance(kind,(ListType,DequeType,TupleSequenceType)):return passive(kind.element)
    if isinstance(kind,TupleType):return all(passive(field)for field in kind.fields)
    if isinstance(kind,UnionType):return all(passive(part)for part in kind.alternatives)
    if isinstance(kind,NullableType):return passive(kind.value)
    if getattr(kind,'_key_container',False):
        return passive(kind.key)and(getattr(kind,'_key_container')!='dict'or passive(kind.value))
    return False


def dead(g,name,values):
    from .native import _Binding
    live=getattr(g,'live_merge_names',None)
    return(live is not None and name not in live
           and all(value is None or isinstance(value,_Binding)and passive(value.kind)for value in values))


@contextmanager
def loop(g,node,header):
    from .native import _Binding
    flow=analysis(g)
    old=getattr(g,'live_merge_names',None)
    selected=header
    if flow is not None and id(node)in flow.exits:
        keep=flow.headers[id(node)]
        selected={name:value for name,value in header.items()
                  if name in keep or not isinstance(value,_Binding)or not passive(value.kind)}
        g.live_merge_names=flow.exits[id(node)]
    try:yield selected
    finally:g.live_merge_names=old
