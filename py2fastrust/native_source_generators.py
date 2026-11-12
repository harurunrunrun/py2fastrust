"""Original source generators compiled into concrete resumable Rust blocks.

Each source family has a typed frame and a source-specific resume function.
Only program counters are dispatched; all Python operations remain native Rust.
"""
import ast
from dataclasses import dataclass
from types import MethodType,SimpleNamespace

from .native_typed_continuations import Builder,Block


@dataclass
class SourceGenerator:
    yields:tuple
    record:object=None


def reject_statement(node):
    from .native_classes import ClassUnsupported
    if isinstance(node,(ast.Try,ast.TryStar)):
        construct='try/finally or try/except statement';required='exception-handler and cleanup suspension state'
    elif isinstance(node,(ast.With,ast.AsyncWith)):
        construct='with statement';required='context-manager cleanup across suspension'
    elif isinstance(node,ast.Raise):
        construct='raise statement';required='explicit raised-exception and exception-chain state'
    elif isinstance(node,ast.Delete):
        construct='del statement';required='suspended binding-deletion and ownership state'
    elif isinstance(node,ast.FunctionDef):
        construct='nested function definition '+repr(node.name);required='retained nested-function bindings and lexical environments'
    else:
        construct='nested class definition '+repr(node.name);required='retained class publication and namespace state'
    raise ClassUnsupported(node,'source generator '+construct+' requires '+required+'; that suspended control protocol is not implemented',operation='source generator '+construct,proof='source generator suspended control protocol')


def own_nodes(node):
    stack=list(reversed(node.body))
    while stack:
        current=stack.pop();yield current
        if isinstance(current,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(current))))


def initialize(model,plan):
    if not isinstance(plan.node,ast.FunctionDef):return False
    yields=tuple(node for node in own_nodes(plan.node)if isinstance(node,(ast.Yield,ast.YieldFrom)))
    if not yields:return False
    from .native_classes import ClassUnsupported
    parents={id(child):node for node in own_nodes(plan.node)for child in ast.iter_child_nodes(node)}
    for node in yields:
        if isinstance(node,ast.YieldFrom):
            raise ClassUnsupported(node,'yield from requires delegated send/throw/close and StopIteration.value propagation; that source generator delegation protocol is not implemented',proof='delegated source generator protocol')
        if not isinstance(parents.get(id(node)),ast.Expr):
            raise ClassUnsupported(node,'a yield used as an expression requires send() values on resumption; only statement yields are implemented',proof='source generator send-result binding')
    for node in own_nodes(plan.node):
        if isinstance(node,(ast.With,ast.AsyncWith,ast.Try,ast.TryStar,ast.Raise,ast.Delete,ast.FunctionDef,ast.ClassDef)):
            reject_statement(node)
    plan.source_generator=SourceGenerator(yields)
    model.source_generators_used=True
    if hasattr(model,'iterators'):attach(model,plan)
    return True


def attach(model,plan):
    from .native_classes import Cell,merge
    from .native_types import EMPTY
    spec=plan.source_generator
    if spec.record is not None:return
    record=model.iterators._record(plan,plan.node,'source_generator')
    record.adapter=ADAPTER;record.generator_plan=plan;record.generator_model=model
    record.element=Cell(EMPTY)
    spec.record=record
    merge(plan.result,Cell(record.kind),plan.node)


def prepare(model):
    for plan in model.plans:
        if getattr(plan,'source_generator',None)is not None:attach(model,plan)


def analyze_yield(model,plan,node,environment):
    from .native_classes import Cell,ClassUnsupported
    spec=getattr(plan,'source_generator',None)
    if spec is None or isinstance(node,ast.YieldFrom):raise ClassUnsupported(node)
    value=Cell('none')if node.value is None else model.expression(plan,node.value,environment)
    model.exceptions.require(node)
    model.iterators._contribute(spec.record.element,value,node)
    return model.cell(plan,node,'none')


def analyze_return(model,plan,node,value):
    from .native_classes import ClassUnsupported
    if node.value is not None and not(isinstance(node.value,ast.Constant)and node.value.value is None):
        raise ClassUnsupported(node,'a source generator return value requires retaining StopIteration.value; only return or return None is implemented',proof='source generator exhaustion value')


