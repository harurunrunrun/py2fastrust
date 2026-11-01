"""Proved call-result type dependencies over normalized source control flow."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ReturnSummary:
    parameters:frozenset[str]
    literals:frozenset[str]


def summary(model,callee):
    if model.unit is None:return None
    cache=getattr(model,'source_return_summaries',None)
    if cache is None:
        from .native_constraints import SemanticGraph
        model.source_return_graph=SemanticGraph(model.unit)
        cache={};model.source_return_summaries=cache
    if callee.index in cache:return cache[callee.index]
    function=model.source_return_graph.functions.get(model.unit.ordinal(callee.node))
    if function is None:cache[callee.index]=None;return None
    names=set(callee.arguments)
    names.discard(getattr(callee.signature,'variadic_positional',None))
    names.discard(getattr(callee.signature,'variadic_keyword',None))
    scope=model.unit.scope_for(callee.node).ordinal
    blocked={binding.name for binding in model.unit.bindings if binding.owner==scope and
             (binding.role not in {'load','parameter'}or binding.scope!=scope)}
    names-=blocked

    def block(operations):
        parameters=set();literals=set();normal=True
        for operation in operations:
            if not normal:break
            op=operation.operation
            if op=='return':
                if not operation.operands:literals.add('none')
                else:
                    term=operation.operands[0]
                    if term.operation=='name'and term.data in names:parameters.add(term.data)
                    elif term.operation=='constant':literals.add(term.data)
                    else:return None
                normal=False
            elif op in {'branch','for','while'}:
                children=[block(child)for child in operation.blocks]
                if any(child is None for child in children):return None
                for child in children:
                    parameters.update(child[0]);literals.update(child[1])
                normal=any(child[2]for child in children)if op=='branch'else True
            elif op=='unknown':return None
            elif op in {'break','continue'}:
                normal=False
        return parameters,literals,normal

    result=block(function.body)
    if result is None:cache[callee.index]=None;return None
    parameters,literals,normal=result
    if normal:literals.add('none')
    result=ReturnSummary(frozenset(parameters),frozenset(literals))
    cache[callee.index]=result
    return result


def project_result(model,caller,node,callee,bound):
    from .native_classes import Cell,shape
    from .native_types import TupleSequenceType
    proof=summary(model,callee)
    if proof is None or not proof.parameters:return callee.result
    if any(isinstance(shape(bound[name]),TupleSequenceType)for name in proof.parameters):return callee.result
    result=model.cell(caller,node,identity=('source_return_dependencies',callee.index))
    for parameter in sorted(proof.parameters):model.contribute(result,bound[parameter],node)
    for kind in sorted(proof.literals):model.contribute(result,Cell(kind),node)
    return result


def emit_result(emitter,node,callee,code,wanted):
    from .native_classes import Expression,shape
    stored=shape(callee.result)
    if stored==wanted:return code
    if summary(emitter.model,callee)is None:return emitter.coerce(Expression(code,stored),wanted,node)
    before,value=emitter.capture(Expression(code,stored))
    return '{'+before+_narrow(emitter,node,stored,wanted,value.code)+'}'


def _narrow(emitter,node,stored,wanted,code):
    from .native_classes import Expression
    from .native_types import TupleType,alternatives,tuple_code
    from .native_unions import project,union_kind
    from .native_class_globals import narrow_binding
    if stored==wanted:return code
    if union_kind(stored):return project(stored,code,lambda child,value:_narrow(emitter,node,child,wanted,'('+value+').clone()'))
    candidates=alternatives(wanted)
    if isinstance(stored,TupleType):
        targets=[kind for kind in candidates if isinstance(kind,TupleType)and len(kind.fields)==len(stored.fields)]
        if len(targets)==1:
            target=targets[0];temporary=emitter.fresh()
            fields=[_narrow(emitter,node,old,new,temporary+'.'+str(index)+'.clone()')
                    for index,(old,new)in enumerate(zip(stored.fields,target.fields))]
            result=emitter.coerce(Expression(tuple_code(fields),target),wanted,node)
            return '{let '+temporary+'='+code+';'+result+'}'
    if getattr(stored,'_native_function_reference',False):
        targets=[kind for kind in candidates if getattr(kind,'_native_function_reference',False)]
        if len(targets)==1:
            narrowed=narrow_binding(emitter,node,stored,targets[0],code)
            return emitter.coerce(narrowed,wanted,node)
    return narrow_binding(emitter,node,stored,wanted,code).code
