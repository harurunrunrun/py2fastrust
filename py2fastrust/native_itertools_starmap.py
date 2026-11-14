"""Lazy tuple/list argument rows use compiled callable binding protocols."""
from .native_types import EMPTY,EmptyType,ListType,TupleType,TupleSequenceType,kind_tag


def bind(positional,keywords):
    if keywords:return 'TypeError: starmap() takes no keyword arguments'
    if len(positional)!=2:return f'TypeError: starmap expected 2 arguments, got {len(positional)}'
    return None


def analyze(model,plan,node,positional,keywords,environment,*,factory):
    from .native_classes import Cell
    from .native_itertools import ToolCall
    error=bind(positional,keywords)
    if error:return ToolCall(factory('none'),error=error)
    registry=model.iterators;record=registry._record(plan,node,'itertools_starmap')
    from .native_iterator_hints import ABSENT
    record.adapter=StarmapState;record.tool='starmap';record.hint_protocol=ABSENT
    if record.callback is None:record.callback=Cell()
    registry._contribute(record.callback,positional[0],node)
    record.input_types=(registry.source(plan,node,positional[1],('starmap',record.index),environment=environment),)
    return ToolCall(factory(record.kind),record)


def emit(emitter,node,call,positional,keywords):
    from .native_classes import Expression
    assert bind(positional,keywords) is None
    record=call.iterator;record.emitted=True
    source=emitter.model.iterators.construct(emitter,node,positional[1],kind=record.input_types[0])
    before,source=emitter.capture(source)
    code=('{'+before+'Rc::new(RefCell::new(ClassIteratorState_'+str(record.index)
          +'{source:'+source.code+',callback:'+positional[0].code+'}))}')
    return Expression(code,record.kind)


def row_protocol(kind,node):
    from .native_classes import ClassUnsupported,domain
    if isinstance(kind,TupleType):return 'fixed'
    if isinstance(kind,(ListType,TupleSequenceType)):return 'expanded'
    if domain(kind)in{'int','bool','int_bool','float','complex','none','function'}:return 'noniterable'
    raise ClassUnsupported(node,
        'itertools.starmap row needs its original iterable-to-argument-tuple conversion, including acquisition and length/error behavior; that row protocol is not implemented beyond builtin tuple/list storage',
        types=(('row',kind),),proof='starmap row argument expansion protocol')


class StarmapState:
    @staticmethod
    def owned(record):
        from .native_classes import shape
        return (*record.input_types,shape(record.callback))

    @staticmethod
    def may_call(registry,record,seen):return True

    @staticmethod
    def demand(registry,plan,node,record,environment,active):
        from .native_classes import Cell,Environment,shape
        from .native_aot_callables import analyze_values
        from .native_union_sequences import branches
        from .call_semantics import Argument,CallArguments
        item=registry.demand(plan,node,Cell(record.input_types[0]),environment,active+(record.index,))
        if isinstance(shape(item),EmptyType):
            registry._contribute(record.element,Cell(EMPTY),node)
            return record.element
        if shape(item) is None:return record.element
        demands={};environments=[]
        for row in branches(item):
            kind=shape(row)
            if kind is None:continue
            protocol=row_protocol(kind,node);inside=Environment(environment)
            identity='starmap_'+str(record.index)+'_'+kind_tag(kind)
            if protocol=='fixed':
                fields=list(row.root().args)
                metadata=CallArguments(tuple(Argument(record.node)for _ in fields),())
                site=analyze_values(registry.model.callable_cells,plan,node,record.callback,
                    metadata,fields,[],inside,identity=('starmap_callback',identity))
                registry._contribute(record.element,site.result,node)
            elif protocol=='expanded':
                site=registry.model.expanded_calls.analyze_captured_row(plan,node,record.callback,row,inside,identity=identity)
                registry._contribute(record.element,site.result,node)
            else:
                site=None;registry._contribute(record.element,Cell(EMPTY),node)
            demands[kind]=(protocol,site);environments.append(inside)
        record.demands[(plan.index,id(node))]=demands
        if environments:
            joined=environments[0]
            for inside in environments[1:]:joined=registry.model.join(joined,inside,node,'starmap_callback')
            registry.model.replace_environment(environment,joined)
        return record.element

    @staticmethod
    def fields(emitter,record):
        from .native_classes import shape
        return ('source:'+emitter.rust_type(record.input_types[0])
                +',callback:'+emitter.rust_type(shape(record.callback)))

    @staticmethod
    def pull(registry,emitter,node,value,active):
        from .native_classes import Expression,ClassUnsupported,shape
        from .native_unions import project,union_kind
        from .native_aot_callables import emit_values
        from .native_class_iterators import demand_key
        record=value.kind.record;wanted=shape(record.element)
        state,source,callback,row=(emitter.fresh()for _ in range(4))
        label='starmap_pull_'+emitter.fresh()
        pulled=registry.pull(emitter,node,Expression(source,record.input_types[0]),active+(record.index,),stop='propagate')
        code='{let ('+source+','+callback+')={let '+state+'='+value.code+'.borrow();('+state+'.source.clone(),'+state+'.callback.clone())};'
        code+="'"+label+':{let Some('+row+')=('+pulled.code+")else{break '"+label+' None;};'
        if isinstance(pulled.kind,EmptyType):return Expression(code+'match '+row+'{}}}',wanted)
        demands=record.demands.get(demand_key(emitter,node))
        if demands is None:raise ClassUnsupported(node,'the deferred starmap callback has no matching original demand proof',proof='starmap captured callback demand')
        callee=Expression(callback,shape(record.callback))
        def branch(kind,text):
            proof=demands.get(kind)
            if proof is None:raise ClassUnsupported(node,'this starmap row alternative has no matching original expansion proof',types=(('row',kind),),proof='starmap row expansion demand')
            protocol,site=proof
            if protocol=='noniterable':
                from .native_class_builtins import _type_name
                name=_type_name(emitter,Expression(text,kind),node)
                return emitter.at('Err::<'+emitter.rust_type(wanted)+',String>(format!("TypeError: \'{}\' object is not iterable",'+name+'))',node)
            if protocol=='fixed':
                fields=[Expression('('+text+').'+str(index)+'.clone()',field)for index,field in enumerate(kind.fields)]
                return emit_values(emitter,node,site,callee,fields,[],wanted).code
            return emitter.model.expanded_calls.emit_captured_row(emitter,node,site,callee,Expression('('+text+').clone()',kind),wanted).code
        result=project(pulled.kind,row,branch)if union_kind(pulled.kind)else branch(pulled.kind,row)
        return Expression(code+'Some('+result+')}}',wanted)
