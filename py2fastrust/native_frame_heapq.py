"""Captured heapq operations on the original shared builtin list handle."""
from dataclasses import dataclass,field
from .native_heapq import CORE,NAMES,orderable


@dataclass
class HeapCall:
    result:object
    error:str|None=None
    comparators:dict=field(default_factory=dict)


class Comparator:
    def __init__(self,emitter):
        self.emitter=emitter
        self.bits={'i64':64,'i128':128,'bigint':0}[emitter.model.integer]
    def temporary(self):return self.emitter.fresh()
    def number(self,value):return self.emitter.number(value)
    def at(self,value,node):return self.emitter.at(value,node)


def binding_error(name,count,keywords):
    if keywords:return f'TypeError: _heapq.{name}() takes no keyword arguments'
    expected=2 if name.removesuffix('_max')in {'heappush','heappushpop','heapreplace'}else 1
    if count!=expected:
        if expected==1:return f'TypeError: _heapq.{name}() takes exactly one argument ({count} given)'
        return f'TypeError: {name} expected 2 arguments, got {count}'
    return None


class HeapAdapter:
    NAMES=frozenset(NAMES)
    EAGER_ARGUMENTS={"nlargest":frozenset({1}),"nsmallest":frozenset({1})}
    EAGER_KEYWORDS={"nlargest":frozenset({"iterable"}),"nsmallest":frozenset({"iterable"})}

    @staticmethod
    def analyze(model,plan,node,identity,call_arguments,arguments,keywords,environment,*,factory):
        from .native_classes import Cell,ClassUnsupported,shape,domain
        from .native_types import alternatives
        from .call_semantics import FunctionSignature
        from .native_union_sequences import branches
        if identity.name in {"nlargest","nsmallest"}:
            from .native_heap_selection import analyze
            return analyze(model,plan,node,identity,call_arguments,arguments,keywords,environment,factory=factory)
        operation=identity.name.removesuffix('_max')
        if operation not in CORE:
            raise ClassUnsupported(node,'heapq.'+identity.name+' needs its lazy multi-source/key selection adapter; this member adapter currently implements the core min/max heap mutations',proof='heap stream/key selection protocol')
        error=binding_error(identity.name,len(arguments),keywords)
        if error:return HeapCall(factory('none'),error)
        parameters=('heap','item')if len(arguments)==2 else('heap',)
        FunctionSignature.declaration(parameters,positional_only=parameters).plan(call_arguments)
        result=factory('none')if operation in {'heapify','heappush'}else factory()
        record=HeapCall(result)
        known=False
        for heap in branches(arguments[0]):
            if heap.tag=='list':
                known=True
                if len(arguments)==2:model.contribute(heap.args[0],arguments[1],node)
                element=shape(heap.args[0])
                from .native_fallible_heapq import analyze as fallible_comparison
                comparator=fallible_comparison(model,plan,node,identity.name,heap,environment)
                if comparator is not None:record.comparators[shape(heap)]=comparator
                if model.final and element is not None:
                    if model.integer=='bigint'and element!='float'and any(kind=='float'for kind in alternatives(element)):
                        raise ClassUnsupported(node,'this heap needs exact BigInt/float comparison; that numeric interoperation adapter is not implemented',proof='BigInt and binary64 heap ordering')
                if operation not in {'heapify','heappush'}:
                    if not model.namespace.contribute(result,heap.args[0],node,force=True):model.contribute(result,heap.args[0],node)
            elif heap.tag is not None:known=True
        if known and result.root().tag is None and model.final:model.contribute(result,Cell('none'),node)
        return record

    @staticmethod
    def emit(emitter,node,identity,record,arguments,keywords):
        from .native_classes import Expression,domain,shape
        from .native_unions import project,union_kind
        from .native_class_builtins import _type_name,_error
        from .native_heapq import _comparator
        from .native import _string
        if identity.name in {"nlargest","nsmallest"}:
            from .native_heap_selection import emit
            return emit(emitter,node,identity,record,arguments,keywords)
        wanted=shape(record.result)
        if record.error:return _error(emitter,node,wanted,_string(record.error)+'.to_owned()')
        operation=identity.name.removesuffix('_max')
        maximum=identity.name.endswith('_max')
        heap=arguments[0]
        def leaf(heap):
            if domain(heap.kind)!='list':
                typename='"None"'if domain(heap.kind)=='none'else _type_name(emitter,heap,node)
                label='argument 1'if len(arguments)==2 else'argument'
                template=f'TypeError: {identity.name}() {label} must be list, not {{}}'
                return _error(emitter,node,wanted,'format!('+_string(template)+','+typename+')').code
            element=heap.kind.element
            if heap.kind in record.comparators:
                from .native_fallible_heapq import emit
                return emit(emitter,node,identity.name,heap,arguments,wanted,record.comparators[heap.kind])
            compare=_comparator(Comparator(emitter),element,node,maximum)
            args='&mut ('+heap.code+').borrow_mut()'
            if len(arguments)==2:args+=','+emitter.coerce(arguments[1],element,node)
            args+=','+compare
            name='native_'+operation
            emitter.model.native_frame_heaps=getattr(emitter.model,'native_frame_heaps',set())|{name}
            code=name+'('+args+')'
            if operation not in {'heapify','heappushpop'}:code=emitter.at(code,node)
            raw='none'if operation in {'heapify','heappush'}else element
            return emitter.coerce(Expression(code,raw),wanted,node)
        code=project(heap.kind,heap.code,lambda kind,value:leaf(Expression('('+value+').clone()',kind)))if union_kind(heap.kind)else leaf(heap)
        return Expression(code,wanted)


def runtime(model):
    names=getattr(model,'native_frame_heaps',())
    from .native_fallible_heapq import runtime as fallible_runtime
    fallible=fallible_runtime(model)
    if not names:return fallible
    from .native_heapq import HELPERS
    from .rust_pruning import select_named_rust_items
    wanted=set(names)
    if wanted-{'native_heappush'}:wanted.add('native_heap_sink')
    wanted.add('native_heap_bubble')
    return select_named_rust_items(HELPERS,wanted)+('\n'+fallible if fallible else'')