class Adapter:
    def owned(self,record):
        from .native_classes import shape
        plan=record.generator_plan
        # A suspended for-loop retains its evaluated iterable even when that
        # value has no Python local name (for example a global builtin cursor).
        # Its lifetime edges must participate before frame emission/validation.
        sources=[record.generator_model.records.get((plan.index,id(node.iter)))
                 for node in own_nodes(plan.node)if isinstance(node,ast.For)]
        return tuple(dict.fromkeys(shape(value)for value in (record.element,*plan.arguments.values(),
            *(value for values in plan.locals.values()for value in values),
            *(value for value in sources if value is not None))))

    def demand(self,registry,plan,node,record,environment,active):
        model=registry.model;callee=record.generator_plan
        model.activate_frame(plan,node,callee,environment)
        model.namespace.call_effects(plan,callee,environment)
        record.demands[(plan.index,id(node))]=True
        return record.element

    def may_call(self,registry,record,seen):return True

    def fields(self,emitter,record):
        return 'frame:Option<ClassSourceGeneratorFrame_'+str(record.generator_plan.index)+'>,running:bool'

    def pull(self,registry,emitter,node,value,active):
        from .native_classes import Expression,shape
        from .native_iterator_stop_policy import callback_call
        record=value.kind.record
        handle,state,frame,outcome=(emitter.fresh()for _ in range(4))
        error=emitter.at('Err::<(),String>("ValueError: generator already executing".to_owned())',node)
        resumed=callback_call(emitter,'class_source_generator_resume_'+str(record.generator_plan.index)+'(frame)',record.generator_plan,node)
        called='(||{Ok::<Option<'+emitter.rust_type(shape(record.element))+'>,NativeError>('+resumed+')})()'
        code=('{let '+handle+'=('+value.code+').clone();let mut '+frame+'={'
              'let mut '+state+'='+handle+'.borrow_mut();if '+state+'.running{'+error+';}'
              +state+'.running=true;'+state+'.frame.take()};'
              'let '+outcome+'=match '+frame+'.as_mut(){Some(frame)=>'+called+',None=>Ok(None)};'
              '{let mut '+state+'='+handle+'.borrow_mut();'+state+'.running=false;'
              'if matches!(&'+outcome+',Ok(Some(_)))||(matches!(&'+outcome+',Err(_))&&!'+emitter.iterator_callback_context+'){'+state+'.frame='+frame+';}}'
              +outcome+'.map_err(|error|{if class_exception_is_stop(&error){'+emitter.iterator_callback_context+'=false;class_exception_generator_stop(error,'+str(node.lineno)+','+emitter.location_code()+')}else{error}})?}')
        return Expression(code,shape(record.element))


ADAPTER=Adapter()


def guard_call(model,plan,node,environment):
    if not isinstance(node.func,ast.Attribute)or node.func.attr not in {'send','throw','close'}:return
    value=model.expression(plan,node.func.value,environment)
    from .native_classes import ClassUnsupported,shape
    from .native_types import alternatives
    if any(getattr(getattr(kind,'record',None),'operation',None)=='source_generator'for kind in alternatives(shape(value))):
        raise ClassUnsupported(node,'source generator '+node.func.attr+'() requires resumption injection/cleanup state that is not implemented; next() and ordinary iteration are supported',proof='source generator '+node.func.attr+' protocol')


