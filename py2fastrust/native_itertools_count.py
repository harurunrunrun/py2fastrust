"""Canonical count cursors with concrete builtin numeric state."""
import ast

from .native_types import alternatives

NUMERIC=frozenset({'int','bool','int_bool','float'})


def bind(positional,keywords):
    size=len(positional)+len(keywords)
    if size>2:return None,f'TypeError: count() takes at most 2 arguments ({size} given)'
    values=dict(zip(('start','step'),positional))
    for name,value in keywords:
        if name not in {'start','step'}:
            return None,f"TypeError: count() got an unexpected keyword argument '{name}'"
        if name in values:
            return None,f"TypeError: argument for count() given by name ('{name}') and position ({1 if name=='start'else 2})"
        values[name]=value
    return [values.get('start'),values.get('step')],None


def numeric_kinds(model,node,value,role):
    from .native_classes import ClassUnsupported,shape,domain
    result=[]
    for kind in alternatives(shape(value)):
        if kind is None:continue
        if kind in NUMERIC:result.append(kind);continue
        if kind=='complex' or domain(kind) not in {
                'str','bytes','bytearray','list','tuple','tuple_sequence','range',
                'none','function','dict','set','frozenset','deque','dict_view',
                'iterator','generator','module','builtin_singleton',
                'builtin_type','exception_class','exception_value','globals_dict'}:
            raise ClassUnsupported(node,
                'itertools.count '+role+' requires a numeric object protocol outside builtin int/bool/float; that numeric-slot and addition adapter is not implemented',
                types=((role,kind),),proof='itertools.count builtin numeric state')
    return result


def analyze(model,plan,node,positional,keywords,environment,*,factory):
    from .native_classes import Cell,shape
    from .native_itertools import ToolCall
    values,error=bind(positional,keywords)
    if error:return ToolCall(factory('none'),error=error)
    start=values[0] if values[0] is not None else Cell('int')
    step=values[1] if values[1] is not None else Cell('int')
    starts=numeric_kinds(model,node,start,'start')
    steps=numeric_kinds(model,node,step,'step')
    if shape(start) is not None and not starts or shape(step) is not None and not steps:
        return ToolCall(factory('none'),error='TypeError: a number is required')
    registry=model.iterators
    record=registry._record(plan,node,'itertools_count')
    from .native_iterator_hints import ABSENT
    record.hint_protocol=ABSENT
    record.adapter=CountState;record.tool='count'
    if record.callback is None:record.callback=Cell()
    for kind in starts:registry._contribute(record.element,model.cell_for_kind(kind),node)
    for kind in steps:registry._contribute(record.callback,model.cell_for_kind(kind),node)
    if shape(record.element) is not None and shape(record.callback) is not None:
        result=model.binary(plan,node,ast.Add(),record.element,record.callback,
                            identity=('count_add',record.index),environment=environment)
        registry._contribute(record.element,result,node)
    return ToolCall(factory(record.kind),record)


def emit(emitter,node,call,positional,keywords):
    from .native_classes import Expression,shape
    from .native_unions import project,union_kind
    values,error=bind(positional,keywords);assert error is None
    start=values[0] if values[0] is not None else Expression(emitter.literal(0),'int',0)
    step=values[1] if values[1] is not None else Expression(emitter.literal(1),'int',1)
    record=call.iterator;record.emitted=True
    wanted=shape(record.element);step_kind=shape(record.callback)
    def branch_start(kind,code):
        first=Expression('('+code+').clone()',kind)
        def branch_step(other,text):
            if kind not in NUMERIC or other not in NUMERIC:
                return emitter.at('Err::<'+emitter.rust_type(record.kind)+',String>("TypeError: a number is required".to_owned())',node)
            amount=Expression('('+text+').clone()',other)
            initial=emitter.coerce(first,wanted,node)
            if kind in {'bool','int_bool'} and other in {'int','bool','int_bool'}:
                integer=Expression(emitter.number(first),'int')
                normalized=emitter.coerce(integer,wanted,node)
                initial='if '+emitter.number(amount)+'=='+emitter.literal(1)+'{'+normalized+'}else{'+initial+'}'
            return ('Rc::new(RefCell::new(ClassIteratorState_'+str(record.index)+'{current:'+initial
                    +',step:'+emitter.coerce(amount,step_kind,node)+'}))')
        return project(step.kind,step.code,branch_step) if union_kind(step.kind) else branch_step(step.kind,step.code)
    code=project(start.kind,start.code,branch_start) if union_kind(start.kind) else branch_start(start.kind,start.code)
    return Expression(code,record.kind)


class CountState:
    @staticmethod
    def owned(record):
        from .native_classes import shape
        return (shape(record.element),shape(record.callback))

    @staticmethod
    def demand(registry,plan,node,record,environment,active):
        result=registry.model.binary(plan,node,ast.Add(),record.element,record.callback,
                                     identity=('count_add',record.index),environment=environment)
        registry._contribute(record.element,result,node)
        return record.element

    @staticmethod
    def may_call(registry,record,seen):return False

    @staticmethod
    def fields(emitter,record):
        from .native_classes import shape
        return ('current:'+emitter.rust_type(shape(record.element))
                +',step:'+emitter.rust_type(shape(record.callback)))

    @staticmethod
    def show(emitter,value,node,representation):
        from .native_classes import Expression,shape
        from .native_unions import project,union_kind
        record=value.kind.record
        owner,state,current,step,rendered=(emitter.fresh() for _ in range(5))
        current_kind=shape(record.element);step_kind=shape(record.callback)
        text=emitter.show(Expression(current,current_kind),node,True)
        amount=emitter.show(Expression(step+'.clone()',step_kind),node,True)
        def integral_one(kind,code):
            if kind not in {'int','bool','int_bool'}:return 'false'
            return emitter.number(Expression('('+code+').clone()',kind))+'=='+emitter.literal(1)
        omit=project(step_kind,step,integral_one) if union_kind(step_kind) else integral_one(step_kind,step)
        return ('{let ('+current+','+step+')={let '+owner+'=&('+value.code+');let '+state+'='+owner
                +'.borrow();('+state+'.current.clone(),'+state+'.step.clone())};'
                +'let '+rendered+'='+text+';if '+omit
                +'{format!("count({})",'+rendered+')}else{format!("count({}, {})",'
                +rendered+','+amount+')}}')

    @staticmethod
    def pull(registry,emitter,node,value,active):
        from .native_classes import Expression,shape
        record=value.kind.record;kind=shape(record.element)
        state,current,step,result=(emitter.fresh() for _ in range(4))
        addition=emitter.binary(ast.Add(),Expression(current+'.clone()',kind),
                                Expression(step,shape(record.callback)),node,kind,
                                identity=('count_add',record.index))
        code=('{let ('+current+','+step+')={let '+state+'='+value.code
              +'.borrow();('+state+'.current.clone(),'+state+'.step.clone())};'
              +'let '+result+'='+addition.code+';'+value.code+'.borrow_mut().current='
              +result+';Some('+current+')}')
        return Expression(code,kind)