class GeneratorBuilder(Builder):
    def __init__(self,emitter):
        self.emitter=emitter;self.plan=emitter.plan
        self.registry=SimpleNamespace(source=lambda plan:plan,omitted=lambda plan,node:
            emitter.model.reached_statements is not None and
            (plan.index,id(node))not in emitter.model.reached_statements)
        self.blocks=[Block()];self.current=0;self.temps={};self.extra={};self.overrides={};self.loops=[]
        self.arguments=[]
        self.control_loops={};self.branch_joins={};self.resume_states={0}
        slot=emitter.slot
        def framed_slot(instance,name,kind):return 'frame.'+slot(name,kind)
        emitter.slot=MethodType(framed_slot,emitter)
        from .native_classes import Expression,shape
        for index,name in enumerate(self.plan.runtime_parameters):
            kind=shape(self.plan.arguments[name]);stored=emitter.model.namespace.local_kind(self.plan,name)or kind
            place=emitter.slot(name,stored)[6:]
            self.arguments.append((place,emitter.coerce(Expression('class_argument_'+str(index),kind),stored,self.plan.node)))
        self.statements(self.plan.node.body)
        if self.current is not None:self.end(('stop',))

    def has_call(self,node):return False

    def condition(self,node):return self.emitter.condition(node).code

    def statement(self,node):
        from .native_classes import Expression,shape,domain,ClassUnsupported
        if isinstance(node,ast.Expr)and isinstance(node.value,ast.Yield):
            value=Expression('()','none')if node.value.value is None else self.emitter.expression(node.value.value)
            resume=self.new()
            self.end(('yield',self.emitter.coerce(value,shape(self.plan.source_generator.record.element),node),resume))
            self.resume_states.add(resume)
            self.current=resume;return
        if isinstance(node,ast.Return):self.end(('stop',));return
        if isinstance(node,(ast.If,ast.While)):
            entry=self.current
            super().statement(node)
            if isinstance(node,ast.If):self.branch_joins[entry]=self.current
            else:
                head=self.blocks[entry].end[1]
                branch=self.blocks[head].end
                self.control_loops[head]=(branch[2],branch[3],self.current,None)
            return
        if isinstance(node,ast.For):
            source=self.emitter.expression(node.iter)
            kind=self.emitter.model.iterators.source(self.plan,node.iter,self.emitter.model.records[self.plan.index,id(node.iter)],('generator_for',id(node)))
            cursor='cursor_'+str(len(self.extra));self.extra[cursor]=('Option<ClassIterator_'+str(kind.index)+'>','None')
            created=self.emitter.model.iterators.construct(self.emitter,node.iter,source,kind=kind)
            self.emit('frame.'+cursor+'=Some('+created.code+');')
            head,body,otherwise,after=self.new(),self.new(),self.new(),self.new();self.end(('jump',head));self.current=head
            pulled=self.emitter.model.iterators.pull(self.emitter,node.iter,Expression('frame.'+cursor+'.as_ref().unwrap().clone()',kind))
            item=self.emitter.fresh()
            self.emit('let '+item+'='+pulled.code+';')
            self.end(('for',item,self.emitter.assign(node.target,Expression('value',pulled.kind)),body,otherwise))
            self.loops.append((head,after));self.current=body;self.statements(node.body);self.loops.pop()
            if self.current is not None:self.end(('jump',head))
            self.current=otherwise;self.emit('frame.'+cursor+'=None;');self.statements(node.orelse)
            if self.current is not None:self.end(('jump',after))
            self.control_loops[head]=(body,otherwise,after,cursor)
            self.current=after;return
        if isinstance(node,(ast.With,ast.AsyncWith,ast.Try,ast.TryStar,ast.Raise,ast.Delete,ast.FunctionDef,ast.ClassDef)):
            reject_statement(node)
        return super().statement(node)

    def declarations(self):
        from .native_local_storage import rust_type
        fields={name:'Option<'+rust_type(self.emitter,binding,kind)+'>'for(binding,kind),name in self.emitter.slots.items()}
        fields.update((name,'Option<'+self.emitter.rust_type(kind)+'>')for name,kind in self.temps.items())
        fields.update((name,kind)for name,(kind,_)in self.extra.items())
        initial={name:'None'for name in fields};initial.update((name,value)for name,(_,value)in self.extra.items())
        initial.update((name,'Some('+value+')')for name,value in self.arguments)
        return fields,initial

    def body(self):
        def render(index,stop=None,active=()):
            for head in reversed(active):
                if index==head:return "continue 'generator_loop_"+str(head)+';'
                if index==self.control_loops[head][2]:return "break 'generator_loop_"+str(head)+';'
            if index==stop:return ''
            block=self.blocks[index];end=block.end or('stop',);tag=end[0]
            if index in self.control_loops:
                body,otherwise,after,cursor=self.control_loops[index]
                label='generator_loop_'+str(index)
                if tag=='branch':condition='if '+end[1]+'{'+render(body,None,active+(index,))+'}else{'+render(otherwise,after,active)+"break '"+label+';}'
                else:condition='if let Some(value)='+end[1]+'{'+end[2]+render(body,None,active+(index,))+'}else{'+render(otherwise,after,active)+"break '"+label+';}'
                clear='frame.'+cursor+'=None;'if cursor else''
                return "'"+label+':loop{'+''.join(block.code)+condition+'}'+clear+render(after,stop,active)
            prefix=''.join(block.code)
            if tag=='jump':tail=render(end[1],stop,active)
            elif tag=='branch':
                join=self.branch_joins.get(index,stop)
                tail='if '+end[1]+'{'+render(end[2],join,active)+'}else{'+render(end[3],join,active)+'}'
                if join is not None and join!=stop:tail+=render(join,stop,active)
            elif tag=='yield':tail='let yielded='+end[1]+';frame.pc='+str(end[2])+';return Ok(Some(yielded));'
            else:tail='return Ok(None);'
            return prefix+tail
        return 'match frame.pc{'+','.join(str(index)+'=>{'+render(index)+'}'for index in sorted(self.resume_states))+',_=>unreachable!("source generator position")} '


def generate(emitter):
    spec=getattr(emitter.plan,'source_generator',None)
    if spec is None:return None
    from .native_classes import ClassUnsupported,shape
    from .native_class_calls import entry_result
    from .native_class_binding_contexts import parameter
    model=emitter.model;plan=emitter.plan;record=spec.record;record.emitted=True
    if model.lexical.signature(plan):
        raise ClassUnsupported(plan.node,'source generator free/nonlocal cells require retaining their original lexical environment across suspension; that capture layout is not implemented',proof='source generator lexical environment capture')
    if not entry_result(model,plan):
        raise ClassUnsupported(plan.node,'source generator body calls require a resumable recursive call continuation; this generator slice supports bounded ordinary native calls',proof='source generator synchronous typed call region')
    from .native_types import ListType,TupleType,TupleSequenceType,NullableType,UnionType,EmptyType
    def closed(kind):
        if kind in {'int','bool','int_bool','none','float','str','bytes','range'}or isinstance(kind,EmptyType):return True
        if isinstance(kind,(ListType,TupleSequenceType)):return closed(kind.element)
        if isinstance(kind,TupleType):return all(closed(part)for part in kind.fields)
        if isinstance(kind,NullableType):return closed(kind.value)
        if isinstance(kind,UnionType):return all(closed(part)for part in kind.alternatives)
        return False
    for value in (record.element,*plan.arguments.values(),*(value for values in plan.locals.values()for value in values)):
        if not closed(shape(value)):
            raise ClassUnsupported(plan.node,'this source generator retains an object, callable or iterator whose suspended lifetime/ownership is not implemented; the current frame supports builtin scalar/list/tuple values',types=(('retained value',shape(value)),),proof='owned source generator frame payload')
    # All frame places remain owned across Rust calls and suspension. Never
    # retain temporary native borrows or an optimizer's stack-local Vec place.
    emitter.primitive_parameters={};emitter.readonly_owned_parameters={}
    emitter.owned_local_lists={};emitter.owned_matrices={};emitter.record_places={}
    builder=GeneratorBuilder(emitter);fields,initial=builder.declarations()
    context=parameter(model,plan)
    if context:
        fields['class_definition']='ClassClassRef';initial['class_definition']='class_defining_class.clone()'
    i=str(plan.index);name='ClassSourceGeneratorFrame_'+i
    layout='struct '+name+'{scope:ClassScope,pc:usize,'+','.join(key+':'+kind for key,kind in fields.items())+'}'
    params=','.join('class_argument_'+str(index)+':'+emitter.rust_type(shape(plan.arguments[key]))for index,key in enumerate(plan.runtime_parameters))
    signature='class_scope:ClassScope'+context+(','+params if params else'')
    factory='fn '+emitter.function_name(plan)+'('+signature+')->ClassResult<ClassIterator_'+str(record.index)+'>{Ok(Rc::new(RefCell::new(ClassIteratorState_'+str(record.index)+'{running:false,frame:Some('+name+'{scope:class_scope,pc:0,'+','.join(key+':'+value for key,value in initial.items())+'})}))) }'
    body=builder.body()
    captured='let class_defining_class=&frame.class_definition;'if context else''
    resume='fn class_source_generator_resume_'+i+'(frame:&mut '+name+')->ClassResult<Option<'+emitter.rust_type(shape(record.element))+'>>{let class_scope=frame.scope.clone();'+captured+body+'}'
    return layout+'\n'+factory+'\n'+resume
